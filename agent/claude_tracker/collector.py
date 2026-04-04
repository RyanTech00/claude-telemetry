"""Collector module — calls ccusage/ccost CLI tools and parses JSON output."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone

from .models import DailyUsage, SessionUsage, RateLimit


class CollectorError(Exception):
    pass


def _run_command(cmd: list[str], timeout: int = 120) -> str:
    """Run a CLI command and return stdout."""
    # On Windows, npx needs shell=True to resolve .cmd wrappers
    use_shell = sys.platform == "win32"
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=use_shell,
    )
    if result.returncode != 0:
        raise CollectorError(f"Command failed: {' '.join(cmd)}\n{result.stderr}")
    return result.stdout


def _detect_subagent(session_id: str) -> bool:
    """Detect if session is a Paperclip subagent by path pattern."""
    return "paperclip-instances-default-" in session_id


def _session_id_to_project(session_id: str) -> str:
    """Extract a readable project name from the session ID path encoding."""
    # ccusage encodes paths as C--Users-RyanS-Documents-project-name

    # Handle Paperclip workspaces/projects
    if "paperclip-instances" in session_id:
        return "Paperclip"

    # Try to extract the last meaningful segment
    # e.g. "c--Users-RyanS-Documents-konta-paperclip" -> "konta-paperclip"
    # Find the last path-like segment (after common prefixes)
    id_lower = session_id.lower()
    for prefix in ["documents-", "projects-", "repos-", "dev-", "code-"]:
        idx = id_lower.find(prefix)
        if idx != -1:
            return session_id[idx + len(prefix):]

    # Fallback: use last segment after the user directory
    # c--Users-RyanS-my-project -> my-project
    segments = session_id.split("-")
    if len(segments) > 3:
        # Skip drive letter and user path segments
        return "-".join(segments[3:])

    return session_id


def collect_daily_usage(since: str | None = None) -> list[DailyUsage]:
    """
    Call `npx ccusage@latest daily --json --instances` and flatten
    the per-project, per-model breakdowns into DailyUsage records.
    """
    cmd = ["npx", "ccusage@latest", "daily", "--json", "--instances", "--no-color"]
    if since:
        cmd.extend(["--since", since])

    raw = _run_command(cmd)
    data = json.loads(raw)

    results: list[DailyUsage] = []
    projects = data.get("projects", {})

    for project_id, days in projects.items():
        project_name = _session_id_to_project(project_id)
        for day in days:
            for breakdown in day.get("modelBreakdowns", []):
                results.append(DailyUsage(
                    date=day["date"],
                    project=project_name,
                    model=breakdown["modelName"],
                    input_tokens=breakdown.get("inputTokens", 0),
                    output_tokens=breakdown.get("outputTokens", 0),
                    cache_creation_tokens=breakdown.get("cacheCreationTokens", 0),
                    cache_read_tokens=breakdown.get("cacheReadTokens", 0),
                    total_tokens=(
                        breakdown.get("inputTokens", 0)
                        + breakdown.get("outputTokens", 0)
                        + breakdown.get("cacheCreationTokens", 0)
                        + breakdown.get("cacheReadTokens", 0)
                    ),
                    cost_usd=breakdown.get("cost", 0.0),
                ))

    return results


def collect_session_usage() -> list[SessionUsage]:
    """Call `npx ccusage@latest session --json` and parse into SessionUsage records."""
    cmd = ["npx", "ccusage@latest", "session", "--json", "--no-color"]
    raw = _run_command(cmd)
    data = json.loads(raw)

    results: list[SessionUsage] = []
    for s in data.get("sessions", []):
        session_id = s["sessionId"]
        results.append(SessionUsage(
            session_id=session_id,
            project=_session_id_to_project(session_id),
            project_path=s.get("projectPath"),
            models=s.get("modelsUsed", []),
            is_subagent=_detect_subagent(session_id),
            input_tokens=s.get("inputTokens", 0),
            output_tokens=s.get("outputTokens", 0),
            cache_creation_tokens=s.get("cacheCreationTokens", 0),
            cache_read_tokens=s.get("cacheReadTokens", 0),
            total_tokens=s.get("totalTokens", 0),
            cost_usd=s.get("totalCost", 0.0),
            last_activity_at=s.get("lastActivity"),
        ))

    return results


def _find_ccost() -> str:
    """Find ccost binary: check venv first, then PATH."""
    import shutil
    from pathlib import Path

    # Check venv/Scripts (Windows) or venv/bin (Unix)
    venv_dir = Path(sys.prefix)
    if sys.platform == "win32":
        venv_ccost = venv_dir / "Scripts" / "ccost.exe"
    else:
        venv_ccost = venv_dir / "bin" / "ccost"
    if venv_ccost.exists():
        return str(venv_ccost)

    # Fall back to PATH
    found = shutil.which("ccost")
    if found:
        return found

    raise FileNotFoundError("ccost not found")


def collect_rate_limits(ccost_path: str | None = None) -> list[RateLimit] | None:
    """(Optional) Call `ccost sl --output json`. Returns None if ccost not installed."""
    try:
        ccost_bin = ccost_path or _find_ccost()
        raw = _run_command([ccost_bin, "sl", "--output", "json"], timeout=60)
        data = json.loads(raw)
        results: list[RateLimit] = []
        for entry in data if isinstance(data, list) else [data]:
            results.append(RateLimit(
                timestamp=entry.get("timestamp", datetime.now(timezone.utc).isoformat()),
                window_5h_percent=entry.get("window_5h_percent"),
                window_1w_percent=entry.get("window_1w_percent"),
                session_cost_usd=entry.get("session_cost_usd"),
                session_duration_seconds=entry.get("session_duration_seconds"),
            ))
        return results
    except (CollectorError, FileNotFoundError, json.JSONDecodeError):
        return None
