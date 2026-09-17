import "server-only";

import { createHash, randomBytes } from "node:crypto";

const ACCESS_COOKIE = "portal_access_token";
const PROFILE_COOKIE = "portal_profile";
const PKCE_COOKIE = "portal_oidc_pkce";

export type PortalOidcConfig = {
  issuer: string;
  clientId: string;
  redirectUri: string;
  interviewApiBaseUrl: string;
  portalHomeUrl: string;
  authorizeUrl: string;
  tokenUrl: string;
};

export type PortalProfile = {
  givenName: string;
  familyName: string;
  displayName: string;
};

export function portalOidcConfigured(): boolean {
  return Boolean(
    process.env.PORTAL_OIDC_ISSUER?.trim()
      && process.env.PORTAL_OIDC_CLIENT_ID?.trim()
      && process.env.PORTAL_OIDC_REDIRECT_URI?.trim()
      && process.env.INTERVIEW_API_BASE_URL?.trim(),
  );
}

export function portalOidcConfig(): PortalOidcConfig {
  const issuerRaw = process.env.PORTAL_OIDC_ISSUER?.trim() ?? "";
  const issuer = issuerRaw.endsWith("/") ? issuerRaw : `${issuerRaw}/`;
  const clientId = process.env.PORTAL_OIDC_CLIENT_ID?.trim() ?? "";
  const redirectUri = process.env.PORTAL_OIDC_REDIRECT_URI?.trim() ?? "";
  const interviewApiBaseUrl = (process.env.INTERVIEW_API_BASE_URL?.trim() ?? "").replace(/\/$/, "");
  if (!issuerRaw || !clientId || !redirectUri || !interviewApiBaseUrl) {
    throw new Error("Portal OIDC env is incomplete");
  }
  const base = issuer.replace(/\/$/, "");
  const portalHomeUrl = (
    process.env.PORTAL_HOME_URL?.trim()
    || `${base}/portal/welcome/`
  );
  return {
    issuer,
    clientId,
    redirectUri,
    interviewApiBaseUrl,
    portalHomeUrl,
    authorizeUrl: `${base}/portal/oauth/authorize`,
    tokenUrl: `${base}/portal/oauth/token`,
  };
}

export function createPkcePair(): { verifier: string; challenge: string; state: string } {
  const verifier = randomBytes(32).toString("base64url");
  const challenge = createHash("sha256").update(verifier).digest("base64url");
  const state = randomBytes(16).toString("base64url");
  return { verifier, challenge, state };
}

function cookieFlags(maxAgeSeconds: number): string {
  const secure = process.env.NODE_ENV === "production" ? "; Secure" : "";
  return `Path=/; HttpOnly; SameSite=Lax; Max-Age=${maxAgeSeconds}${secure}`;
}

export function pkceCookie(value: string, maxAgeSeconds = 600): string {
  return `${PKCE_COOKIE}=${encodeURIComponent(value)}; ${cookieFlags(maxAgeSeconds)}`;
}

export function clearPkceCookie(): string {
  return `${PKCE_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0`;
}

export function accessTokenCookie(token: string, maxAgeSeconds: number): string {
  return `${ACCESS_COOKIE}=${token}; ${cookieFlags(maxAgeSeconds)}`;
}

export function clearAccessTokenCookie(): string {
  return `${ACCESS_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0`;
}

export function profileCookie(profile: PortalProfile, maxAgeSeconds: number): string {
  const value = encodeURIComponent(JSON.stringify(profile));
  return `${PROFILE_COOKIE}=${value}; ${cookieFlags(maxAgeSeconds)}`;
}

export function clearProfileCookie(): string {
  return `${PROFILE_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0`;
}

export function readCookie(request: Request, name: string): string | null {
  const header = request.headers.get("cookie") ?? "";
  for (const item of header.split(";")) {
    const [rawName, ...parts] = item.trim().split("=");
    if (rawName === name) return decodeURIComponent(parts.join("="));
  }
  return null;
}

export function readAccessToken(request: Request): string | null {
  const raw = readCookie(request, ACCESS_COOKIE);
  if (!raw) return null;
  if (raw.includes(".")) return raw;
  try {
    const decoded = decodeURIComponent(raw);
    return decoded.includes(".") ? decoded : raw;
  } catch {
    return raw;
  }
}

export function readProfile(request: Request): PortalProfile | null {
  const raw = readCookie(request, PROFILE_COOKIE);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<PortalProfile>;
    const displayName = (parsed.displayName ?? "").trim();
    if (!displayName) return null;
    return {
      givenName: (parsed.givenName ?? "").trim(),
      familyName: (parsed.familyName ?? "").trim(),
      displayName,
    };
  } catch {
    return null;
  }
}

export function profileFromIdToken(idToken: string | undefined): PortalProfile | null {
  if (!idToken) return null;
  try {
    const parts = idToken.split(".");
    if (parts.length < 2) return null;
    const json = Buffer.from(parts[1].replace(/-/g, "+").replace(/_/g, "/"), "base64").toString(
      "utf8",
    );
    const payload = JSON.parse(json) as {
      given_name?: string;
      family_name?: string;
      name?: string;
      email?: string;
    };
    const givenName = (payload.given_name ?? "").trim();
    const familyName = (payload.family_name ?? "").trim();
    const displayName = (
      payload.name
      || [givenName, familyName].filter(Boolean).join(" ")
      || payload.email
      || ""
    ).trim();
    if (!displayName) return null;
    return { givenName, familyName, displayName };
  } catch {
    return null;
  }
}

export function readPkcePayload(request: Request): { verifier: string; state: string } | null {
  const raw = readCookie(request, PKCE_COOKIE);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as { verifier?: string; state?: string };
    if (!parsed.verifier || !parsed.state) return null;
    return { verifier: parsed.verifier, state: parsed.state };
  } catch {
    return null;
  }
}
