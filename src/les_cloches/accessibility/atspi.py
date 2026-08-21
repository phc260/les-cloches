"""Generic AT-SPI plumbing: tree traversal and node introspection.

Nothing here knows what a "conversation," a "turn," or a "Send button" is.
It only knows how to walk an AT-SPI accessibility tree defensively and read
role/name/text/action information off a node. Application semantics belong
in `les_cloches.apps`, not here.
"""

from __future__ import annotations

from typing import Callable, Iterator, TypeVar

from ..core.errors import LesClochesError

T = TypeVar("T")


def require_atspi():
    """Import and return the AT-SPI GI binding, or raise a clear error."""
    try:
        import gi

        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi
    except (ImportError, ValueError) as exc:
        raise LesClochesError("AT-SPI 2 GI bindings are required") from exc
    return Atspi


def safe(call: Callable[[], T], default: T | None = None) -> "T | None":
    """Call an AT-SPI accessor, swallowing the DBus/proxy errors it can raise.

    AT-SPI proxy objects raise on stale or unreachable nodes as a matter of
    course (a node can disappear mid-traversal as the renderer updates), so
    every accessor in this module goes through this helper instead of
    catching exceptions ad hoc at each call site.
    """
    try:
        return call()
    except Exception:
        return default


def walk(root, *, node_limit: int = 20000) -> Iterator:
    """Depth-first walk of an AT-SPI subtree, bounded against cyclic trees."""
    stack = [root]
    visited = 0
    while stack:
        node = stack.pop()
        visited += 1
        if visited > node_limit:
            raise LesClochesError(f"accessibility tree exceeded {node_limit} nodes")
        yield node
        count = safe(node.get_child_count, 0) or 0
        children = [safe(lambda i=i: node.get_child_at_index(i)) for i in range(count)]
        stack.extend(child for child in reversed(children) if child is not None)


def role(node) -> str:
    return safe(node.get_role_name, "") or ""


def name(node) -> str:
    return safe(node.get_name, "") or ""


def text(node) -> "str | None":
    iface = safe(node.get_text_iface)
    if iface is None:
        return None
    count = safe(iface.get_character_count, 0) or 0
    return safe(lambda: iface.get_text(0, count), "")


def attributes(node) -> dict:
    return safe(node.get_attributes, {}) or {}


def is_editable_entry(atspi, node) -> bool:
    return role(node) == "entry" and bool(
        safe(lambda: node.get_state_set().contains(atspi.StateType.EDITABLE), False)
    )


def find_all(root, predicate: Callable[[object], bool], *, node_limit: int = 20000) -> list:
    if root is None:
        return []
    return [node for node in walk(root, node_limit=node_limit) if predicate(node)]


def press_named_action(node, action_names: "set[str]") -> bool:
    iface = safe(node.get_action_iface)
    if iface is None:
        return False
    for index in range(safe(iface.get_n_actions, 0) or 0):
        candidate = safe(lambda index=index: iface.get_action_name(index), "")
        if candidate in action_names:
            return bool(safe(lambda index=index: iface.do_action(index), False))
    return False


def application_by_name(atspi, predicate: Callable[[str], bool]):
    """Return the first top-level desktop application whose name matches."""
    desktop = atspi.get_desktop(0)
    for index in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(index)
        candidate_name = name(app)
        if predicate(candidate_name):
            return app
    return None
