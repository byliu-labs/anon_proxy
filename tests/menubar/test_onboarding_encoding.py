"""Regression: the packaged app runs under an ASCII default locale (py2app sets
no LANG/LC_*), so any read of the user's shell profile MUST pin encoding=utf-8.
A bare read_text() falls back to ascii and crashes on the first non-ASCII byte
(em dash, curly quote, accented name) — which is what happened on launch.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# em dash (U+2014) -> UTF-8 byte 0xe2; exactly the byte that crashed the bundle.
_NON_ASCII_PROFILE = "# anon-proxy note — curly quote “x”\n"

# Force the interpreter into the same ASCII-default state as the py2app bundle.
_ASCII_ENV = {
    **os.environ,
    "LC_ALL": "C",
    "LANG": "C",
    "PYTHONUTF8": "0",
    "PYTHONCOERCECLOCALE": "0",
}


def _run_under_ascii_locale(code: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=_ASCII_ENV,
    )


def test_is_routing_installed_survives_non_ascii_profile(tmp_path: Path):
    profile = tmp_path / ".zshrc"
    profile.write_text(
        _NON_ASCII_PROFILE + "export PATH=...  # added by anon-proxy\n",
        encoding="utf-8",
    )
    code = (
        "from pathlib import Path;"
        "from anon_proxy.menubar.onboarding import is_routing_installed;"
        f"print(is_routing_installed(Path({str(profile)!r})))"
    )
    res = _run_under_ascii_locale(code)
    assert res.returncode == 0, f"crashed under ascii locale:\n{res.stderr}"
    assert res.stdout.strip() == "True"


def test_path_entry_round_trip_survives_non_ascii_profile(tmp_path: Path):
    profile = tmp_path / ".zshrc"
    profile.write_text(_NON_ASCII_PROFILE, encoding="utf-8")
    code = (
        "from pathlib import Path;"
        "from anon_proxy.routing.shim import install_path_entry, remove_path_entry;"
        f"p = Path({str(profile)!r});"
        "install_path_entry(p);"
        "remove_path_entry(p);"
        "print('OK')"
    )
    res = _run_under_ascii_locale(code)
    assert res.returncode == 0, f"crashed under ascii locale:\n{res.stderr}"
    assert res.stdout.strip() == "OK"
    # byte-for-byte restore must survive the utf-8 round trip
    assert profile.read_text(encoding="utf-8") == _NON_ASCII_PROFILE
