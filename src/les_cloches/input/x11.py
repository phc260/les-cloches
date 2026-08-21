"""Commissioned X11 prompt input: process-owned window activation + clipboard/XTEST.

This is the sole supported input backend for v0.1 (see ARCHITECTURE.md — native
Wayland cannot provide the required X11/XTEST mechanism). It never uses
coordinates. It locates the X11 window that AT-SPI process lineage says owns
the semantically discovered editor, raises and focuses exactly that window, then pastes
through the clipboard and XTEST Ctrl+A / Ctrl+V. AT-SPI FOCUSED state does
not guarantee the owning top-level X11 window is active, so this backend
always establishes X11-level window focus itself before synthesizing input.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import time
from pathlib import Path
from typing import Callable

from ..core.errors import LesClochesError, LesClochesTimeout


class X11ClipboardInput:
    name = "x11-clipboard-xtest"

    @staticmethod
    def _drain_context(context, deadline: float) -> bool:
        """Drain ready GLib work without crossing the transaction deadline."""
        while time.monotonic() < deadline and context.pending():
            context.iteration(False)
        return not context.pending()

    @staticmethod
    def _semantic_process_id(editor) -> "int | None":
        node = editor
        for _ in range(40):
            try:
                candidate = node.get_process_id()
            except Exception:
                candidate = None
            if candidate:
                return int(candidate)
            try:
                node = node.get_parent()
            except Exception:
                break
            if node is None:
                break
        return None

    @staticmethod
    def _process_ancestors(process_id: int) -> "list[int]":
        result = []
        current = process_id
        for _ in range(20):
            if current <= 1 or current in result:
                break
            result.append(current)
            try:
                status = Path(f"/proc/{current}/status").read_text(encoding="utf-8", errors="replace")
                parent_line = next(line for line in status.splitlines() if line.startswith("PPid:"))
                current = int(parent_line.split(":", 1)[1].strip())
            except (OSError, StopIteration, ValueError):
                break
        return result

    @staticmethod
    def _property_values(x11, display_ptr, window: int, atom: int) -> "list[int]":
        actual_type = ctypes.c_ulong()
        actual_format = ctypes.c_int()
        item_count = ctypes.c_ulong()
        bytes_after = ctypes.c_ulong()
        data = ctypes.POINTER(ctypes.c_ubyte)()
        status = x11.XGetWindowProperty(
            display_ptr, window, atom, 0, 4096, False, 0,
            ctypes.byref(actual_type), ctypes.byref(actual_format),
            ctypes.byref(item_count), ctypes.byref(bytes_after), ctypes.byref(data),
        )
        if status != 0 or not data:
            return []
        try:
            if actual_format.value != 32:
                return []
            values = ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))
            return [int(values[index]) for index in range(item_count.value)]
        finally:
            x11.XFree(data)

    def _activate_semantic_window(self, x11, display_ptr, editor) -> None:
        process_id = self._semantic_process_id(editor)
        if process_id is None:
            raise LesClochesError("AT-SPI editor did not expose an owning process ID")
        process_ids = set(self._process_ancestors(process_id))
        root = x11.XDefaultRootWindow(display_ptr)
        clients_atom = x11.XInternAtom(display_ptr, b"_NET_CLIENT_LIST", False)
        pid_atom = x11.XInternAtom(display_ptr, b"_NET_WM_PID", False)
        target = None
        for window in self._property_values(x11, display_ptr, root, clients_atom):
            values = self._property_values(x11, display_ptr, window, pid_atom)
            if values and values[0] in process_ids:
                target = window
                break
        if target is None:
            raise LesClochesError(
                f"no X11 client window belongs to AT-SPI process lineage {sorted(process_ids)!r}"
            )
        x11.XRaiseWindow(display_ptr, target)
        x11.XSetInputFocus(display_ptr, target, 2, 0)
        x11.XSync(display_ptr, False)
        try:
            component = editor.get_component_iface()
            if component is not None:
                component.grab_focus()
        except Exception:
            pass
        time.sleep(0.05)

    def replace(self, editor, text: str, deadline: float, verify: Callable[[], bool]) -> None:
        try:
            import gi

            gi.require_version("Gdk", "4.0")
            gi.require_version("Gtk", "4.0")
            from gi.repository import Gdk, GLib, GObject, Gtk
        except (ImportError, ValueError) as exc:
            raise LesClochesError("GDK 4 is required for safe clipboard input") from exc

        Gtk.init()
        display = Gdk.Display.get_default()
        if display is None:
            raise LesClochesError("GDK could not open the X11 display")
        clipboard = display.get_clipboard()
        previous_result = []

        def read_done(source, result, _data):
            try:
                previous_result.append(source.read_text_finish(result))
            except Exception:
                previous_result.append(None)

        clipboard.read_text_async(None, read_done, None)
        context = GLib.MainContext.default()
        while not previous_result and time.monotonic() < deadline:
            context.iteration(False)
            time.sleep(min(0.01, max(0, deadline - time.monotonic())))
        if not previous_result:
            raise LesClochesTimeout("timed out reading clipboard before prompt insertion")
        previous = previous_result[0]

        def set_clipboard(value):
            holder = GObject.Value()
            holder.init(str)
            holder.set_string(value)
            clipboard.set_content(Gdk.ContentProvider.new_for_value(holder))

        set_clipboard(text)
        # `set_content()` establishes this process as the clipboard owner
        # synchronously.  Do not pump the default GLib context here: on a
        # cold Electron session GDK can report unrelated work as pending and
        # a single `iteration(False)` may enter a callback which does not
        # return before the transaction deadline.  Clipboard transfer work
        # starts only after Ctrl+V below and is pumped by the bounded verify
        # loop.

        x11_path = ctypes.util.find_library("X11")
        xtst_path = ctypes.util.find_library("Xtst")
        if not x11_path or not xtst_path:
            raise LesClochesError("libX11 and libXtst are required for X11 input")
        x11 = ctypes.cdll.LoadLibrary(x11_path)
        xtst = ctypes.cdll.LoadLibrary(xtst_path)
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XStringToKeysym.restype = ctypes.c_ulong
        x11.XStringToKeysym.argtypes = [ctypes.c_char_p]
        x11.XKeysymToKeycode.restype = ctypes.c_uint
        x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        x11.XFlush.argtypes = [ctypes.c_void_p]
        x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        x11.XDefaultRootWindow.restype = ctypes.c_ulong
        x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        x11.XInternAtom.restype = ctypes.c_ulong
        x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        x11.XGetWindowProperty.restype = ctypes.c_int
        x11.XGetWindowProperty.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long, ctypes.c_long,
            ctypes.c_int, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
        ]
        x11.XFree.argtypes = [ctypes.c_void_p]
        x11.XRaiseWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        x11.XSetInputFocus.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
        display_ptr = x11.XOpenDisplay(None)
        if not display_ptr:
            raise LesClochesError("could not open X display for clipboard paste")
        try:
            self._activate_semantic_window(x11, display_ptr, editor)

            def code(key_name):
                return x11.XKeysymToKeycode(display_ptr, x11.XStringToKeysym(key_name.encode()))

            control, a_key, v_key = code("Control_L"), code("a"), code("v")
            for key in (control, a_key):
                xtst.XTestFakeKeyEvent(display_ptr, key, True, 0)
            for key in (a_key, control):
                xtst.XTestFakeKeyEvent(display_ptr, key, False, 0)
            for key in (control, v_key):
                xtst.XTestFakeKeyEvent(display_ptr, key, True, 0)
            for key in (v_key, control):
                xtst.XTestFakeKeyEvent(display_ptr, key, False, 0)
            x11.XFlush(display_ptr)
            x11.XSync(display_ptr, 0)
        finally:
            x11.XCloseDisplay(display_ptr)

        end = min(deadline, time.monotonic() + 5.0)
        while time.monotonic() < end and not verify():
            self._drain_context(context, end)
            time.sleep(0.02)
        set_clipboard(previous or "")
        self._drain_context(context, deadline)
