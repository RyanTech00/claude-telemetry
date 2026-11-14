"""Sync module — sends collected data to Supabase."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from supabase import create_client, Client

from .config import load_config, update_last_sync, get_last_sync
from .models import DailyUsage, EffortUsage, SessionUsage, RateLimit, StatsExtra, BlockUsage, SyncResult

logger = logging.getLogger("claude-telemetry")


def _get_client(config: dict[str, Any]) -> Client:
    return create_client(config["supabase_url"], config["supabase_service_key"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sync_daily_usage(
    records: list[DailyUsage],
    machine_id: str,
    client: Client,
    force: bool = False,
) -> SyncResult:
    """Batch upsert daily usage records to Supabase."""
    start = time.monotonic()
    errors: list[str] = []
    upserted = 0

    last_sync = None if force else get_last_sync("daily_usage")

    rows = []
    for record in records:
        if last_sync and record.date < last_sync[:10]:
            continue
        rows.append({
            "machine_id": machine_id,
            "date": record.date,
            "project": record.project,
            "model": record.model,
            "input_tokens": record.input_tokens,
            "output_tokens": record.output_tokens,
            "cache_creation_tokens": record.cache_creation_tokens,
            "cache_read_tokens": record.cache_read_tokens,
            "total_tokens": record.total_tokens,
            "cost_usd": record.cost_usd,
        })

    # Deduplicate by (machine_id, date, project, model) keeping highest cost
    seen: dict[tuple[str, str, str, str], dict] = {}
    for row in rows:
        key = (row["machine_id"], row["date"], row["project"], row["model"])
        if key not in seen or row.get("cost_usd", 0) > seen[key].get("cost_usd", 0):
            seen[key] = row
    rows = list(seen.values())

    if rows:
        try:
            client.table("daily_usage").upsert(
                rows,
                on_conflict="machine_id,date,project,model",
            ).execute()
            upserted = len(rows)
        except Exception as e:
            errors.append(f"daily_usage batch: {e}")

    elapsed = int((time.monotonic() - start) * 1000)

    if not errors:
        update_last_sync("daily_usage", _now_iso())

    _log_sync(client, machine_id, "daily_usage", upserted, errors, elapsed)

    return SyncResult(
        source="daily_usage",
        records_upserted=upserted,
        errors=errors,
        duration_ms=elapsed,
    )


def sync_effort_usage(
    records: list[EffortUsage],
    machine_id: str,
    client: Client,
    batch_size: int = 500,
) -> SyncResult:
    """Batch upsert daily effort usage records to Supabase.

    Each record is a full-day total recomputed from the transcripts, so upserting
    replaces the previous value (idempotent, safe to resend).
    """
    start = time.monotonic()
    errors: list[str] = []
    upserted = 0

    rows = [{
        "machine_id": machine_id,
        "date": r.date,
        "project": r.project,
        "model": r.model,
        "effort": r.effort,
        "messages": r.messages,
        "input_tokens": r.input_tokens,
        "output_tokens": r.output_tokens,
        "cache_creation_tokens": r.cache_creation_tokens,
        "cache_read_tokens": r.cache_read_tokens,
        "total_tokens": r.total_tokens,
    } for r in records]

    for i in range(0, len(rows), batch_size):
        chunk = rows[i:i + batch_size]
        try:
            client.table("effort_usage").upsert(
                chunk,
                on_conflict="machine_id,date,project,model,effort",
            ).execute()
            upserted += len(chunk)
        except Exception as e:
            errors.append(f"effort_usage batch: {e}")
            break

    elapsed = int((time.monotonic() - start) * 1000)

    if not errors:
        update_last_sync("effort_usage", _now_iso())

    _log_sync(client, machine_id, "effort_usage", upserted, errors, elapsed)

    return SyncResult(
        source="effort_usage",
        records_upserted=upserted,
        errors=errors,
        duration_ms=elapsed,
    )


def sync_sessions(
    records: list[SessionUsage],
    machine_id: str,
    client: Client,
    force: bool = False,
) -> SyncResult:
    """Batch upsert session records to Supabase."""
    start = time.monotonic()
    errors: list[str] = []
    upserted = 0

    rows = []
    for record in records:
        rows.append({
            "machine_id": machine_id,
            "session_id": record.session_id,
            "project": record.project,
            "project_path": record.project_path,
            "models": record.models,
            "is_subagent": record.is_subagent,
            "input_tokens": record.input_tokens,
            "output_tokens": record.output_tokens,
            "cache_creation_tokens": record.cache_creation_tokens,
            "cache_read_tokens": record.cache_read_tokens,
            "total_tokens": record.total_tokens,
            "cost_usd": record.cost_usd,
            "last_activity_at": record.last_activity_at,
        })

    # Deduplicate by (machine_id, session_id) keeping highest cost
    seen: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (row["machine_id"], row["session_id"])
        if key not in seen or row.get("cost_usd", 0) > seen[key].get("cost_usd", 0):
            seen[key] = row
    rows = list(seen.values())

    if rows:
        try:
            client.table("sessions").upsert(
                rows,
                on_conflict="machine_id,session_id",
            ).execute()
            upserted = len(rows)
        except Exception as e:
            errors.append(f"sessions batch: {e}")

    elapsed = int((time.monotonic() - start) * 1000)

    if not errors:
        update_last_sync("sessions", _now_iso())

    _log_sync(client, machine_id, "sessions", upserted, errors, elapsed)

    return SyncResult(
        source="sessions",
        records_upserted=upserted,
        errors=errors,
        duration_ms=elapsed,
    )


def sync_rate_limits(
    records: list[RateLimit],
    machine_id: str,
    client: Client,
) -> SyncResult:
    """Batch upsert rate limit records to Supabase."""
    start = time.monotonic()
    errors: list[str] = []
    upserted = 0

    rows = []
    for record in records:
        rows.append({
            "machine_id": machine_id,
            "timestamp": record.timestamp,
            "window_5h_percent": record.window_5h_percent,
            "window_1w_percent": record.window_1w_percent,
            "session_cost_usd": record.session_cost_usd,
            "session_duration_seconds": record.session_duration_seconds,
        })

    if rows:
        try:
            client.table("rate_limits").upsert(
                rows,
                on_conflict="machine_id,timestamp",
            ).execute()
            upserted = len(rows)
        except Exception as e:
            errors.append(f"rate_limits batch: {e}")

    elapsed = int((time.monotonic() - start) * 1000)

    if not errors:
        update_last_sync("rate_limits", _now_iso())

    _log_sync(client, machine_id, "rate_limits", upserted, errors, elapsed)

    return SyncResult(
        source="rate_limits",
        records_upserted=upserted,
        errors=errors,
        duration_ms=elapsed,
    )


def sync_stats_extra(
    stats: StatsExtra,
    machine_id: str,
    client: Client,
) -> SyncResult:
    """Upsert stats_extra record to Supabase (not insert — prevents duplicates)."""
    start = time.monotonic()
    errors: list[str] = []
    upserted = 0

    row = {
        "machine_id": machine_id,
        "total_sessions": stats.total_sessions,
        "total_messages": stats.total_messages,
        "longest_session_messages": stats.longest_session_messages,
        "longest_session_duration_ms": stats.longest_session_duration_ms,
        "first_session_date": stats.first_session_date,
        "hour_counts": stats.hour_counts,
        "daily_activity": stats.daily_activity,
        "model_usage": stats.model_usage,
    }
    try:
        client.table("stats_extra").upsert(
            row,
            on_conflict="machine_id",
        ).execute()
        upserted = 1
    except Exception as e:
        errors.append(f"stats_extra: {e}")

    elapsed = int((time.monotonic() - start) * 1000)

    if not errors:
        update_last_sync("stats_extra", _now_iso())

    _log_sync(client, machine_id, "stats_extra", upserted, errors, elapsed)

    return SyncResult(
        source="stats_extra",
        records_upserted=upserted,
        errors=errors,
        duration_ms=elapsed,
    )


def sync_blocks(
    records: list[BlockUsage],
    machine_id: str,
    client: Client,
) -> SyncResult:
    """Batch upsert block records to Supabase."""
    start_t = time.monotonic()
    errors: list[str] = []
    upserted = 0

    rows = []
    for record in records:
        rows.append({
            "machine_id": machine_id,
            "block_start": record.block_start,
            "block_end": record.block_end,
            "is_active": record.is_active,
            "is_gap": record.is_gap,
            "input_tokens": record.input_tokens,
            "output_tokens": record.output_tokens,
            "cache_creation_tokens": record.cache_creation_tokens,
            "cache_read_tokens": record.cache_read_tokens,
            "total_tokens": record.total_tokens,
            "cost_usd": record.cost_usd,
            "models": record.models,
            "duration_minutes": record.duration_minutes,
            "entries": record.entries,
        })

    # Deduplicate by (machine_id, block_start)
    seen: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (row["machine_id"], row["block_start"])
        if key not in seen or row.get("cost_usd", 0) > seen[key].get("cost_usd", 0):
            seen[key] = row
    rows = list(seen.values())

    if rows:
        # Deactivate blocks no longer reported as active by ccusage
        active_starts = [r["block_start"] for r in rows if r.get("is_active")]
        try:
            q = client.table("blocks").update({"is_active": False}).eq(
                "machine_id", machine_id
            ).eq("is_active", True)
            if active_starts:
                q = q.not_.in_("block_start", active_starts)
            q.execute()
        except Exception:
            pass  # Best-effort deactivation

        try:
            client.table("blocks").upsert(
                rows,
                on_conflict="machine_id,block_start",
            ).execute()
            upserted = len(rows)
        except Exception as e:
            errors.append(f"blocks batch: {e}")

    elapsed = int((time.monotonic() - start_t) * 1000)
    _log_sync(client, machine_id, "blocks", upserted, errors, elapsed)

    return SyncResult(
        source="blocks",
        records_upserted=upserted,
        errors=errors,
        duration_ms=elapsed,
    )


def _log_sync(
    client: Client,
    machine_id: str,
    source: str,
    records_upserted: int,
    errors: list[str],
    duration_ms: int,
) -> None:
    """Write an entry to sync_log and update machine last_sync_at."""
    try:
        client.table("sync_log").insert({
            "machine_id": machine_id,
            "source": source,
            "records_upserted": records_upserted,
            "errors": errors if errors else None,
            "duration_ms": duration_ms,
        }).execute()

        client.table("machines").update({
            "last_sync_at": _now_iso(),
        }).eq("id", machine_id).execute()
    except Exception as e:
        logger.warning("Failed to log sync: %s", e)
