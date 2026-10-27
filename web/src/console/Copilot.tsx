import { BookOpen, Check, ChevronDown, Copy, Loader2, Sparkles, Wand2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Prose } from "@/components/ui/misc";
import type { ConsoleTicket, Run } from "@/lib/api";
import { topicLabel } from "@/lib/status";
import { cn, timeAgo } from "@/lib/utils";
import { useAiDraft } from "./hooks";

type QA = { overall_score: number; passed: boolean; checks: { rule_id: string; severity: string; passed: boolean; detail: string }[] };
type Result = {
  mode?: string;
  output?: { internal_note: string; player_reply: string; next_steps: string[]; confidence: string; citations: { article: string; section: string }[] };
  classification?: { primary_topic: string; platforms: string[]; urgency: string; extracted_ids: string[]; player_language: string };
  safety?: { pii_detected: { pii_type: string; must_redact: boolean }[]; escalation_flag: boolean; threat_type: string; escalation_target: string };
  qa?: QA[];
  timings?: Record<string, number | number[]>;
};

const DECISION_LABEL: Record<string, string> = {
  answered: "Answered, awaiting confirmation",
  needs_info: "Asked the player for info",
  low_confidence: "Answered with low confidence",
  escalated: "Holding reply + escalated",
  draft: "Draft for agent",
};

function Section({ title, children, defaultOpen = true, aside }: { title: string; children: React.ReactNode; defaultOpen?: boolean; aside?: React.ReactNode }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="border-b border-border">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 px-4 py-2.5 text-left">
        <span className="text-[11.5px] font-semibold tracking-wide text-muted uppercase">{title}</span>
        <span className="ml-auto flex items-center gap-2">
          {aside}
          <ChevronDown className={cn("size-3.5 text-faint transition-transform", !open && "-rotate-90")} />
        </span>
      </button>
      {open && <div className="px-4 pb-4">{children}</div>}
    </section>
  );
}

function ScoreRing({ score, passed }: { score: number; passed: boolean }) {
  const r = 18;
  const c = 2 * Math.PI * r;
  return (
    <div className="relative size-12">
      <svg viewBox="0 0 44 44" className="size-12 -rotate-90">
        <circle cx="22" cy="22" r={r} fill="none" stroke="var(--surface-3)" strokeWidth="4" />
        <circle cx="22" cy="22" r={r} fill="none" stroke={passed ? "var(--success)" : "var(--warning)"} strokeWidth="4" strokeLinecap="round" strokeDasharray={`${score * c} ${c}`} />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center text-[12px] font-semibold tabular-nums">{Math.round(score * 100)}</span>
    </div>
  );
}

function Timings({ timings, total }: { timings: Record<string, number | number[]>; total: number | null }) {
  const rows = [
    ["Classify", timings.classifier],
    ["Retrieve", timings.retrieval],
    ["Safety", timings.safety],
    ["Draft ×3", timings.drafting],
    ["QA", Array.isArray(timings.qa) ? timings.qa.reduce((a, b) => a + b, 0) : timings.qa],
  ].filter(([, v]) => typeof v === "number") as [string, number][];
  const max = Math.max(...rows.map(([, v]) => v), 0.001);
  return (
    <div className="space-y-1.5">
      {rows.map(([label, v]) => (
        <div key={label} className="flex items-center gap-2 text-[12px]">
          <span className="w-16 text-muted">{label}</span>
          <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-3">
            <span className="block h-full rounded-full bg-primary/70" style={{ width: `${(v / max) * 100}%` }} />
          </span>
          <span className="w-10 text-right text-faint tabular-nums">{v.toFixed(1)}s</span>
        </div>
      ))}
      {total != null && <p className="pt-1 text-right text-[11.5px] text-faint">Total {total.toFixed(1)}s (retrieval and safety run in parallel)</p>}
    </div>
  );
}

