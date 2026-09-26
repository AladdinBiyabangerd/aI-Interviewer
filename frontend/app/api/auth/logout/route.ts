import {
  clearAccessTokenCookie,
  clearPkceCookie,
  clearProfileCookie,
  noStore,
} from "../../../../lib/server/portal-oidc.ts";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const configuredAppUrl = process.env.NEXT_PUBLIC_APP_URL?.trim();
  const redirectBase = configuredAppUrl && /^https?:\/\//i.test(configuredAppUrl)
    ? configuredAppUrl : request.url;
  const response = new Response(null, {
    status: 303,
    headers: { Location: new URL("/", redirectBase).toString() },
  });
  response.headers.append("Set-Cookie", clearAccessTokenCookie());
  response.headers.append("Set-Cookie", clearPkceCookie());
  response.headers.append("Set-Cookie", clearProfileCookie());
  return noStore(response);
}
