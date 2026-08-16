import json
from types import SimpleNamespace

from starlette.testclient import TestClient

from anon_proxy.metrics import ProxyMetrics
from anon_proxy.registry import MaskerRegistry
from anon_proxy.server import build_app


def _status_masker(*, backend: str = "auto"):
    return SimpleNamespace(backend=backend, store=[])


def test_status_reports_metrics_and_static_facts():
    metrics = ProxyMetrics(started_at=0.0)
    metrics.record_request("Claude Code", entities_masked=2, now=1.0)
    metrics.record_tokens("Claude Code", 40, now=1.0)
    app = build_app(
        masker=_status_masker(backend="mps"),
        metrics=metrics,
        backend="mps",
        listen_addr="127.0.0.1:8080",
    )

    with TestClient(app) as client:
        resp = client.get("/_status")

    body = json.loads(resp.text)
    assert resp.status_code == 200
    assert body["status"] == "running"
    assert body["backend"] == "mps"
    assert body["listen_addr"] == "127.0.0.1:8080"
    assert body["requests_masked_total"] == 1
    assert body["entities_masked_total"] == 2
    assert body["tokens_out_total"] == 40
    assert body["last_client"] == "Claude Code"
    assert "anthropic" in body["providers"]
    assert "openai" in body["providers"]
    assert body["store"] == 0


def test_status_route_not_treated_as_provider():
    app = build_app(masker=_status_masker(), metrics=ProxyMetrics(started_at=0.0))

    with TestClient(app) as client:
        resp = client.get("/_status")

    assert resp.status_code == 200
    assert json.loads(resp.text)["status"] == "running"


def test_multi_user_status_reports_without_single_user_masker():
    app = build_app(
        registry=MaskerRegistry(lambda store: _status_masker(), store_dir=None),
        metrics=ProxyMetrics(started_at=0.0),
    )

    with TestClient(app) as client:
        resp = client.get("/_status")

    body = json.loads(resp.text)
    assert resp.status_code == 200
    assert body["status"] == "running"
    assert body["store"] == 0


def test_status_reports_resolved_backend_not_auto(monkeypatch):
    from anon_proxy import privacy_filter
    from anon_proxy.masker import Masker

    monkeypatch.setattr(
        privacy_filter, "_module_available", lambda name: name == "onnxruntime"
    )
    monkeypatch.setattr(
        privacy_filter, "_load_onnx_classifier", lambda **_kw: lambda *_a, **_k: []
    )
    pf = privacy_filter.PrivacyFilter(backend="auto")

    app = build_app(
        masker=Masker(filter=pf),
        metrics=ProxyMetrics(started_at=0.0),
        backend="auto",
    )

    with TestClient(app) as client:
        resp = client.get("/_status")

    assert resp.status_code == 200
    assert json.loads(resp.text)["backend"] == "onnx"
