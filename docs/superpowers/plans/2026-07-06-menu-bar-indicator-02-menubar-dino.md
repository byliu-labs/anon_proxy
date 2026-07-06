# Menu-Bar Dino App — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Depends on:** Plan 01 (`2026-07-06-menu-bar-indicator-01-status-endpoint.md`) — this app consumes the `GET /_status` JSON defined there. Implement and merge Plan 01 first.

**Goal:** A macOS menu-bar app whose icon is a running Chrome-style dinosaur — gait speed tracks live token throughput from `/_status`, with idle / masking-error-alarm / down states, per-agent attribution, holiday-swappable skins, observe-plus-supervise (Start/Stop/Restart), and a launchd "Start at login" opt-in. Off-macOS (or `--watch`) it degrades to a live terminal status line.

**Architecture:** Pure, unit-tested modules do all the logic — `statusclient` (poll), `render` (status→icon/fps/menu), `themes` (registry + holiday calendar + fallback), `config` (persisted prefs), `supervisor` (subprocess + launchd). `app.py` is a thin rumps shell that wires them into an `NSStatusBar` timer loop. Dino frames are committed PNGs generated from a reviewed pixel matrix; adding a holiday = drop a frame folder + one registry entry.

**Tech Stack:** Python ≥3.10, rumps (macOS NSStatusBar, optional extra), httpx, Pillow (asset generation only, dev extra), pytest.

## Global Constraints

- Python `>=3.10` — `X | None` unions, `dict[...]`/`list[...]` generics.
- Use `uv run pytest ...`; use `uv add` / edit `pyproject.toml` for deps, never pip.
- `rumps` is macOS-only and lives in the `menubar` optional extra; nothing at import time in the pure modules may import rumps. `app.py` imports rumps lazily inside the macOS branch.
- The app is a pure observer over `/_status`; it never sees PII or auth. It may spawn/stop a proxy **it launched itself** (tracked PID) — never signal a foreign PID.
- Missing/partial theme assets MUST fall back to `classic` — never a blank icon.
- No commits to `main`/`master`; feature branch only.
- Dino fidelity is a gated deliverable: rendered frames must visually match the reference Chrome T-rex at `/Users/boyuliu/.claude/image-cache/b40bc9db-3ef4-4088-a5d6-ddf20651aca7/1.png` (Task 1 acceptance).

---

### Task 1: Package scaffold, deps, asset generator, classic frames

**Files:**
- Modify: `pyproject.toml` (optional extras, console script, package-data)
- Create: `anon_proxy/menubar/__init__.py` (empty)
- Create: `scripts/gen_dino_assets.py` (Pillow generator with the pixel matrices)
- Create (generated, committed): `anon_proxy/assets/dino/classic/{stand,run1,run2,dead,cactus}.png`

**Interfaces:**
- Consumes: nothing.
- Produces: committed PNG frames at `anon_proxy/assets/dino/classic/`; a repeatable generator `python scripts/gen_dino_assets.py`.

- [ ] **Step 1: Add deps, script, and package-data to `pyproject.toml`**

Add these blocks (append/merge with existing `[project.scripts]`):

```toml
[project.optional-dependencies]
menubar = ["rumps>=0.4.0"]
gen = ["pillow>=10.0.0"]

[project.scripts]
anon-proxy-store = "anon_proxy.store_cli:main"
anon-proxy-menubar = "anon_proxy.menubar.app:main"

[tool.setuptools.package-data]
anon_proxy = ["assets/dino/**/*.png"]
```

Run: `uv sync --extra gen`
Expected: Pillow installed into the environment.

- [ ] **Step 2: Write the asset generator with reviewed matrices**

The matrix is the source of truth for the classic dino. `#` = body pixel, `o` =
eye (left transparent), space = empty. Frames are 24×22. Run frames differ only
in the legs; `dead` swaps the eye to a cross; `cactus` is the alarm obstacle.

