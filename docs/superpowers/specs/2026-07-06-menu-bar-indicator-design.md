# anon-proxy status indicator (macOS menu bar dino) — design

**Date:** 2026-07-06
**Status:** Approved for planning

## Problem

The proxy is a laptop-first CLI server. Today the only signal that it is
running is terminal stdout — once the terminal is buried or closed, you cannot
tell at a glance whether traffic is flowing through the mask/unmask layer or
going out unprotected. For a privacy tool, "is it protecting me right now?" is
the single most important thing to know, and it is currently invisible.

## Goal

A macOS menu bar indicator that answers, at a glance:

1. **Presence** — is the proxy up and listening?
2. **Activity** — is traffic flowing, and how much PII is being masked?
3. **Safety** — has the proxy ever failed to mask a request cleanly (the
   "did my PII just leak?" alarm)?
4. **Attribution** — which agent is driving the traffic (Claude Code, Codex, …)?
5. **Fun** — a Chrome-style running dinosaur whose gait speed tracks live token
   throughput, so the indicator is a delight to watch, not just a status light.

## Non-goals

- Not a full web dashboard (the `/_status` endpoint is dashboard-ready, but the
  dashboard itself is out of scope).
- Not a cross-platform GUI. The menu bar is macOS-only (rumps/NSStatusBar); a
  terminal `--watch` fallback covers other platforms.
- Never surfaces request content or auth headers — counts and agent labels only.

## Architecture

Chosen approach: **status endpoint + decoupled polling menu bar** (observer
pattern), rejected alternatives being (B) menu-bar-supervises-embedded-server
and (C) status-file + file-watch.

Rationale: keeps the codebase invariants intact — the masking layer stays
HTTP-unaware, and the menu bar is a pure observer over a documented HTTP
interface. It matches the real workflow (proxy launched from a terminal or
launchd; menu bar just watches), is testable with Starlette's `TestClient`,
and the same `/_status` endpoint doubles as a k8s liveness/readiness probe for
the multi-user direction.

```
┌─────────────────┐        GET /_status (poll ~1s active / ~3s idle)
│  menu bar app   │ ───────────────────────────────────────────────►┌──────────────┐
│  (rumps, macOS) │ ◄─────────────────────────────────────────────── │ anon-proxy   │
│  renders dino   │   JSON counts (no PII, no headers, no content)    │ server       │
└─────────────────┘                                                   │  ProxyMetrics│
       │ optional: spawn / signal                                     └──────────────┘
       ▼
   proxy subprocess (only when the menu bar launched it)
```

### Components

**1. `ProxyMetrics` (new, `anon_proxy/metrics.py`)**
An in-memory, thread-safe accumulator held on `app.state.metrics`. Pure data +
increment methods; no HTTP knowledge.

Fields:
- `started_at: float`
- `requests_masked_total: int`
- `entities_masked_total: int` — unique PII entities protected, measured as
  **store growth per request** (`len(store)` after − before). The server already
  computes `store_before` in `_handle_proxy`, so this needs zero changes to the
  adapters or `masker.mask()`; the data structure already exposes the count.
  Semantics: counts each distinct PII value once (repeated PII across turns
  reuses its placeholder and is not double-counted) — "entities protected", not
  "substitutions made".
- `masking_errors_total: int` — the alarm source (see below)
- `tokens_out_total: int`
- `tokens_per_sec: float` — EWMA (~3s half-life) of output token rate, for dino speed
- `last_request_at: float | None`
- `last_client: str | None` — classified agent label
- `by_client: dict[str, {"requests": int, "tokens": int}]`

Methods (all cheap, called from `_handle_proxy`):
- `record_request(client_label, entities_masked)` — `entities_masked` is the
  per-request store delta the server already computes
- `record_tokens(n)` — updates total + feeds the EWMA
- `record_masking_error()`
- `snapshot() -> dict` — serialized form for `/_status`

**2. Agent classification (new, `anon_proxy/client_id.py`)**
Pure function `classify_client(headers) -> str` over request headers:
- `claude-cli` in user-agent (+ `x-app`) → `"Claude Code"`
- `originator: codex_cli_*` or `codex` in user-agent → `"Codex"`
- `x-stainless-*` present → `"OpenAI SDK"` / `"Anthropic SDK"` per package header
- else → leading product token of user-agent, or `"unknown"`
Trivially unit-testable; stores only the label, never the raw headers.

**3. Token throughput measurement (in `server.py` / adapters)**
Two sources, for robustness:
- Exact: read `usage.output_tokens` (Anthropic) / `usage.completion_tokens`
  (OpenAI) from non-streaming responses and from the final streaming usage event.
- Fallback (always available): the server already observes the client-facing
  stream text via the `on_client_text` hook; approximate tokens as
  `len(streamed_text) / 4` when no usage is reported. This makes the dino run
  even for clients that do not request usage.
`tokens_per_sec` is smoothed server-side so the menu bar reads a stable rate.

**4. `/_status` endpoint (in `server.py`)**
`GET /_status` — an internal, non-proxied route (matched before the catch-all
provider dispatch) returning `metrics.snapshot()` plus `listen_addr`,
`providers`, `backend`, and `store` size. Content-type `application/json`.
Returns only counts/labels. This is the one interface the menu bar depends on.

