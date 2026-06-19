import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emit a self-contained server bundle for a small, non-root runtime image.
  output: "standalone",
};

export default nextConfig;
