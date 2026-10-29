import { Moon, Sun } from "lucide-react";
import { Link } from "react-router";
import { useTheme } from "@/hooks/theme";
import { cn } from "@/lib/utils";
import { Button } from "./ui/button";
import { Tooltip } from "./ui/misc";

export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cn("size-7", className)} aria-hidden>
      <defs>
        <linearGradient id="evd-dawn" x1="0" y1="1" x2="0" y2="0">
          <stop offset="0" stopColor="#f97316" />
          <stop offset="1" stopColor="#8b5cf6" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="#1b1630" />
      <path d="M6 21.5h20" stroke="#fde68a" strokeWidth="2" strokeLinecap="round" />
      <path d="M9 21.5a7 7 0 0 1 14 0" fill="url(#evd-dawn)" />
    </svg>
  );
}

export function Logo({ to = "/", suffix = "Support" }: { to?: string; suffix?: string }) {
  return (
    <Link to={to} className="flex items-center gap-2.5 rounded-lg font-semibold tracking-tight text-text">
      <LogoMark />
      <span className="text-[15px]">
        Everdawn <span className="font-normal text-muted">{suffix}</span>
      </span>
    </Link>
  );
}

export function ThemeToggle() {
  const { dark, toggle } = useTheme();
  return (
    <Tooltip label={dark ? "Light mode" : "Dark mode"}>
      <Button variant="ghost" size="icon-sm" onClick={toggle} aria-label="Toggle dark mode">
        {dark ? <Sun /> : <Moon />}
      </Button>
    </Tooltip>
  );
}