**5. Menu bar app (new, `anon_proxy/menubar.py`, optional extra)**
`python -m anon_proxy.menubar [--url http://127.0.0.1:8080] [--watch]`.
- macOS: rumps app polling `/_status`, rendering the dino icon + dropdown.
- Non-macOS or `--watch`: renders the same status as a live-updating terminal
  line (so the feature is not a dead end off-macOS; serves the k8s direction).
- Pure render function `render(status_json) -> (icon_state, menu_labels)` is
  factored out and unit-tested; the rumps glue is a thin shell.
- Observe **+ supervise**: can `Start / Stop / Restart` a proxy it launched
  itself (tracks the child PID); externally-launched proxies are observe-only
  (Start/Stop disabled, status still shown).
- `Start at login` toggle installs/removes a `launchd` LaunchAgent plist
  (opt-in) so the indicator — and optionally the proxy — return after reboot.

`rumps` is a macOS-only optional dependency: `anon-proxy[menubar]`. Core proxy
gains no new hard dependencies.

## Visual states (the dino)

The menu bar icon is a running dinosaur; gait speed ∝ `tokens_per_sec`.

| State | Dino | Trigger |
|---|---|---|
| Idle | standing still | no traffic |
| Trickle | ambling | ~tens tok/s |
| Cranking | full sprint | hundreds tok/s |
| **Alarm (latched)** | hits a cactus, turns red | `masking_errors_total` increased; stays until user resets |
| Down | dim / "zzz" | status poll failed (connection refused) |

Speed→FPS mapping (`1.5 + tokens_per_sec/28`, capped) is approved via the
interactive HTML prototype
(`docs/superpowers/prototypes/dino/index.html`). The prototype's hand-authored
sprite is a **placeholder** — implementation uses an authentic Chrome T-rex
sprite (the placeholder reads as a duck: neck too long, head wrong). Frames
needed per theme: `stand`, `run1`, `run2`, `dead`; plus an obstacle (`cactus`)
for the alarm.

### Theming / holiday skins

Like Google's Chrome Dino holiday easter eggs, the dino is **themeable**.

- A theme is a folder of frame PNGs (`stand/run1/run2/dead/cactus`) under
  `anon_proxy/assets/dino/<theme>/`, registered in a small `THEMES` table.
- `classic` is the default (authentic gray T-rex).
- Holiday themes (e.g. `halloween` pumpkin dino, `winter` santa-hat dino,
  `newyear`) are selected automatically by date via a `holiday_for(date)`
  calendar function, with a **manual override** in a menu `Theme ▸` submenu
  (`Auto`, `Classic`, `Halloween`, …). Selection persists in a tiny config
  file (`~/.config/anon-proxy/menubar.json`).
- Menu bar rendering: themed/colored frames use a non-template `NSImage` (so
  color shows); `classic` may use a template image (auto-adapts to light/dark
  menu bar). The renderer picks per theme.
- Adding a holiday later = drop a frame folder + one `THEMES`/calendar entry;
  no code changes to the animation or polling loop. `holiday_for` and the theme
  registry are pure and unit-tested; missing/partial theme assets fall back to
  `classic` (never a blank icon).

Dropdown detail:
```
🦖 Running · 127.0.0.1:8080 · 380 tok/s
  Driving: Claude Code
  Uptime 2h14m · backend: mps
  Requests 143 · PII masked 512 · tokens 1.2M
  By agent: Claude Code 412 · Codex 88
  Last request 8s ago
  ⚠️ Masking errors: 0        (submenu: reset / show last, only when >0)
  Store: 37 entities
  ─────────
  Open status JSON · Copy base URL
  Start / Stop / Restart proxy
  Theme ▸  (Auto · Classic · Halloween · Winter · …)
  Start at login  ✓
  Quit menu bar
```

## The alarm signal (safety)

`masking_errors_total` increments whenever masking a should-be-masked request
raises. Today that path 500s (fail-closed-ish); the counter makes it visible
regardless. If fail-open masking policy (remediation-08) later lands, the same
counter cleanly distinguishes "leaked" vs "blocked" — no redesign needed. The
alarm latches (red dino) until the user explicitly resets, so a transient error
is never silently missed.

## Error handling

- Menu bar poll failure → "Down" state, not a crash; keeps polling.
- `/_status` must never raise on partial metrics; `snapshot()` returns defaults.
- Metrics increments are wrapped so a metrics bug can never break a proxied
  request (fail-open on telemetry, never on masking).
- Supervised subprocess: Stop sends SIGTERM then SIGKILL after a grace period;
  Restart re-spawns with the same flags.

## Testing

- Unit: `ProxyMetrics` increments (every counter incl. error path, EWMA math);
  `classify_client` over a table of real user-agent/header fixtures;
  `render(status_json)` → icon state + labels for idle/active/alarm/down;
  `holiday_for(date)` over a fixture calendar; theme registry falls back to
  `classic` on missing assets.
- Integration: `/_status` via `TestClient` — shape correct; counts move after a
  masked request; `masking_errors_total` bumps when the masker raises;
  `tokens_out_total` moves for both usage-reported and fallback paths.
- Manual (documented): macOS smoke launch of the rumps app; observe dino speed
  under a real Claude Code session; trip the alarm by forcing a masker error.

## Rollout / packaging

- `rumps` under `[project.optional-dependencies] menubar`.
- New modules: `metrics.py`, `client_id.py`, `menubar.py`; edits to `server.py`
  (endpoint + increments) and the adapters (token counting hook).
- Console-script entry point `anon-proxy-menubar = anon_proxy.menubar:main`.
- README: a "Menu bar indicator" section with install + launch + launchd notes.
