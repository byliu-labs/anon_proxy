"""Operational stderr events with human and PII-free JSON formats."""

from __future__ import annotations

import json
import sys
import time
from typing import TextIO

_MAGENTA = "\033[95m"
_RESET = "\033[0m"
SCHEMA_VERSION = 1


class EventSink:
    def __init__(self, *, log_json: bool = False, stream: TextIO | None = None) -> None:
        self._log_json = log_json
        self._stream = stream

    def metrics(
        self,
        *,
        provider: str,
        e2e: float,
        upstream: float,
        usage: dict | None = None,
        request_id: str | None = None,
    ) -> None:
        proxy = max(e2e - upstream, 0.0)
        proxy_pct = proxy / e2e * 100.0 if e2e > 0 else 0.0
        fields = {
            "provider": provider,
            "e2e_ms": round(e2e * 1000, 1),
            "upstream_ms": round(upstream * 1000, 1),
            "proxy_ms": round(proxy * 1000, 1),
            "proxy_pct": round(proxy_pct, 1),
        }
        if usage is not None:
            fields["usage"] = usage
        if request_id is not None:
            fields["request_id"] = request_id
        self._emit("metrics", _format_metrics(fields), fields)

    def metrics_summary(self, snapshot: dict) -> None:
        human = f"[metrics-summary] {json.dumps(snapshot, sort_keys=True)}"
        self._emit("metrics_summary", human, snapshot)

    def canary_hit(
        self, *, label: str, text: str, action: str, request_id: str | None = None
    ) -> None:
        suffix = " - masking now" if action == "fix" else ""
        human = f"warning: canary: {label} {text!r} survived masking{suffix}"
        fields = {"label": label, "len": len(text), "action": action}
        if request_id is not None:
            fields["request_id"] = request_id
        self._emit("canary_hit", human, fields)

    def unknown_token(self, token: str, *, request_id: str | None = None) -> None:
        human = (
            f"warning: unmask: unknown placeholder {token} left in response "
            f"(model may have invented it)"
        )
        fields = {"token": token}
        if request_id is not None:
            fields["request_id"] = request_id
        self._emit("unmask_unknown_token", human, fields)

    def _emit(self, event: str, human: str, fields: dict) -> None:
        stream = self._stream or sys.stderr
        if self._log_json:
            payload = {
                "schema_version": SCHEMA_VERSION,
                "ts": time.time(),
                "event": event,
                **fields,
            }
            print(json.dumps(payload, sort_keys=True), file=stream)
        else:
            print(human, file=stream)
        stream.flush()


def _format_metrics(fields: dict) -> str:
    usage = fields.get("usage")
    tokens = ""
    if usage is not None:
        tokens = (
            f"  tokens: in={usage['input']} cache_read={usage['cache_read']} "
            f"cache_create={usage['cache_creation']}"
        )
    return (
        f"{_MAGENTA}[metrics {fields['provider']}]{_RESET} "
        f"e2e={fields['e2e_ms']:.1f}ms  upstream={fields['upstream_ms']:.1f}ms  "
        f"proxy={fields['proxy_ms']:.1f}ms ({fields['proxy_pct']:.1f}%){tokens}"
    )
