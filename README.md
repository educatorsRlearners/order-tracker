# Order Tracker

A small order tracking app for the AI Dev Tools Zoomcamp observability homework. It includes a web page, API, tests, and a Docker Compose setup. You add telemetry, alerts, and an incident responder in Homework 4.

The main user flow is creating an order and checking its status. Three sample orders are created on first startup.

## Run it

You need Docker with Compose. To run the tests, you also need Python 3.11+ and `uv`.

```bash
docker compose up --build -d --wait
```

Open <http://127.0.0.1:8000>. The API is at `/api/orders`, and the health check is at `/healthz`. Data is stored in a Docker volume and survives container recreation.

If port 8000 is occupied, set `ORDER_TRACKER_PORT`, for example:

```bash
ORDER_TRACKER_PORT=18080 docker compose up --build -d --wait
```

Run tests with `uv run --frozen pytest -q`. Stop the app with `docker compose down`. Add `-v` only if you also want to delete the order data.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/` | Web page |
| GET | `/healthz` | Database health check |
| GET | `/api/orders` | List orders |
| POST | `/api/orders` | Create an order |
| GET | `/api/orders/{id}` | Check an order |
| PATCH | `/api/orders/{id}` | Change an order status |

The app uses SQLite to keep setup small. Run one app container at a time. The course exercise is about detecting and handling an incident, not scaling the database.

## Incident response agent

`incident-response/` receives Grafana alerts on `POST /alerts` (port 8001), saves the evidence an on-call engineer would look at, and starts Claude Code headless (`claude -p`) to investigate, fix, or escalate.

It runs on the host (it needs the local `claude` CLI); Grafana reaches it through the provisioned `incident-response` webhook contact point at `host.docker.internal:8001`.

```bash
docker compose up --build -d --wait
cd incident-response && uv run uvicorn app.main:app --port 8001
```

Per alert it writes `incident-response/incidents/<start>-<fingerprint>/` with `alert.json`, `manifest.json`, `logs.json` (Loki), `traces/*.json` (Tempo error traces), `request_rates.json` (Prometheus), then the agent's `agent.jsonl` transcript and `report.md` (RESOLVED or ESCALATED). Resent alerts are ignored. Set `INCIDENT_AGENT=off` to collect evidence without starting the agent. The agent may edit code and run tests, but is told not to commit or touch containers.