```python
# scripts/gen_dino_assets.py
"""Generate committed dino frame PNGs from reviewed pixel matrices.

Run: uv run --extra gen python scripts/gen_dino_assets.py
Frames are 24x22, drawn in dark gray on transparent, matching the Chrome T-rex.
Re-run after editing a matrix; commit the resulting PNGs.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

BODY = (60, 60, 66, 255)      # dark gray, close to Chrome dino
TRANSPARENT = (0, 0, 0, 0)
SCALE = 1                      # 1px per cell; menu bar renders at native template size

# Shared upper body (rows 0-15): head top-right, sloping back, raised tail left.
_UPPER = [
    "              #######   ",
    "             #########  ",
    "             ##o######  ",
    "             #########  ",
    "             ####       ",
    "  #          #####      ",
    "  ##        #######     ",
    "  ###      ########     ",
    "  #####  ##########     ",
    "  #################     ",
    "  ##################    ",
    "   ################ #   ",
    "   ###############     ",
    "    #############      ",
    "     ###########      ",
    "      #########       ",
]
# Legs (rows 16-21) per frame.
_LEGS_STAND = [
    "      ####  ###       ",
    "      ###    ##       ",
    "      ##     ##       ",
    "      ##     ##       ",
    "      ##     ##       ",
    "      ##     ##       ",
]
_LEGS_RUN1 = [   # rear leg planted, front leg lifted
    "      ####  ###       ",
    "      ###    ##       ",
    "      ##     ##       ",
    "      ##     #        ",
    "      ##              ",
    "      ###             ",
]
_LEGS_RUN2 = [   # front leg planted, rear leg lifted
    "      ####  ###       ",
    "      ###    ##       ",
    "       #     ##       ",
    "             ##       ",
    "             ###      ",
    "            ###       ",
]
_CACTUS = [
    "  #  ",
    "  #  ",
    "# #  ",
    "# # #",
    "### #",
    "  # #",
    "  ###",
    "  #  ",
    "  #  ",
    "  #  ",
]


def _pad(rows: list[str], width: int) -> list[str]:
    return [r.ljust(width) for r in rows]


def _frame(legs: list[str], *, dead: bool = False) -> list[str]:
    rows = list(_UPPER) + legs
    if dead:
        rows = [r.replace("o", "x") for r in rows]
    return rows


def _render(rows: list[str], path: Path) -> None:
    rows = _pad(rows, max(len(r) for r in rows))
    h, w = len(rows), len(rows[0])
    img = Image.new("RGBA", (w * SCALE, h * SCALE), TRANSPARENT)
    px = img.load()
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch == "#":
                for dy in range(SCALE):
                    for dx in range(SCALE):
                        px[x * SCALE + dx, y * SCALE + dy] = BODY
            # 'o' (eye) and 'x' (dead eye hole) stay transparent
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "anon_proxy" / "assets" / "dino" / "classic"
    _render(_frame(_LEGS_STAND), out / "stand.png")
    _render(_frame(_LEGS_RUN1), out / "run1.png")
    _render(_frame(_LEGS_RUN2), out / "run2.png")
    _render(_frame(_LEGS_STAND, dead=True), out / "dead.png")
    _render(_CACTUS, out / "cactus.png")
    print(f"wrote frames to {out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Generate the frames**

Run: `uv run --extra gen python scripts/gen_dino_assets.py`
Expected: `wrote frames to .../anon_proxy/assets/dino/classic` and five PNGs exist:

Run: `ls anon_proxy/assets/dino/classic/`
Expected: `cactus.png  dead.png  run1.png  run2.png  stand.png`

- [ ] **Step 4: VISUAL ACCEPTANCE GATE — compare to the reference dino**

Render an enlarged contact sheet and eyeball it against the reference:

```bash
uv run --extra gen python -c "
from PIL import Image
from pathlib import Path
d = Path('anon_proxy/assets/dino/classic')
frames = ['stand','run1','run2','dead']
imgs = [Image.open(d/f'{n}.png') for n in frames]
w = sum(i.width for i in imgs) + 10*len(imgs)
sheet = Image.new('RGBA',(w*8, imgs[0].height*8+16),(245,245,245,255))
x=0
for im in imgs:
    big = im.resize((im.width*8, im.height*8), Image.NEAREST)
    sheet.paste(big,(x,8),big); x += big.width+80
sheet.save('/tmp/dino-contact.png')
print('wrote /tmp/dino-contact.png')
"
```

Then use the Read tool on `/tmp/dino-contact.png` AND on the reference
`/Users/boyuliu/.claude/image-cache/b40bc9db-3ef4-4088-a5d6-ddf20651aca7/1.png`.
Acceptance: the silhouette reads as a T-rex (big blocky head top-right, single
eye, short arm, bulky body, raised tail on the left, two thick legs) — **not a
duck** (no long neck, no beak). If it fails, adjust the matrices in
`scripts/gen_dino_assets.py`, re-run Step 3, and re-check. Do not proceed until
it passes.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock scripts/gen_dino_assets.py anon_proxy/menubar/__init__.py anon_proxy/assets/dino/classic/
git commit -m "feat: scaffold menubar package + generate classic dino frames"
```

---

### Task 2: Status client (poll `/_status`)

**Files:**
- Create: `anon_proxy/menubar/statusclient.py`
- Test: `tests/menubar/__init__.py` (empty), `tests/menubar/test_statusclient.py`

**Interfaces:**
- Consumes: nothing (httpx).
- Produces: `fetch_status(url: str, *, get=None, timeout: float = 2.0) -> dict | None` — GET `url`; returns parsed JSON dict on 200, else `None` (connection refused, timeout, non-200, bad JSON). `get` is an injectable `httpx.get`-compatible callable for tests.

- [ ] **Step 1: Write the failing tests**

