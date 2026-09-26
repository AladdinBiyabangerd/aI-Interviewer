import "server-only";

import { createHash, createHmac, randomBytes, timingSafeEqual } from "node:crypto";

import { createRemoteJWKSet, jwtVerify, type JWTPayload } from "jose";

import { sessionSecret } from "./config.ts";

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
  jwksUrl: string;
};

export type PortalProfile = {
  givenName: string;
  familyName: string;
  displayName: string;
};

function configuredValue(name: string): string {
  return process.env[name]?.trim() ?? "";
}

function configuredUrl(name: string, value: string): URL {
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error(`${name} must be an absolute URL`);
  }
  if (!(["http:", "https:"] as string[]).includes(parsed.protocol)
    || parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new Error(`${name} must be an absolute HTTP(S) URL without credentials, query, or fragment`);
  }
  if (process.env.NODE_ENV === "production" && parsed.protocol !== "https:") {
    throw new Error(`${name} must use HTTPS in production`);
  }
  return parsed;
}

export function portalOidcEnabled(): boolean {
  return configuredValue("PORTAL_OIDC_ENABLED").toLowerCase() === "true";
}

export function portalOidcConfigured(): boolean {
  return portalOidcEnabled() && [
    "PORTAL_OIDC_ISSUER",
    "PORTAL_OIDC_CLIENT_ID",
    "PORTAL_OIDC_REDIRECT_URI",
    "PORTAL_OIDC_JWKS_URL",
    "INTERVIEW_API_BASE_URL",
    "NEXT_PUBLIC_APP_URL",
  ].every((name) => Boolean(configuredValue(name)));
}

export function portalOidcConfigurationIssue(): string | null {
  const enabled = configuredValue("PORTAL_OIDC_ENABLED").toLowerCase();
  if (!enabled || enabled === "false") return null;
  if (enabled !== "true") return "PORTAL_OIDC_ENABLED must be true or false";
  if (!portalOidcConfigured()) return "Portal OIDC environment is incomplete";
  try {
    portalOidcConfig();
    return null;
  } catch (error) {
    return error instanceof Error ? error.message : "Portal OIDC configuration is invalid";
  }
}

export function portalOidcConfig(): PortalOidcConfig {
  const issuerValue = configuredValue("PORTAL_OIDC_ISSUER");
  const clientId = configuredValue("PORTAL_OIDC_CLIENT_ID");
  const redirectValue = configuredValue("PORTAL_OIDC_REDIRECT_URI");
  const jwksValue = configuredValue("PORTAL_OIDC_JWKS_URL");
  const apiValue = configuredValue("INTERVIEW_API_BASE_URL");
  const appValue = configuredValue("NEXT_PUBLIC_APP_URL");
  if (!issuerValue || !clientId || !redirectValue || !jwksValue || !apiValue || !appValue) {
    throw new Error("Portal OIDC environment is incomplete");
  }
  if (clientId.length > 200 || /\s/.test(clientId)) {
    throw new Error("PORTAL_OIDC_CLIENT_ID is invalid");
  }

  const issuerUrl = configuredUrl("PORTAL_OIDC_ISSUER", issuerValue);
  const redirectUrl = configuredUrl("PORTAL_OIDC_REDIRECT_URI", redirectValue);
  const jwksUrl = configuredUrl("PORTAL_OIDC_JWKS_URL", jwksValue);
  const apiUrl = configuredUrl("INTERVIEW_API_BASE_URL", apiValue);
  const appUrl = configuredUrl("NEXT_PUBLIC_APP_URL", appValue);
  const issuer = `${issuerUrl.toString().replace(/\/$/, "")}/`;
  const interviewApiBaseUrl = apiUrl.toString().replace(/\/$/, "");
  const homeValue = configuredValue("PORTAL_HOME_URL") || `${issuer}portal/welcome/`;
  const homeUrl = configuredUrl("PORTAL_HOME_URL", homeValue);
  if (jwksUrl.origin !== issuerUrl.origin || homeUrl.origin !== issuerUrl.origin) {
    throw new Error("Portal JWKS and home URLs must use the issuer origin");
  }
  if (redirectUrl.pathname !== "/api/auth/callback") {
    throw new Error("PORTAL_OIDC_REDIRECT_URI must target /api/auth/callback");
  }
  if (appUrl.origin !== redirectUrl.origin) {
    throw new Error("PORTAL_OIDC_REDIRECT_URI must use the application origin");
  }

  return {
    issuer,
    clientId,
    redirectUri: redirectUrl.toString(),
    interviewApiBaseUrl,
    portalHomeUrl: homeUrl.toString(),
    authorizeUrl: new URL("portal/oauth/authorize", issuer).toString(),
    tokenUrl: new URL("portal/oauth/token", issuer).toString(),
    jwksUrl: jwksUrl.toString(),
  };
}

