from __future__ import annotations

from anon_proxy.regex_detector import RegexDetector
from tests.support.mock_upstream import (
    assert_masked_roundtrip,
    fixture_json,
    fixture_text,
    proxy_client,
    record_route,
)


def test_zai_messages_non_streaming_roundtrip_and_url(make_masker):
    masker = make_masker(extra_detectors=[RegexDetector({"PERSON": r"\bAlice\b"})])
    client, upstream = proxy_client(
        masker,
        routes=[
            record_route(
                "POST",
                "/api/anthropic/v1/messages",
                json_body=fixture_json("anthropic", "messages_basic.response.json"),
            )
        ],
    )

    with client:
        response = client.post(
            "/zai/v1/messages",
            json=fixture_json("anthropic", "messages_basic.request.json"),
        )

    assert response.status_code == 200
    assert upstream.requests[0].url == "https://api.z.ai/api/anthropic/v1/messages"
    assert_masked_roundtrip(
        upstream.requests[0].body,
        response.content,
        raw="Alice",
        token="<PERSON_1>",
    )


def test_zai_messages_streaming_roundtrip(make_masker):
    masker = make_masker(extra_detectors=[RegexDetector({"PERSON": r"\bAlice\b"})])
    client, upstream = proxy_client(
        masker,
        routes=[
            record_route(
                "POST",
                "/api/anthropic/v1/messages",
                sse=fixture_text("anthropic", "messages_basic.response.sse.txt"),
            )
        ],
    )
    request = fixture_json("anthropic", "messages_basic.request.json")
    request["stream"] = True

    with client:
        response = client.post("/zai/v1/messages", json=request)

    assert response.status_code == 200
    assert_masked_roundtrip(
        upstream.requests[0].body,
        response.content,
        raw="Alice",
        token="<PERSON_1>",
    )
