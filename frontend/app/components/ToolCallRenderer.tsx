"use client";
import ToolCard from "./ToolCard";
import EmailListCard from "./EmailListCard";
import EmailActionCard from "./EmailActionCard";
import { useInterruptContext } from "./InterruptContext";

const TOOL_META: Record<string, { label: string; pendingLabel: string; successLabel: string }> = {
  send_draft:               { label: "Send Draft",               pendingLabel: "Sending…",    successLabel: "Sent" },
  delete_email:             { label: "Delete Email",             pendingLabel: "Deleting…",   successLabel: "Deleted" },
  update_email_settings:    { label: "Update Settings",          pendingLabel: "Saving…",     successLabel: "Saved" },
  schedule_send_email:      { label: "Schedule Email",           pendingLabel: "Scheduling…", successLabel: "Scheduled" },
  schedule_recurring_email: { label: "Schedule Recurring Email", pendingLabel: "Scheduling…", successLabel: "Scheduled" },
  remember_user_fact:       { label: "Remember",                 pendingLabel: "Saving…",     successLabel: "Remembered" },
  recall_user_context:      { label: "Recall Memory",            pendingLabel: "Recalling…",  successLabel: "Recalled" },
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
    <div className="flex items-center justify-between px-4 py-2.5 border border-t-0 border-gray-200 dark:border-gray-700 rounded-b-xl bg-gray-50 dark:bg-gray-800/60">
      <span className="text-xs text-gray-400 dark:text-gray-500">Confirm before proceeding</span>
      <div className="flex gap-2">
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

export default function ToolCallRenderer({ name, status, args, result }: Props) {
  const { pending } = useInterruptContext();
  // The approval buttons attach only to the live, in-progress card whose tool
  // matches the pending interrupt. Historical cards are always "complete", so
  // an old send_email card never sprouts buttons when a new send is awaiting
  // approval, and we only flatten the card's bottom corners when buttons follow.
  const showApproval = !!pending && pending.tool === name && status !== "complete";

  if (name === "read_emails" || name === "search_emails") {
    return <EmailListCard status={status} result={result} />;
  }

  let card: React.ReactNode;
  if (name === "send_email") {
    card = <EmailActionCard args={args as any} status={status} result={result} label="Send Email" icon={<SendIcon />} pendingLabel="Sending…" successLabel="Sent" />;
  } else if (name === "draft_email") {
    card = <EmailActionCard args={args as any} status={status} result={result} label="Save Draft" icon={<DraftIcon />} pendingLabel="Saving…" successLabel="Saved" />;
  } else if (name === "reply_to_email") {
    card = <EmailActionCard args={args as any} status={status} result={result} label="Reply to Email" icon={<ReplyIcon />} pendingLabel="Sending…" successLabel="Sent" />;
  } else {
    card = <ToolCard name={name} status={status} args={args} result={result} {...TOOL_META[name]} />;
  }

  if (!showApproval) return <>{card}</>;

  return (
    <div>
      <div className="[&>div]:rounded-b-none">{card}</div>
      <ApprovalButtons tool={name} resolve={pending!.resolve} />
    </div>
  );
}
