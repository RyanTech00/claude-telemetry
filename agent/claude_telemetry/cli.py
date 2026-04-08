"""CLI interface for Claude Usage Tracker."""

from __future__ import annotations

import copy
import json
import platform
import shutil
import subprocess
import sys
import textwrap
import time
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
from .collector import collect_daily_usage, collect_session_usage, collect_rate_limits, collect_blocks_usage
from .extras import read_stats_cache, read_history_index


def _migrate_legacy_config() -> None:
    """Migrate from claude_tracker → claude_telemetry naming automatically."""
    legacy_dir = Path.home() / ".claude-tracker"
    new_dir = Path.home() / ".claude-telemetry"

    # 1. Move config directory
    if legacy_dir.exists() and not new_dir.exists():
        import shutil as _shutil
        _shutil.move(str(legacy_dir), str(new_dir))
        click.echo(f"Migrated config: {legacy_dir} → {new_dir}")

    # 2. Update hooks in ~/.claude/settings.json
    settings_path = Path.home() / ".claude" / "settings.json"
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            raw = json.dumps(data)
            if "claude_tracker" in raw:
                updated = raw.replace("claude_tracker", "claude_telemetry")
                settings_path.write_text(
                    json.dumps(json.loads(updated), indent=2), encoding="utf-8"
                )
                click.echo(f"Migrated hooks in {settings_path}")
        except Exception:
            pass

    # 3. Update MCP server in ~/.claude.json
    claude_json = Path.home() / ".claude.json"
    if claude_json.exists():
        try:
            data = json.loads(claude_json.read_text(encoding="utf-8"))
            raw = json.dumps(data)
            if "claude_tracker" in raw:
                updated = raw.replace("claude_tracker", "claude_telemetry")
                claude_json.write_text(
                    json.dumps(json.loads(updated), indent=2), encoding="utf-8"
                )
                click.echo(f"Migrated MCP config in {claude_json}")
        except Exception:
            pass

    # 4. Update hook scripts (.ps1 / .sh) that still reference claude_tracker
    claude_dir = Path.home() / ".claude"
    for script_name in ("hook-session-sync.ps1", "hook-session-sync.sh"):
        script = claude_dir / script_name
        if script.exists():
            try:
                content = script.read_text(encoding="utf-8")
                if "claude_tracker" in content:
                    script.write_text(
                        content.replace("claude_tracker", "claude_telemetry"),
                        encoding="utf-8",
                    )
                    click.echo(f"Migrated hook script: {script}")
            except Exception:
                pass

    # 5. Fix StatusLine: move from hooks.StatusLine to top-level statusLine
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            hooks = data.get("hooks", {})
            if "StatusLine" in hooks:
                # Move to top-level statusLine format
                old = hooks["StatusLine"]
                cmd = old[0].get("command", "") if isinstance(old, list) and old else ""
                if cmd:
                    data["statusLine"] = {"type": "command", "command": cmd, "padding": 0}
                del hooks["StatusLine"]
                if not hooks:
                    del data["hooks"]
                settings_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
                click.echo("Migrated StatusLine from hooks to top-level statusLine")
        except Exception:
            pass

    # 6. Rename MCP server key from "claude-telemetry" → "cc-telemetry" in ~/.claude.json
    if claude_json.exists():
        try:
            data = json.loads(claude_json.read_text(encoding="utf-8"))
            servers = data.get("mcpServers", {})
            if "claude-telemetry" in servers and "cc-telemetry" not in servers:
                servers["cc-telemetry"] = servers.pop("claude-telemetry")
                claude_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
                click.echo(f"Migrated MCP key: claude-telemetry → cc-telemetry")
        except Exception:
            pass


@click.group()
@click.version_option(version=__version__)
def main() -> None:
    """Claude Telemetry — centralized token usage tracking for Claude Code."""
    _migrate_legacy_config()


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------


