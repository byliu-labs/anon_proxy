# Observability Contract

anon-proxy emits PII-free operational telemetry for live status and stderr logs.
Detector metadata never includes matched text; it uses `{source, label, score, len}`.
Capture files are different: they contain raw request and response bodies and must
be treated as sensitive local artifacts.

## Schema Stability

Current `schema_version`: `1`.

Additive fields may be added without a version bump. Renaming a field, removing a
field, changing a field's type, or changing an event's meaning requires a new
`schema_version`.

## `/_status`

`GET /_status` returns one JSON object with:

- `schema_version`: integer schema version.
- `status`: `"running"` when the process is alive.
- `started_at`, `uptime_sec`: process lifetime.
- `listen_addr`: configured bind label, or `null`.
- `providers`: configured provider names.
- `backend`: resolved detector backend.
- `store`: current placeholder-store entry count. In multi-user mode this is the
  sum of loaded per-user stores.
- `requests_masked_total`, `entities_masked_total`, `masking_errors_total`,
  `tokens_out_total`, `tokens_per_sec`, `last_request_at`, `last_client`,
  `by_client`: proxy activity counters.
- `detection`: live detector aggregate snapshot.

`detection` contains:

- `mask_calls`: mask operations observed.
- `mask_cache_hits`, `mask_cache_hit_rate`: cache hit count and rate.
- `mask_latency_ms.p50`, `mask_latency_ms.p95`, `mask_latency_ms.p99`: latency
  percentiles over the bounded in-process sample.
- `entities_by_label`: fresh detections by normalized label.
- `entities_by_source`: fresh detections by detector source.
- `canary_hits`, `canary_hit_rate`: canary detections and per-call rate.
- `unknown_tokens`: invented placeholder tokens observed while unmasking.

## JSON Events

With `--log-json`, each stderr line is a JSON object with:

- `schema_version`: integer schema version.
- `ts`: Unix timestamp in seconds.
- `event`: event name.
- `request_id`: short request correlation id when the event belongs to one
  proxied request.

Event-specific fields:

- `metrics`: `provider`, `e2e_ms`, `upstream_ms`, `proxy_ms`, `proxy_pct`, and
  optional `usage`; includes `request_id`.
- `metrics_summary`: the same fields as the `detection` status snapshot.
- `metrics_rollup`: `proxy` with proxy activity counters and `detection` with
  the detector status snapshot.
- `canary_hit`: `label`, `len`, `action`.
- `unmask_unknown_token`: `token`.

`canary_hit` and `unmask_unknown_token` include `request_id` when they occur
inside a proxied request. `canary_hit` reports the matched text length, never the
matched text itself.

## Capture Correlation

`--capture` records include top-level `request_id`. This is the same id emitted
on the request's `metrics` JSON event, so a local capture line can be joined to
PII-free operational logs without copying raw request or response bodies into the
log stream.

## Log Sink And Rotation

The supported deployment model is stderr/stdout collection by the host system:
launchd for the laptop app, container stdout for Docker and Kubernetes, and the
cluster log pipeline for retention and rotation. anon-proxy does not rotate its
own stderr stream.

Use `--metrics-file` for append-only `metrics_rollup` aggregate snapshots when
dashboards or post-hoc analysis need process snapshots outside stderr.
