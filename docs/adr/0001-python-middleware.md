# ADR-0001: Middleware на Python (FastAPI), не TypeScript

## Status
Accepted (2026-05-21)

## Context

Saleor App Framework канонически живёт на TypeScript (`@saleor/app-sdk` 1.0+, `saleor/apps` monorepo — Next.js + Vercel). Это рекомендация Saleor.

Параллельно у нас Odoo (Python) и существующий `payments/` сервис (FastAPI). Команда — Python-first; вторая экосистема (TS/Node) увеличивает операционную поверхность, требует Node runtime в Docker, отдельный package manager (pnpm), отдельные паттерны deploy.

Saleor App SDK даёт удобства: APL, webhook signature verification, manifest helpers, AppBridge для дашборд-iframe. Но AppBridge нам не нужен (нет UI extensions в Saleor Dashboard в Phase 3 — middleware никем не отображается, только принимает webhooks и шлёт GraphQL). Остаётся APL + signature + manifest — это ~200 строк Python без SDK.

## Decision

Middleware пишем на **Python 3.12 + FastAPI**, без `@saleor/app-sdk` и без `mirumee/saleor-app-framework-python`.

JWS signature verification — через [`joserfc`](https://github.com/authlib/joserfc) (active, replaces deprecated `python-jose`). APL — собственная реализация на Redis (~50 LOC, ABC + один backend). Manifest — pydantic-модель + jinja-style substitution для public URL.

Stack: `FastAPI[standard]` + `httpx` (для GraphQL и Odoo REST) + `joserfc` + `redis` + `pydantic-settings` + `structlog`.

## Alternatives considered

1. **TypeScript / Next.js + `@saleor/app-sdk` 1.0.** Канон. Меньше своего кода для signature/APL/manifest. **Отброшено:** второй runtime, второй package manager, лишний Node-контейнер. Команда Python-only.

2. **Python с `mirumee/saleor-app-framework-python`.** Был бы middle ground. **Отброшено:** [сами авторы пишут](https://mirumee.github.io/saleor-app-framework-python/) "still in development, expect things to change". Брать в production-критичный путь рискованно. Плюс — лишняя зависимость, которая делает то, что мы можем сами за 200 LOC.

3. **Cloudflare Workers / Deno.** Современная edge-runtime, бесплатный hosting. **Отброшено:** опять не Python.

## Consequences

**Pros:**
- Один runtime, один package manager (uv), один deploy pipeline.
- Полный контроль над сигнатурной верификацией, retry-логикой, observability.
- Прозрачный код — никаких "магических" SDK-обёрток.
- Легче нанимать (Python-developers больше, чем Saleor-app-developers).

**Cons:**
- Сами поддерживаем JWS verification — при изменениях в Saleor подписях надо отслеживать.
- Нет AppBridge — если в будущем захотим UI extension в Saleor Dashboard, придётся писать TS-компонент отдельно или мигрировать App.
- Не получим обновления API из SDK автоматически — следим за Saleor changelog вручную.

**Mitigation для cons:** в README зафиксировать список Saleor-feature'ов, на которые мы подписаны (JWS headers, manifest schema version, webhook payload format). При обновлении Saleor — review changelog + integration tests.

См. также: [ADR-0002](0002-no-saleor-app-sdk.md).
