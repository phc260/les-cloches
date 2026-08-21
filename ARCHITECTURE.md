# Les Cloches v0.1 — Architecture

This describes how v0.1 is structured, why its architectural boundaries
exist, what was rejected, and what remains open. It is one document, meant
to be read start to finish once.

This is a rationale record, not an instruction file. Future coding-agent
requirements distilled from these decisions live in `AGENTS.md`.

## 1. Inventory of earlier prototype work

Two earlier implementations informed v0.1: a root proof-of-concept script
and a mature nested package that superseded it. v0.1 treats both as code
donors, not an architectural foundation.

### Root proof-of-concept script

**OBSOLETE**, in full. Coordinate-click dock icon, coordinate-click the
input box, synthesize keystrokes character-by-character via a hand-rolled
US-ASCII table, sleep a fixed `--reply-wait`, screenshot the result for a
human to read. No semantic discovery, no exact verification, no structured
response extraction, no recovery, no locking. It was superseded by
`claude-desktop-bridge` before this project started, and the proposal
explicitly forbids coordinates and OCR/screenshot-based verification.
Nothing from it was ported.

### `claude-desktop-bridge/transport/` — the real donor

| File | Disposition | Notes |
|---|---|---|
| `errors.py` | **ADAPT** | Renamed `ClaudeDesktop*` → `LesCloches*` (see §6); hierarchy otherwise unchanged. Added `UnsupportedPlatform`. |
| `locking.py` | **KEEP** | `TransactionLock` ported near-verbatim into `core/session.py`; already application-agnostic. |
| `atspi.py` — tree walk (`_walk`, `_safe`, `_role`/`_name`/`_text`, `_find_all`, `_press_named_action`) | **KEEP** | Extracted into `accessibility/atspi.py` as free functions; this part never assumed Claude-specific tree shape. |
| `atspi.py` — health/recovery loop (`_ensure_renderer`, `_wait_ready`, `_terminate_for_recovery`, `RendererHealth`, `SessionOwnership`, `TransactionPhase`) | **ADAPT** | Genuinely shared *behavior*, but the donor implemented it as base-class methods launching Claude specifically. Rewritten in `core/recovery.py` as a free function (`ensure_ready`) parameterized over a narrow adapter protocol (`health_snapshot`/`launch`/`terminate_for_recovery`/`existing_process_id`), so it owns zero application knowledge. |
| `atspi.py` — Claude semantics (`_application`, `_health_snapshot` selectors, `_open_fresh_chat`, `_editor_contains`, `_submit`, `_serialize_content`, `_assistant_response`, `_finished`, `_response_root`, `_response_state`, `_try_stop`) | **CLAUDE-SPECIFIC** | Ported into `apps/claude.py` as `ClaudeAdapter`, ported with behavior intact (see §3 for what changed and what didn't). |
| `atspi.py` — `_new_suffix` | **OBSOLETE** | Dead code: defined, unit-tested, never called by anything else in the donor. Not ported; its test was not ported either. |
| `atspi.py` — AT-SPI completion event listener (`_completion_listener`, `_remove_completion_listener`, GLib main-context pumping in `_wait_for_response`) | **OBSOLETE, deliberate simplification** | See §4. |
| `chatgpt.py` — `ChatGPTSemantics`, `ChatGPTAtspiBackend` | **CHATGPT-SPECIFIC** | Ported into `apps/chatgpt.py` as `ChatGPTAdapter`. No longer inherits from the Claude backend (see §2). |
| `chatgpt.py` — `ChatGPTDesktopTransport` | **ADAPT** | Folded into the public `ChatGPT` class in `les_cloches/__init__.py`; the separate `*Transport` wrapper class is gone (§5). |
| `input.py` — `AtspiTextInput`, `default_input_backend` (Wayland/env-based auto-selection) | **OBSOLETE for v0.1** | This *is* native Wayland write automation. Not carried forward; see §7. |
| `x11_input.py` — `X11ClipboardInput` | **KEEP** | Ported near-verbatim into `input/x11.py`. Process-ownership window activation via AT-SPI process lineage + `_NET_WM_PID`/`_NET_CLIENT_LIST` is exactly the commissioned, coordinate-free mechanism the proposal asks to preserve. |
| `xtest_fallback.py` | **OBSOLETE** | Coordinate-click diagnostic, explicitly never selected by the transport even in the donor. Coordinates are out of scope. |
| `commission_wayland.py`, `WAYLAND_*.json`, `docs/wayland-commissioning.md`, `W3A_EDITABLE_TEXT_REPORT.md` | **OBSOLETE** | Wayland cannot provide this project's required X11/XTEST write mechanism; see §7. Historical artifacts were not copied. |
| `commission_chatgpt_x11.py`, `CHATGPT_X11_*.json`, `docs/chatgpt-x11-commissioning.md` | **ADAPT** | Ported to `commissioning/commission_chatgpt_x11.py` against the new API (method names, `TransactionState` dataclass instead of 3-tuples, per-thread `ChatGPT()` instances for the concurrency experiment). Same X1–X14 experiment set and acceptance bar. |
| `diagnostics/dump_atspi.py` | **KEEP, generalized** | Already accepted `--application`; ported as `diagnostics/dump_atspi.py`. |
| `diagnostics/probe_chatgpt_atspi.py` | **ADAPT, merged** | A ChatGPT-specific variant of `dump_atspi.py` whose only real differentiator was redacting message text. Folded into `dump_atspi.py` as `--redact-text` rather than keeping two near-duplicate diagnostic scripts. |
| `tests/*.py` | **ADAPT** | Ported to `tests/`, updated for the new module layout and the `TransactionState`/adapter-protocol shapes. `test_atspi_helpers.py` (which only tested the now-dropped `_new_suffix`) was replaced with `test_accessibility_atspi.py`, covering the shared plumbing it should have covered. Added `test_claude_semantics.py`, since the donor had unit coverage for ChatGPT's response ownership but none for Claude's. |
| `tests/live/test_live_transport.py` | **ADAPT** | Split into `tests/live/test_live_claude.py` and `tests/live/test_live_chatgpt.py`; gate env var renamed `CLAUDE_DESKTOP_LIVE` → `LES_CLOCHES_LIVE`. |
| `README.md`, `REPORT.md`, `docs/accessibility.md`, `CHATGPT_X11_REPORT.md` | **ADAPT / reference only** | Not copied file-for-file; their content informed this README and this document. |

## 2. Why Claude and ChatGPT adapters do not share a base class

The donor's `ChatGPTAtspiBackend(AtspiBackend)` inherited from the Claude
backend and overrode roughly fifteen methods — discovery, health snapshot,
launch, fresh-chat, prompt verification, submit, response extraction,
completion detection, the wait loop, stop. Nearly everything non-trivial was
overridden. That is exactly the shape the proposal warns against: forcing
two materially different accessibility trees (Claude's turn-scoped
`article` nodes vs. ChatGPT's flat, heading-delimited stream) into one
inheritance hierarchy because they happened to share superficial AT-SPI
vocabulary (`push button`, `entry`, `heading`).

v0.1 replaces inheritance with a semantic contract
(`les_cloches.transport.DesktopAdapter`, a `Protocol`, not a base class):
`health_snapshot`, `launch`, `terminate_for_recovery`, `existing_process_id`,
`open_fresh_conversation`, `insert_prompt`, `editor_matches`, `submit`,
`transaction_state`, `try_stop`. `apps/claude.py` and `apps/chatgpt.py` each
implement every method independently. The one piece of literally identical
logic between them — killing an owned or (if permitted) pre-existing OS
process during recovery — is small, mechanical, and behavior-critical
enough to share as a plain function (`core.session.terminate_owned_or_existing`)
rather than duplicate; everything about *how to read the application* is
adapter-owned.

## 3. What changed vs. what was preserved in the adapters

Preserved exactly: Claude's article/heading response ownership
(`_assistant_response` picks the latest `article` whose body starts with a
heading named "Claude responded:"), its bold/code markdown reconstruction,
ChatGPT's "newest `You said:` → following `ChatGPT said:` → stop before the
next user turn" ownership rule, its markdown serialization (headings,
lists, paragraphs, code blocks via `class` containing `CodeBlock`), and the
mandatory insert → verify → MATCH/abort invariant (§4 of the proposal) —
verification is still enforced by the caller after `input_backend.replace()`
returns, exactly as in the donor, so a `replace()` that gives up silently
after its own short internal window still cannot result in a submitted
mismatch.

Changed: field names on the shared `HealthSnapshot`/`FailureDiagnostic`
dataclasses (`new_button_found` → `fresh_conversation_control_found`, etc.)
so the shared dataclass reads as generic rather than Claude-shaped, per the
proposal's naming guidance. `_response_state`/`_wait_for_response` (per-app,
duplicated) became one shared `transport.wait_for_completion` driven by one
adapter method, `transaction_state()`, returning `TransactionState
(generating, complete, response)` from a single tree traversal — see §4 for
why the completion *wait loop* itself could be unified even though
*response ownership* could not.