export function createPkcePair(): { verifier: string; challenge: string; state: string; nonce: string } {
  const verifier = randomBytes(32).toString("base64url");
  const challenge = createHash("sha256").update(verifier).digest("base64url");
  const state = randomBytes(16).toString("base64url");
  const nonce = randomBytes(32).toString("base64url");
  return { verifier, challenge, state, nonce };
}

function cookieName(name: string): string {
  return process.env.NODE_ENV === "production" ? `__Host-${name}` : name;
}

function cookieFlags(maxAgeSeconds: number): string {
  const secure = process.env.NODE_ENV === "production" ? "; Secure" : "";
  return `Path=/; HttpOnly; SameSite=Lax; Priority=High; Max-Age=${maxAgeSeconds}${secure}`;
}

function cookie(name: string, value: string, maxAgeSeconds: number): string {
  return `${cookieName(name)}=${encodeURIComponent(value)}; ${cookieFlags(maxAgeSeconds)}`;
}

function signCookieValue(purpose: string, encoded: string): string {
  return createHmac("sha256", sessionSecret())
    .update(`portal-cookie:v1:${purpose}:${encoded}`)
    .digest("base64url");
}

function sealCookieValue(purpose: string, value: unknown): string {
  const encoded = Buffer.from(JSON.stringify(value), "utf8").toString("base64url");
  return `${encoded}.${signCookieValue(purpose, encoded)}`;
}

function unsealCookieValue(purpose: string, raw: string): unknown | null {
  const [encoded, receivedSignature, extra] = raw.split(".");
  if (!encoded || !receivedSignature || extra || encoded.length > 4096
    || !/^[A-Za-z0-9_-]+$/.test(encoded) || !/^[A-Za-z0-9_-]{43}$/.test(receivedSignature)) {
    return null;
  }
  const expected = Buffer.from(signCookieValue(purpose, encoded), "ascii");
  const received = Buffer.from(receivedSignature, "ascii");
  if (expected.length !== received.length || !timingSafeEqual(expected, received)) return null;
  try {
    return JSON.parse(Buffer.from(encoded, "base64url").toString("utf8"));
  } catch {
    return null;
  }
}

export function pkceCookie(
  value: { verifier: string; state: string; nonce: string },
  maxAgeSeconds = 600,
): string {
  return cookie(PKCE_COOKIE, sealCookieValue(PKCE_COOKIE, value), maxAgeSeconds);
}

export function clearPkceCookie(): string {
  return cookie(PKCE_COOKIE, "", 0);
}

export function accessTokenCookie(token: string, maxAgeSeconds: number): string {
  return cookie(ACCESS_COOKIE, token, maxAgeSeconds);
}

export function clearAccessTokenCookie(): string {
  return cookie(ACCESS_COOKIE, "", 0);
}

export function profileCookie(profile: PortalProfile, maxAgeSeconds: number): string {
  return cookie(PROFILE_COOKIE, sealCookieValue(PROFILE_COOKIE, profile), maxAgeSeconds);
}

export function clearProfileCookie(): string {
  return cookie(PROFILE_COOKIE, "", 0);
}

export function readCookie(request: Request, name: string): string | null {
  const header = request.headers.get("cookie") ?? "";
  for (const item of header.split(";")) {
    const [rawName, ...parts] = item.trim().split("=");
    if (rawName !== cookieName(name)) continue;
    try {
      return decodeURIComponent(parts.join("="));
    } catch {
      return null;
    }
  }
  return null;
}

export function readAccessToken(request: Request): string | null {
  const token = readCookie(request, ACCESS_COOKIE);
  return token && token.length <= 8192 && token.split(".").length === 3 ? token : null;
}

