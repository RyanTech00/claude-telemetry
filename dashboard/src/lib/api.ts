import { TOKEN_KEY } from "./constants";

const API_BASE = "/api";

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
    // Token expired — clear and redirect to login
    localStorage.removeItem(TOKEN_KEY);
    window.location.hash = "";
    window.location.reload();
    throw new Error("Session expired");
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
    localStorage.removeItem(TOKEN_KEY);
    window.location.hash = "";
    window.location.reload();
    throw new Error("Session expired");
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
    localStorage.removeItem(TOKEN_KEY);
    window.location.hash = "";
    window.location.reload();
    throw new Error("Session expired");
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API error ${res.status}: ${text}`);
  }
  return res.json();
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
