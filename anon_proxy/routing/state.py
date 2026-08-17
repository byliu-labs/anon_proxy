"""Single source of truth for app routing: ~/.anon-proxy/state.json."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class TargetSpec:
    command: str
    provider: str
    enabled: bool = False


DEFAULT_TARGETS: dict[str, TargetSpec] = {
    "claude": TargetSpec("claude", "anthropic", False),
    "codex": TargetSpec("codex", "openai", False),
}


@dataclass
class RoutingState:
    host: str = "127.0.0.1"
    port: int | None = None
    enabled: bool = False
    targets: dict[str, TargetSpec] = field(
        default_factory=lambda: dict(DEFAULT_TARGETS)
    )


def home_dir() -> Path:
    return Path(os.environ.get("ANON_PROXY_HOME", str(Path.home() / ".anon-proxy")))


def state_path() -> Path:
    return home_dir() / "state.json"


def load_state(path: Path | None = None) -> RoutingState:
    path = path or state_path()
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return RoutingState()
    if not isinstance(data, dict):
        return RoutingState()

    raw_targets = data.get("targets") or {}
    targets: dict[str, TargetSpec] = {}
    for cmd, spec in raw_targets.items():
        if isinstance(spec, dict) and "provider" in spec:
            targets[cmd] = TargetSpec(
                command=cmd,
                provider=str(spec["provider"]),
                enabled=bool(spec.get("enabled", False)),
            )

    return RoutingState(
        host=str(data.get("host", "127.0.0.1")),
        port=data.get("port"),
        enabled=bool(data.get("enabled", False)),
        targets=targets or dict(DEFAULT_TARGETS),
    )


def save_state(state: RoutingState, path: Path | None = None) -> None:
    path = Path(path or state_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "host": state.host,
        "port": state.port,
        "enabled": state.enabled,
        "targets": {
            cmd: {"provider": target.provider, "enabled": target.enabled}
            for cmd, target in state.targets.items()
        },
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    os.replace(tmp, path)
