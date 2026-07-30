"use client";
import ToolCard from "./ToolCard";
import EmailListCard from "./EmailListCard";
import EmailActionCard from "./EmailActionCard";
import SearchCard from "./SearchCard";
import { useInterruptContext } from "./InterruptContext";

const TOOL_META: Record<string, { label: string; pendingLabel: string; successLabel: string }> = {
  send_draft:               { label: "Send Draft",               pendingLabel: "Sending…",    successLabel: "Sent" },
  delete_email:             { label: "Delete Email",             pendingLabel: "Deleting…",   successLabel: "Deleted" },
  update_email_settings:    { label: "Update Settings",          pendingLabel: "Saving…",     successLabel: "Saved" },
  schedule_send_email:      { label: "Schedule Email",           pendingLabel: "Scheduling…", successLabel: "Scheduled" },
  schedule_recurring_email: { label: "Schedule Recurring Email", pendingLabel: "Scheduling…", successLabel: "Scheduled" },
  remember_user_fact:       { label: "Remember",                 pendingLabel: "Saving…",     successLabel: "Remembered" },
  recall_user_context:      { label: "Recall Memory",            pendingLabel: "Recalling…",  successLabel: "Recalled" },
  forget_memory:            { label: "Forget",                   pendingLabel: "Removing…",   successLabel: "Removed" },
  get_current_time:         { label: "Check Time",               pendingLabel: "Checking…",   successLabel: "Checked" },
  convert_time:             { label: "Convert Time Zone",        pendingLabel: "Converting…", successLabel: "Converted" },
  web_search:               { label: "Web Search",               pendingLabel: "Searching…",  successLabel: "Found" },
};

const CONFIRM_LABELS: Record<string, { confirm: string; danger?: boolean }> = {
  send_email:     { confirm: "Send" },
  reply_to_email: { confirm: "Send reply" },
  send_draft:     { confirm: "Send" },
  delete_email:   { confirm: "Delete", danger: true },
};

const SendIcon = () => (
  <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
  </svg>
);
const DraftIcon = () => (
  <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
  </svg>
);
const ReplyIcon = () => (
  <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6" />
  </svg>
);

interface Props {
  name: string;
  status: string;
  args?: Record<string, unknown> | unknown;
  result?: string;
}

function ApprovalButtons({ tool, resolve }: { tool: string; resolve: (r: any) => void }) {
  const meta = CONFIRM_LABELS[tool] ?? { confirm: "Confirm" };
  return (
    <div className="flex items-center justify-between gap-2 px-4 py-2.5 border border-t-0 border-gray-200 dark:border-gray-700 rounded-b-xl bg-gray-50 dark:bg-gray-800/60">
      <button
        onClick={() => resolve({ approved: true, always: true })}
        className="text-xs text-gray-400 dark:text-gray-500 hover:text-blue-500 dark:hover:text-blue-400 hover:underline cursor-pointer whitespace-nowrap"
        title="Approve and stop asking for this action (manage in Settings → Approvals)"
      >
        Don't ask again
      </button>
      <div className="flex gap-2 shrink-0">
        <button
          onClick={() => resolve({ approved: false })}
          className="px-3 py-1.5 rounded-lg text-xs font-medium border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600 transition-colors cursor-pointer"
        >
          Decline
        </button>
        <button
          onClick={() => resolve({ approved: true })}
          className={`px-3 py-1.5 rounded-lg text-xs font-semibold text-white transition-colors cursor-pointer border-none ${meta.danger ? "bg-red-600 hover:bg-red-700" : "bg-blue-600 hover:bg-blue-700"}`}
        >
          {meta.confirm}
        </button>
      </div>
    </div>
  );
}

// Background personalization tools run silently. They're logged on the backend
// ([MEMORY] lines) but never shown as cards in chat, since recall now fires
// before every task and would otherwise clutter the conversation.
// search_tools/load_tools/unload_tools are the deferred-loading plumbing: the
// model uses them to pull tool schemas on demand (to save tokens), but they are
// internal mechanics, not user-facing actions, so they stay hidden too.
export const HIDDEN_TOOLS = new Set([
  "recall_user_context", "remember_user_fact",
  "search_tools", "load_tools", "unload_tools",
]);

export default function ToolCallRenderer({ name, status, args, result }: Props) {
  const { pending } = useInterruptContext();

  if (HIDDEN_TOOLS.has(name)) return null;
  // The approval buttons attach to the live card awaiting approval. We key off
  // `result` rather than `status`: when the graph pauses at the interrupt, the
  // tool-call args finish streaming so CopilotKit flips status to "complete"
  // even though the tool never ran. A paused tool has NO result yet, while
  // every historical card does. So "matches pending tool AND has no result" is
  // the precise, flicker-free signal.
  const showApproval = !!pending && pending.tool === name && !result;
  // While awaiting approval, force the card to read as in-progress instead of
  // showing a premature "Sent"/"Saved" badge from the args-complete status.
  const cardStatus = showApproval ? "executing" : status;

  if (name === "read_emails" || name === "search_emails") {
    return <EmailListCard status={status} result={result} />;
  }

  // web_search gets the cinematic "scanning the web" treatment, the hero moment
  // for the working-hours / company-lookup flow.
  if (name === "web_search") {
    return <SearchCard status={cardStatus} args={args} result={result} />;
  }

  let card: React.ReactNode;
  if (name === "send_email") {
    card = <EmailActionCard args={args as any} status={cardStatus} result={result} label="Send Email" icon={<SendIcon />} pendingLabel="Awaiting approval…" successLabel="Sent" />;
  } else if (name === "draft_email") {
    card = <EmailActionCard args={args as any} status={cardStatus} result={result} label="Save Draft" icon={<DraftIcon />} pendingLabel="Saving…" successLabel="Saved" />;
  } else if (name === "reply_to_email") {
    card = <EmailActionCard args={args as any} status={cardStatus} result={result} label="Reply to Email" icon={<ReplyIcon />} pendingLabel="Awaiting approval…" successLabel="Sent" />;
  } else {
    card = <ToolCard name={name} status={cardStatus} args={args} result={result} {...TOOL_META[name]} />;
  }

  if (!showApproval) return <>{card}</>;

  return (
    <div>
      <div className="[&>div]:rounded-b-none">{card}</div>
      <ApprovalButtons tool={name} resolve={pending!.resolve} />
    </div>
  );
}
