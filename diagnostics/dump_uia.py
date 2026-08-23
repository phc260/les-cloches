#!/usr/bin/env python3
"""Dump a visible Windows application's Microsoft UI Automation tree.

This diagnostic reads semantic accessibility properties only.  It does not
capture screenshots, use coordinates, or connect to a browser debugging
interface.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", required=True, help="case-insensitive regex for the top-level window name")
    parser.add_argument("--max-depth", type=int, default=30)
    parser.add_argument("--node-limit", type=int, default=20_000)
    parser.add_argument("--redact-text", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="required output file; full trees are never streamed into the inspected desktop app",
    )
    return parser


def _escaped(value: str) -> str:
    return value.encode("unicode_escape", errors="backslashreplace").decode("ascii")


def main() -> int:
    args = _parser().parse_args()
    if args.max_depth < 0 or args.node_limit <= 0:
        raise SystemExit("--max-depth must be non-negative and --node-limit must be positive")

    try:
        from pywinauto import Desktop
    except ImportError as exc:
        raise SystemExit("pywinauto is required on Windows") from exc

    pattern = re.compile(args.window, re.IGNORECASE)
    windows = [window for window in Desktop(backend="uia").windows() if pattern.search(window.window_text() or "")]
    if not windows:
        raise SystemExit(f"no visible UIA window matched {args.window!r}")
    if len(windows) > 1:
        matches = ", ".join(repr(window.window_text()) for window in windows)
        raise SystemExit(f"multiple visible UIA windows matched {args.window!r}: {matches}")

    stack = [(windows[0].element_info, 0)]
    visited = 0
    lines = []
    while stack:
        node, depth = stack.pop()
        visited += 1
        if visited > args.node_limit:
            raise SystemExit(f"UIA tree exceeded {args.node_limit} nodes")
        name = node.name or ""
        if args.redact_text and node.control_type in {"Text", "Document", "Edit"}:
            name = f"<redacted:{len(name)}>" if name else ""
        lines.append(
            f"{'  ' * depth}{node.control_type or '?'} "
            f"name={_escaped(name)!r} automation_id={_escaped(node.automation_id or '')!r} "
            f"class={_escaped(node.class_name or '')!r} pid={node.process_id} handle={node.handle}"
        )
        if depth >= args.max_depth:
            continue
        children = node.children()
        stack.extend((child, depth + 1) for child in reversed(children))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(f"wrote {visited} UIA nodes to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
