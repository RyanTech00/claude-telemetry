"""Effort collector — reads reasoning effort levels straight from Claude Code transcripts.

ccusage does not expose the reasoning effort used for each response, but Claude Code
records it on every assistant entry of ~/.claude/projects/<project>/<session>.jsonl
(``"effort": "low" | "medium" | "high" | "xhigh" | "max"``). This module aggregates
those entries into daily (project, model, effort) buckets.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .collector import _session_id_to_project
from .models import EffortUsage

UNKNOWN_EFFORT = "unknown"


def _local_date(timestamp: str) -> str | None:
    """Convert an ISO-8601 UTC timestamp to a local YYYY-MM-DD date (matches ccusage daily)."""
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone()
    return dt.date().isoformat()


def collect_effort_usage(claude_dir: Path, since: str | None = None) -> list[EffortUsage]:
    """
    Scan Claude Code transcripts and return daily usage per (project, model, effort).

    ``since`` is an optional YYYY-MM-DD date; earlier days are skipped. Each API message
    is counted once even if it is written on several transcript lines (streamed content
    blocks repeat the same message id and usage).
    """
    projects_dir = claude_dir / "projects"
    if not projects_dir.is_dir():
        return []

    since_ts = None
    if since:
        try:
            since_ts = datetime.fromisoformat(since).timestamp()
        except ValueError:
            since_ts = None

    # message key -> (date, project, model, effort, input, output, cache_creation, cache_read)
    messages: dict[str, tuple] = {}

    for path in projects_dir.glob("**/*.jsonl"):
        try:
            if since_ts is not None and path.stat().st_mtime < since_ts:
                continue  # file untouched since the cutoff: nothing new in it
        except OSError:
            continue

        # Session files live in projects/<encoded-project-dir>/...; subagent
        # transcripts may be nested deeper, so use the first directory level.
        rel = path.relative_to(projects_dir)
        project = _session_id_to_project(rel.parts[0]) if len(rel.parts) > 1 else "unknown"

        try:
            fh = open(path, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                if '"usage"' not in line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("type") != "assistant":
                    continue
                msg = entry.get("message") or {}
                usage = msg.get("usage") or {}
                model = msg.get("model") or ""
                if not usage or not model or model.startswith("<"):  # e.g. <synthetic>
                    continue
                date = _local_date(entry.get("timestamp", ""))
                if date is None or (since and date < since):
                    continue
                key = msg.get("id") or entry.get("uuid")
                if not key:
                    continue
                effort = entry.get("effort") or entry.get("perTurnEffort") or UNKNOWN_EFFORT
                messages[key] = (
                    date,
                    project,
                    model,
                    str(effort),
                    usage.get("input_tokens") or 0,
                    usage.get("output_tokens") or 0,
                    usage.get("cache_creation_input_tokens") or 0,
                    usage.get("cache_read_input_tokens") or 0,
                )

    buckets: dict[tuple[str, str, str, str], EffortUsage] = {}
    for date, project, model, effort, inp, out, cc, cr in messages.values():
        k = (date, project, model, effort)
        b = buckets.get(k)
        if b is None:
            b = buckets[k] = EffortUsage(date=date, project=project, model=model, effort=effort)
        b.messages += 1
        b.input_tokens += inp
        b.output_tokens += out
        b.cache_creation_tokens += cc
        b.cache_read_tokens += cr
        b.total_tokens += inp + out + cc + cr

    return sorted(buckets.values(), key=lambda r: (r.date, r.project, r.model, r.effort))
