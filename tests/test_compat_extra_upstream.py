from __future__ import annotations

from anon_proxy.regex_detector import RegexDetector
from anon_proxy.upstream import UpstreamConfig
from tests.support.mock_upstream import (
    assert_masked_roundtrip,
    fixture_json,
    proxy_client,
    record_route,
)


def test_extra_openai_compatible_upstream_roundtrips_from_template(make_masker):
    masker = make_masker(extra_detectors=[RegexDetector({"PERSON": r"\bAlice\b"})])
    client, upstream = proxy_client(
        masker,
        extra_upstreams={
            "acme": UpstreamConfig(
                name="acme",
                base_url="https://api.acme.example",
                path_prefix="v1",
                adapter="openai",
            )
        },
        routes=[
            record_route(
                "POST",
                "/v1/chat/completions",
                json_body=fixture_json("openai", "chat_basic.response.json"),
            )
        ],
    )

    with client:
        response = client.post(
            "/acme/v1/chat/completions",
            json=fixture_json("openai", "chat_basic.request.json"),
        )

    assert response.status_code == 200
    assert upstream.requests[0].url == "https://api.acme.example/v1/chat/completions"
    assert_masked_roundtrip(
        upstream.requests[0].body,
        response.content,
        raw="Alice",
        token="<PERSON_1>",
    )
