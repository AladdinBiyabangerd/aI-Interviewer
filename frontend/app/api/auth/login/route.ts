import {
  createPkcePair,
  noStore,
  pkceCookie,
  portalOidcConfig,
  portalOidcConfigured,
} from "../../../../lib/server/portal-oidc.ts";

export const runtime = "nodejs";

export async function GET() {
  if (!portalOidcConfigured()) {
    return noStore(Response.json({ error: "portal_oidc_not_configured" }, { status: 503 }));
  }

  const config = portalOidcConfig();
  const { verifier, challenge, state, nonce } = createPkcePair();
  const params = new URLSearchParams({
    response_type: "code",
    client_id: config.clientId,
    redirect_uri: config.redirectUri,
    scope: "openid profile:read preparation:read preparation:write privacy:read privacy:write",
    state,
    nonce,
    code_challenge: challenge,
    code_challenge_method: "S256",
  });

  const response = new Response(null, {
    status: 302,
    headers: { Location: `${config.authorizeUrl}?${params.toString()}` },
  });
  response.headers.append("Set-Cookie", pkceCookie({ verifier, state, nonce }));
  return noStore(response);
}
