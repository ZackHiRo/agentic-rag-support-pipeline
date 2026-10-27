import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  BookOpen,
  Check,
  CheckCircle2,
  CircleDashed,
  FileText,
  HeartHandshake,
  Loader2,
  Paperclip,
  Phone,
  SendHorizontal,
  Sparkles,
  UserRoundCheck,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { Avatar, Prose, Skeleton } from "@/components/ui/misc";
import { DialogContent, DialogRoot, DialogTitle } from "@/components/ui/sheet";
import { useMe } from "@/hooks/auth";
import { type Action, ApiError, api, type Citation, form, type Message, type Ticket } from "@/lib/api";
import { useLiveEvents } from "@/lib/sse";
import { PLAYER_STAGES, playerStatus } from "@/lib/status";
import { cn, formatBytes, formatDateTime, timeAgo } from "@/lib/utils";
import { ArticleSheet } from "./ArticleSheet";
import { ACCEPT, AttachmentList, acceptFiles, filesFromClipboard } from "./Attachments";
import { SignInForm } from "./SignIn";

function useTicket(ref: string) {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["ticket", ref], queryFn: () => api<Ticket>(`/api/tickets/${ref}`) });
  useLiveEvents(query.data ? `/api/tickets/${ref}/stream` : null, () => {
    qc.invalidateQueries({ queryKey: ["ticket", ref] });
    qc.invalidateQueries({ queryKey: ["my-tickets"] });
  });
  return query;
}

function useTicketAction(ref: string) {
  const qc = useQueryClient();
  return (path: string, init: RequestInit & { json?: unknown } = {}) =>
    api<Ticket>(`/api/tickets/${ref}${path}`, { method: "POST", ...init }).then((t) => {
      qc.setQueryData(["ticket", ref], t);
      qc.invalidateQueries({ queryKey: ["my-tickets"] });
      return t;
    });
}

/* ── Live AI progress ─────────────────────────────────────────────────────── */

function AiProgress({ ticket }: { ticket: Ticket }) {
  const run = ticket.active_run;
  const reached = new Set(run?.stages.map((s) => s.key) ?? []);
  const steps = [...(reached.has("vision") ? [{ key: "vision", label: "Reading your screenshots" }] : []), ...PLAYER_STAGES];
  const lastKey = run?.stages.at(-1)?.key;
  const activeIdx = Math.max(0, steps.findIndex((s) => s.key === lastKey));
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const start = run?.started_at ? new Date(run.started_at).getTime() : Date.now();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 500);
    return () => clearInterval(id);
  }, [run?.started_at]);

  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="flex gap-3">
      <Avatar name="AI" kind="ai" />
      <div className="relative flex-1 overflow-hidden rounded-2xl rounded-tl-md border border-border bg-surface p-4 shadow-soft">
        <div className="absolute inset-x-0 top-0 h-0.5 overflow-hidden">
          <div className="dawn-gradient h-full w-1/3 animate-[indeterminate_1.4s_ease-in-out_infinite]" />
        </div>
        <div className="mb-3 flex items-center justify-between">
          <p className="text-sm font-medium">Working on your answer</p>
          <span className="text-xs text-faint tabular-nums">{elapsed}s</span>
        </div>
        <ol className="space-y-2.5">
          {steps.map((s, i) => {
            const done = i < activeIdx || (run?.status === "succeeded" && i <= activeIdx);
            const active = i === activeIdx && !done;
            return (
              <li key={s.key} className="flex items-center gap-2.5 text-sm">
                <span className="flex size-5 items-center justify-center">
                  {done ? (
                    <motion.span initial={{ scale: 0.4 }} animate={{ scale: 1 }} className="flex size-5 items-center justify-center rounded-full bg-success-soft text-success">
                      <Check className="size-3.5" strokeWidth={3} />
                    </motion.span>
                  ) : active ? (
                    <Loader2 className="size-4 animate-spin text-primary" />
                  ) : (
                    <CircleDashed className="size-4 text-faint" />
                  )}
                </span>
                <span className={cn(done ? "text-muted" : active ? "font-medium text-text" : "text-faint")}>{s.label}</span>
              </li>
            );
          })}
        </ol>
      </div>
    </motion.div>
  );
}

/* ── Messages ────────────────────────────────────────────────────────────── */

