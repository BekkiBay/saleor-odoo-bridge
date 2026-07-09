# Architecture Decision Records (ADRs)

Each ADR records a single architectural decision for the Saleor↔Odoo integration project.

ADR format:

```
# ADR-NNNN: Title

## Status
Accepted | Superseded by ADR-XXXX | Deprecated (date)

## Context
What drove the decision. Business requirements, technical constraints.

## Decision
What was decided. No filler.

## Alternatives considered
What was considered, and why it was rejected.

## Consequences
Pros / Cons / risks / what this means going forward.
```

ADRs are **append-only**. If a decision changes, we write a new ADR with a `Superseded by ADR-XXXX` reference in the status of the old one.

Index of active decisions: [`../decisions.md`](../decisions.md).
