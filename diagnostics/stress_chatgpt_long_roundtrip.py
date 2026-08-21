#!/usr/bin/env python3
"""Send long source context and validate a long desktop-chat response."""

from __future__ import annotations

import argparse
import hashlib
import time
from pathlib import Path

from les_cloches import ChatGPT, Claude


BEGIN_SENTINEL = "LES_CLOCHES_LONG_ANSWER_BEGIN"
END_SENTINEL = "LES_CLOCHES_LONG_ANSWER_END"


def gutenberg_body(text: str) -> str:
    """Remove Project Gutenberg's machine-readable wrapper when present."""
    start_marker = "*** START OF THE PROJECT GUTENBERG EBOOK"
    end_marker = "*** END OF THE PROJECT GUTENBERG EBOOK"
    start = text.find(start_marker)
    if start >= 0:
        start = text.find("\n", start)
        text = text[start + 1 :]
    end = text.find(end_marker)
    if end >= 0:
        text = text[:end]
    return text.strip()


def build_prompt(
    source: str,
    context_words: int,
    requested_response_words: int,
    task: str = "debate",
) -> str:
    words = gutenberg_body(source).split()
    if len(words) < context_words:
        raise ValueError(
            f"source contains only {len(words)} usable words; {context_words} requested"
        )
    context = " ".join(words[:context_words])
    if task == "debate":
        assignment = (
            "Write a rigorous analytical essay based only on the supplied public debate "
            "transcript. Reconstruct each speaker's principal arguments, premises, evidence, "
            "definitions, attacks, rebuttals, and defenses. Steelman both sides before "
            "evaluating them. Identify agreements, direct clashes, unanswered objections, "
            "logical gaps, historical assumptions, and rhetorical techniques. Compare how "
            "each speaker frames the burden of proof and responds to the strongest opposing "
            "case. Organize the answer into at least ten titled sections, use precise textual "
            "references, include a substantial section presenting the best defense of each "
            "side, and finish with a balanced judgment rather than a plot-like summary."
        )
    elif task == "debate_exchange":
        assignment = (
            "Create a rigorous adversarial casebook based only on the supplied public "
            "debate transcript. Part I must map each speaker's claims, premises, evidence, "
            "definitions, and burdens of proof. Parts II and III must present the strongest "
            "possible opening brief for each side. Part IV must contain at least twelve "
            "paired cross-examination questions and substantive answers grounded in the "
            "transcript. Parts V and VI must give each side a detailed rebuttal and then a "
            "defense against the opponent's strongest objection. Part VII must identify "
            "concessions, unanswered arguments, logical gaps, historical assumptions, and "
            "rhetorical techniques. Part VIII must deliver a neutral adjudication with "
            "separate rulings on factual support, internal logic, responsiveness, and "
            "persuasiveness. Steelman both sides, cite precise language and events, clearly "
            "distinguish transcript content from analytical reconstruction, and use nested "
            "headings and numbered lists throughout."
        )
    elif task == "literary":
        assignment = (
            "Write a rigorous critical essay based only on the supplied literary excerpt. "
            "Develop a single defensible thesis and examine narrative irony, character "
            "development, class and economics, courtship and marriage, gender expectations, "
            "misjudgment, dialogue, and the narrator's moral perspective. Organize the essay "
            "into at least ten titled sections. Support every major claim with precise "
            "references, discuss plausible counterarguments, and do not merely summarize."
        )
    else:
        raise ValueError(f"unsupported task: {task}")

    # Keep the composer input to one paragraph. ChatGPT's ProseMirror splits
    # multi-paragraph pastes into separate accessible static nodes, whose
    # boundaries cannot currently be reconstructed exactly by the adapter.
    return (
        f"You are given a long source excerpt. {assignment} Write at least "
        f"{requested_response_words:,} words. The first line of your response must be "
        f"exactly {BEGIN_SENTINEL}. The final line of your response must be exactly "
        f"{END_SENTINEL}. SOURCE_EXCERPT_BEGIN {context} SOURCE_EXCERPT_END Now produce "
        "the requested essay."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_file", type=Path)
    parser.add_argument("--app", choices=("chatgpt", "claude"), default="chatgpt")
    parser.add_argument("--context-words", type=int, default=10_000)
    parser.add_argument("--response-words", type=int, default=5_000)
    parser.add_argument("--minimum-accepted-words", type=int, default=4_500)
    parser.add_argument(
        "--task",
        choices=("debate", "debate_exchange", "literary"),
        default="debate",
    )
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("diagnostics/LONG_CHATGPT_RESPONSE.md"),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-restart-existing-session", action="store_true")
    args = parser.parse_args()

    source = args.source_file.read_text(encoding="utf-8", errors="replace")
    prompt = build_prompt(source, args.context_words, args.response_words, args.task)
    encoded = prompt.encode("utf-8")
    print(f"app={args.app}")
    print(f"total_prompt_words={len(prompt.split())}")
    print(f"prompt_characters={len(prompt)}")
    print(f"prompt_lines={len(prompt.splitlines())}")
    print(f"prompt_sha256={hashlib.sha256(encoded).hexdigest()}")
    print(f"requested_response_words={args.response_words}")
    print(f"minimum_accepted_words={args.minimum_accepted_words}")
    if args.dry_run:
        print("dry_run=true; nothing was sent")
        return 0

    print("Sending now. Do not use the desktop until this command finishes.")
    started = time.monotonic()
    client_class = ChatGPT if args.app == "chatgpt" else Claude
    response = client_class(
        allow_restart_existing_session=args.allow_restart_existing_session
    ).send(prompt, timeout=args.timeout)
    elapsed = time.monotonic() - started

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(response, encoding="utf-8")
    response_words = len(response.split())
    begins_correctly = response.lstrip().startswith(BEGIN_SENTINEL)
    ends_correctly = response.rstrip().endswith(END_SENTINEL)
    long_enough = response_words >= args.minimum_accepted_words

    print(f"elapsed_seconds={elapsed:.3f}")
    print(f"response_words={response_words}")
    print(f"response_characters={len(response)}")
    print(f"begin_sentinel={begins_correctly}")
    print(f"end_sentinel={ends_correctly}")
    print(f"output={args.output}")
    if begins_correctly and ends_correctly and long_enough:
        print("PASS: long prompt and long response completed with intact boundaries")
        return 0
    print("FAIL: response was short or a boundary sentinel was missing")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
