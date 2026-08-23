"""Bounded, deadline-scoped recovery for an unhealthy application renderer.

This module knows nothing about Claude or ChatGPT. It asks an adapter for a
`HealthSnapshot`, and if the renderer is not ready it asks the adapter to
launch or restart the application, retrying recovery exactly once per
transaction before giving up. A pre-existing (user-owned) session is never
restarted unless the caller explicitly opts in.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Protocol

from .errors import LesClochesTimeout, LesClochesUnavailable
from .session import SessionOwnership, SessionState


class RendererHealth(Enum):
    PROCESS_ABSENT = auto()
    FRAME_ONLY = auto()
    DOCUMENT_LOADING = auto()
    READY = auto()


@dataclass(frozen=True)
class HealthSnapshot:
    """A generic, application-agnostic reading of renderer readiness.

    Field names describe roles that both Claude and ChatGPT expose
    (a window/frame, a loaded document, a control that starts a fresh
    conversation, an editable prompt editor) without naming either
    application's concrete accessibility-tree shape.
    """

    health: RendererHealth
    application_found: bool
    frame_found: bool
    document_found: bool
    fresh_conversation_control_found: bool
    editor_found: bool
    submit_control_found: bool
    visible_turn_count: int


@dataclass(frozen=True)
class FailureDiagnostic:
    phase: str
    health: str
    elapsed_seconds: float
    application_found: bool
    frame_found: bool
    document_found: bool
    fresh_conversation_control_found: bool
    editor_found: bool
    submit_control_found: bool
    visible_turn_count: int
    recovery_attempted: bool
    session_ownership: str
    bridge_version: str


class RecoverableApplication(Protocol):
    """The narrow contract `ensure_ready` needs from an application adapter."""

    def health_snapshot(self) -> HealthSnapshot: ...
    def launch(self, deadline: float) -> None: ...
    def terminate_for_recovery(self, session: SessionState, deadline: float) -> None: ...
    def existing_process_id(self) -> "int | None": ...


def record_ownership(session: SessionState, snapshot: HealthSnapshot, existing_pid) -> None:
    if session.ownership is not SessionOwnership.UNKNOWN:
        return
    if snapshot.application_found:
        session.ownership = SessionOwnership.PRE_EXISTING
        session.existing_pid = existing_pid


def _wait_ready(app: RecoverableApplication, deadline: float, poll_interval: float) -> bool:
    while time.monotonic() < deadline:
        snapshot = app.health_snapshot()
        if snapshot.health is RendererHealth.READY:
            return True
        time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))
    return False


def ensure_ready(
    app: RecoverableApplication,
    session: SessionState,
    deadline: float,
    *,
    allow_restart_existing_session: bool,
    poll_interval: float = 1.0,
) -> None:
    """Bring the application to a READY renderer, recovering at most once."""
    snapshot = app.health_snapshot()
    record_ownership(session, snapshot, app.existing_process_id())

    if snapshot.health is RendererHealth.PROCESS_ABSENT:
        app.launch(deadline)
        session.ownership = SessionOwnership.BRIDGE_OWNED
        if _wait_ready(app, deadline, poll_interval):
            return
        snapshot = app.health_snapshot()
    elif snapshot.health is RendererHealth.READY:
        return
    elif snapshot.health is RendererHealth.DOCUMENT_LOADING:
        grace = min(deadline, time.monotonic() + min(2.0, max(0.0, (deadline - time.monotonic()) / 3)))
        if _wait_ready(app, grace, poll_interval):
            return
        snapshot = app.health_snapshot()

    if snapshot.health is RendererHealth.READY:
        return

    if session.ownership is SessionOwnership.PRE_EXISTING and not allow_restart_existing_session:
        raise LesClochesUnavailable(
            "the application renderer is unhealthy; the pre-existing session was not restarted"
        )

    session.recovery_attempted = True
    if deadline - time.monotonic() <= 0:
        raise LesClochesTimeout("deadline expired before recovery could begin")
    app.terminate_for_recovery(session, deadline)
    app.launch(deadline)
    session.ownership = SessionOwnership.BRIDGE_OWNED
    if not _wait_ready(app, deadline, poll_interval):
        final_snapshot = app.health_snapshot()
        current_pid = app.existing_process_id()
        raise LesClochesUnavailable(
            "the renderer remained unavailable after one recovery attempt "
            f"(target_pid={session.recovery_target_pid}, forced={session.recovery_forced}, "
            f"current_pid={current_pid}, health={final_snapshot.health.name})"
        )
