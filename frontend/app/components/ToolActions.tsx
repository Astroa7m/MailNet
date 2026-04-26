"use client";
import { useDefaultRenderTool } from "@copilotkit/react-core/v2";

export default function ToolActions() {
  useDefaultRenderTool({
    render: ({ name, status, result }) => (
      <div className="my-1 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-gray-800 dark:text-gray-200 text-sm overflow-hidden">
        <div className="flex items-center gap-2 px-3 py-2">
          <span className="text-base">{status === "complete" ? "✓" : "⏳"}</span>
          <span className="font-medium">{name.replace(/_/g, " ")}</span>
          <span className="ml-auto text-xs text-gray-400 dark:text-gray-500 capitalize">{status}</span>
        </div>
        {status === "complete" && result && (
          <div className="border-t border-gray-200 dark:border-gray-700 px-3 py-2 text-xs text-gray-500 dark:text-gray-400 font-mono whitespace-pre-wrap break-all max-h-32 overflow-y-auto">
            {typeof result === "string" ? result : JSON.stringify(result, null, 2)}
          </div>
        )}
      </div>
    ),
  });
  return null;
}
