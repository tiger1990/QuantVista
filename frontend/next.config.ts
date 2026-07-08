import type { NextConfig } from "next";

// Thin BFF: proxy /api/* to the FastAPI backend so the browser calls same-origin
// `/api/v1/...`. The httpOnly refresh cookie (path /api/v1/auth) then flows without
// CORS, and the backend URL stays hidden. No business logic lives in Next.
const API_URL = process.env.API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // Emit a self-contained server bundle for a small, non-root runtime image.
  output: "standalone",
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/api/:path*` }];
  },
};

export default nextConfig;
