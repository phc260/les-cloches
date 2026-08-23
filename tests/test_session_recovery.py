import os
import signal
import subprocess

import pytest

from les_cloches.core.errors import LesClochesUnavailable
from les_cloches.core.session import (
    SessionOwnership,
    SessionState,
    terminate_owned_or_existing,
)

pytestmark = [
    pytest.mark.medium,
    pytest.mark.skipif(os.name == "nt", reason="POSIX signal recovery coverage"),
]


def test_preexisting_process_is_waited_for_before_relaunch(monkeypatch):
    pid = 4242
    signals = []
    waits = []

    def fake_kill(target, sig):
        signals.append((target, sig))

    def fake_wait(target, deadline, poll_interval=0.05):
        waits.append((target, deadline))
        return True

    monkeypatch.setattr(os, "kill", fake_kill)
    monkeypatch.setattr("les_cloches.core.session._wait_for_pid_exit", fake_wait)
    session = SessionState(ownership=SessionOwnership.PRE_EXISTING, existing_pid=pid)

    terminate_owned_or_existing(None, session, float("inf"), "Test Desktop")

    assert signals == [(pid, signal.SIGTERM)]
    assert waits and waits[0][0] == pid
    assert session.existing_pid is None
    assert session.recovery_target_pid == pid
    assert session.recovery_forced is False


def test_preexisting_process_escalates_after_grace_period(monkeypatch):
    pid = 4242
    signals = []
    wait_results = iter([False, True])

    monkeypatch.setattr(os, "kill", lambda target, sig: signals.append((target, sig)))
    monkeypatch.setattr(
        "les_cloches.core.session._wait_for_pid_exit",
        lambda target, deadline, poll_interval=0.05: next(wait_results),
    )
    session = SessionState(ownership=SessionOwnership.PRE_EXISTING, existing_pid=pid)

    terminate_owned_or_existing(None, session, float("inf"), "Test Desktop")

    assert signals == [(pid, signal.SIGTERM), (pid, signal.SIGKILL)]
    assert session.existing_pid is None
    assert session.recovery_target_pid == pid
    assert session.recovery_forced is True


def test_preexisting_process_must_be_gone_after_sigkill(monkeypatch):
    pid = 4242
    monkeypatch.setattr(os, "kill", lambda target, sig: None)
    monkeypatch.setattr("les_cloches.core.session._wait_for_pid_exit", lambda *args, **kwargs: False)
    session = SessionState(ownership=SessionOwnership.PRE_EXISTING, existing_pid=pid)

    with pytest.raises(LesClochesUnavailable, match=r"process 4242 remained alive after SIGKILL"):
        terminate_owned_or_existing(None, session, float("inf"), "Test Desktop")


def test_current_process_is_never_a_recovery_target():
    session = SessionState(ownership=SessionOwnership.PRE_EXISTING, existing_pid=os.getpid())
    with pytest.raises(LesClochesUnavailable, match="refusing to stop the current process"):
        terminate_owned_or_existing(None, session, float("inf"), "Test Desktop")


def test_bridge_owned_process_group_escalates_after_grace_period(monkeypatch):
    class OwnedProcess:
        pid = 5252

        def __init__(self):
            self.waits = 0

        def wait(self, timeout):
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired("test", timeout)
            return 0

    signals = []
    monkeypatch.setattr(os, "killpg", lambda target, sig: signals.append((target, sig)))
    process = OwnedProcess()

    terminate_owned_or_existing(process, SessionState(), float("inf"), "Test Desktop")

    assert signals == [(process.pid, signal.SIGTERM), (process.pid, signal.SIGKILL)]
