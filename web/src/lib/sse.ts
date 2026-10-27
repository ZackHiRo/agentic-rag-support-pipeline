import { useEffect, useRef } from "react";

export type LiveEvent = {
  type: string;
  ticket_id: number;
  run_id?: number;
  key?: string;
  label?: string;
  status?: string;
  trigger?: string;
};

/** Subscribe to a server-sent event stream; reconnects automatically (EventSource does). */
export function useLiveEvents(url: string | null, onEvent: (e: LiveEvent) => void) {
  const handler = useRef(onEvent);
  handler.current = onEvent;
  useEffect(() => {
    if (!url) return;
    const es = new EventSource(url);
    const listener = (msg: MessageEvent) => {
      try {
        handler.current(JSON.parse(msg.data));
      } catch {
        /* ignore malformed events */
      }
    };
    const types = ["run.queued", "run.started", "run.stage", "run.finished", "ticket.updated", "ticket.created"];
    types.forEach((t) => es.addEventListener(t, listener));
    return () => es.close();
  }, [url]);
}
