import { X } from "lucide-react";
import { Dialog } from "radix-ui";
import type * as React from "react";
import { cn } from "@/lib/utils";

export const Sheet = Dialog.Root;
export const SheetTrigger = Dialog.Trigger;
export const SheetClose = Dialog.Close;
export const SheetTitle = Dialog.Title;
export const SheetDescription = Dialog.Description;

/** Side panel on desktop, bottom sheet on phones. */
export function SheetContent({ className, children, ...props }: React.ComponentProps<typeof Dialog.Content>) {
  return (
    <Dialog.Portal>
      <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40 backdrop-blur-[2px] animate-[fade-in_160ms_ease-out]" />
      <Dialog.Content
        className={cn(
          "fixed z-50 flex flex-col bg-surface shadow-lift outline-none animate-[sheet-up_240ms_cubic-bezier(.2,.8,.2,1)] sm:animate-[sheet-left_240ms_cubic-bezier(.2,.8,.2,1)]",
          "inset-x-0 bottom-0 max-h-[88dvh] rounded-t-2xl border-t border-border",
          "sm:inset-y-0 sm:right-0 sm:left-auto sm:max-h-none sm:w-[min(560px,92vw)] sm:rounded-none sm:rounded-l-2xl sm:border-t-0 sm:border-l",
          className,
        )}
        {...props}
      >
        {children}
        <Dialog.Close className="absolute top-3.5 right-3.5 rounded-md p-1.5 text-muted transition hover:bg-surface-2 hover:text-text">
          <X className="size-4" />
          <span className="sr-only">Close</span>
        </Dialog.Close>
      </Dialog.Content>
    </Dialog.Portal>
  );
}

export function DialogContent({ className, children, ...props }: React.ComponentProps<typeof Dialog.Content>) {
  return (
    <Dialog.Portal>
      <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40 backdrop-blur-[2px] animate-[fade-in_160ms_ease-out]" />
      <Dialog.Content
        className={cn(
          "fixed top-[12vh] left-1/2 z-50 w-[min(640px,calc(100vw-32px))] -translate-x-1/2 overflow-hidden rounded-2xl border border-border bg-surface shadow-lift outline-none animate-[pop-in_180ms_cubic-bezier(.2,.8,.2,1)]",
          className,
        )}
        {...props}
      >
        {children}
      </Dialog.Content>
    </Dialog.Portal>
  );
}
export const DialogRoot = Dialog.Root;
export const DialogTitle = Dialog.Title;
