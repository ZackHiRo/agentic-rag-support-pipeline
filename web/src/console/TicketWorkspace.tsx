import {
  AlertTriangle,
  Check,
  ChevronDown,
  CircleCheck,
  FileText,
  ListPlus,
  Loader2,
  Lock,
  MessageSquare,
  ShieldAlert,
  Sparkles,
  UserRoundCheck,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Badge, Kbd } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Avatar, Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger, Prose, Skeleton } from "@/components/ui/misc";
import { useMe } from "@/hooks/auth";
import type { ConsoleTicket, Message, TicketEvent } from "@/lib/api";
import { HANDOFF_REASON, PRIORITY, STAFF_STATUS, topicLabel } from "@/lib/status";
import { cn, formatBytes, formatDateTime, timeAgo } from "@/lib/utils";
import { Copilot } from "./Copilot";
import { useConsoleTicket, usePatchTicket, useReply, useStaff } from "./hooks";

const THREAT_LABEL: Record<string, string> = {
  legal: "Legal threat",
  rlt_self_harm: "Self-harm risk",
  rlt_violence: "Threat of violence",
  sensitive_inquiry: "Sensitive inquiry",
  controversial: "Controversial",
};

/* ── Header controls ─────────────────────────────────────────────────────────── */

function Picker({ label, value, children }: { label: string; value: React.ReactNode; children: React.ReactNode }) {
  return (
    <Menu>
      <MenuTrigger asChild>
        <button className="flex h-8 items-center gap-1.5 rounded-lg border border-border bg-surface px-2.5 text-[12.5px] shadow-soft hover:border-border-strong">
          <span className="text-faint">{label}</span>
          {value}
          <ChevronDown className="size-3.5 text-faint" />
        </button>
      </MenuTrigger>
      <MenuContent align="start">{children}</MenuContent>
    </Menu>
  );
}

function Header({ t }: { t: ConsoleTicket }) {
  const patch = usePatchTicket(t.id);
  const staff = useStaff().data ?? [];
  const me = useMe().data;
  const status = STAFF_STATUS[t.status];
  return (
    <header className="border-b border-border px-5 pt-4 pb-3">
      <div className="flex flex-wrap items-center gap-2 text-[12.5px] text-faint">
        <span className="tabular-nums">{t.ref}</span>
        <span>·</span>
        <span title={formatDateTime(t.created_at)}>opened {timeAgo(t.created_at)}</span>
        {t.platform && (
          <>
            <span>·</span>
            <span>{t.platform}</span>
          </>
        )}
        {t.topic && (
          <>
            <span>·</span>
            <span>{topicLabel(t.topic)}</span>
          </>
        )}
      </div>
      <h2 className="mt-1 text-lg font-semibold tracking-tight text-balance">{t.subject}</h2>
      <p className="mt-0.5 text-[13px] text-muted">
        {t.requester_name} <span className="text-faint">&lt;{t.requester_email}&gt;</span>
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Picker label="Status" value={<Badge tone={status?.tone ?? "slate"}>{status?.label ?? t.status}</Badge>}>
          {Object.entries(STAFF_STATUS)
            .filter(([k]) => k !== "new")
            .map(([k, v]) => (
              <MenuItem key={k} onSelect={() => patch.mutate({ status: k })}>
                <Badge tone={v.tone} dot>
                  {v.label}
                </Badge>
                {k === t.status && <Check className="ml-auto" />}
              </MenuItem>
            ))}
        </Picker>
        <Picker label="Priority" value={<span className="font-medium">{PRIORITY[t.priority]?.label}</span>}>
          {Object.entries(PRIORITY).map(([k, v]) => (
            <MenuItem key={k} onSelect={() => patch.mutate({ priority: k })}>
              {v.label}
              {k === t.priority && <Check className="ml-auto" />}
            </MenuItem>
          ))}
        </Picker>
        <Picker
          label="Assignee"
          value={
            t.assignee_name ? (
              <span className="flex items-center gap-1.5 font-medium">
                <Avatar name={t.assignee_name} className="size-5 text-[9px]" /> {t.assignee_name}
              </span>
            ) : (
              <span className="text-muted">Unassigned</span>
            )
          }
        >
          {me && me.id !== t.assignee_id && (
            <>
              <MenuItem onSelect={() => patch.mutate({ assignee_id: me.id })}>
                <UserRoundCheck /> Assign to me
              </MenuItem>
              <MenuSeparator />
            </>
          )}
          <MenuLabel>Team</MenuLabel>
          {staff.map((s) => (
            <MenuItem key={s.id} onSelect={() => patch.mutate({ assignee_id: s.id })}>
              <Avatar name={s.display_name} className="size-5 text-[9px]" /> {s.display_name}
              {s.id === t.assignee_id && <Check className="ml-auto" />}
            </MenuItem>
          ))}
          {t.assignee_id && (
            <>
              <MenuSeparator />
              <MenuItem onSelect={() => patch.mutate({ unassign: true })}>
                <X /> Unassign
              </MenuItem>
            </>
          )}
        </Picker>
        {!["solved", "closed"].includes(t.status) && (
          <Button size="sm" variant="secondary" className="ml-auto" onClick={() => patch.mutate({ status: "solved" })} disabled={patch.isPending}>
            <CircleCheck className="text-success" /> Mark solved
          </Button>
        )}
      </div>
    </header>
  );
}

