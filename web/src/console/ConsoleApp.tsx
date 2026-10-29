import { Command } from "cmdk";
import {
  AlertTriangle,
  BarChart3,
  CircleDot,
  Clock,
  Inbox,
  LifeBuoy,
  LogOut,
  Moon,
  PauseCircle,
  Search,
  Sparkles,
  SquareCheck,
  UserRound,
} from "lucide-react";
import { lazy, Suspense, useEffect, useState } from "react";
import { Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate, useSearchParams } from "react-router";
import { LogoMark, ThemeToggle } from "@/components/brand";
import { Kbd } from "@/components/ui/badge";
import { Avatar, Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger } from "@/components/ui/misc";
import { DialogContent, DialogRoot, DialogTitle } from "@/components/ui/sheet";
import { useLogout, useMe } from "@/hooks/auth";
import { useTheme } from "@/hooks/theme";
import { cn } from "@/lib/utils";
import { useConsoleLive, useQueue, VIEWS } from "./hooks";
import { Login } from "./Login";
import { Queue } from "./Queue";

const Reports = lazy(() => import("./Reports"));

const VIEW_ICON: Record<string, typeof Inbox> = {
  attention: AlertTriangle,
  review: Sparkles,
  mine: UserRound,
  pending: Clock,
  on_hold: PauseCircle,
  new: CircleDot,
  solved: SquareCheck,
  all: Inbox,
};

function Sidebar() {
  const [params] = useSearchParams();
  const view = params.get("view") ?? "attention";
  const counts = useQueue(view, "", "").data?.counts ?? {};
  const me = useMe().data;
  const logout = useLogout();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  return (
    <aside className="hidden w-56 shrink-0 flex-col border-r border-border bg-surface-2/40 md:flex">
      <div className="flex h-14 items-center gap-2.5 px-4">
        <LogoMark className="size-6.5" />
        <span className="text-sm font-semibold tracking-tight">Support Console</span>
      </div>
      <nav className="flex-1 space-y-0.5 overflow-y-auto px-2 py-2">
        <p className="px-2.5 pt-2 pb-1.5 text-[11px] font-medium tracking-wide text-faint uppercase">Inbox</p>
        {VIEWS.map((v) => {
          const Icon = VIEW_ICON[v.key];
          const active = !pathname.includes("reports") && view === v.key;
          const n = counts[v.key];
          return (
            <Link
              key={v.key}
              to={`/console?view=${v.key}`}
              title={v.hint}
              className={cn(
                "flex h-8 items-center gap-2.5 rounded-lg px-2.5 text-[13px] transition-colors",
                active ? "bg-surface text-text shadow-soft" : "text-muted hover:bg-surface/60 hover:text-text",
              )}
            >
              <Icon className={cn("size-4", v.key === "attention" && n ? "text-danger" : "")} />
              <span className="flex-1">{v.label}</span>
              {n !== undefined && !["solved", "all"].includes(v.key) && (
                <span className={cn("text-[11.5px] tabular-nums", v.key === "attention" && n ? "font-semibold text-danger" : "text-faint")}>{n}</span>
              )}
            </Link>
          );
        })}
        <p className="px-2.5 pt-5 pb-1.5 text-[11px] font-medium tracking-wide text-faint uppercase">Insights</p>
        <NavLink
          to="/console/reports"
          className={({ isActive }) =>
            cn(
              "flex h-8 items-center gap-2.5 rounded-lg px-2.5 text-[13px] transition-colors",
              isActive ? "bg-surface text-text shadow-soft" : "text-muted hover:bg-surface/60 hover:text-text",
            )
          }
        >
          <BarChart3 className="size-4" /> Reporting
        </NavLink>
      </nav>
      <div className="flex items-center gap-1 border-t border-border p-2">
        <Menu>
          <MenuTrigger asChild>
            <button className="flex min-w-0 flex-1 items-center gap-2 rounded-lg p-1.5 text-left hover:bg-surface/60">
              <Avatar name={me?.display_name ?? "?"} className="size-7 text-[10px]" />
              <span className="min-w-0">
                <span className="block truncate text-[13px] font-medium">{me?.display_name}</span>
                <span className="block truncate text-[11px] text-faint capitalize">{me?.role}</span>
              </span>
            </button>
          </MenuTrigger>
          <MenuContent align="start" side="top">
            <MenuLabel>{me?.email}</MenuLabel>
            <MenuItem asChild>
              <Link to="/">
                <LifeBuoy /> Player help center
              </Link>
            </MenuItem>
            <MenuSeparator />
            <MenuItem onSelect={() => logout.mutate(undefined, { onSuccess: () => navigate("/console/login") })}>
              <LogOut /> Sign out
            </MenuItem>
          </MenuContent>
        </Menu>
        <ThemeToggle />
      </div>
    </aside>
  );
}

