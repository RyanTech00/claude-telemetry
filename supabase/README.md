# Supabase Setup

## 1. Create Project

1. Go to [supabase.com](https://supabase.com) and create a free account
2. Click **New Project** — choose a name and region
3. Wait for the project to provision

## 2. Run Migrations

Go to **SQL Editor** in the Supabase Dashboard and run each migration **in order**:

| # | Migration | Description |
|---|---|---|
| 1 | [`001_initial_schema.sql`](migrations/001_initial_schema.sql) | Base tables: machines, daily_usage, sessions, rate_limits, stats_extra, sync_log, RLS policies, RPC functions |
| 2 | [`002_stats_extra_unique.sql`](migrations/002_stats_extra_unique.sql) | Uniqueness constraint on stats_extra |
| 3 | [`003_user_preferences.sql`](migrations/003_user_preferences.sql) | User preferences table (plan, budgets, thresholds) |
| 4 | [`004_blocks.sql`](migrations/004_blocks.sql) | 5-hour block tracking |
| 5 | [`005_notifications.sql`](migrations/005_notifications.sql) | Notification history + notifications JSONB column on user_preferences |
| 6 | [`006_effort_usage.sql`](migrations/006_effort_usage.sql) | Daily usage per reasoning effort level + `get_effort_breakdown` RPC |

> **Important:** Migrations must be applied sequentially — each builds on the previous.

## 3. Configure Authentication

1. Go to **Authentication** > **URL Configuration**
2. Set **Site URL** to your dashboard URL (e.g., `https://your-app.pages.dev`)
3. Add the same URL to **Redirect URLs**

## 4. Copy Keys

1. Go to **Settings** > **API**
2. Copy:
   - **Project URL** (e.g., `https://xxxxx.supabase.co`)
   - **service_role key** (starts with `eyJ...`)

These are used as Cloudflare Pages secrets (`SUPABASE_URL` and `SUPABASE_SERVICE_KEY`).

## Schema Overview

| Table | Source | Description |
|---|---|---|
| `machines` | Agent setup | Registered PCs |
| `daily_usage` | ccusage daily | Per-day, per-project, per-model usage |
| `sessions` | ccusage session | Individual conversation sessions |
| `blocks` | stats-cache.json | 5-hour usage block tracking |
| `rate_limits` | ccost (optional) | Rate limit window data |
| `stats_extra` | stats-cache.json | Hour counts, activity, model usage |
| `sync_log` | Agent sync | Sync history and errors |
| `users` | Supabase Auth | Dashboard users |
| `machine_owners` | Auto | User-machine ownership |
| `user_preferences` | Dashboard | Plan selection, budgets, thresholds, notification settings |
| `notification_history` | Cron worker | Anti-spam tracking for webhook alerts |
