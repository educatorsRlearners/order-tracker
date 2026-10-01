import asyncio
import logging

from fastapi import FastAPI, Request

from app import agent, config, evidence

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("incident")

app = FastAPI(title="Incident Response")
in_flight: set[str] = set()  # Grafana re-sends firing alerts; one investigation per incident
tasks: set[asyncio.Task] = set()


async def handle_alert(alert: dict, group: dict) -> None:
    name = evidence.incident_id(alert)
    directory = config.INCIDENTS_DIR / name
    try:
        manifest = await evidence.collect(alert, group, directory)
        logger.info("Saved evidence for %s: %s", name, manifest["files"])
        if config.AGENT_ENABLED:
            code = await agent.run(directory)
            logger.info("Agent for %s exited with %s", name, code)
    except Exception:
        logger.exception("Incident %s failed", name)
        in_flight.discard(name)  # allow a retry on the next re-send
    # On success the id stays in in_flight so repeat notifications don't start a second agent.


@app.post("/alerts", status_code=202)
async def receive_alerts(request: Request):
    payload = await request.json()
    started, skipped = [], []
    for alert in payload.get("alerts", []):
        name = evidence.incident_id(alert)
        if alert.get("status") != "firing" or name in in_flight or (config.INCIDENTS_DIR / name / "manifest.json").exists():
            skipped.append(name)
            continue
        in_flight.add(name)
        task = asyncio.create_task(handle_alert(alert, {k: v for k, v in payload.items() if k != "alerts"}))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        started.append(name)
    return {"started": started, "skipped": skipped}


@app.get("/healthz")
def health():
    return {"status": "ok"}
