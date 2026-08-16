from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from starlette.testclient import TestClient

from anon_proxy.masker import Masker
from anon_proxy.server import build_app
from anon_proxy.upstream import UpstreamConfig


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@dataclass(frozen=True)
class RouteResponse:
    method: str
    path_suffix: str
    json_body: Any | None = None
    sse_body: str | None = None
    status: int = 200
    headers: dict[str, str] | None = None


@dataclass
class UpstreamRequest:
    method: str
    url: str
    body: bytes
    headers: dict[str, str]


class MockUpstream:
    def __init__(self, routes: list[RouteResponse]) -> None:
        self._routes = {
            (route.method.upper(), route.path_suffix): route for route in routes
        }
        self.requests: list[UpstreamRequest] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        captured = UpstreamRequest(
            method=request.method,
            url=str(request.url),
            body=request.content,
            headers=dict(request.headers),
        )
        self.requests.append(captured)
        key = (request.method.upper(), request.url.path)
        route = self._routes.get(key)
        if route is None:
            return httpx.Response(599, json={"error": f"unhandled upstream {key}"})
        headers = dict(route.headers or {})
        if route.sse_body is not None:
            headers.setdefault("content-type", "text/event-stream")
            return httpx.Response(
                route.status,
                content=route.sse_body.encode("utf-8"),
                headers=headers,
            )
        headers.setdefault("content-type", "application/json")
        return httpx.Response(route.status, json=route.json_body, headers=headers)


def fixture_json(provider: str, name: str) -> Any:
    return json.loads((FIXTURES / provider / name).read_text())


def fixture_text(provider: str, name: str) -> str:
    return (FIXTURES / provider / name).read_text()


def record_route(
    method: str,
    path_suffix: str,
    *,
    json_body: Any | None = None,
    sse: str | None = None,
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> RouteResponse:
    return RouteResponse(
        method=method,
        path_suffix=path_suffix,
        json_body=json_body,
        sse_body=sse,
        status=status,
        headers=headers,
    )


def proxy_client(
    masker: Masker,
    *,
    routes: list[RouteResponse],
    extra_upstreams: dict[str, UpstreamConfig] | None = None,
    system_inject: bool = False,
) -> tuple[TestClient, MockUpstream]:
    upstream = MockUpstream(routes)
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(upstream.handler))
    app = build_app(
        masker=masker,
        extra_upstreams=extra_upstreams,
        http_client=http_client,
        system_inject=system_inject,
    )
    return TestClient(app), upstream


def assert_masked_roundtrip(
    upstream_seen: bytes,
    client_got: bytes,
    *,
    raw: str,
    token: str,
) -> None:
    assert token.encode("utf-8") in upstream_seen
    assert raw.encode("utf-8") not in upstream_seen
    assert raw.encode("utf-8") in client_got
    assert token.encode("utf-8") not in client_got
