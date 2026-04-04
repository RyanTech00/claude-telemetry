"""Daemon mode — auto-sync loop with backoff, signal handling, and logging."""

from __future__ import annotations

import logging
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import CONFIG_DIR, load_config
from .collector import collect_daily_usage, collect_session_usage, collect_rate_limits
from .extras import read_stats_cache

LOG_FILE = CONFIG_DIR / "daemon.log"

logger = logging.getLogger("claude-tracker-daemon")


def _setup_logging(verbose: bool = False) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(message)s"

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(fmt))

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter(fmt))

    logger.setLevel(level)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)


def _run_sync_cycle(config: dict[str, Any]) -> dict[str, int]:
    """Run one full sync cycle. Returns {source: records_upserted}."""
    from supabase import create_client
    from .sync import sync_daily_usage, sync_sessions, sync_rate_limits, sync_stats_extra

    machine_id = config["machine_id"]
    client = create_client(config["supabase_url"], config["supabase_service_key"])
    results: dict[str, int] = {}

    # Daily usage
    since = None
    last = config.get("last_sync", {}).get("daily_usage")
    if last:
        since = last[:10].replace("-", "")
    daily = collect_daily_usage(since=since)
    r = sync_daily_usage(daily, machine_id, client)
    results["daily_usage"] = r.records_upserted
    if r.errors:
        for err in r.errors:
            logger.warning("daily_usage error: %s", err)

    # Sessions
    sessions = collect_session_usage()
    r = sync_sessions(sessions, machine_id, client)
    results["sessions"] = r.records_upserted
    if r.errors:
        for err in r.errors:
            logger.warning("sessions error: %s", err)

    # Rate limits (optional)
    if config.get("features", {}).get("ccost_installed"):
        rate_data = collect_rate_limits(ccost_path=config.get("features", {}).get("ccost_path"))
        if rate_data:
            r = sync_rate_limits(rate_data, machine_id, client)
            results["rate_limits"] = r.records_upserted

    # Stats extra
    claude_dir = Path(config.get("claude_data_dir", str(Path.home() / ".claude")))
    stats = read_stats_cache(claude_dir)
    if stats:
        r = sync_stats_extra(stats, machine_id, client)
        results["stats_extra"] = r.records_upserted

    return results


def run_daemon(interval_minutes: int = 15, verbose: bool = False) -> None:
    """Main daemon loop with exponential backoff on failures."""
    _setup_logging(verbose)

    config = load_config()
    machine_name = config.get("machine_name", "unknown")
    logger.info(
        "Daemon starting: machine=%s interval=%dm",
        machine_name, interval_minutes,
    )

    shutdown_requested = False

    def _handle_signal(signum: int, _frame: Any) -> None:
        nonlocal shutdown_requested
        sig_name = signal.Signals(signum).name
        logger.info("Received %s, shutting down gracefully...", sig_name)
        shutdown_requested = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    consecutive_failures = 0
    max_backoff = 3600  # 1 hour max

    while not shutdown_requested:
        try:
            # Reload config each cycle (picks up changes)
            config = load_config()
            logger.info("Starting sync cycle...")

            results = _run_sync_cycle(config)

            total = sum(results.values())
            logger.info(
                "Sync complete: %d records (%s)",
                total,
                ", ".join(f"{k}={v}" for k, v in results.items()),
            )
            consecutive_failures = 0

        except Exception as e:
            consecutive_failures += 1
            backoff = min(
                interval_minutes * 60 * (2 ** (consecutive_failures - 1)),
                max_backoff,
            )
            logger.error(
                "Sync failed (attempt %d): %s. Retrying in %ds",
                consecutive_failures, e, backoff,
            )
            _sleep_interruptible(backoff, lambda: shutdown_requested)
            continue

        # Sleep until next cycle
        sleep_seconds = interval_minutes * 60
        logger.debug("Next sync in %dm", interval_minutes)
        _sleep_interruptible(sleep_seconds, lambda: shutdown_requested)

    logger.info("Daemon stopped.")


def _sleep_interruptible(seconds: float, should_stop: Any) -> None:
    """Sleep in 1-second increments to allow graceful shutdown."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if should_stop():
            break
        time.sleep(min(1.0, end - time.monotonic()))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("interval", type=int, nargs="?", default=15)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    run_daemon(interval_minutes=args.interval, verbose=args.verbose)
