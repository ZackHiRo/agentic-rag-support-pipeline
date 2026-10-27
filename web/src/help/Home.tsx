import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, BookOpen, ChevronRight, Gamepad2, LifeBuoy, Loader2, Paperclip, Sparkles, UserRound, Wifi } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router";
import { toast } from "sonner";
import { Badge, Kbd } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/misc";
import { useMe } from "@/hooks/auth";
import { useDebounced } from "@/hooks/theme";
import { api, type ArticleSuggestion, type ArticleSummary, form, type Ticket } from "@/lib/api";
import { playerStatus } from "@/lib/status";
import { cn, timeAgo } from "@/lib/utils";
import { ArticleSheet } from "./ArticleSheet";
import { ACCEPT, AttachmentList, acceptFiles, filesFromClipboard } from "./Attachments";
import { useMyTickets } from "./HelpLayout";
import { SignInForm } from "./SignIn";

const PLATFORMS = ["PC", "PlayStation", "Xbox", "Switch"];
const DRAFT_KEY = "evd-draft";
const CATEGORY_ICON: Record<string, typeof Wifi> = { technical: Wifi, gameplay: Gamepad2, account: UserRound, general: LifeBuoy };
const EXAMPLES = ["Error 105 when I queue with friends", "I got a penalty after a server crash", "I can't get into my account"];

function loadDraft(): { text: string; platform: string } {
  try {
    return JSON.parse(sessionStorage.getItem(DRAFT_KEY) ?? "") as { text: string; platform: string };
  } catch {
    return { text: "", platform: "" };
  }
}

function saveDraft(text: string, platform: string) {
  try {
    if (text) sessionStorage.setItem(DRAFT_KEY, JSON.stringify({ text, platform }));
    else sessionStorage.removeItem(DRAFT_KEY);
  } catch {
    /* storage unavailable: the draft just won't survive a reload */
  }
}

