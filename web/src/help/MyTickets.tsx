import { ChevronRight, Inbox, Plus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/misc";
import { useMe } from "@/hooks/auth";
import { playerStatus } from "@/lib/status";
import { cn, timeAgo } from "@/lib/utils";
import { useMyTickets } from "./HelpLayout";
import { SignInForm } from "./SignIn";

export function MyTickets() {
  const me = useMe();
  const tickets = useMyTickets(!!me.data);
  const [tab, setTab] = useState<"active" | "resolved">("active");

  if (me.isSuccess && !me.data) {
    return (
      <div className="mx-auto max-w-md px-4 py-16">
        <h1 className="mb-1 text-xl font-semibold tracking-tight">Sign in to see your tickets</h1>
        <p className="mb-6 text-sm text-muted">We'll find every request you've sent with this email.</p>
        <SignInForm onSignedIn={() => {}} />
      </div>
    );
  }

  const all = tickets.data ?? [];
  const isResolved = (s: string) => s === "solved" || s === "closed";
  const list = all.filter((t) => (tab === "resolved") === isResolved(t.status));
  const counts = { active: all.filter((t) => !isResolved(t.status)).length, resolved: all.filter((t) => isResolved(t.status)).length };

  return (
    <div className="mx-auto max-w-3xl px-4 pt-10 pb-16">
      <div className="mb-6 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">My tickets</h1>
          <p className="mt-1 text-sm text-muted">Everything you've asked us, in one place.</p>
        </div>
        <Button asChild variant="dawn">
          <Link to="/">
            <Plus /> New request
          </Link>
        </Button>
      </div>

      <div className="mb-4 inline-flex rounded-lg bg-surface-2 p-1" role="tablist">
        {(["active", "resolved"] as const).map((k) => (
          <button
            key={k}
            role="tab"
            aria-selected={tab === k}
            onClick={() => setTab(k)}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm font-medium capitalize transition",
              tab === k ? "bg-surface text-text shadow-soft" : "text-muted hover:text-text",
            )}
          >
            {k} <span className="ml-1 text-faint">{counts[k]}</span>
          </button>
        ))}
      </div>

      {tickets.isLoading ? (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-20 rounded-xl" />
          ))}
        </div>
      ) : list.length === 0 ? (
        <div className="flex flex-col items-center rounded-2xl border border-dashed border-border py-14 text-center">
          <Inbox className="size-8 text-faint" />
          <p className="mt-3 font-medium">{tab === "active" ? "No open tickets" : "Nothing resolved yet"}</p>
          <p className="mt-1 text-sm text-muted">{tab === "active" ? "If something comes up, we're one message away." : "Solved tickets will show up here."}</p>
        </div>
      ) : (
        <ul className="space-y-2">
          {list.map((t) => {
            const s = playerStatus(t);
            return (
              <li key={t.id}>
                <Link
                  to={`/tickets/${t.ref}`}
                  className="group flex items-center gap-4 rounded-xl border border-border bg-surface px-4 py-3.5 shadow-soft transition hover:border-border-strong hover:shadow-lift"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate font-medium">{t.subject}</span>
                    </div>
                    <p className="mt-0.5 truncate text-[13px] text-muted">{t.last_message_preview}</p>
                    <p className="mt-1 text-[12px] text-faint">
                      {t.ref} · updated {timeAgo(t.updated_at)}
                    </p>
                  </div>
                  <div className="flex flex-col items-end gap-1.5">
                    <Badge tone={s.tone} dot>
                      {s.label}
                    </Badge>
                    {t.open_actions > 0 && <span className="text-[12px] text-dawn-text">{t.open_actions} to do</span>}
                  </div>
                  <ChevronRight className="size-4 text-faint transition group-hover:translate-x-0.5" />
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