function Banners({ t }: { t: ConsoleTicket }) {
  const items: { icon: typeof AlertTriangle; tone: string; text: React.ReactNode }[] = [];
  const reason = t.runs.find((r) => r.trigger !== "agent_draft")?.result?.safety as { escalation_reason?: string } | undefined;
  if (t.escalated || t.threat_type !== "none") {
    items.push({
      icon: ShieldAlert,
      tone: "border-danger/30 bg-danger-soft text-danger",
      text: (
        <>
          <strong>{THREAT_LABEL[t.threat_type] ?? "Escalation"}.</strong> {reason?.escalation_reason || "Flagged by the safety agent."} The AI sent a holding reply
          and will not answer on its own.
        </>
      ),
    });
  } else if (t.handoff_reason && t.needs_human && !["solved", "closed"].includes(t.status)) {
    items.push({ icon: UserRoundCheck, tone: "border-info/30 bg-info-soft text-info", text: <strong>{HANDOFF_REASON[t.handoff_reason] ?? t.handoff_reason}.</strong> });
  }
  if (t.needs_review && !["solved", "closed"].includes(t.status)) {
    items.push({
      icon: Sparkles,
      tone: "border-primary/30 bg-primary-soft text-primary",
      text: (
        <>
          <strong>AI answered with low confidence.</strong> Check the reply below; take over if it's off.
        </>
      ),
    });
  }
  if (t.pii_flag) {
    items.push({
      icon: Lock,
      tone: "border-warning/30 bg-warning-soft text-warning",
      text: (
        <>
          <strong>Personal data detected.</strong> Redact it before quoting the player.
        </>
      ),
    });
  }
  if (!items.length) return null;
  return (
    <div className="space-y-2 border-b border-border px-5 py-3">
      {items.map((it, i) => (
        <div key={i} className={cn("flex items-start gap-2.5 rounded-xl border px-3.5 py-2.5 text-[13px]", it.tone)}>
          <it.icon className="mt-0.5 size-4 shrink-0" />
          <p className="text-text">{it.text}</p>
        </div>
      ))}
    </div>
  );
}

/* ── Conversation ────────────────────────────────────────────────────────────── */

