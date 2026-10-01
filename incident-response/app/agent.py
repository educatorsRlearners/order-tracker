"""Start Claude Code headless to play the on-call engineer for one incident."""
import asyncio
import logging
from pathlib import Path

from app import config

logger = logging.getLogger("incident.agent")

PROMPT = """\
You are the on-call engineer for the order-tracker service. A Grafana alert just fired.

Evidence has been saved in {incident_dir} (read manifest.json first):
- alert.json: the Grafana alert payload
- logs.json: Loki logs for the service around the alert
- traces/*.json: Tempo traces with error spans
- request_rates.json: per-route request counts by status code

Work the incident like an on-call engineer:
1. Understand: identify the affected endpoint, what the error is, and when it started. Use the logs and traces to find the failing code path (the app is in app/).
2. Diagnose: find the root cause in the code and say how you know.
3. Resolve: if you are confident of a safe, small fix, make it, add or update a test in tests/, and run `uv run --frozen pytest -q`. Do NOT git commit, push, or restart/rebuild containers.
4. Escalate: if you cannot find the cause, the fix is risky or large, or it needs infrastructure/data changes, do not guess. Hand it to the developers.

Finish by writing {incident_dir}/report.md with: status (RESOLVED or ESCALATED), affected endpoint, timeline, root cause, evidence (log lines / trace IDs), what you changed (files), and for ESCALATED what you tried and what the developers should look at next.
"""

# Read/search/edit freely; Bash only for tests, read-only git, and read-only compose logs.
ALLOWED_TOOLS = [
    "Read", "Grep", "Glob", "Edit", "Write",
    "Bash(uv run --frozen pytest:*)",
    "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)",
    "Bash(docker compose logs:*)", "Bash(docker compose ps:*)",
]


def build_command(incident_dir: Path) -> list[str]:
    return [
        config.CLAUDE_BIN, "-p", PROMPT.format(incident_dir=incident_dir),
        "--output-format", "stream-json", "--verbose",
        "--allowedTools", *ALLOWED_TOOLS,
    ]


async def run(incident_dir: Path) -> int | None:
    """Run the agent to completion, logging its transcript into the incident directory."""
    with (incident_dir / "agent.jsonl").open("wb") as out, (incident_dir / "agent.err").open("wb") as err:
        try:
            proc = await asyncio.create_subprocess_exec(
                *build_command(incident_dir),
                cwd=config.REPO_ROOT,
                stdin=asyncio.subprocess.DEVNULL, stdout=out, stderr=err,
            )
        except FileNotFoundError:
            logger.error("Claude Code binary %r not found; set CLAUDE_BIN", config.CLAUDE_BIN)
            return None
        logger.info("Started agent pid=%s for %s", proc.pid, incident_dir.name)
        try:
            return await asyncio.wait_for(proc.wait(), config.AGENT_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            proc.kill()
            logger.error("Agent for %s timed out after %ss", incident_dir.name, config.AGENT_TIMEOUT_SECONDS)
            return None