```python
# tests/menubar/test_statusclient.py
import httpx

from anon_proxy.menubar.statusclient import fetch_status


def test_returns_dict_on_200():
    def fake_get(url, timeout=None):
        return httpx.Response(200, json={"status": "running", "tokens_per_sec": 12.0})
    assert fetch_status("http://x/_status", get=fake_get)["status"] == "running"


def test_returns_none_on_connect_error():
    def fake_get(url, timeout=None):
        raise httpx.ConnectError("refused")
    assert fetch_status("http://x/_status", get=fake_get) is None


def test_returns_none_on_non_200():
    def fake_get(url, timeout=None):
        return httpx.Response(500, text="nope")
    assert fetch_status("http://x/_status", get=fake_get) is None


def test_returns_none_on_bad_json():
    def fake_get(url, timeout=None):
        return httpx.Response(200, text="not json")
    assert fetch_status("http://x/_status", get=fake_get) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/menubar/test_statusclient.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'anon_proxy.menubar.statusclient'`

- [ ] **Step 3: Write the implementation**

```python
# anon_proxy/menubar/statusclient.py
"""Poll the proxy's /_status endpoint. Any failure => None ("down")."""

from __future__ import annotations

import httpx


def fetch_status(url: str, *, get=None, timeout: float = 2.0) -> dict | None:
    get = get or httpx.get
    try:
        resp = get(url, timeout=timeout)
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/menubar/test_statusclient.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add anon_proxy/menubar/statusclient.py tests/menubar/
git commit -m "feat: menubar status client polling /_status"
```

---

### Task 3: Theme registry + holiday calendar + fallback

**Files:**
- Create: `anon_proxy/menubar/themes.py`
- Test: `tests/menubar/test_themes.py`

**Interfaces:**
- Consumes: committed assets under `anon_proxy/assets/dino/` (Task 1).
- Produces:
  - `FRAMES: tuple[str, ...] = ("stand", "run1", "run2", "dead", "cactus")`
  - `THEMES: dict[str, str]` — theme name → subdir name (at least `{"classic": "classic"}`).
  - `holiday_for(date) -> str` — theme name for a `datetime.date` (e.g. `"winter"` late Dec, else `"classic"`).
  - `resolve_theme(selected: str, date) -> str` — `"auto"` → `holiday_for(date)`, else `selected` (unknown → `"classic"`).
  - `frame_paths(theme: str, *, base: "Path | None" = None) -> dict[str, Path]` — frame→PNG path; any frame missing in `theme` falls back to the `classic` file; base defaults to the packaged assets dir.

- [ ] **Step 1: Write the failing tests**

```python
# tests/menubar/test_themes.py
import datetime as dt
from pathlib import Path

from anon_proxy.menubar import themes


def test_holiday_for_winter_and_default():
    assert themes.holiday_for(dt.date(2026, 12, 25)) == "winter"
    assert themes.holiday_for(dt.date(2026, 7, 6)) == "classic"


def test_resolve_theme_auto_and_manual():
    assert themes.resolve_theme("auto", dt.date(2026, 12, 25)) == "winter"
    assert themes.resolve_theme("classic", dt.date(2026, 12, 25)) == "classic"
    assert themes.resolve_theme("no-such-theme", dt.date(2026, 7, 6)) == "classic"


def test_frame_paths_fall_back_to_classic(tmp_path: Path):
    # classic has all frames; "spooky" has only stand.png -> others fall back.
    classic = tmp_path / "classic"
    classic.mkdir()
    for f in themes.FRAMES:
        (classic / f"{f}.png").write_bytes(b"x")
    spooky = tmp_path / "spooky"
    spooky.mkdir()
    (spooky / "stand.png").write_bytes(b"x")

    paths = themes.frame_paths("spooky", base=tmp_path)
    assert paths["stand"] == spooky / "stand.png"          # theme's own frame
    assert paths["run1"] == classic / "run1.png"           # fell back to classic


def test_packaged_classic_frames_exist():
    paths = themes.frame_paths("classic")
    for f in themes.FRAMES:
        assert paths[f].exists(), f"missing packaged frame {f}"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/menubar/test_themes.py -v`
Expected: FAIL with `ModuleNotFoundError` / attribute errors.

- [ ] **Step 3: Write the implementation**

