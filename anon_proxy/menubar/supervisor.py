"""Proxy subprocess lifecycle plus a launchd Start-at-login agent."""

from __future__ import annotations

import atexit
import socket
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

_PLIST_TMPL = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" \
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key>
  <array>
{args}
  </array>
  <key>RunAtLoad</key><{run_at_load}/>
</dict>
</plist>
"""


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def server_command(args: list[str]) -> list[str]:
    """argv that launches the proxy server, correct under a PyInstaller bundle.

    In a frozen bundle ``sys.executable`` is the app binary, not a Python
    interpreter, so ``-m anon_proxy.server`` is meaningless — the bundle's
    ``__main__`` routes a ``--run-server`` sentinel to the server entry point
    instead. Outside a bundle we still spawn the interpreter with ``-m``.
    """
    if _is_frozen():
        return [sys.executable, "--run-server", *args]
    return [sys.executable, "-m", "anon_proxy.server", *args]


def menubar_command(args: list[str]) -> list[str]:
    """argv that launches the menu-bar app, correct under a PyInstaller bundle.

    A frozen bundle already *is* the menu-bar app, so it is re-invoked with no
    module selector; outside a bundle we spawn ``-m anon_proxy.menubar.app``.
    """
    if _is_frozen():
        return [sys.executable, *args]
    return [sys.executable, "-m", "anon_proxy.menubar.app", *args]


class ProxySupervisor:
    def __init__(
        self, cmd: list[str] | None = None, *, backend: str | None = None
    ) -> None:
        if cmd is None:
            from anon_proxy.server import default_store_path

            server_args = ["--store", str(default_store_path()), "--metrics"]
            if backend is not None:
                server_args += ["--backend", backend]
            cmd = server_command(server_args)
        self._cmd = cmd
        self._proc: subprocess.Popen | None = None

    @staticmethod
    def free_port() -> int:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return int(s.getsockname()[1])

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self, extra_args: list[str] | None = None) -> None:
        if self.is_running():
            return
        self._proc = subprocess.Popen(self._cmd + list(extra_args or []))
        # Reap this child if the process exits before stop() is called (e.g. the
        # menu-bar app is quit). Unregistered again in stop(), so the atexit list
        # tracks the child's lifecycle, not the supervisor's object lifetime.
        atexit.register(self.stop)

    def stop(self, grace: float = 5.0) -> None:
        atexit.unregister(self.stop)
        if not self.is_running():
            self._proc = None
            return
        assert self._proc is not None
        self._proc.terminate()
        try:
            self._proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()
        self._proc = None

    def restart(self, extra_args: list[str] | None = None) -> None:
        self.stop()
        self.start(extra_args)


def launch_agent_plist(
    label: str, program_args: list[str], *, run_at_load: bool = True
) -> str:
    args = "\n".join(f"    <string>{escape(arg)}</string>" for arg in program_args)
    return _PLIST_TMPL.format(
        label=escape(label),
        args=args,
        run_at_load="true" if run_at_load else "false",
    )


def _plist_path(label: str, plist_dir: Path | None) -> Path:
    base = (
        plist_dir if plist_dir is not None else Path.home() / "Library" / "LaunchAgents"
    )
    return base / f"{label}.plist"


def install_launch_agent(
    label: str,
    program_args: list[str],
    *,
    plist_dir: Path | None = None,
    load: bool = True,
) -> Path:
    path = _plist_path(label, plist_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(launch_agent_plist(label, program_args))
    if load:
        subprocess.run(["launchctl", "load", str(path)], check=False)
    return path


def uninstall_launch_agent(
    label: str, *, plist_dir: Path | None = None, load: bool = True
) -> None:
    path = _plist_path(label, plist_dir)
    if load and path.exists():
        subprocess.run(["launchctl", "unload", str(path)], check=False)
    path.unlink(missing_ok=True)
