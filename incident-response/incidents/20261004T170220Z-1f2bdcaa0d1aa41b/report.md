# Incident 20261004T170220Z-1f2bdcaa0d1aa41b

**Status: RESOLVED in the working tree. Not committed or deployed, so the running service is still affected until a developer ships it.**

**Affected endpoint:** `GET /api/orders/{order_id}`. Only express-priority orders are affected; `POST` and `PATCH` also call `get_order`, so they are affected too.

## Timeline (UTC, 2026-10-04)
- 17:01:38 – `GET /api/orders/express-1002` is served. The handler logs "Order lookup hit", then `order_detail` raises `ValueError`. Response is 500.
- 17:02:20 – the first 5xx bucket (~1.2 req/s) appears in `request_rates.json`, and the Grafana alert "Order Tracker 5xx responses" fires.
- No 5xx was recorded on this route before that bucket. Only 1 error was seen in the window.

## Root cause
`order_detail` in `app/main.py` computed the express ETA with `placed_at.replace(day=placed_at.day + 2)`. When the order was placed on day 30 or 31 of a month, `day + 2` is out of range, and `datetime.replace` raises `ValueError: day is out of range for month`.

The seeded order `express-1002` is dated the last day of the previous month (Sept 30), so it always triggers this. Any real express order placed in the last two days of a month would fail the same way.

## Evidence
- Trace `df235e8a1f02d746313e13c0a106c161`: the `GET /api/orders/{order_id}` and `order.lookup` spans both carry an `exception` event with type `ValueError` and the message "day is out of range for month".
- Loki log at 17:01:38: `Order lookup hit: order_id=express-1002 priority=express`. The row was found, so this is not a missing-order case.
- `request_rates.json`: `status=500, route=/api/orders/{order_id}` goes from 0 to 1.2 in the last bucket. The 404 series stays at 0.

## What changed
- `app/main.py`: `placed_at.replace(day=placed_at.day + 2)` became `placed_at + timedelta(days=2)`. `timedelta` was already imported.
- `tests/test_api.py`: added `test_express_estimate_crosses_month_end` with three cases (Sept 30 → Oct 2, Dec 31 → Jan 2, Oct 4 → Oct 6).
- `uv run --frozen pytest -q`: 6 passed.

Both edits were already in the working tree, uncommitted, when I started. I checked them against the evidence and the tests and left them as they were.

## Follow-ups for developers
- Review, commit and deploy the fix. I did not commit or restart containers.
- `Dockerfile` has an unrelated uncommitted change (`UV_HTTP_TIMEOUT=300`).
- The alert fires on a single 5xx. Consider whether that threshold is intended.
