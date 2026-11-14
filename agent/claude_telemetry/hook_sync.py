"""Hook-triggered sync for Claude Code real-time data capture.

Designed to be spawned as a detached process from a Claude Code Stop hook.
Runs a single sync cycle then exits. Uses a lock file to debounce — skips
if the last sync was less than MIN_INTERVAL seconds ago.

Usage: python -m claude_telemetry.hook_sync
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from .config import CONFIG_DIR, load_config
from .logging_config import get_rotating_handler

LOCK_FILE = CONFIG_DIR / ".hook_lock"
MIN_INTERVAL = 120  # seconds — minimum gap between hook syncs


def _setup_logging() -> logging.Logger:
    logger = logging.getLogger("claude-telemetry-hook")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        try:
            logger.addHandler(get_rotating_handler("hooks.log"))
        except Exception:
            pass
    return logger


def _should_sync() -> bool:
    """Return False if a sync happened less than MIN_INTERVAL seconds ago."""
    if LOCK_FILE.exists():
        try:
            if time.time() - LOCK_FILE.stat().st_mtime < MIN_INTERVAL:
                return False
        except OSError:
            pass
    return True


def _touch_lock() -> None:
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.touch()


def _run_hook_sync(config: dict[str, Any], logger: logging.Logger) -> None:
    """Single sync cycle — collect data and upsert to Supabase."""
    import platform as _platform

    from supabase import create_client

    from .collector import collect_daily_usage, collect_session_usage, collect_blocks_usage
    from .effort import collect_effort_usage
    from .sync import sync_daily_usage, sync_effort_usage, sync_sessions, sync_blocks

    machine_id = config["machine_id"]
    client = create_client(config["supabase_url"], config["supabase_service_key"])

    # Ensure machine is registered
    client.table("machines").upsert({
        "id": machine_id,
        "name": config.get("machine_name", _platform.node()),
        "api_key": config.get("api_key", ""),
        "hostname": _platform.node(),
    }, on_conflict="id").execute()

    results: dict[str, int] = {}

    # Daily usage (incremental)
    since = None
    last = config.get("last_sync", {}).get("daily_usage")
    if last:
        since = last[:10].replace("-", "")
    daily = collect_daily_usage(since=since)
    r = sync_daily_usage(daily, machine_id, client)
    results["daily_usage"] = r.records_upserted

    # Sessions
    sessions = collect_session_usage()
    r = sync_sessions(sessions, machine_id, client)
    results["sessions"] = r.records_upserted

    # Blocks
    blocks = collect_blocks_usage()
    if blocks:
        r = sync_blocks(blocks, machine_id, client)
        results["blocks"] = r.records_upserted

    # Effort usage (incremental, read directly from transcripts)
    claude_dir = Path(config.get("claude_data_dir", str(Path.home() / ".claude")))
    last_effort = config.get("last_sync", {}).get("effort_usage")
    effort = collect_effort_usage(claude_dir, since=last_effort[:10] if last_effort else None)
    if effort:
        r = sync_effort_usage(effort, machine_id, client)
        results["effort_usage"] = r.records_upserted

    total = sum(results.values())
    logger.info(
        "Hook sync complete: %d records (%s)",
        total,
        ", ".join(f"{k}={v}" for k, v in results.items()),
    )


def main() -> None:
    logger = _setup_logging()

    if not _should_sync():
        logger.debug("Skipping — last hook sync < %ds ago", MIN_INTERVAL)
        return

    _touch_lock()

    try:
        config = load_config()
    except FileNotFoundError:
        logger.warning("Config not found — run 'cc-telemetry setup' first")
        return

    try:
        _run_hook_sync(config, logger)
    except Exception as e:
        logger.error("Hook sync failed: %s", e)


if __name__ == "__main__":
    main()
