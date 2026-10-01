"""Collect and save what an on-call engineer would look at: the alert, logs, traces, metrics."""
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from app import config

logger = logging.getLogger("incident.evidence")


def parse_time(value: str | None) -> datetime:
    """Parse Grafana's RFC3339 timestamps (nanosecond precision, 'Z' suffix)."""
    if not value or value.startswith("0001-"):
        return datetime.now(timezone.utc)
    value = re.sub(r"(\.\d{6})\d+", r"\1", value.replace("Z", "+00:00"))
    return datetime.fromisoformat(value)


def affected_endpoint(alert: dict) -> str | None:
    labels = alert.get("labels", {})
    return labels.get("http_route") or labels.get("http.route") or labels.get("route")


def incident_id(alert: dict) -> str:
    started = parse_time(alert.get("startsAt")).strftime("%Y%m%dT%H%M%SZ")
    return f"{started}-{alert.get('fingerprint', 'unknown')}"


def window(alert: dict) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    start = min(parse_time(alert.get("startsAt")), now) - timedelta(minutes=config.LOOKBACK_MINUTES)
    return start, now + timedelta(minutes=1)


def _proxy(uid: str, path: str) -> str:
    return f"{config.GRAFANA_URL}/api/datasources/proxy/uid/{uid}{path}"


async def _get(client: httpx.AsyncClient, url: str, **params) -> dict:
    response = await client.get(url, params=params)
    response.raise_for_status()
    return response.json()


async def fetch_logs(client, start: datetime, end: datetime) -> dict:
    return await _get(
        client,
        _proxy("loki", "/loki/api/v1/query_range"),
        query=f'{{service_name="{config.SERVICE_NAME}"}}',
        start=int(start.timestamp() * 1e9),
        end=int(end.timestamp() * 1e9),
        limit=config.LOG_LIMIT,
        direction="backward",
    )


async def fetch_trace_ids(client, start: datetime, end: datetime, route: str | None) -> list[str]:
    # Error spans first; the route filter narrows to the alerting endpoint when known.
    conditions = [f'resource.service.name = "{config.SERVICE_NAME}"', "status = error"]
    if route:
        conditions.append(f'span.http.route = "{route}"')
    result = await _get(
        client,
        _proxy("tempo", "/api/search"),
        q="{ " + " && ".join(conditions) + " }",
        start=int(start.timestamp()),
        end=int(end.timestamp()),
        limit=config.TRACE_LIMIT,
    )
    return [t["traceID"] for t in result.get("traces", [])]


async def fetch_trace(client, trace_id: str) -> dict:
    return await _get(client, _proxy("tempo", f"/api/traces/{trace_id}"))


async def fetch_request_rates(client, start: datetime, end: datetime) -> dict:
    return await _get(
        client,
        _proxy("prometheus", "/api/v1/query_range"),
        query="sum by (http_route, http_response_status_code) "
        "(increase(order_tracker_http_requests_total[1m]))",
        start=start.timestamp(),
        end=end.timestamp(),
        step=60,
    )


def _write(path: Path, data) -> None:
    path.write_text(data if isinstance(data, str) else json.dumps(data, indent=2))


async def collect(alert: dict, group: dict, directory: Path) -> dict:
    """Write everything known about the alert into `directory`.

    Each source is best-effort: a Grafana/Loki/Tempo failure is recorded in the manifest
    rather than blocking the agent, which can still work from the alert itself.
    """
    directory.mkdir(parents=True, exist_ok=True)
    start, end = window(alert)
    route = affected_endpoint(alert)
    _write(directory / "alert.json", {"alert": alert, "group": group})
    manifest = {
        "incident_id": directory.name,
        "alertname": alert.get("labels", {}).get("alertname"),
        "severity": alert.get("labels", {}).get("severity"),
        "affected_endpoint": route,
        "summary": alert.get("annotations", {}).get("summary"),
        "description": alert.get("annotations", {}).get("description"),
        "fired_at": alert.get("startsAt"),
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "files": ["alert.json"],
        "errors": {},
    }

    async with httpx.AsyncClient(timeout=15) as client:
        async def step(name: str, filename: str, fn):
            try:
                _write(directory / filename, await fn())
                manifest["files"].append(filename)
            except Exception as exc:  # noqa: BLE001 - evidence gathering must not fail the incident
                logger.warning("Could not collect %s: %s", name, exc)
                manifest["errors"][name] = repr(exc)

        await step("logs", "logs.json", lambda: fetch_logs(client, start, end))
        await step("request_rates", "request_rates.json", lambda: fetch_request_rates(client, start, end))

        try:
            trace_ids = await fetch_trace_ids(client, start, end, route)
            if route and not trace_ids:  # route attribute may differ; fall back to any error trace
                trace_ids = await fetch_trace_ids(client, start, end, None)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not search traces: %s", exc)
            manifest["errors"]["trace_search"] = repr(exc)
            trace_ids = []
        (directory / "traces").mkdir(exist_ok=True)
        for trace_id in trace_ids:
            await step(f"trace {trace_id}", f"traces/{trace_id}.json", lambda t=trace_id: fetch_trace(client, t))
        manifest["trace_ids"] = trace_ids

    _write(directory / "manifest.json", manifest)
    return manifest
