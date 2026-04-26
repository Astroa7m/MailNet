"use client";

interface ToolCardProps {
  name: string;
  status: "pending" | "complete" | string;
  args?: Record<string, unknown> | unknown;
  result?: string;
}

export default function ToolCard({ name, status, args, result }: ToolCardProps) {
  const hasArgs = args && Object.keys(args as object).length > 0;
  const hasDetails = hasArgs || result;

  return (
    <details className="my-1 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-gray-800 dark:text-gray-200 text-sm overflow-hidden">
      <summary className={`flex items-center gap-2 px-3 py-2 list-none select-none ${hasDetails ? "cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700" : "cursor-default"} transition-colors`}>
        <span className="text-base">{status === "complete" ? "✓" : "⏳"}</span>
        <span className="font-medium">{name.replace(/_/g, " ")}</span>
        <span className="ml-auto flex items-center gap-1.5 text-xs text-gray-400 dark:text-gray-500">
          <span className="capitalize">{status}</span>
          {hasDetails && (
            <svg className="w-3 h-3 details-chevron" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
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
