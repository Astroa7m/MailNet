"use client";
import ToolCard from "./ToolCard";
import EmailListCard from "./EmailListCard";
import EmailActionCard from "./EmailActionCard";

const TOOL_META: Record<string, { label: string; pendingLabel: string; successLabel: string }> = {
  send_draft:               { label: "Send Draft",               pendingLabel: "Sending…",    successLabel: "Sent" },
  delete_email:             { label: "Delete Email",             pendingLabel: "Deleting…",   successLabel: "Deleted" },
  update_email_settings:    { label: "Update Settings",          pendingLabel: "Saving…",     successLabel: "Saved" },
  schedule_send_email:      { label: "Schedule Email",           pendingLabel: "Scheduling…", successLabel: "Scheduled" },
  schedule_recurring_email: { label: "Schedule Recurring Email", pendingLabel: "Scheduling…", successLabel: "Scheduled" },
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

export default function ToolCallRenderer({ name, status, args, result }: Props) {
  if (name === "read_emails" || name === "search_emails") {
    return <EmailListCard status={status} result={result} />;
  }
  if (name === "send_email") {
    return <EmailActionCard args={args as any} status={status} result={result} label="Send Email" icon={<SendIcon />} pendingLabel="Sending…" successLabel="Sent" />;
  }
  if (name === "draft_email") {
    return <EmailActionCard args={args as any} status={status} result={result} label="Save Draft" icon={<DraftIcon />} pendingLabel="Saving…" successLabel="Saved" />;
  }
  if (name === "reply_to_email") {
    return <EmailActionCard args={args as any} status={status} result={result} label="Reply to Email" icon={<ReplyIcon />} pendingLabel="Sending…" successLabel="Sent" />;
  }
  const meta = TOOL_META[name];
  return <ToolCard name={name} status={status} args={args} result={result} {...meta} />;
}
