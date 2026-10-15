"use client";
// Analytics dashboard, only for the addresses in ANALYTICS_ADMIN_EMAILS on the
// API. The API answers 404 to everyone else, and this page then sends them
// straight back home, so the route never shows a stranger anything.
import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { API } from "../lib/api";

type Daily = {
  day: string; active_users: number; calls: number; fallback: number; failed: number;
  agent_runs: number; signups: number; rate_limited: number;
};
type Stats = {
  window: { days: number; start: string; end: string };
  totals: Record<string, number>;
  users: { active: number; signups: number };
  total_users: number;
  truncated: boolean;
  models: {
    calls: number;
    outcomes: Record<string, number>;
    served_by: Record<string, number>;
    by_hop: Record<string, number>;
    fallback_rate_pct: number | null;
    failed_attempts: { provider: string; kind: string; count: number }[];
    latency_ms: Record<string, { p50: number | null; p95: number | null; n: number }>;
  };
  memory: { saves: Record<string, number>; recalls: number; recall_hit_pct: number | null };
  tools: { calls: Record<string, number>; errors: Record<string, number>; hitl: Record<string, { approved: number; declined: number }> };
  rate_limited: Record<string, number>;
  daily: Daily[];
  accounts: {
    own_chat_key: Record<string, number>;
    own_memory_key: Record<string, number>;
    memory_paused: number;
    auto_approve_users: number;
    linked_gmail: number;
    linked_outlook: number;
    scheduled_emails: number | null;
    tester_requests: number;
    top_users: { name: string; email: string; runs: number; model_calls: number; last_seen: string | null }[];
  };
};

const RANGES = [7, 14, 30, 90];
const PROVIDER_NAMES: Record<string, string> = {
  nvidia: "NVIDIA", groq: "Groq", google_genai: "Gemini", openai: "OpenAI",
  anthropic: "Anthropic", ollama_cloud: "Ollama Cloud", unknown: "Unknown",
};
const label = (p: string) => PROVIDER_NAMES[p] ?? p;
const fmt = (n: number | null | undefined, suffix = "") => (n === null || n === undefined ? "n/a" : `${n.toLocaleString()}${suffix}`);
const secs = (ms: number | null) => (ms === null ? "n/a" : `${(ms / 1000).toFixed(1)}s`);

// Series colors live here as CSS variables so light and dark each get their
// own validated steps (see the dataviz palette): primary, failover, failed.
const VIZ_STYLE = `
.viz { --s-primary:#2a78d6; --s-failover:#eb6834; --s-failed:#e34948; --s-bar:#2a78d6; --grid:#e7e6e2; }
.dark .viz { --s-primary:#3987e5; --s-failover:#d95926; --s-failed:#e66767; --s-bar:#3987e5; --grid:#2f2f2d; }
`;

function Card({ title, children, className = "" }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={`rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4 ${className}`}>
      <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">{title}</h2>
      {children}
    </section>
  );
}

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4">
      <div className="text-xs text-gray-500 dark:text-gray-400">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums text-gray-900 dark:text-gray-100">{value}</div>
      {hint && <div className="mt-1 text-xs text-gray-400 dark:text-gray-500">{hint}</div>}
    </div>
  );
}

