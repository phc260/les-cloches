import time

import pytest

from les_cloches.core.errors import LesClochesUnavailable
from les_cloches.core.session import SessionState, _terminate_owned_or_existing_windows

pytestmark = pytest.mark.medium


def test_windows_recovery_escalates_a_process_tree(monkeypatch):
    calls = []
    exits = iter([False, True])

    monkeypatch.setattr(
        "les_cloches.core.windows.terminate_process_tree",
        lambda pid, deadline, label, force: calls.append((pid, label, force)),
    )
    monkeypatch.setattr(
        "les_cloches.core.windows.wait_for_process_exit",
        lambda pid, deadline: next(exits),
    )
    session = SessionState(existing_pid=4242)

    _terminate_owned_or_existing_windows(None, session, time.monotonic() + 10, "Test Desktop")

    assert calls == [(4242, "Test Desktop", False), (4242, "Test Desktop", True)]
    assert session.recovery_target_pid == 4242
    assert session.recovery_forced is True
    assert session.existing_pid is None


def test_windows_recovery_requires_a_known_process_id():
    with pytest.raises(LesClochesUnavailable, match="did not expose its process id"):
        _terminate_owned_or_existing_windows(None, SessionState(), float("inf"), "Test Desktop")