function CitationChips({ label, items, onOpen }: { label: string; items: Citation[]; onOpen: (slug: string) => void }) {
  if (!items.length) return null;
  return (
    <div className="mt-3 flex flex-wrap items-center gap-1.5">
      <span className="text-[12px] text-faint">{label}</span>
      {items.map((c) => (
        <button
          key={c.slug}
          onClick={() => onOpen(c.slug)}
          className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-border bg-surface-2 px-2.5 py-1 text-[12.5px] text-text transition hover:border-border-strong hover:bg-surface-3"
        >
          <BookOpen className="size-3.5 shrink-0 text-dawn-text" />
          <span className="truncate">{c.title}</span>
        </button>
      ))}
    </div>
  );
}

function CrisisCard() {
  return (
    <div className="mt-3 rounded-xl border border-danger/30 bg-danger-soft p-4 text-sm">
      <p className="flex items-center gap-2 font-semibold text-danger">
        <HeartHandshake className="size-4" /> You don't have to go through this alone
      </p>
      <ul className="mt-2 space-y-1.5 text-text">
        <li className="flex gap-2">
          <Phone className="mt-0.5 size-3.5 shrink-0 text-muted" />
          If you're in immediate danger, call your local emergency number now.
        </li>
        <li className="flex gap-2">
          <Phone className="mt-0.5 size-3.5 shrink-0 text-muted" />
          <span>
            In the US, call or text <strong>988</strong>. Elsewhere, find a free, confidential helpline at{" "}
            <a href="https://findahelpline.com" target="_blank" rel="noreferrer" className="font-medium underline">
              findahelpline.com
            </a>
            .
          </span>
        </li>
      </ul>
    </div>
  );
}

function Attachments({ m }: { m: Message }) {
  if (!m.attachments.length) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-2">
      {m.attachments.map((a) =>
        a.mime.startsWith("image/") ? (
          <a key={a.id} href={a.url} target="_blank" rel="noreferrer" className="overflow-hidden rounded-lg border border-border">
            <img src={a.url} alt={a.filename} className="h-24 max-w-48 object-cover" loading="lazy" />
          </a>
        ) : (
          <a key={a.id} href={a.url} target="_blank" rel="noreferrer" className="flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-[13px]">
            <FileText className="size-4 text-muted" /> {a.filename} <span className="text-faint">{formatBytes(a.size)}</span>
          </a>
        ),
      )}
    </div>
  );
}

function MessageItem({ m, onOpenArticle }: { m: Message; onOpenArticle: (slug: string) => void }) {
  const time = <time title={formatDateTime(m.created_at)}>{timeAgo(m.created_at)}</time>;
  if (m.author_kind === "system") {
    return (
      <div className="flex items-start gap-2.5 rounded-xl bg-surface-2 px-4 py-3 text-[13.5px] text-muted">
        <UserRoundCheck className="mt-0.5 size-4 shrink-0 text-primary" />
        <div className="flex-1">
          {m.body}
          <span className="ml-2 text-[12px] text-faint">{time}</span>
        </div>
      </div>
    );
  }
  if (m.author_kind === "player") {
    return (
      <div className="flex flex-col items-end">
        <div className="max-w-[88%] rounded-2xl rounded-tr-md bg-primary-soft px-4 py-3 text-[14.5px] whitespace-pre-wrap text-text sm:max-w-[80%]">
          {m.body}
        </div>
        <Attachments m={m} />
        <span className="mt-1 mr-1 text-[12px] text-faint">You · {time}</span>
      </div>
    );
  }
  const isAi = m.author_kind === "ai";
  return (
    <div className="flex gap-3">
      <Avatar name={m.author_name} kind={m.author_kind} />
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex flex-wrap items-center gap-2 text-[13px]">
          <span className="font-medium">{m.author_name}</span>
          {isAi ? (
            <Badge tone="violet" className="h-5 gap-1">
              <Sparkles className="size-3" /> AI
            </Badge>
          ) : (
            <Badge tone="blue" className="h-5">
              Everdawn team
            </Badge>
          )}
          <span className="text-faint">{time}</span>
        </div>
        <div className="rounded-2xl rounded-tl-md border border-border bg-surface px-4 py-3.5 shadow-soft">
          <Prose breaks>{m.body}</Prose>
          {m.crisis_resources && <CrisisCard />}
          <CitationChips label="Sources" items={m.citations} onOpen={onOpenArticle} />
          <CitationChips label="Related" items={m.related} onOpen={onOpenArticle} />
        </div>
        <Attachments m={m} />
      </div>
    </div>
  );
}

