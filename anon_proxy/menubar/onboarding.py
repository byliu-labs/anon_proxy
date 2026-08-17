"""First-run routing setup: install/uninstall shims and PATH profile entry."""

from __future__ import annotations

import shutil
from pathlib import Path

from anon_proxy.routing.shim import (
    PATH_MARKER,
    install_path_entry,
    install_shim,
    remove_path_entry,
    remove_shim,
)


def default_profile() -> Path:
    if shutil.which("zsh"):
        return Path.home() / ".zshrc"
    return Path.home() / ".bashrc"


def is_routing_installed(profile: Path) -> bool:
    return profile.exists() and PATH_MARKER in profile.read_text()


def install_routing(commands: list[str], profile: Path) -> None:
    for command in commands:
        install_shim(command)
    install_path_entry(profile)


def uninstall_routing(commands: list[str], profile: Path) -> None:
    for command in commands:
        remove_shim(command)
    remove_path_entry(profile)
