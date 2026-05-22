"use client";
import { useDefaultRenderTool } from "@copilotkit/react-core/v2";
import ToolCallRenderer from "./ToolCallRenderer";

export default function ToolActions() {
  useDefaultRenderTool({
    render: ({ name, status, args, result }) => (
      <ToolCallRenderer name={name} status={status} args={args} result={result} />
    ),
  });

  return null;
}
