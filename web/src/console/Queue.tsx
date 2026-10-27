import { ArrowLeft, Inbox, Search, Sparkles, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { Badge, Kbd } from "@/components/ui/badge";
import { Avatar, Menu, MenuContent, MenuItem, MenuTrigger, Skeleton, Tooltip } from "@/components/ui/misc";
import { useDebounced } from "@/hooks/theme";
import type { ConsoleTicketRow } from "@/lib/api";
import { HANDOFF_REASON, PRIORITY, STAFF_STATUS, topicLabel } from "@/lib/status";
import { cn, shortAge } from "@/lib/utils";
import { useQueue, VIEWS } from "./hooks";
import { TicketWorkspace } from "./TicketWorkspace";

const PRIORITY_DOT: Record<string, string> = {
  urgent: "bg-danger",
  high: "bg-warning",
  normal: "bg-faint/50",
  low: "bg-faint/25",
};

function Row({ t, selected, onSelect }: { t: ConsoleTicketRow; selected: boolean; onSelect: () => void }) {
  const ref = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (selected) ref.current?.scrollIntoView({ block: "nearest" });
  }, [selected]);
  const status = STAFF_STATUS[t.status];
  return (
    <button
      ref={ref}
      onClick={onSelect}
      aria-current={selected}
      className={cn(
        "relative block w-full border-b border-border px-4 py-3 text-left transition-colors",
        selected ? "bg-primary-soft/60" : "hover:bg-surface-2/60",
      )}
    >
      {selected && <span className="absolute inset-y-0 left-0 w-0.5 bg-primary" />}
      <div className="flex items-center gap-2">
        <Tooltip label={`${PRIORITY[t.priority]?.label ?? t.priority} priority`}>
          <span className={cn("size-2 shrink-0 rounded-full", PRIORITY_DOT[t.priority])} />
        </Tooltip>
        <span className="truncate text-[13px] font-medium">{t.requester_name || t.requester_email}</span>
        <span className="ml-auto shrink-0 text-[11.5px] text-faint tabular-nums">{shortAge(t.created_at)}</span>
      </div>
      <p className="mt-1 truncate text-[13.5px] text-text">{t.subject}</p>
      <p className="mt-0.5 truncate text-[12.5px] text-muted">{t.last_message_preview}</p>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <span className="text-[11.5px] text-faint tabular-nums">{t.ref}</span>
        {status && t.status !== "open" && <Badge tone={status.tone}>{status.label}</Badge>}
        {t.escalated && <Badge tone="red">Escalated</Badge>}
        {!t.escalated && t.handoff_reason && t.status === "open" && <Badge tone="blue">{HANDOFF_REASON[t.handoff_reason] ?? t.handoff_reason}</Badge>}
        {t.needs_review && (
          <Badge tone="violet">
            <Sparkles className="size-3" /> Review
          </Badge>
        )}
        {t.ai_state === "working" && <Badge tone="violet">AI working…</Badge>}
        {t.open_actions > 0 && <Badge tone="amber">{t.open_actions} waiting on player</Badge>}
        {t.topic && <span className="text-[11.5px] text-faint">· {topicLabel(t.topic)}</span>}
        {t.assignee_name && <Avatar name={t.assignee_name} className="ml-auto size-5 text-[9px]" />}
      </div>
    </button>
  );
}

