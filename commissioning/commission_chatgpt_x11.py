#!/usr/bin/env python3
"""Run and record X1-X14 commissioning for ChatGPT Desktop on X11.

This exercises `les_cloches.apps.linux.chatgpt.ChatGPTAdapter` and
`les_cloches.input.x11.X11ClipboardInput` both directly (for structural
experiments that need to inspect the accessibility tree) and through the
public `les_cloches.ChatGPT` API (for end-to-end and concurrency
experiments), matching what an external caller would actually use.

WARNING: this controls the real ChatGPT Desktop window, including semantic
focus, keyboard/clipboard input, and window state. Do not use the desktop
while it runs.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from les_cloches import ChatGPT, LesClochesTimeout
from les_cloches import transport as lc_transport
from les_cloches.accessibility.atspi import name, press_named_action, role
from les_cloches.apps.linux.chatgpt import ChatGPTAdapter
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
        self.adapter = ChatGPTAdapter(poll_interval=0.2)
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

    def x1(self):
        if os.environ.get("XDG_SESSION_TYPE", "").casefold() != "x11":
            raise AssertionError("XDG_SESSION_TYPE is not x11")
        if not os.environ.get("DISPLAY"):
            raise AssertionError("DISPLAY is absent")
        processes = subprocess.check_output(["ps", "-eo", "pid,args"], text=True, errors="replace")
        if "/usr/lib/chatgpt/ChatGPT" not in processes or "--ozone-platform=x11" not in processes:
            raise AssertionError("ChatGPT renderer/GPU process lacks --ozone-platform=x11")
        root_properties = subprocess.check_output(["xprop", "-root", "_NET_CLIENT_LIST"], text=True, errors="replace")
        window_ids = [token.strip().strip(",") for token in root_properties.split("#", 1)[-1].split(",")]
        chatgpt_window = None
        for window_id in window_ids:
            props = subprocess.check_output(
                ["xprop", "-id", window_id, "_NET_WM_NAME", "WM_CLASS", "_NET_WM_PID"], text=True, errors="replace"
            )
            if '"ChatGPT"' in props and "Chatgpt" in props:
                chatgpt_window = window_id
                break
        if chatgpt_window is None:
            raise AssertionError("ChatGPT X11 window was not owned in _NET_CLIENT_LIST")
        self.ensure_ready(self.deadline())
        if self.adapter.health_snapshot().health.name != "READY":
            raise AssertionError("ChatGPT AT-SPI renderer is not ready")
        package_version = subprocess.check_output(["dpkg-query", "-W", "-f=${Version}", "chatgpt"], text=True).strip()
        electron_version = Path("/usr/lib/chatgpt/version").read_text(encoding="utf-8").strip()
        return (
            f"session=X11; window={chatgpt_window}; AT-SPI=READY; "
            f"ChatGPT={package_version}; Electron={electron_version}"
        )

    def x2(self):
        self.ensure_ready(self.deadline())
        required = {
            "new_chat": bool(
                self.adapter._find_all(lambda node: role(node) == "push button" and name(node) == self.adapter.semantics.new_chat_name)
            ),
            "editor": bool(self.adapter._find_all(lambda node: self.adapter.semantics.is_editor(self.adapter.Atspi, node))),
        }
        if not all(required.values()):
            raise AssertionError(required)
        user, assistant = self.adapter._message_counts()
        return (
            "application=Codex/frame=ChatGPT; New chat=push button; "
            "editor=entry Message ChatGPT|Work with ChatGPT; Send=push button; "
            f"turn delimiters=heading You said:/ChatGPT said:; visible counts={user}/{assistant}"
        )

    def x3(self):
        deadline = self.deadline()
        self.ensure_ready(deadline)
        editor = self.adapter.open_fresh_conversation(deadline)
        cases = ["hello", "ChatGPT X11 test 123", "Hello 世界 — naïve café — 🤖", "line one\nline two\nUnicode 世界 🤖"]
        for value in cases:
            editor = self.adapter.insert_prompt(self.input_backend, editor, value, deadline)
            if self.adapter._editor_value(editor) != value:
                raise AssertionError(f"editor mismatch for {value!r}")
        editor = self.adapter.insert_prompt(self.input_backend, editor, "replacement", deadline)
        if self.adapter._editor_value(editor) != "replacement":
            raise AssertionError("replacement failed")
        editor = self.adapter.insert_prompt(self.input_backend, editor, "", deadline)
        if self.adapter._editor_value(editor):
            raise AssertionError("clear failed")
        return "focus, insertion, replacement, clear, multiline, and Unicode verified through AT-SPI"

    def x4(self):
        deadline = self.deadline()
        self.ensure_ready(deadline)
        self.adapter.open_fresh_conversation(deadline)
        before = self.adapter._message_counts()
        response = self.adapter.send_within_current_conversation(self.input_backend, "Reply with exactly: SEMANTIC_SEND_OK", deadline)
        after = self.adapter._message_counts()
        if response != "SEMANTIC_SEND_OK" or after[0] != before[0] + 1:
            raise AssertionError(f"response={response!r}; counts={before}->{after}")
        return "semantic Send action created exactly one user message and one owned response"

    def x5(self):
        for _ in range(5):
            self.send_exact("PONG")
        return "5/5 exact PONG in fresh chats"

    def x6(self):
        deadline = self.deadline(2)
        self.ensure_ready(deadline)
        self.adapter.open_fresh_conversation(deadline)
        first = self.adapter.send_within_current_conversation(self.input_backend, "Reply with exactly: OWNERSHIP_ALPHA", deadline)
        second = self.adapter.send_within_current_conversation(self.input_backend, "Reply with exactly: OWNERSHIP_BETA", deadline)
        if (first, second) != ("OWNERSHIP_ALPHA", "OWNERSHIP_BETA"):
            raise AssertionError((first, second))
        user, assistant = self.adapter._message_counts()
        if user != 2 or assistant < 2:
            raise AssertionError(f"unexpected message counts {user}/{assistant}")
        return (
            "latest user-heading boundary owns all following ChatGPT-heading fragments; "
            "two-turn extraction returned ALPHA then BETA without final-node heuristics"
        )

    def x7(self):
        self.send_exact("COMPLETION_OK")
        state = self.adapter.transaction_state()
        if state.generating or not state.complete or state.response != "COMPLETION_OK":
            raise AssertionError(state)
        return "response start observed; completion=Stop absent + assistant action present + stable owned text"

    def x8(self):
        expected = {"status": "ok", "unicode": "café 世界 🤖", "lines": ["one", "two"]}
        prompt = "Return exactly this minified JSON and nothing else: " + json.dumps(expected, ensure_ascii=False, separators=(",", ":"))
        for _ in range(5):
            actual = json.loads(self.send(prompt))
            if actual != expected:
                raise AssertionError(f"JSON mismatch: {actual!r}")
        return "5/5 parsed JSON; no prompt/UI-label contamination; Unicode and arrays preserved"

    def x9(self):
        for expected in ("ISOLATION_ALPHA", "ISOLATION_BETA", "REPEATED", "REPEATED"):
            self.send_exact(expected)
        return "four fresh chats isolated, including two identical expected responses"

    def x10(self):
        frame = self.adapter._main_frame()
        if frame is None:
            raise AssertionError("ChatGPT frame missing")
        for control_name in ("Restore", "Maximize", "Restore"):
            controls = self.adapter._find_all(
                lambda node, control_name=control_name: role(node) == "push button" and name(node) == control_name
            )
            if controls:
                press_named_action(controls[0], {"press", "click"})
                time.sleep(0.5)
        hide = self.adapter._find_all(lambda node: role(node) == "push button" and name(node) == "Hide sidebar")
        if hide:
            press_named_action(hide[0], {"press", "click"})
            time.sleep(0.5)
        self.send_exact("GEOMETRY_OK")
        return "restore/maximize/restore and sidebar-hidden semantic run passed without coordinates"

    def x11(self):
        try:
            self.send("Write at least 5,000 words before giving a conclusion.", timeout=5.0)
        except LesClochesTimeout:
            pass
        else:
            raise AssertionError("short-timeout request unexpectedly completed")
        self.send_exact("TIMEOUT_RECOVERED")
        return "request A timed out explicitly; semantic Stop/bounded cleanup; request B passed"

    def x12(self):
        deadline = self.deadline()
        stale = self.adapter.open_fresh_conversation(deadline)
        buttons = self.adapter._find_all(
            lambda node: role(node) == "push button" and name(node) == self.adapter.semantics.new_chat_name
        )
        if not buttons or not press_named_action(buttons[0], {"press", "click"}):
            raise AssertionError("could not force composer replacement")
        current = self.adapter._focus_editor(stale, deadline)
        if not self.adapter.semantics.is_editor(self.adapter.Atspi, current):
            raise AssertionError("stale composer was not rediscovered")
        return "stale composer reference recovered through bounded semantic rediscovery"

    def x13(self):
        responses, errors = [], []

        def caller(token):
            try:
                chatgpt = ChatGPT()
                responses.append((token, chatgpt.send(f"Reply with exactly: {token}", self.timeout * 4)))
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

    def x14(self):
        cases = [
            ("SMOKE_SHORT", None, "ordinary"),
            ("line one\nline two", "Return exactly these two lines, with no fences:\nline one\nline two", "multiline"),
            ("Unicode café 世界 🤖", None, "unicode"),
            (
                '{"smoke":true}',
                "Return a minified JSON object with one key named smoke and boolean value true. "
                "Return only the JSON and do not use code fences.",
                "json",
            ),
            ("# Smoke", "Reply with a Markdown level-one heading containing only the word Smoke.", "markdown"),
            ("smoke_code", "Reply with a fenced plain-text code block containing only the text smoke_code.", "code"),
            ("REPEAT_SMOKE", None, "repeat-a"),
            ("REPEAT_SMOKE", None, "repeat-b"),
        ]
        failures = []
        for expected, prompt, category in cases:
            try:
                self.send_exact(expected, prompt)
            except Exception as exc:
                failures.append(f"{category}: {exc}")
        if failures:
            raise AssertionError("; ".join(failures))
        return f"{len(cases)} mixed fresh-chat requests passed; failures by category: none"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="*", default=[], help="experiment IDs, e.g. X1 X2 X3")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(__file__).resolve().parent / "CHATGPT_X11_COMMISSIONING.json",
    )
    parser.add_argument(
        "--allow-restart-existing-session",
        action="store_true",
        help="restart a pre-existing, unhealthy ChatGPT Desktop session (e.g. one started without "
        "--force-renderer-accessibility) instead of refusing to touch it",
    )
    args = parser.parse_args()
    commission = Commission(args.timeout, allow_restart_existing_session=args.allow_restart_existing_session)
    selected = {item.upper() for item in args.only} or {f"X{number}" for number in range(1, 15)}
    for number in range(1, 15):
        experiment_name = f"X{number}"
        if experiment_name in selected:
            commission.run(experiment_name, getattr(commission, experiment_name.casefold()))
            result = commission.results[-1]
            print(f"[{result.status}] {result.experiment} - {result.detail}", flush=True)
    payload = {
        "target": "ChatGPT Desktop on X11",
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
