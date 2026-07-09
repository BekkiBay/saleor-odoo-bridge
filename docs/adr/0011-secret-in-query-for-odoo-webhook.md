# ADR-0011: Secret in the URL query string for outbound Odoo → middleware webhooks

## Status
Accepted (2026-05-23)

## Context

For the reverse flow, changes to `product.template` / `product.category` in Odoo
need to reach the middleware (`POST /api/odoo-events`), which enqueues a job in arq
and pushes it to Saleor.

The trigger on the Odoo side is `base.automation` (`on_create_or_write`) → a server
action. The call into the middleware needs to be authenticated, so that
`/api/odoo-events` can't be hit by just anyone.

Options for delivering the secret:

1. **An HMAC signature over the body, in a header** (the way Saleor signs its own
   webhooks, see `saleor/signature.py`). The most robust: the body can't be tampered
   with, and replay is time-bounded.
2. **A bearer token in the `Authorization` header.**
3. **A secret in the query parameter `?secret=...`.**

Odoo's constraint: the native webhook server action (`state='webhook'`) **cannot**
send custom headers — only a URL and a list of fields. To get both an outbox record
and echo-loop protection, we instead write a `state='code'` (Python) server action
that performs the `POST` itself. Custom headers are technically reachable from that
code, but we deliberately stick with a query secret for simplicity and consistency
with what Odoo supports out of the box.

## Decision

**The secret is passed as a query parameter:**

```
POST {saleor_sync.middleware_url}/api/odoo-events?secret={saleor_sync.webhook_secret}
Body: {"odoo_model": "...", "odoo_id": N, "action": "create|write|unlink"}
```

- `webhook_secret` is stored in `ir.config_parameter` (`saleor_sync.webhook_secret`),
  sourced from env `BRIDGE_ODOO_WEBHOOK_SECRET` (the middleware uses the same secret
  via its own `BRIDGE_ODOO_WEBHOOK_SECRET`).
- The middleware compares it in constant time (`hmac.compare_digest`); on a mismatch
  it returns 401.
- The Odoo→middleware connection runs over the internal docker network
  (`http://middleware:8080`) and never leaves it. A query secret appearing in
  reverse-proxy logs is an acceptable risk for an internal hop; for production, an
  HTTPS tunnel closes off interception.

## Alternatives considered

- **HMAC (option 1).** More robust, but more complex: requires sharing a key,
  serializing the body deterministically, and checking a timestamp. Deferred to a
  future iteration (an extended action with a signature). The benefit is small for
  an internal hop behind a reverse proxy.
- **Bearer header (option 2).** Roughly as secure as the query secret, but requires
  explicitly adding a header; there's no real advantage over the query parameter
  given the hop is internal.

## Consequences

**Pros:** minimal code, easy to debug with `curl`, and the secret rotates through a
single config parameter + env var.

**Cons:** the secret is visible in the URL (proxy access logs). No protection
against replay or body tampering. This is acceptable because the call is internal
and the body is only `(model, id, action)`; the middleware always re-reads the
current record from Odoo by `id` before pushing anything (Odoo remains the source
of truth, per ADR-0006), so a forged body can't result in forged data being written.

**Future migration:** replace `?secret=` with an HMAC header + timestamp; the
endpoint would accept both during a transition period.
