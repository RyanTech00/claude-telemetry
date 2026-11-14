import { TOKEN_KEY } from "./constants";

const API_BASE = "/api";

// Global auth expiry handler — set by AuthContext
let _onAuthExpired: (() => void) | null = null;
export function setOnAuthExpired(fn: () => void) {
  _onAuthExpired = fn;
}

function handleUnauthorized(): never {
  localStorage.removeItem(TOKEN_KEY);
  if (_onAuthExpired) _onAuthExpired();
  throw new Error("Session expired");
}

function getAuthHeaders(): Record<string, string> {
  const token = localStorage.getItem(TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function fetchJson<T>(path: string, params?: Record<string, string | undefined>): Promise<T> {
  const searchParams = new URLSearchParams();
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null) {
        searchParams.set(key, value);
      }
    }
  }
  const query = searchParams.toString();
  const url = query ? `${API_BASE}/${path}?${query}` : `${API_BASE}/${path}`;

  const res = await fetch(url, { headers: getAuthHeaders() });
  if (res.status === 401) {
    handleUnauthorized();
  }
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API error ${res.status}: ${body}`);
  }
  return res.json();
}

async function postJson<T>(path: string, body: Record<string, unknown>): Promise<T> {
  const res = await fetch(`${API_BASE}/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
    body: JSON.stringify(body),
  });
  if (res.status === 401) {
    handleUnauthorized();
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API error ${res.status}: ${text}`);
  }
  return res.json();
}

// --- RPC endpoints ---

export async function fetchUsageSummary(
  startDate: string,
  endDate: string,
  machineId?: string,
) {
  return fetchJson("usage-summary", {
    start_date: startDate,
    end_date: endDate,
    machine_id: machineId,
  });
}

export async function fetchProjectCosts(
  startDate: string,
  endDate: string,
  machineId?: string,
) {
  return fetchJson("project-costs", {
    start_date: startDate,
    end_date: endDate,
    machine_id: machineId,
  });
}

export async function fetchWeeklyEstimate(machineId?: string) {
  return fetchJson("weekly-estimate", {
    machine_id: machineId,
  });
}

export async function fetchMachineSummary(
  startDate?: string,
  endDate?: string,
) {
  return fetchJson("machine-summary", {
    start_date: startDate,
    end_date: endDate,
  });
}

// --- Table endpoints ---

export async function fetchDailyUsage(
  startDate: string,
  endDate: string,
  machineId?: string,
  project?: string,
  model?: string,
) {
  return fetchJson("daily-usage", {
    start_date: startDate,
    end_date: endDate,
    machine_id: machineId,
    project,
    model,
  });
}

export interface PaginatedSessions {
  data: SessionRow[];
  total: number;
  page: number;
  per_page: number;
}

export interface SessionRow {
  id: string;
  machine_id: string;
  session_id: string;
  project: string;
  project_path: string | null;
  models: string[];
  is_subagent: boolean;
  input_tokens: number;
  output_tokens: number;
  cache_creation_tokens: number;
  cache_read_tokens: number;
  total_tokens: number;
  cost_usd: number;
  last_activity_at: string | null;
  created_at: string;
}

export async function fetchSessions(opts?: {
  machineId?: string;
  project?: string;
  model?: string;
  isSubagent?: string;
  page?: number;
  perPage?: number;
  sort?: string;
  order?: string;
}): Promise<PaginatedSessions> {
  return fetchJson("sessions", {
    machine_id: opts?.machineId,
    project: opts?.project,
    model: opts?.model,
    is_subagent: opts?.isSubagent,
    page: opts?.page?.toString(),
    per_page: opts?.perPage?.toString(),
    sort: opts?.sort,
    order: opts?.order,
  });
}

export async function fetchMachines(activeOnly?: boolean) {
  return fetchJson("machines", {
    active_only: activeOnly === false ? "false" : undefined,
  });
}

export async function fetchStatsExtra(machineId?: string) {
  return fetchJson("stats-extra", {
    machine_id: machineId,
  });
}

export async function fetchRateLimits(machineId?: string, limit?: string) {
  return fetchJson("rate-limits", {
    machine_id: machineId,
    limit,
  });
}

// --- Agent deployment ---

export interface AgentConfig {
  machine_id: string;
  api_key: string;
  supabase_url: string;
  service_key: string;
}

export async function generateAgentConfig(
  name: string,
  os: string,
): Promise<AgentConfig> {
  return postJson("generate-agent-config", { name, os });
}

// --- Machine management ---

export async function deleteMachine(
  id: string,
): Promise<{ success: boolean; deleted: string }> {
  const res = await fetch(`${API_BASE}/delete-machine?id=${id}`, {
    method: "DELETE",
    headers: getAuthHeaders(),
  });
  if (res.status === 401) {
    handleUnauthorized();
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API error ${res.status}: ${text}`);
  }
  return res.json();
}

