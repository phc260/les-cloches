# Les Cloches Agent Instructions

These instructions apply to the entire repository. Read `README.md` for the
user-facing contract, `ARCHITECTURE.md` for architectural rationale, and
`ISSUES.md` for the resolved-issue record.

## Product contract

- Automate only the visible Claude Desktop and ChatGPT Desktop interfaces.
- Use semantic accessibility discovery and actions. Never add private model
  APIs, authentication/session extraction, browser or CDP automation,
  coordinate-driven input, screenshots/OCR, or timing-only correctness.
- Preserve the prompt invariant: insert the requested text, read it back from
  the application's visible accessibility subtree, compare it exactly, and
  submit only on a character-for-character match.
- Open a fresh conversation before every transaction. For ChatGPT Desktop
  diagnostics, work inside Project `les-cloches` and use **New chat**; never
  reuse a conversation whose prior context could affect the result.
- Treat one visible application window as one serialized resource. Preserve
  the cross-process transaction lock and the single end-to-end deadline.
- Never restart a pre-existing desktop session without the caller's explicit
  `allow_restart_existing_session` permission.

## Architecture boundaries

- `src/les_cloches/transport.py` owns the shared transaction algorithm.
- `src/les_cloches/apps/linux/claude.py` and `apps/linux/chatgpt.py`
  independently own Linux/X11 application semantics and response-ownership
  rules. The corresponding modules under `apps/windows/` independently own
  the Windows UI Automation semantics and response-ownership rules.
- Do not introduce a shared adapter base class, selector DSL, plugin registry,
  or generic tree model merely for symmetry. Promote behavior into shared code
  only when it is genuinely identical and application-agnostic.
- Preserve fresh-chat isolation, exact response ownership, Markdown
  serialization, bounded completion polling, timeout cleanup, and recovery
  diagnostics when changing transport or adapter code.
- Prefer semantic controls and process ownership over geometry. Geometry may
  be observed for commissioning but must not become a correctness dependency.

## Platform truthfulness

- Linux/X11 is the only supported and commissioned platform. Keep the
  X11/XTEST clipboard backend explicit.
- Windows 11 is recognized but unverified and unsupported. Keep imports and
  status inspection graceful, but do not claim Windows compatibility or add
  an uncommissioned automatic fallback.
- Native Wayland write automation is unavailable under this project's
  semantic, coordinate-free, exact-verification requirements. Do not present
  it as a deferred or likely future backend.

## Testing and evidence

- Every test must have exactly one execution-scope marker: `easy` for isolated
  deterministic tests, `medium` for cross-module or OS-boundary tests, or
  `hard` for end-to-end desktop tests. Keep `live` as the independent opt-in
  safety marker for tests that control real applications.
- Run the non-live suite after code changes:

  ```bash
  .venv/bin/python -m pytest -q -m "not live"
  ```

- Live tests are opt-in and control real desktop applications. Run them only
  when the task authorizes desktop interaction, and do not use the desktop
  concurrently.
- A live stress test is proven only by persisted evidence. Record the app,
  Project/chat identity, fresh-chat status, prompt words/characters/bytes and
  hash, requested response size, actual response size, elapsed time, boundary
  sentinels, and pass/fail result. Distinguish a prepared harness or dry run
  from a completed live pass.
- Large-input and large-response claims must be reported separately. Do not
  infer a successful run from a script, bytecode cache, response fragment, or
  unsaved terminal output.
- Full commissioning and forced process-recovery runs can be disruptive. Do
  not run destructive recovery merely to strengthen documentation; require
  explicit authorization.

## Documentation

- Keep `README.md` authoritative for public behavior and platform status.
- Keep `ARCHITECTURE.md` focused on rationale and historical design choices;
  place instructions for future agents here instead of adding operational
  rules there.
- Keep `ISSUES.md` truthful about whether entries are active or resolved.
- Keep prior-art references generic in Markdown and comments rather than
  naming removed predecessor repositories or scripts.
- Apply repository language and framing rules to authored documentation,
  source, and comments. Generated stress-test inputs and captured model
  responses may preserve their original subject matter when retained as test
  evidence.
- Do not claim support, commissioning, test completion, or compatibility
  without corresponding evidence.

## Git attribution

- When Codex contributes materially to a commit, append this trailer to the
  commit message so GitHub attributes the contribution to `@codex`:

  ```text
  Co-authored-by: Codex <codex@openai.com>
  ```
- Keep the human contributor as the primary commit author.
