import os
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = Path(os.getenv("REPO_ROOT", SERVICE_DIR.parent))
INCIDENTS_DIR = Path(os.getenv("INCIDENTS_DIR", SERVICE_DIR / "incidents"))

# Loki, Tempo and Prometheus are not published on the host; Grafana (anonymous Admin in
# compose) proxies to all three, so one URL is enough.
GRAFANA_URL = os.getenv("GRAFANA_URL", "http://localhost:3000").rstrip("/")
LOOKBACK_MINUTES = int(os.getenv("INCIDENT_LOOKBACK_MINUTES", "15"))
LOG_LIMIT = int(os.getenv("INCIDENT_LOG_LIMIT", "500"))
TRACE_LIMIT = int(os.getenv("INCIDENT_TRACE_LIMIT", "10"))
SERVICE_NAME = os.getenv("INCIDENT_SERVICE_NAME", "order-tracker")

AGENT_ENABLED = os.getenv("INCIDENT_AGENT", "on") != "off"
CLAUDE_BIN = os.getenv("CLAUDE_BIN", "claude")
AGENT_TIMEOUT_SECONDS = int(os.getenv("INCIDENT_AGENT_TIMEOUT", "900"))
