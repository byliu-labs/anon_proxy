import importlib.util
from pathlib import Path


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_setup_app_is_menu_bar_agent_and_signable(monkeypatch):
    monkeypatch.setenv("ANON_PROXY_CODESIGN_IDENTITY", "Developer ID Application: X")
    mod = _load("setup_app", Path("packaging/setup_app.py"))
    assert mod.PLIST["LSUIElement"] is True
    assert mod.PLIST["CFBundleName"] == "anon-proxy"
    assert mod.CODESIGN_IDENTITY == "Developer ID Application: X"


def test_setup_app_defaults_to_adhoc(monkeypatch):
    monkeypatch.delenv("ANON_PROXY_CODESIGN_IDENTITY", raising=False)
    mod = _load("setup_app", Path("packaging/setup_app.py"))
    assert mod.CODESIGN_IDENTITY == "-"
