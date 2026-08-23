"""Exception hierarchy shared by every Les Cloches application adapter."""

from __future__ import annotations


class LesClochesError(RuntimeError):
    """Base error for deterministic Les Cloches failures."""


class LesClochesTimeout(LesClochesError, TimeoutError):
    """The desktop did not reach the required state before the hard deadline."""


class LesClochesBusy(LesClochesTimeout):
    """The transaction lock was not acquired before the caller's deadline."""


class LesClochesUnavailable(LesClochesError):
    """The target application or its accessible renderer is unavailable."""

    def __init__(self, message: str, diagnostic=None) -> None:
        super().__init__(message)
        self.diagnostic = diagnostic


class UnsupportedPlatform(LesClochesError):
    """Les Cloches was asked to run write automation outside its supported platform.

    v0.1 supports Linux/X11 only. Windows 11 is recognized and has an
    uncommissioned backend under development; native Wayland write automation
    is unavailable under the project's constraints. Les Cloches states this
    plainly instead of silently degrading to a different input path.
    """


class NodeNotFoundError(LesClochesError):
    """The application's accessibility tree did not expose a required semantic node."""