/* ── Checklist ("waiting on you") ───────────────────────────────────────────── */

function ChecklistItem({ action, ticketRef }: { action: Action; ticketRef: string }) {
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const run = useTicketAction(ticketRef);
  const fileInput = useRef<HTMLInputElement>(null);

  if (action.done) {
    return (
      <li className="flex gap-3 py-3">
        <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-success" />
        <div className="min-w-0 text-sm">
          <p className="text-muted line-through decoration-faint">{action.text}</p>
          {action.response && <p className="mt-0.5 truncate text-text">{action.response}</p>}
        </div>
      </li>
    );
  }
  const submit = async () => {
    setBusy(true);
    try {
      await run(`/actions/${action.id}/complete`, { body: form({ response: text.trim() }, files) });
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <li className="py-3">
      <div className="flex gap-3">
        <span className="mt-0.5 size-5 shrink-0 rounded-full border-2 border-dawn" />
        <div className="min-w-0 flex-1 space-y-2">
          <p className="text-sm font-medium">{action.text}</p>
          <div className="flex gap-2">
            <Textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              onPaste={(e) => {
                const pasted = filesFromClipboard(e);
                if (pasted.length) {
                  e.preventDefault();
                  setFiles((f) => acceptFiles(f, pasted));
                }
              }}
              rows={1}
              placeholder="Your answer"
              className="min-h-10 py-2"
            />
            <input ref={fileInput} type="file" multiple accept={ACCEPT} className="hidden" onChange={(e) => e.target.files && setFiles((f) => acceptFiles(f, e.target.files!))} />
            <Button variant="secondary" size="icon" className="size-10 shrink-0" onClick={() => fileInput.current?.click()} aria-label="Attach a file">
              <Paperclip />
            </Button>
          </div>
          <AttachmentList files={files} onChange={setFiles} />
          <Button size="sm" onClick={submit} disabled={busy || (!text.trim() && !files.length)}>
            {busy ? <Loader2 className="animate-spin" /> : <Check />} Done
          </Button>
        </div>
      </div>
    </li>
  );
}

function Checklist({ ticket }: { ticket: Ticket }) {
  const open = ticket.actions.filter((a) => !a.done);
  if (!open.length) return null;
  const recent = ticket.actions.filter((a) => a.done).slice(-3);
  return (
    <motion.section initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="rounded-2xl border border-dawn/40 bg-dawn-soft/50 p-4 sm:p-5">
      <h2 className="font-semibold tracking-tight">We need a few things from you</h2>
      <p className="mt-0.5 text-sm text-muted">
        Once you've answered {open.length === 1 ? "this" : `all ${open.length}`}, we'll pick it straight back up.
      </p>
      <ul className="mt-2 divide-y divide-border/70">
        {[...recent, ...open].map((a) => (
          <ChecklistItem key={a.id} action={a} ticketRef={ticket.ref} />
        ))}
      </ul>
    </motion.section>
  );
}

/* ── Resolution, reply, rating ─────────────────────────────────────────────── */

function ResolutionBar({ ticket }: { ticket: Ticket }) {
  const run = useTicketAction(ticket.ref);
  const [askOpen, setAskOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState<"" | "fixed" | "human">("");
  const act = async (kind: "fixed" | "human") => {
    setBusy(kind);
    try {
      if (kind === "fixed") {
        await run("/resolve");
        toast.success("Great, we've marked this as solved.");
      } else {
        await run("/need-human", { json: { reason } });
        setAskOpen(false);
      }
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy("");
    }
  };
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      className="sticky bottom-3 z-10 flex flex-col gap-3 rounded-2xl border border-border bg-surface/95 p-3 pl-4 shadow-lift backdrop-blur sm:flex-row sm:items-center"
    >
      <p className="flex-1 text-sm font-medium">Did this solve your problem?</p>
      <div className="flex gap-2">
        <Button variant="secondary" className="flex-1 sm:flex-none" onClick={() => setAskOpen(true)} disabled={!!busy}>
          I still need help
        </Button>
        <Button className="flex-1 sm:flex-none" onClick={() => act("fixed")} disabled={!!busy}>
          {busy === "fixed" ? <Loader2 className="animate-spin" /> : <Check />} That fixed it
        </Button>
      </div>
      <DialogRoot open={askOpen} onOpenChange={setAskOpen}>
        <DialogContent aria-describedby={undefined} className="p-5">
          <DialogTitle className="text-lg font-semibold tracking-tight">Talk to a person</DialogTitle>
          <p className="mt-1 text-sm text-muted">A member of the Everdawn team will pick this up. Anything we should know first?</p>
          <Textarea className="mt-4" rows={3} placeholder="Optional: what's still not working?" value={reason} onChange={(e) => setReason(e.target.value)} autoFocus />
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setAskOpen(false)}>
              Cancel
            </Button>
            <Button onClick={() => act("human")} disabled={!!busy}>
              {busy === "human" ? <Loader2 className="animate-spin" /> : <UserRoundCheck />} Send to the team
            </Button>
          </div>
        </DialogContent>
      </DialogRoot>
    </motion.div>
  );
}