// One labelled horizontal bar per row. Rows are named, so a single bar color
// is enough: the label carries identity, the length carries the number.
function BarList({ rows, empty = "Nothing yet" }: { rows: [string, number][]; empty?: string }) {
  const max = Math.max(1, ...rows.map(([, n]) => n));
  const total = rows.reduce((a, [, n]) => a + n, 0);
  if (rows.length === 0) return <p className="text-sm text-gray-400">{empty}</p>;
  return (
    <ul className="space-y-2">
      {rows.map(([name, n]) => (
        <li key={name} title={`${name}: ${n.toLocaleString()} (${total ? Math.round((100 * n) / total) : 0}%)`}>
          <div className="flex justify-between text-xs text-gray-600 dark:text-gray-300 mb-1">
            <span>{name}</span>
            <span className="tabular-nums">
              {n.toLocaleString()} <span className="text-gray-400">({total ? Math.round((100 * n) / total) : 0}%)</span>
            </span>
          </div>
          <div className="h-2 rounded-full bg-gray-100 dark:bg-gray-800">
            <div className="h-2 rounded-full" style={{ width: `${(100 * n) / max}%`, background: "var(--s-bar)" }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

// Daily model calls, stacked: answered by the primary, rescued by a failover
// hop, or failed outright. Hover a day for its exact numbers.
function DailyCalls({ daily }: { daily: Daily[] }) {
  const [hover, setHover] = useState<number | null>(null);
  // PAD_T keeps the top tick label inside the SVG.
  const W = 720, H = 190, PAD_T = 10, PAD_B = 22, PAD_L = 30;
  const max = Math.max(1, ...daily.map((d) => d.calls));
  const slot = (W - PAD_L) / daily.length;
  const barW = Math.max(3, Math.min(28, slot - 4));
  const y = (v: number) => ((H - PAD_B - PAD_T) * v) / max;
  const ticks = [0, Math.ceil(max / 2), max];
  const h = hover === null ? null : daily[hover];

  return (
    <div className="relative">
      <div className="flex gap-4 text-xs text-gray-600 dark:text-gray-300 mb-2">
        {[["Primary", "--s-primary"], ["Failover", "--s-failover"], ["Failed", "--s-failed"]].map(([n, v]) => (
          <span key={n} className="flex items-center gap-1.5">
            <span className="inline-block w-2.5 h-2.5 rounded-sm" style={{ background: `var(${v})` }} />
            {n}
          </span>
        ))}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img" aria-label="Daily model calls by outcome" onMouseLeave={() => setHover(null)}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD_L} x2={W} y1={H - PAD_B - y(t)} y2={H - PAD_B - y(t)} stroke="var(--grid)" strokeWidth={1} />
            <text x={PAD_L - 6} y={H - PAD_B - y(t) + 3} textAnchor="end" className="fill-gray-400" fontSize={10}>{t}</text>
          </g>
        ))}
        {daily.map((d, i) => {
          const x = PAD_L + i * slot + (slot - barW) / 2;
          const primary = d.calls - d.fallback - d.failed;
          // Stack bottom up with a 2px surface gap between segments.
          const segs: [number, string][] = [[primary, "--s-primary"], [d.fallback, "--s-failover"], [d.failed, "--s-failed"]];
          let base = H - PAD_B;
          return (
            <g key={d.day} onMouseEnter={() => setHover(i)}>
              <rect x={PAD_L + i * slot} y={0} width={slot} height={H - PAD_B} fill="transparent" />
              {segs.map(([v, c], j) => {
                if (v <= 0) return null;
                const hgt = Math.max(1, y(v) - 2);
                base -= y(v);
                return <rect key={j} x={x} y={base + 2} width={barW} height={hgt} rx={2} fill={`var(${c})`} opacity={hover === null || hover === i ? 1 : 0.45} />;
              })}
              {(i === 0 || i === daily.length - 1 || i % Math.ceil(daily.length / 7) === 0) && (
                <text x={x + barW / 2} y={H - 6} textAnchor="middle" fontSize={10} className="fill-gray-400">{d.day.slice(5)}</text>
              )}
            </g>
          );
        })}
      </svg>
      {h && (
        <div className="pointer-events-none absolute top-6 right-0 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-xs shadow-sm text-gray-700 dark:text-gray-200">
          <div className="font-medium mb-1">{h.day}</div>
          <div className="tabular-nums">{h.calls} calls: {h.calls - h.fallback - h.failed} primary, {h.fallback} failover, {h.failed} failed</div>
          <div className="tabular-nums text-gray-500 dark:text-gray-400">{h.active_users} active users, {h.agent_runs} runs</div>
        </div>
      )}
    </div>
  );
}

export default function AdminPage() {
  const router = useRouter();
  const [days, setDays] = useState(14);
  const [stats, setStats] = useState<Stats | null>(null);
  const [state, setState] = useState<"loading" | "ok" | "denied" | "error">("loading");

  const load = useCallback(async (d: number) => {
    setState("loading");
    try {
      const r = await fetch(`${API}/admin/stats?days=${d}`, { credentials: "include", cache: "no-store" });
      if (r.status === 404 || r.status === 401) { setState("denied"); router.replace("/"); return; }
      if (!r.ok) throw new Error(String(r.status));
      setStats(await r.json());
      setState("ok");
    } catch {
      setState("error");
    }
  }, [router]);

  useEffect(() => { load(days); }, [days, load]);

  const m = stats?.models;
  const served = useMemo(() => Object.entries(m?.served_by ?? {}).map(([p, n]) => [label(p), n] as [string, number]), [m]);
  const hops = useMemo(() => Object.entries(m?.by_hop ?? {}) as [string, number][], [m]);

  // Redirecting home: render nothing, so a stranger never sees the page shell.
  if (state === "denied") return null;

  return (
    <main className="viz h-screen overflow-y-auto flex-1 bg-gray-50 dark:bg-gray-950 text-gray-900 dark:text-gray-100">
      <style>{VIZ_STYLE}</style>
      <div className="max-w-6xl mx-auto px-4 py-6 space-y-4">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold">MailNet usage</h1>
            {stats && <p className="text-xs text-gray-500">{stats.window.start} to {stats.window.end} (UTC){stats.truncated ? ", capped at the newest 50,000 events" : ""}</p>}
          </div>
          <div className="flex items-center gap-2">
            <div className="inline-flex rounded-lg bg-gray-100 dark:bg-gray-800 p-0.5 text-xs">
              {RANGES.map((r) => (
                <button key={r} onClick={() => setDays(r)}
                  className={`px-2.5 py-1 rounded-md ${days === r ? "bg-white dark:bg-gray-700 shadow-sm font-medium" : "text-gray-500"}`}>
                  {r}d
                </button>
              ))}
            </div>
            <button onClick={() => load(days)} className="text-xs px-2.5 py-1 rounded-md border border-gray-200 dark:border-gray-700">Refresh</button>
            <Link href="/" className="text-xs text-blue-500 hover:underline">Back to app</Link>
          </div>
        </header>

        {state === "error" && <p className="text-sm text-red-500">Couldn&apos;t load stats. Is the API up?</p>}
        {state === "loading" && !stats && <p className="text-sm text-gray-400">Loading…</p>}

        {stats && m && (
          <>
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
              <Tile label="Active users" value={fmt(stats.users.active)} hint={`${fmt(stats.total_users)} accounts total`} />
              <Tile label="Signups" value={fmt(stats.users.signups)} />
              <Tile label="Agent runs" value={fmt(stats.totals.agent_run ?? 0)} />
              <Tile label="Model calls" value={fmt(m.calls)} />
              <Tile label="Fallback rate" value={fmt(m.fallback_rate_pct, "%")} hint="shared calls a failover hop answered" />
              <Tile label="Failed calls" value={fmt(m.calls - (m.outcomes.ok ?? 0))} hint="whole chain down" />
            </div>

            <Card title="Model calls per day">
              <DailyCalls daily={stats.daily} />
            </Card>

            <div className="grid md:grid-cols-2 gap-4">
              <Card title="Which key answered">
                <BarList rows={served} />
              </Card>
              <Card title="Primary or failover">
                <BarList rows={hops} />
              </Card>
            </div>

            <div className="grid md:grid-cols-2 gap-4">
              <Card title="Why calls failed over">
                {m.failed_attempts.length === 0 ? <p className="text-sm text-gray-400">No failed attempts</p> : (
                  <table className="w-full text-sm">
                    <thead><tr className="text-left text-xs text-gray-500"><th className="font-normal pb-1">Provider</th><th className="font-normal pb-1">Error</th><th className="font-normal pb-1 text-right">Count</th></tr></thead>
                    <tbody>{m.failed_attempts.map((f) => (
                      <tr key={`${f.provider}-${f.kind}`} className="border-t border-gray-100 dark:border-gray-800">
                        <td className="py-1">{label(f.provider)}</td><td className="py-1">{f.kind}</td><td className="py-1 text-right tabular-nums">{f.count}</td>
                      </tr>))}</tbody>
                  </table>
                )}
              </Card>
              <Card title="Latency per call">
                {Object.keys(m.latency_ms).length === 0 ? <p className="text-sm text-gray-400">Nothing yet</p> : (
                  <table className="w-full text-sm">
                    <thead><tr className="text-left text-xs text-gray-500"><th className="font-normal pb-1">Provider</th><th className="font-normal pb-1 text-right">Median</th><th className="font-normal pb-1 text-right">p95</th><th className="font-normal pb-1 text-right">Calls</th></tr></thead>
                    <tbody>{Object.entries(m.latency_ms).map(([p, l]) => (
                      <tr key={p} className="border-t border-gray-100 dark:border-gray-800">
                        <td className="py-1">{label(p)}</td><td className="py-1 text-right tabular-nums">{secs(l.p50)}</td><td className="py-1 text-right tabular-nums">{secs(l.p95)}</td><td className="py-1 text-right tabular-nums">{l.n}</td>
                      </tr>))}</tbody>
                  </table>
                )}
              </Card>
            </div>

            <div className="grid md:grid-cols-3 gap-4">
              <Card title="Tools used">
                <BarList rows={Object.entries(stats.tools.calls).slice(0, 10) as [string, number][]} />
                {Object.keys(stats.tools.errors).length > 0 && (
                  <p className="mt-3 text-xs text-gray-500">Errors: {Object.entries(stats.tools.errors).map(([t, n]) => `${t} ${n}`).join(", ")}</p>
                )}
              </Card>
              <Card title="Approvals">
                {Object.keys(stats.tools.hitl).length === 0 ? <p className="text-sm text-gray-400">No approval cards yet</p> : (
                  <ul className="space-y-1 text-sm">{Object.entries(stats.tools.hitl).map(([t, v]) => (
                    <li key={t} className="flex justify-between"><span>{t}</span><span className="tabular-nums text-gray-500">{v.approved} approved, {v.declined} declined</span></li>
                  ))}</ul>
                )}
              </Card>
              <Card title="Memory and limits">
                <ul className="space-y-1 text-sm">
                  {Object.entries(stats.memory.saves).map(([k, n]) => (
                    <li key={k} className="flex justify-between"><span>Saves: {k.replace(/_/g, " ")}</span><span className="tabular-nums">{n}</span></li>
                  ))}
                  <li className="flex justify-between"><span>Recalls with a hit</span><span className="tabular-nums">{fmt(stats.memory.recall_hit_pct, "%")} of {stats.memory.recalls}</span></li>
                  {Object.entries(stats.rate_limited).map(([k, n]) => (
                    <li key={k} className="flex justify-between"><span>Rate limited: {k.replace(/_/g, " ")}</span><span className="tabular-nums">{n}</span></li>
                  ))}
                </ul>
              </Card>
            </div>

            <Card title="Most active users">
              {stats.accounts.top_users.length === 0 ? <p className="text-sm text-gray-400">Nobody yet</p> : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead><tr className="text-left text-xs text-gray-500">{["User", "Runs", "Model calls", "Last seen (UTC)"].map((c) => <th key={c} className="font-normal pb-1 pr-3">{c}</th>)}</tr></thead>
                    <tbody>{stats.accounts.top_users.map((u) => (
                      <tr key={u.email + u.name} className="border-t border-gray-100 dark:border-gray-800">
                        <td className="py-1 pr-3"><div>{u.name}</div><div className="text-xs text-gray-400">{u.email}</div></td>
                        <td className="pr-3 tabular-nums">{u.runs}</td><td className="pr-3 tabular-nums">{u.model_calls}</td><td className="pr-3 tabular-nums text-xs">{u.last_seen ?? "n/a"}</td>
                      </tr>))}</tbody>
                  </table>
                </div>
              )}
            </Card>

            <div className="grid md:grid-cols-3 gap-4">
              <Card title="Own chat keys">
                <BarList rows={Object.entries(stats.accounts.own_chat_key).map(([p, n]) => [label(p), n] as [string, number])} empty="Everyone is on MailNet's keys" />
              </Card>
              <Card title="Own memory keys">
                <BarList rows={Object.entries(stats.accounts.own_memory_key).map(([p, n]) => [label(p === "google" ? "google_genai" : p), n] as [string, number])} empty="Everyone is on MailNet's key" />
              </Card>
              <Card title="Accounts right now">
                <ul className="space-y-1 text-sm">
                  {([
                    ["Gmail linked", stats.accounts.linked_gmail],
                    ["Outlook linked", stats.accounts.linked_outlook],
                    ["Memory paused", stats.accounts.memory_paused],
                    ["Use auto-approve", stats.accounts.auto_approve_users],
                    ["Scheduled emails queued", stats.accounts.scheduled_emails],
                    ["Tester requests", stats.accounts.tester_requests],
                  ] as [string, number | null][]).map(([k, n]) => (
                    <li key={k} className="flex justify-between"><span>{k}</span><span className="tabular-nums">{fmt(n)}</span></li>
                  ))}
                </ul>
              </Card>
            </div>

            <Card title="Daily table">
              <div className="overflow-x-auto">
                <table className="w-full text-xs tabular-nums">
                  <thead><tr className="text-left text-gray-500">{["Day", "Active", "Runs", "Calls", "Failover", "Failed", "Signups", "Limited"].map((c) => <th key={c} className="font-normal pb-1 pr-3">{c}</th>)}</tr></thead>
                  <tbody>{[...stats.daily].reverse().map((d) => (
                    <tr key={d.day} className="border-t border-gray-100 dark:border-gray-800">
                      <td className="py-1 pr-3">{d.day}</td><td className="pr-3">{d.active_users}</td><td className="pr-3">{d.agent_runs}</td><td className="pr-3">{d.calls}</td><td className="pr-3">{d.fallback}</td><td className="pr-3">{d.failed}</td><td className="pr-3">{d.signups}</td><td className="pr-3">{d.rate_limited}</td>
                    </tr>))}</tbody>
                </table>
              </div>
            </Card>
          </>
        )}
      </div>
    </main>
  );
}
