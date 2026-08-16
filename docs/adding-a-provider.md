# Adding a provider

Provider support has two moving parts:

1. An `UpstreamConfig` that maps a local provider prefix to an upstream base URL.
2. An adapter contract: `mask_request`, `unmask_response`, and `transform_stream`.

If the upstream speaks an existing protocol, reuse that adapter. For example, an
OpenAI-compatible provider can be registered with `adapter="openai"` and a base URL
for that service. If the upstream has a new request, response, or SSE shape, add a
new adapter module and register it in `anon_proxy.server._ADAPTERS`.

Use mock-upstream compatibility tests before trying a real endpoint. The tests must
drive `build_app(http_client=...)` through `httpx.MockTransport`, assert the exact
bytes seen by the mock upstream, and assert the client response has been unmasked.
Do not point compatibility tests at paid provider APIs.

Template:

```python
from anon_proxy.upstream import UpstreamConfig
from tests.support.mock_upstream import proxy_client, record_route

extra_upstreams = {
    "acme": UpstreamConfig(
        name="acme",
        base_url="https://api.acme.example",
        path_prefix="v1",
        adapter="openai",
    )
}

client, upstream = proxy_client(
    masker,
    extra_upstreams=extra_upstreams,
    routes=[
        record_route("POST", "/v1/chat/completions", json_body=response_fixture)
    ],
)
```

The invariant every provider test must prove:

- Outbound bytes contain the placeholder token and not raw PII.
- Inbound bytes contain raw PII and not the placeholder token.
