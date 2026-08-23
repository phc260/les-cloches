"""Explicit platform classification for the public desktop API.

Platform awareness is deliberately separate from commissioning status.
"""

from __future__ import annotations

import os
import platform
import re
from dataclasses import dataclass

from .errors import UnsupportedPlatform


@dataclass(frozen=True)
class PlatformSupport:
    """The current host's relationship to Les Cloches' commissioned surface."""

    platform: str
    recognized: bool
    supported: bool
    commissioned: bool
    detail: str


def _windows_name(release: str, version: str) -> str:
    """Best-effort Windows 11 naming without treating it as validation.

    Some Python/Windows combinations continue to report release ``10`` on
    Windows 11.  Client build 22000 is therefore used as the secondary
    recognition signal.  A generic ``Windows`` result is safer when the
    version cannot be classified.
    """

    if release.strip() == "11":
        return "Windows 11"
    match = re.search(r"(?:^|\.)(\d{5})(?:\.|$)", version)
    if match and int(match.group(1)) >= 22_000:
        return "Windows 11"
    return "Windows"


def current_platform_support() -> PlatformSupport:
    """Return platform status without importing a desktop backend."""

    system = platform.system() or "Unknown"
    release = platform.release() or ""
    version = platform.version() or ""

    if system.casefold() == "windows":
        name = _windows_name(release, version)
        return PlatformSupport(
            platform=name,
            recognized=True,
            supported=False,
            commissioned=False,
            detail=(
                "Windows 11 has an explicit Microsoft UI Automation and SendInput "
                "backend under development, but it remains unverified and unsupported "
                "until live commissioning evidence is persisted; no desktop action was attempted."
                if name == "Windows 11"
                else f"{name} is recognized but unsupported; Windows 11 is required."
            ),
        )

    if system.casefold() == "linux":
        session_type = os.environ.get("XDG_SESSION_TYPE", "").casefold()
        if session_type == "x11":
            return PlatformSupport(
                platform="Linux/X11",
                recognized=True,
                supported=True,
                commissioned=True,
                detail="Linux/X11 is the supported, experimentally commissioned platform.",
            )
        if session_type == "wayland":
            return PlatformSupport(
                platform="Linux/Wayland",
                recognized=True,
                supported=False,
                commissioned=False,
                detail=(
                    "Native Wayland write automation is unsupported. The compositor "
                    "does not expose the X11/XTEST focus and input mechanism required "
                    "by Les Cloches, and the project does not use an unsafe fallback."
                ),
            )
        return PlatformSupport(
            platform="Linux (non-X11 session)",
            recognized=True,
            supported=False,
            commissioned=False,
            detail=(
                "Les Cloches requires an X11 session on Linux "
                f"(XDG_SESSION_TYPE={session_type!r})."
            ),
        )

    return PlatformSupport(
        platform=f"{system}{f' {release}' if release else ''}",
        recognized=False,
        supported=False,
        commissioned=False,
        detail=f"Les Cloches has no desktop backend for {system!r}.",
    )


def require_supported_platform() -> PlatformSupport:
    """Return supported status or raise before any desktop action is attempted."""

    status = current_platform_support()
    if not status.supported:
        raise UnsupportedPlatform(status.detail)
    return status