```python
# anon_proxy/menubar/themes.py
"""Dino skins: a theme registry, a holiday calendar, and asset resolution.

Adding a holiday = drop a folder of frame PNGs under assets/dino/<name>/ and add
one THEMES entry (+ a holiday_for rule if it should auto-activate). Missing
frames fall back to classic so a partial theme can never blank the icon.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

FRAMES: tuple[str, ...] = ("stand", "run1", "run2", "dead", "cactus")

THEMES: dict[str, str] = {
    "classic": "classic",
    "winter": "winter",
    "halloween": "halloween",
}

_ASSETS = Path(__file__).resolve().parent.parent / "assets" / "dino"


def holiday_for(date: dt.date) -> str:
    m, d = date.month, date.day
    if (m == 12 and d >= 20) or (m == 1 and d == 1):
        return "winter"
    if m == 10 and d >= 24:
        return "halloween"
    return "classic"


def resolve_theme(selected: str, date: dt.date) -> str:
    name = holiday_for(date) if selected == "auto" else selected
    return name if name in THEMES else "classic"


def frame_paths(theme: str, *, base: Path | None = None) -> dict[str, Path]:
    base = base if base is not None else _ASSETS
    subdir = THEMES.get(theme, "classic")
    theme_dir = base / subdir
    classic_dir = base / "classic"
    out: dict[str, Path] = {}
    for f in FRAMES:
        candidate = theme_dir / f"{f}.png"
        out[f] = candidate if candidate.exists() else classic_dir / f"{f}.png"
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/menubar/test_themes.py -v`
Expected: PASS (4 passed). (`test_packaged_classic_frames_exist` relies on Task 1's committed PNGs.)

- [ ] **Step 5: Commit**

```bash
git add anon_proxy/menubar/themes.py tests/menubar/test_themes.py
git commit -m "feat: dino theme registry, holiday calendar, classic fallback"
```

---

### Task 4: Persisted config

**Files:**
- Create: `anon_proxy/menubar/config.py`
- Test: `tests/menubar/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `DEFAULTS: dict` = `{"theme": "auto", "start_at_login": False, "url": "http://127.0.0.1:8080/_status"}`
  - `default_path() -> Path` = `~/.config/anon-proxy/menubar.json`
  - `load_config(path: Path | None = None) -> dict` — defaults merged with file (missing/corrupt file → defaults).
  - `save_config(cfg: dict, path: Path | None = None) -> None` — atomic write, creating parent dirs.

- [ ] **Step 1: Write the failing tests**

```python
# tests/menubar/test_config.py
from anon_proxy.menubar import config


def test_load_returns_defaults_when_missing(tmp_path):
    cfg = config.load_config(tmp_path / "nope.json")
    assert cfg == config.DEFAULTS
    assert cfg is not config.DEFAULTS  # a copy, not the shared dict


def test_save_then_load_roundtrip(tmp_path):
    p = tmp_path / "sub" / "menubar.json"
    config.save_config({"theme": "winter", "start_at_login": True,
                        "url": "http://x/_status"}, p)
    cfg = config.load_config(p)
    assert cfg["theme"] == "winter"
    assert cfg["start_at_login"] is True


def test_partial_file_is_merged_over_defaults(tmp_path):
    p = tmp_path / "menubar.json"
    p.write_text('{"theme": "halloween"}')
    cfg = config.load_config(p)
    assert cfg["theme"] == "halloween"
    assert cfg["start_at_login"] is False           # default preserved


def test_corrupt_file_falls_back_to_defaults(tmp_path):
    p = tmp_path / "menubar.json"
    p.write_text("{not json")
    assert config.load_config(p) == config.DEFAULTS
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/menubar/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

```python
# anon_proxy/menubar/config.py
"""Persisted menu-bar preferences (theme choice, start-at-login, status URL)."""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULTS: dict = {
    "theme": "auto",
    "start_at_login": False,
    "url": "http://127.0.0.1:8080/_status",
}


def default_path() -> Path:
    return Path.home() / ".config" / "anon-proxy" / "menubar.json"


def load_config(path: Path | None = None) -> dict:
    path = path or default_path()
    cfg = dict(DEFAULTS)
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return cfg
    if isinstance(data, dict):
        cfg.update({k: data[k] for k in DEFAULTS if k in data})
    return cfg


def save_config(cfg: dict, path: Path | None = None) -> None:
    path = path or default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, path)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/menubar/test_config.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add anon_proxy/menubar/config.py tests/menubar/test_config.py
git commit -m "feat: persisted menubar config with defaults + atomic save"
```

---

### Task 5: Render logic (status → icon state, FPS, menu text)

**Files:**
- Create: `anon_proxy/menubar/render.py`
- Test: `tests/menubar/test_render.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `fps_for(tps: float) -> float` = `min(12.0, 1.5 + tps/28.0)`.
  - `@dataclass RenderState` fields: `icon_state: str` (`"running"|"idle"|"alarm"|"down"`), `fps: float`, `title: str`, `tooltip: str`, `menu: list[str]`.
  - `render(status: dict | None, *, alarm: bool, now: float) -> RenderState`.
  - `format_watch_line(status: dict | None, *, alarm: bool, now: float) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/menubar/test_render.py
from anon_proxy.menubar.render import fps_for, render, format_watch_line


def _status(**over):
    base = {
        "status": "running", "listen_addr": "127.0.0.1:8080",
        "tokens_per_sec": 0.0, "requests_masked_total": 0,
        "entities_masked_total": 0, "masking_errors_total": 0,
        "tokens_out_total": 0, "last_client": None, "by_client": {},
        "backend": "mps", "uptime_sec": 0.0, "store": 0,
    }
    base.update(over)
    return base


def test_fps_scales_and_caps():
    assert fps_for(0) == 1.5
    assert abs(fps_for(280) - (1.5 + 10)) < 1e-9
    assert fps_for(100000) == 12.0


def test_down_when_status_none():
    r = render(None, alarm=False, now=1.0)
    assert r.icon_state == "down"
    assert "not running" in r.tooltip.lower()


def test_idle_when_no_throughput():
    r = render(_status(tokens_per_sec=0.0), alarm=False, now=1.0)
    assert r.icon_state == "idle"


def test_running_when_throughput_positive():
    r = render(_status(tokens_per_sec=380.0, last_client="Claude Code"), alarm=False, now=1.0)
    assert r.icon_state == "running"
    assert r.fps == fps_for(380.0)
    assert "380" in r.title
    assert any("Claude Code" in line for line in r.menu)


def test_alarm_overrides_running():
    r = render(_status(tokens_per_sec=380.0, masking_errors_total=2), alarm=True, now=1.0)
    assert r.icon_state == "alarm"
    assert any("2" in line and "error" in line.lower() for line in r.menu)


def test_watch_line_is_one_line_string():
    line = format_watch_line(_status(tokens_per_sec=120.0), alarm=False, now=1.0)
    assert "\n" not in line
    assert "120" in line
    assert format_watch_line(None, alarm=False, now=1.0).lower().count("down") == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/menubar/test_render.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

```python
# anon_proxy/menubar/render.py
"""Pure status -> presentation. No rumps, no I/O — trivially unit-testable."""

from __future__ import annotations

from dataclasses import dataclass


def fps_for(tps: float) -> float:
    return min(12.0, 1.5 + tps / 28.0)


@dataclass
class RenderState:
    icon_state: str      # "running" | "idle" | "alarm" | "down"
    fps: float
    title: str           # short menu-bar title (tokens/sec, or "" when idle/down)
    tooltip: str
    menu: list[str]


def _fmt_int(n) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "0"


def _menu_lines(status: dict, alarm: bool) -> list[str]:
    tps = int(round(status.get("tokens_per_sec", 0.0)))
    lines = [
        f"Running · {status.get('listen_addr') or '?'} · {tps} tok/s",
        f"Driving: {status.get('last_client') or '—'}",
        f"Requests {_fmt_int(status.get('requests_masked_total'))}"
        f" · PII {_fmt_int(status.get('entities_masked_total'))}"
        f" · tokens {_fmt_int(status.get('tokens_out_total'))}",
    ]
    by_client = status.get("by_client") or {}
    if by_client:
        parts = [f"{name} {_fmt_int(v.get('requests'))}" for name, v in by_client.items()]
        lines.append("By agent: " + " · ".join(parts))
    errs = int(status.get("masking_errors_total", 0) or 0)
    if errs:
        lines.append(f"⚠️ Masking errors: {errs}")
    lines.append(f"Backend: {status.get('backend') or '?'} · Store: {_fmt_int(status.get('store'))}")
    return lines


def render(status: dict | None, *, alarm: bool, now: float) -> RenderState:
    if status is None:
        return RenderState("down", 0.0, "", "anon-proxy: not running", ["Not running"])
    tps = float(status.get("tokens_per_sec", 0.0) or 0.0)
    if alarm:
        state = "alarm"
    elif tps > 0.0:
        state = "running"
    else:
        state = "idle"
    title = str(int(round(tps))) if state == "running" else ""
    driving = status.get("last_client") or "—"
    tooltip = (
        "anon-proxy: MASKING ERROR — check the proxy"
        if state == "alarm"
        else f"anon-proxy: {int(round(tps))} tok/s · {driving}"
    )
    return RenderState(state, fps_for(tps), title, tooltip, _menu_lines(status, alarm))


def format_watch_line(status: dict | None, *, alarm: bool, now: float) -> str:
    r = render(status, alarm=alarm, now=now)
    if r.icon_state == "down":
        return "● down — proxy not running"
    glyph = {"running": "▶", "idle": "•", "alarm": "⚠"}[r.icon_state]
    return f"{glyph} {r.menu[0]}" + (f"  [{r.icon_state}]" if r.icon_state != "running" else "")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/menubar/test_render.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add anon_proxy/menubar/render.py tests/menubar/test_render.py
git commit -m "feat: pure render logic mapping /_status to icon state + menu"
```

---

### Task 6: Supervisor (subprocess lifecycle + launchd)

**Files:**
- Create: `anon_proxy/menubar/supervisor.py`
- Test: `tests/menubar/test_supervisor.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class ProxySupervisor(cmd: list[str] | None = None)` with `start(extra_args: list[str] | None = None) -> None`, `stop(grace: float = 5.0) -> None`, `restart(extra_args=None) -> None`, `is_running() -> bool`. Default `cmd` = `[sys.executable, "-m", "anon_proxy.server"]`. Only manages the child it spawned.
  - `launch_agent_plist(label: str, program_args: list[str], *, run_at_load: bool = True) -> str` — returns the plist XML.
  - `install_launch_agent(label, program_args, *, plist_dir: Path | None = None, load: bool = True) -> Path` — writes the plist (and `launchctl load` when `load`).
  - `uninstall_launch_agent(label, *, plist_dir: Path | None = None, load: bool = True) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/menubar/test_supervisor.py
import sys
import time

from anon_proxy.menubar.supervisor import (
    ProxySupervisor, launch_agent_plist, install_launch_agent, uninstall_launch_agent,
)


def test_start_stop_lifecycle():
    sup = ProxySupervisor(cmd=[sys.executable, "-c", "import time; time.sleep(30)"])
    assert sup.is_running() is False
    sup.start()
    assert sup.is_running() is True
    sup.stop(grace=2.0)
    assert sup.is_running() is False


def test_restart_replaces_process():
    sup = ProxySupervisor(cmd=[sys.executable, "-c", "import time; time.sleep(30)"])
    sup.start()
    first_pid = sup._proc.pid
    sup.restart()
    assert sup.is_running() is True
    assert sup._proc.pid != first_pid
    sup.stop(grace=2.0)


def test_start_is_idempotent_while_running():
    sup = ProxySupervisor(cmd=[sys.executable, "-c", "import time; time.sleep(30)"])
    sup.start()
    pid = sup._proc.pid
    sup.start()                       # no-op while already running
    assert sup._proc.pid == pid
    sup.stop(grace=2.0)


def test_plist_contains_label_and_args():
    xml = launch_agent_plist("com.anon-proxy.menubar",
                             ["/usr/bin/env", "anon-proxy-menubar"], run_at_load=True)
    assert "com.anon-proxy.menubar" in xml
    assert "anon-proxy-menubar" in xml
    assert "<key>RunAtLoad</key>" in xml
    assert xml.startswith("<?xml")


def test_install_and_uninstall_plist_file(tmp_path):
    p = install_launch_agent("com.anon-proxy.menubar",
                             ["anon-proxy-menubar"], plist_dir=tmp_path, load=False)
    assert p.exists()
    assert p.name == "com.anon-proxy.menubar.plist"
    uninstall_launch_agent("com.anon-proxy.menubar", plist_dir=tmp_path, load=False)
    assert not p.exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/menubar/test_supervisor.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

```python
# anon_proxy/menubar/supervisor.py
"""Lifecycle for a proxy the menu bar launched, plus a launchd Start-at-login agent.

Only ever manages the child process this object spawned (tracked PID). Never
signals a foreign process.
"""

from __future__ import annotations

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


class ProxySupervisor:
    def __init__(self, cmd: list[str] | None = None) -> None:
        self._cmd = cmd or [sys.executable, "-m", "anon_proxy.server"]
        self._proc: subprocess.Popen | None = None

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self, extra_args: list[str] | None = None) -> None:
        if self.is_running():
            return
        self._proc = subprocess.Popen(self._cmd + list(extra_args or []))

    def stop(self, grace: float = 5.0) -> None:
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


