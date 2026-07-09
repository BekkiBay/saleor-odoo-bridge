# Architecture Decision Records (ADRs)

Каждый ADR фиксирует одно архитектурное решение по проекту Saleor↔Odoo интеграции.

Формат ADR:

```
# ADR-NNNN: Заголовок

## Status
Accepted | Superseded by ADR-XXXX | Deprecated (дата)

## Context
Что заставило принять решение. Бизнес-требования, технические ограничения.

## Decision
Что решили. Без воды.

## Alternatives considered
Что рассматривали и почему отбросили.

## Consequences
Pros / Cons / риски / что это значит для будущего.
```

ADR — **append-only**. Если решение меняется — пишем новый ADR со ссылкой `Superseded by ADR-XXXX` в статусе старого.

Индекс активных решений: [`../decisions.md`](../decisions.md).
