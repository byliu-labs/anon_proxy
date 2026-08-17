import pytest

from anon_proxy.routing.controller import RoutingController
from anon_proxy.routing.env import env_dir
from anon_proxy.routing.shim import shim_dir
from anon_proxy.routing.state import RoutingState, TargetSpec, load_state


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("ANON_PROXY_HOME", str(tmp_path))
    return tmp_path


def test_enable_writes_fragment_and_persists(home):
    c = RoutingController(RoutingState(port=51843, enabled=True))
    c.set_enabled("claude", True)
    assert (env_dir() / "claude.sh").read_text().count("ANTHROPIC_BASE_URL") == 1
    assert load_state().targets["claude"].enabled is True


def test_disable_clears_fragment(home):
    c = RoutingController(RoutingState(port=51843, enabled=True))
    c.set_enabled("claude", True)
    c.set_enabled("claude", False)
    assert (env_dir() / "claude.sh").read_text().strip() == ""


def test_set_port_rerenders_enabled_targets(home):
    st = RoutingState(
        port=None,
        enabled=True,
        targets={"claude": TargetSpec("claude", "anthropic", True)},
    )
    c = RoutingController(st)
    c.set_port(60000)
    assert "60000" in (env_dir() / "claude.sh").read_text()


def test_add_target_rejects_unknown_provider(home):
    c = RoutingController(RoutingState(port=1, enabled=True))
    with pytest.raises(ValueError, match="provider"):
        c.add_target("aider", "cohere")


def test_add_target_rejects_missing_command(home, monkeypatch):
    monkeypatch.setenv("PATH", str(home))
    c = RoutingController(RoutingState(port=1, enabled=True))
    with pytest.raises(ValueError, match="not found"):
        c.add_target("aider", "openai")


def test_add_target_installs_shim(home, monkeypatch):
    bind = home / "b"
    bind.mkdir()
    (bind / "aider").write_text("#!/bin/sh\n")
    (bind / "aider").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bind}")
    c = RoutingController(RoutingState(port=1, enabled=True))
    c.add_target("aider", "openai")
    assert (shim_dir() / "aider").exists()
    assert load_state().targets["aider"].provider == "openai"