def launch_agent_plist(label: str, program_args: list[str], *, run_at_load: bool = True) -> str:
    args = "\n".join(f"    <string>{escape(a)}</string>" for a in program_args)
    return _PLIST_TMPL.format(
        label=escape(label), args=args,
        run_at_load="true" if run_at_load else "false",
    )


def _plist_path(label: str, plist_dir: Path | None) -> Path:
    base = plist_dir if plist_dir is not None else Path.home() / "Library" / "LaunchAgents"
    return base / f"{label}.plist"


def install_launch_agent(
    label: str, program_args: list[str], *, plist_dir: Path | None = None, load: bool = True
) -> Path:
    path = _plist_path(label, plist_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(launch_agent_plist(label, program_args))
    if load:
        subprocess.run(["launchctl", "load", str(path)], check=False)
    return path


def uninstall_launch_agent(label: str, *, plist_dir: Path | None = None, load: bool = True) -> None:
    path = _plist_path(label, plist_dir)
    if load and path.exists():
        subprocess.run(["launchctl", "unload", str(path)], check=False)
    path.unlink(missing_ok=True)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/menubar/test_supervisor.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add anon_proxy/menubar/supervisor.py tests/menubar/test_supervisor.py
git commit -m "feat: proxy supervisor (subprocess lifecycle + launchd agent)"
```

---

### Task 7: rumps app shell, `--watch` fallback, CLI, README

**Files:**
- Create: `anon_proxy/menubar/app.py`
- Test: `tests/menubar/test_watch.py`
- Modify: `README.md` (add "Menu-bar indicator" section)

**Interfaces:**
- Consumes: `statusclient.fetch_status`, `render.render`/`format_watch_line`, `themes`, `config`, `supervisor.ProxySupervisor`.
- Produces:
  - `watch_once(url: str, *, alarm: bool, now: float, get=None) -> str` — one formatted status line (pure-ish; `get` injectable).
  - `watch_loop(url: str, *, interval: float = 2.0) -> None` — prints `watch_once` on a loop (thin).
  - `AlarmLatch` — tracks `masking_errors_total`; `.update(status) -> bool` returns whether latched; `.reset()`.
  - `main(argv: list[str] | None = None) -> None` — argparse `--url`, `--watch`, `--start-proxy`; runs rumps app on macOS else the watch loop.

- [ ] **Step 1: Write the failing tests**

```python
# tests/menubar/test_watch.py
import httpx

from anon_proxy.menubar.app import watch_once, AlarmLatch


def test_watch_once_running_line():
    def fake_get(url, timeout=None):
        return httpx.Response(200, json={
            "status": "running", "listen_addr": "127.0.0.1:8080",
            "tokens_per_sec": 200.0, "requests_masked_total": 3,
            "entities_masked_total": 1, "tokens_out_total": 500,
            "masking_errors_total": 0, "last_client": "Claude Code",
            "by_client": {}, "backend": "mps", "store": 1, "uptime_sec": 5.0,
        })
    line = watch_once("http://x/_status", alarm=False, now=1.0, get=fake_get)
    assert "200" in line and "\n" not in line


def test_watch_once_down_line():
    def fake_get(url, timeout=None):
        raise httpx.ConnectError("refused")
    line = watch_once("http://x/_status", alarm=False, now=1.0, get=fake_get)
    assert "down" in line.lower()


def test_alarm_latch_trips_and_resets():
    latch = AlarmLatch()
    assert latch.update({"masking_errors_total": 0}) is False
    assert latch.update({"masking_errors_total": 1}) is True    # new error -> latched
    assert latch.update({"masking_errors_total": 1}) is True    # stays latched
    latch.reset()
    assert latch.update({"masking_errors_total": 1}) is False   # baseline re-armed


def test_alarm_latch_ignores_missing_status():
    latch = AlarmLatch()
    assert latch.update(None) is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/menubar/test_watch.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'anon_proxy.menubar.app'`

- [ ] **Step 3: Write the implementation**

```python
# anon_proxy/menubar/app.py
"""Menu-bar entry point.

On macOS: a rumps NSStatusBar app polling /_status, animating the dino, and
offering theme/supervise/start-at-login actions. Elsewhere or with --watch: a
live terminal status line. All logic lives in the pure sibling modules; this
file wires them together.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import time

from anon_proxy.menubar import config as cfg
from anon_proxy.menubar import themes
from anon_proxy.menubar.render import format_watch_line, render
from anon_proxy.menubar.statusclient import fetch_status
from anon_proxy.menubar.supervisor import ProxySupervisor

_LABEL = "com.anon-proxy.menubar"


class AlarmLatch:
    """Latches when masking_errors_total rises above the last reset baseline."""

    def __init__(self) -> None:
        self._baseline: int | None = None
        self._latched = False

    def update(self, status: dict | None) -> bool:
        if not status:
            return self._latched
        errs = int(status.get("masking_errors_total", 0) or 0)
        if self._baseline is None:
            self._baseline = errs
        if errs > self._baseline:
            self._latched = True
        return self._latched

    def reset(self) -> None:
        self._baseline = None
        self._latched = False


def watch_once(url: str, *, alarm: bool, now: float, get=None) -> str:
    status = fetch_status(url, get=get)
    return format_watch_line(status, alarm=alarm, now=now)


def watch_loop(url: str, *, interval: float = 2.0) -> None:
    latch = AlarmLatch()
    print(f"watching {url} (Ctrl-C to stop)")
    try:
        while True:
            status = fetch_status(url)
            alarm = latch.update(status)
            print(format_watch_line(status, alarm=alarm, now=time.time()))
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nstopped.")


def _run_macos_app(url: str) -> None:
    import rumps  # lazy: macOS-only dependency

    frames_by_theme: dict[str, dict] = {}

    class DinoApp(rumps.App):
        def __init__(self) -> None:
            super().__init__("anon-proxy", quit_button="Quit menu bar")
            self._cfg = cfg.load_config()
            self._url = url or self._cfg["url"]
            self._latch = AlarmLatch()
            self._supervisor = ProxySupervisor()
            self._frame_idx = 0
            self._last_status: dict | None = None
            self._icon_frames = self._load_frames()
            self.menu = ["(starting…)"]
            # ~10fps animation clock; polling is decimated inside _tick.
            self._poll_every = 10
            self._ticks = 0
            rumps.Timer(self._tick, 0.1).start()

        def _load_frames(self) -> dict:
            theme = themes.resolve_theme(self._cfg["theme"], dt.date.today())
            return themes.frame_paths(theme)

        def _tick(self, _timer) -> None:
            self._ticks += 1
            if self._ticks % self._poll_every == 1:
                self._last_status = fetch_status(self._url)
            alarm = self._latch.update(self._last_status)
            state = render(self._last_status, alarm=alarm, now=time.time())
            self._animate(state)
            self.title = f" {state.title}" if state.title else ""
            self.menu.clear()
            for line in state.menu:
                self.menu.add(line)

        def _animate(self, state) -> None:
            paths = self._icon_frames
            if state.icon_state == "alarm":
                icon = paths["dead"]
            elif state.icon_state == "down":
                icon = paths["stand"]
            elif state.icon_state == "running":
                self._frame_idx ^= 1
                icon = paths["run1"] if self._frame_idx else paths["run2"]
            else:
                icon = paths["stand"]
            self.icon = str(icon)

    DinoApp().run()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="anon-proxy menu-bar indicator")
    parser.add_argument("--url", default=None, help="status endpoint URL")
    parser.add_argument("--watch", action="store_true",
                        help="terminal status line instead of the menu bar")
    parser.add_argument("--start-proxy", action="store_true",
                        help="(macOS app) also launch a supervised proxy on start")
    args = parser.parse_args(argv)

    url = args.url or cfg.load_config()["url"]

    if args.watch or sys.platform != "darwin":
        if sys.platform != "darwin" and not args.watch:
            print("menu bar is macOS-only; showing --watch terminal view instead.")
        watch_loop(url)
        return
    _run_macos_app(url)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/menubar/test_watch.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Add the README section**

Append to `README.md` (below the roadmap or in a "Tooling" area):

```markdown
## Menu-bar indicator (macOS)

A menu-bar dinosaur whose run speed tracks live token throughput, with idle /
masking-error-alarm / down states, per-agent attribution, and holiday skins.

```bash
uv sync --extra menubar
# with the proxy already running (see above):
uv run anon-proxy-menubar                 # menu-bar app (macOS)
uv run anon-proxy-menubar --watch         # terminal status line (any OS)
uv run anon-proxy-menubar --url http://127.0.0.1:8080/_status
```

- **Theme ▸** in the dropdown: `Auto` (holiday-aware), `Classic`, `Halloween`, `Winter`.
- **Start / Stop / Restart proxy** supervises a proxy the app launched itself.
- **Start at login** installs a launchd LaunchAgent (`com.anon-proxy.menubar`).

Regenerate dino art after editing the matrices:
`uv run --extra gen python scripts/gen_dino_assets.py`.
```

- [ ] **Step 6: Full suite + collection check**

Run: `uv run pytest tests/ --collect-only -q 2>&1 | tail -5`
Expected: 0 errors.

Run: `uv run pytest tests/ -q`
Expected: all pass.

- [ ] **Step 7: Manual macOS smoke (evidence for handoff)**

```bash
uv sync --extra menubar
uv run python -m anon_proxy.server --port 8080 &      # terminal 1 (or --start-proxy)
uv run anon-proxy-menubar --url http://127.0.0.1:8080/_status
```

Verify by eye:
- Dino appears in the menu bar; **stands still** when idle.
- Run a real Claude Code session pointed at `http://127.0.0.1:8080/anthropic`;
  the dino **runs, faster at higher throughput**; dropdown shows `Driving: Claude Code`.
- `Theme ▸ Winter` swaps the skin live.
- Force a masking error (temporarily break the detector) → dino goes to the
  **alarm** frame and `⚠️ Masking errors` appears; menu **reset** re-arms it.
- Quit the proxy → icon goes to the **down** (standing, dim) state.

Capture a screen recording or screenshots as handoff evidence.

- [ ] **Step 8: Commit**

```bash
git add anon_proxy/menubar/app.py tests/menubar/test_watch.py README.md
git commit -m "feat: rumps menu-bar dino app + --watch fallback + docs"
```

---

## Self-Review

**Spec coverage (menu-bar portion):**
- Observer over `/_status`, never PII/auth → `statusclient` + pure modules; app only polls. ✓
- Dino icon states idle/running/alarm/down → `render` (Task 5) + `_animate` (Task 7). ✓
- Speed→FPS `1.5 + tps/28` capped → `fps_for` (Task 5). ✓
- Per-agent attribution in dropdown → `_menu_lines` uses `last_client`/`by_client` (Task 5). ✓
- Fail-open alarm, latched until reset → `AlarmLatch` (Task 7). ✓
- Observe + supervise (Start/Stop/Restart, own PID only) → `ProxySupervisor` (Task 6), wired in app. ✓
- launchd Start-at-login opt-in → `install/uninstall_launch_agent` (Task 6). ✓
- Authentic Chrome T-rex sprite (not a duck) → Task 1 matrices + visual acceptance gate. ✓
- Holiday theming, auto-by-date + manual override + fallback → `themes` (Task 3), `config` theme pref (Task 4), Theme submenu (Task 7). ✓
- macOS-only rumps in optional extra; `--watch` fallback elsewhere → Task 1 extras, Task 7 `main`. ✓
- Testing: pure modules unit-tested; rumps shell thin + manual smoke → each task's tests + Task 7 Step 7. ✓

**Placeholder scan:** none — full code and commands in every step. The one
human-judgment step (Task 1 Step 4 visual acceptance) is explicit and gated with
a concrete reference image and pass/fail criteria.

**Type consistency:** `fetch_status(...) -> dict | None` (Task 2) matches all
callers (Tasks 5, 7). `render(status, *, alarm, now) -> RenderState` and
`format_watch_line(status, *, alarm, now)` signatures match tests and `app.py`
usage. `themes.frame_paths(theme, *, base)`, `FRAMES`, `THEMES` names consistent
across Tasks 1/3/7. `ProxySupervisor.start/stop/restart/is_running` and
`launch_agent_plist`/`install_launch_agent`/`uninstall_launch_agent` names match
Task 6 tests and app wiring. Config keys `theme`/`start_at_login`/`url` match
`DEFAULTS` (Task 4) and `app.py` reads.
```
