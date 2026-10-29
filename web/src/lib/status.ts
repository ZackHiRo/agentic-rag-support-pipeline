/** Shared status vocabulary. Players and staff see different wording for the same states. */

export type Tone = "violet" | "red" | "amber" | "slate" | "green" | "gray" | "blue";

export const TONE_CLASSES: Record<Tone, string> = {
  violet: "bg-primary-soft text-primary",
  red: "bg-danger-soft text-danger",
  amber: "bg-warning-soft text-warning",
  slate: "bg-surface-3 text-muted",
  green: "bg-success-soft text-success",
  gray: "bg-surface-2 text-faint",
  blue: "bg-info-soft text-info",
};

export function playerStatus(t: { status: string; open_actions: number; needs_human: boolean; ai_state: string }): {
  label: string;
  tone: Tone;
} {
  if (t.ai_state === "working") return { label: "Working on it", tone: "violet" };
  switch (t.status) {
    case "new":
      return { label: "Working on it", tone: "violet" };
    case "open":
    case "on_hold":
      return { label: "With our team", tone: "blue" };
    case "pending":
      return t.open_actions > 0 ? { label: "Waiting on you", tone: "amber" } : { label: "Answered", tone: "green" };
    case "solved":
      return { label: "Solved", tone: "green" };
    default:
      return { label: "Closed", tone: "gray" };
  }
}

export const STAFF_STATUS: Record<string, { label: string; tone: Tone }> = {
  new: { label: "AI working", tone: "violet" },
  open: { label: "Open", tone: "red" },
  pending: { label: "Pending", tone: "amber" },
  on_hold: { label: "On hold", tone: "slate" },
  solved: { label: "Solved", tone: "green" },
  closed: { label: "Closed", tone: "gray" },
};

export const PRIORITY: Record<string, { label: string; tone: Tone; rank: number }> = {
  urgent: { label: "Urgent", tone: "red", rank: 0 },
  high: { label: "High", tone: "amber", rank: 1 },
  normal: { label: "Normal", tone: "slate", rank: 2 },
  low: { label: "Low", tone: "gray", rank: 3 },
};

export const HANDOFF_REASON: Record<string, string> = {
  player_request: "Player asked for a human",
  safety: "Safety escalation",
  ai_error: "AI couldn't answer",
  agent_took_over: "Agent took over",
};

export function topicLabel(topic: string): string {
  if (!topic) return "Uncategorized";
  return topic.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

/** Player-facing names for pipeline stages, in order. */
export const PLAYER_STAGES = [
  { key: "classify", label: "Understanding your issue" },
  { key: "retrieve", label: "Checking help articles" },
  { key: "draft", label: "Writing your answer" },
  { key: "qa", label: "Double-checking it" },
] as const;