## 4. Simplification: dropped the AT-SPI completion event listener

The donor registered an `Atspi.EventListener` per transaction and pumped a
GLib main context inside the wait loop. Reading both implementations
closely: ChatGPT's listener callback recorded a `last_change` timestamp
that `_wait_for_response` never actually read — the wait loop derived
staleness from comparing successive `_response_state()` candidates itself.
Claude's listener did real work (a fast path keyed off the specific
"Claude finished the response" marker, plus a 5-second periodic fallback
probe), but polling at 50ms already gives comparable latency without the
extra ~40 lines of registration/deregistration plumbing per adapter, and
without requiring `GLib.MainContext` pumping in the shared wait loop at
all. v0.1 drops the listener and uses one shared, uniform polling +
stability-window loop (`transport.wait_for_completion`) for both
applications. This is a deliberate simplification, not a rediscovered
requirement — recorded here so a reviewer can decide it was a judgment call,
not an oversight. Behavior at the deadline boundary is unchanged: still
bounded, still raises `LesClochesTimeout`, still calls `try_stop()`.

## 5. Small public API

`ClaudeDesktopTransport`/`ChatGPTDesktopTransport` wrapper classes are gone.
The public surface is exactly:

```python
from les_cloches import Claude, ChatGPT
Claude().send(prompt, timeout=120.0) -> str
ChatGPT().send(prompt, timeout=120.0) -> str
```

