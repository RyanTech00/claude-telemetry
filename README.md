<div align="center">

<img src="docs/logo.svg" alt="Logo" width="95">

# claude-telemetry

<img src="docs/screenshot-overview1.png" alt="Dashboard Overview" width="800">

**Centralized Claude Code usage tracking across multiple PCs**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-yellow.svg)](https://python.org)
[![React 18](https://img.shields.io/badge/React-18-61dafb.svg)](https://react.dev)
[![Cloudflare Pages](https://img.shields.io/badge/Cloudflare-Pages-f38020.svg)](https://pages.cloudflare.com)

</div>

---

## What is this?

CLI tools like [ccusage](https://github.com/ryoppippi/ccusage) and ccost are single-machine. If you use Claude Code across multiple PCs, you have no unified view of your total spending.

**claude-telemetry** solves this with an Elastic/Wazuh-style architecture: a lightweight Python agent on each PC auto-syncs usage data to a central Supabase database, and a React dashboard shows everything aggregated with filters by machine, project, model, and time period.

The agent does **no custom JSONL parsing** — it calls `ccusage` as the parsing/pricing layer and focuses only on multi-PC aggregation and centralized sync.

## Features

- Multi-PC aggregation with per-machine tracking
- Auto-sync daemon (Elastic/Wazuh style agent)
- Dark-mode dashboard with interactive charts (Recharts)
- **5-hour block tracking** with active block card, burn rate, and multi-PC timeline
- **Plan vs API cost comparison** (Pro/Max 5x/Max 20x/Custom)
- **Rate limit progress bars** (5-hour + weekly windows)
- **Usage pace calculator** with trend detection
- **Project budget tracker** with alerts at 90%/100%
- **Weekly usage reports** with daily/weekly toggle
- Cross-machine usage pace comparison
- Model mix analysis (Opus/Sonnet/Haiku breakdown)
- Supabase Auth (magic link login) with email whitelist
- Cloudflare Workers proxy (zero exposed keys in frontend)
- Deploy page with copy-paste agent install commands
- Statusline auto-setup for rate limit tracking
- Export data as CSV/JSON
- Uses existing tools (ccusage) — no custom JSONL parsing

## Quick Start

### Step 1 — Supabase (free tier)

1. Create account at [supabase.com](https://supabase.com)
2. New Project — choose name and region
3. SQL Editor — paste and run each migration in order:
   1. [`supabase/migrations/001_initial_schema.sql`](supabase/migrations/001_initial_schema.sql)
   2. [`supabase/migrations/002_stats_extra_unique.sql`](supabase/migrations/002_stats_extra_unique.sql)
   3. [`supabase/migrations/003_user_preferences.sql`](supabase/migrations/003_user_preferences.sql)
   4. [`supabase/migrations/004_blocks.sql`](supabase/migrations/004_blocks.sql)
4. Authentication > URL Configuration:
   - **Site URL:** `https://your-app.pages.dev`
   - **Redirect URLs:** add same URL
5. Settings > API — copy **Project URL** and **service_role key**

### Step 2 — Dashboard (Cloudflare Pages)

```bash
git clone https://github.com/RyanTech00/claude-telemetry.git
cd claude-telemetry/dashboard
npm install
npx wrangler pages project create claude-telemetry
npx wrangler pages secret put SUPABASE_URL        # paste Project URL
npx wrangler pages secret put SUPABASE_SERVICE_KEY # paste service_role key
npx wrangler pages secret put ALLOWED_EMAILS       # e.g. "you@email.com,friend@email.com"
npm run build
npx wrangler pages deploy dist
```

### Step 3 — Agent (each PC)

```bash
cd claude-telemetry/agent
python3 -m venv venv
source venv/bin/activate  # Windows: .\venv\Scripts\Activate
pip install -e .
claude-tracker setup
claude-tracker sync --verbose
claude-tracker install-service  # auto-sync every 15min
```

## Architecture

![Architecture](docs/architecture.svg)

## Dashboard Pages

| Page | Description |
|---|---|
| **Overview** | Total cost, daily chart, model pie, machine cards, plan savings, rate limits |
| **Daily** | Stacked area chart with daily/weekly toggle, top 10 days, hour heatmap |
| **Blocks** | 5-hour block timeline, active block card, burn rate, multi-PC table |
| **Projects** | Cost by project, pie distribution, budget progress bars, full table |
| **Models** | Opus/Sonnet/Haiku breakdown, mix over time, savings alert |
| **Machines** | Per-machine cards, comparison chart, daily pace, status badges |
| **Deploy** | Generate agent install commands with one-click copy, statusline setup |
| **Sessions** | Paginated table with sorting, filters by machine/project/type |
| **Insights** | Plan value, burn rate, rate limits, budgets, trend analysis, cross-machine |
| **Settings** | Plan selection, project budgets, alert thresholds, machine management, export |

## CLI Reference

| Command | Description |
|---|---|
| `claude-tracker setup` | Configure agent (interactive or `--non-interactive`) |
| `claude-tracker sync` | Manual sync to Supabase |
| `claude-tracker sync --verbose` | Sync with detailed output |
| `claude-tracker sync --force` | Re-sync all data |
| `claude-tracker daemon` | Run auto-sync in foreground |
| `claude-tracker daemon --interval 10` | Custom interval (minutes) |
| `claude-tracker install-service` | Install as system service |
| `claude-tracker uninstall-service` | Remove system service |
| `claude-tracker service-status` | Check daemon status |
| `claude-tracker status` | Show config and last sync |
| `claude-tracker local --daily` | View local data without syncing |
| `claude-tracker setup-statusline` | Configure rate limit tracking |
| `claude-tracker uninstall` | Remove agent config from this machine |

## Security

- **Dashboard access**: Only emails listed in `ALLOWED_EMAILS` can log in. Set via:
  ```bash
  npx wrangler pages secret put ALLOWED_EMAILS
  # value: "you@email.com" or "you@email.com,teammate@email.com"
  ```
- **API proxy**: All Supabase keys are server-side only (Cloudflare Workers). Zero secrets in the browser bundle.
- **Agent auth**: Each machine uses a unique API key stored locally in `~/.claude-tracker/config.json`.
- **RLS**: Row-Level Security ensures each user only sees their own machines and data.

## Uninstall

To completely remove claude-telemetry from all services:

**Step 1 — Remove agent (each PC)**

```bash
# Stop and remove the service
claude-tracker uninstall-service

# Remove config and data
claude-tracker uninstall

# Or manually:
# Windows: rd /s /q %USERPROFILE%\.claude-tracker
# Linux/macOS: rm -rf ~/.claude-tracker

# Remove the package
pip uninstall claude-usage-tracker
# Delete the repo folder
```

**Step 2 — Delete Cloudflare Pages**

```bash
npx wrangler pages project delete claude-telemetry
# Or: Cloudflare Dashboard > Workers & Pages > claude-telemetry > Settings > Delete project
```

**Step 3 — Delete Supabase project**

Supabase Dashboard > Project Settings > General > Delete project.
This permanently deletes all data.

After these 3 steps, nothing remains — no data, no services, no secrets.

## Tech Stack

| Component | Technology | Hosting |
|---|---|---|
| Agent | Python 3.11+, ccusage | Local (each PC) |
| Dashboard | React 18, Vite, TailwindCSS, Recharts | Cloudflare Pages |
| Database | PostgreSQL | Supabase (free tier) |
| Auth | Magic Link | Supabase Auth |
| API Proxy | Pages Functions | Cloudflare Workers |

## Support

If this tool saved you from rate limit blindness, consider buying me a coffee:

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/ryanbarbosa)

Or just star the repo — it helps a lot!

## Star History

<div align="center">
<a href="https://star-history.com/#RyanTech00/claude-telemetry&Date">
  <img src="https://api.star-history.com/svg?repos=RyanTech00/claude-telemetry&type=Date" width="500" alt="Star History">
</a>
</div>

## License

MIT — see [LICENSE](LICENSE)

## Author

Ryan Barbosa — ryan@ryanbarbosa.com
