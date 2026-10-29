import { useQuery } from "@tanstack/react-query";
import { ArrowDownRight, ArrowUpRight, BookPlus, Info, Table2 } from "lucide-react";
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis } from "recharts";
import { Badge } from "@/components/ui/badge";
import { Skeleton, Tooltip } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { topicLabel } from "@/lib/status";
import { cn } from "@/lib/utils";

type Kpis = {
  tickets: number;
  resolved: number;
  ai_resolution_rate: number | null;
  resolved_by: { ai: number; agent: number; auto: number };
  handoff_rate: number | null;
  escalations: number;
  deflections: number;
  article_feedback: number;
  median_first_response_s: number | null;
  median_first_human_response_h: number | null;
  median_resolution_h: number | null;
  csat_avg: number | null;
  csat_count: number;
};
type Report = {
  range: { days: number };
  has_demo_data: boolean;
  kpis: Kpis;
  previous: Kpis;
  volume: { date: string; created: number; ai: number; agent: number; auto: number; open: number }[];
  topics: { topic: string; tickets: number; ai_resolution_rate: number | null; low_confidence_rate: number | null; csat_avg: number | null }[];
  kb_gaps: { topic: string; tickets: number; low_confidence_rate: number | null; no_citation: number }[];
  handoff_reasons: Record<string, number>;
  pending_aging: { bucket: string; count: number }[];
  backlog: Record<string, number>;
  csat_distribution: { rating: number; count: number }[];
  qa: { runs: number; pass_rate: number | null; avg_score: number | null; critical_fail_rate: number | null };
  latency: Record<string, number | null>;
  top_articles: { slug: string; title: string; citations: number }[];
  deflection_articles: { slug: string; title: string; helpful: number }[];
};

// Outcome series in fixed categorical order (validated: see index.css). "Open" is a neutral, not a category.
const OUTCOMES = [
  { key: "ai", label: "Resolved by AI", color: "var(--series-1)" },
  { key: "agent", label: "Resolved by agent", color: "var(--series-2)" },
  { key: "auto", label: "Auto-solved (no reply)", color: "var(--series-3)" },
  { key: "open", label: "Not resolved yet", color: "var(--series-neutral)" },
] as const;

const pct = (v: number | null | undefined, digits = 0) => (v == null ? "—" : `${(v * 100).toFixed(digits)}%`);
const dur = (h: number | null | undefined) => (h == null ? "—" : h < 1 ? `${Math.round(h * 60)}m` : h < 48 ? `${h.toFixed(1)}h` : `${(h / 24).toFixed(1)}d`);
const shortDate = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" });

/* ── Building blocks ────────────────────────────────────────────────────────── */

