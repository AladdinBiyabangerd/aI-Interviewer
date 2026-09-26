import assert from "node:assert/strict";
import test from "node:test";

import { exportJWK, generateKeyPair, SignJWT } from "jose";

import { GET as callback } from "../app/api/auth/callback/route.ts";
import { GET as login } from "../app/api/auth/login/route.ts";
import { GET as me } from "../app/api/auth/me/route.ts";
import {
  portalOidcConfigurationIssue,
  readProfile,
} from "../lib/server/portal-oidc.ts";

const managedEnvironment = [
  "NODE_ENV",
  "INTERVIEW_SESSION_SECRET",
  "NEXT_PUBLIC_APP_URL",
  "PORTAL_OIDC_ENABLED",
  "PORTAL_OIDC_ISSUER",
  "PORTAL_OIDC_CLIENT_ID",
  "PORTAL_OIDC_REDIRECT_URI",
  "PORTAL_OIDC_JWKS_URL",
  "INTERVIEW_API_BASE_URL",
  "PORTAL_HOME_URL",
];
const originalEnvironment = Object.fromEntries(
  managedEnvironment.map((name) => [name, process.env[name]]),
);
const originalFetch = globalThis.fetch;
let sequence = 0;

function restoreEnvironment() {
  for (const name of managedEnvironment) {
    const original = originalEnvironment[name];
    if (original === undefined) delete process.env[name];
    else process.env[name] = original;
  }
  globalThis.fetch = originalFetch;
}

function configure() {
  sequence += 1;
  const suffix = sequence;
  const coordinates = {
    app: `https://app-${suffix}.example.test`,
    issuer: `https://portal-${suffix}.example.test/`,
    api: `https://api-${suffix}.example.test`,
    clientId: "interview-web",
  };
  process.env.NODE_ENV = "production";
  process.env.INTERVIEW_SESSION_SECRET = "test-session-secret-with-at-least-32-bytes";
  process.env.NEXT_PUBLIC_APP_URL = coordinates.app;
  process.env.PORTAL_OIDC_ENABLED = "true";
  process.env.PORTAL_OIDC_ISSUER = coordinates.issuer;
  process.env.PORTAL_OIDC_CLIENT_ID = coordinates.clientId;
  process.env.PORTAL_OIDC_REDIRECT_URI = `${coordinates.app}/api/auth/callback`;
  process.env.PORTAL_OIDC_JWKS_URL = `${coordinates.issuer}portal/oauth/jwks.json`;
  process.env.INTERVIEW_API_BASE_URL = coordinates.api;
  process.env.PORTAL_HOME_URL = `${coordinates.issuer}portal/welcome/`;
  return coordinates;
}

function cookiePair(setCookie) {
  return setCookie.split(";", 1)[0];
}

async function beginLogin() {
  const response = await login();
  assert.equal(response.status, 302);
  assert.equal(response.headers.get("cache-control"), "no-store, max-age=0");
  const location = new URL(response.headers.get("location"));
  const setCookie = response.headers.get("set-cookie");
  assert.ok(setCookie);
  assert.match(setCookie, /^__Host-portal_oidc_pkce=/);
  assert.match(setCookie, /HttpOnly/);
  assert.match(setCookie, /Secure/);
  assert.match(setCookie, /SameSite=Lax/);
  assert.equal(location.searchParams.get("response_type"), "code");
  assert.equal(location.searchParams.get("code_challenge_method"), "S256");
  assert.match(location.searchParams.get("state") ?? "", /^[A-Za-z0-9_-]{22}$/);
  assert.match(location.searchParams.get("nonce") ?? "", /^[A-Za-z0-9_-]{43}$/);
  return { location, cookie: cookiePair(setCookie) };
}

async function signedTokens(coordinates, nonce) {
  const { privateKey, publicKey } = await generateKeyPair("RS256", { extractable: true });
  const jwk = await exportJWK(publicKey);
  Object.assign(jwk, { alg: "RS256", kid: "test-key", use: "sig" });
  const now = Math.floor(Date.now() / 1000);
  const idToken = await new SignJWT({
    nonce,
    given_name: "Aylin",
    family_name: "Məmmədova",
    name: "Aylin Məmmədova",
  })
    .setProtectedHeader({ alg: "RS256", kid: "test-key", typ: "JWT" })
    .setIssuer(coordinates.issuer)
    .setAudience(coordinates.clientId)
    .setSubject("portal-user-1")
    .setIssuedAt(now)
    .setExpirationTime(now + 300)
    .sign(privateKey);
  const accessToken = await new SignJWT({ client_id: coordinates.clientId })
    .setProtectedHeader({ alg: "RS256", kid: "test-key", typ: "at+jwt" })
    .setIssuer(coordinates.issuer)
    .setAudience(coordinates.api)
    .setSubject("portal-user-1")
    .setIssuedAt(now)
    .setExpirationTime(now + 300)
    .sign(privateKey);
  return { accessToken, idToken, jwk };
}

function installProviderFetch(coordinates, tokens) {
  globalThis.fetch = async (input, init) => {
    const url = String(input);
    if (url === `${coordinates.issuer}portal/oauth/token`) {
      assert.equal(init?.method, "POST");
      const body = init?.body;
      assert.ok(body instanceof URLSearchParams);
      assert.equal(body.get("grant_type"), "authorization_code");
      assert.match(body.get("code_verifier") ?? "", /^[A-Za-z0-9_-]{43}$/);
      return Response.json({
        access_token: tokens.accessToken,
        id_token: tokens.idToken,
        token_type: "Bearer",
        expires_in: 300,
      });
    }
    if (url === `${coordinates.issuer}portal/oauth/jwks.json`) {
      return Response.json({ keys: [tokens.jwk] });
    }
    if (url === `${coordinates.api}/api/v1/identity/me`) {
      assert.match(new Headers(init?.headers).get("authorization") ?? "", /^Bearer ey/);
      return Response.json({ account_id: "018f47ac-7c58-7b7d-8e5d-2f5c7dfbb600" });
    }
    throw new Error(`Unexpected fetch: ${url}`);
  };
}

