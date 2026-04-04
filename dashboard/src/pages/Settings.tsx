import { useState, useEffect, useCallback } from "react";
import { fetchMachines, deleteMachine, downloadExport } from "../lib/api";
import { getStatusDisplay } from "../lib/machineStatus";
import { ConfirmDeleteModal } from "../components/ConfirmDeleteModal";

interface Machine {
  id: string;
  name: string;
  os: string | null;
  hostname: string | null;
  last_sync_at: string | null;
  is_active: boolean;
  created_at: string;
}

export function Settings() {
  const [machines, setMachines] = useState<Machine[]>([]);
  const [loading, setLoading] = useState(true);
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null);
  const [dailyThreshold, setDailyThreshold] = useState(() =>
    localStorage.getItem("alert_daily_threshold") || "20",
  );
  const [weeklyThreshold, setWeeklyThreshold] = useState(() =>
    localStorage.getItem("alert_weekly_threshold") || "100",
  );

  const loadMachines = useCallback(() => {
    setLoading(true);
    fetchMachines(false)
      .then((data) => setMachines(data as Machine[]))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadMachines();
  }, [loadMachines]);

  const handleDelete = useCallback(async () => {
    if (!deleteTarget) return;
    try {
      await deleteMachine(deleteTarget.id);
      setDeleteTarget(null);
      loadMachines();
    } catch {
      // Error handled by api.ts
    }
  }, [deleteTarget, loadMachines]);

  const [allowedEmails, setAllowedEmails] = useState<string[]>([]);

  useEffect(() => {
    fetch("/api/config", {
      headers: { Authorization: `Bearer ${localStorage.getItem("claude_tracker_token") || ""}` },
    })
      .then((r) => r.json())
      .then((data: { allowed_emails: string[] }) => setAllowedEmails(data.allowed_emails))
      .catch(() => {});
  }, []);

  const saveThresholds = () => {
    localStorage.setItem("alert_daily_threshold", dailyThreshold);
    localStorage.setItem("alert_weekly_threshold", weeklyThreshold);
  };

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <h2 className="text-xl font-semibold">Settings</h2>

      {/* Machines list */}
      <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
        <h3 className="mb-3 text-sm font-medium">Registered Machines</h3>
        {loading ? (
          <p className="text-xs text-slate-500">Loading...</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-white/[0.06] text-slate-500">
                  <th className="pb-2 text-left font-medium">Name</th>
                  <th className="pb-2 text-left font-medium">OS</th>
                  <th className="pb-2 text-left font-medium">Hostname</th>
                  <th className="pb-2 text-left font-medium">Last Sync</th>
                  <th className="pb-2 text-left font-medium">Status</th>
                  <th className="pb-2 text-right font-medium"></th>
                </tr>
              </thead>
              <tbody>
                {machines.map((m) => {
                  const badge = getStatusDisplay(m.last_sync_at);
                  return (
                    <tr
                      key={m.id}
                      className="border-b border-white/[0.03] hover:bg-white/[0.02]"
                    >
                      <td className="py-2 font-medium">{m.name}</td>
                      <td className="py-2 text-slate-400">{m.os || "—"}</td>
                      <td className="py-2 font-mono text-slate-400">
                        {m.hostname || "—"}
                      </td>
                      <td className="py-2 font-mono text-slate-400">
                        {m.last_sync_at?.slice(0, 16).replace("T", " ") || "never"}
                      </td>
                      <td className="py-2">
                        <div className="flex items-center gap-1.5">
                          <span className={`inline-flex h-2 w-2 rounded-full ${badge.color}`} />
                          <span className="text-slate-500">{badge.label}</span>
                        </div>
                      </td>
                      <td className="py-2 text-right">
                        <button
                          onClick={() => setDeleteTarget({ id: m.id, name: m.name })}
                          className="rounded px-2 py-1 text-[10px] font-medium text-rose-400 hover:bg-rose-500/10"
                        >
                          Delete
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Authorized emails */}
      <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
        <h3 className="mb-3 text-sm font-medium">Authorized Emails</h3>
        {allowedEmails.length > 0 ? (
          <ul className="space-y-1">
            {allowedEmails.map((email, i) => (
              <li key={i} className="text-xs font-mono text-slate-300">{email}</li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-slate-500">No email restrictions configured (all emails allowed).</p>
        )}
        <p className="mt-3 text-[10px] text-slate-600">
          To add or remove emails, update the ALLOWED_EMAILS secret in Cloudflare:{" "}
          <code className="text-slate-400">npx wrangler pages secret put ALLOWED_EMAILS</code>
        </p>
      </div>

      {/* Alert thresholds */}
      <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
        <h3 className="mb-3 text-sm font-medium">Alert Thresholds</h3>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs text-slate-400 mb-1">
              Daily cost alert ($)
            </label>
            <input
              type="number"
              value={dailyThreshold}
              onChange={(e) => setDailyThreshold(e.target.value)}
              className="w-full rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-1.5 text-sm font-mono outline-none focus:border-sky-500/50"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1">
              Weekly cost alert ($)
            </label>
            <input
              type="number"
              value={weeklyThreshold}
              onChange={(e) => setWeeklyThreshold(e.target.value)}
              className="w-full rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-1.5 text-sm font-mono outline-none focus:border-sky-500/50"
            />
          </div>
        </div>
        <button
          onClick={saveThresholds}
          className="mt-3 rounded-lg bg-sky-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-sky-600"
        >
          Save Thresholds
        </button>
      </div>

      {/* Export */}
      <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
        <h3 className="mb-3 text-sm font-medium">Export Data</h3>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => downloadExport("daily", "csv")}
            className="rounded-lg border border-white/[0.06] px-3 py-1.5 text-xs text-slate-300 hover:bg-white/[0.04]"
          >
            Export Daily (CSV)
          </button>
          <button
            onClick={() => downloadExport("sessions", "csv")}
            className="rounded-lg border border-white/[0.06] px-3 py-1.5 text-xs text-slate-300 hover:bg-white/[0.04]"
          >
            Export Sessions (CSV)
          </button>
          <button
            onClick={() => downloadExport("daily", "json")}
            className="rounded-lg border border-white/[0.06] px-3 py-1.5 text-xs text-slate-300 hover:bg-white/[0.04]"
          >
            Export JSON
          </button>
        </div>
      </div>

      {/* About */}
      <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
        <h3 className="mb-2 text-sm font-medium">About</h3>
        <p className="text-xs text-slate-400">
          Claude Usage Tracker v0.1.0
        </p>
        <p className="mt-1 text-xs text-slate-500">
          Open-source centralized token usage tracking for Claude Code.
        </p>
      </div>

      <ConfirmDeleteModal
        machineName={deleteTarget?.name || ""}
        isOpen={!!deleteTarget}
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
