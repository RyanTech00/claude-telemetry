import { useEffect, useMemo, useState } from "react";
import { fetchEffortBreakdown, type EffortBreakdownRow } from "../../lib/api";
import { useMachineFilter } from "../../hooks/useMachineFilter";

const EFFORT_ORDER = ["low", "medium", "high", "xhigh", "max", "unknown"];
const EFFORT_COLORS: Record<string, string> = {
  low: "#34d399",
  medium: "#38bdf8",
  high: "#fbbf24",
  xhigh: "#fb923c",
  max: "#f43f5e",
  unknown: "#64748b",
};

type Metric = "total" | "output";

const effortRank = (e: string) => {
  const i = EFFORT_ORDER.indexOf(e);
  return i === -1 ? EFFORT_ORDER.length : i;
};
const effortColor = (e: string) => EFFORT_COLORS[e] ?? "#a78bfa";
const shortModel = (m: string) => m.replace(/^claude-/, "");

function fmtTokens(n: number): string {
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return String(n);
}

function StackedBar({ parts, total }: { parts: [string, number][]; total: number }) {
  return (
    <div className="flex h-3 w-full overflow-hidden rounded-full bg-white/[0.04]">
      {parts.map(([effort, v]) => (
        <div
          key={effort}
          style={{ width: `${(v / total) * 100}%`, backgroundColor: effortColor(effort) }}
          title={`${effort}: ${((v / total) * 100).toFixed(1)}%`}
        />
      ))}
    </div>
  );
}

export function EffortBreakdown({ dateRange }: { dateRange: { start: string; end: string } }) {
  const { machineId, machines } = useMachineFilter();
  const [rows, setRows] = useState<EffortBreakdownRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [metric, setMetric] = useState<Metric>("total");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchEffortBreakdown(dateRange.start, dateRange.end, machineId)
      .then((data) => { if (!cancelled) setRows(data); })
      .catch((e: Error) => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [dateRange.start, dateRange.end, machineId]);

  const { total, byEffort, byModelEffort, byMachine } = useMemo(() => {
    const value = (r: EffortBreakdownRow) =>
      Number(metric === "output" ? r.output_tokens : r.total_tokens);
    let total = 0;
    const byEffort = new Map<string, number>();
    const byModelEffort = new Map<string, { model: string; effort: string; messages: number; input: number; output: number; value: number }>();
    const byMachine = new Map<string, Map<string, number>>();
    for (const r of rows) {
      const v = value(r);
      total += v;
      byEffort.set(r.effort, (byEffort.get(r.effort) ?? 0) + v);

      const k = `${r.model}\u0000${r.effort}`;
      const me = byModelEffort.get(k) ?? { model: r.model, effort: r.effort, messages: 0, input: 0, output: 0, value: 0 };
      me.messages += Number(r.messages);
      me.input += Number(r.input_tokens) + Number(r.cache_creation_tokens);
      me.output += Number(r.output_tokens);
      me.value += v;
      byModelEffort.set(k, me);

      const m = byMachine.get(r.machine_id) ?? new Map<string, number>();
      m.set(r.effort, (m.get(r.effort) ?? 0) + v);
      byMachine.set(r.machine_id, m);
    }
    return { total, byEffort, byModelEffort, byMachine };
  }, [rows, metric]);

  const sortedEfforts = (m: Map<string, number>): [string, number][] =>
    [...m.entries()].sort((a, b) => effortRank(a[0]) - effortRank(b[0]));
  const machineName = (id: string) => machines.find((m) => m.id === id)?.name ?? id.slice(0, 8);

  return (
    <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-sm font-medium">Reasoning Effort</h3>
        <div className="flex overflow-hidden rounded-lg border border-white/[0.08] text-xs">
          {(["total", "output"] as Metric[]).map((m) => (
            <button
              key={m}
              onClick={() => setMetric(m)}
              className={`px-3 py-1 ${metric === m ? "bg-white/[0.08] text-slate-100" : "text-slate-400 hover:text-slate-200"}`}
            >
              {m === "total" ? "All tokens" : "Output tokens"}
            </button>
          ))}
        </div>
      </div>

      {loading && <p className="text-xs text-slate-500">Loading...</p>}
      {error && <p className="text-xs text-rose-400">{error}</p>}
      {!loading && !error && total === 0 && (
        <p className="text-xs text-slate-500">
          No effort data for this period. Update the agent and run <code>cc-telemetry sync</code>.
        </p>
      )}

      {!loading && !error && total > 0 && (
        <div className="space-y-6">
          {/* Overall effort mix */}
          <div>
            <StackedBar parts={sortedEfforts(byEffort)} total={total} />
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400">
              {sortedEfforts(byEffort).map(([e, v]) => (
                <span key={e} className="flex items-center gap-1.5">
                  <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: effortColor(e) }} />
                  {e} <span className="font-mono text-slate-200">{((v / total) * 100).toFixed(1)}%</span>
                  <span className="text-slate-500">· {fmtTokens(v)}</span>
                </span>
              ))}
            </div>
          </div>

          {/* Per machine (only when not filtered to a single machine) */}
          {!machineId && byMachine.size > 1 && (
            <div className="space-y-2">
              <p className="text-xs font-medium text-slate-400">By machine</p>
              {[...byMachine.entries()]
                .map(([id, m]) => [id, m, [...m.values()].reduce((a, b) => a + b, 0)] as const)
                .sort((a, b) => b[2] - a[2])
                .map(([id, m, t]) => (
                  <div key={id} className="grid grid-cols-[140px_1fr_80px] items-center gap-3 text-xs">
                    <span className="truncate text-slate-300">{machineName(id)}</span>
                    <StackedBar parts={sortedEfforts(m)} total={t} />
                    <span className="text-right font-mono text-slate-400">{fmtTokens(t)}</span>
                  </div>
                ))}
            </div>
          )}

          {/* Model x effort table */}
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-white/[0.06] text-slate-500">
                  <th className="py-2 text-left font-medium">Model</th>
                  <th className="py-2 text-left font-medium">Effort</th>
                  <th className="py-2 text-right font-medium">Responses</th>
                  <th className="py-2 text-right font-medium">Input</th>
                  <th className="py-2 text-right font-medium">Output</th>
                  <th className="py-2 pl-4 text-left font-medium">Share</th>
                </tr>
              </thead>
              <tbody>
                {[...byModelEffort.values()]
                  .sort((a, b) => b.value - a.value)
                  .map((r) => {
                    const pct = (r.value / total) * 100;
                    return (
                      <tr key={`${r.model}-${r.effort}`} className="border-b border-white/[0.03]">
                        <td className="py-1.5 text-slate-300">{shortModel(r.model)}</td>
                        <td className="py-1.5">
                          <span className="flex items-center gap-1.5 text-slate-300">
                            <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: effortColor(r.effort) }} />
                            {r.effort}
                          </span>
                        </td>
                        <td className="py-1.5 text-right font-mono text-slate-400">{r.messages.toLocaleString()}</td>
                        <td className="py-1.5 text-right font-mono text-slate-400">{fmtTokens(r.input)}</td>
                        <td className="py-1.5 text-right font-mono text-slate-400">{fmtTokens(r.output)}</td>
                        <td className="py-1.5 pl-4">
                          <div className="flex items-center gap-2">
                            <div className="h-1.5 w-24 overflow-hidden rounded-full bg-white/[0.04]">
                              <div className="h-full" style={{ width: `${pct}%`, backgroundColor: effortColor(r.effort) }} />
                            </div>
                            <span className="font-mono text-slate-300">{pct.toFixed(1)}%</span>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