// --- Blocks ---

export interface BlockRow {
  id: number;
  machine_id: string;
  block_start: string;
  block_end: string;
  is_active: boolean;
  is_gap: boolean;
  input_tokens: number;
  output_tokens: number;
  cache_creation_tokens: number;
  cache_read_tokens: number;
  total_tokens: number;
  cost_usd: number;
  models: string[];
  duration_minutes: number;
  entries: number;
}

export async function fetchBlocks(opts?: {
  machineId?: string;
  startDate?: string;
  endDate?: string;
  activeOnly?: boolean;
}): Promise<BlockRow[]> {
  return fetchJson("blocks", {
    machine_id: opts?.machineId,
    start_date: opts?.startDate,
    end_date: opts?.endDate,
    active_only: opts?.activeOnly ? "true" : undefined,
  });
}

// --- Effort ---

export interface EffortBreakdownRow {
  machine_id: string;
  model: string;
  effort: string;
  messages: number;
  input_tokens: number;
  output_tokens: number;
  cache_creation_tokens: number;
  cache_read_tokens: number;
  total_tokens: number;
}

export async function fetchEffortBreakdown(
  startDate: string,
  endDate: string,
  machineId?: string,
): Promise<EffortBreakdownRow[]> {
  return fetchJson("effort-breakdown", {
    start_date: startDate,
    end_date: endDate,
    machine_id: machineId,
  });
}

// --- Preferences ---

export interface NotificationPrefs {
  webhook_url: string | null;
  webhook_enabled: boolean;
  types: {
    project_budget: boolean;
    rate_limit: boolean;
  };
}

export interface UserPreferences {
  user_id: string;
  plan_cost: number | null;
  plan_name: string;
  project_budgets: Record<string, number>;
  alert_thresholds: { daily: number; weekly: number };
  week_start_day: string;
  theme: string;
  notifications: NotificationPrefs;
  updated_at: string;
}

export async function fetchPreferences(): Promise<UserPreferences> {
  return fetchJson("preferences");
}

export async function updatePreferences(
  data: Partial<Omit<UserPreferences, "user_id" | "updated_at">>,
): Promise<UserPreferences> {
  const res = await fetch(`${API_BASE}/preferences`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
    body: JSON.stringify(data),
  });
  if (res.status === 401) handleUnauthorized();
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API error ${res.status}: ${text}`);
  }
  return res.json();
}

// --- Analytics ---

export interface TrendsData {
  direction: "up" | "down" | "stable";
  slope: number;
  avg: number;
  stdev: number;
  first_half_avg: number;
  second_half_avg: number;
  half_change_pct: number;
  days: number;
  forecast: Array<{ day: number; predicted: number }>;
  forecast_total: number;
  forecast_low: number;
  forecast_high: number;
  daily_data: Array<{
    date: string;
    cost: number;
    tokens: number;
    z_score: number;
    is_anomaly: boolean;
  }>;
  error?: string;
}

export interface ComparePeriodsData {
  period_a: { label: string; cost: number; tokens: number };
  period_b: { label: string; cost: number; tokens: number };
  cost_change_pct: number;
  tokens_change_pct: number;
  movers: Array<{ project: string; cost_a: number; cost_b: number; diff: number }>;
}

export async function fetchTrends(days?: number, machineId?: string): Promise<TrendsData> {
  return fetchJson("analytics-trends", {
    days: days?.toString(),
    machine_id: machineId,
  });
}

export async function fetchComparePeriods(
  periodA: string = "last_week",
  periodB: string = "this_week",
  machineId?: string,
): Promise<ComparePeriodsData> {
  return fetchJson("analytics-compare-periods", {
    period_a: periodA,
    period_b: periodB,
    machine_id: machineId,
  });
}

// --- Notifications ---

export async function testWebhook(webhookUrl: string): Promise<boolean> {
  const res = await fetch(webhookUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      embeds: [{
        title: "Claude Telemetry — Test",
        description: "Webhook is configured correctly!",
        color: 5763719,
        footer: { text: "claude-telemetry" },
      }],
    }),
  });
  return res.ok;
}

// --- Exports ---

export async function downloadExport(
  type: "daily" | "sessions",
  format: "csv" | "json",
  params?: Record<string, string | undefined>,
): Promise<void> {
  const endpoint = type === "daily" ? "export-daily" : "export-sessions";
  const searchParams = new URLSearchParams({ format });
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value) searchParams.set(key, value);
    }
  }
  const url = `${API_BASE}/${endpoint}?${searchParams}`;
  const res = await fetch(url, { headers: getAuthHeaders() });
  if (res.status === 401) handleUnauthorized();
  if (!res.ok) {
    throw new Error(`Export failed: ${res.status}`);
  }
  const blob = await res.blob();
  const filename = `${type}_usage.${format}`;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}
