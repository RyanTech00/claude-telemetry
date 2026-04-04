"""CLI interface for Claude Usage Tracker."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import click

from . import __version__
from .config import (
    CONFIG_DIR,
    CONFIG_FILE,
    DEFAULT_CONFIG,
    detect_claude_data_dir,
    detect_os,
    generate_api_key,
    generate_machine_id,
    load_config,
    save_config,
)
from .collector import collect_daily_usage, collect_session_usage, collect_rate_limits
from .extras import read_stats_cache, read_history_index


@click.group()
@click.version_option(version=__version__)
def main() -> None:
    """Claude Usage Tracker — centralized token usage tracking for Claude Code."""
    pass


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------


@main.command()
@click.option("--non-interactive", is_flag=True, help="Skip prompts, use flags")
@click.option("--name", "machine_name", default=None, help="Machine name")
@click.option("--supabase-url", default=None, help="Supabase project URL")
@click.option("--supabase-key", default=None, help="Supabase service_role key")
@click.option("--machine-id", default=None, help="Pre-generated machine UUID")
@click.option("--api-key", default=None, help="Pre-generated API key")
def setup(
    non_interactive: bool,
    machine_name: str | None,
    supabase_url: str | None,
    supabase_key: str | None,
    machine_id: str | None,
    api_key: str | None,
) -> None:
    """Configure machine, Supabase connection, and verify dependencies."""

    click.echo("=== Claude Usage Tracker — Setup ===\n")

    # Check Node.js / npx
    if not shutil.which("npx"):
        click.echo("ERROR: npx not found. Install Node.js 18+ first.")
        click.echo("  Windows: winget install OpenJS.NodeJS")
        click.echo("  macOS:   brew install node")
        click.echo("  Linux:   https://nodejs.org/")
        raise SystemExit(1)

    node_ver = subprocess.run(
        ["node", "--version"], capture_output=True, text=True
    ).stdout.strip()
    click.echo(f"  Node.js: {node_ver}")

    # Check ccost: venv first, then PATH
    try:
        from .collector import _find_ccost
        ccost_path = _find_ccost()
        ccost_ver = subprocess.run(
            [ccost_path, "--version"], capture_output=True, text=True
        ).stdout.strip()
        ccost_installed = True
        click.echo(f"  ccost:   {ccost_ver or 'installed'} (rate limit tracking enabled)")
    except (FileNotFoundError, Exception):
        ccost_installed = False
        ccost_path = None
        click.echo("  ccost:   not found (rate limit tracking disabled)")
        click.echo("           Install from https://github.com/toolsu/ccost")

    claude_dir = detect_claude_data_dir()
    click.echo(f"  Claude dir: {claude_dir} ({'exists' if claude_dir.exists() else 'NOT FOUND'})")
    click.echo()

    # Load existing or create new config
    if CONFIG_FILE.exists() and not non_interactive:
        config = json.loads(CONFIG_FILE.read_text())
        click.echo(f"Existing config found. Machine ID: {config.get('machine_id')}")
        if not click.confirm("Overwrite existing config?", default=False):
            click.echo("Setup cancelled.")
            return
    config = DEFAULT_CONFIG.copy()
    config["last_sync"] = DEFAULT_CONFIG["last_sync"].copy()
    config["features"] = DEFAULT_CONFIG["features"].copy()

    if non_interactive:
        if not machine_name or not supabase_url or not supabase_key:
            click.echo("ERROR: --name, --supabase-url, --supabase-key are required in non-interactive mode.")
            raise SystemExit(1)
        config["machine_name"] = machine_name
        config["supabase_url"] = supabase_url
        config["supabase_service_key"] = supabase_key
        config["machine_id"] = machine_id or generate_machine_id()
        config["api_key"] = api_key or generate_api_key()
    else:
        default_name = platform.node()
        config["machine_name"] = click.prompt("Machine name", default=default_name)
        config["supabase_url"] = click.prompt("Supabase URL (https://xxxxx.supabase.co)")
        config["supabase_service_key"] = click.prompt("Supabase service_role key")
        config["machine_id"] = generate_machine_id()
        config["api_key"] = generate_api_key()

    config["claude_data_dir"] = str(claude_dir)
    config["features"]["ccost_installed"] = ccost_installed
    config["features"]["ccost_path"] = ccost_path if ccost_installed else None

    save_config(config)
    click.echo(f"\nConfig saved to {CONFIG_FILE}")

    # Register machine in Supabase
    try:
        from supabase import create_client

        client = create_client(config["supabase_url"], config["supabase_service_key"])
        client.table("machines").upsert({
            "id": config["machine_id"],
            "name": config["machine_name"],
            "api_key": config["api_key"],
            "os": detect_os(),
            "hostname": platform.node(),
        }, on_conflict="id").execute()
        click.echo(f"Machine registered in Supabase: {config['machine_name']}")
    except Exception as e:
        click.echo(f"WARNING: Could not register machine in Supabase: {e}")
        click.echo("You can retry with 'claude-tracker sync' after fixing the connection.")

    click.echo(f"\nMachine ID: {config['machine_id']}")
    click.echo(f"API Key:    {config['api_key']}")
    click.echo("\nSetup complete! Run 'claude-tracker sync' to start syncing.")


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------


@main.command()
@click.option("--verbose", "-v", is_flag=True, help="Show detailed output")
@click.option("--daily-only", is_flag=True, help="Only sync daily usage data")
@click.option("--force", is_flag=True, help="Resend all data (ignore last_sync)")
def sync(verbose: bool, daily_only: bool, force: bool) -> None:
    """Collect data from ccusage and sync to Supabase."""
    from supabase import create_client
    from .sync import sync_daily_usage, sync_sessions, sync_rate_limits, sync_stats_extra

    config = load_config()
    machine_id = config["machine_id"]
    client = create_client(config["supabase_url"], config["supabase_service_key"])

    click.echo(f"Syncing machine: {config['machine_name']} ({machine_id[:8]}...)")

    # Daily usage
    click.echo("\n  Collecting daily usage...", nl=False)
    since = None
    if not force:
        last = config.get("last_sync", {}).get("daily_usage")
        if last:
            since = last[:10].replace("-", "")
    daily = collect_daily_usage(since=since)
    click.echo(f" {len(daily)} records")
    if verbose:
        for d in daily[:5]:
            click.echo(f"    {d.date} | {d.project} | {d.model} | ${d.cost_usd:.4f}")
        if len(daily) > 5:
            click.echo(f"    ... and {len(daily) - 5} more")

    result = sync_daily_usage(daily, machine_id, client, force=force)
    click.echo(f"  Upserted: {result.records_upserted} ({result.duration_ms}ms)")
    if result.errors:
        for err in result.errors:
            click.echo(f"  ERROR: {err}", err=True)

    if daily_only:
        click.echo("\nDone (daily-only mode).")
        return

    # Sessions
    click.echo("\n  Collecting sessions...", nl=False)
    sessions = collect_session_usage()
    click.echo(f" {len(sessions)} sessions")
    if verbose:
        for s in sessions[:5]:
            click.echo(f"    {s.session_id[:40]} | {s.project} | ${s.cost_usd:.4f}")

    result = sync_sessions(sessions, machine_id, client, force=force)
    click.echo(f"  Upserted: {result.records_upserted} ({result.duration_ms}ms)")
    if result.errors:
        for err in result.errors:
            click.echo(f"  ERROR: {err}", err=True)

    # Rate limits (optional)
    if config.get("features", {}).get("ccost_installed"):
        click.echo("\n  Collecting rate limits...", nl=False)
        rate_data = collect_rate_limits(ccost_path=config.get("features", {}).get("ccost_path"))
        if rate_data:
            click.echo(f" {len(rate_data)} records")
            result = sync_rate_limits(rate_data, machine_id, client)
            click.echo(f"  Upserted: {result.records_upserted} ({result.duration_ms}ms)")
        else:
            click.echo(" skipped (ccost unavailable)")

    # Stats extra
    click.echo("\n  Reading stats cache...", nl=False)
    claude_dir = Path(config.get("claude_data_dir", str(Path.home() / ".claude")))
    stats = read_stats_cache(claude_dir)
    if stats:
        click.echo(" found")
        result = sync_stats_extra(stats, machine_id, client)
        click.echo(f"  Upserted: {result.records_upserted} ({result.duration_ms}ms)")
    else:
        click.echo(" not found")

    click.echo("\nSync complete!")


# ---------------------------------------------------------------------------
# daemon
# ---------------------------------------------------------------------------


@main.command()
@click.option("--interval", default=15, help="Sync interval in minutes (default: 15)")
@click.option("--verbose", "-v", is_flag=True, help="Verbose logging")
@click.option("--background", is_flag=True, help="Run detached in background")
def daemon(interval: int, verbose: bool, background: bool) -> None:
    """Run auto-sync daemon (like Elastic Agent)."""
    if background:
        _start_background_daemon(interval, verbose)
        return

    from .daemon import run_daemon
    run_daemon(interval_minutes=interval, verbose=verbose)


def _start_background_daemon(interval: int, verbose: bool) -> None:
    """Start daemon as a detached background process."""
    args = [sys.executable, "-m", "claude_tracker.daemon", str(interval)]
    if verbose:
        args.append("--verbose")

    if sys.platform == "win32":
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        DETACHED_PROCESS = 0x00000008
        subprocess.Popen(
            args,
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        subprocess.Popen(
            args,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    click.echo(f"Daemon started in background (interval: {interval}m)")
    click.echo(f"Log: {CONFIG_DIR / 'daemon.log'}")


# ---------------------------------------------------------------------------
# install-service / uninstall-service / service-status
# ---------------------------------------------------------------------------


@main.command("install-service")
def install_service() -> None:
    """Install daemon as a system service (Task Scheduler / systemd / launchd)."""
    system = platform.system()
    tracker_path = shutil.which("claude-tracker") or f"{sys.executable} -m claude_tracker.cli"

    if system == "Windows":
        _install_windows_service(tracker_path)
    elif system == "Darwin":
        _install_macos_service(tracker_path)
    else:
        _install_linux_service(tracker_path)


@main.command("uninstall-service")
def uninstall_service() -> None:
    """Remove the daemon system service."""
    system = platform.system()

    if system == "Windows":
        _uninstall_windows_service()
    elif system == "Darwin":
        _uninstall_macos_service()
    else:
        _uninstall_linux_service()


@main.command()
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
def uninstall(yes: bool) -> None:
    """Remove all claude-tracker config from this machine."""
    if not yes:
        click.confirm(
            "This will remove all claude-tracker config from this machine. "
            "Data in Supabase is NOT affected. Continue?",
            default=False,
            abort=True,
        )

    # Try to remove service first (may not exist)
    system = platform.system()
    try:
        if system == "Windows":
            _uninstall_windows_service()
        elif system == "Darwin":
            _uninstall_macos_service()
        else:
            _uninstall_linux_service()
    except Exception:
        pass  # Service may not be installed

    # Remove config directory
    import shutil as _shutil
    if CONFIG_DIR.exists():
        _shutil.rmtree(CONFIG_DIR)
        click.echo(f"Removed {CONFIG_DIR}")
    else:
        click.echo(f"Config directory not found: {CONFIG_DIR}")

    click.echo(
        "\nAgent removed from this machine.\n"
        "To also delete your data from the server, remove the machine from\n"
        "the dashboard Settings page or delete the Supabase project."
    )


@main.command("service-status")
def service_status() -> None:
    """Show daemon service status."""
    system = platform.system()

    if system == "Windows":
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", "ClaudeUsageTracker", "/FO", "LIST"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            click.echo("Service: INSTALLED (Windows Task Scheduler)")
            click.echo(result.stdout)
        else:
            click.echo("Service: NOT INSTALLED")

    elif system == "Darwin":
        plist = Path.home() / "Library/LaunchAgents/com.claude-tracker.plist"
        if plist.exists():
            result = subprocess.run(
                ["launchctl", "list", "com.claude-tracker"],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                click.echo("Service: RUNNING (launchd)")
                click.echo(result.stdout)
            else:
                click.echo("Service: INSTALLED but NOT RUNNING")
        else:
            click.echo("Service: NOT INSTALLED")

    else:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "claude-tracker"],
            capture_output=True, text=True,
        )
        status = result.stdout.strip()
        click.echo(f"Service: {status.upper()} (systemd)")
        if status == "active":
            subprocess.run(
                ["systemctl", "--user", "status", "claude-tracker", "--no-pager"],
            )

    # Show last sync info
    try:
        config = load_config()
        log_file = CONFIG_DIR / "daemon.log"
        click.echo(f"\nMachine: {config.get('machine_name')}")
        last_sync = config.get("last_sync", {})
        for source, ts in last_sync.items():
            click.echo(f"  {source:20s} {ts or 'never'}")
        if log_file.exists():
            click.echo(f"\nLog file: {log_file}")
    except FileNotFoundError:
        click.echo("\nNot configured. Run 'claude-tracker setup' first.")


# --- Windows Task Scheduler ---

def _install_windows_service(tracker_path: str) -> None:
    cmd_line = f'"{sys.executable}" -m claude_tracker.daemon 15'
    result = subprocess.run(
        [
            "schtasks", "/Create",
            "/TN", "ClaudeUsageTracker",
            "/TR", cmd_line,
            "/SC", "ONLOGON",
            "/RL", "LIMITED",
            "/F",
        ],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        click.echo("Windows Task Scheduler task created: ClaudeUsageTracker")
        click.echo("The daemon will start automatically on login.")
        # Also start it now
        subprocess.run(["schtasks", "/Run", "/TN", "ClaudeUsageTracker"])
        click.echo("Daemon started.")
    else:
        click.echo(f"ERROR: {result.stderr}")


def _uninstall_windows_service() -> None:
    subprocess.run(
        ["schtasks", "/Delete", "/TN", "ClaudeUsageTracker", "/F"],
        capture_output=True, text=True,
    )
    click.echo("Windows Task Scheduler task removed.")


# --- macOS LaunchAgent ---

def _install_macos_service(tracker_path: str) -> None:
    plist_dir = Path.home() / "Library/LaunchAgents"
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist_path = plist_dir / "com.claude-tracker.plist"

    plist_content = textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
          "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>Label</key>
            <string>com.claude-tracker</string>
            <key>ProgramArguments</key>
            <array>
                <string>{sys.executable}</string>
                <string>-m</string>
                <string>claude_tracker.daemon</string>
                <string>15</string>
            </array>
            <key>RunAtLoad</key>
            <true/>
            <key>KeepAlive</key>
            <true/>
            <key>StandardOutPath</key>
            <string>{CONFIG_DIR / 'daemon.log'}</string>
            <key>StandardErrorPath</key>
            <string>{CONFIG_DIR / 'daemon.log'}</string>
        </dict>
        </plist>
    """)
    plist_path.write_text(plist_content)
    subprocess.run(["launchctl", "load", str(plist_path)])
    click.echo(f"LaunchAgent installed: {plist_path}")
    click.echo("Daemon started and will auto-start on login.")


