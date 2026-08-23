import pytest

from les_cloches import ChatGPT, Claude, current_platform_support
from les_cloches.core.errors import UnsupportedPlatform
from les_cloches.core.platforms import require_supported_platform
from les_cloches.core.session import TransactionLock, default_lock_path

pytestmark = pytest.mark.easy


def set_host(monkeypatch, *, system: str, release: str = "", version: str = "") -> None:
    monkeypatch.setattr("les_cloches.core.platforms.platform.system", lambda: system)
    monkeypatch.setattr("les_cloches.core.platforms.platform.release", lambda: release)
    monkeypatch.setattr("les_cloches.core.platforms.platform.version", lambda: version)


def test_linux_x11_is_the_commissioned_surface(monkeypatch):
    set_host(monkeypatch, system="Linux", release="6.8")
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")

    status = current_platform_support()

    assert status.platform == "Linux/X11"
    assert status.recognized is True
    assert status.supported is True
    assert status.commissioned is True
    assert require_supported_platform() == status


def test_windows_11_backend_remains_gated_pending_live_commissioning(monkeypatch):
    set_host(monkeypatch, system="Windows", release="10", version="10.0.22631")

    status = current_platform_support()

    assert status.platform == "Windows 11"
    assert status.recognized is True
    assert status.supported is False
    assert status.commissioned is False
    assert "backend under development" in status.detail
    with pytest.raises(UnsupportedPlatform, match="unverified and unsupported"):
        require_supported_platform()


@pytest.mark.parametrize("client", [Claude, ChatGPT])
def test_public_clients_remain_gated_on_windows_before_desktop_access(monkeypatch, client):
    set_host(monkeypatch, system="Windows", release="11", version="10.0.26100")

    with pytest.raises(UnsupportedPlatform, match="no desktop action was attempted"):
        client()


def test_wayland_is_explicitly_unavailable_without_fallback(monkeypatch):
    set_host(monkeypatch, system="Linux", release="6.8")
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")

    status = current_platform_support()

    assert status.platform == "Linux/Wayland"
    assert status.supported is False
    assert status.commissioned is False
    assert "X11/XTEST" in status.detail
    with pytest.raises(UnsupportedPlatform, match="Native Wayland write automation is unsupported"):
        require_supported_platform()


def test_missing_lock_backends_fail_clearly(monkeypatch, tmp_path):
    monkeypatch.setattr("les_cloches.core.session.fcntl", None)
    monkeypatch.setattr("les_cloches.core.session.msvcrt", None)
    lock = TransactionLock(tmp_path / "windows-aware.lock")

    with pytest.raises(Exception, match="no cross-process file-locking backend"):
        lock.acquire(float("inf"))


def test_default_lock_path_uses_the_platform_temp_directory():
    assert "les-cloches-test-" in default_lock_path("test")
