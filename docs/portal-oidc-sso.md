# Portal OIDC SSO (ingress-academy issuer)

The frontend exposes an optional Portal login through `/api/auth/*`. It uses the
OAuth authorization-code flow with PKCE and an OIDC nonce, verifies ID-token signature
and claims against the Portal JWKS, and keeps the access token in a server-only,
`HttpOnly` cookie. The standalone `/admin/login` flow remains separate.

The interview API is an OAuth 2.0 **resource server**. It does not implement login.
Point it at the portal issuer documented in
`ingress-academy/docs/oidc-issuer.md`.

## Local coordinates

On **portal** (Django, typically `:8000`):

```env
OIDC_ISSUER=http://127.0.0.1:8000/
OIDC_INTERVIEW_AUDIENCE=http://127.0.0.1:8001
OIDC_INTERVIEW_REDIRECT_URIS=http://localhost:3000/api/auth/callback,http://127.0.0.1:3000/api/auth/callback
```

On **interview API** (FastAPI, audience must match portal client `audience`):

```env
AI_INTERVIEWER_AUTH_ENABLED=true
AI_INTERVIEWER_AUTH_OIDC_ISSUER=http://127.0.0.1:8000/
AI_INTERVIEWER_AUTH_OIDC_AUDIENCE=http://127.0.0.1:8001
AI_INTERVIEWER_AUTH_OIDC_JWKS_URL=http://127.0.0.1:8000/portal/oauth/jwks.json
```

`iss` strings must match **including the trailing slash**.

On **interview frontend** (Next.js `:3000`):

```env
NEXT_PUBLIC_APP_URL=http://localhost:3000
PORTAL_OIDC_ISSUER=http://127.0.0.1:8000/
PORTAL_OIDC_ENABLED=true
PORTAL_OIDC_CLIENT_ID=interview-web
PORTAL_OIDC_REDIRECT_URI=http://localhost:3000/api/auth/callback
PORTAL_OIDC_JWKS_URL=http://127.0.0.1:8000/portal/oauth/jwks.json
INTERVIEW_API_BASE_URL=http://127.0.0.1:8001
```

## Production coordinates

Portal:

```env
OIDC_ISSUER=https://ingress.academy/
OIDC_INTERVIEW_AUDIENCE=https://api.interview.ingress.academy
OIDC_INTERVIEW_REDIRECT_URIS=https://interview.ingress.academy/api/auth/callback
```

Interview API:

```env
AI_INTERVIEWER_AUTH_ENABLED=true
AI_INTERVIEWER_AUTH_OIDC_ISSUER=https://ingress.academy/
AI_INTERVIEWER_AUTH_OIDC_AUDIENCE=https://api.interview.ingress.academy
AI_INTERVIEWER_AUTH_OIDC_JWKS_URL=https://ingress.academy/portal/oauth/jwks.json
```

Vercel frontend:

```env
PORTAL_OIDC_ISSUER=https://ingress.academy/
PORTAL_OIDC_ENABLED=true
PORTAL_OIDC_CLIENT_ID=interview-web
PORTAL_OIDC_REDIRECT_URI=https://interview.ingress.academy/api/auth/callback
PORTAL_OIDC_JWKS_URL=https://ingress.academy/portal/oauth/jwks.json
INTERVIEW_API_BASE_URL=https://api.interview.ingress.academy
PORTAL_HOME_URL=https://ingress.academy/portal/welcome/
NEXT_PUBLIC_APP_URL=https://interview.ingress.academy
```

Before enabling production auth, both custom domains must resolve over HTTPS, the Portal
must list the exact callback URI, its JWKS endpoint must return a valid key set, and the
API `/api/v1/identity/me` route must accept a Portal access token whose `iss`, `aud`, and
`typ` match the values above. Keep `PORTAL_OIDC_ENABLED=false` while any prerequisite is
unavailable; the frontend then hides the login control and returns `not_configured` from
`/api/auth/me`.

## Smoke: access token → `/api/v1/identity/me`

1. Log into the portal in a browser.
2. Complete PKCE via the frontend “Sign in with Ingress” control, **or** obtain an
   access token from `POST /portal/oauth/token` after authorize.
3. Call:

```bash
export ACCESS_TOKEN='…'
uv run python scripts/smoke_portal_oidc.py
```

Expected JSON: `{ "account_id": "<uuid>" }` (scope `profile:read` required).

Portal login is additive to the anonymous Java assessment. Authentication can later be
made mandatory at the product boundary without changing the OIDC exchange itself.