export function readProfile(request: Request): PortalProfile | null {
  const raw = readCookie(request, PROFILE_COOKIE);
  if (!raw || raw.length > 4096) return null;
  const parsed = unsealCookieValue(PROFILE_COOKIE, raw) as Partial<PortalProfile> | null;
  if (!parsed || typeof parsed !== "object") return null;
  const displayName = typeof parsed.displayName === "string"
    ? parsed.displayName.trim().slice(0, 200) : "";
  if (!displayName) return null;
  return {
    givenName: typeof parsed.givenName === "string" ? parsed.givenName.trim().slice(0, 100) : "",
    familyName: typeof parsed.familyName === "string" ? parsed.familyName.trim().slice(0, 100) : "",
    displayName,
  };
}

type PortalIdTokenClaims = JWTPayload & {
  nonce?: unknown;
  given_name?: unknown;
  family_name?: unknown;
  name?: unknown;
  email?: unknown;
  azp?: unknown;
};

const remoteJwks = new Map<string, ReturnType<typeof createRemoteJWKSet>>();

function jwksFor(url: string): ReturnType<typeof createRemoteJWKSet> {
  const existing = remoteJwks.get(url);
  if (existing) return existing;
  const created = createRemoteJWKSet(new URL(url), {
    timeoutDuration: 5_000,
    cooldownDuration: 30_000,
    cacheMaxAge: 10 * 60_000,
    headers: { "User-Agent": "intervia-web/0.1" },
  });
  remoteJwks.set(url, created);
  return created;
}

function textClaim(value: unknown, maximum: number): string {
  return typeof value === "string" ? value.trim().slice(0, maximum) : "";
}

export async function profileFromIdToken(
  idToken: string | undefined,
  expectedNonce: string,
  config: PortalOidcConfig,
): Promise<PortalProfile | null> {
  if (!idToken || idToken.length > 8192) throw new Error("id_token_missing");
  const { payload, protectedHeader } = await jwtVerify<PortalIdTokenClaims>(
    idToken,
    jwksFor(config.jwksUrl),
    {
      algorithms: ["RS256"],
      issuer: config.issuer,
      audience: config.clientId,
      requiredClaims: ["sub", "iat", "exp", "nonce"],
      maxTokenAge: 600,
      clockTolerance: 5,
    },
  );
  if (protectedHeader.typ && protectedHeader.typ.toLowerCase() !== "jwt") {
    throw new Error("id_token_type_invalid");
  }
  if (payload.nonce !== expectedNonce) throw new Error("id_token_nonce_invalid");
  if (Array.isArray(payload.aud) && payload.aud.length > 1 && payload.azp !== config.clientId) {
    throw new Error("id_token_authorized_party_invalid");
  }

  const givenName = textClaim(payload.given_name, 100);
  const familyName = textClaim(payload.family_name, 100);
  const displayName = (
    textClaim(payload.name, 200)
    || [givenName, familyName].filter(Boolean).join(" ")
    || textClaim(payload.email, 200)
  ).slice(0, 200);
  return displayName ? { givenName, familyName, displayName } : null;
}

export function readPkcePayload(
  request: Request,
): { verifier: string; state: string; nonce: string } | null {
  const raw = readCookie(request, PKCE_COOKIE);
  if (!raw || raw.length > 1024) return null;
  const parsed = unsealCookieValue(PKCE_COOKIE, raw) as {
    verifier?: unknown; state?: unknown; nonce?: unknown;
  } | null;
  if (!parsed || typeof parsed.verifier !== "string" || typeof parsed.state !== "string"
    || typeof parsed.nonce !== "string" || !/^[A-Za-z0-9_-]{43}$/.test(parsed.verifier)
    || !/^[A-Za-z0-9_-]{22}$/.test(parsed.state)
    || !/^[A-Za-z0-9_-]{43}$/.test(parsed.nonce)) return null;
  return { verifier: parsed.verifier, state: parsed.state, nonce: parsed.nonce };
}

export async function readBoundedJsonObject(
  response: Response,
  maximumBytes: number,
): Promise<Record<string, unknown> | null> {
  const declaredLength = Number(response.headers.get("content-length") ?? "0");
  if (Number.isFinite(declaredLength) && declaredLength > maximumBytes) return null;
  if (!response.body) return null;
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > maximumBytes) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  try {
    const parsed = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed as Record<string, unknown> : null;
  } catch {
    return null;
  }
}

export function noStore<T extends Response>(response: T): T {
  response.headers.set("Cache-Control", "no-store, max-age=0");
  response.headers.set("Pragma", "no-cache");
  response.headers.set("X-Content-Type-Options", "nosniff");
  return response;
}
