#!/usr/bin/env python3
"""Bounded, non-streaming accessibility probe for AT-SPI and Windows UIA.

The traversal runs in a child process so the parent can enforce a wall-clock
timeout even when an accessibility provider blocks inside a child-enumeration
call.  The child returns counts and process metadata only: it never returns
node names, editor text, or conversation content.  The parent persists one
small JSON record after traversal finishes or is terminated.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import platform
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


SCHEMA = "les-cloches-accessibility-probe-v1"


class NodeLimitReached(RuntimeError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("atspi", "uia"), required=True)
    parser.add_argument("--target", required=True, help="case-insensitive regex for the top-level application name")
    parser.add_argument("--max-depth", type=int, default=22)
    parser.add_argument("--node-limit", type=int, default=2_000)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def summarize_tree(
    root: Any,
    *,
    children: Callable[[Any], list[Any]],
    kind: Callable[[Any], str],
    process_id: Callable[[Any], int | None],
    max_depth: int,
    node_limit: int,
) -> dict[str, Any]:
    """Summarize one already-discovered tree without reading node text."""
    stack = [(root, 0)]
    visited = 0
    deepest = 0
    kinds: Counter[str] = Counter()
    while stack:
        node, depth = stack.pop()
        visited += 1
        if visited > node_limit:
            raise NodeLimitReached(f"accessibility tree exceeded {node_limit} nodes")
        deepest = max(deepest, depth)
        kinds[kind(node) or "<unknown>"] += 1
        if depth >= max_depth:
            continue
        descendants = children(node)
        stack.extend((child, depth + 1) for child in reversed(descendants))
    return {
        "node_count": visited,
        "max_depth_observed": deepest,
        "kinds": dict(sorted(kinds.items())),
        "root_process_id": process_id(root),
    }


def _uia_root(target: str):
    from les_cloches.accessibility.uia import name, require_uia

    Desktop, _ = require_uia()
    pattern = re.compile(target, re.IGNORECASE)
    matches = [window for window in Desktop(backend="uia").windows() if pattern.search(name(window))]
    return matches


def _atspi_root(target: str):
    from les_cloches.accessibility.atspi import name, require_atspi

    atspi = require_atspi()
    desktop = atspi.get_desktop(0)
    pattern = re.compile(target, re.IGNORECASE)
    matches = []
    for index in range(desktop.get_child_count()):
        application = desktop.get_child_at_index(index)
        if pattern.search(name(application)):
            matches.append(application)
    return matches


def _collect_uia(payload: dict[str, Any]) -> dict[str, Any]:
    from les_cloches.accessibility.uia import control_type, process_id, safe

    matches = _uia_root(payload["target"])
    if not matches:
        return {"status": "target_not_found"}
    if len(matches) > 1:
        return {"status": "ambiguous_target", "match_count": len(matches)}
    result = summarize_tree(
        matches[0],
        children=lambda node: safe(node.children, []) or [],
        kind=control_type,
        process_id=process_id,
        max_depth=payload["max_depth"],
        node_limit=payload["node_limit"],
    )
    return {"status": "passed", **result}


def _collect_atspi(payload: dict[str, Any]) -> dict[str, Any]:
    from les_cloches.accessibility.atspi import role, safe

    matches = _atspi_root(payload["target"])
    if not matches:
        return {"status": "target_not_found"}
    if len(matches) > 1:
        return {"status": "ambiguous_target", "match_count": len(matches)}

    def children(node):
        count = safe(node.get_child_count, 0) or 0
        values = [safe(lambda index=index: node.get_child_at_index(index)) for index in range(count)]
        return [value for value in values if value is not None]

    def process_id(node):
        value = safe(node.get_process_id)
        return int(value) if value else None

    result = summarize_tree(
        matches[0],
        children=children,
        kind=role,
        process_id=process_id,
        max_depth=payload["max_depth"],
        node_limit=payload["node_limit"],
    )
    return {"status": "passed", **result}


def _worker(payload: dict[str, Any], connection) -> None:
    try:
        if payload["backend"] == "atspi":
            result = _collect_atspi(payload)
        else:
            result = _collect_uia(payload)
    except NodeLimitReached as exc:
        result = {"status": "node_limit_reached", "error": str(exc)}
    except BaseException as exc:
        result = {"status": "error", "error_type": type(exc).__name__, "error": str(exc)}
    try:
        connection.send(result)
    finally:
        connection.close()


def run_bounded(payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_worker, args=(payload, sender), daemon=True)
    started = time.monotonic()
    process.start()
    sender.close()
    try:
        if receiver.poll(timeout):
            try:
                result = receiver.recv()
            except EOFError:
                result = {"status": "worker_exited_without_result"}
        else:
            result = {"status": "timed_out"}
    finally:
        receiver.close()
        process.join(timeout=1.0)
        if process.is_alive():
            process.terminate()
            process.join(timeout=1.0)
        if process.is_alive():
            process.kill()
            process.join(timeout=1.0)
    return {**result, "elapsed_seconds": round(time.monotonic() - started, 3)}


def _write_json(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    args = _parser().parse_args()
    if args.max_depth < 0 or args.node_limit <= 0 or args.timeout <= 0:
        raise SystemExit("max depth must be non-negative; node limit and timeout must be positive")
    payload = {
        "backend": args.backend,
        "target": args.target,
        "max_depth": args.max_depth,
        "node_limit": args.node_limit,
    }
    result = {
        "schema": SCHEMA,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        **payload,
        **run_bounded(payload, args.timeout),
    }
    _write_json(args.output, result)
    print(json.dumps({"status": result["status"], "output": str(args.output)}))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
