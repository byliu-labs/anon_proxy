import json
from pathlib import Path

from anon_proxy.routing.state import (
    DEFAULT_TARGETS,
    RoutingState,
    TargetSpec,
    load_state,
    save_state,
)


def test_round_trip_preserves_targets(tmp_path: Path):
    st = RoutingState(
        host="127.0.0.1",
        port=51843,
        enabled=True,
        targets={"claude": TargetSpec("claude", "anthropic", True)},
    )
    p = tmp_path / "state.json"
    save_state(st, p)
    got = load_state(p)
    assert got == st


def test_missing_file_returns_seeded_defaults(tmp_path: Path):
    got = load_state(tmp_path / "nope.json")
    assert got.enabled is False
    assert got.port is None
    assert got.targets == DEFAULT_TARGETS
    assert got.targets["claude"].provider == "anthropic"
    assert got.targets["codex"].provider == "openai"


def test_corrupt_file_returns_defaults(tmp_path: Path):
    p = tmp_path / "state.json"
    p.write_text("{not json")
    got = load_state(p)
    assert got.targets == DEFAULT_TARGETS


def test_save_is_atomic_and_readable(tmp_path: Path):
    p = tmp_path / "state.json"
    save_state(RoutingState(port=9, targets={}), p)
    data = json.loads(p.read_text())
    assert data["host"] == "127.0.0.1"
    assert data["port"] == 9
