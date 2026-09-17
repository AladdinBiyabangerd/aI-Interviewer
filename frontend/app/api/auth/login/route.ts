import { NextResponse } from "next/server";

import {
  createPkcePair,
  pkceCookie,
  portalOidcConfig,
  portalOidcConfigured,
} from "../../../../lib/server/portal-oidc";

export const runtime = "nodejs";

export async function GET() {
  if (!portalOidcConfigured()) {
    return NextResponse.json(
      { error: "portal_oidc_not_configured" },
      { status: 503 },
    );
  }

  const config = portalOidcConfig();
  const { verifier, challenge, state } = createPkcePair();
  const params = new URLSearchParams({
    response_type: "code",
    client_id: config.clientId,
    redirect_uri: config.redirectUri,
    scope: "openid profile:read preparation:read preparation:write privacy:read privacy:write",
    state,
    code_challenge: challenge,
    code_challenge_method: "S256",
  });

  const response = NextResponse.redirect(`${config.authorizeUrl}?${params.toString()}`, 302);
  response.headers.append(
    "Set-Cookie",
    pkceCookie(JSON.stringify({ verifier, state })),
  );
  return response;
}
