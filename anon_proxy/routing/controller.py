"""Orchestrates state, fragments, shims, and scanning for the menu bar."""

from __future__ import annotations

import os
import shutil

from anon_proxy.routing.env import PROVIDER_ENV, write_env_fragment
from anon_proxy.routing.scan import ProcInfo, scan_target
from anon_proxy.routing.shim import install_shim, shim_dir
from anon_proxy.routing.state import RoutingState, TargetSpec, save_state


def _resolve_outside_shim(command: str) -> str | None:
    shim = str(shim_dir())
    dirs = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d and d != shim]
    return shutil.which(command, path=os.pathsep.join(dirs))


class RoutingController:
    def __init__(self, state: RoutingState) -> None:
        self.state = state

    def _persist(self) -> None:
        save_state(self.state)

    def _render(self, command: str) -> None:
        write_env_fragment(self.state, self.state.targets[command])

    def sync_all(self) -> None:
        for command, target in self.state.targets.items():
            install_shim(command)
            write_env_fragment(self.state, target)

    def set_port(self, port: int) -> None:
        self.state.port = port
        for command in self.state.targets:
            self._render(command)
        self._persist()

    def set_enabled(self, command: str, enabled: bool) -> None:
        old = self.state.targets[command]
        if enabled:
            self.state.enabled = True
        self.state.targets[command] = TargetSpec(command, old.provider, enabled)
        install_shim(command)
        self._render(command)
        self._persist()

    def add_target(self, command: str, provider: str) -> None:
        if provider not in PROVIDER_ENV:
            raise ValueError(f"unknown provider: {provider}")
        if _resolve_outside_shim(command) is None:
            raise ValueError(f"command not found on PATH: {command}")
        self.state.enabled = True
        self.state.targets[command] = TargetSpec(command, provider, True)
        install_shim(command)
        self._render(command)
        self._persist()

    def status(self, command: str) -> list[ProcInfo]:
        target = self.state.targets.get(command)
        if target is None:
            return []
        return scan_target(command, target.provider)
