from types import SimpleNamespace

import httpx
from starlette.testclient import TestClient

from anon_proxy.metrics import ProxyMetrics
from anon_proxy.server import build_app


def test_upstream_client_honors_env_proxy(monkeypatch):
    captured = {}
    real_async_client = httpx.AsyncClient

    def make_client(*args, **kwargs):
        captured.update(kwargs)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", make_client)
    app = build_app(
        masker=SimpleNamespace(backend="auto", store=[]),
        metrics=ProxyMetrics(started_at=0.0),
    )

    with TestClient(app) as client:
        assert client.get("/_status").status_code == 200

    assert captured["trust_env"] is True
