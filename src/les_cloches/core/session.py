"""Cross-process serialization and per-transaction session state.

A visible desktop application is a serialized resource: one caller owns a UI
transaction at a time, others wait. `TransactionLock` is the advisory,
per-user, cross-process lock that enforces this. `SessionState` tracks
whether the current process launched the application (and may therefore
restart it during recovery) or found it already running (and must not
restart it without explicit opt-in).
"""

from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path

from .errors import LesClochesBusy, LesClochesTimeout, LesClochesUnavailable

try:
    import fcntl
except ImportError:  # Windows: recognized, but no commissioned lock/backend.
    fcntl = None


class SessionOwnership(Enum):
    UNKNOWN = auto()
    BRIDGE_OWNED = auto()
    PRE_EXISTING = auto()


class TransactionPhase(Enum):
    CHECKING_HEALTH = auto()
    STARTING_APPLICATION = auto()
    OPENING_FRESH_CONVERSATION = auto()
    LOCATING_EDITOR = auto()
    INSERTING_PROMPT = auto()
    VERIFYING_PROMPT = auto()
    SUBMITTING = auto()
    WAITING_FOR_COMPLETION = auto()
    EXTRACTING_RESPONSE = auto()
    DONE = auto()


@dataclass
class SessionState:
    """Per-transport, cross-transaction bookkeeping for one application."""

    ownership: SessionOwnership = SessionOwnership.UNKNOWN
    owned_process: "subprocess.Popen | None" = None
    existing_pid: "int | None" = None
    phase: TransactionPhase = TransactionPhase.CHECKING_HEALTH
    recovery_attempted: bool = False
    recovery_target_pid: "int | None" = None
    recovery_forced: bool = False
    started_at: float = field(default_factory=time.monotonic)

    def reset_for_transaction(self) -> None:
        self.phase = TransactionPhase.CHECKING_HEALTH
        self.recovery_attempted = False
        self.recovery_target_pid = None
        self.recovery_forced = False
        self.started_at = time.monotonic()


class TransactionLock:
    """Advisory per-user, cross-process lock for one visible application."""

    def __init__(self, path: "str | os.PathLike[str] | None" = None, poll_interval: float = 0.05):
        self.path = Path(path) if path else None
        self.poll_interval = poll_interval
        self._file = None

    def acquire(self, deadline: float) -> None:
        if self.path is None:
            raise ValueError("TransactionLock requires a path")
        if fcntl is None:
            from .errors import UnsupportedPlatform

            raise UnsupportedPlatform(
                "Windows cross-process desktop locking is recognized but unverified "
                "and unsupported; no lock or desktop action was attempted."
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = self.path.open("a+")
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                lock_file.seek(0)
                lock_file.truncate()
                lock_file.write(f"pid={os.getpid()}\n")
                lock_file.flush()
                self._file = lock_file
                return
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    lock_file.close()
                    raise LesClochesBusy("timed out waiting for the transaction lock")
                time.sleep(min(self.poll_interval, remaining))
            except BaseException:
                lock_file.close()
                raise

    def release(self) -> None:
        if self._file is not None:
            try:
                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            finally:
                self._file.close()
                self._file = None

    def __enter__(self):
        raise TypeError("use acquire(deadline) before entering a transaction")

    def __exit__(self, *_args) -> None:
        self.release()


def default_lock_path(label: str) -> str:
    user_token = (
        str(os.getuid()) if hasattr(os, "getuid") else os.environ.get("USERNAME", "unknown")
    )
    return str(Path(tempfile.gettempdir()) / f"les-cloches-{label}-{user_token}.lock")


def terminate_owned_or_existing(
    owned_process: "subprocess.Popen | None", session: SessionState, deadline: float, label: str
) -> None:
    """Stop what we launched, or the pre-existing process the caller opted
    in to restart, before recovery launches a replacement.

    Identical between the Claude and ChatGPT adapters — the only
    application-specific part is which process handle `owned_process` is.

    Electron applications enforce single-instance ownership.  Relaunching
    while the old process is still alive merely hands the request back to
    that process, so sending SIGTERM without waiting is not sufficient.
    Give the process a bounded graceful-stop window, then use SIGKILL and
    confirm that the target is gone before returning to the recovery loop.
    """
    if owned_process is not None:
        session.recovery_target_pid = owned_process.pid
        try:
            os.killpg(owned_process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        graceful_deadline = _graceful_stop_deadline(deadline)
        try:
            owned_process.wait(timeout=max(0.0, graceful_deadline - time.monotonic()))
            return
        except subprocess.TimeoutExpired:
            session.recovery_forced = True
            try:
                os.killpg(owned_process.pid, signal.SIGKILL)
            except ProcessLookupError:
                return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise LesClochesTimeout(f"deadline expired while force-stopping {label} for recovery")
        try:
            owned_process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            raise LesClochesUnavailable(
                f"bridge-owned {label} process group {owned_process.pid} remained alive after SIGKILL"
            ) from exc
    elif session.existing_pid:
        pid = session.existing_pid
        session.recovery_target_pid = pid
        if pid == os.getpid():
            raise LesClochesUnavailable(f"refusing to stop the current process while recovering {label}")
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            session.existing_pid = None
            return
        except PermissionError as exc:
            raise LesClochesUnavailable(
                f"permission denied while stopping pre-existing {label} process {pid}"
            ) from exc

        if not _wait_for_pid_exit(pid, _graceful_stop_deadline(deadline)):
            session.recovery_forced = True
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                session.existing_pid = None
                return
            except PermissionError as exc:
                raise LesClochesUnavailable(
                    f"permission denied while force-stopping pre-existing {label} process {pid}"
                ) from exc
            if not _wait_for_pid_exit(pid, deadline):
                raise LesClochesUnavailable(
                    f"pre-existing {label} process {pid} remained alive after SIGKILL"
                )
        session.existing_pid = None
    else:
        raise LesClochesUnavailable(
            f"cannot restart pre-existing {label}: AT-SPI did not expose its process id"
        )


def _graceful_stop_deadline(deadline: float, maximum_grace: float = 5.0) -> float:
    """Reserve at least half of the remaining transaction time for SIGKILL
    confirmation and relaunch while allowing up to five seconds for SIGTERM."""
    now = time.monotonic()
    remaining = max(0.0, deadline - now)
    return min(deadline, now + min(maximum_grace, remaining / 2))


def _wait_for_pid_exit(pid: int, deadline: float, poll_interval: float = 0.05) -> bool:
    """Wait until a non-child process disappears, bounded by `deadline`."""
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            # The process still exists even though this user cannot signal it.
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(poll_interval, remaining))
