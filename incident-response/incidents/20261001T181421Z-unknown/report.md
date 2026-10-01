# Incident report: 20261001T181421Z-unknown

**Status:** RESOLVED (no-op). This was a test notification, not a real incident. No code was changed and no escalation is needed.

**Affected endpoint:** None.

## Timeline
- Evidence window: 2026-10-01 17:59:21Z to 18:15:21Z.
- 18:14:21Z: the `ResponderTest` alert fired with the label `test: "true"` and the summary "Test notification; no incident to fix".

## Root cause
There is no fault. The alert is a synthetic test of the alert-to-responder pipeline.

## Evidence
- `alert.json`: `alertname=ResponderTest`, label `test=true`, summary "Test notification; no incident to fix". There is no severity, endpoint or description.
- `manifest.json`: `affected_endpoint`, `severity` and `fired_at` are all null, and `trace_ids` is empty. No `traces/*.json` files exist (the `traces/` directory is empty).
- `logs.json`: the Loki query returned 0 streams and 0 lines for the window.
- `request_rates.json`: the only non-zero series is `/healthz` with a 200 status at about 7.7 req/s. Every 500-status series is 0 for `/`, `/api/orders`, `/api/orders/{order_id}`, `/docs`, `/docs/oauth2-redirect`, `/healthz`, `/openapi.json` and `/redoc`.

## What I changed
Nothing apart from this report. I did not edit `app/` or `tests/`, and I did not run pytest because no code was touched. I made no commits and did not restart or rebuild any containers.

## Follow-up (optional)
The Loki query returned no log lines at all, not even `/healthz` access logs, even though `/healthz` is serving about 7.7 req/s. The app may not be logging requests to Loki, or the query's label selector may not match. This does not affect this test alert, but whoever owns the observability setup should check it before a real incident relies on those logs.