@main.command()
@click.option("--non-interactive", is_flag=True, help="Skip prompts, use flags")
@click.option("--minimal", is_flag=True, help="Only configure base settings (no hooks/MCP/service)")
@click.option("--name", "machine_name", default=None, help="Machine name")
@click.option("--supabase-url", default=None, help="Supabase project URL")
@click.option("--supabase-key", default=None, help="Supabase service_role key")
@click.option("--machine-id", default=None, help="Pre-generated machine UUID")
@click.option("--api-key", default=None, help="Pre-generated API key")
def setup(
    non_interactive: bool,
    minimal: bool,
    machine_name: str | None,
    supabase_url: str | None,
    supabase_key: str | None,
    machine_id: str | None,
    api_key: str | None,
) -> None:
    """Setup wizard — configure everything in one command.

    Configures Supabase connection, verifies dependencies, sets up
    real-time hooks, MCP server, statusline, and daemon service.
    """
    click.echo("=== Claude Telemetry — Setup Wizard ===\n")

    # --- Step 1: Check Node.js ---
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

    # --- Step 2: Check/install ccusage ---
    if not shutil.which("ccusage") and not shutil.which("npx"):
        pass  # npx will handle it
    ccusage_check = subprocess.run(
        ["npx", "ccusage@latest", "--version"], capture_output=True, text=True, timeout=30,
    )
    if ccusage_check.returncode == 0:
        click.echo(f"  ccusage: {ccusage_check.stdout.strip() or 'available via npx'}")
    else:
        click.echo("  ccusage: available via npx (will download on first use)")

    # --- Step 3: Check/install ccost ---
    try:
        from .collector import _find_ccost
        ccost_path = _find_ccost()
        ccost_ver = subprocess.run(
            [ccost_path, "--version"], capture_output=True, text=True
        ).stdout.strip()
        ccost_installed = True
        click.echo(f"  ccost:   {ccost_ver or 'installed'}")
    except FileNotFoundError:
        ccost_installed = False
        ccost_path = None
        if not non_interactive:
            click.echo("  ccost:   not found")
            if click.confirm("  Install ccost globally? (enables rate limit tracking)", default=True):
                result = subprocess.run(
                    ["npm", "install", "-g", "ccost"], capture_output=True, text=True
                )
                if result.returncode == 0:
                    try:
                        ccost_path = _find_ccost()
                        ccost_installed = True
                        click.echo("  ccost:   installed!")
                    except FileNotFoundError:
                        click.echo("  ccost:   install succeeded but not found in PATH")
                else:
                    click.echo(f"  ccost:   install failed ({result.stderr.strip()[:80]})")
        else:
            click.echo("  ccost:   not found (rate limit tracking disabled)")

    claude_dir = detect_claude_data_dir()
    click.echo(f"  Claude dir: {claude_dir} ({'exists' if claude_dir.exists() else 'NOT FOUND'})")
    click.echo()

    # --- Step 4: Config (Supabase connection + machine) ---
    existing_config: dict | None = None
    if CONFIG_FILE.exists():
        existing_config = json.loads(CONFIG_FILE.read_text())
        existing_id = existing_config.get("machine_id")
        click.echo(f"Existing config found. Machine ID: {existing_id}")
        if not non_interactive:
            if not click.confirm("Update existing config?", default=True):
                click.echo("Setup cancelled.")
                return

    config = copy.deepcopy(DEFAULT_CONFIG)

    # Preserve existing machine_id and api_key when re-running setup
    if existing_config and existing_config.get("machine_id"):
        config["machine_id"] = existing_config["machine_id"]
        config["api_key"] = existing_config.get("api_key") or generate_api_key()
        if existing_config.get("last_sync"):
            config["last_sync"] = existing_config["last_sync"]
        if existing_config.get("features"):
            config["features"] = {**config["features"], **existing_config["features"]}

    if non_interactive:
        if not machine_name or not supabase_url or not supabase_key:
            click.echo("ERROR: --name, --supabase-url, --supabase-key are required in non-interactive mode.")
            raise SystemExit(1)
        config["machine_name"] = machine_name
        config["supabase_url"] = supabase_url
        config["supabase_service_key"] = supabase_key
        if machine_id:
            config["machine_id"] = machine_id
        elif not config.get("machine_id"):
            config["machine_id"] = generate_machine_id()
        if api_key:
            config["api_key"] = api_key
        elif not config.get("api_key"):
            config["api_key"] = generate_api_key()
    else:
        if existing_config:
            default_name = existing_config.get("machine_name", platform.node())
        else:
            default_name = platform.node()
        config["machine_name"] = click.prompt("Machine name", default=default_name)
        config["supabase_url"] = click.prompt(
            "Supabase URL",
            default=existing_config.get("supabase_url") if existing_config else None,
        )
        config["supabase_service_key"] = click.prompt(
            "Supabase service_role key",
            default=existing_config.get("supabase_service_key") if existing_config else None,
        )
        if not config.get("machine_id"):
            config["machine_id"] = generate_machine_id()
        if not config.get("api_key"):
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
        click.echo(f"Machine registered: {config['machine_name']}")
    except Exception as e:
        click.echo(f"WARNING: Could not register machine: {e}")
        click.echo("You can retry with 'cc-telemetry sync' after fixing the connection.")

    # --- Step 5: Full setup (unless --minimal) ---
    auto_configure = not minimal
    if not minimal and not non_interactive:
        click.echo()
        auto_configure = click.confirm("Configure everything automatically? (hooks, MCP, statusline, service)", default=True)

    configured = []

    if auto_configure:
        click.echo()

        # Statusline
        try:
            _setup_statusline_internal()
            configured.append("statusline")
            click.echo("  Statusline configured")
        except Exception as e:
            click.echo(f"  Statusline failed: {e}")

        # Hooks
        try:
            _setup_hooks_internal()
            config = load_config()
            config.setdefault("features", {})
            config["features"]["hooks_configured"] = True
            save_config(config)
            configured.append("hooks")
            click.echo("  Hooks configured (SessionEnd + Stop)")
        except Exception as e:
            click.echo(f"  Hooks failed: {e}")

        # MCP server
        try:
            _setup_mcp_internal()
            configured.append("mcp")
            click.echo("  MCP server registered")
        except Exception as e:
            click.echo(f"  MCP server failed: {e}")

        # Install service
        try:
            system = platform.system()
            tracker_path = shutil.which("cc-telemetry") or f"{sys.executable} -m claude_telemetry.cli"
            if system == "Windows":
                _install_windows_service(tracker_path)
            elif system == "Darwin":
                _install_macos_service(tracker_path)
            else:
                _install_linux_service(tracker_path)
            configured.append("service")
        except Exception as e:
            click.echo(f"  Service install failed: {e}")

    # --- Step 6: Initial sync ---
    if auto_configure:
        click.echo("\n  Running initial sync...")
        try:
            from .daemon import _run_sync_cycle
            config = load_config()
            results = _run_sync_cycle(config)
            total = sum(results.values())
            click.echo(f"  Synced {total} records")
            configured.append("sync")
        except Exception as e:
            click.echo(f"  Initial sync failed: {e}")

    # --- Summary ---
    click.echo(f"\n{'=' * 40}")
    click.echo(f"Machine:  {config['machine_name']}")
    click.echo(f"ID:       {config['machine_id'][:8]}...")
    if configured:
        click.echo(f"Enabled:  {', '.join(configured)}")
    click.echo()
    if auto_configure:
        click.echo("Everything is configured! Run 'cc-telemetry doctor' to verify.")
    else:
        click.echo("Base config saved. Run individual commands to enable more features:")
        click.echo("  cc-telemetry setup-hooks        # real-time sync")
        click.echo("  cc-telemetry setup-mcp          # Claude Code MCP integration")
        click.echo("  cc-telemetry setup-statusline   # rate limit tracking")
        click.echo("  cc-telemetry install-service    # background daemon")


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
    from .sync import sync_daily_usage, sync_sessions, sync_rate_limits, sync_stats_extra, sync_blocks

    config = load_config()
    machine_id = config["machine_id"]
    client = create_client(config["supabase_url"], config["supabase_service_key"])

    click.echo(f"Syncing machine: {config['machine_name']} ({machine_id[:8]}...)")

    # Ensure machine is registered (fixes FK constraint failures)
    try:
        client.table("machines").upsert({
            "id": machine_id,
            "name": config["machine_name"],
            "api_key": config.get("api_key", ""),
            "os": detect_os(),
            "hostname": platform.node(),
        }, on_conflict="id").execute()
    except Exception as e:
        click.echo(f"\n  ERROR: Cannot register machine in Supabase: {e}", err=True)
        click.echo("  Check your supabase_url and supabase_service_key in config.", err=True)
        raise SystemExit(1)

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

    # Blocks
    click.echo("\n  Collecting blocks...", nl=False)
    blocks = collect_blocks_usage()
    click.echo(f" {len(blocks)} blocks")
    if blocks:
        result = sync_blocks(blocks, machine_id, client)
        click.echo(f"  Upserted: {result.records_upserted} ({result.duration_ms}ms)")
        if result.errors:
            for err in result.errors:
                click.echo(f"  ERROR: {err}", err=True)

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


