#!/usr/bin/env python3
"""Find when Claude converts inline pasted text into a PASTED attachment."""

from __future__ import annotations

import argparse
import time

from les_cloches.accessibility.atspi import name, role
from les_cloches.apps.linux.claude import ClaudeAdapter
from les_cloches.input.x11 import X11ClipboardInput


VOCABULARY = ("amber", "bridge", "candle", "delta", "ember")


def prompt_with_words(word_count: int) -> str:
    return " ".join(VOCABULARY[index % len(VOCABULARY)] for index in range(word_count))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--words",
        type=int,
        nargs="+",
        default=(250, 500, 1_000, 2_000, 4_000, 8_000),
    )
    parser.add_argument("--case-timeout", type=float, default=45.0)
    args = parser.parse_args()

    adapter = ClaudeAdapter(poll_interval=0.2)
    input_backend = X11ClipboardInput()
    print(adapter.health_snapshot())
    for word_count in args.words:
        deadline = time.monotonic() + args.case_timeout
        prompt = prompt_with_words(word_count)
        editor = adapter.open_fresh_conversation(deadline)
        editor = adapter.insert_prompt(input_backend, editor, prompt, deadline)
        exact = adapter.editor_matches(editor, prompt)
        attachments = adapter._find_all(
            lambda node: role(node) == "push button"
            and name(node).startswith("Pasted Text")
        )
        print(
            f"words={word_count} characters={len(prompt)} "
            f"exact_inline={exact} pasted_attachments={len(attachments)}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