test.afterEach(restoreEnvironment);

test("enabled Portal login fails readiness validation when a required coordinate is missing", () => {
  configure();
  delete process.env.PORTAL_OIDC_JWKS_URL;
  assert.equal(portalOidcConfigurationIssue(), "Portal OIDC environment is incomplete");
});

test("Portal code flow validates nonce and ID-token signature before creating cookies", async () => {
  const coordinates = configure();
  const started = await beginLogin();
  const tokens = await signedTokens(coordinates, started.location.searchParams.get("nonce"));
  installProviderFetch(coordinates, tokens);

  const response = await callback(new Request(
    `${coordinates.app}/api/auth/callback?code=authorization-code&state=${started.location.searchParams.get("state")}`,
    { headers: { Cookie: started.cookie } },
  ));
  assert.equal(response.status, 307);
  assert.equal(response.headers.get("location"), `${coordinates.app}/?sso=ok`);
  assert.equal(response.headers.get("cache-control"), "no-store, max-age=0");
  const setCookies = response.headers.getSetCookie();
  assert.ok(setCookies.some((value) => value.startsWith("__Host-portal_access_token=")));
  assert.ok(setCookies.some((value) => value.startsWith("__Host-portal_profile=")));

  const requestCookie = setCookies.map(cookiePair).join("; ");
  const profile = readProfile(new Request(`${coordinates.app}/`, { headers: { Cookie: requestCookie } }));
  assert.deepEqual(profile, {
    givenName: "Aylin",
    familyName: "Məmmədova",
    displayName: "Aylin Məmmədova",
  });

  const meResponse = await me(new Request(`${coordinates.app}/api/auth/me`, {
    headers: { Cookie: requestCookie },
  }));
  assert.equal(meResponse.status, 200);
  assert.deepEqual(await meResponse.json(), {
    authenticated: true,
    account_id: "018f47ac-7c58-7b7d-8e5d-2f5c7dfbb600",
    given_name: "Aylin",
    family_name: "Məmmədova",
    display_name: "Aylin Məmmədova",
    portal_url: `${coordinates.issuer}portal/welcome/`,
  });
});

test("Portal callback rejects a validly signed ID token with the wrong nonce", async () => {
  const coordinates = configure();
  const started = await beginLogin();
  const tokens = await signedTokens(coordinates, "x".repeat(43));
  installProviderFetch(coordinates, tokens);

  const response = await callback(new Request(
    `${coordinates.app}/api/auth/callback?code=authorization-code&state=${started.location.searchParams.get("state")}`,
    { headers: { Cookie: started.cookie } },
  ));
  assert.equal(response.status, 307);
  assert.equal(response.headers.get("location"), `${coordinates.app}/?sso_error=invalid_id_token`);
  assert.ok(response.headers.getSetCookie().some((value) => (
    value.startsWith("__Host-portal_access_token=") && value.includes("Max-Age=0")
  )));
});

test("Portal callback rejects state mismatch before contacting the provider", async () => {
  const coordinates = configure();
  const started = await beginLogin();
  globalThis.fetch = async () => { throw new Error("fetch must not run"); };

  const response = await callback(new Request(
    `${coordinates.app}/api/auth/callback?code=authorization-code&state=wrong-state`,
    { headers: { Cookie: started.cookie } },
  ));
  assert.equal(response.status, 307);
  assert.equal(response.headers.get("location"), `${coordinates.app}/?sso_error=invalid_callback`);
});

test("Portal callback turns a malformed token response into a bounded safe error", async () => {
  const coordinates = configure();
  const started = await beginLogin();
  globalThis.fetch = async (input) => {
    const url = String(input);
    if (url === `${coordinates.issuer}portal/oauth/token`) {
      return new Response("not-json", { status: 200, headers: { "Content-Type": "application/json" } });
    }
    throw new Error(`Unexpected fetch: ${url}`);
  };

  const response = await callback(new Request(
    `${coordinates.app}/api/auth/callback?code=authorization-code&state=${started.location.searchParams.get("state")}`,
    { headers: { Cookie: started.cookie } },
  ));
  assert.equal(response.status, 307);
  assert.equal(response.headers.get("location"), `${coordinates.app}/?sso_error=invalid_token_response`);
});

test("tampering with the signed Portal profile cookie is rejected", async () => {
  const coordinates = configure();
  const started = await beginLogin();
  const tokens = await signedTokens(coordinates, started.location.searchParams.get("nonce"));
  installProviderFetch(coordinates, tokens);
  const response = await callback(new Request(
    `${coordinates.app}/api/auth/callback?code=authorization-code&state=${started.location.searchParams.get("state")}`,
    { headers: { Cookie: started.cookie } },
  ));
  const profileCookie = response.headers.getSetCookie()
    .map(cookiePair)
    .find((value) => value.startsWith("__Host-portal_profile="));
  assert.ok(profileCookie);
  const finalCharacter = profileCookie.at(-1) === "a" ? "b" : "a";
  const tampered = `${profileCookie.slice(0, -1)}${finalCharacter}`;
  assert.equal(readProfile(new Request(`${coordinates.app}/`, {
    headers: { Cookie: tampered },
  })), null);
});
