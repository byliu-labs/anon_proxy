"""Frozen-bundle launch wiring.

Under a PyInstaller bundle ``sys.executable`` is the app binary, not a Python
interpreter, and ``sys.frozen`` is set. So ``-m anon_proxy.server`` /
``-m anon_proxy.menubar.app`` launch commands are meaningless — they would just
re-enter the frozen menu-bar app with ``-m ...`` as argv. The command builders
must swap in a ``--run-server`` sentinel that the bundle ``__main__`` routes.
"""

import sys

import anon_proxy.menubar.__main__ as bundle_main
from anon_proxy.menubar.supervisor import (
    ProxySupervisor,
    menubar_command,
    server_command,
)


def _fake_frozen(monkeypatch, exe="/App/anon-proxy.app/Contents/MacOS/anon-proxy"):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", exe, raising=False)


def test_server_command_not_frozen_uses_dash_m():
    assert server_command(["--metrics"]) == [
        sys.executable,
        "-m",
        "anon_proxy.server",
        "--metrics",
    ]


def test_server_command_frozen_uses_run_server_sentinel(monkeypatch):
    _fake_frozen(monkeypatch)
    cmd = server_command(["--metrics"])
    assert cmd == [sys.executable, "--run-server", "--metrics"]
    assert "-m" not in cmd


def test_menubar_command_frozen_drops_dash_m(monkeypatch):
    _fake_frozen(monkeypatch)
    cmd = menubar_command(["--url", "http://127.0.0.1:8080/_status"])
    assert cmd == [sys.executable, "--url", "http://127.0.0.1:8080/_status"]
    assert "-m" not in cmd


def test_supervisor_default_cmd_frozen_is_launchable(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    _fake_frozen(monkeypatch)
    cmd = ProxySupervisor(backend="onnx")._cmd
    assert cmd[:2] == [sys.executable, "--run-server"]
    assert "-m" not in cmd
    assert "--store" in cmd and "--metrics" in cmd
    assert cmd[cmd.index("--backend") + 1] == "onnx"


def test_dispatch_routes_run_server_to_server_main(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "anon_proxy.server.main", lambda argv=None: captured.update(argv=argv)
    )
    bundle_main._dispatch(["--run-server", "--port", "9999"])
    assert captured["argv"] == ["--port", "9999"]


def test_dispatch_routes_default_to_menubar_app(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "anon_proxy.menubar.app.main", lambda argv=None: captured.update(argv=argv)
    )
    bundle_main._dispatch(["--url", "http://x"])
    assert captured["argv"] == ["--url", "http://x"]
