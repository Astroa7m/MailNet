"use client";

// Coordinates EmailListCard <-> TriageCard without prop-drilling through
// CopilotKit's independent per-tool-call renderers. Tool cards render in the
// same order the agent emitted the tool calls (both live streaming and
// history replay), and present_triage always immediately follows the
// read_emails/search_emails it triages, so "collapse whichever EmailListCard
// registered most recently" is a reliable proxy for "collapse my sibling"
// without needing to correlate turns or tool_call_ids across renderers.

type Listener = () => void;

// Every list registered since the last triage card. A single 'last' id meant
// that a user with both Gmail and Outlook connected (two read_emails calls)
// only ever had the second list collapsed.
let pendingIds: string[] = [];
const collapsedIds = new Set<string>();
const listeners = new Set<Listener>();

function notify() {
  listeners.forEach((l) => l());
}

export function registerEmailList(id: string) {
  if (!pendingIds.includes(id)) pendingIds.push(id);
}

export function collapseLastEmailList() {
  let changed = false;
  for (const id of pendingIds) {
    if (!collapsedIds.has(id)) {
      collapsedIds.add(id);
      changed = true;
    }
  }
  pendingIds = [];
  if (changed) notify();
}

export function isCollapsed(id: string): boolean {
  return collapsedIds.has(id);
}

export function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
