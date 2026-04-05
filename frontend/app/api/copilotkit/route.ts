import {
  CopilotRuntime,
  ExperimentalEmptyAdapter,
  copilotRuntimeNextJSAppRouterEndpoint,
} from "@copilotkit/runtime";
//import { HttpAgent } from "@ag-ui/client";
import { LangGraphHttpAgent } from "@copilotkit/runtime/langgraph";

import { NextRequest } from "next/server";

export const POST = async (req: NextRequest) => {
  const cookie = req.headers.get("cookie") ?? "";

  const runtime = new CopilotRuntime({
    agents: {
      sample_agent: new LangGraphHttpAgent({
        url: process.env.FASTAPI_URL || "http://localhost:8002/agent",
        headers: { cookie },
      }),
    },
  });

  const { handleRequest } = copilotRuntimeNextJSAppRouterEndpoint({
    runtime,
    serviceAdapter: new ExperimentalEmptyAdapter(),
    endpoint: "/api/copilotkit",
  });

  return handleRequest(req);
};