function ReplyBox({ ticket }: { ticket: Ticket }) {
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const fileInput = useRef<HTMLInputElement>(null);
  const run = useTicketAction(ticket.ref);
  const send = useMutation({
    mutationFn: () => run("/messages", { body: form({ body: text.trim() }, files) }),
    onSuccess: () => {
      setText("");
      setFiles([]);
    },
    onError: (e) => toast.error(e.message),
  });
  const working = ticket.ai_state === "working";
  const canSend = (text.trim() || files.length) && !working && !send.isPending;
  const hint = ticket.status === "solved" ? "Reply to reopen this ticket" : ticket.needs_human ? "Reply to the team" : "Reply, or add more details";
  return (
    <div className="rounded-2xl border border-border bg-surface shadow-soft focus-within:border-border-strong">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onPaste={(e) => {
          const pasted = filesFromClipboard(e);
          if (pasted.length) {
            e.preventDefault();
            setFiles((f) => acceptFiles(f, pasted));
          }
        }}
        onKeyDown={(e) => e.key === "Enter" && (e.metaKey || e.ctrlKey) && canSend && send.mutate()}
        disabled={working}
        rows={2}
        placeholder={working ? "Hang on, we're still working on your last message…" : hint}
        className="block w-full resize-none bg-transparent px-4 pt-3.5 pb-1 text-[14.5px] placeholder:text-faint focus:outline-none disabled:opacity-60"
      />
      <div className="px-4">
        <AttachmentList files={files} onChange={setFiles} />
      </div>
      <div className="flex items-center justify-end gap-1.5 p-2">
        <input ref={fileInput} type="file" multiple accept={ACCEPT} className="hidden" onChange={(e) => e.target.files && setFiles((f) => acceptFiles(f, e.target.files!))} />
        <Button variant="ghost" size="icon-sm" onClick={() => fileInput.current?.click()} aria-label="Attach files" disabled={working}>
          <Paperclip />
        </Button>
        <Button size="sm" onClick={() => send.mutate()} disabled={!canSend}>
          {send.isPending ? <Loader2 className="animate-spin" /> : <SendHorizontal />} Send
        </Button>
      </div>
    </div>
  );
}

function CsatCard({ ticket }: { ticket: Ticket }) {
  const run = useTicketAction(ticket.ref);
  const [hover, setHover] = useState(0);
  if (ticket.csat) {
    return <p className="text-center text-sm text-muted">Thanks for rating us {ticket.csat}/5. It helps us improve.</p>;
  }
  const labels = ["Terrible", "Bad", "Okay", "Good", "Great"];
  return (
    <div className="rounded-2xl border border-border bg-surface p-5 text-center shadow-soft">
      <p className="font-medium">How did we do?</p>
      <div className="mt-3 flex justify-center gap-1.5" onMouseLeave={() => setHover(0)}>
        {labels.map((l, i) => (
          <button
            key={l}
            onMouseEnter={() => setHover(i + 1)}
            onFocus={() => setHover(i + 1)}
            onClick={() => run("/csat", { json: { rating: i + 1 } }).catch((e) => toast.error(e.message))}
            className={cn(
              "flex size-11 items-center justify-center rounded-xl border text-lg transition",
              hover > i ? "border-dawn bg-dawn-soft scale-105" : "border-border hover:border-border-strong",
            )}
            aria-label={`${i + 1} – ${l}`}
          >
            {["😣", "🙁", "😐", "🙂", "🤩"][i]}
          </button>
        ))}
      </div>
      <p className="mt-2 h-4 text-xs text-faint">{hover ? labels[hover - 1] : ""}</p>
    </div>
  );
}

