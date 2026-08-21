# Les Cloches v0.1 — Resolved Issues

Found while building and then live-testing v0.1 against the real desktop on
2026-08-19. All issues recorded here have been fixed. There are currently no
known active defects in this file. This remains separate from `ARCHITECTURE.md`'s
"Open Questions", which are design judgment calls rather than bugs.

## Resolved

### 1. `Commission.send()` didn't pass `allow_restart_existing_session` through

**Where:** `commissioning/commission_claude_x11.py` and
`commissioning/commission_chatgpt_x11.py`, `Commission.send()`.

**Bug:** `Commission.ensure_ready()` correctly passed
`allow_restart_existing_session=self.allow_restart_existing_session` to
`core.recovery.ensure_ready()`, but `Commission.send()` called
`transport.send(...)` without that keyword, so it silently used
`transport.send()`'s default (`False`). Any experiment invoking `self.send()`
or `self.send_exact()` (C3–C7 in the Claude script; X5, X8, X9, X11, X14 in
the ChatGPT script) therefore never actually attempted recovery, regardless
of the `--allow-restart-existing-session` flag — while experiments calling
`self.ensure_ready()` directly (C1/C2, X1/X2) did.

**Symptom seen live:** after `--allow-restart-existing-session` was passed,
C1/C2 attempted recovery (and failed for a different reason, see Issue 3
below); C3 onward failed instantly with "the pre-existing session was not
restarted" — a different, misleading error that looked like the flag had no
effect at all.

**Resolution:** `Commission.send()` in both scripts now passes
`allow_restart_existing_session=self.allow_restart_existing_session`
through to `transport.send()`. Unit coverage verifies the forwarding behavior
for both commissioning scripts.

### 2. `uv run` cannot see the system AT-SPI/GDK bindings

**Symptom:** `uv run python3 commissioning/commission_claude_x11.py`
failed immediately with `ModuleNotFoundError: No module named 'gi'`, even
though `python3 -c "import gi"` succeeds using the system interpreter.

**Cause:** `gi` (PyGObject, providing `Atspi` and `Gdk`) comes from the
system package `python3-gi` / `gir1.2-atspi-2.0`, not from PyPI (see
README's "Tests" section and `pyproject.toml`'s comment on
`dependencies = []`). `uv sync` creates an isolated venv that does not
inherit system site-packages, so anything importing `gi` fails inside it.

**Resolution:** the README now gives a one-time environment bootstrap that uses the
system interpreter and makes its distribution-provided packages visible:

```bash
uv venv --clear --python /usr/bin/python3 --system-site-packages
uv sync --extra test
```

After that, both tests and commissioning use `uv run`; an import smoke check
is documented too. Verified in a fresh temporary environment against the
system `gi` installation.

This remains a system dependency rather than a PyPI dependency; recreating
`.venv` without `--system-site-packages` intentionally removes access to it.

### 3. Live Claude Desktop commissioning could not reach a `READY` renderer

**What happened:** Running `commission_claude_x11.py
--allow-restart-existing-session` against the real desktop, C1 and C2 each
spent their full 90-second deadline attempting bounded recovery (kill the
existing session, relaunch `claude-desktop --force-renderer-accessibility`,
wait) and both gave up with `LesClochesUnavailable: the renderer remained
unavailable after one recovery attempt`.

**Root cause, as far as I got:** neither Claude Desktop nor ChatGPT Desktop
had an actual mapped top-level window on the display at the time — I
confirmed this two ways: a screenshot showed only the desktop and a
terminal (no app window), and `xprop -root _NET_CLIENT_LIST` listed four
windows (Nautilus, a terminal, desktop icons, Brave) with neither app
present. AT-SPI's `_health_snapshot()` saw `application_found=True` and
`frame_found=True` but `document_found=False` — consistent with the process
running backgrounded/minimized-to-tray with no loaded, visible document.

**Root cause in the recovery code:** `terminate_owned_or_existing()` sent
`SIGTERM` to the recorded PID and returned immediately. `ensure_ready()`
then relaunched while that process was still alive. For a single-instance
Electron application, the relaunch can hand off to the unchanged background
instance. This is a concrete code-level cause consistent with PID 112881
surviving both attempts.

**Resolution:** recovery now waits for the recorded process to disappear before
relaunching. It allows a bounded graceful-stop interval, escalates to
`SIGKILL` only if necessary, and confirms exit after escalation. It also
fails explicitly instead of pretending to restart when AT-SPI supplies no
PID, reports permission failures and the targeted PID, and refuses to ever
target the bridge's own process. The bridge-owned process-group path has the
same bounded escalation behavior.

Unit coverage verifies graceful exit, escalation, post-`SIGKILL`
confirmation, missing-PID failure, current-process protection, and the
commissioning scripts' restart-flag propagation.

Subsequent live Claude Desktop and ChatGPT Desktop transactions reached ready
renderers and completed end to end. The destructive forced-restart branch is
covered by unit tests; a full commissioning rerun can still be used to produce
fresh acceptance evidence, but it is no longer tracking a known defect:

```bash
uv run python commissioning/commission_claude_x11.py --allow-restart-existing-session
uv run python commissioning/commission_chatgpt_x11.py --allow-restart-existing-session
```
