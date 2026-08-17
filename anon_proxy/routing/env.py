"""Render POSIX-sh env fragments the shim sources. Loopback + NO_PROXY only."""

from __future__ import annotations

import os
from pathlib import Path

from anon_proxy.routing.state import RoutingState, TargetSpec, home_dir

PROVIDER_ENV: dict[str, str] = {
    "anthropic": "ANTHROPIC_BASE_URL",
    "openai": "OPENAI_BASE_URL",
}


def env_dir() -> Path:
    return home_dir() / "env.d"


def base_url(state: RoutingState, provider: str) -> str:
    return f"http://{state.host}:{state.port}/{provider}"


def render_env_fragment(state: RoutingState, target: TargetSpec) -> str:
    if not state.enabled or not target.enabled or not state.port:
        return ""
    env_var = PROVIDER_ENV.get(target.provider)
    if env_var is None:
        return ""
    url = base_url(state, target.provider)
    return (
        f"# anon-proxy routing fragment for {target.command}\n"
        f'export {env_var}="{url}"\n'
        f'export NO_PROXY="127.0.0.1,localhost${{NO_PROXY:+,$NO_PROXY}}"\n'
        f'export no_proxy="127.0.0.1,localhost${{no_proxy:+,$no_proxy}}"\n'
    )


def write_env_fragment(state: RoutingState, target: TargetSpec) -> Path:
    d = env_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{target.command}.sh"
    tmp = path.with_suffix(".sh.tmp")
    tmp.write_text(render_env_fragment(state, target))
    os.replace(tmp, path)
    return path
