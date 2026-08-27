# ADR 0004: OIDC resource server and minimal local identity

- **Status:** Accepted for Phase 0C-A
- **Date:** 2026-08-23

## Context

The platform needs an account/owner boundary before it can receive candidate data. Implementing passwords, password recovery, MFA, and credential-breach controls locally would add a high-risk security subsystem unrelated to the interview product. At the same time, trusting arbitrary decoded JWT claims or a provider-specific user identifier would make cross-user isolation fragile.

## Decision

The API is an OAuth 2.0 resource server and accepts only operator-configured, audience-restricted JWT access tokens from one OIDC issuer. It does not accept ID tokens and does not implement a password database.

The contract follows [OAuth 2.0 Security Best Current Practice (RFC 9700)](https://datatracker.ietf.org/doc/html/rfc9700), [JWT Access Token Profile (RFC 9068)](https://datatracker.ietf.org/doc/html/rfc9068), [JWT Best Current Practices (RFC 8725)](https://datatracker.ietf.org/doc/html/rfc8725), and [Bearer Token Usage (RFC 6750)](https://datatracker.ietf.org/doc/html/rfc6750):

- production requires explicit HTTPS issuer and JWKS URLs plus an exact API audience;
- signing algorithms are an operator allowlist that must include `RS256`; symmetric algorithms and `none` are forbidden;
- the protected header must contain a bounded `kid` and the explicit `at+jwt` type, preventing ID-token confusion;
- signature, issuer, audience, expiry, issued-at time, subject, client ID, token ID, token age, and scope syntax are validated;
- JWKS lookup has bounded network time, short-lived set caching, and refresh-on-unknown-key behavior supplied by PyJWT;
- bearer values and untrusted verifier details never enter responses, logs, audit metadata, or the database;
- invalid credentials return RFC-compatible `WWW-Authenticate` challenges; authenticated-but-under-scoped calls return `insufficient_scope`;
- authorization is scope-first and owner-second. A cross-owner lookup is represented as not found to avoid resource enumeration.

The only persisted identity attributes are a generated UUIDv7 account ID, exact issuer, exact subject, local active/disabled status, version, and timestamps. Email, name, avatar, groups, full token claims, access tokens, refresh tokens, and signing keys are not persisted. A unique issuer/subject constraint makes concurrent first-login provisioning idempotent, and the provisioning event is appended to the audit table in the same transaction.

## Boundaries and later decisions

- The browser authorization-code/PKCE flow and concrete identity provider are selected with the frontend and deployment environment. The API contract does not provide an implicit flow or accept browser credentials directly.
- Bearer tokens are audience- and lifetime-restricted. DPoP or mTLS sender-constrained tokens require compatible client/provider selection and must be evaluated before the public production gate; the verifier/service interfaces allow that adapter to be introduced without changing domain repositories.
- Provider-side policy must grant user scopes only to approved user authorization flows. Machine/service identities require a separate account type and policy; they are not silently treated as candidate accounts.
- Account deletion, subject unlinking/relinking, consent, retention, export, and backup expiry belong to Phase 0C-B. Until then, accounts can only be active or administratively disabled.
- Object storage, uploads, quarantine, malware scanning, and runtime secret delivery belong to Phase 0C-C.

## Consequences

- A valid external token does not by itself authorize access; endpoint scopes and local account status still apply.
- Identity-provider availability is needed when a signing key is not cached. Key lookup failures fail closed without exposing network details.
- Pairwise OIDC subjects are preferred because the database deliberately treats the issuer/subject pair as pseudonymous personal data.
- Production configuration cannot start with authentication disabled.
