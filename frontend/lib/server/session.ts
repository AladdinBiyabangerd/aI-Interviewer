import "server-only";

import { createHash, createHmac, randomBytes, timingSafeEqual } from "node:crypto";

import { retentionDays, sessionSecret } from "./config";

const COOKIE_NAME = "interview_session";

export type SessionContext = {
  id: string;
  ownerHash: string;
  requesterHash: string;
  cookie: string | null;
};

function hmac(value: string): string {
  return createHmac("sha256", sessionSecret()).update(value).digest("hex");
}

function cookieValue(request: Request): string | null {
  const header = request.headers.get("cookie") ?? "";
  for (const item of header.split(";")) {
    const [name, ...parts] = item.trim().split("=");
    if (name === COOKIE_NAME) return decodeURIComponent(parts.join("="));
  }
  return null;
}

function verifiedId(value: string | null): string | null {
  if (!value) return null;
  const [id, signature, ...rest] = value.split(".");
  if (rest.length || !/^[A-Za-z0-9_-]{32,128}$/.test(id ?? "") || !/^[0-9a-f]{64}$/.test(signature ?? "")) {
    return null;
  }
  const expected = Buffer.from(hmac(id), "hex");
  const received = Buffer.from(signature, "hex");
  return expected.length === received.length && timingSafeEqual(expected, received) ? id : null;
}

function requesterAddress(request: Request): string {
  return request.headers.get("x-forwarded-for")?.split(",")[0]?.trim()
    || request.headers.get("x-real-ip")?.trim()
    || "unknown";
}

export function sessionFor(request: Request): SessionContext {
  const existing = verifiedId(cookieValue(request));
  const id = existing ?? randomBytes(32).toString("base64url");
  const signed = `${id}.${hmac(id)}`;
  const maxAge = retentionDays() * 24 * 60 * 60;
  return {
    id,
    ownerHash: hmac(`owner:${id}`),
    requesterHash: hmac(`requester:${requesterAddress(request)}`),
    cookie: existing
      ? null
      : `${COOKIE_NAME}=${encodeURIComponent(signed)}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${maxAge}${process.env.NODE_ENV === "production" ? "; Secure" : ""}`,
  };
}

export function withSessionCookie(response: Response, session: SessionContext): Response {
  if (session.cookie) response.headers.append("Set-Cookie", session.cookie);
  return response;
}

export function opaqueSafetyIdentifier(session: SessionContext): string {
  return createHash("sha256").update(session.ownerHash).digest("hex").slice(0, 64);
}
