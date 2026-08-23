"""Application-agnostic evidence recording for Windows commissioning."""

from __future__ import annotations

import hashlib
import json
import platform
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from les_cloches import transport
from les_cloches.core.platforms import current_platform_support
from les_cloches.input.windows import WindowsClipboardInput


def _record(adapter, input_backend, prompt: str, expected: str, identity: str, timeout: float) -> dict:
    started = time.monotonic()
    result = {
        "app": adapter.desktop_label,
        "identity": identity,
        "fresh_chat": True,
        "prompt_words": len(prompt.split()),
        "prompt_characters": len(prompt),
        "prompt_bytes": len(prompt.encode("utf-8")),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "requested_response": expected,
        "requested_response_characters": len(expected),
        "prompt_boundary_sentinels": [prompt[:24], prompt[-24:]],
    }
    try:
        response = transport.send(
            adapter,
            input_backend,
            prompt,
            timeout,
            completion_poll_interval=0.1,
        )
        result.update(
            {
                "actual_response": response,
                "actual_response_characters": len(response),
                "actual_response_bytes": len(response.encode("utf-8")),
                "actual_response_sha256": hashlib.sha256(response.encode("utf-8")).hexdigest(),
                "response_boundary_sentinels": [response[:24], response[-24:]],
                "pass": response == expected,
            }
        )
    except Exception as exc:
        result.update(
            {
                "pass": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "diagnostic": getattr(getattr(exc, "diagnostic", None), "__dict__", None),
            }
        )
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return result


def run_windows_commissioning(
    *,
    adapter_factory: Callable[[], object],
    identity: str,
    sentinel_prefix: str,
    timeout: float,
    output: Path,
) -> int:
    """Run one app-specific transaction and persist its commissioning evidence."""

    status = current_platform_support()
    if status.platform != "Windows 11":
        raise SystemExit(f"Windows 11 is required, found {status.platform}")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sentinel = f"{sentinel_prefix}_{timestamp}"
    prompt = f"Reply with exactly: {sentinel}"
    record = _record(
        adapter_factory(),
        WindowsClipboardInput(),
        prompt,
        sentinel,
        identity,
        timeout,
    )
    evidence = {
        "schema": "les-cloches-windows-commissioning-v1",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "platform_support": asdict(status),
        "desktop_interaction_authorized": True,
        "results": [record],
        "pass": record["pass"],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2, ensure_ascii=True))
    return 0 if evidence["pass"] else 1
