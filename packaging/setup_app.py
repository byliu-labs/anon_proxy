"""py2app build script for the anon-proxy menu-bar app.

Build: ANON_PROXY_CODESIGN_IDENTITY=- uv run python packaging/setup_app.py py2app
"""

from __future__ import annotations

import os

CODESIGN_IDENTITY = os.environ.get("ANON_PROXY_CODESIGN_IDENTITY", "-")

PLIST = {
    "CFBundleName": "anon-proxy",
    "CFBundleShortVersionString": "0.1.0",
    "LSUIElement": True,
    "LSMinimumSystemVersion": "12.0",
}

APP = ["packaging/app_main.py"]
OPTIONS = {
    "argv_emulation": False,
    "plist": PLIST,
    "packages": ["anon_proxy", "rumps"],
    "iconfile": None,
    "resources": ["anon_proxy/assets"],
    "codesign_identity": CODESIGN_IDENTITY,
}


if __name__ == "__main__":
    from setuptools import setup

    setup(app=APP, options={"py2app": OPTIONS}, setup_requires=["py2app"])
