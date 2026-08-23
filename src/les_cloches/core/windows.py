"""Windows process discovery and packaged-desktop application launch helpers."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from .errors import LesClochesError, LesClochesTimeout, LesClochesUnavailable


def _process_image(process_id: int) -> "str | None":
    try:
        import win32api
        import win32con
        import win32process

        access = getattr(win32con, "PROCESS_QUERY_LIMITED_INFORMATION", 0x1000) | win32con.PROCESS_VM_READ
        handle = win32api.OpenProcess(access, False, process_id)
        try:
            return win32process.GetModuleFileNameEx(handle, 0)
        finally:
            handle.Close()
    except Exception:
        return None


def process_ids_for_executable(executable_name: str) -> list[int]:
    try:
        import win32process
    except ImportError as exc:
        raise LesClochesError("pywin32 is required for Windows process discovery") from exc
    target = executable_name.casefold()
    matches = []
    for process_id in win32process.EnumProcesses():
        image = _process_image(process_id)
        if image and Path(image).name.casefold() == target:
            matches.append(int(process_id))
    return matches


def terminate_process_tree(process_id: int, deadline: float, label: str, *, force: bool) -> None:
    command = ["taskkill", "/PID", str(process_id), "/T"]
    if force:
        command.append("/F")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise LesClochesTimeout(f"deadline expired while stopping {label}")
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=remaining)
    except subprocess.TimeoutExpired as exc:
        if not force:
            return
        raise LesClochesTimeout(f"timed out stopping {label} process tree {process_id}") from exc
    if force and result.returncode and _process_image(process_id) is not None:
        raise LesClochesUnavailable(
            f"could not stop {label} process tree {process_id}: {(result.stderr or result.stdout).strip()}"
        )


def wait_for_process_exit(process_id: int, deadline: float, poll_interval: float = 0.05) -> bool:
    while time.monotonic() < deadline:
        if _process_image(process_id) is None:
            return True
        time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))
    return _process_image(process_id) is None


def launch_packaged_with_accessibility(
    *, aumid: str, window_title: str, executable_name: str, deadline: float
) -> subprocess.Popen:
    """Bootstrap an MSIX app to discover its versioned executable, then relaunch
    that bridge-owned process with Chromium renderer accessibility forced on."""
    from ..accessibility.uia import find_window, process_id

    subprocess.Popen(
        ["explorer.exe", f"shell:AppsFolder\\{aumid}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    window = None
    while time.monotonic() < deadline:
        window = find_window(window_title)
        if window is not None:
            break
        time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
    if window is None:
        raise LesClochesTimeout(f"timed out launching {window_title}")
    bootstrap_pid = process_id(window)
    image = _process_image(bootstrap_pid) if bootstrap_pid else None
    if not bootstrap_pid or not image or Path(image).name.casefold() != executable_name.casefold():
        raise LesClochesUnavailable(
            f"could not resolve {window_title}'s packaged executable from its visible UIA window"
        )
    terminate_process_tree(bootstrap_pid, deadline, window_title, force=True)
    if not wait_for_process_exit(bootstrap_pid, deadline):
        raise LesClochesUnavailable(
            f"bridge-launched {window_title} bootstrap process {bootstrap_pid} remained alive"
        )
    return subprocess.Popen(
        [image, "--force-renderer-accessibility"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
