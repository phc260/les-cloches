"""The one shared transaction algorithm every Les Cloches adapter follows.

    locate application -> ensure ready -> open fresh conversation
        -> insert prompt -> verify exact match -> submit
        -> wait for bounded completion -> extract owned response

Everything above is generic and lives here. Everything below — what "ready,"
"fresh conversation," "submit," and "owned response" concretely mean for a
given application — is answered by a `DesktopAdapter` implementation in
`les_cloches.apps`. This module never inspects an accessibility tree itself;
it only calls adapter operations and enforces the deadline, the cross-process
lock, bounded recovery, and the exact-prompt-verification invariant around
them.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Protocol

from .core.deadlines import deadline_from, wait_for
from .core.errors import LesClochesError, LesClochesTimeout
from .core.recovery import FailureDiagnostic, HealthSnapshot, ensure_ready
from .core.session import SessionState, TransactionLock, TransactionPhase, default_lock_path

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class TransactionState:
    """One application-owned reading of generation progress, taken in a
    single traversal so polling does not re-walk the accessibility tree
    three times per tick."""

    generating: bool
    complete: bool
    response: str


class DesktopAdapter(Protocol):
    """The semantic contract the shared transport expects an application
    adapter to satisfy. See the platform-specific implementations under
    `les_cloches/apps/linux/` and `les_cloches/apps/windows/`; nothing here
    assumes they share an accessibility-tree shape."""

    desktop_label: str

    def health_snapshot(self) -> HealthSnapshot: ...
    def launch(self, deadline: float) -> None: ...
    def terminate_for_recovery(self, session: SessionState, deadline: float) -> None: ...
    def existing_process_id(self) -> "int | None": ...

    def open_fresh_conversation(self, deadline: float): ...
    def insert_prompt(self, input_backend, editor, prompt: str, deadline: float): ...
    def editor_matches(self, editor, prompt: str) -> bool: ...
    def submit(self, editor, deadline: float) -> None: ...

    def transaction_state(self) -> TransactionState: ...
    def try_stop(self) -> None: ...


def wait_for_completion(adapter: DesktopAdapter, deadline: float, stable_interval: float = 0.8, *, poll_interval: float = 0.05) -> str:
    """Poll `adapter.transaction_state()` until generation is complete and the
    response text has been stable for `stable_interval`. Exposed for reuse by
    commissioning helpers that submit within an already-open conversation."""
    last_candidate = ""
    unchanged_since = time.monotonic()
    response_started = False
    while time.monotonic() < deadline:
        state = adapter.transaction_state()
        response_started = response_started or state.generating or bool(state.response)
        if state.response != last_candidate:
            last_candidate = state.response
            unchanged_since = time.monotonic()
        stable = time.monotonic() - unchanged_since >= stable_interval
        if response_started and state.complete and not state.generating and stable:
            return state.response
        time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))
    raise LesClochesTimeout(f"timed out waiting for {adapter.desktop_label} generation to complete")


def _bridge_version(package_name: str) -> str:
    try:
        return version(package_name)
    except PackageNotFoundError:
        return "development"


def _attach_diagnostic(exc: BaseException, adapter: DesktopAdapter, session: SessionState, package_name: str) -> None:
    snapshot = adapter.health_snapshot()
    diagnostic = FailureDiagnostic(
        phase=session.phase.name,
        health=snapshot.health.name,
        elapsed_seconds=round(time.monotonic() - session.started_at, 3),
        application_found=snapshot.application_found,
        frame_found=snapshot.frame_found,
        document_found=snapshot.document_found,
        fresh_conversation_control_found=snapshot.fresh_conversation_control_found,
        editor_found=snapshot.editor_found,
        submit_control_found=snapshot.submit_control_found,
        visible_turn_count=snapshot.visible_turn_count,
        recovery_attempted=session.recovery_attempted,
        session_ownership=session.ownership.name,
        bridge_version=_bridge_version(package_name),
    )
    setattr(exc, "diagnostic", diagnostic)
    LOG.error(
        "%s transaction failed: %s",
        adapter.desktop_label,
        json.dumps(asdict(diagnostic), sort_keys=True),
    )


def send(
    adapter: DesktopAdapter,
    input_backend,
    prompt: str,
    timeout: float,
    *,
    lock_path: "str | None" = None,
    allow_restart_existing_session: bool = False,
    poll_interval: float = 1.0,
    prompt_poll_interval: float = 0.1,
    completion_poll_interval: float = 0.05,
    stable_interval: float = 0.8,
    package_name: str = "les-cloches",
) -> str:
    if not isinstance(prompt, str):
        raise TypeError("prompt must be a str")
    if not prompt:
        raise ValueError("prompt must not be empty")
    if timeout <= 0:
        raise ValueError("timeout must be positive")

    deadline = deadline_from(timeout)
    label = adapter.desktop_label.casefold().replace(" ", "-")
    lock = TransactionLock(lock_path or default_lock_path(label))
    lock.acquire(deadline)
    session = SessionState()
    try:
        if deadline - time.monotonic() <= 0:
            raise LesClochesTimeout("transaction deadline expired after lock acquisition")

        session.phase = TransactionPhase.CHECKING_HEALTH
        ensure_ready(
            adapter,
            session,
            deadline,
            allow_restart_existing_session=allow_restart_existing_session,
            poll_interval=poll_interval,
        )

        session.phase = TransactionPhase.OPENING_FRESH_CONVERSATION
        editor = adapter.open_fresh_conversation(deadline)

        session.phase = TransactionPhase.LOCATING_EDITOR
        session.phase = TransactionPhase.INSERTING_PROMPT
        editor = adapter.insert_prompt(input_backend, editor, prompt, deadline)

        session.phase = TransactionPhase.VERIFYING_PROMPT
        wait_for(
            deadline,
            f"the exact prompt in {adapter.desktop_label}'s editor accessibility subtree",
            lambda: adapter.editor_matches(editor, prompt),
            poll_interval=prompt_poll_interval,
        )

        session.phase = TransactionPhase.SUBMITTING
        adapter.submit(editor, deadline)

        session.phase = TransactionPhase.WAITING_FOR_COMPLETION
        response = wait_for_completion(adapter, deadline, stable_interval, poll_interval=completion_poll_interval)

        session.phase = TransactionPhase.EXTRACTING_RESPONSE
        if not response:
            raise LesClochesError(f"{adapter.desktop_label}'s assistant response contained no text")
        session.phase = TransactionPhase.DONE
        if not isinstance(response, str):
            raise TypeError("adapter returned a non-string response")
        return response
    except LesClochesTimeout as exc:
        adapter.try_stop()
        _attach_diagnostic(exc, adapter, session, package_name)
        raise
    except Exception as exc:
        _attach_diagnostic(exc, adapter, session, package_name)
        raise
    finally:
        lock.release()