`les_cloches.transport.send(adapter, input_backend, prompt, timeout, ...)`
is the shared engine underneath; it is not private (commissioning scripts
call it directly to reuse the exact same orchestration the public classes
use, rather than re-implementing it), but it is not exported from
`les_cloches/__init__.py` either — the two-class surface is what an external
caller is meant to use. No registry, no factory, no plugin manifest: adding
a third application would mean writing a third adapter module and a third
one-line public class, not touching shared code.

## 6. Renaming

`ClaudeDesktopError`/`Timeout`/`Busy`/`Unavailable` → `LesCloches*`.
`ClaudeDesktopTransport`/`ChatGPTDesktopTransport` → `les_cloches.transport.send()`
+ the `Claude`/`ChatGPT` classes. This is a greenfield package (`les_cloches`
has no external consumers yet — the sibling `les-cloches` git repository
was an empty `uv init` skeleton before this work), so there was no
migration-risk reason to keep Claude-specific names in shared exception
types or to add compatibility aliases. No compatibility shims were needed
or added.

## 7. Wayland is unavailable; Windows 11 is recognized but unproven

`AtspiTextInput` (AT-SPI keyboard-event synthesis, auto-selected by the
donor's `default_input_backend()` whenever `XDG_SESSION_TYPE=wayland`) *is*
the native Wayland write path the proposal says has "already been
investigated sufficiently for now" and marks unsupported for v0.1. It was
not ported. Instead, `Claude()`/`ChatGPT()` call
`require_supported_platform()` and raise `UnsupportedPlatform` immediately
outside an X11 session, rather than
silently falling back to a different, less-proven input path — this is the
"do not implement automatic fallback machinery that hides the real
platform" instruction taken literally. The earlier `AtspiTextInput` code was
not carried forward because it is not a viable backend under Les Cloches'
semantic, coordinate-free, exact-verification requirements. Native Wayland
does not expose the X11/XTEST window-focus and input mechanism on which the
commissioned write path depends.

Windows 11 is a different status: recognized, but neither implemented nor
commissioned. `current_platform_support()` identifies Windows 11 (including
modern builds that still report release `10`) and the public clients raise a
Windows-specific `UnsupportedPlatform` before attempting desktop access.
POSIX-only imports are guarded so merely importing and inspecting the package
does not crash first. This is platform awareness, not a compatibility claim:
there is no Windows UI Automation/input backend and no Windows 11 live-test or
commissioning evidence.

## 8. Judgment calls (not experimentally forced)

- Composition over inheritance for the two adapters (§2) — the donor's
  design worked and was tested; this is a legibility bet for independent
  review, not a fix for a proven defect.
- Dropping the AT-SPI completion listener (§4) — a latency/complexity
  trade, not a correctness fix.
- `HealthSnapshot`/`FailureDiagnostic` field renames (§3) — cosmetic,
  low-risk because nothing external consumes them yet.
- Splitting `diagnostics/probe_chatgpt_atspi.py` into a `--redact-text` flag
  on the generic dump tool instead of keeping both scripts.
- The Claude commissioning script (`commission_claude_x11.py`) is smaller
  (C1–C7) than ChatGPT's (X1–X14) rather than mechanically mirroring every
  ChatGPT experiment. Claude's article-scoped tree makes cross-turn response
  misattribution structurally harder than in ChatGPT's flat stream, so the
  donor never carried anywhere near this much live-commissioning weight for
  Claude either (only `tests/live/test_live_transport.py`). Forcing a
  symmetric X1–X14-shaped Claude script would have manufactured experiments
  that don't correspond to a real ownership risk in that tree shape.

## Rejected alternatives

```
generic plugin registry / factory for applications
    rejected — exactly two applications exist; a third would still only
    mean one new adapter module and one new public class

shared base class for ClaudeAdapter/ChatGPTAdapter
    rejected — see §2; the donor's inheritance already showed this forces
    ChatGPT to override nearly everything non-trivial

generic accessibility-tree abstraction / DSL
    rejected — Claude's turn-scoped articles and ChatGPT's flat
    heading-delimited stream are materially different; the proposal
    explicitly forbids normalizing them for architectural symmetry

native Wayland input backend (AT-SPI keyboard-event synthesis)
    rejected for this design — it does not provide the required X11/XTEST
    focus and input guarantees and was not carried into v0.1's supported
    surface (§7)

coordinate-based input or OCR fallback
    rejected — semantic targeting already works; coordinates are the
    donor's superseded proof-of-concept, not a fallback worth keeping

AT-SPI completion event listener
    dropped as a simplification (§4), not because it was broken

parallel/concurrent desktop transactions
    rejected — one visible UI is a serialized resource; the cross-process
    TransactionLock enforces exactly one owner at a time
```

## Known limitations

See the README's "Known limitations" section — it is the authoritative,
user-facing copy of this list (Windows 11 recognized but unverified and
unsupported; native Wayland write automation unavailable; an editor may
transform certain literal pasted strings and
exact verification will correctly reject them before submission; geometry
commissioning covers restore/maximize/sidebar-hide, not every
movement/resize/scroll permutation; desktop updates can change
accessibility semantics; this abstraction has been demonstrated against
exactly two applications).

## OPEN QUESTIONS

- Whether a third application would ever justify promoting
  `DesktopAdapter` from a `Protocol` to something more formal (an ABC with
  shared default implementations of the parts that do turn out to be
  identical). Two data points are not enough to know which parts of
  `terminate_owned_or_existing`-style sharing generalize and which don't.
- Whether the dropped AT-SPI completion listener (§4) should come back if a
  future desktop update makes plain polling measurably slower to detect
  completion than the donor's fast path was. No regression has been
  observed, but it also has not been load-tested against a slow AT-SPI bus.
- Whether the C1–C7 vs. X1–X14 asymmetry in commissioning coverage (§8)
  should be evened out once Claude's tree has been observed to have some
  ownership failure mode ChatGPT's structural risk profile predicted —
  right now there is no such observed failure motivating more Claude
  experiments.
