import "server-only";

import { sessionSecret } from "./config";
import { issueAdminSession, verifyAdminPassword, verifyAdminSession } from "./admin-auth-core";

const cookieName = "interview_admin";
const maxAge = 12 * 60 * 60;

function settings(): { username: string; passwordHash: string } | null {
  const username = process.env.INTERVIEW_ADMIN_USERNAME?.trim() || "admin";
  const passwordHash = process.env.INTERVIEW_ADMIN_PASSWORD_HASH?.trim() ?? "";
  return username && username.length <= 120 && /^scrypt-v1:[A-Za-z0-9_-]{22}:[A-Za-z0-9_-]{86}$/.test(passwordHash)
    ? { username, passwordHash } : null;
}

export function adminConfigured(): boolean { return Boolean(settings()); }

function cookieValue(request: Request): string | null {
  const cookies = request.headers.get("cookie") ?? "";
  for (const item of cookies.split(";")) {
    const [name, ...parts] = item.trim().split("=");
    if (name === cookieName) {
      try { return decodeURIComponent(parts.join("=")); } catch { return null; }
    }
  }
  return null;
}

export function adminSession(request: Request): { name: string } | null {
  const configured = settings();
  if (!configured) return null;
  return verifyAdminSession(cookieValue(request), sessionSecret(), configured.passwordHash, configured.username)
    ? { name: configured.username } : null;
}

export async function authenticateAdmin(username: unknown, password: unknown): Promise<boolean> {
  const configured = settings();
  if (!configured || typeof username !== "string" || typeof password !== "string") return false;
  if (username.length > 120 || password.length > 256) return false;
  const passwordMatches = await verifyAdminPassword(password, configured.passwordHash);
  return passwordMatches && username.trim() === configured.username;
}

export function adminSessionCookie(): string {
  const configured = settings();
  if (!configured) throw new Error("admin_not_configured");
  const secure = process.env.NODE_ENV === "production" ? "; Secure" : "";
  const value = issueAdminSession(sessionSecret(), configured.passwordHash, configured.username);
  return `${cookieName}=${encodeURIComponent(value)}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${maxAge}${secure}`;
}

export function clearAdminSessionCookie(): string {
  const secure = process.env.NODE_ENV === "production" ? "; Secure" : "";
  return `${cookieName}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0${secure}`;
}

export function adminGuard(request: Request, write = false): Response | null {
  if (!adminSession(request)) return Response.json({ code: "admin_access_denied" }, {
    status: 403, headers: { "Cache-Control": "no-store" },
  });
  if (write && request.headers.get("origin") !== new URL(request.url).origin) {
    return Response.json({ code: "invalid_origin" }, {
      status: 403, headers: { "Cache-Control": "no-store" },
    });
  }
  return null;
}
