import importlib.util
import zlib
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
    assert mod.APP == [{"script": "packaging/app_main.py", "dest_base": "anon-proxy"}]
    assert "codesign_identity" not in mod.OPTIONS
    assert mod.codesign_command() == [
        "codesign",
        "--force",
        "--deep",
        "--sign",
        "Developer ID Application: X",
        "dist/anon-proxy.app",
    ]


def test_setup_app_defaults_to_adhoc(monkeypatch):
    monkeypatch.delenv("ANON_PROXY_CODESIGN_IDENTITY", raising=False)
    mod = _load("setup_app", Path("packaging/setup_app.py"))
    assert mod.CODESIGN_IDENTITY == "-"


def test_setup_app_patches_builtin_zlib_for_uv_python(monkeypatch):
    mod = _load("setup_app", Path("packaging/setup_app.py"))
    original = getattr(zlib, "__file__", None)
    monkeypatch.delattr(zlib, "__file__", raising=False)

    mod.ensure_zlib_file()

    assert zlib.__file__
    if original is not None:
        zlib.__file__ = original