def _get_pythonw() -> str:
    """Get pythonw.exe path on Windows (no console window)."""
    if sys.platform == "win32":
        pythonw = Path(sys.executable).parent / "pythonw.exe"
        if pythonw.exists():
            return str(pythonw)
    return sys.executable


def _start_background_daemon(interval: int, verbose: bool) -> None:
    """Start daemon as a detached background process."""
    exe = _get_pythonw() if sys.platform == "win32" else sys.executable
    args = [exe, "-m", "claude_telemetry.daemon", str(interval)]
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
    tracker_path = shutil.which("cc-telemetry") or f"{sys.executable} -m claude_telemetry.cli"

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
    """Remove all cc-telemetry config from this machine."""
    if not yes:
        click.confirm(
            "This will remove all cc-telemetry config from this machine. "
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
    if CONFIG_DIR.exists():
        shutil.rmtree(CONFIG_DIR)
        click.echo(f"Removed {CONFIG_DIR}")
    else:
        click.echo(f"Config directory not found: {CONFIG_DIR}")

    click.echo(
        "\nAgent removed from this machine.\n"
        "To also delete your data from the server, remove the machine from\n"
        "the dashboard Settings page or delete the Supabase project."
    )


def _setup_statusline_internal() -> None:
    """Internal: configure statusline (no user output)."""
    claude_dir = Path.home() / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    system = platform.system()

    if system == "Windows":
        script_path = claude_dir / "statusline.ps1"
        script_path.write_text(textwrap.dedent("""\
            $input = $Input | Out-String
            $ts = [int](New-TimeSpan -Start (Get-Date '1970-01-01') -End (Get-Date).ToUniversalTime()).TotalSeconds
            $line = '{{"ts":' + $ts + ',"data":' + $input.Trim() + '}}'
            Add-Content -Path "$env:USERPROFILE\\.claude\\statusline.jsonl" -Value $line -Encoding UTF8
        """))
    else:
        script_path = claude_dir / "statusline.sh"
        script_path.write_text(textwrap.dedent("""\
            #!/bin/bash
            input=$(cat)
            echo "{\\"ts\\":$(date +%s),\\"data\\":$input}" >> ~/.claude/statusline.jsonl
        """))
        script_path.chmod(0o755)

    settings_path = claude_dir / "settings.json"
    settings: dict = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text())
        except Exception:
            pass

    # statusLine is a top-level key (NOT inside hooks)
    settings["statusLine"] = {
        "type": "command",
        "command": str(script_path),
        "padding": 0,
    }

    # Clean up legacy wrong location if present
    if "hooks" in settings and "StatusLine" in settings["hooks"]:
        del settings["hooks"]["StatusLine"]
        if not settings["hooks"]:
            del settings["hooks"]

    settings_path.write_text(json.dumps(settings, indent=2))


