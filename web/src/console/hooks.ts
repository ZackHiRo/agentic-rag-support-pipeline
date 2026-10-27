import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, type ConsoleReply, type ConsoleTicket, type ConsoleTicketList, type Staff, type TicketPatch } from "@/lib/api";
import { useLiveEvents } from "@/lib/sse";

export const VIEWS = [
  { key: "attention", label: "Needs attention", hint: "Handed off, escalated, or the AI couldn't answer" },
  { key: "review", label: "AI review", hint: "Answered by the AI with low confidence" },
  { key: "mine", label: "Assigned to me", hint: "" },
  { key: "pending", label: "Waiting on player", hint: "" },
  { key: "on_hold", label: "On hold", hint: "" },
  { key: "new", label: "AI working", hint: "" },
  { key: "solved", label: "Solved", hint: "" },
  { key: "all", label: "All tickets", hint: "" },
] as const;
export type ViewKey = (typeof VIEWS)[number]["key"];

export function useQueue(view: string, q: string, priority: string) {
  const params = new URLSearchParams({ view, q, priority });
  return useQuery({
    queryKey: ["console-list", view, q, priority],
    queryFn: () => api<ConsoleTicketList>(`/api/console/tickets?${params}`),
    placeholderData: (prev) => prev,
  });
}

export function useConsoleTicket(id: number | null) {
  return useQuery({
    queryKey: ["console-ticket", id],
    queryFn: () => api<ConsoleTicket>(`/api/console/tickets/${id}`),
    enabled: id !== null,
  });
}

export function useStaff() {
  return useQuery({ queryKey: ["staff"], queryFn: () => api<Staff[]>("/api/console/staff"), staleTime: 5 * 60_000 });
}

/** Live updates for the whole console: any ticket change refreshes the queue and that ticket. */
export function useConsoleLive() {
  const qc = useQueryClient();
  useLiveEvents("/api/console/stream", (e) => {
    qc.invalidateQueries({ queryKey: ["console-list"] });
    qc.invalidateQueries({ queryKey: ["console-ticket", e.ticket_id] });
    if (e.type === "run.finished" || e.type === "ticket.updated") qc.invalidateQueries({ queryKey: ["reports"] });
  });
}

function useTicketMutation<T>(id: number, fn: (body: T) => Promise<ConsoleTicket>, success?: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (t) => {
      qc.setQueryData(["console-ticket", id], t);
      qc.invalidateQueries({ queryKey: ["console-list"] });
      if (success) toast.success(success);
    },
    onError: (e) => toast.error(e.message),
  });
}

export function usePatchTicket(id: number) {
  return useTicketMutation(id, (body: TicketPatch) => api<ConsoleTicket>(`/api/console/tickets/${id}`, { method: "PATCH", json: body }));
}

export function useReply(id: number) {
  return useTicketMutation(id, (body: ConsoleReply) => api<ConsoleTicket>(`/api/console/tickets/${id}/reply`, { method: "POST", json: body }));
}

export function useAiDraft(id: number) {
  return useTicketMutation(
    id,
    (guidance: string) => api<ConsoleTicket>(`/api/console/tickets/${id}/ai-draft`, { method: "POST", json: { guidance } }),
  );
}
