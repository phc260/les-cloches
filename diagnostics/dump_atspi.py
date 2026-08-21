#!/usr/bin/env python3
"""Dump an application's AT-SPI subtree without assuming node labels or roles.

Generalizes the two donor scripts `dump_atspi.py` (Claude, full text) and
`probe_chatgpt_atspi.py` (ChatGPT, redacted text) into one tool: pass
`--application` to select the target and `--redact-text` to omit accessible
text values (useful when a conversation may contain sensitive content).
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi  # noqa: E402


def safe(call: Any, default: Any = None) -> Any:
    try:
        return call()
    except Exception:
        return default


def node_text(node: Atspi.Accessible, limit: int, redact: bool) -> "str | None":
    text_iface = safe(node.get_text_iface)
    if text_iface is None:
        return None
    count = safe(text_iface.get_character_count, 0)
    if not count:
        return ""
    if redact:
        return f"<{count} chars redacted>"
    value = safe(lambda: text_iface.get_text(0, min(count, limit)), "")
    if count > limit:
        value += f"… <{count - limit} more chars>"
    return value


def states(node: Atspi.Accessible) -> "list[str]":
    state_set = safe(node.get_state_set)
    if state_set is None:
        return []
    names: "list[str]" = []
    for value in range(int(Atspi.StateType.LAST_DEFINED) + 1):
        state = Atspi.StateType(value)
        if safe(lambda: state_set.contains(state), False):
            names.append(state.value_nick)
    return names


def actions(node: Atspi.Accessible) -> "list[str]":
    iface = safe(node.get_action_iface)
    if iface is None:
        return []
    return [safe(lambda i=i: iface.get_action_name(i), "") for i in range(safe(iface.get_n_actions, 0))]


def dump(node: Atspi.Accessible, depth: int, max_depth: int, text_limit: int, redact: bool) -> None:
    indent = "  " * depth
    role = safe(node.get_role_name, "<unknown>")
    name = safe(node.get_name, "") or ""
    description = safe(node.get_description, "") or ""
    child_count = safe(node.get_child_count, 0)
    bits = [f"{indent}- role={role!r}", f"name={name!r}", f"states={states(node)!r}"]
    if description:
        bits.append(f"description={description!r}")
    node_actions = actions(node)
    if node_actions:
        bits.append(f"actions={node_actions!r}")
    text = node_text(node, text_limit, redact)
    if text is not None:
        bits.append(f"text={text!r}")
    bits.append(f"children={child_count}")
    print(" ".join(bits), flush=True)
    if depth >= max_depth:
        return
    for index in range(child_count):
        child = safe(lambda index=index: node.get_child_at_index(index))
        if child is not None:
            dump(child, depth + 1, max_depth, text_limit, redact)


def find_app(name_fragment: str) -> Atspi.Accessible:
    desktop = Atspi.get_desktop(0)
    matches = []
    for index in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(index)
        name = safe(app.get_name, "") or ""
        if name_fragment.casefold() in name.casefold():
            matches.append(app)
    if not matches:
        available = [safe(desktop.get_child_at_index(i).get_name, "") for i in range(desktop.get_child_count())]
        raise RuntimeError(f"no application matching {name_fragment!r}; available: {available}")
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--application", default="claude-desktop", help="name fragment, e.g. claude-desktop or Codex")
    parser.add_argument("--max-depth", type=int, default=20)
    parser.add_argument("--text-limit", type=int, default=2000)
    parser.add_argument("--redact-text", action="store_true", help="omit accessible text values (character counts only)")
    args = parser.parse_args()
    try:
        dump(find_app(args.application), 0, args.max_depth, args.text_limit, args.redact_text)
    except Exception as exc:
        print(f"AT-SPI diagnostic failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
