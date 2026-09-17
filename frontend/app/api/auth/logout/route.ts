import { NextResponse } from "next/server";

import {
  clearAccessTokenCookie,
  clearPkceCookie,
  clearProfileCookie,
} from "../../../../lib/server/portal-oidc";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const response = NextResponse.redirect(new URL("/", request.url), 303);
  response.headers.append("Set-Cookie", clearAccessTokenCookie());
  response.headers.append("Set-Cookie", clearPkceCookie());
  response.headers.append("Set-Cookie", clearProfileCookie());
  return response;
}

export async function GET(request: Request) {
  return POST(request);
}
