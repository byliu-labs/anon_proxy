from anon_proxy.routing.env import (
    base_url,
    env_dir,
    render_env_fragment,
    write_env_fragment,
)
from anon_proxy.routing.state import RoutingState, TargetSpec


def _state(**kw):
    return RoutingState(host="127.0.0.1", port=51843, enabled=True, targets={}, **kw)


def test_base_url_is_loopback_with_provider_path():
    assert base_url(_state(), "anthropic") == "http://127.0.0.1:51843/anthropic"


def test_fragment_sets_provider_env_to_loopback():
    frag = render_env_fragment(_state(), TargetSpec("claude", "anthropic", True))
    assert 'export ANTHROPIC_BASE_URL="http://127.0.0.1:51843/anthropic"' in frag


def test_fragment_includes_no_proxy_guard():
    frag = render_env_fragment(_state(), TargetSpec("claude", "anthropic", True))
    assert "NO_PROXY" in frag
    assert "127.0.0.1" in frag and "localhost" in frag


def test_fragment_never_emits_public_host():
    frag = render_env_fragment(_state(), TargetSpec("codex", "openai", True))
    assert "api.openai.com" not in frag
    assert "api.anthropic.com" not in frag


def test_disabled_target_yields_empty_fragment():
    frag = render_env_fragment(_state(), TargetSpec("claude", "anthropic", False))
    assert frag.strip() == ""


def test_global_disabled_yields_empty_fragment():
    st = RoutingState(host="127.0.0.1", port=51843, enabled=False, targets={})
    frag = render_env_fragment(st, TargetSpec("claude", "anthropic", True))
    assert frag.strip() == ""


def test_write_fragment_round_trips(tmp_path, monkeypatch):
    monkeypatch.setenv("ANON_PROXY_HOME", str(tmp_path))
    p = write_env_fragment(_state(), TargetSpec("claude", "anthropic", True))
    assert p == env_dir() / "claude.sh"
    assert 'ANTHROPIC_BASE_URL="http://127.0.0.1:51843/anthropic"' in p.read_text()
