"use client";
import { useDefaultRenderTool, useRenderTool } from "@copilotkit/react-core/v2";
import { z } from "zod";
import ToolCallRenderer from "./ToolCallRenderer";

// The wildcard (default) renderer in CopilotKit 1.56 does NOT receive the
// parsed tool arguments; only name-registered renderers with a schema do. So
// tools whose cards render from args get explicit registrations here, and the
// wildcard stays as the fallback for everything else (their cards use result).
// Schemas are deliberately loose (everything optional) so partial args during
// streaming never fail validation.
const TRIAGE_SCHEMA = z.object({
  items: z
    .array(
      z.object({
        category: z.string().optional(),
        sender: z.string().optional(),
        subject: z.string().optional(),
        reason: z.string().optional(),
      })
    )
    .optional(),
});

function useArgTool(name: string, schema: z.ZodTypeAny) {
  useRenderTool({
    name,
    parameters: schema,
    render: (props) => (
      <ToolCallRenderer
        name={name}
        status={props.status}
        args={props.parameters}
        result={props.status === "complete" ? props.result : undefined}
        toolCallId={props.toolCallId}
      />
    ),
  });
}

const EMAIL_ACTION_SCHEMA = z.object({
  to: z.string().optional(),
  subject: z.string().optional(),
  body: z.string().optional(),
  attachment_ids: z.array(z.string()).optional(),
  msg_id: z.string().optional(),
});

// read_emails/search_emails don't render from args (EmailListCard reads
// `result`), but they still need a typed, stable toolCallId to coordinate
// the collapse-on-triage behavior with TriageCard.
const SCHEDULE_SCHEMA = z.object({
  to: z.string().optional(),
  subject: z.string().optional(),
  body: z.string().optional(),
  minutes_from_now: z.number().optional(),
  hours_from_now: z.number().optional(),
  days_from_now: z.number().optional(),
  day_string: z.string().optional(),
  at_hour: z.number().optional(),
  at_minute: z.number().optional(),
  at_year: z.number().optional(),
  at_month: z.number().optional(),
  at_day: z.number().optional(),
  hour: z.number().optional(),
  minute: z.number().optional(),
  day_of_week: z.string().optional(),
});

const EMPTY_SCHEMA = z.object({}).passthrough();

export default function ToolActions() {
  useArgTool("present_triage", TRIAGE_SCHEMA);
  useArgTool("send_email", EMAIL_ACTION_SCHEMA);
  useArgTool("reply_to_email", EMAIL_ACTION_SCHEMA);
  useArgTool("draft_email", EMAIL_ACTION_SCHEMA);
  useArgTool("web_search", z.object({ query: z.string().optional(), max_results: z.number().optional() }));
  // Approval-gated tools must be registered with a schema, otherwise they fall
  // through the wildcard below, which passes args={undefined}. That is why the
  // delete and send-draft approval cards used to render with no target at all.
  useArgTool("delete_email", z.object({ msg_id: z.string().optional() }));
  useArgTool("send_draft", z.object({ draft_id: z.string().optional(), msg_id: z.string().optional() }));
  useArgTool("update_email_settings", z.object({}).passthrough());
  useArgTool("bound_schedule_send_email", SCHEDULE_SCHEMA);
  useArgTool("bound_schedule_recurring_email", SCHEDULE_SCHEMA);
  useArgTool("read_emails", EMPTY_SCHEMA);
  useArgTool("search_emails", EMPTY_SCHEMA);

  useDefaultRenderTool({
    render: (props) => (
      <ToolCallRenderer
        name={props.name}
        status={props.status}
        args={undefined}
        result={props.result}
        toolCallId={(props as { toolCallId?: string }).toolCallId}
      />
    ),
  });

  return null;
}
