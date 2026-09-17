# Portal OIDC SSO (ingress-academy issuer)

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
PORTAL_OIDC_ISSUER=http://127.0.0.1:8000/
PORTAL_OIDC_CLIENT_ID=interview-web
PORTAL_OIDC_REDIRECT_URI=http://localhost:3000/api/auth/callback
INTERVIEW_API_BASE_URL=http://127.0.0.1:8001
```

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

The Next.js Java assessment still uses anonymous signed cookies; portal SSO is an
additive proof path via `/api/auth/*` and does not migrate assessment ownership yet.
