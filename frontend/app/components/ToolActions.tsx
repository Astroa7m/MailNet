"use client";
import { useDefaultRenderTool } from "@copilotkit/react-core/v2";
import ToolCard from "./ToolCard";

export default function ToolActions() {
  useDefaultRenderTool({
    render: ({ name, status, args, result }) => (
      <ToolCard name={name} status={status} args={args} result={result} />
    ),
  });
  return null;
}
