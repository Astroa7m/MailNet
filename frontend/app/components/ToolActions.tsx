"use client";
import { useDefaultRenderTool } from "@copilotkit/react-core/v2";
import ToolCard from "./ToolCard";
import EmailListCard from "./EmailListCard";
import EmailActionCard from "./EmailActionCard";

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

export default function ToolActions() {
  useDefaultRenderTool({
    render: ({ name, status, args, result }) => {
      if (name === "read_emails" || name === "search_emails") {
        return <EmailListCard status={status} result={result} />;
      }
      if (name === "send_email") {
        return <EmailActionCard args={args} status={status} result={result} label="Send Email" icon={<SendIcon />} />;
      }
      if (name === "draft_email") {
        return <EmailActionCard args={args} status={status} result={result} label="Save Draft" icon={<DraftIcon />} />;
      }
      if (name === "reply_to_email") {
        return <EmailActionCard args={args} status={status} result={result} label="Reply to Email" icon={<ReplyIcon />} />;
      }
      return <ToolCard name={name} status={status} args={args} result={result} />;
    },
  });

  return null;
}
