"use client";

interface AttachmentArg {
  filename: string;
  mime_type?: string;
  size?: number;
}

interface SendArgs {
  to?: string;
  subject?: string;
  body?: string;
  msg_id?: string;
  attachments?: AttachmentArg[];
  attachment_ids?: string[];
}

interface Props {
  args: SendArgs;
  status: string;
  result?: string;
  label: string;
  icon: React.ReactNode;
  pendingLabel?: string;
  successLabel?: string;
}

function StatusBadge({ status, result, successLabel = "Sent" }: { status: string; result?: string; successLabel?: string }) {
  if (status !== "complete") return null;

  let ok = true;
  try {
    const parsed = typeof result === "string" ? JSON.parse(result) : result;
    ok = parsed?.operation_status !== "failed";
  } catch { /* treat as success */ }

  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${ok ? "bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-400" : "bg-red-100 dark:bg-red-900/40 text-red-600 dark:text-red-400"}`}>
      {ok ? successLabel : "Failed"}
    </span>
  );
}

export default function EmailActionCard({ args, status, result, label, icon, pendingLabel = "Sending…", successLabel = "Sent" }: Props) {
  const pending = status !== "complete";

  // The tool parameter is attachment_ids; args.attachments was never populated,
  // so an approval card could show a short note while silently carrying a file.
  // Ids are shown when that is all we have, so the count is at least visible.
  const attachmentLabels: string[] =
    args.attachments?.map((a) => a.filename).filter(Boolean) ??
    args.attachment_ids?.map((id) => `Attached file ${String(id).slice(0, 8)}`) ??
    [];

  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-800">
        <span className="text-blue-500">{icon}</span>
        <span className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide flex-1">{label}</span>
        {pending
          ? <span className="flex items-center gap-1 text-xs text-gray-400 dark:text-gray-500">
              <svg className="w-3 h-3 animate-spin" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
              {pendingLabel}
            </span>
          : <StatusBadge status={status} result={result} successLabel={successLabel} />
        }
      </div>

      {/* Fields */}
      <div className="divide-y divide-gray-100 dark:divide-gray-700/60">
        {args.to && (
          <div className="flex items-baseline gap-3 px-4 py-2">
            <span className="text-xs font-medium text-gray-400 dark:text-gray-500 w-14 shrink-0">To</span>
            <span className="text-sm text-gray-800 dark:text-gray-200 break-all">{args.to}</span>
          </div>
        )}
        {args.subject && (
          <div className="flex items-baseline gap-3 px-4 py-2">
            <span className="text-xs font-medium text-gray-400 dark:text-gray-500 w-14 shrink-0">Subject</span>
            <span className="text-sm font-medium text-gray-800 dark:text-gray-200">{args.subject}</span>
          </div>
        )}
        {args.msg_id && !args.to && (
          <div className="flex items-baseline gap-3 px-4 py-2">
            <span className="text-xs font-medium text-gray-400 dark:text-gray-500 w-14 shrink-0">Reply to</span>
            <span className="text-sm text-gray-500 dark:text-gray-400 font-mono text-xs break-all">{args.msg_id}</span>
          </div>
        )}
        {args.body && (
          <div className="px-4 py-3">
            <p className="text-xs font-medium text-gray-400 dark:text-gray-500 mb-1.5">Body</p>
            <pre className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap break-words font-sans leading-relaxed max-h-48 overflow-y-auto">
              {args.body}
            </pre>
          </div>
        )}
        {attachmentLabels.length > 0 && (
          <div className="px-4 py-3 border-t border-gray-100 dark:border-gray-700/60">
            <p className="text-xs font-medium text-gray-400 dark:text-gray-500 mb-2">Attachments</p>
            <div className="flex flex-wrap gap-1.5">
              {attachmentLabels.map((label, i) => (
                <span key={i} className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-gray-100 dark:bg-gray-700 text-xs text-gray-600 dark:text-gray-300 border border-gray-200 dark:border-gray-600">
                  <span className="max-w-[180px] truncate">{label}</span>
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
