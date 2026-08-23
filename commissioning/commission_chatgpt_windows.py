#!/usr/bin/env python3
"""Opt-in live commissioning harness for ChatGPT Desktop on Windows 11.

WARNING: this controls Project `les-cloches` in the real ChatGPT Desktop
window. Do not use the desktop while it runs. A run is evidence only when its
persisted report is complete.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from _windows_common import run_windows_commissioning
from les_cloches.apps.windows.chatgpt import WindowsChatGPTAdapter


PROJECT = "les-cloches"


class ProjectChatGPTAdapter(WindowsChatGPTAdapter):
    def open_fresh_conversation(self, deadline: float):
        return super().open_project_fresh_conversation(PROJECT, deadline)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("commissioning/WINDOWS_CHATGPT_COMMISSIONING.json"),
    )
    return parser


def main(argv: "list[str] | None" = None) -> int:
    args = _parser().parse_args(argv)
    return run_windows_commissioning(
        adapter_factory=ProjectChatGPTAdapter,
        identity=f"Project {PROJECT} / New chat",
        sentinel_prefix="WINDOWS_CHATGPT_PONG",
        timeout=args.timeout,
        output=args.output,
    )


if __name__ == "__main__":
    sys.exit(main())
