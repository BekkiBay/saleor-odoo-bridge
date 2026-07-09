# ADR-0002: Тонкий собственный Saleor App без SDK

## Status
Accepted (2026-05-21)

## Context

Связано с [ADR-0001](0001-python-middleware.md). После выбора Python остаётся вопрос: использовать `mirumee/saleor-app-framework-python` или писать самим.

Saleor App framework делает три вещи:
1. **Manifest serving** — endpoint возвращает JSON по схеме Saleor.
2. **Token exchange** — приём `POST /api/register` с `auth_token` и `saleor_domain`, persist в APL.
3. **Webhook signature verification** — JWS RS256 detached, public key из JWKS.

Каждое — небольшой объём кода (50-200 LOC).

## Decision

Не использовать никакой Saleor App SDK. Реализуем три компонента сами:

1. **Manifest** — pydantic-модель с `model_dump()`, jinja-style substitution `{public_url}` через `Settings.middleware_public_url`.
2. **Token exchange** — простой FastAPI endpoint, `await apl.set("app:" + domain, token)`.
3. **JWS verification** — `joserfc.jws.deserialize_compact(raw_body, key=jwks)` где `jwks` фетчим из `{saleor_url}/.well-known/jwks.json` и кэшируем 1 час.

APL — abstract base class + Redis implementation (~50 LOC).

## Alternatives considered

1. **`mirumee/saleor-app-framework-python`.** "Still in development". Брать на production-критический путь — риск. См. ADR-0001.
2. **Опираться на `@saleor/app-sdk` через Python ↔ Node bridge.** Дико, не рассматривали серьёзно.

## Consequences

**Pros:**
- Полный контроль, минимум зависимостей.
- Можем добавить кастомную observability (structlog с trace_id на каждом шаге).
- Easy testing — никаких mock'ов SDK, всё реальные unit-тесты.

**Cons:**
- При изменениях Saleor signature scheme (например, в 4.0) нужно патчить руками. В SDK это бы делалось автообновлением.
- Нужно знать spec — описывать тестируемое поведение в комментариях кода.

**Mitigation:** покрыть signature verification unit-тестами с реальными JWS payloads (помещаем в `tests/fixtures/`). Если Saleor сменит схему — тесты упадут, не production.

**Fallback на HMAC-SHA256.** В spec Phase 3.0 сказано: если у Saleor instance включён `secretKey` (legacy mode, deprecated в Saleor 4.0) — поддержать как fallback. Реализация: если в headers есть `Saleor-HMAC-SHA256` и нет `Saleor-Signature` — verify через HMAC-SHA256 с secret из env. Решение: реализуем only JWS в Phase 3.0, HMAC fallback отложен (наш Saleor 3.23 поддерживает JWS).