export function Queue() {
  const [params, setParams] = useSearchParams();
  const view = params.get("view") ?? "attention";
  const selectedId = params.get("t") ? Number(params.get("t")) : null;
  const [search, setSearch] = useState("");
  const [priority, setPriority] = useState("");
  const q = useDebounced(search, 250);
  const queue = useQueue(view, q, priority);
  const tickets = useMemo(() => queue.data?.tickets ?? [], [queue.data]);
  const viewMeta = VIEWS.find((v) => v.key === view) ?? VIEWS[0];

  const select = (id: number | null) =>
    setParams(
      (p) => {
        if (id === null) p.delete("t");
        else p.set("t", String(id));
        return p;
      },
      { replace: true },
    );

  // Open the first ticket by default on wide screens.
  useEffect(() => {
    if (selectedId === null && tickets.length && window.matchMedia("(min-width: 1024px)").matches) select(tickets[0].id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tickets, selectedId]);

  // j / k to move through the queue (ignored while typing).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (el.closest("input, textarea, [contenteditable], [role=dialog]") || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key !== "j" && e.key !== "k") return;
      const idx = tickets.findIndex((t) => t.id === selectedId);
      const next = tickets[Math.min(tickets.length - 1, Math.max(0, idx + (e.key === "j" ? 1 : -1)))];
      if (next) select(next.id);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tickets, selectedId]);

  return (
    <div className="flex min-h-0 flex-1">
      <section className={cn("flex w-full flex-col border-r border-border lg:w-[380px] lg:shrink-0", selectedId !== null && "hidden lg:flex")}>
        <header className="border-b border-border px-4 pt-3.5 pb-3">
          <div className="flex items-center justify-between">
            <h1 className="text-[15px] font-semibold tracking-tight">{viewMeta.label}</h1>
            <span className="text-[12px] text-faint tabular-nums">{tickets.length}</span>
          </div>
          <div className="mt-2.5 flex gap-2">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-faint" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search ref, subject, email"
                className="h-8 w-full rounded-lg border border-border bg-surface pr-7 pl-8 text-[13px] placeholder:text-faint focus:border-primary focus:outline-none"
              />
              {search && (
                <button onClick={() => setSearch("")} className="absolute top-1/2 right-2 -translate-y-1/2 text-faint hover:text-text" aria-label="Clear search">
                  <X className="size-3.5" />
                </button>
              )}
            </div>
            <Menu>
              <MenuTrigger asChild>
                <button className="h-8 rounded-lg border border-border bg-surface px-2.5 text-[12.5px] text-muted hover:text-text">
                  {priority ? PRIORITY[priority].label : "Any priority"}
                </button>
              </MenuTrigger>
              <MenuContent align="end">
                <MenuItem onSelect={() => setPriority("")}>Any priority</MenuItem>
                {Object.entries(PRIORITY).map(([k, v]) => (
                  <MenuItem key={k} onSelect={() => setPriority(k)}>
                    <span className={cn("size-2 rounded-full", PRIORITY_DOT[k])} /> {v.label}
                  </MenuItem>
                ))}
              </MenuContent>
            </Menu>
          </div>
          {/* Views on small screens, where the sidebar is hidden */}
          <div className="-mx-1 mt-2.5 flex gap-1 overflow-x-auto md:hidden">
            {VIEWS.map((v) => (
              <button
                key={v.key}
                onClick={() => setParams({ view: v.key })}
                className={cn("shrink-0 rounded-full px-2.5 py-1 text-[12px]", v.key === view ? "bg-primary-soft text-primary" : "text-muted")}
              >
                {v.label}
              </button>
            ))}
          </div>
        </header>
        <div className="flex-1 overflow-y-auto">
          {queue.isLoading ? (
            Array.from({ length: 6 }, (_, i) => (
              <div key={i} className="space-y-2 border-b border-border p-4">
                <Skeleton className="h-3.5 w-1/3" />
                <Skeleton className="h-3.5 w-4/5" />
                <Skeleton className="h-3 w-2/3" />
              </div>
            ))
          ) : tickets.length === 0 ? (
            <div className="flex flex-col items-center px-6 py-16 text-center">
              <Inbox className="size-7 text-faint" />
              <p className="mt-3 text-sm font-medium">{q ? "No matches" : "All clear"}</p>
              <p className="mt-1 text-[13px] text-muted">{q ? "Try a different search." : "Nothing here right now. The AI is handling the rest."}</p>
            </div>
          ) : (
            tickets.map((t) => <Row key={t.id} t={t} selected={t.id === selectedId} onSelect={() => select(t.id)} />)
          )}
        </div>
        <footer className="hidden items-center gap-3 border-t border-border px-4 py-2 text-[11.5px] text-faint lg:flex">
          <span className="flex items-center gap-1">
            <Kbd>j</Kbd>
            <Kbd>k</Kbd> move
          </span>
          <span className="flex items-center gap-1">
            <Kbd>⌘</Kbd>
            <Kbd>K</Kbd> search
          </span>
        </footer>
      </section>

      <section className={cn("min-w-0 flex-1", selectedId === null && "hidden lg:block")}>
        {selectedId !== null ? (
          <>
            <button onClick={() => select(null)} className="flex items-center gap-1.5 px-4 pt-3 text-[13px] text-muted lg:hidden">
              <ArrowLeft className="size-4" /> Back to queue
            </button>
            <TicketWorkspace key={selectedId} id={selectedId} />
          </>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-faint">Select a ticket</div>
        )}
      </section>
    </div>
  );
}