function Composer() {
  const me = useMe();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [text, setText] = useState(() => loadDraft().text);
  const [platform, setPlatform] = useState(() => loadDraft().platform);
  const [files, setFiles] = useState<File[]>([]);
  const [step, setStep] = useState<"compose" | "signin">("compose");
  const [dragging, setDragging] = useState(false);
  const [openSlug, setOpenSlug] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => saveDraft(text, platform), [text, platform]);

  // Auto-grow the textarea with its content.
  useEffect(() => {
    const el = textRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 320)}px`;
  }, [text]);

  const q = useDebounced(text.trim(), 220);
  const suggestions = useQuery({
    queryKey: ["suggest", q],
    queryFn: () => api<ArticleSuggestion[]>(`/api/kb/suggest?q=${encodeURIComponent(q)}`),
    enabled: q.length >= 3,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
  const shown = q.length >= 3 ? (suggestions.data ?? []) : [];

  const create = useMutation({
    mutationFn: () =>
      api<Ticket>("/api/tickets", { method: "POST", body: form({ description: text.trim(), platform }, files) }),
    onSuccess: (t) => {
      saveDraft("", "");
      qc.invalidateQueries({ queryKey: ["my-tickets"] });
      qc.setQueryData(["ticket", t.ref], t);
      navigate(`/tickets/${t.ref}`);
    },
    onError: (e) => toast.error(e.message),
  });

  const canSend = (text.trim().length >= 3 || files.length > 0) && !create.isPending;
  const submit = () => {
    if (!canSend) return;
    if (!me.data) setStep("signin");
    else create.mutate();
  };

  const resetAfterDeflection = () => {
    setText("");
    setFiles([]);
    setOpenSlug(null);
  };

  return (
    <div className="relative">
      <div
        className={cn(
          "relative rounded-2xl border bg-surface shadow-lift transition-[border-color,box-shadow]",
          dragging ? "border-primary ring-4 ring-primary/15" : "border-border focus-within:border-border-strong",
        )}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          setFiles((f) => acceptFiles(f, e.dataTransfer.files));
        }}
      >
        <AnimatePresence mode="wait" initial={false}>
          {step === "compose" ? (
            <motion.div key="compose" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.15 }}>
              <label htmlFor="describe" className="sr-only">
                Describe your problem
              </label>
              <textarea
                id="describe"
                ref={textRef}
                value={text}
                onChange={(e) => setText(e.target.value)}
                onPaste={(e) => {
                  const pasted = filesFromClipboard(e);
                  if (pasted.length) {
                    e.preventDefault();
                    setFiles((f) => acceptFiles(f, pasted));
                  }
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
                }}
                rows={3}
                placeholder="Describe what's going on. For example: “Error 105 when I queue with my friend on PS5.”"
                className="block w-full resize-none bg-transparent px-5 pt-5 pb-2 text-[16px] leading-relaxed text-text placeholder:text-faint focus:outline-none"
              />
              <div className="px-5">
                <AttachmentList files={files} onChange={setFiles} />
              </div>
              <div className="flex flex-wrap items-center gap-2 px-3 pt-2 pb-3 sm:px-4">
                <div className="flex flex-wrap items-center gap-1.5" role="radiogroup" aria-label="Platform">
                  {PLATFORMS.map((p) => (
                    <button
                      key={p}
                      type="button"
                      role="radio"
                      aria-checked={platform === p}
                      onClick={() => setPlatform(platform === p ? "" : p)}
                      className={cn(
                        "h-8 rounded-full border px-3 text-[13px] font-medium transition-colors",
                        platform === p
                          ? "border-primary bg-primary-soft text-primary"
                          : "border-border text-muted hover:border-border-strong hover:text-text",
                      )}
                    >
                      {p}
                    </button>
                  ))}
                </div>
                <div className="ml-auto flex items-center gap-1.5">
                  <input
                    ref={fileInput}
                    type="file"
                    multiple
                    accept={ACCEPT}
                    className="hidden"
                    onChange={(e) => {
                      if (e.target.files) setFiles((f) => acceptFiles(f, e.target.files!));
                      e.target.value = "";
                    }}
                  />
                  <Button variant="ghost" size="icon" onClick={() => fileInput.current?.click()} aria-label="Attach screenshots or logs">
                    <Paperclip />
                  </Button>
                  <Button variant="dawn" onClick={submit} disabled={!canSend}>
                    {create.isPending ? <Loader2 className="animate-spin" /> : <Sparkles />}
                    Get help
                  </Button>
                </div>
              </div>
            </motion.div>
          ) : (
            <motion.div key="signin" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="p-5">
              <div className="mb-4 flex items-start justify-between gap-4">
                <div>
                  <h2 className="font-semibold tracking-tight">Where should we send updates?</h2>
                  <p className="mt-0.5 text-sm text-muted">So you can come back to this ticket and see our replies.</p>
                </div>
                <Button variant="ghost" size="sm" onClick={() => setStep("compose")}>
                  Edit message
                </Button>
              </div>
              <SignInForm
                compact
                submitLabel="Send to support"
                onSignedIn={() => {
                  setStep("compose");
                  create.mutate();
                }}
              />
            </motion.div>
          )}
        </AnimatePresence>
        {dragging && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center rounded-2xl bg-primary-soft/70 text-sm font-medium text-primary">
            Drop screenshots or logs to attach
          </div>
        )}
      </div>

      <div className={cn("mt-2 flex items-center justify-between px-1 text-[12.5px] text-faint", step !== "compose" && "invisible")}>
        <span>Screenshots help: drop, paste or attach them.</span>
        <span className="hidden items-center gap-1 sm:flex">
          <Kbd>⌘</Kbd>
          <Kbd>Enter</Kbd> to send
        </span>
      </div>

      {step === "compose" && !text && (
        <div className="mt-4 flex flex-wrap justify-center gap-1">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              onClick={() => {
                setText(ex);
                textRef.current?.focus();
              }}
              className="inline-flex items-center gap-1 rounded-full px-3 py-1.5 text-[13px] text-muted transition hover:bg-surface-2 hover:text-text"
            >
              {ex} <ArrowRight className="size-3.5" />
            </button>
          ))}
        </div>
      )}

      {/* Live article suggestions: often the answer is already written. */}
      <AnimatePresence>
        {step === "compose" && shown.length > 0 && (
          <motion.section
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.18 }}
            className="mt-5"
            aria-live="polite"
          >
            <h2 className="mb-2 flex items-center gap-2 px-1 text-[13px] font-medium text-muted">
              <BookOpen className="size-4" /> These articles might already have your answer
            </h2>
            <ul className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-surface">
              {shown.slice(0, 3).map((a) => (
                <li key={a.slug}>
                  <button
                    onClick={() => setOpenSlug(a.slug)}
                    className="group flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-surface-2 focus-visible:bg-surface-2 focus-visible:outline-none"
                  >
                    <ArticleIcon category={a.category} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">{a.title}</span>
                      <span className="block truncate text-[13px] text-muted">{a.summary}</span>
                    </span>
                    <ChevronRight className="size-4 text-faint transition group-hover:translate-x-0.5 group-hover:text-muted" />
                  </button>
                </li>
              ))}
            </ul>
          </motion.section>
        )}
      </AnimatePresence>

      <ArticleSheet slug={openSlug} onOpenChange={(o) => !o && setOpenSlug(null)} query={text} onSolved={resetAfterDeflection} />
    </div>
  );
}

function ArticleIcon({ category }: { category: string }) {
  const Icon = CATEGORY_ICON[category] ?? BookOpen;
  return (
    <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-surface-2 text-muted">
      <Icon className="size-4.5" />
    </span>
  );
}

function RecentTickets() {
  const me = useMe();
  const tickets = useMyTickets(!!me.data);
  const active = (tickets.data ?? []).filter((t) => !["solved", "closed"].includes(t.status)).slice(0, 3);
  if (!active.length) return null;
  return (
    <section className="mx-auto mt-14 max-w-2xl px-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold">Your open tickets</h2>
        <Link to="/tickets" className="text-[13px] text-muted hover:text-text">
          View all
        </Link>
      </div>
      <ul className="space-y-2">
        {active.map((t) => {
          const s = playerStatus(t);
          return (
            <li key={t.id}>
              <Link
                to={`/tickets/${t.ref}`}
                className="flex items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3 shadow-soft transition hover:border-border-strong"
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{t.subject}</span>
                  <span className="text-[12.5px] text-faint">
                    {t.ref} · updated {timeAgo(t.updated_at)}
                  </span>
                </span>
                <Badge tone={s.tone} dot>
                  {s.label}
                </Badge>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function PopularArticles() {
  const articles = useQuery({ queryKey: ["articles"], queryFn: () => api<ArticleSummary[]>("/api/kb/articles"), staleTime: 5 * 60_000 });
  const [openSlug, setOpenSlug] = useState<string | null>(null);
  return (
    <section className="mx-auto mt-16 max-w-5xl px-4 sm:px-6">
      <h2 className="mb-4 text-sm font-semibold">Browse help articles</h2>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {articles.isLoading &&
          Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-24 rounded-xl" />)}
        {articles.data?.map((a) => (
          <button
            key={a.slug}
            onClick={() => setOpenSlug(a.slug)}
            className="group flex flex-col items-start gap-2 rounded-xl border border-border bg-surface p-4 text-left shadow-soft transition hover:-translate-y-0.5 hover:border-border-strong hover:shadow-lift"
          >
            <span className="flex w-full items-center gap-3">
              <ArticleIcon category={a.category} />
              <span className="text-sm leading-snug font-medium">{a.title}</span>
            </span>
            <span className="line-clamp-2 text-[13px] text-muted">{a.summary}</span>
          </button>
        ))}
      </div>
      <ArticleSheet slug={openSlug} onOpenChange={(o) => !o && setOpenSlug(null)} />
    </section>
  );
}

export function Home() {
  return (
    <div className="pb-20">
      <section className="relative overflow-hidden">
        {/* Dawn horizon glow */}
        <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[520px]">
          <div className="absolute inset-0 bg-[radial-gradient(55%_60%_at_50%_0%,color-mix(in_oklch,var(--primary)_14%,transparent),transparent_70%)]" />
          <div className="absolute inset-x-0 top-[180px] h-[340px] bg-[radial-gradient(45%_55%_at_50%_100%,color-mix(in_oklch,var(--dawn)_22%,transparent),transparent_70%)]" />
        </div>
        <div className="mx-auto max-w-2xl px-4 pt-14 sm:pt-20">
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="mb-8 text-center">
            <p className="mb-4 inline-flex items-center gap-1.5 rounded-full border border-border bg-surface/70 px-3 py-1 text-[12.5px] text-muted backdrop-blur">
              <span className="size-1.5 rounded-full bg-success" /> Answers in under a minute, 24/7
            </p>
            <h1 className="text-[34px] leading-tight font-semibold tracking-[-0.03em] text-balance sm:text-5xl">
              How can we <span className="dawn-text-gradient">help</span>?
            </h1>
            <p className="mx-auto mt-3 max-w-lg text-[15px] text-pretty text-muted">
              Tell us what's happening. Our AI assistant answers right away using our help articles, and our team is
              here whenever you need a person.
            </p>
          </motion.div>
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45, delay: 0.05 }}>
            <Composer />
          </motion.div>
        </div>
      </section>
      <RecentTickets />
      <PopularArticles />
    </div>
  );
}
