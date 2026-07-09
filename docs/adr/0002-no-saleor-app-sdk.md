# ADR-0002: A thin custom Saleor App without an SDK

## Status
Accepted (2026-05-21)

## Context

Related to [ADR-0001](0001-python-middleware.md). After choosing Python, the question remains: use `mirumee/saleor-app-framework-python` or write it ourselves.

The Saleor App framework does three things:
1. **Manifest serving** — an endpoint that returns JSON matching Saleor's schema.
2. **Token exchange** — accepting `POST /api/register` with `auth_token` and `saleor_domain`, and persisting it in the APL.
3. **Webhook signature verification** — JWS RS256 detached, with the public key from JWKS.

Each of these is a small amount of code (50-200 LOC).

## Decision

We don't use any Saleor App SDK. We implement all three components ourselves:

1. **Manifest** — a pydantic model with `model_dump()`, jinja-style substitution of `{public_url}` via `Settings.middleware_public_url`.
2. **Token exchange** — a simple FastAPI endpoint, `await apl.set("app:" + domain, token)`.
3. **JWS verification** — `joserfc.jws.deserialize_compact(raw_body, key=jwks)`, where `jwks` is fetched from `{saleor_url}/.well-known/jwks.json` and cached for 1 hour.

APL is an abstract base class plus a Redis implementation (~50 LOC).

## Alternatives considered

1. **`mirumee/saleor-app-framework-python`.** "Still in development." Too risky for a production-critical path. See ADR-0001.
2. **Relying on `@saleor/app-sdk` via a Python ↔ Node bridge.** Impractical, not seriously considered.

## Consequences

**Pros:**
- Full control, minimal dependencies.
- We can add custom observability (structlog with a trace_id on every step).
- Easy testing — no SDK mocks, all real unit tests.

**Cons:**
- If Saleor changes its signature scheme (e.g., in 4.0), we need to patch it by hand. An SDK would pick this up via auto-update.
- We need to know the spec ourselves — the expected behavior has to be documented in code comments.

**Mitigation:** cover signature verification with unit tests using real JWS payloads (stored in `tests/fixtures/`). If Saleor changes its scheme, the tests fail — not production.

**Fallback to HMAC-SHA256.** The original design spec called for a fallback: if a Saleor instance has `secretKey` enabled (legacy mode, deprecated in Saleor 4.0), it should be supported as a fallback. Implementation: if the `Saleor-HMAC-SHA256` header is present and `Saleor-Signature` is absent, verify via HMAC-SHA256 with a secret from the environment. Decision: only JWS is implemented for now; the HMAC fallback is deferred (our Saleor 3.23 instance supports JWS).
