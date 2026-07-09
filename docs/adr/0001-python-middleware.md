# ADR-0001: Middleware in Python (FastAPI), not TypeScript

## Status
Accepted (2026-05-21)

## Context

The Saleor App Framework canonically lives on TypeScript (`@saleor/app-sdk` 1.0+, the `saleor/apps` monorepo — Next.js + Vercel). That's Saleor's recommendation.

In parallel we already have Odoo (Python) and a separate payments service (FastAPI). The team is Python-first; a second ecosystem (TS/Node) increases the operational surface, requires a Node runtime in Docker, a separate package manager (pnpm), and separate deploy patterns.

The Saleor App SDK offers conveniences: APL, webhook signature verification, manifest helpers, AppBridge for the dashboard iframe. But we don't need AppBridge (there are no UI extensions in the Saleor Dashboard at this stage — the middleware isn't displayed anywhere, it only receives webhooks and sends GraphQL mutations). What's left is APL + signature + manifest — about 200 lines of Python without the SDK.

## Decision

The middleware is written in **Python 3.12 + FastAPI**, without `@saleor/app-sdk` and without `mirumee/saleor-app-framework-python`.

JWS signature verification uses [`joserfc`](https://github.com/authlib/joserfc) (active, replaces the deprecated `python-jose`). APL is a custom implementation on Redis (~50 LOC, ABC + one backend). Manifest is a pydantic model with jinja-style substitution for the public URL.

Stack: `FastAPI[standard]` + `httpx` (for GraphQL and the Odoo REST API) + `joserfc` + `redis` + `pydantic-settings` + `structlog`.

## Alternatives considered

1. **TypeScript / Next.js + `@saleor/app-sdk` 1.0.** The canonical path. Less custom code for signature/APL/manifest. **Rejected:** a second runtime, a second package manager, an extra Node container. The team is Python-only.

2. **Python with `mirumee/saleor-app-framework-python`.** Would have been a middle ground. **Rejected:** [the authors themselves say](https://mirumee.github.io/saleor-app-framework-python/) it's "still in development, expect things to change." Too risky to put on a production-critical path. Plus it's an extra dependency doing something we can implement ourselves in 200 LOC.

3. **Cloudflare Workers / Deno.** A modern edge runtime, free hosting. **Rejected:** still not Python.

## Consequences

**Pros:**
- One runtime, one package manager (uv), one deploy pipeline.
- Full control over signature verification, retry logic, and observability.
- Transparent code — no "magic" SDK wrappers.
- Easier hiring (there are more Python developers than Saleor-app developers).

**Cons:**
- We maintain JWS verification ourselves — need to track any changes to Saleor's signing scheme.
- No AppBridge — if we ever want a UI extension in the Saleor Dashboard, we'll need to write a separate TS component or migrate the app.
- We don't get API updates from an SDK automatically — we track the Saleor changelog manually.

**Mitigation for the cons:** record in the README the list of Saleor features we depend on (JWS headers, manifest schema version, webhook payload format). On any Saleor upgrade — review the changelog + run integration tests.

See also: [ADR-0002](0002-no-saleor-app-sdk.md).
