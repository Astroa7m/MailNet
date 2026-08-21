"use client";
import { useEffect, useId, useState, useSyncExternalStore } from "react";
import { registerEmailList, isCollapsed, subscribe } from "./emailListCollapseStore";

interface Email {
  messageId?: string;
  id?: string;
  subject?: string;
  sender?: string;
  body?: string;
  dateTime?: string;
  attachments?: string[];
  labelIds?: string[];
}

function attachmentIcon(filename: string) {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  if (["jpg","jpeg","png","gif","webp","svg"].includes(ext)) return "🖼️";
  if (ext === "pdf") return "📄";
  if (["doc","docx"].includes(ext)) return "📝";
  if (["xls","xlsx","csv"].includes(ext)) return "📊";
  if (["zip","rar","7z","tar","gz"].includes(ext)) return "🗜️";
  if (["mp4","mov","avi","mkv"].includes(ext)) return "🎬";
  if (["mp3","wav","m4a"].includes(ext)) return "🎵";
  return "📎";
}

function formatDate(str: string) {
  try {
    return new Date(str).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  } catch {
    return str;
  }
}

function senderName(sender: string) {
  const m = sender.match(/^(.+?)\s*</);
  return m ? m[1].replace(/"/g, "").trim() : sender;
}

function senderInitial(sender: string) {
  return senderName(sender).charAt(0).toUpperCase();
}

function EmailCard({ email, index }: { email: Email; index: number }) {
  const colors = ["bg-blue-500", "bg-purple-500", "bg-green-500", "bg-orange-500", "bg-pink-500"];
  const color = colors[index % colors.length];

  return (
    <details className="group border-b border-gray-100 dark:border-gray-700 last:border-0">
      <summary className="flex items-start gap-3 px-4 py-3 cursor-pointer list-none hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors">
        <div className={`shrink-0 w-8 h-8 rounded-full ${color} flex items-center justify-center text-white text-xs font-semibold mt-0.5`}>
          {email.sender ? senderInitial(email.sender) : "?"}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
              {email.sender ? senderName(email.sender) : "Unknown"}
            </span>
            <div className="flex items-center gap-1.5 shrink-0">
              {email.attachments && email.attachments.length > 0 && (
                <svg className="w-3 h-3 text-gray-400" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24" title={`${email.attachments.length} attachment(s)`}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.586-6.586a4 4 0 00-5.656-5.656L5.757 10.757a6 6 0 008.485 8.485L19 14" />
                </svg>
              )}
              <span className="text-xs text-gray-400 dark:text-gray-500">
                {email.dateTime ? formatDate(email.dateTime) : ""}
              </span>
            </div>
          </div>
          <p className="text-sm text-gray-700 dark:text-gray-300 truncate">{email.subject ?? "(no subject)"}</p>
          <p className="text-xs text-gray-400 dark:text-gray-500 truncate mt-0.5">{email.body?.slice(0, 80)}</p>
        </div>
        <svg
          className="shrink-0 w-3.5 h-3.5 text-gray-400 mt-1 transition-transform group-open:rotate-180"
          fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </summary>
      <div className="px-4 pb-4 pt-1 ml-11">
        {email.attachments && email.attachments.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-2">
            {email.attachments.map((filename, idx) => (
              <span
                key={idx}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-gray-100 dark:bg-gray-700 text-xs text-gray-600 dark:text-gray-300 border border-gray-200 dark:border-gray-600"
              >
                <span>{attachmentIcon(filename)}</span>
                <span className="max-w-[120px] truncate">{filename}</span>
              </span>
            ))}
          </div>
        )}
        <pre className="text-xs text-gray-600 dark:text-gray-300 whitespace-pre-wrap break-words font-sans max-h-64 overflow-y-auto leading-relaxed">
          {email.body ?? "(no body)"}
        </pre>
      </div>
    </details>
  );
}

export default function EmailListCard({ result, status, id }: { result?: string; status: string; id?: string }) {
  // Stable per-card identity so the collapse store can target this exact
  // instance. Falls back to useId if no toolCallId/msg.id was passed down.
  const fallbackId = useId();
  const cardId = id ?? fallbackId;
  const [manuallyExpanded, setManuallyExpanded] = useState(false);
  const collapsed = useSyncExternalStore(subscribe, () => isCollapsed(cardId), () => false);

  useEffect(() => {
    registerEmailList(cardId);
  }, [cardId]);

  if (status !== "complete" || !result) {
    return (
      <div className="flex items-center gap-2 px-4 py-3 text-sm text-gray-400 dark:text-gray-500">
        <svg className="w-4 h-4 animate-spin" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
        </svg>
        Fetching emails…
      </div>
    );
  }

  let emails: Email[] = [];
  try {
    const parsed = typeof result === "string" ? JSON.parse(result) : result;
    const raw = parsed?.result ?? parsed;
    emails = Array.isArray(raw) ? raw : [raw];
  } catch {
    return <p className="text-xs text-red-500 px-4 py-2">Could not parse email results.</p>;
  }

  if (emails.length === 0) {
    return <p className="text-sm text-gray-400 dark:text-gray-500 px-4 py-3">No emails found.</p>;
  }

  const showList = manuallyExpanded || !collapsed;

  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 overflow-hidden">
      <button
        type="button"
        onClick={() => collapsed && setManuallyExpanded((v) => !v)}
        className={`w-full flex items-center gap-2 px-4 py-2.5 border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 ${collapsed ? "cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700/60" : "cursor-default"}`}
      >
        <svg className="w-4 h-4 text-blue-500 shrink-0" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
        </svg>
        <span className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">
          {emails.length} email{emails.length !== 1 ? "s" : ""}
        </span>
        {collapsed && (
          <svg
            className={`w-3.5 h-3.5 text-gray-400 ml-auto transition-transform ${showList ? "rotate-180" : ""}`}
            fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        )}
      </button>
      {showList && emails.map((email, i) => (
        <EmailCard key={email.messageId ?? i} email={email} index={i} />
      ))}
    </div>
  );
}
