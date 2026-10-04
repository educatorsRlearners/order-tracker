# Incident report 20261004T164620Z-1f2bdcaa0d1aa41b

**Status: RESOLVED (code fix in working tree, NOT committed or deployed)**

**Affected endpoint:** `GET /api/orders/{order_id}` (also reached via `POST /api/orders` and `PATCH /api/orders/{order_id}`, which call `get_order`). Only `express` priority orders whose `created_at` falls near month end are affected.

## Timeline (UTC, 2026-10-04)
- ~16:45:22: first failing request, trace `3cad6e11...`, `curl` for order `78d8ac53-1fef-4e38-9555-24456e0ed268`. This is the first non-zero 500 sample on the route. Every earlier 500 sample is 0.
- ~16:45:22: second failing request, trace `740b2f21...`, same order.
- 16:46:20: Grafana alert "Order Tracker 5xx responses" fires (critical, 2 5xx in 5 min).
- Only 2 errors are in the window. Both are for the same order, so this looks like a manual repro or test rather than organic traffic.

## Root cause
`order_detail()` in `app/main.py` computed the express estimated delivery as `placed_at.replace(day=placed_at.day + 2)`. When the order was placed on the 29th, 30th or 31st, the day goes out of range for the month and `ValueError: day is out of range for month` is raised. The result is an unhandled 500. Standard orders skip this branch, so they are unaffected.

The seed data in `init_db` inserts an express order dated the last day of the previous month (`previous_month_end`). That makes the bug reproducible at startup on any date.

## Evidence
- Trace `740b2f21713eccc1acbaaaa2950b1373`: SERVER span `GET /api/orders/{order_id}` has `http.status_code=500` and an exception event. The `order.lookup` child span shows the same exception, so the failure is inside `get_order`.
  - Stacktrace: `app/main.py line 120, in get_order -> line 64, in order_detail: estimated_at = placed_at.replace(day=placed_at.day + 2)` raising `ValueError: day is out of range for month`.
- Trace `3cad6e1100a4fd5876f0e25c0752b15b`: the second 500, same order. I only inspected its header and did not read it in full, but it matches the log below and the same order ID.
- Loki, `scope_name=app.orders`: `Order lookup hit: order_id=78d8ac53-1fef-4e38-9555-24456e0ed268 priority=express`, logged once for each trace (`3cad6e11...` and `740b2f21...`) and once for an unrelated trace `e672c0f9...`. The lookup succeeded and the failure came after it. The `priority=express` value fits the failing branch.
- `request_rates.json`: `500 /api/orders/{order_id}` is 0 until the final sample (`1791132380`, ~2.07 req/s rate). Healthz and the other routes show no 500s.

## What I changed
- `app/main.py`: `placed_at.replace(day=placed_at.day + 2)` is now `placed_at + timedelta(days=2)`. `timedelta` was already imported. This also handles month and year rollover correctly.
- `tests/test_api.py`: added `test_express_estimate_crosses_month_end`, parametrized over 09-30 to 10-02, 12-31 to 01-02, and a mid-month case.
- `uv run --frozen pytest -q`: 6 passed. I did not confirm the new test fails without the fix; the mid-month case is a no-op either way, but the two month-end cases hit the exact crash from the trace.

## Follow-ups for the developers
- The fix is uncommitted and not deployed. I did not commit, push or restart/rebuild containers, as instructed. It needs to be reviewed, committed and deployed for the running service to stop returning 500s.
- Check whether the existing database already holds express orders placed on the 29th to 31st. They will return 200 once the fix is deployed, so no data change is needed.
- The 2-day estimate is a calendar-day delta with no business-day logic. That is unchanged behaviour, so confirm the product intent.
- Alert noise: the repo working tree has two untracked incident dirs, `20261004T164254Z-unknown` and this one. That is from the earlier incident-reporting test and is unrelated to the fix.
