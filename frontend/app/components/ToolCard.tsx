"use client";

interface ToolCardProps {
  name: string;
  status: "pending" | "complete" | string;
  args?: Record<string, unknown> | unknown;
  result?: string;
  label?: string;
  pendingLabel?: string;
  successLabel?: string;
}

export default function ToolCard({ name, status, args, result, label, pendingLabel = "Working…", successLabel = "Done" }: ToolCardProps) {
  const hasArgs = args && Object.keys(args as object).length > 0;
  const hasDetails = hasArgs || result;
  const complete = status === "complete";

  let isError = false;
  if (complete && result) {
    try {
      const parsed = typeof result === "string" ? JSON.parse(result) : result;
      isError = parsed?.operation_status === "failed";
    } catch { /* treat as success */ }
  }

  const displayName = label ?? name.replace(/_/g, " ");

  return (
    <details className="my-1 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-gray-800 dark:text-gray-200 text-sm overflow-hidden">
      <summary className={`flex items-center gap-2 px-3 py-2 list-none select-none ${hasDetails ? "cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700" : "cursor-default"} transition-colors`}>
        <span className="text-base">{complete ? (isError ? "✗" : "✓") : "⏳"}</span>
        <span className="font-medium capitalize">{displayName}</span>
        <span className="ml-auto flex items-center gap-1.5 text-xs">
          {!complete ? (
            <span className="text-gray-400 dark:text-gray-500 flex items-center gap-1">
              <svg className="w-3 h-3 animate-spin" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
              {pendingLabel}
            </span>
          ) : (
            <span className={`px-2 py-0.5 rounded-full font-medium ${isError ? "bg-red-100 dark:bg-red-900/40 text-red-600 dark:text-red-400" : "bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-400"}`}>
              {isError ? "Failed" : successLabel}
            </span>
          )}
          {hasDetails && (
            <svg className="w-3 h-3 details-chevron text-gray-400 dark:text-gray-500" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
            </svg>
          )}
        </span>
      </summary>

      {hasDetails && (
        <div className="border-t border-gray-200 dark:border-gray-700 divide-y divide-gray-200 dark:divide-gray-700">
          {hasArgs && (
            <div className="px-3 py-2">
              <p className="text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wide mb-1">Args</p>
              <pre className="text-xs text-gray-600 dark:text-gray-300 whitespace-pre-wrap break-all">
                {JSON.stringify(args, null, 2)}
              </pre>
            </div>
          )}
          {result && (
            <div className="px-3 py-2 max-h-48 overflow-y-auto">
              <p className="text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wide mb-1">Result</p>
              <pre className="text-xs text-gray-600 dark:text-gray-300 whitespace-pre-wrap break-all">{result}</pre>
            </div>
          )}
        </div>
      )}
    </details>
  );
}
