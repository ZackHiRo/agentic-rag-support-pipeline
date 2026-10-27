import type { components } from "@/api/schema";

type S = components["schemas"];
export type User = S["UserOut"];
export type ArticleSummary = S["ArticleSummary"];
export type ArticleSuggestion = S["ArticleSuggestion"];
export type Article = S["ArticleOut"];
export type Ticket = S["TicketOut"];
export type TicketSummary = S["TicketSummaryOut"];
export type Message = S["MessageOut"];
export type Action = S["ActionOut"];
export type Citation = S["CitationOut"];
export type ConsoleTicketList = S["ConsoleTicketList"];
export type ConsoleTicketRow = S["ConsoleTicketRow"];
export type ConsoleTicket = S["ConsoleTicketOut"];
export type Run = S["RunOut"];
export type TicketEvent = S["EventOut"];
export type Staff = S["StaffOut"];
// Request bodies: fields with server-side defaults are optional.
export type TicketPatch = Partial<S["TicketPatchIn"]>;
export type ConsoleReply = S["ConsoleReplyIn"];

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

function detailMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d) && d[0]?.msg) return String(d[0].msg);
  }
  return fallback;
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init;
  const res = await fetch(path, {
    credentials: "same-origin",
    ...rest,
    headers: json !== undefined ? { "Content-Type": "application/json", ...headers } : headers,
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, detailMessage(body, `Request failed (${res.status})`));
  return body as T;
}

export function form(fields: Record<string, string | undefined>, files: File[] = []): FormData {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) if (v !== undefined) fd.append(k, v);
  for (const f of files) fd.append("files", f, f.name);
  return fd;
}
