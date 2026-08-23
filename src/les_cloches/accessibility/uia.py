"""Generic Microsoft UI Automation plumbing for Windows desktop controls."""

from __future__ import annotations

from typing import Callable, Iterator

from ..core.errors import LesClochesError


def require_uia():
    """Import pywinauto's UIA backend or raise a deterministic error."""
    try:
        from pywinauto import Desktop
        from pywinauto.controls.uiawrapper import UIAWrapper
    except ImportError as exc:
        raise LesClochesError("pywinauto is required for Windows UI Automation") from exc
    return Desktop, UIAWrapper


def safe(call: Callable, default=None):
    try:
        return call()
    except Exception:
        return default


def walk(root, *, node_limit: int = 20_000) -> Iterator:
    """Depth-first UIA control-view traversal bounded against provider bugs."""
    stack = [root]
    visited = 0
    while stack:
        node = stack.pop()
        visited += 1
        if visited > node_limit:
            raise LesClochesError(f"accessibility tree exceeded {node_limit} nodes")
        yield node
        children = safe(node.children, []) or []
        stack.extend(reversed(children))


def name(node) -> str:
    return safe(lambda: node.element_info.name, "") or ""


def control_type(node) -> str:
    return safe(lambda: node.element_info.control_type, "") or ""


def class_name(node) -> str:
    return safe(lambda: node.element_info.class_name, "") or ""


def automation_id(node) -> str:
    return safe(lambda: node.element_info.automation_id, "") or ""


def process_id(node) -> "int | None":
    value = safe(lambda: node.element_info.process_id)
    return int(value) if value else None


def find_window(title: str):
    """Return one visible top-level window with the exact accessible title."""
    Desktop, _ = require_uia()
    matches = [window for window in Desktop(backend="uia").windows() if name(window) == title]
    if len(matches) > 1:
        raise LesClochesError(f"multiple visible UI Automation windows are named {title!r}")
    return matches[0] if matches else None


def find_all(root, predicate: Callable[[object], bool], *, node_limit: int = 20_000) -> list:
    if root is None:
        return []
    return [node for node in walk(root, node_limit=node_limit) if predicate(node)]


def invoke(node) -> bool:
    """Invoke a semantic UIA control without coordinate input."""
    try:
        node.invoke()
        return True
    except Exception:
        return False


def focus(node) -> bool:
    try:
        node.set_focus()
        return bool(safe(node.has_keyboard_focus, False))
    except Exception:
        return False


def editable_text(node) -> str:
    """Read the exact string exposed by an editor's UIA text/value pattern."""
    try:
        return node.iface_text.DocumentRange.GetText(-1)
    except Exception:
        pass
    try:
        return node.iface_value.CurrentValue
    except Exception:
        return ""


def is_editable(node) -> bool:
    if control_type(node) != "Edit":
        return False
    try:
        return not bool(node.iface_value.CurrentIsReadOnly)
    except Exception:
        return bool(safe(node.is_keyboard_focusable, False))


def parent(node):
    return safe(node.parent)
