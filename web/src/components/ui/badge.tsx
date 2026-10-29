import type * as React from "react";
import { TONE_CLASSES, type Tone } from "@/lib/status";
import { cn } from "@/lib/utils";

export function Badge({
  tone = "slate",
  dot,
  className,
  children,
  ...props
}: React.ComponentProps<"span"> & { tone?: Tone; dot?: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex h-5.5 items-center gap-1.5 rounded-full px-2 text-[11.5px] font-medium whitespace-nowrap",
        TONE_CLASSES[tone],
        className,
      )}
      {...props}
    >
      {dot && <span className="size-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}

export function Kbd({ className, ...props }: React.ComponentProps<"kbd">) {
  return (
    <kbd
      className={cn(
        "inline-flex h-5 min-w-5 items-center justify-center rounded border border-border bg-surface-2 px-1 font-sans text-[11px] font-medium text-muted",
        className,
      )}
      {...props}
    />
  );
}
