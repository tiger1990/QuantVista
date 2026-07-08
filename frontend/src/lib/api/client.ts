import createClient from "openapi-fetch";

import type { paths } from "./schema";

/**
 * Typed API client for the FastAPI backend (generated `paths`). Calls the same-origin
 * `/api/*` proxy (Next rewrites → FastAPI), so the httpOnly refresh cookie flows without
 * CORS. The bearer access token is attached per-request from an in-memory holder that the
 * AuthProvider updates — never persisted to localStorage.
 */
let accessToken: string | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export const api = createClient<paths>({ baseUrl: "" });

api.use({
  onRequest({ request }) {
    if (accessToken) {
      request.headers.set("Authorization", `Bearer ${accessToken}`);
    }
    return request;
  },
});