function Draft({ run, onUse }: { run: Run; onUse: (text: string) => void }) {
  const r = run.result as Result;
  if (run.status === "queued" || run.status === "running") {
    return (
      <div className="flex items-center gap-2 rounded-lg bg-surface-2 px-3 py-2.5 text-[13px] text-muted">
        <Loader2 className="size-4 animate-spin text-primary" /> Drafting a reply…
      </div>
    );
  }
  if (run.status === "failed") return <p className="text-[13px] text-danger">Draft failed. Try again.</p>;
  const text = r.output?.player_reply ?? "";
  return (
    <div className="rounded-lg border border-primary/30 bg-primary-soft/30">
      <div className="max-h-52 overflow-y-auto px-3 py-2.5">
        <Prose breaks className="text-[13px]">
          {text}
        </Prose>
      </div>
      <div className="flex items-center gap-2 border-t border-primary/20 px-3 py-2">
        <span className="text-[11.5px] text-faint">{timeAgo(run.created_at)}</span>
        <Button size="sm" className="ml-auto" onClick={() => onUse(text)}>
          <Check /> Use draft
        </Button>
      </div>
    </div>
  );
}

export function Copilot({ t, onUseDraft }: { t: ConsoleTicket; onUseDraft: (text: string) => void }) {
  const [guidance, setGuidance] = useState("");
  const [done, setDone] = useState<Set<number>>(new Set());
  const draftReq = useAiDraft(t.id);
  const run = t.runs.find((r) => r.trigger !== "agent_draft" && r.status === "succeeded");
  const draft = t.runs.find((r) => r.trigger === "agent_draft");
  const r = (run?.result ?? {}) as Result;
  const qa = r.qa?.at(-1);
  const failed = qa?.checks.filter((c) => !c.passed) ?? [];
  const decision = (run?.decision as { kind?: string })?.kind;

  return (
    <aside className="hidden w-[340px] shrink-0 flex-col overflow-y-auto border-l border-border bg-surface-2/30 xl:flex">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <span className="dawn-gradient flex size-6 items-center justify-center rounded-md text-white">
          <Sparkles className="size-3.5" />
        </span>
        <span className="text-sm font-semibold">Copilot</span>
        {r.mode && (
          <Badge tone={r.mode === "live" ? "green" : "slate"} className="ml-auto">
            {r.mode === "live" ? "Live pipeline" : "Mock pipeline"}
          </Badge>
        )}
      </div>

      <Section title="Draft a reply">
        <textarea
          value={guidance}
          onChange={(e) => setGuidance(e.target.value)}
          rows={2}
          placeholder="Optional guidance, e.g. “offer the crash compensation” or “ask for NetLog.txt”"
          className="w-full resize-none rounded-lg border border-border bg-surface px-3 py-2 text-[13px] placeholder:text-faint focus:border-primary focus:outline-none"
        />
        <Button size="sm" variant="dawn" className="mt-2 w-full" onClick={() => draftReq.mutate(guidance)} disabled={draftReq.isPending || draft?.status === "running" || draft?.status === "queued"}>
          <Wand2 /> Generate draft
        </Button>
        <p className="mt-1.5 text-[11.5px] text-faint">Drafts are written as a human agent and never sent automatically.</p>
        {draft && (
          <div className="mt-3">
            <Draft run={draft} onUse={onUseDraft} />
          </div>
        )}
      </Section>

      {!run ? (
        <p className="px-4 py-6 text-[13px] text-muted">{t.ai_state === "working" ? "The AI is working on this ticket…" : "No AI analysis yet."}</p>
      ) : (
        <>
          <Section title="Last AI run" aside={<span className="text-[11.5px] text-faint">{timeAgo(run.created_at)}</span>}>
            <div className="flex items-center gap-3">
              {qa && <ScoreRing score={qa.overall_score} passed={qa.passed} />}
              <div className="min-w-0 text-[13px]">
                <p className="font-medium">{decision ? DECISION_LABEL[decision] ?? decision : "—"}</p>
                <p className="text-muted">
                  QA {qa?.passed ? "passed" : "failed"} · confidence {r.output?.confidence ?? "?"}
                </p>
              </div>
            </div>
            {failed.length > 0 && (
              <ul className="mt-3 space-y-1.5">
                {failed.map((c) => (
                  <li key={c.rule_id} className="rounded-lg bg-warning-soft/60 px-2.5 py-1.5 text-[12px]">
                    <span className="font-medium">{c.rule_id}</span> <span className="text-faint">({c.severity})</span>
                    {c.detail && <span className="block text-muted">{c.detail}</span>}
                  </li>
                ))}
              </ul>
            )}
          </Section>

          {r.classification && (
            <Section title="Classification">
              <dl className="grid grid-cols-[88px_1fr] gap-y-1.5 text-[12.5px]">
                <dt className="text-faint">Topic</dt>
                <dd>{topicLabel(r.classification.primary_topic)}</dd>
                <dt className="text-faint">Platforms</dt>
                <dd>{r.classification.platforms.join(", ") || "—"}</dd>
                <dt className="text-faint">Urgency</dt>
                <dd className="capitalize">{r.classification.urgency}</dd>
                <dt className="text-faint">IDs found</dt>
                <dd className="break-all">{r.classification.extracted_ids.join(", ") || "—"}</dd>
                <dt className="text-faint">Language</dt>
                <dd className="uppercase">{r.classification.player_language}</dd>
              </dl>
            </Section>
          )}

          {r.safety && (r.safety.escalation_flag || r.safety.pii_detected.length > 0) && (
            <Section title="Safety">
              <div className="space-y-1.5 text-[12.5px]">
                {r.safety.escalation_flag && (
                  <p>
                    <Badge tone="red">{r.safety.threat_type.replace(/_/g, " ")}</Badge> → {r.safety.escalation_target}
                  </p>
                )}
                {r.safety.pii_detected.map((p, i) => (
                  <p key={i}>
                    <Badge tone={p.must_redact ? "amber" : "slate"}>{p.pii_type.replace(/_/g, " ")}</Badge> {p.must_redact ? "must redact" : ""}
                  </p>
                ))}
              </div>
            </Section>
          )}

          {r.output && r.output.next_steps.length > 0 && (
            <Section title="Next steps">
              <ol className="space-y-1.5">
                {r.output.next_steps.map((s, i) => (
                  <li key={i}>
                    <label className="flex cursor-pointer gap-2.5 text-[13px]">
                      <input
                        type="checkbox"
                        checked={done.has(i)}
                        onChange={() => setDone((d) => new Set(d.has(i) ? [...d].filter((x) => x !== i) : [...d, i]))}
                        className="mt-0.5 size-3.5 accent-[var(--primary)]"
                      />
                      <span className={cn(done.has(i) && "text-faint line-through")}>{s}</span>
                    </label>
                  </li>
                ))}
              </ol>
            </Section>
          )}

          {r.output?.internal_note && (
            <Section
              title="Internal note"
              defaultOpen={false}
              aside={
                <span
                  role="button"
                  tabIndex={0}
                  onClick={(e) => {
                    e.stopPropagation();
                    navigator.clipboard.writeText(r.output!.internal_note).then(() => toast.success("Note copied"));
                  }}
                  className="text-faint hover:text-text"
                  aria-label="Copy internal note"
                >
                  <Copy className="size-3.5" />
                </span>
              }
            >
              <Prose breaks className="text-[12.5px]">
                {r.output.internal_note}
              </Prose>
            </Section>
          )}

          {r.output && r.output.citations.length > 0 && (
            <Section title="Sources used">
              <ul className="space-y-1.5">
                {r.output.citations.map((c, i) => (
                  <li key={i} className="flex gap-2 text-[12.5px]">
                    <BookOpen className="mt-0.5 size-3.5 shrink-0 text-dawn-text" />
                    <span>
                      {c.article} <span className="text-faint">› {c.section}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {r.timings && (
            <Section title="Pipeline timing" defaultOpen={false}>
              <Timings timings={r.timings} total={run.duration_s} />
            </Section>
          )}
        </>
      )}
    </aside>
  );
}
