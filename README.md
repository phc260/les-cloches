# Les Cloches

![Platform: Linux/X11](https://img.shields.io/badge/platform-Linux%2FX11-2ea44f)
![Python: 3.12+](https://img.shields.io/badge/python-3.12%2B-3776ab)
![Status: Experimental](https://img.shields.io/badge/status-experimental-orange)

Les Cloches is a correspondence adapter for gathering feedback from AI
desktop applications. It sends prompts through
the visible Claude Desktop and ChatGPT Desktop interfaces and returns their
response text.

```python
from les_cloches import Claude, ChatGPT

claude_reply = Claude().send("Reply with exactly: PONG")
chatgpt_reply = ChatGPT().send("Reply with exactly: PONG")
```

Each call opens a fresh chat. `send()` is synchronous and uses one timeout for
the complete transaction, including application readiness, prompt entry,
generation, and response extraction.

## Platform status

| Environment | Status |
|---|---|
| Claude Desktop on Linux/X11 | Experimental and commissioned |
| ChatGPT Desktop on Linux/X11 | Experimental and commissioned |
| Windows 11 | Recognized, unverified, and unsupported |
| Linux/Wayland | Write automation unavailable |

Windows 11 awareness is not a compatibility claim. Les Cloches can report the
platform accurately. A Microsoft UI Automation and SendInput backend is under
development, but the public API remains gated because Windows has not completed
commissioning and is still unsupported.

```python
from les_cloches import current_platform_support

print(current_platform_support())
```

Constructing `Claude()` or `ChatGPT()` on an unsupported platform raises
`UnsupportedPlatform` before attempting desktop interaction.

## Requirements

- A Linux X11 desktop session
- Claude Desktop and/or ChatGPT Desktop, installed and signed in
- Python 3.12 or newer
- System PyGObject bindings for AT-SPI, GTK 4, and GDK 4
- X11 and XTEST libraries

Create the environment with access to the system PyGObject installation:

```bash
uv venv --clear --python /usr/bin/python3 --system-site-packages
uv sync --extra test
```

Les Cloches enables renderer accessibility when it launches an application.
When attaching manually to an existing session, start the application with:

```bash
claude-desktop --force-renderer-accessibility
chatgpt --force-renderer-accessibility
```

## Safety behavior

Before submission, Les Cloches reads the visible editor content and compares
it character-for-character with the requested prompt. A mismatch aborts the
transaction; altered text is never submitted silently.

Desktop access is serialized so concurrent callers cannot own the same visible
application window simultaneously. A pre-existing application session is not
restarted unless explicitly allowed:

```python
claude = Claude(allow_restart_existing_session=True)
reply = claude.send("Hello", timeout=180.0)
```

Les Cloches does not use private model APIs, authentication-token extraction,
browser/CDP automation, coordinates, screenshots, or OCR.

## Backend contract boundaries

The non-live contract tests run on either host and make the shared requirements
and intentional platform differences explicit:

| Boundary | Linux/X11 | Windows 11 prototype |
|---|---|---|
| Semantic discovery | AT-SPI | Microsoft UI Automation |
| Prompt input | Process-owned X11 focus, clipboard, XTEST | UIA ValuePattern when exact; otherwise semantic focus, Unicode clipboard, SendInput |
| Exact readback before submit | Required | Required |
| Fresh conversation and response ownership | Application adapter owns semantics | Application adapter owns semantics |
| Transaction lock and deadline | Shared transport contract | Shared transport contract |
| Renderer launch | `--force-renderer-accessibility` | `--force-renderer-accessibility` |
| Coordinates, screenshots/OCR, browser/CDP, private APIs | Forbidden | Forbidden |
| Public support status | Experimental and commissioned | Gated, unverified, unsupported |

Shared tests cover only genuinely identical, application-agnostic behavior:
bounded tree traversal, exact verification, deadlines, locking, recovery
permission, and diagnostic schema. AT-SPI and UIA selectors, focus/input
mechanisms, application launches, and response ownership remain independent.
Native Wayland has no automatic fallback.

## Development

Every test has exactly one execution-scope level:

| Level | Scope |
|---|---|
| `easy` | Isolated, deterministic behavior using fakes or pure helpers |
| `medium` | Cross-module contracts, subprocess behavior, recovery, or platform boundaries |
| `hard` | End-to-end control of real desktop applications |

Run an individual level with `-m easy`, `-m medium`, or `-m hard`. The `live`
marker remains a separate safety gate; all current hard tests are also live.
See [tests/README.md](tests/README.md) for the complete test-module index,
including difficulty, platform contract, host requirements, and focus.
Investigation tools and their safety and output contracts are documented in
[diagnostics/README.md](diagnostics/README.md).

Run the non-live tests:

```bash
.venv/bin/python -m pytest -q -m "not live"
```

Live tests control the real desktop and are opt-in:

```bash
LES_CLOCHES_LIVE=1 uv run pytest -m "hard and live" -q
```

Do not use the desktop while live tests are running.

## Limitations

- Desktop application updates may change accessibility semantics and require
  adapter updates.
- Some editor transformations are rejected by exact prompt verification.
- Windows 11 has an under-development backend, but it remains uncommissioned,
  gated, and unsupported.
- Native Wayland cannot provide this project's required X11/XTEST write path.

See [ARCHITECTURE.md](ARCHITECTURE.md) for architectural rationale and
[AGENTS.md](AGENTS.md) for repository working instructions.
