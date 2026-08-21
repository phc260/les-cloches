import pytest

from les_cloches import ChatGPT, Claude, current_platform_support
from les_cloches.core.errors import UnsupportedPlatform
from les_cloches.core.platforms import require_supported_platform
from les_cloches.core.session import TransactionLock, default_lock_path


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


def test_windows_11_is_recognized_but_not_claimed_as_supported(monkeypatch):
    set_host(monkeypatch, system="Windows", release="10", version="10.0.22631")

    status = current_platform_support()

    assert status.platform == "Windows 11"
    assert status.recognized is True
    assert status.supported is False
    assert status.commissioned is False
    with pytest.raises(UnsupportedPlatform, match="recognized but unverified and unsupported"):
        require_supported_platform()


@pytest.mark.parametrize("client", [Claude, ChatGPT])
def test_public_clients_reject_windows_before_desktop_access(monkeypatch, client):
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


def test_non_posix_lock_fails_clearly_instead_of_using_fcntl(monkeypatch, tmp_path):
    monkeypatch.setattr("les_cloches.core.session.fcntl", None)
    lock = TransactionLock(tmp_path / "windows-aware.lock")

    with pytest.raises(UnsupportedPlatform, match="Windows cross-process desktop locking"):
        lock.acquire(float("inf"))


def test_default_lock_path_uses_the_platform_temp_directory():
    assert "les-cloches-test-" in default_lock_path("test")
