from pathlib import Path

from anon_proxy.menubar.onboarding import (
    default_profile,
    install_routing,
    is_routing_installed,
    uninstall_routing,
)
from anon_proxy.routing.shim import PATH_MARKER, shim_dir


def test_default_profile_prefers_zsh_when_available(monkeypatch):
    monkeypatch.setattr("anon_proxy.menubar.onboarding.shutil.which", lambda _: "zsh")
    monkeypatch.setattr(Path, "home", lambda: Path("/tmp/home"))
    assert default_profile() == Path("/tmp/home/.zshrc")


def test_default_profile_falls_back_to_bash(monkeypatch):
    monkeypatch.setattr("anon_proxy.menubar.onboarding.shutil.which", lambda _: None)
    monkeypatch.setattr(Path, "home", lambda: Path("/tmp/home"))
    assert default_profile() == Path("/tmp/home/.bashrc")


def test_install_then_uninstall_restores_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("ANON_PROXY_HOME", str(tmp_path / "home"))
    profile = tmp_path / ".zshrc"
    original = "export EDITOR=vim\n"
    profile.write_text(original)

    assert is_routing_installed(profile) is False
    install_routing(["claude", "codex"], profile)
    assert is_routing_installed(profile) is True
    assert PATH_MARKER in profile.read_text()
    assert (shim_dir() / "claude").exists()
    assert (shim_dir() / "codex").exists()

    uninstall_routing(["claude", "codex"], profile)
    assert profile.read_text() == original
    assert not (shim_dir() / "claude").exists()
    assert is_routing_installed(profile) is False