def _uninstall_macos_service() -> None:
    plist_path = Path.home() / "Library/LaunchAgents/com.claude-tracker.plist"
    if plist_path.exists():
        subprocess.run(["launchctl", "unload", str(plist_path)])
        plist_path.unlink()
        click.echo("LaunchAgent removed.")
    else:
        click.echo("LaunchAgent not found.")


# --- Linux systemd ---

def _install_linux_service(tracker_path: str) -> None:
    service_dir = Path.home() / ".config/systemd/user"
    service_dir.mkdir(parents=True, exist_ok=True)
    service_path = service_dir / "claude-tracker.service"

    service_content = textwrap.dedent(f"""\
        [Unit]
        Description=Claude Usage Tracker Daemon
        After=network-online.target

        [Service]
        Type=simple
        ExecStart={sys.executable} -m claude_tracker.daemon 15
        Restart=on-failure
        RestartSec=30

        [Install]
        WantedBy=default.target
    """)
    service_path.write_text(service_content)
    subprocess.run(["systemctl", "--user", "daemon-reload"])
    subprocess.run(["systemctl", "--user", "enable", "--now", "claude-tracker"])
    click.echo(f"systemd service installed: {service_path}")
    click.echo("Daemon started and enabled on login.")


def _uninstall_linux_service() -> None:
    subprocess.run(["systemctl", "--user", "disable", "--now", "claude-tracker"])
    service_path = Path.home() / ".config/systemd/user/claude-tracker.service"
    if service_path.exists():
        service_path.unlink()
        subprocess.run(["systemctl", "--user", "daemon-reload"])
    click.echo("systemd service removed.")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@main.command()
