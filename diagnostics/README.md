# Diagnostic tools

This directory contains development and investigation tools for understanding
desktop accessibility behavior, reproducing bounded edge cases, and collecting
failure evidence. Diagnostic results do not establish platform support or
commissioning.

The repository separates these roles:

| Directory | Role |
|---|---|
| `src/` | Installable runtime behavior |
| `tests/` | Deterministic contract verification |
| `commissioning/` | Formal live acceptance with persisted pass/fail evidence |
| `diagnostics/` | Investigation of unknown behavior and failures |

## Tools

| Tool | Interaction | Output | Purpose |
|---|---|---|---|
| `dump_atspi.py` | Read-only Linux/AT-SPI inspection | Text on stdout | Inspect an application's semantic accessibility tree; use `--redact-text` when content may be sensitive |
| `dump_uia.py` | Read-only Windows/UIA inspection | Required text file | Inspect a bounded UIA tree without streaming it into the inspected desktop application |
| `probe_accessibility.py` | Read-only AT-SPI or UIA inspection | JSON file | Collect bounded, content-free node counts and process metadata in a timeout-controlled child process |
| `probe_claude_paste_threshold.py` | Live Claude Desktop control | Console measurements | Determine when pasted text changes from inline editor content into an attachment |
| `stress_chatgpt_long_prompt.py` | Live ChatGPT Desktop control unless `--dry-run` | Console measurements | Verify exact transport of a deterministic large prompt and a short exact response |
| `stress_chatgpt_long_roundtrip.py` | Live Claude or ChatGPT Desktop control unless `--dry-run` | Markdown response plus console measurements | Exercise a large input and large response with boundary sentinels |
| `configure_crash_capture.ps1` | Administrative Windows registry change | JSON file | Record and change crash-capture settings; `-Restore` applies the script's configured baseline values |

Run scripts from the repository root. Examples:

```bash
python diagnostics/probe_accessibility.py \
  --backend atspi \
  --target "claude-desktop" \
  --output diagnostics/claude-atspi-probe.json
```

```powershell
python diagnostics\dump_uia.py `
  --window "^Claude$" `
  --max-depth 22 `
  --node-limit 2000 `
  --redact-text `
  --output diagnostics\claude-uia-tree.txt
```

Use the environment setup documented in the [root README](../README.md); Linux
AT-SPI tools require the system GI bindings.

## Generated outputs

Generated diagnostic outputs are local by default and are ignored by
`.gitignore`:

- JSON for structured reports and configuration evidence
- text for raw accessibility-tree dumps
- Markdown for captured model responses or human analysis
- HTML for operating-system-generated reports
- logs for command output
- temporary files left by an interrupted atomic write

For new or revised diagnostics, prefer one JSON report as the canonical
execution record. When the natural payload is text, Markdown, or HTML, the
JSON report should reference that artifact by path and SHA-256 instead of
embedding it.

`README.md` is explicitly exempted so permanent directory documentation stays
trackable. Files already tracked by Git remain tracked even when their
extension matches an ignore rule.

Console output is useful for progress but is not persisted evidence. A raw
response, tree fragment, or report file alone must not be treated as proof of a
completed stress test or platform commissioning. If diagnostic evidence is
intentionally retained, preserve the complete metadata required by
[AGENTS.md](../AGENTS.md), including application and chat identity, fresh-chat
status, prompt sizes and hash, requested and actual response sizes, elapsed
time, boundary sentinels, and pass/fail result.

## Safety

- Tools marked live control real desktop applications. Run them only with
  explicit authorization and do not use the target desktop concurrently.
- Open a fresh conversation for every transaction. For ChatGPT diagnostics,
  work inside Project `les-cloches` and use **New chat**.
- Never restart a pre-existing desktop session unless the caller explicitly
  permits it with `--allow-restart-existing-session`.
- Prefer bounded, content-free `probe_accessibility.py` when a full tree is not
  necessary. Full tree dumps may expose visible conversation text; use
  redaction and write output to a file.
- `configure_crash_capture.ps1` changes machine-wide Windows settings, requires
  administrator privileges, and must not be run without explicit permission.
- Do not use coordinates, screenshots/OCR, browser/CDP automation, private
  APIs, or authentication/session extraction in diagnostics.
