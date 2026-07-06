from __future__ import annotations

import json
import sys
from typing import TextIO

_MAGENTA = "\033[95m"
_RESET = "\033[0m"


class EventSink:
    """Emit human or JSON event lines through one path.

    JSON payloads carry operational metadata only. Caller-supplied display text
    is allowed in human messages but is intentionally not serialized.
    """

    def __init__(self, *, log_json: bool = False, stream: TextIO | None = None) -> None:
        self.log_json = log_json
        self._stream = stream

    def metrics(
        self,
        *,
        provider: str,
        e2e: float,
        upstream: float,
        usage: dict | None = None,
    ) -> None:
        proxy = max(e2e - upstream, 0.0)
        proxy_pct = (proxy / e2e * 100.0) if e2e > 0 else 0.0
        payload = {
            "event": "metrics",
            "provider": provider,
            "e2e_ms": round(e2e * 1000, 1),
            "upstream_ms": round(upstream * 1000, 1),
            "proxy_ms": round(proxy * 1000, 1),
            "proxy_pct": round(proxy_pct, 1),
        }
        if usage is not None:
            payload["usage"] = usage
        human = _format_metrics(provider, payload, usage)
        self._emit(payload, human)

    def canary_hit(self, *, provider: str, path: str, display_text: str = "") -> None:
        payload = {"event": "canary_hit", "provider": provider, "path": path}
        suffix = f": {display_text}" if display_text else ""
        self._emit(payload, f"[canary {provider}] {path}{suffix}")

    def unknown_token(
        self,
        *,
        provider: str,
        path: str,
        label: str,
        display_text: str = "",
    ) -> None:
        payload = {
            "event": "unknown_token",
            "provider": provider,
            "path": path,
            "label": label,
        }
        suffix = f": {display_text}" if display_text else ""
        self._emit(payload, f"[unknown-token {provider}] {path} {label}{suffix}")

    def _emit(self, payload: dict, human_line: str) -> None:
        stream = self._stream if self._stream is not None else sys.stderr
        if self.log_json:
            print(json.dumps(payload, sort_keys=True), file=stream)
        else:
            print(human_line, file=stream)
        stream.flush()


def _format_metrics(provider: str, payload: dict, usage: dict | None) -> str:
    token_part = ""
    if usage is not None:
        token_part = (
            f"  tokens: in={usage['input']} cache_read={usage['cache_read']} "
            f"cache_create={usage['cache_creation']}"
        )
    return (
        f"{_MAGENTA}[metrics {provider}]{_RESET} "
        f"e2e={payload['e2e_ms']:.1f}ms  "
        f"upstream={payload['upstream_ms']:.1f}ms  "
        f"proxy={payload['proxy_ms']:.1f}ms ({payload['proxy_pct']:.1f}%)"
        f"{token_part}"
    )
