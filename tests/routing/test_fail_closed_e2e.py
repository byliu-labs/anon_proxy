import os
import subprocess

from anon_proxy.routing.env import write_env_fragment
from anon_proxy.routing.shim import install_shim, shim_dir
from anon_proxy.routing.state import RoutingState, TargetSpec


def test_shimmed_tool_targets_loopback_never_public(tmp_path, monkeypatch):
    monkeypatch.setenv("ANON_PROXY_HOME", str(tmp_path))
    realdir = tmp_path / "realbin"
    realdir.mkdir()
    fake = realdir / "claude"
    fake.write_text('#!/bin/sh\necho "CALL=$ANTHROPIC_BASE_URL"\n')
    fake.chmod(0o755)
    st = RoutingState(
        host="127.0.0.1",
        port=51999,
        enabled=True,
        targets={"claude": TargetSpec("claude", "anthropic", True)},
    )
    write_env_fragment(st, st.targets["claude"])
    shim = install_shim("claude")
    env = dict(os.environ, PATH=f"{shim_dir()}:{realdir}")
    out = subprocess.run(
        [str(shim)], env=env, capture_output=True, text=True, timeout=5
    )
    call = out.stdout.strip()
    assert call == "CALL=http://127.0.0.1:51999/anthropic"
    assert "api.anthropic.com" not in call
