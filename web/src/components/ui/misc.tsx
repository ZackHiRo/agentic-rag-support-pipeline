import { DropdownMenu, Tooltip as T } from "radix-ui";
import type * as React from "react";
import Markdown from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import { cn, initials } from "@/lib/utils";

export function Skeleton({ className, style }: { className?: string; style?: React.CSSProperties }) {
  return <div className={cn("skeleton rounded-md", className)} style={style} />;
}

export function Avatar({ name, kind, className }: { name: string; kind?: string; className?: string }) {
  if (kind === "ai") {
    return (
      <span className={cn("dawn-gradient inline-flex size-8 shrink-0 items-center justify-center rounded-full text-white shadow-soft", className)}>
        <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
          <path d="M4 16h16M7 16a5 5 0 0 1 10 0M12 4v2M5.6 7.6l1.4 1.4M18.4 7.6 17 9" />
        </svg>
      </span>
    );
  }
  const palette = ["bg-primary-soft text-primary", "bg-info-soft text-info", "bg-success-soft text-success", "bg-dawn-soft text-dawn-text"];
  const tone = palette[[...name].reduce((a, c) => a + c.charCodeAt(0), 0) % palette.length];
  return (
    <span
      className={cn(
        "inline-flex size-8 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold",
        kind === "system" ? "bg-surface-3 text-muted" : tone,
        className,
      )}
    >
      {kind === "system" ? "E" : initials(name)}
    </span>
  );
}

/** Markdown renderer. `breaks` keeps single line breaks (chat messages, sign-offs). */
export function Prose({ children, className, breaks }: { children: string; className?: string; breaks?: boolean }) {
  return (
    <div className={cn("prose-evd text-[14.5px] text-text", className)}>
      <Markdown remarkPlugins={breaks ? [remarkGfm, remarkBreaks] : [remarkGfm]}>{children}</Markdown>
    </div>
  );
}

export function Tooltip({ label, children, side = "top" }: { label: React.ReactNode; children: React.ReactNode; side?: "top" | "bottom" | "left" | "right" }) {
  return (
    <T.Root delayDuration={300}>
      <T.Trigger asChild>{children}</T.Trigger>
      <T.Portal>
        <T.Content side={side} sideOffset={6} className="z-50 rounded-md bg-text px-2 py-1 text-xs text-bg shadow-lift">
          {label}
        </T.Content>
      </T.Portal>
    </T.Root>
  );
}
export const TooltipProvider = T.Provider;

export const Menu = DropdownMenu.Root;
export const MenuTrigger = DropdownMenu.Trigger;
export function MenuContent({ className, ...props }: React.ComponentProps<typeof DropdownMenu.Content>) {
  return (
    <DropdownMenu.Portal>
      <DropdownMenu.Content
        sideOffset={6}
        className={cn("z-50 min-w-44 rounded-xl border border-border bg-surface p-1 shadow-lift", className)}
        {...props}
      />
    </DropdownMenu.Portal>
  );
}
export function MenuItem({ className, ...props }: React.ComponentProps<typeof DropdownMenu.Item>) {
  return (
    <DropdownMenu.Item
      className={cn(
        "flex cursor-default items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm text-text outline-none select-none data-[highlighted]:bg-surface-2 [&_svg]:size-4 [&_svg]:text-muted",
        className,
      )}
      {...props}
    />
  );
}
export const MenuSeparator = () => <DropdownMenu.Separator className="my-1 h-px bg-border" />;
export const MenuLabel = ({ children }: { children: React.ReactNode }) => (
  <DropdownMenu.Label className="px-2.5 pt-1.5 pb-1 text-[11px] font-medium tracking-wide text-faint uppercase">{children}</DropdownMenu.Label>
);
