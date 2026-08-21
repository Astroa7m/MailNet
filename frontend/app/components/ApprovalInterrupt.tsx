"use client";
import { useEffect } from "react";
import { useInterrupt, CopilotChatConfigurationProvider } from "@copilotkit/react-core/v2";
import { useInterruptContext } from "./InterruptContext";

// Human-in-the-loop confirmation for sensitive backend tools (send/reply/delete).
// The backend pauses via interrupt({type:"approval", tool, args}); this catches
// that event and pushes the pending interrupt into InterruptContext so that
// ToolCallRenderer can render Accept/Decline buttons directly inside the tool card.
//
// agentId must match the provider's agent ("mailing_net_agent").
// renderInChat is false because this app uses the legacy <CopilotChat>.
// CopilotChatConfigurationProvider supplies the threadId so useInterrupt subscribes
// to the SAME (agentId, threadId) agent instance the chat runs on.

const AGENT_ID = "mailing_net_agent";

function parseValue(event: any): any {
  const v = event?.value;
  if (typeof v === "string") {
    try { return JSON.parse(v); } catch { return {}; }
  }
  return v ?? {};
}

// Mounts when an interrupt fires, pushes it into context, clears on unmount.
function InterruptBridge({ event, resolve }: { event: any; resolve: (r: any) => void }) {
  const { setPending } = useInterruptContext();
  const val = parseValue(event);

  useEffect(() => {
    setPending({ tool: val.tool ?? "", toolCallId: val.tool_call_id ?? "", resolve });
    return () => setPending(null);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return null;
}

function InterruptListener() {
  const element = useInterrupt({
    agentId: AGENT_ID,
    renderInChat: false,
    enabled: (event: any) => parseValue(event).type === "approval",
    render: ({ event, resolve }: any) => (
      <InterruptBridge event={event} resolve={resolve} />
    ),
  });

  // element is the InterruptBridge (renders null visually); we just need it mounted
  return <>{element}</>;
}

export default function ApprovalInterrupt({ threadId }: { threadId: string }) {
  return (
    <CopilotChatConfigurationProvider agentId={AGENT_ID} threadId={threadId}>
      <InterruptListener />
    </CopilotChatConfigurationProvider>
  );
}