def _setup_hooks_internal() -> None:
    """Internal: configure hooks (no user output)."""
    claude_dir = Path.home() / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    system = platform.system()

    python_path = sys.executable
    if system == "Windows":
        pythonw = Path(sys.executable).parent / "pythonw.exe"
        if pythonw.exists():
            python_path = str(pythonw)

    if system == "Windows":
        script_path = claude_dir / "hook-session-sync.ps1"
        script_path.write_text(textwrap.dedent(f"""\
            Start-Process -FilePath "{python_path}" -ArgumentList "-m","claude_telemetry.hook_sync" -WindowStyle Hidden
        """))
    else:
        script_path = claude_dir / "hook-session-sync.sh"
        script_path.write_text(textwrap.dedent(f"""\
            #!/bin/bash
            nohup "{python_path}" -m claude_telemetry.hook_sync > /dev/null 2>&1 &
            disown
        """))
        script_path.chmod(0o755)

    settings_path = claude_dir / "settings.json"
    settings: dict = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text())
        except Exception:
            pass
    settings.setdefault("hooks", {})
    hook_entry = {"hooks": [{"type": "command", "command": str(script_path)}]}
    settings["hooks"]["SessionEnd"] = [hook_entry]
    settings["hooks"]["Stop"] = [hook_entry]
    settings_path.write_text(json.dumps(settings, indent=2))


