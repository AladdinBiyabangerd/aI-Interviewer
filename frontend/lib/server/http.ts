import "server-only";

import type { SessionContext } from "./session";
import { withSessionCookie } from "./session";

export function json(body: unknown, status = 200, session?: SessionContext, headers?: HeadersInit): Response {
  const response = Response.json(body, {
    status,
    headers: {
      "Cache-Control": "no-store, max-age=0",
      "X-Content-Type-Options": "nosniff",
      ...headers,
    },
  });
  return session ? withSessionCookie(response, session) : response;
}

export function safeErrorCode(error: unknown): string {
  if (error instanceof Error && /^[a-z0-9_]{3,64}$/.test(error.message)) return error.message;
  return "internal_error";
}