function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const navigate = useNavigate();
  const { toggle } = useTheme();
  const results = useQueue("all", q.length >= 2 ? q : "", "");
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const go = (to: string) => {
    setOpen(false);
    setQ("");
    navigate(to);
  };
  const item = "flex cursor-default items-center gap-2.5 rounded-lg px-3 py-2 text-sm data-[selected=true]:bg-surface-2 [&_svg]:size-4 [&_svg]:text-muted";
  return (
    <DialogRoot open={open} onOpenChange={setOpen}>
      <DialogContent aria-describedby={undefined}>
        <DialogTitle className="sr-only">Command palette</DialogTitle>
        <Command shouldFilter={false} className="flex flex-col">
          <div className="flex items-center gap-2 border-b border-border px-4">
            <Search className="size-4 text-faint" />
            <Command.Input value={q} onValueChange={setQ} placeholder="Search tickets by ref, subject or email…" className="h-12 flex-1 bg-transparent text-sm outline-none placeholder:text-faint" />
          </div>
          <Command.List className="max-h-[50vh] overflow-y-auto p-2">
            <Command.Empty className="px-3 py-6 text-center text-sm text-muted">No matches.</Command.Empty>
            {q.length >= 2 && (results.data?.tickets.length ?? 0) > 0 && (
              <Command.Group heading="Tickets" className="[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:text-faint">
                {results.data!.tickets.slice(0, 8).map((t) => (
                  <Command.Item key={t.id} value={`t-${t.id}`} onSelect={() => go(`/console?view=all&t=${t.id}`)} className={item}>
                    <Inbox />
                    <span className="text-faint tabular-nums">{t.ref}</span>
                    <span className="truncate">{t.subject}</span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}
            <Command.Group heading="Go to" className="[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:text-faint">
              {VIEWS.filter((v) => !q || v.label.toLowerCase().includes(q.toLowerCase())).map((v) => {
                const Icon = VIEW_ICON[v.key];
                return (
                  <Command.Item key={v.key} value={v.key} onSelect={() => go(`/console?view=${v.key}`)} className={item}>
                    <Icon /> {v.label}
                  </Command.Item>
                );
              })}
              {(!q || "reporting".includes(q.toLowerCase())) && (
                <Command.Item value="reports" onSelect={() => go("/console/reports")} className={item}>
                  <BarChart3 /> Reporting
                </Command.Item>
              )}
              {(!q || "theme dark light".includes(q.toLowerCase())) && (
                <Command.Item
                  value="theme"
                  onSelect={() => {
                    toggle();
                    setOpen(false);
                  }}
                  className={item}
                >
                  <Moon /> Toggle dark mode
                </Command.Item>
              )}
            </Command.Group>
          </Command.List>
          <div className="flex items-center gap-3 border-t border-border px-4 py-2 text-[11.5px] text-faint">
            <span className="flex items-center gap-1">
              <Kbd>↑</Kbd>
              <Kbd>↓</Kbd> navigate
            </span>
            <span className="flex items-center gap-1">
              <Kbd>↵</Kbd> open
            </span>
            <span className="ml-auto flex items-center gap-1">
              <Kbd>esc</Kbd> close
            </span>
          </div>
        </Command>
      </DialogContent>
    </DialogRoot>
  );
}

function StaffShell() {
  useConsoleLive();
  return (
    <div className="flex h-dvh overflow-hidden bg-bg text-text">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Routes>
          <Route index element={<Queue />} />
          <Route
            path="reports"
            element={
              <Suspense fallback={<div className="p-8 text-sm text-muted">Loading reports…</div>}>
                <Reports />
              </Suspense>
            }
          />
          <Route path="*" element={<Navigate to="/console" replace />} />
        </Routes>
      </div>
      <CommandPalette />
    </div>
  );
}

export default function ConsoleApp() {
  const me = useMe();
  return (
    <Routes>
      <Route path="login" element={<Login />} />
      <Route
        path="*"
        element={
          me.isLoading ? (
            <div className="h-dvh bg-bg" />
          ) : me.data && me.data.role !== "player" ? (
            <StaffShell />
          ) : (
            <Navigate to="/console/login" replace />
          )
        }
      />
    </Routes>
  );
}
