"""Monotonic deadline helpers shared by every adapter.

Every long-running operation in Les Cloches is bounded by a single monotonic
deadline computed once at the start of a transaction. Lock waiting, renderer
startup/recovery, UI operations, and response extraction all share it: there
are no independent, additive timeouts hiding inside adapters.
"""

from __future__ import annotations

import time
from typing import Callable, TypeVar

from .errors import LesClochesTimeout

T = TypeVar("T")


def deadline_from(timeout: float) -> float:
    return time.monotonic() + timeout


def remaining(deadline: float) -> float:
    return deadline - time.monotonic()


def expired(deadline: float) -> bool:
    return time.monotonic() >= deadline


def sleep_until(deadline: float, interval: float) -> None:
    time.sleep(min(interval, max(0.0, remaining(deadline))))


def wait_for(
    deadline: float,
    description: str,
    probe: Callable[[], T],
    *,
    poll_interval: float = 1.0,
) -> T:
    """Poll `probe` until it returns a truthy value or the deadline expires."""
    while time.monotonic() < deadline:
        value = probe()
        if value:
            return value
        sleep_until(deadline, poll_interval)
    raise LesClochesTimeout(f"timed out waiting for {description}")
