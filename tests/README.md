# Test suite guide

The suite is organized by subsystem rather than by difficulty or platform.
This table is the index for those two properties.

Every test has exactly one execution-scope marker: `easy`, `medium`, or
`hard`. The `live` marker is independent and identifies tests that control a
real desktop application. `tests/conftest.py` enforces the execution-scope
rule during collection.

The platform column names the implementation contract under test. It does not
necessarily name the host required to run the test: tests built from fakes can
exercise Linux or Windows semantics on either host.

| File | Difficulty | Platform | Runs on | Focus |
|---|---|---|---|---|
| `test_accessibility_atspi.py` | Easy | Linux / AT-SPI | Any | Bounded semantic traversal, safe stale-node handling, and named actions |
| `test_accessibility_uia.py` | Easy | Windows / UIA | Any | Bounded UIA traversal and exact editable-text extraction using fakes |
| `test_chatgpt_semantics.py` | Easy | Linux / AT-SPI | Any | ChatGPT response ownership, editor reconstruction, and Markdown serialization |
| `test_claude_semantics.py` | Easy | Linux / AT-SPI | Any | Claude response ownership, editor and attachment verification, and Markdown serialization |
| `test_input_backends.py` | Easy | Linux / X11 | Any | X11 process ownership, bounded lookup, GLib draining, and source-level input invariants |
| `test_platforms.py` | Easy | Cross-platform | Any | Platform classification, public gating, Wayland rejection, and lock-path behavior |
| `test_windows_semantics.py` | Easy | Windows / UIA | Any | Windows editor reconstruction, project matching, semantic input, and response ownership |
| `test_commissioning.py` | Medium | Cross-platform | Any | X11 recovery-permission propagation, app-specific Windows harness boundaries, and evidence persistence |
| `test_platform_contracts.py` | Medium | Cross-platform | Any | Shared backend boundaries, bounded diagnostics, explicit input mechanisms, and forbidden-stack checks |
| `test_recovery.py` | Medium | Shared | Any | Application-agnostic readiness, recovery policy, and failure diagnostics |
| `test_session_recovery.py` | Medium | POSIX process control | POSIX; skipped on Windows | Graceful and forced process termination behavior |
| `test_transport.py` | Medium | Shared | Any | End-to-end transaction orchestration, validation, locking, and deadline behavior with fakes |
| `test_windows_recovery.py` | Medium | Windows process control | Any | Windows process-tree recovery behavior using fakes |
| `live/test_live_chatgpt.py` | Hard + live | Linux / X11 | Commissioned Linux/X11 desktop | Real ChatGPT Desktop exactness, timeout, recovery, and fresh-chat isolation |
| `live/test_live_claude.py` | Hard + live | Linux / X11 | Commissioned Linux/X11 desktop | Real Claude Desktop exactness, timeout, recovery, and fresh-chat isolation |

## Running tests

Run the non-live suite after code changes:

```bash
.venv/bin/python -m pytest -q -m "not live"
```

Select one execution scope:

```bash
.venv/bin/python -m pytest -q -m easy
.venv/bin/python -m pytest -q -m medium
```

Live tests are opt-in and control real desktop applications. Run them only on
the commissioned Linux/X11 environment, without using the desktop
concurrently:

```bash
LES_CLOCHES_LIVE=1 uv run pytest -q -m "hard and live"
```

Platform groupings in the table are descriptive rather than pytest markers.
Select a platform-specific module by path when needed, for example:

```bash
.venv/bin/python -m pytest -q tests/test_windows_semantics.py
.venv/bin/python -m pytest -q tests/test_chatgpt_semantics.py
```
