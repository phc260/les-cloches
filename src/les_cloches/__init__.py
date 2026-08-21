"""Les Cloches: semantic desktop automation for corresponding with AI
applications through their visible interfaces.

    from les_cloches import Claude, ChatGPT

    claude = Claude()
    reply = claude.send("Reply with exactly: PONG")

    chatgpt = ChatGPT()
    reply = chatgpt.send("Reply with exactly: PONG")

v0.1 supports Claude Desktop and ChatGPT Desktop on Linux/X11 only. Windows
11 is recognized but unverified and unsupported. See README.md for the
mechanism and ARCHITECTURE.md for why it is shaped this way.
"""

from __future__ import annotations

from . import transport as _transport
from .apps.chatgpt import ChatGPTAdapter, ChatGPTSemantics
from .apps.claude import ClaudeAdapter
from .core.errors import (
    LesClochesBusy,
    LesClochesError,
    LesClochesTimeout,
    LesClochesUnavailable,
    NodeNotFoundError,
    UnsupportedPlatform,
)
from .core.platforms import PlatformSupport, current_platform_support, require_supported_platform
from .input.x11 import X11ClipboardInput

__all__ = [
    "Claude",
    "ChatGPT",
    "ChatGPTSemantics",
    "LesClochesBusy",
    "LesClochesError",
    "LesClochesTimeout",
    "LesClochesUnavailable",
    "NodeNotFoundError",
    "PlatformSupport",
    "UnsupportedPlatform",
    "current_platform_support",
]


class Claude:
    """Send a prompt to Claude Desktop and return its exact response text."""

    def __init__(
        self,
        *,
        allow_restart_existing_session: bool = False,
        lock_path: "str | None" = None,
    ) -> None:
        require_supported_platform()
        self._adapter = ClaudeAdapter()
        self._input = X11ClipboardInput()
        self._allow_restart_existing_session = allow_restart_existing_session
        self._lock_path = lock_path

    def send(self, prompt: str, timeout: float = 120.0) -> str:
        return _transport.send(
            self._adapter,
            self._input,
            prompt,
            timeout,
            lock_path=self._lock_path,
            allow_restart_existing_session=self._allow_restart_existing_session,
        )


class ChatGPT:
    """Send a prompt to ChatGPT Desktop and return its exact response text."""

    def __init__(
        self,
        *,
        allow_restart_existing_session: bool = False,
        lock_path: "str | None" = None,
        semantics: "ChatGPTSemantics | None" = None,
    ) -> None:
        require_supported_platform()
        self._adapter = ChatGPTAdapter(semantics=semantics)
        self._input = X11ClipboardInput()
        self._allow_restart_existing_session = allow_restart_existing_session
        self._lock_path = lock_path

    def send(self, prompt: str, timeout: float = 120.0) -> str:
        return _transport.send(
            self._adapter,
            self._input,
            prompt,
            timeout,
            lock_path=self._lock_path,
            allow_restart_existing_session=self._allow_restart_existing_session,
        )