def status() -> None:
    """Show current machine status and sync info."""
    try:
        config = load_config()
    except FileNotFoundError:
        click.echo("Not configured. Run 'claude-tracker setup' first.")
        return

    click.echo(f"Machine:     {config.get('machine_name', 'unknown')}")
    click.echo(f"Machine ID:  {config.get('machine_id', 'N/A')}")
    click.echo(f"Supabase:    {config.get('supabase_url', 'N/A')}")
    click.echo(f"Claude dir:  {config.get('claude_data_dir', 'N/A')}")
    click.echo(f"ccost:       {'yes' if config.get('features', {}).get('ccost_installed') else 'no'}")
    click.echo()

    last_sync = config.get("last_sync", {})
    click.echo("Last sync:")
    for source, ts in last_sync.items():
        click.echo(f"  {source:20s} {ts or 'never'}")


# ---------------------------------------------------------------------------
# local
# ---------------------------------------------------------------------------


@main.command()
@click.option("--daily", is_flag=True, help="Show daily usage data")
@click.option("--sessions", is_flag=True, help="Show session data")
@click.option("--projects", is_flag=True, help="Show project summary")
def local(daily: bool, sessions: bool, projects: bool) -> None:
    """Show local data without sending to Supabase."""
    if not (daily or sessions or projects):
        daily = True

    if daily:
        click.echo("=== Daily Usage (local) ===\n")
        records = collect_daily_usage()
        click.echo(f"{'Date':12s} {'Project':30s} {'Model':25s} {'Tokens':>12s} {'Cost':>10s}")
        click.echo("-" * 93)
        for r in records:
            click.echo(
                f"{r.date:12s} {r.project:30s} {r.model:25s} "
                f"{r.total_tokens:>12,d} ${r.cost_usd:>9.4f}"
            )
        total_cost = sum(r.cost_usd for r in records)
        total_tokens = sum(r.total_tokens for r in records)
        click.echo("-" * 93)
        click.echo(f"{'TOTAL':12s} {'':30s} {'':25s} {total_tokens:>12,d} ${total_cost:>9.4f}")

    if sessions:
        click.echo("\n=== Sessions (local) ===\n")
        records = collect_session_usage()
        click.echo(f"{'Session ID':40s} {'Project':25s} {'Models':20s} {'Cost':>10s}")
        click.echo("-" * 99)
        for s in records:
            models = ", ".join(m.split("-")[-1] for m in s.models) if s.models else "?"
            click.echo(
                f"{s.session_id[:40]:40s} {s.project[:25]:25s} "
                f"{models[:20]:20s} ${s.cost_usd:>9.4f}"
            )

    if projects:
        click.echo("\n=== Project Summary (local) ===\n")
        records = collect_daily_usage()
        project_totals: dict[str, dict] = {}
        for r in records:
            if r.project not in project_totals:
                project_totals[r.project] = {"cost": 0.0, "tokens": 0, "models": set()}
            project_totals[r.project]["cost"] += r.cost_usd
            project_totals[r.project]["tokens"] += r.total_tokens
            project_totals[r.project]["models"].add(r.model)

        click.echo(f"{'Project':35s} {'Tokens':>12s} {'Cost':>10s} {'Models'}")
        click.echo("-" * 90)
        for proj, data in sorted(project_totals.items(), key=lambda x: x[1]["cost"], reverse=True):
            models = ", ".join(m.split("-")[-1] for m in data["models"])
            click.echo(
                f"{proj[:35]:35s} {data['tokens']:>12,d} "
                f"${data['cost']:>9.4f} {models}"
            )


if __name__ == "__main__":
    main()
