<div align="center">

# claude-telemetry

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

![Dashboard Overview](docs/screenshot-overview.png)

## Features

- Multi-PC aggregation with per-machine tracking
- Auto-sync daemon (Elastic/Wazuh style agent)
- Dark-mode dashboard with interactive charts (Recharts)
- Rate limit insights and cost optimization recommendations
- Model mix analysis (Opus/Sonnet/Haiku breakdown)
- Supabase Auth (magic link login)
- Cloudflare Workers proxy (zero exposed keys in frontend)
- Deploy page with copy-paste agent install commands
- Export data as CSV/JSON
- Uses existing tools (ccusage) — no custom JSONL parsing

## Quick Start

### Step 1 — Supabase (free tier)

1. Create account at [supabase.com](https://supabase.com)
2. New Project — choose name and region
3. SQL Editor — paste contents of [`supabase/migrations/001_initial_schema.sql`](supabase/migrations/001_initial_schema.sql) — Run
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
| **Overview** | Total cost, daily chart, model pie, machine cards |
| **Daily** | Stacked area chart, top 10 days, hour heatmap |
| **Projects** | Cost by project, pie distribution, full table |
| **Models** | Opus/Sonnet/Haiku breakdown, mix over time, savings alert |
| **Machines** | Per-machine cards, comparison chart, status badges |
| **Deploy** | Generate agent install commands with one-click copy |
| **Sessions** | Paginated table with sorting and filters |
| **Insights** | Rate projections, optimization tips, trend analysis |
| **Settings** | Machine management, export, alert thresholds |

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
| `claude-tracker uninstall` | Remove agent config from this machine |

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

## License

MIT — see [LICENSE](LICENSE)

## Author

Ryan Barbosa — ryan@ryanbarbosa.com
