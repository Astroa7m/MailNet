import {
  CopilotRuntime,
  ExperimentalEmptyAdapter,
  copilotRuntimeNextJSAppRouterEndpoint,
} from "@copilotkit/runtime";
import { HttpAgent } from "@ag-ui/client";

import { NextRequest } from "next/server";

export const POST = async (req: NextRequest) => {
  const cookie = req.headers.get("cookie") ?? "";

  const runtime = new CopilotRuntime({
    agents: {
      mailing_net_agent: new HttpAgent({
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