def _setup_mcp_internal() -> None:
    """Internal: register MCP server (no user output)."""
    python_path = sys.executable

    config_path = Path.home() / ".claude.json"
    config_data: dict = {}
    if config_path.exists():
        try:
            config_data = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    config_data.setdefault("mcpServers", {})
    config_data["mcpServers"]["cc-telemetry"] = {
        "command": python_path,
        "args": ["-m", "claude_telemetry.mcp_server"],
    }
    config_path.write_text(json.dumps(config_data, indent=2), encoding="utf-8")


@main.command("setup-statusline")
def setup_statusline() -> None:
    """Configure Claude Code statusline for rate limit tracking."""
    _setup_statusline_internal()
    click.echo("Statusline configured! Rate limit tracking will start on next Claude Code session.")


@main.command("setup-hooks")
def setup_hooks() -> None:
    """Configure Claude Code hooks for real-time data sync on session end."""
    _setup_hooks_internal()
    try:
        config = load_config()
        config.setdefault("features", {})
        config["features"]["hooks_configured"] = True
        save_config(config)
    except FileNotFoundError:
        click.echo("WARNING: Agent not configured yet. Run 'cc-telemetry setup' first.")
    click.echo("Hooks configured! (SessionEnd + Stop)")
    click.echo("The daemon (if running) will switch to a 60-minute backup interval.")


@main.command("hook-status")
def hook_status() -> None:
    """Show hook configuration status and recent sync info."""
    claude_dir = Path.home() / ".claude"
    settings_path = claude_dir / "settings.json"

    # Check if hooks are configured in settings.json
    session_end_ok = False
    stop_ok = False
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text())
            hooks = settings.get("hooks", {})
            for event_name, entries in [("SessionEnd", hooks.get("SessionEnd", [])), ("Stop", hooks.get("Stop", []))]:
                for entry in entries:
                    # Check nested hooks format
                    inner = entry.get("hooks", [entry])
                    for h in inner:
                        if "hook-session-sync" in h.get("command", ""):
                            if event_name == "SessionEnd":
                                session_end_ok = True
                            else:
                                stop_ok = True
        except Exception:
            pass

    click.echo(f"SessionEnd hook:  {'YES' if session_end_ok else 'NO'}")
    click.echo(f"Stop hook:        {'YES' if stop_ok else 'NO'}")

    # Check lock file for last sync time
    lock_file = CONFIG_DIR / ".hook_lock"
    if lock_file.exists():
        import datetime
        mtime = lock_file.stat().st_mtime
        last_sync = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        ago = int(time.time() - mtime)
        if ago < 60:
            ago_str = f"{ago}s ago"
        elif ago < 3600:
            ago_str = f"{ago // 60}m ago"
        else:
            ago_str = f"{ago // 3600}h ago"
        click.echo(f"Last hook sync:   {last_sync} ({ago_str})")
    else:
        click.echo("Last hook sync:   never")

    # Show recent log entries
    log_file = CONFIG_DIR / "logs" / "hooks.log"
    if log_file.exists():
        lines = log_file.read_text().strip().splitlines()
        recent = lines[-5:] if len(lines) > 5 else lines
        click.echo(f"\nRecent log ({log_file}):")
        for line in recent:
            click.echo(f"  {line}")
    else:
        click.echo(f"\nNo hook log yet ({log_file})")


