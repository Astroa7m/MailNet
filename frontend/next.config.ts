import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  typescript: {
    // third-party type conflict between @ag-ui/client and @copilotkit/runtime
    ignoreBuildErrors: true,
  },
};

export default nextConfig;
