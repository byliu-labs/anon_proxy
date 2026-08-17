"""Read-only classification of running target instances via `ps eww`."""

from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from functools import lru_cache

_LOOPBACK_PREFIXES = ("=http://127.0.0.1", "=http://localhost")
_ENV_MARKER = "ANON_PROXY_PS_PROBE=visible"


@dataclass(frozen=True)
class ProcInfo:
    pid: int
    proxied: bool


def classify_instances(
    command: str, env_var: str, *, ps_lines: list[str] | None = None
) -> list[ProcInfo]:
    lines = ps_lines if ps_lines is not None else _ps_eww()
    out: list[ProcInfo] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        head, _, rest = line.partition(" ")
        try:
            pid = int(head)
        except ValueError:
            continue
        try:
            argv0 = shlex.split(rest)[0] if rest else ""
        except ValueError:
            argv0 = rest.split(" ", 1)[0]
        if os.path.basename(argv0) != command:
            continue
        proxied = any(f"{env_var}{prefix}" in rest for prefix in _LOOPBACK_PREFIXES)
        out.append(ProcInfo(pid=pid, proxied=proxied))
    return out


def _ps_eww() -> list[str]:
    try:
        res = subprocess.run(
            ["ps", "eww", "-o", "pid=,args="],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return res.stdout.splitlines()


def _has_env_marker(lines: list[str], marker: str) -> bool:
    return any(marker in line for line in lines)


@lru_cache(maxsize=1)
def env_visibility_available() -> bool:
    env = dict(os.environ, ANON_PROXY_PS_PROBE="visible")
    try:
        proc = subprocess.Popen(["/bin/sh", "-c", "sleep 1"], env=env)
    except OSError:
        return False
    try:
        return _has_env_marker(_ps_eww(), _ENV_MARKER)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.SubprocessError:
            proc.kill()
            proc.wait()


def scan_target(command: str, provider: str) -> list[ProcInfo]:
    from anon_proxy.routing.env import PROVIDER_ENV

    env_var = PROVIDER_ENV.get(provider)
    if env_var is None:
        return []
    return classify_instances(command, env_var)