@main.command("setup-mcp")
def setup_mcp() -> None:
    """Register the cc-telemetry MCP server with Claude Code."""
    try:
        load_config()
    except FileNotFoundError:
        click.echo("ERROR: Agent not configured. Run 'cc-telemetry setup' first.")
        raise SystemExit(1)

    _setup_mcp_internal()
    click.echo("MCP server registered: cc-telemetry")
    click.echo("\nYou can now ask Claude Code things like:")
    click.echo('  "How much did I spend this week across all machines?"')
    click.echo('  "What are my top 5 projects by cost?"')
    click.echo('  "Show me the rate limit status"')
    click.echo("\nRestart Claude Code to activate the MCP server.")


@main.command()
def doctor() -> None:
    """Health check — verify all components are configured and working."""
    click.echo("Claude Telemetry — Health Check\n")
    passed = 0
    total = 0

    def _check(label: str, ok: bool, detail: str = "", hint: str = "") -> None:
        nonlocal passed, total
        total += 1
        if ok:
            passed += 1
            mark = click.style("OK", fg="green")
            click.echo(f"  {mark}  {label:<28s} {detail}")
        else:
            mark = click.style("FAIL", fg="red")
            click.echo(f"  {mark}  {label:<28s} {hint}")

    # 1. ccusage (global install OR available via npx)
    ccusage_ok = bool(shutil.which("ccusage")) or bool(shutil.which("npx"))
    _check("ccusage", ccusage_ok,
           "installed" if shutil.which("ccusage") else "available via npx",
           "Install Node.js 18+ (npx required)")

    # 2. ccost
    ccost_ok = False
    try:
        from .collector import _find_ccost
        ccost_path = _find_ccost()
        r = subprocess.run([ccost_path, "--version"], capture_output=True, text=True)
        ccost_ok = r.returncode == 0
        _check("ccost", ccost_ok, r.stdout.strip() or "installed", "Run: npm install -g ccost")
    except FileNotFoundError:
        _check("ccost", False, hint="Run: npm install -g ccost")

    # 3. Config
    config_ok = False
    try:
        config = load_config()
        config_ok = bool(config.get("machine_id") and config.get("supabase_url"))
        name = config.get("machine_name", "?")
        mid = config.get("machine_id", "?")[:8]
        _check("Config valid", config_ok, f"{name} ({mid}...)", "Run: cc-telemetry setup")
    except FileNotFoundError:
        _check("Config valid", False, hint="Run: cc-telemetry setup")
        config = {}

    # 4. Supabase reachable
    if config_ok:
        try:
            from supabase import create_client
            client = create_client(config["supabase_url"], config["supabase_service_key"])
            client.table("machines").select("id").limit(1).execute()
            _check("Supabase reachable", True, "connected")
        except Exception as e:
            _check("Supabase reachable", False, hint=f"Check URL/key: {e}")
    else:
        _check("Supabase reachable", False, hint="Fix config first")

    # 5. Statusline
    settings_path = Path.home() / ".claude" / "settings.json"
    statusline_ok = False
    if settings_path.exists():
        try:
            s = json.loads(settings_path.read_text())
            statusline_ok = "statusLine" in s
        except Exception:
            pass
    _check("Statusline configured", statusline_ok,
           hint="Run: cc-telemetry setup-statusline")

    # 6. Hooks
    hooks_ok = False
    if settings_path.exists():
        try:
            s = json.loads(settings_path.read_text())
            hooks = s.get("hooks", {})
            hooks_ok = "SessionEnd" in hooks and "Stop" in hooks
        except Exception:
            pass
    _check("Hooks configured", hooks_ok,
           "SessionEnd + Stop" if hooks_ok else "",
           "Run: cc-telemetry setup-hooks")

    # 7. MCP server
    mcp_ok = False
    claude_json = Path.home() / ".claude.json"
    if claude_json.exists():
        try:
            d = json.loads(claude_json.read_text(encoding="utf-8"))
            mcp_ok = "cc-telemetry" in d.get("mcpServers", {})
        except Exception:
            pass
    _check("MCP server registered", mcp_ok,
           hint="Run: cc-telemetry setup-mcp")

    # 8. Daemon running
    daemon_ok = False
    system = platform.system()
    if system == "Windows":
        r = subprocess.run(
            ["schtasks", "/Query", "/TN", "ClaudeUsageTracker", "/FO", "LIST"],
            capture_output=True, text=True,
        )
        daemon_ok = r.returncode == 0
    elif system == "Darwin":
        plist = Path.home() / "Library/LaunchAgents/com.cc-telemetry.plist"
        daemon_ok = plist.exists()
    else:
        r = subprocess.run(
            ["systemctl", "--user", "is-active", "cc-telemetry"],
            capture_output=True, text=True,
        )
        daemon_ok = r.stdout.strip() == "active"
    _check("Daemon running", daemon_ok,
           hint="Run: cc-telemetry install-service")

    # 9. Last sync
    sync_ok = False
    if config:
        last_daily = config.get("last_sync", {}).get("daily_usage")
        if last_daily:
            sync_ok = True
            _check("Last sync", True, last_daily[:19].replace("T", " "))
        else:
            _check("Last sync", False, hint="Run: cc-telemetry sync")
    else:
        _check("Last sync", False, hint="Fix config first")

    # 10. Rate limits
    lock_file = CONFIG_DIR / ".hook_lock"
    rl_ok = False
    if lock_file.exists():
        age = time.time() - lock_file.stat().st_mtime
        rl_ok = age < 86400  # active within 24h
    _check("Hook sync active", rl_ok,
           f"{int(age // 60)}m ago" if rl_ok else "",
           "Hooks may not be firing — check logs")

    # Summary
    color = "green" if passed == total else ("yellow" if passed >= total - 2 else "red")
    click.echo(f"\n  {click.style(f'{passed}/{total}', fg=color)} checks passed")


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
        plist = Path.home() / "Library/LaunchAgents/com.cc-telemetry.plist"
        if plist.exists():
            result = subprocess.run(
                ["launchctl", "list", "com.cc-telemetry"],
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
            ["systemctl", "--user", "is-active", "cc-telemetry"],
            capture_output=True, text=True,
        )
        status = result.stdout.strip()
        click.echo(f"Service: {status.upper()} (systemd)")
        if status == "active":
            subprocess.run(
                ["systemctl", "--user", "status", "cc-telemetry", "--no-pager"],
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
        click.echo("\nNot configured. Run 'cc-telemetry setup' first.")


# --- Windows Task Scheduler ---

def _install_windows_service(tracker_path: str) -> None:
    exe = _get_pythonw()
    cmd_line = f'"{exe}" -m claude_telemetry.daemon 15'
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
    plist_path = plist_dir / "com.cc-telemetry.plist"

    plist_content = textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
          "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>Label</key>
            <string>com.cc-telemetry</string>
            <key>ProgramArguments</key>
            <array>
                <string>{sys.executable}</string>
                <string>-m</string>
                <string>claude_telemetry.daemon</string>
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
    plist_path = Path.home() / "Library/LaunchAgents/com.cc-telemetry.plist"
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
    service_path = service_dir / "cc-telemetry.service"

    service_content = textwrap.dedent(f"""\
        [Unit]
        Description=Claude Usage Tracker Daemon
        After=network-online.target

        [Service]
        Type=simple
        ExecStart={sys.executable} -m claude_telemetry.daemon 15
        Restart=on-failure
        RestartSec=30

        [Install]
        WantedBy=default.target
    """)
    service_path.write_text(service_content)
    subprocess.run(["systemctl", "--user", "daemon-reload"])
    subprocess.run(["systemctl", "--user", "enable", "--now", "cc-telemetry"])
    click.echo(f"systemd service installed: {service_path}")
    click.echo("Daemon started and enabled on login.")


def _uninstall_linux_service() -> None:
    subprocess.run(["systemctl", "--user", "disable", "--now", "cc-telemetry"])
    service_path = Path.home() / ".config/systemd/user/cc-telemetry.service"
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
        click.echo("Not configured. Run 'cc-telemetry setup' first.")
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