function Card({ title, subtitle, children, className, action }: { title: string; subtitle?: string; children: React.ReactNode; className?: string; action?: React.ReactNode }) {
  return (
    <section className={cn("rounded-2xl border border-border bg-surface p-5 shadow-soft", className)}>
      <div className="mb-4 flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <h2 className="text-[14px] font-semibold tracking-tight">{title}</h2>
          {subtitle && <p className="mt-0.5 text-[12.5px] text-muted">{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function Delta({ cur, prev, goodWhenUp, format }: { cur: number | null; prev: number | null; goodWhenUp: boolean; format: (d: number) => string }) {
  if (cur == null || prev == null || prev === 0) return <span className="text-[12px] text-faint">no prior data</span>;
  const d = cur - prev;
  if (Math.abs(d) < 1e-9) return <span className="text-[12px] text-faint">no change</span>;
  const up = d > 0;
  const good = up === goodWhenUp;
  const Icon = up ? ArrowUpRight : ArrowDownRight;
  return (
    <span className={cn("inline-flex items-center gap-0.5 text-[12px] font-medium", good ? "text-success" : "text-danger")}>
      <Icon className="size-3.5" />
      {format(Math.abs(d))}
      <span className="ml-1 font-normal text-faint">vs prior</span>
    </span>
  );
}

function StatTile({ label, value, hint, delta, hero }: { label: string; value: string; hint?: string; delta?: React.ReactNode; hero?: boolean }) {
  return (
    <div className={cn("rounded-2xl border border-border bg-surface p-4 shadow-soft", hero && "sm:col-span-2 lg:col-span-1 lg:row-span-1")}>
      <div className="flex items-center gap-1.5 text-[12.5px] text-muted">
        {label}
        {hint && (
          <Tooltip label={<span className="block max-w-56">{hint}</span>}>
            <Info className="size-3.5 text-faint" />
          </Tooltip>
        )}
      </div>
      <p className={cn("mt-1.5 font-semibold tracking-tight", hero ? "text-[40px] leading-none" : "text-[26px] leading-tight")}>{value}</p>
      <div className="mt-1.5 h-4">{delta}</div>
    </div>
  );
}

/** Inline horizontal bar for tables: single series, value label outside the bar. */
function InlineBar({ value, max, label }: { value: number; max: number; label: string }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-surface-2">
        <div className="h-full rounded-r-[4px] bg-[var(--series-1)]" style={{ width: `${max ? (value / max) * 100 : 0}%` }} />
      </div>
      <span className="w-10 text-right text-[12.5px] text-muted tabular-nums">{label}</span>
    </div>
  );
}

function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: { dataKey: string; value: number; color: string; name: string }[]; label?: string }) {
  if (!active || !payload?.length) return null;
  const total = payload.reduce((a, p) => a + (p.value || 0), 0);
  return (
    <div className="rounded-xl border border-border bg-surface px-3 py-2.5 text-[12.5px] shadow-lift">
      <p className="mb-1.5 font-medium">{label ? shortDate(label) : ""}</p>
      {[...payload].reverse().map((p) => (
        <p key={p.dataKey} className="flex items-center gap-2">
          <span className="size-2.5 rounded-[3px]" style={{ background: p.color }} />
          <span className="text-muted">{p.name}</span>
          <span className="ml-auto pl-4 font-medium tabular-nums">{p.value}</span>
        </p>
      ))}
      <p className="mt-1.5 flex border-t border-border pt-1.5 text-muted">
        Tickets opened <span className="ml-auto font-medium text-text tabular-nums">{total}</span>
      </p>
    </div>
  );
}

function Legend() {
  return (
    <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1.5">
      {OUTCOMES.map((o) => (
        <span key={o.key} className="flex items-center gap-1.5 text-[12px] text-muted">
          <span className="size-2.5 rounded-[3px]" style={{ background: o.color }} />
          {o.label}
        </span>
      ))}
    </div>
  );
}

function VolumeChart({ data }: { data: Report["volume"] }) {
  const [table, setTable] = useState(false);
  const barSize = Math.max(4, Math.min(24, Math.floor(640 / data.length) - 4));
  return (
    <Card
      title="Tickets opened per day, by outcome"
      subtitle="Each day's tickets split by how they were resolved"
      action={
        <button onClick={() => setTable(!table)} className="flex items-center gap-1.5 rounded-lg px-2 py-1 text-[12px] text-muted hover:bg-surface-2 hover:text-text">
          <Table2 className="size-3.5" /> {table ? "Show chart" : "Show table"}
        </button>
      }
    >
      {table ? (
        <div className="max-h-72 overflow-y-auto">
          <table className="w-full text-[12.5px] tabular-nums">
            <thead className="sticky top-0 bg-surface text-left text-faint">
              <tr>
                <th className="py-1.5 font-medium">Date</th>
                <th className="py-1.5 text-right font-medium">Opened</th>
                {OUTCOMES.map((o) => (
                  <th key={o.key} className="py-1.5 text-right font-medium">
                    {o.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[...data].reverse().map((d) => (
                <tr key={d.date} className="border-t border-border">
                  <td className="py-1.5">{shortDate(d.date)}</td>
                  <td className="py-1.5 text-right">{d.created}</td>
                  {OUTCOMES.map((o) => (
                    <td key={o.key} className="py-1.5 text-right text-muted">
                      {d[o.key]}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <>
          <Legend />
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -18 }} barCategoryGap="20%">
                <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
                <XAxis dataKey="date" tickFormatter={shortDate} tick={{ fill: "var(--chart-axis)", fontSize: 11 }} axisLine={{ stroke: "var(--chart-grid)" }} tickLine={false} minTickGap={28} />
                <YAxis allowDecimals={false} tick={{ fill: "var(--chart-axis)", fontSize: 11 }} axisLine={false} tickLine={false} width={44} />
                <RTooltip content={<ChartTooltip />} cursor={{ fill: "var(--surface-2)" }} />
                {OUTCOMES.map((o, i) => (
                  <Bar
                    key={o.key}
                    dataKey={o.key}
                    name={o.label}
                    stackId="v"
                    fill={o.color}
                    barSize={barSize}
                    stroke="var(--surface)"
                    strokeWidth={data.length > 45 ? 1 : 2}
                    radius={i === OUTCOMES.length - 1 ? [4, 4, 0, 0] : 0}
                    isAnimationActive={false}
                  />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </Card>
  );
}

function SimpleBars({ rows, valueLabel }: { rows: { label: string; value: number; display?: string }[]; valueLabel?: (v: number) => string }) {
  const max = Math.max(...rows.map((r) => r.value), 0);
  if (!rows.length || max === 0) return <p className="text-[13px] text-faint">No data in this period.</p>;
  return (
    <ul className="space-y-3">
      {rows.map((r) => (
        <li key={r.label} className="text-[13px]">
          <div className="flex items-baseline justify-between gap-3">
            <span className="truncate text-muted">{r.label}</span>
            <span className="shrink-0 tabular-nums">{r.display ?? (valueLabel ? valueLabel(r.value) : String(r.value))}</span>
          </div>
          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-surface-2">
            <div className="h-full rounded-r-[4px] bg-[var(--series-1)]" style={{ width: `${(r.value / max) * 100}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

function CsatChart({ data, avg, count }: { data: Report["csat_distribution"]; avg: number | null; count: number }) {
  const max = Math.max(...data.map((d) => d.count), 1);
  const faces = ["😣", "🙁", "😐", "🙂", "🤩"];
  return (
    <Card title="Player satisfaction" subtitle={count ? `${count} ratings · average ${avg?.toFixed(2)} / 5` : "No ratings yet"}>
      <div className="flex h-36 items-end gap-3 border-b border-[var(--chart-grid)] px-2">
        {data.map((d) => (
          <Tooltip key={d.rating} label={`${d.count} rating${d.count === 1 ? "" : "s"} of ${d.rating}`}>
            <div className="flex h-full flex-1 flex-col items-center justify-end gap-1">
              <span className="text-[11.5px] text-muted tabular-nums">{d.count || ""}</span>
              <div className="w-full max-w-6 rounded-t-[4px] bg-[var(--series-1)]" style={{ height: `${(d.count / max) * 100}%`, minHeight: d.count ? 3 : 0 }} />
            </div>
          </Tooltip>
        ))}
      </div>
      <div className="mt-1.5 flex gap-3 px-2">
        {data.map((d) => (
          <span key={d.rating} className="flex-1 text-center text-[14px]" aria-label={`${d.rating} stars`}>
            {faces[d.rating - 1]}
          </span>
        ))}
      </div>
    </Card>
  );
}

/* ── Page ──────────────────────────────────────────────────────────────────── */

export default function Reports() {
  const [days, setDays] = useState(30);
  const report = useQuery({
    queryKey: ["reports", days],
    queryFn: () => api<Report>(`/api/console/reports?days=${days}`),
    placeholderData: (p) => p,
  });
  const r = report.data;
  const k = r?.kpis;
  const p = r?.previous;

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-6xl px-5 py-6 sm:px-8">
        <div className="mb-6 flex flex-wrap items-center gap-3">
          <div className="flex-1">
            <h1 className="text-xl font-semibold tracking-tight">Reporting</h1>
            <p className="mt-0.5 text-[13px] text-muted">How the AI and the team are handling player support.</p>
          </div>
          {r?.has_demo_data && (
            <Badge tone="slate" className="h-6">
              Includes seeded demo data
            </Badge>
          )}
          <div className="inline-flex rounded-lg bg-surface-2 p-1" role="radiogroup" aria-label="Date range">
            {[7, 30, 90].map((d) => (
              <button
                key={d}
                role="radio"
                aria-checked={days === d}
                onClick={() => setDays(d)}
                className={cn("rounded-md px-3 py-1 text-[13px] font-medium transition", days === d ? "bg-surface text-text shadow-soft" : "text-muted hover:text-text")}
              >
                {d} days
              </button>
            ))}
          </div>
        </div>

        {report.isError && !r ? (
          <div className="rounded-2xl border border-danger/30 bg-danger-soft p-5 text-sm">
            Couldn't load the report: {report.error.message}{" "}
            <button onClick={() => report.refetch()} className="font-medium underline">
              Try again
            </button>
          </div>
        ) : !r || !k || !p ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 8 }, (_, i) => (
              <Skeleton key={i} className={cn("rounded-2xl", i < 4 ? "h-28" : "h-64 sm:col-span-2")} />
            ))}
          </div>
        ) : (
          <div className={cn("space-y-4 transition-opacity", report.isFetching && "opacity-70")}>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <StatTile
                hero
                label="AI resolution rate"
                hint="Resolved tickets the player confirmed as fixed with no human reply. Auto-solved tickets (player went quiet) are not counted as AI wins."
                value={pct(k.ai_resolution_rate)}
                delta={<Delta cur={k.ai_resolution_rate} prev={p.ai_resolution_rate} goodWhenUp format={(d) => `${(d * 100).toFixed(1)} pts`} />}
              />
              <StatTile
                label="Tickets opened"
                value={k.tickets.toLocaleString()}
                hint={`${k.deflections} more players found their answer in a help article instead of opening a ticket.`}
                delta={<Delta cur={k.tickets} prev={p.tickets} goodWhenUp={false} format={(d) => d.toFixed(0)} />}
              />
              <StatTile
                label="First response (median)"
                value={k.median_first_response_s == null ? "—" : `${Math.round(k.median_first_response_s)}s`}
                hint="Time from ticket creation to the first answer, almost always the AI's."
                delta={<span className="text-[12px] text-faint">human first reply: {dur(k.median_first_human_response_h)}</span>}
              />
              <StatTile
                label="CSAT"
                value={k.csat_avg == null ? "—" : `${k.csat_avg.toFixed(2)}`}
                hint="Average rating (1–5) players gave after their ticket was solved."
                delta={<Delta cur={k.csat_avg} prev={p.csat_avg} goodWhenUp format={(d) => d.toFixed(2)} />}
              />
            </div>

            <div className="grid gap-4 lg:grid-cols-3">
              <div className="lg:col-span-2">
                <VolumeChart data={r.volume} />
              </div>
              <Card title="Resolution" subtitle={`${k.resolved} resolved · median ${dur(k.median_resolution_h)} to resolve`}>
                <SimpleBars
                  rows={OUTCOMES.slice(0, 3).map((o) => ({
                    label: o.label,
                    value: k.resolved_by[o.key as "ai" | "agent" | "auto"],
                    display: pct(k.resolved ? k.resolved_by[o.key as "ai" | "agent" | "auto"] / k.resolved : null),
                  }))}
                />
                <div className="mt-5 border-t border-border pt-4">
                  <p className="mb-2.5 text-[12.5px] font-medium">Handed to a human · {pct(k.handoff_rate)}</p>
                  <SimpleBars
                    rows={Object.entries(r.handoff_reasons)
                      .sort((a, b) => b[1] - a[1])
                      .map(([reason, n]) => ({
                        label: { player_request: "Player asked", safety: "Safety flag", ai_error: "AI error", agent_took_over: "Agent took over" }[reason] ?? reason,
                        value: n,
                      }))}
                  />
                </div>
              </Card>
            </div>

            <div className="grid gap-4 lg:grid-cols-3">
              <Card title="Topics" subtitle="What players contact us about, and how well the AI handles each" className="lg:col-span-2">
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[520px] text-[13px]">
                    <thead className="text-left text-[12px] text-faint">
                      <tr>
                        <th className="pb-2 font-medium">Topic</th>
                        <th className="w-[34%] pb-2 font-medium">Tickets</th>
                        <th className="pb-2 text-right font-medium">AI resolved</th>
                        <th className="pb-2 text-right font-medium">Low confidence</th>
                        <th className="pb-2 text-right font-medium">CSAT</th>
                      </tr>
                    </thead>
                    <tbody className="tabular-nums">
                      {r.topics.map((t) => (
                        <tr key={t.topic} className="border-t border-border">
                          <td className="py-2 pr-3">{topicLabel(t.topic)}</td>
                          <td className="py-2 pr-4">
                            <InlineBar value={t.tickets} max={r.topics[0]?.tickets ?? 1} label={String(t.tickets)} />
                          </td>
                          <td className="py-2 text-right">{pct(t.ai_resolution_rate)}</td>
                          <td className={cn("py-2 text-right", (t.low_confidence_rate ?? 0) >= 0.3 ? "font-medium text-warning" : "text-muted")}>{pct(t.low_confidence_rate)}</td>
                          <td className="py-2 text-right text-muted">{t.csat_avg?.toFixed(1) ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
              <Card title="Knowledge gaps" subtitle="Topics where the AI often had no good article. Write these next.">
                {r.kb_gaps.length === 0 ? (
                  <p className="text-[13px] text-muted">No gaps: the help center covers what players are asking.</p>
                ) : (
                  <ul className="space-y-2.5">
                    {r.kb_gaps.map((g) => (
                      <li key={g.topic} className="flex items-start gap-3 rounded-xl border border-warning/30 bg-warning-soft/40 p-3">
                        <BookPlus className="mt-0.5 size-4 shrink-0 text-warning" />
                        <div className="text-[13px]">
                          <p className="font-medium">{topicLabel(g.topic)}</p>
                          <p className="text-muted">
                            {g.tickets} tickets · {pct(g.low_confidence_rate)} low confidence · {g.no_citation} with no source
                          </p>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
            </div>

            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              <Card title="Waiting on players" subtitle="Pending tickets by how long they've waited">
                <SimpleBars rows={r.pending_aging.map((a) => ({ label: a.bucket, value: a.count }))} />
                <p className="mt-4 text-[12px] text-faint">Reminders go out at 3 days; tickets auto-solve at 7.</p>
              </Card>
              <CsatChart data={r.csat_distribution} avg={k.csat_avg} count={k.csat_count} />
              <Card title="AI quality" subtitle={`${r.qa.runs} player-facing AI answers`}>
                <dl className="grid grid-cols-3 gap-3">
                  {[
                    ["QA pass rate", pct(r.qa.pass_rate)],
                    ["Avg QA score", r.qa.avg_score == null ? "—" : `${Math.round(r.qa.avg_score * 100)}`],
                    ["Critical fails", pct(r.qa.critical_fail_rate, 1)],
                  ].map(([l, v]) => (
                    <div key={l}>
                      <dt className="text-[12px] text-muted">{l}</dt>
                      <dd className="mt-0.5 text-[20px] font-semibold tracking-tight">{v}</dd>
                    </div>
                  ))}
                </dl>
                <p className="mt-5 mb-2.5 text-[12.5px] font-medium">Median time per stage</p>
                <SimpleBars
                  rows={(["classifier", "retrieval", "safety", "drafting", "qa"] as const)
                    .filter((s) => r.latency[s] != null)
                    .map((s) => ({ label: { classifier: "Classify", retrieval: "Retrieve", safety: "Safety", drafting: "Draft (parallel)", qa: "QA" }[s], value: r.latency[s] ?? 0 }))}
                  valueLabel={(v) => `${v.toFixed(1)}s`}
                />
              </Card>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <Card title="Most-cited help articles" subtitle="Tickets where the AI used each article in its answer">
                <SimpleBars rows={r.top_articles.map((a) => ({ label: a.title, value: a.citations }))} />
              </Card>
              <Card title="Self-service deflection" subtitle={`${k.deflections} of ${k.article_feedback} article readers said it solved their problem`}>
                <SimpleBars rows={r.deflection_articles.map((a) => ({ label: a.title, value: a.helpful }))} />
              </Card>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
