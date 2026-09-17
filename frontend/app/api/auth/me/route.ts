import { NextResponse } from "next/server";

import {
  portalOidcConfig,
  portalOidcConfigured,
  readAccessToken,
  readProfile,
} from "../../../../lib/server/portal-oidc";

export const runtime = "nodejs";

export async function GET(request: Request) {
  if (!portalOidcConfigured()) {
    return NextResponse.json({ authenticated: false, reason: "not_configured" }, { status: 200 });
  }

  const config = portalOidcConfig();
  const token = readAccessToken(request);
  if (!token) {
    return NextResponse.json({
      authenticated: false,
      portal_url: config.portalHomeUrl,
    }, { status: 200 });
  }

  const upstream = await fetch(`${config.interviewApiBaseUrl}/api/v1/identity/me`, {
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/json",
    },
    cache: "no-store",
  });

  if (!upstream.ok) {
    return NextResponse.json(
      {
        authenticated: false,
        reason: "upstream",
        status: upstream.status,
        portal_url: config.portalHomeUrl,
      },
      { status: 200 },
    );
  }

  const data = (await upstream.json()) as { account_id?: string };
  const profile = readProfile(request);
  return NextResponse.json({
    authenticated: true,
    account_id: data.account_id ?? null,
    given_name: profile?.givenName ?? "",
    family_name: profile?.familyName ?? "",
    display_name: profile?.displayName ?? "",
    portal_url: config.portalHomeUrl,
  });
}