function ConsoleMessage({ m }: { m: Message }) {
  const internal = m.visibility === "internal";
  const isAiNote = internal && m.author_kind === "ai";
  if (m.author_kind === "system") {
    return (
      <div className="flex items-center gap-3 py-1 text-[12px] text-faint">
        <span className="h-px flex-1 bg-border" />
        <span className="max-w-[70%] text-center">{m.body}</span>
        <span className="h-px flex-1 bg-border" />
      </div>
    );
  }
  return (
    <div className="flex gap-3">
      <Avatar name={m.author_name} kind={m.author_kind} className="mt-0.5" />
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex flex-wrap items-center gap-2 text-[12.5px]">
          <span className="font-medium">{m.author_name}</span>
          {m.author_kind === "player" && <Badge tone="slate">Player</Badge>}
          {m.author_kind === "ai" && !internal && <Badge tone="violet">AI · sent to player</Badge>}
          {internal && (
            <Badge tone="amber">
              <Lock className="size-3" /> {isAiNote ? "AI internal note" : "Internal note"}
            </Badge>
          )}
          <span className="text-faint" title={formatDateTime(m.created_at)}>
            {timeAgo(m.created_at)}
          </span>
        </div>
        <div
          className={cn(
            "rounded-xl border px-4 py-3",
            internal ? "border-dashed border-warning/40 bg-warning-soft/40" : m.author_kind === "player" ? "border-border bg-surface-2/60" : "border-border bg-surface",
          )}
        >
          <Prose breaks className="text-[14px]">
            {m.body}
          </Prose>
          {(m.citations.length > 0 || m.crisis_resources) && (
            <div className="mt-2.5 flex flex-wrap gap-1.5 text-[11.5px] text-muted">
              {m.crisis_resources && <Badge tone="red">Crisis resources shown</Badge>}
              {m.citations.map((c) => (
                <span key={c.slug} className="rounded-md bg-surface-2 px-1.5 py-0.5">
                  ↳ {c.title}
                </span>
              ))}
            </div>
          )}
        </div>
        {m.attachments.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-2">
            {m.attachments.map((a) =>
              a.mime.startsWith("image/") ? (
                <a key={a.id} href={a.url} target="_blank" rel="noreferrer" className="overflow-hidden rounded-lg border border-border">
                  <img src={a.url} alt={a.filename} className="h-20 max-w-40 object-cover" loading="lazy" />
                </a>
              ) : (
                <a key={a.id} href={a.url} target="_blank" rel="noreferrer" className="flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-[12.5px]">
                  <FileText className="size-3.5 text-muted" /> {a.filename} <span className="text-faint">{formatBytes(a.size)}</span>
                </a>
              ),
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function describeEvent(e: TicketEvent): string {
  const d = e.data as Record<string, unknown>;
  switch (e.kind) {
    case "ticket.created":
      return "opened the ticket";
    case "status.changed":
      return `changed status ${STAFF_STATUS[d.from as string]?.label ?? d.from} → ${STAFF_STATUS[d.to as string]?.label ?? d.to}${d.reason ? ` (${String(d.reason).replace(/_/g, " ")})` : ""}`;
    case "ai.replied":
      return `answered the player (${String(d.decision).replace(/_/g, " ")}${d.qa_score != null ? `, QA ${Math.round(Number(d.qa_score) * 100)}%` : ""})`;
    case "ai.escalated":
      return "sent a holding reply and escalated to the team";
    case "ai.failed":
      return "couldn't produce an answer";
    case "ai.draft_requested":
      return "asked the copilot for a draft";
    case "ai.draft_ready":
      return "prepared a reply draft";
    case "handoff.requested":
      return "asked for a human";
    case "action.completed":
      return "completed a checklist item";
    case "agent.replied":
      return `replied to the player${Number(d.action_items) ? ` and requested ${d.action_items} item(s)` : ""}`;
    case "note.added":
      return "added an internal note";
    case "priority.changed":
      return `set priority to ${PRIORITY[d.to as string]?.label ?? d.to}`;
    case "assignee.changed":
      return d.to ? `assigned the ticket to ${d.to}` : "unassigned the ticket";
    case "csat.submitted":
      return `rated the support ${d.rating}/5`;
    case "reminder.sent":
      return "sent a reminder to the player";
    case "player.replied":
      return "replied";
    default:
      return e.kind.replace(/[._]/g, " ");
  }
}

function Activity({ t }: { t: ConsoleTicket }) {
  return (
    <ol className="relative space-y-4 border-l border-border pl-5">
      {t.events.map((e) => (
        <li key={e.id} className="relative text-[13px]">
          <span className={cn("absolute top-1.5 -left-[24.5px] size-2 rounded-full ring-4 ring-bg", e.actor_kind === "ai" ? "bg-primary" : e.actor_kind === "agent" ? "bg-info" : e.actor_kind === "player" ? "bg-dawn" : "bg-faint")} />
          <span className="font-medium">{e.actor_name}</span> <span className="text-muted">{describeEvent(e)}</span>
          <span className="block text-[11.5px] text-faint">{formatDateTime(e.at)}</span>
        </li>
      ))}
    </ol>
  );
}

/* ── Composer ────────────────────────────────────────────────────────────────── */

function Composer({ t, draft, onDraftUsed }: { t: ConsoleTicket; draft: string | null; onDraftUsed: () => void }) {
  const [mode, setMode] = useState<"public" | "internal">("public");
  const [body, setBody] = useState("");
  const [items, setItems] = useState<string[]>([]);
  const [itemInput, setItemInput] = useState("");
  const [showItems, setShowItems] = useState(false);
  const reply = useReply(t.id);
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (draft) {
      setMode("public");
      setBody(draft);
      onDraftUsed();
      ref.current?.focus();
    }
  }, [draft, onDraftUsed]);

  // "r" focuses the reply box.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (el.closest("input, textarea, [role=dialog]") || e.metaKey || e.ctrlKey) return;
      if (e.key === "r") {
        e.preventDefault();
        ref.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const send = (status?: string) => {
    if (!body.trim()) return;
    reply.mutate(
      { body, visibility: mode, status: status ?? null, action_items: mode === "public" ? items : [] },
      {
        onSuccess: () => {
          setBody("");
          setItems([]);
          setShowItems(false);
        },
      },
    );
  };
  if (t.status === "closed") {
    return <div className="border-t border-border px-5 py-4 text-center text-[13px] text-muted">This ticket is closed.</div>;
  }
  const isNote = mode === "internal";
  return (
    <div className="border-t border-border bg-bg px-4 pt-3 pb-4">
      <div className={cn("rounded-xl border shadow-soft transition-colors", isNote ? "border-dashed border-warning/50 bg-warning-soft/30" : "border-border bg-surface focus-within:border-border-strong")}>
        <div className="flex items-center gap-1 border-b border-border/70 px-2 pt-1.5">
          {(["public", "internal"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={cn(
                "-mb-px flex items-center gap-1.5 border-b-2 px-2.5 pb-2 text-[12.5px] font-medium",
                mode === m ? (m === "public" ? "border-primary text-text" : "border-warning text-text") : "border-transparent text-muted hover:text-text",
              )}
            >
              {m === "public" ? <MessageSquare className="size-3.5" /> : <Lock className="size-3.5" />}
              {m === "public" ? "Reply to player" : "Internal note"}
            </button>
          ))}
        </div>
        <textarea
          ref={ref}
          value={body}
          onChange={(e) => setBody(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && (e.metaKey || e.ctrlKey) && send()}
          rows={3}
          placeholder={isNote ? "Only your team will see this…" : "Write a reply, or use an AI draft from the copilot →"}
          className="block max-h-72 min-h-20 w-full resize-y bg-transparent px-3.5 py-3 text-[14px] leading-relaxed placeholder:text-faint focus:outline-none"
        />
        {mode === "public" && showItems && (
          <div className="border-t border-border/70 px-3.5 py-2.5">
            <p className="mb-1.5 text-[12px] font-medium text-muted">Ask the player to… (shown as a checklist)</p>
            <div className="flex flex-wrap gap-1.5">
              {items.map((it, i) => (
                <span key={i} className="inline-flex items-center gap-1 rounded-full bg-dawn-soft px-2.5 py-1 text-[12.5px]">
                  {it}
                  <button onClick={() => setItems(items.filter((_, j) => j !== i))} aria-label="Remove">
                    <X className="size-3" />
                  </button>
                </span>
              ))}
              <input
                value={itemInput}
                onChange={(e) => setItemInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && itemInput.trim()) {
                    e.preventDefault();
                    setItems([...items, itemInput.trim()]);
                    setItemInput("");
                  }
                }}
                placeholder="e.g. Attach NetLog.txt, then Enter"
                className="min-w-48 flex-1 bg-transparent text-[13px] placeholder:text-faint focus:outline-none"
              />
            </div>
          </div>
        )}
        <div className="flex items-center gap-2 px-2.5 pb-2.5">
          {mode === "public" && (
            <Button variant="ghost" size="sm" onClick={() => setShowItems((s) => !s)} className={cn(showItems && "text-text")}>
              <ListPlus /> Request items{items.length ? ` (${items.length})` : ""}
            </Button>
          )}
          <span className="ml-auto hidden items-center gap-1 text-[11.5px] text-faint sm:flex">
            <Kbd>⌘</Kbd>
            <Kbd>↵</Kbd>
          </span>
          {isNote ? (
            <Button size="sm" variant="secondary" onClick={() => send()} disabled={!body.trim() || reply.isPending}>
              {reply.isPending ? <Loader2 className="animate-spin" /> : <Lock />} Add note
            </Button>
          ) : (
            <div className="flex">
              <Button size="sm" className="rounded-r-none" onClick={() => send()} disabled={!body.trim() || reply.isPending}>
                {reply.isPending ? <Loader2 className="animate-spin" /> : <MessageSquare />} Send · Pending
              </Button>
              <Menu>
                <MenuTrigger asChild>
                  <Button size="sm" className="rounded-l-none border-l border-primary-fg/20 px-2" disabled={!body.trim() || reply.isPending} aria-label="More send options">
                    <ChevronDown />
                  </Button>
                </MenuTrigger>
                <MenuContent align="end">
                  <MenuItem onSelect={() => send("pending")}>Send and wait for player</MenuItem>
                  <MenuItem onSelect={() => send("solved")}>Send and mark solved</MenuItem>
                  <MenuItem onSelect={() => send("on_hold")}>Send and put on hold</MenuItem>
                  <MenuItem onSelect={() => send("open")}>Send and keep open</MenuItem>
                </MenuContent>
              </Menu>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Workspace ─────────────────────────────────────────────────────────────────── */

export function TicketWorkspace({ id }: { id: number }) {
  const ticket = useConsoleTicket(id);
  const [tab, setTab] = useState<"conversation" | "activity">("conversation");
  const [draft, setDraft] = useState<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const t = ticket.data;
  const lastMsg = t?.messages.at(-1)?.id;

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight });
  }, [lastMsg, tab]);

  if (!t) {
    return (
      <div className="space-y-3 p-6">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-7 w-2/3" />
        <Skeleton className="mt-6 h-32 rounded-xl" />
        <Skeleton className="h-24 rounded-xl" />
      </div>
    );
  }
  const openActions = t.actions.filter((a) => !a.done);

  return (
    <div className="flex h-full min-h-0">
      <div className="flex min-w-0 flex-1 flex-col">
        <Header t={t} />
        <div className="flex gap-4 border-b border-border px-5">
          {(["conversation", "activity"] as const).map((k) => (
            <button
              key={k}
              onClick={() => setTab(k)}
              className={cn("-mb-px border-b-2 py-2.5 text-[13px] font-medium capitalize", tab === k ? "border-primary text-text" : "border-transparent text-muted hover:text-text")}
            >
              {k}
              {k === "activity" && <span className="ml-1.5 text-faint">{t.events.length}</span>}
            </button>
          ))}
        </div>
        <Banners t={t} />
        <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto">
          <div className="px-5 py-5">
            {tab === "conversation" ? (
              <div className="space-y-5">
                {t.messages.map((m) => (
                  <ConsoleMessage key={m.id} m={m} />
                ))}
                {openActions.length > 0 && (
                  <div className="rounded-xl border border-dawn/40 bg-dawn-soft/40 px-4 py-3 text-[13px]">
                    <p className="font-medium">Waiting on the player for:</p>
                    <ul className="mt-1 list-disc pl-5 text-muted">
                      {openActions.map((a) => (
                        <li key={a.id}>{a.text}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {t.ai_state === "working" && (
                  <div className="flex items-center gap-2 text-[13px] text-muted">
                    <Loader2 className="size-4 animate-spin text-primary" /> The AI is answering the player…
                  </div>
                )}
              </div>
            ) : (
              <Activity t={t} />
            )}
          </div>
        </div>
        <Composer t={t} draft={draft} onDraftUsed={() => setDraft(null)} />
      </div>
      <Copilot t={t} onUseDraft={setDraft} />
    </div>
  );
}
