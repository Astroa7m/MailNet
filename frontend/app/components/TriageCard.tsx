"use client";
import { useEffect, useMemo } from "react";
import { collapseLastEmailList } from "./emailListCollapseStore";

// Renders the present_triage tool call as a grouped, color-coded card.
// The payload rides in the tool ARGS (not the result): the history endpoint
// truncates results to 500 chars but returns args in full, so args are the
// durable source for both live streaming and thread replay.

interface TriageItem {
  category: "immediate" | "action" | "fyi";
  sender: string;
  subject: string;
  reason: string;
}

interface Props {
  status: string;
  args?: Record<string, unknown> | unknown;
  result?: string;
}

const SECTIONS: {
  key: TriageItem["category"];
  label: string;
  dot: string;
  badge: string;
}[] = [
  {
    key: "immediate",
    label: "Needs immediate response",
    dot: "bg-red-500",
    badge: "text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-500/10 border-red-200 dark:border-red-500/30",
  },
  {
    key: "action",
    label: "Needs action",
    dot: "bg-amber-500",
    badge: "text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-500/10 border-amber-200 dark:border-amber-500/30",
  },
  {
    key: "fyi",
    label: "FYI only",
    dot: "bg-gray-400",
    badge: "text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-500/10 border-gray-200 dark:border-gray-600",
  },
];

// Mirror of the backend's category normalization: models sometimes emit
// "Immediate" or "urgent"; render them instead of dropping the row.
const CATEGORY_ALIASES: Record<string, TriageItem["category"]> = {
  immediate: "immediate", urgent: "immediate", critical: "immediate",
  action: "action", task: "action", "follow-up": "action", followup: "action",
  fyi: "fyi", info: "fyi", informational: "fyi", newsletter: "fyi",
};

// Streaming-safe: args arrive incrementally, so keep only items that already
// have a valid category plus a sender or subject to show.
function parseItems(args: unknown): TriageItem[] {
  const raw = (args as { items?: unknown })?.items;
  if (!Array.isArray(raw)) return [];
  const valid: TriageItem[] = [];
  for (const it of raw) {
    if (!it || typeof it !== "object") continue;
    const rawCat = (it as { category?: unknown }).category;
    const cat = typeof rawCat === "string" ? CATEGORY_ALIASES[rawCat.trim().toLowerCase()] : undefined;
    if (!cat) continue;
    const sender = typeof (it as TriageItem).sender === "string" ? (it as TriageItem).sender : "";
    const subject = typeof (it as TriageItem).subject === "string" ? (it as TriageItem).subject : "";
    if (!sender && !subject) continue;
    const reason = typeof (it as TriageItem).reason === "string" ? (it as TriageItem).reason : "";
    valid.push({ category: cat, sender, subject, reason });
  }
  return valid;
}

const TriageIcon = () => (
  <svg className="w-4 h-4 text-blue-500" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" d="M3 6h18M6 12h12M10 18h4" />
  </svg>
);

export default function TriageCard({ status, args, result }: Props) {
  const items = useMemo(() => parseItems(args), [args]);
  const complete = status === "complete" && !!result;

  // Once triage has real content, the raw email list above it is redundant
  // (same emails, no judgment) — collapse it to a summary bar. The list
  // stays fully expanded for plain "read/search emails" asks that never
  // produce a present_triage sibling.
  useEffect(() => {
    if (items.length > 0) collapseLastEmailList();
  }, [items.length]);

  // Nothing parseable yet: minimal pending line, same idiom as EmailListCard.
  if (!complete && items.length === 0) {
    return (
      <div className="flex items-center gap-2 px-4 py-3 text-sm text-gray-400 dark:text-gray-500">
        <svg className="w-4 h-4 animate-spin" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
        </svg>
        Triaging your inbox…
      </div>
    );
  }

  if (complete && items.length === 0) {
    return <p className="text-sm text-gray-400 dark:text-gray-500 px-4 py-3">Nothing to triage.</p>;
  }

  const urgentCount = items.filter((i) => i.category === "immediate").length;

  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-800">
        <TriageIcon />
        <span className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">
          Inbox triage
        </span>
        <span className="ml-auto text-xs text-gray-400 dark:text-gray-500">
          {complete
            ? `${items.length} email${items.length !== 1 ? "s" : ""}${urgentCount ? ` · ${urgentCount} urgent` : ""}`
            : "sorting…"}
        </span>
      </div>

      {SECTIONS.map((section) => {
        const rows = items.filter((i) => i.category === section.key);
        if (rows.length === 0) return null;
        return (
          <div key={section.key} className="border-b border-gray-100 dark:border-gray-800 last:border-b-0">
            <div className="flex items-center gap-2 px-4 pt-3 pb-1.5">
              <span className={`w-2 h-2 rounded-full ${section.dot}`} />
              <span className={`text-[11px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded border ${section.badge}`}>
                {section.label}
              </span>
            </div>
            <ul className="pb-2.5">
              {rows.map((item, i) => (
                <li key={`${section.key}-${i}`} className="flex items-baseline gap-2 px-4 py-1.5">
                  <span className="text-sm font-semibold text-gray-800 dark:text-gray-100 shrink-0">
                    {item.sender || "Unknown sender"}
                  </span>
                  <span className="text-sm text-gray-600 dark:text-gray-300 truncate min-w-0">
                    {item.subject}
                  </span>
                  {item.reason && (
                    <span className="text-xs text-gray-400 dark:text-gray-500 truncate min-w-0 hidden sm:inline">
                      {item.reason}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </div>
  );
}
