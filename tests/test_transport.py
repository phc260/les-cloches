import multiprocessing
import time

import pytest

from les_cloches.core.errors import LesClochesBusy
from les_cloches.core.recovery import HealthSnapshot, RendererHealth
from les_cloches.core.session import TransactionLock
from les_cloches.transport import TransactionState, send


class FakeAdapter:
    desktop_label = "Fake Desktop"

    def __init__(self, response="ok"):
        self.response = response
        self.calls = []
        self.deadlines = []

    def health_snapshot(self):
        return HealthSnapshot(RendererHealth.READY, True, True, True, True, True, True, 0)

    def launch(self):
        pass

    def terminate_for_recovery(self, session, deadline):
        pass

    def existing_process_id(self):
        return None

    def open_fresh_conversation(self, deadline):
        self.deadlines.append(deadline)
        return object()

    def insert_prompt(self, input_backend, editor, prompt, deadline):
        self.calls.append(("insert_prompt", prompt))
        return editor

    def editor_matches(self, editor, prompt):
        return True

    def submit(self, editor, deadline):
        self.calls.append(("submit",))

    def transaction_state(self):
        return TransactionState(generating=False, complete=True, response=self.response)

    def try_stop(self):
        self.calls.append(("try_stop",))


class FakeInputBackend:
    pass


def test_send_delegates_and_returns_exact_string(tmp_path):
    adapter = FakeAdapter("AVFD_PONG")
    result = send(adapter, FakeInputBackend(), "ping", 3.5, lock_path=str(tmp_path / "lock"), stable_interval=0)
    assert result == "AVFD_PONG"
    assert ("insert_prompt", "ping") in adapter.calls


@pytest.mark.parametrize("prompt", ["", None, 42])
def test_invalid_prompt_rejected(tmp_path, prompt):
    with pytest.raises((TypeError, ValueError)):
        send(FakeAdapter(), FakeInputBackend(), prompt, 3.5, lock_path=str(tmp_path / "lock"))


@pytest.mark.parametrize("timeout", [0, -1])
def test_invalid_timeout_rejected(tmp_path, timeout):
    with pytest.raises(ValueError):
        send(FakeAdapter(), FakeInputBackend(), "hello", timeout, lock_path=str(tmp_path / "lock"))


def test_non_string_response_is_rejected(tmp_path):
    with pytest.raises(TypeError):
        send(
            FakeAdapter(response=42),
            FakeInputBackend(),
            "hello",
            3.5,
            lock_path=str(tmp_path / "lock"),
            stable_interval=0,
        )


def test_lock_released_after_adapter_exception(tmp_path):
    class BrokenAdapter(FakeAdapter):
        def open_fresh_conversation(self, deadline):
            raise RuntimeError("broken")

    path = str(tmp_path / "bridge.lock")
    with pytest.raises(RuntimeError):
        send(BrokenAdapter(), FakeInputBackend(), "hello", 3.5, lock_path=path)
    result = send(FakeAdapter("recovered"), FakeInputBackend(), "hello", 3.5, lock_path=path, stable_interval=0)
    assert result == "recovered"


def _hold_lock(path, ready):
    lock = TransactionLock(path)
    lock.acquire(time.monotonic() + 2)
    ready.set()
    time.sleep(0.4)
    lock.release()


def test_cross_process_lock_has_bounded_busy_error(tmp_path):
    path = str(tmp_path / "bridge.lock")
    ready = multiprocessing.Event()
    process = multiprocessing.Process(target=_hold_lock, args=(path, ready))
    process.start()
    assert ready.wait(1)
    try:
        with pytest.raises(LesClochesBusy):
            send(FakeAdapter(), FakeInputBackend(), "hello", 0.05, lock_path=path)
    finally:
        process.join(2)
    assert process.exitcode == 0


def test_lock_wait_consumes_shared_deadline(tmp_path):
    path = str(tmp_path / "bridge.lock")
    ready = multiprocessing.Event()
    process = multiprocessing.Process(target=_hold_lock, args=(path, ready))
    process.start()
    assert ready.wait(1)
    adapter = FakeAdapter()
    try:
        send(adapter, FakeInputBackend(), "hello", 1.0, lock_path=path, stable_interval=0)
    finally:
        process.join(2)
    assert adapter.deadlines[0] - time.monotonic() < 0.8