function StatusLine({ ticket }: { ticket: Ticket }) {
  const open = ticket.actions.filter((a) => !a.done).length;
  let text = "";
  if (ticket.ai_state === "working") text = "Our AI assistant is on it. This usually takes under a minute.";
  else if (ticket.status === "pending" && open) text = "We need a few things from you before we can continue.";
  else if (ticket.status === "pending") text = "Here's our answer. Let us know if it worked.";
  else if (ticket.needs_human && ["open", "on_hold"].includes(ticket.status))
    text = "A member of our team has your ticket. We'll reply right here.";
  else if (ticket.status === "solved") text = "Solved. Reply within a few days if anything comes back.";
  else if (ticket.status === "closed") text = "This ticket is closed.";
  return <p className="mt-1 text-sm text-muted">{text}</p>;
}

/* ── Page ───────────────────────────────────────────────────────────────────── */

export function TicketPage() {
  const { ref = "" } = useParams();
  const me = useMe();
  const ticket = useTicket(ref);
  const [openSlug, setOpenSlug] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const t = ticket.data;
  const lastId = t?.messages.at(-1)?.id;
  const working = t?.ai_state === "working";

  useEffect(() => {
    if (lastId || working) bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [lastId, working]);

  if (me.isSuccess && !me.data) {
    return (
      <div className="mx-auto max-w-md px-4 py-16">
        <h1 className="mb-1 text-xl font-semibold tracking-tight">Sign in to view this ticket</h1>
        <p className="mb-6 text-sm text-muted">Use the email you contacted us with.</p>
        <SignInForm onSignedIn={() => ticket.refetch()} />
      </div>
    );
  }
  if (ticket.error instanceof ApiError && ticket.error.status === 404) {
    return (
      <div className="mx-auto max-w-md px-4 py-20 text-center">
        <h1 className="text-xl font-semibold">Ticket not found</h1>
        <p className="mt-2 text-sm text-muted">It may belong to a different account.</p>
        <Button asChild variant="secondary" className="mt-6">
          <Link to="/tickets">Back to my tickets</Link>
        </Button>
      </div>
    );
  }
  if (!t) {
    return (
      <div className="mx-auto max-w-3xl space-y-4 px-4 py-10">
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="h-24 w-4/5 rounded-2xl" />
        <Skeleton className="h-40 rounded-2xl" />
      </div>
    );
  }

  const status = playerStatus(t);
  const last = t.messages.at(-1);
  const showResolution =
    t.status === "pending" && !working && !t.actions.some((a) => !a.done) && (last?.author_kind === "ai" || last?.author_kind === "agent");

  return (
    <div className="mx-auto max-w-3xl px-4 pt-6 pb-10 sm:pt-10">
      <Link to="/tickets" className="mb-5 inline-flex items-center gap-1.5 text-[13px] text-muted hover:text-text">
        <ArrowLeft className="size-4" /> My tickets
      </Link>
      <header className="mb-8">
        <div className="mb-2 flex flex-wrap items-center gap-2 text-[13px] text-faint">
          <Badge tone={status.tone} dot>
            {status.label}
          </Badge>
          <span>{t.ref}</span>
          <span>·</span>
          <span>Opened {timeAgo(t.created_at)}</span>
        </div>
        <h1 className="text-2xl font-semibold tracking-tight text-balance">{t.subject}</h1>
        <StatusLine ticket={t} />
      </header>

      <div className="space-y-6">
        {t.messages.map((m) => (
          <motion.div key={m.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
            <MessageItem m={m} onOpenArticle={setOpenSlug} />
          </motion.div>
        ))}
        <AnimatePresence>{working && <AiProgress key="progress" ticket={t} />}</AnimatePresence>
        <Checklist ticket={t} />
        {showResolution && <ResolutionBar ticket={t} />}
        {["solved", "closed"].includes(t.status) && <CsatCard ticket={t} />}
        {t.status === "closed" ? (
          <div className="rounded-2xl border border-dashed border-border p-6 text-center text-sm text-muted">
            This ticket is closed.{" "}
            <Link to="/" className="font-medium text-primary hover:underline">
              Start a new request
            </Link>
          </div>
        ) : (
          <ReplyBox ticket={t} />
        )}
        <div ref={bottom} />
      </div>
      <ArticleSheet slug={openSlug} onOpenChange={(o) => !o && setOpenSlug(null)} showFeedback={false} />
    </div>
  );
}
