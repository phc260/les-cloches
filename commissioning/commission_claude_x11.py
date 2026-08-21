#!/usr/bin/env python3
"""Run and record C1-C7 commissioning for Claude Desktop on X11.

Claude Desktop's article-based accessibility tree carries much lower
response-ownership risk than ChatGPT's flat, heading-delimited stream (see
ARCHITECTURE.md), so this commissioning script is deliberately smaller than
`commission_chatgpt_x11.py`: it covers the acceptance categories from the
Les Cloches v0.1 proposal (discovery, input, submission, response ownership,
completion, timeout/recovery, serialization) without re-deriving every
ChatGPT-specific experiment.

WARNING: this controls the real Claude Desktop window — mouse focus,
keyboard input. Do not use the desktop while it runs.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from les_cloches import Claude, LesClochesTimeout
from les_cloches import transport as lc_transport
from les_cloches.apps.claude import ClaudeAdapter
from les_cloches.core.recovery import ensure_ready
from les_cloches.core.session import SessionState
from les_cloches.input.x11 import X11ClipboardInput


@dataclass
class Result:
    experiment: str
    status: str
    detail: str
    seconds: float


class Commission:
    def __init__(self, timeout: float, allow_restart_existing_session: bool = False):
        self.timeout = timeout
        self.adapter = ClaudeAdapter(poll_interval=0.2)
        self.input_backend = X11ClipboardInput()
        self.allow_restart_existing_session = allow_restart_existing_session
        self.results: list[Result] = []

    def run(self, experiment_name, function):
        started = time.monotonic()
        try:
            detail = function() or "acceptance checks passed"
            status = "GREEN"
        except Exception as exc:
            status, detail = "RED", f"{type(exc).__name__}: {exc}"
        self.results.append(Result(experiment_name, status, detail, round(time.monotonic() - started, 3)))

    def deadline(self, multiplier: float = 1.0) -> float:
        return time.monotonic() + self.timeout * multiplier

    def ensure_ready(self, deadline: float) -> None:
        ensure_ready(
            self.adapter,
            SessionState(),
            deadline,
            allow_restart_existing_session=self.allow_restart_existing_session,
            poll_interval=0.2,
        )

    def send(self, prompt: str, timeout: "float | None" = None) -> str:
        return lc_transport.send(
            self.adapter,
            self.input_backend,
            prompt,
            timeout or self.timeout,
            stable_interval=0.8,
            allow_restart_existing_session=self.allow_restart_existing_session,
        )

    def send_exact(self, expected: str, prompt: "str | None" = None) -> None:
        actual = self.send(prompt or f"Reply with exactly: {expected}")
        if actual != expected:
            raise AssertionError(f"expected {expected!r}, received {actual!r}")

    def c1_discovery(self):
        if os.environ.get("XDG_SESSION_TYPE", "").casefold() != "x11":
            raise AssertionError("XDG_SESSION_TYPE is not x11")
        if not os.environ.get("DISPLAY"):
            raise AssertionError("DISPLAY is absent")
        self.ensure_ready(self.deadline())
        if self.adapter.health_snapshot().health.name != "READY":
            raise AssertionError("Claude AT-SPI renderer is not ready")
        return "session=X11; AT-SPI=READY"

    def c2_input(self):
        deadline = self.deadline()
        self.ensure_ready(deadline)
        editor = self.adapter.open_fresh_conversation(deadline)
        cases = ["hello", "Claude X11 test 123", "Hello 世界 — naïve café — 🤖", "line one\nline two\nUnicode 世界 🤖"]
        for value in cases:
            editor = self.adapter.insert_prompt(self.input_backend, editor, value, deadline)
            if not self.adapter.editor_matches(editor, value):
                raise AssertionError(f"editor mismatch for {value!r}")
        return "focus, insertion, multiline, and Unicode verified through AT-SPI"

    def c3_submission_and_ownership(self):
        self.send_exact("SUBMISSION_OK")
        state = self.adapter.transaction_state()
        if state.generating or not state.complete or state.response != "SUBMISSION_OK":
            raise AssertionError(state)
        return "semantic Send invoked; latest article with 'Claude responded:' heading owned the response"

    def c4_isolation(self):
        for expected in ("ISOLATION_ALPHA", "ISOLATION_BETA", "REPEATED", "REPEATED"):
            self.send_exact(expected)
        return "four fresh conversations isolated, including two identical expected responses"

    def c5_structured_output(self):
        expected = {"status": "ok", "unicode": "café 世界 🤖", "lines": ["one", "two"]}
        prompt = "Return exactly this minified JSON and nothing else: " + json.dumps(expected, ensure_ascii=False, separators=(",", ":"))
        for _ in range(5):
            actual = json.loads(self.send(prompt))
            if actual != expected:
                raise AssertionError(f"JSON mismatch: {actual!r}")
        return "5/5 parsed JSON; no prompt/UI-label contamination; Unicode and arrays preserved"

    def c6_timeout_and_recovery(self):
        try:
            self.send("Write a detailed 5,000 word essay.", timeout=5.0)
        except LesClochesTimeout:
            pass
        else:
            raise AssertionError("short-timeout request unexpectedly completed")
        self.send_exact("TIMEOUT_RECOVERED")
        return "request A timed out explicitly; semantic Stop/bounded cleanup; request B passed"

    def c7_serialization(self):
        responses, errors = [], []

        def caller(token):
            try:
                claude = Claude()
                responses.append((token, claude.send(f"Reply with exactly: {token}", self.timeout * 4)))
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")

        threads = [threading.Thread(target=caller, args=(f"SERIAL_{index}",)) for index in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(self.timeout * 12)
        if errors or len(responses) != 3 or any(expected != actual for expected, actual in responses):
            raise AssertionError(f"responses={responses!r}; errors={errors!r}")
        return "three concurrent callers serialized with exact, unambiguous responses"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="*", default=[], help="experiment IDs, e.g. C1 C2 C3")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--report", type=Path, default=Path("CLAUDE_X11_COMMISSIONING.json"))
    parser.add_argument(
        "--allow-restart-existing-session",
        action="store_true",
        help="restart a pre-existing, unhealthy Claude Desktop session (e.g. one started without "
        "--force-renderer-accessibility) instead of refusing to touch it",
    )
    args = parser.parse_args()
    commission = Commission(args.timeout, allow_restart_existing_session=args.allow_restart_existing_session)
    experiments = [
        ("C1", commission.c1_discovery),
        ("C2", commission.c2_input),
        ("C3", commission.c3_submission_and_ownership),
        ("C4", commission.c4_isolation),
        ("C5", commission.c5_structured_output),
        ("C6", commission.c6_timeout_and_recovery),
        ("C7", commission.c7_serialization),
    ]
    selected = {item.upper() for item in args.only} or {experiment_name for experiment_name, _ in experiments}
    for experiment_name, function in experiments:
        if experiment_name in selected:
            commission.run(experiment_name, function)
            result = commission.results[-1]
            print(f"[{result.status}] {result.experiment} - {result.detail}", flush=True)
    payload = {
        "target": "Claude Desktop on X11",
        "date": time.strftime("%Y-%m-%d"),
        "session_type": os.environ.get("XDG_SESSION_TYPE"),
        "display": os.environ.get("DISPLAY"),
        "input_backend": commission.input_backend.name,
        "results": [asdict(result) for result in commission.results],
    }
    args.report.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 1 if any(result.status == "RED" for result in commission.results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
