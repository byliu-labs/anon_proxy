"""py2app build script for the anon-proxy menu-bar app.

Build: ANON_PROXY_CODESIGN_IDENTITY=- uv run python packaging/setup_app.py py2app
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CODESIGN_IDENTITY = os.environ.get("ANON_PROXY_CODESIGN_IDENTITY", "-")
BUNDLE_PATH = PROJECT_ROOT / "dist/anon-proxy.app"

PLIST = {
    "CFBundleName": "anon-proxy",
    "CFBundleShortVersionString": "0.1.0",
    "LSUIElement": True,
    "LSMinimumSystemVersion": "12.0",
}

APP = [{"script": "packaging/app_main.py", "dest_base": "anon-proxy"}]
BUILD_APP = [
    {"script": str(PROJECT_ROOT / "packaging/app_main.py"), "dest_base": "anon-proxy"}
]
OPTIONS = {
    "argv_emulation": False,
    "plist": PLIST,
    "packages": ["anon_proxy", "rumps"],
    "iconfile": None,
    "resources": [str(PROJECT_ROOT / "anon_proxy/assets")],
    "dist_dir": str(PROJECT_ROOT / "dist"),
    "bdist_base": str(PROJECT_ROOT / "build"),
}


def codesign_command(app_path: Path = BUNDLE_PATH) -> list[str]:
    return [
        "codesign",
        "--force",
        "--deep",
        "--sign",
        CODESIGN_IDENTITY,
        str(app_path.relative_to(PROJECT_ROOT)),
    ]


def codesign_app(app_path: Path = BUNDLE_PATH) -> None:
    subprocess.run(codesign_command(app_path), cwd=PROJECT_ROOT, check=True)


def ensure_zlib_file() -> None:
    import zlib
    from yaml import _yaml

    if not hasattr(zlib, "__file__"):
        zlib.__file__ = _yaml.__file__


def run_py2app() -> None:
    from distutils.core import setup

    cwd = Path.cwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            ensure_zlib_file()
            setup(name="anon-proxy-app", app=BUILD_APP, options={"py2app": OPTIONS})
        finally:
            os.chdir(cwd)


if __name__ == "__main__":
    run_py2app()
    codesign_app()
