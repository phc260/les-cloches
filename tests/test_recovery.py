from dataclasses import asdict

import pytest

from les_cloches.core.errors import LesClochesUnavailable
from les_cloches.core.recovery import (
    FailureDiagnostic,
    HealthSnapshot,
    RendererHealth,
    ensure_ready,
)
from les_cloches.core.session import SessionOwnership, SessionState


def snapshot(health):
    return HealthSnapshot(
        health=health,
        application_found=health is not RendererHealth.PROCESS_ABSENT,
        frame_found=health is not RendererHealth.PROCESS_ABSENT,
        document_found=health in {RendererHealth.DOCUMENT_LOADING, RendererHealth.READY},
        fresh_conversation_control_found=health is RendererHealth.READY,
        editor_found=health is RendererHealth.READY,
        submit_control_found=False,
        visible_turn_count=0,
    )


class PolicyApp:
    def __init__(self, states):
        self.states = iter(states)
        self.current = snapshot(states[-1])
        self.launches = 0
        self.terminations = 0

    def health_snapshot(self):
        try:
            self.current = snapshot(next(self.states))
        except StopIteration:
            pass
        return self.current

    def launch(self):
        self.launches += 1

    def terminate_for_recovery(self, session, deadline):
        self.terminations += 1

    def existing_process_id(self):
        return None


def test_bridge_owned_renderer_restarts_exactly_once():
    app = PolicyApp([RendererHealth.FRAME_ONLY, RendererHealth.FRAME_ONLY, RendererHealth.READY])
    session = SessionState(ownership=SessionOwnership.BRIDGE_OWNED)
    ensure_ready(app, session, float("inf"), allow_restart_existing_session=False, poll_interval=0)
    assert app.terminations == 1
    assert app.launches == 1
    assert session.recovery_attempted is True


def test_failed_recovery_never_restarts_twice():
    import time

    app = PolicyApp([RendererHealth.FRAME_ONLY, RendererHealth.FRAME_ONLY, RendererHealth.FRAME_ONLY])
    session = SessionState(ownership=SessionOwnership.BRIDGE_OWNED)
    # The renderer never becomes healthy, so `_wait_ready` genuinely exhausts
    # the deadline; use a short, finite one instead of the fixed 3-iteration
    # bound the old inheritance-based fake used.
    deadline = time.monotonic() + 0.05
    with pytest.raises(LesClochesUnavailable):
        ensure_ready(app, session, deadline, allow_restart_existing_session=False, poll_interval=0.01)
    assert app.terminations == app.launches == 1


def test_user_owned_unhealthy_renderer_is_protected_by_default():
    app = PolicyApp([RendererHealth.FRAME_ONLY])
    session = SessionState(ownership=SessionOwnership.PRE_EXISTING)
    with pytest.raises(LesClochesUnavailable):
        ensure_ready(app, session, float("inf"), allow_restart_existing_session=False, poll_interval=0)
    assert app.terminations == app.launches == 0


def test_user_owned_restart_requires_explicit_option():
    app = PolicyApp([RendererHealth.FRAME_ONLY, RendererHealth.READY])
    session = SessionState(ownership=SessionOwnership.PRE_EXISTING)
    ensure_ready(app, session, float("inf"), allow_restart_existing_session=True, poll_interval=0)
    assert app.terminations == app.launches == 1


def test_failure_diagnostic_is_narrow_and_structural():
    diagnostic = FailureDiagnostic(
        phase="LOCATING_EDITOR",
        health="FRAME_ONLY",
        elapsed_seconds=1.2,
        application_found=True,
        frame_found=True,
        document_found=False,
        fresh_conversation_control_found=False,
        editor_found=False,
        submit_control_found=False,
        visible_turn_count=0,
        recovery_attempted=True,
        session_ownership="BRIDGE_OWNED",
        bridge_version="0.1.0",
    )
    fields = asdict(diagnostic)
    assert "prompt" not in fields
    assert "conversation" not in fields
    assert fields["health"] == "FRAME_ONLY"


def test_recovery_refuses_to_relaunch_when_preexisting_pid_is_unknown():
    class MissingPidApp(PolicyApp):
        def terminate_for_recovery(self, session, deadline):
            from les_cloches.core.session import terminate_owned_or_existing

            terminate_owned_or_existing(None, session, deadline, "Test Desktop")

    app = MissingPidApp([RendererHealth.FRAME_ONLY])
    session = SessionState(ownership=SessionOwnership.PRE_EXISTING)
    with pytest.raises(LesClochesUnavailable, match="did not expose its process id"):
        ensure_ready(app, session, float("inf"), allow_restart_existing_session=True, poll_interval=0)
    assert app.launches == 0
