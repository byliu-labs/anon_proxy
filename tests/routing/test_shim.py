import os
import subprocess

from anon_proxy.routing.shim import (
    PATH_MARKER,
    install_path_entry,
    install_shim,
    path_snippet,
    remove_path_entry,
    remove_shim,
    render_shim,
    shim_dir,
)


def test_render_shim_execs_command_and_sources_fragment():
    body = render_shim("claude")
    assert "env.d/claude.sh" in body
    assert 'exec "$REAL"' in body
    assert "continue" in body


def test_installed_shim_is_executable(tmp_path, monkeypatch):
    monkeypatch.setenv("ANON_PROXY_HOME", str(tmp_path))
    p = install_shim("claude")
    assert p == shim_dir() / "claude"
    assert os.access(p, os.X_OK)


def test_shim_applies_fragment_and_execs_real(tmp_path, monkeypatch):
    monkeypatch.setenv("ANON_PROXY_HOME", str(tmp_path))
    realdir = tmp_path / "realbin"
    realdir.mkdir()
    real = realdir / "claude"
    real.write_text('#!/bin/sh\necho "SEEN=$ANTHROPIC_BASE_URL"\n')
    real.chmod(0o755)
    envd = tmp_path / "env.d"
    envd.mkdir()
    (envd / "claude.sh").write_text(
        'export ANTHROPIC_BASE_URL="http://127.0.0.1:51843/anthropic"\n'
    )
    shim = install_shim("claude")
    env = dict(os.environ, PATH=f"{shim_dir()}:{realdir}")
    out = subprocess.run(
        [str(shim)], env=env, capture_output=True, text=True, timeout=5
    )
    assert out.stdout.strip() == "SEEN=http://127.0.0.1:51843/anthropic"


def test_remove_shim(tmp_path, monkeypatch):
    monkeypatch.setenv("ANON_PROXY_HOME", str(tmp_path))
    install_shim("claude")
    remove_shim("claude")
    assert not (shim_dir() / "claude").exists()


def test_path_entry_is_idempotent_and_reversible(tmp_path):
    profile = tmp_path / ".zshrc"
    original = "export FOO=bar\n"
    profile.write_text(original)
    assert PATH_MARKER in path_snippet()
    assert install_path_entry(profile) is True
    assert install_path_entry(profile) is False
    assert PATH_MARKER in profile.read_text()
    assert remove_path_entry(profile) is True
    assert profile.read_text() == original
