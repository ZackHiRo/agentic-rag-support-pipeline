import { useQuery } from "@tanstack/react-query";
import { LogOut, TicketCheck } from "lucide-react";
import { Link, NavLink, Outlet, ScrollRestoration } from "react-router";
import { Logo, ThemeToggle } from "@/components/brand";
import { Button } from "@/components/ui/button";
import { Avatar, Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger } from "@/components/ui/misc";
import { useLogout, useMe } from "@/hooks/auth";
import { api, type TicketSummary } from "@/lib/api";
import { cn } from "@/lib/utils";

export function useMyTickets(enabled: boolean) {
  return useQuery({
    queryKey: ["my-tickets"],
    queryFn: () => api<TicketSummary[]>("/api/tickets"),
    enabled,
  });
}

function NavItem({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <NavLink
      to={to}
      end
      className={({ isActive }) =>
        cn(
          "relative flex h-9 items-center gap-2 rounded-lg px-3 text-sm font-medium transition-colors",
          isActive ? "text-text" : "text-muted hover:text-text",
        )
      }
    >
      {children}
    </NavLink>
  );
}

export function HelpLayout() {
  const me = useMe();
  const user = me.data;
  const tickets = useMyTickets(!!user);
  const waiting = tickets.data?.filter((t) => t.status === "pending" && t.open_actions > 0).length ?? 0;
  const logout = useLogout();

  return (
    <div className="flex min-h-dvh flex-col">
      <header className="sticky top-0 z-40 border-b border-border/60 bg-bg/80 backdrop-blur-xl">
        <div className="mx-auto flex h-15 max-w-6xl items-center gap-2 px-4 sm:px-6">
          <Logo />
          <nav className="ml-auto flex items-center gap-0.5">
            {user && (
              <NavItem to="/tickets">
                <TicketCheck className="size-4" />
                <span className="hidden sm:inline">My tickets</span>
                {waiting > 0 && (
                  <span className="flex h-4.5 min-w-4.5 items-center justify-center rounded-full bg-dawn px-1 text-[10.5px] font-semibold text-white">
                    {waiting}
                  </span>
                )}
              </NavItem>
            )}
            <ThemeToggle />
            {user ? (
              <Menu>
                <MenuTrigger asChild>
                  <button className="ml-1 rounded-full" aria-label="Account">
                    <Avatar name={user.display_name} className="size-8" />
                  </button>
                </MenuTrigger>
                <MenuContent align="end">
                  <MenuLabel>Signed in as</MenuLabel>
                  <div className="px-2.5 pb-2 text-sm text-text">{user.email}</div>
                  <MenuSeparator />
                  <MenuItem asChild>
                    <Link to="/tickets">
                      <TicketCheck /> My tickets
                    </Link>
                  </MenuItem>
                  <MenuItem onSelect={() => logout.mutate()}>
                    <LogOut /> Sign out
                  </MenuItem>
                </MenuContent>
              </Menu>
            ) : (
              <Button asChild variant="ghost" size="sm" className="ml-1">
                <Link to="/tickets">Sign in</Link>
              </Button>
            )}
          </nav>
        </div>
      </header>

      <main className="flex-1">
        <Outlet />
      </main>

      <footer className="border-t border-border/60">
        <div className="mx-auto flex max-w-6xl flex-col gap-2 px-4 py-8 text-[13px] text-faint sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <p>Everdawn is a fictional game by NovaStar Games. This is a demo support platform.</p>
          <Link to="/console" className="hover:text-muted">
            Staff console →
          </Link>
        </div>
      </footer>
      <ScrollRestoration />
    </div>
  );
}
