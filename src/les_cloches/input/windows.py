"""Windows prompt input using exact UIA writes or clipboard-backed SendInput."""

from __future__ import annotations

import time
from typing import Callable

from ..accessibility.uia import focus
from ..core.errors import LesClochesError, LesClochesTimeout


class WindowsClipboardInput:
    name = "windows-uia-clipboard-sendinput"

    @staticmethod
    def _set_semantic_value(editor, text: str) -> bool:
        try:
            pattern = editor.iface_value
            if bool(pattern.CurrentIsReadOnly):
                return False
            pattern.SetValue(text)
            return True
        except Exception:
            return False

    @staticmethod
    def _wait_for_exact_readback(deadline: float, verify: Callable[[], bool]) -> bool:
        while time.monotonic() < deadline:
            if verify():
                return True
            time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))
        return False

    @staticmethod
    def _open_clipboard(win32clipboard, deadline: float) -> None:
        while time.monotonic() < deadline:
            try:
                win32clipboard.OpenClipboard()
                return
            except Exception:
                time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))
        raise LesClochesTimeout("timed out acquiring the Windows clipboard")

    def replace(self, editor, text: str, deadline: float, verify: Callable[[], bool]) -> None:
        semantic_deadline = min(deadline, time.monotonic() + 2.0)
        if self._set_semantic_value(editor, text) and self._wait_for_exact_readback(
            semantic_deadline, verify
        ):
            return

        try:
            import win32clipboard
            from pywinauto.keyboard import send_keys
        except ImportError as exc:
            raise LesClochesError("pywin32 and pywinauto are required for Windows input") from exc

        self._open_clipboard(win32clipboard, deadline)
        try:
            previous = None
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                previous = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
        finally:
            win32clipboard.CloseClipboard()

        try:
            if not focus(editor):
                raise LesClochesError("UI Automation could not focus the semantic prompt editor")
            send_keys("^a^v", pause=0.01)
            insertion_deadline = min(deadline, time.monotonic() + 5.0)
            self._wait_for_exact_readback(insertion_deadline, verify)
        finally:
            self._open_clipboard(win32clipboard, deadline)
            try:
                win32clipboard.EmptyClipboard()
                if previous is not None:
                    win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, previous)
            finally:
                win32clipboard.CloseClipboard()
