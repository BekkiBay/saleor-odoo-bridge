# ADR-0027: Attribute input type — DROPDOWN only for the MVP

## Status
Accepted (2026-05-23)

## Context

Saleor supports many attribute types: `DROPDOWN`, `MULTISELECT`, `NUMERIC`,
`RICH_TEXT`, `PLAIN_TEXT`, `BOOLEAN`, `DATE`, `DATE_TIME`, `FILE`, `REFERENCE`,
`SWATCH`. Odoo's `product.attribute.display_type` is
`radio`/`select`/`color`/`pills`, plus `product.attribute.value.html_color` for
swatches.

For the MVP catalog we need size/color/material — all of which are selected from a
finite list of values.

## Decision

- **All attributes are synced as `inputType: DROPDOWN`**, regardless of Odoo's
  `display_type`. `domain.Attribute.input_type = Literal["DROPDOWN"]`.
- **`type: PRODUCT`, `valueRequired: false`** — so single-variant products can keep
  their variant without attribute values (see the migration in ADR-0025).
- Variant attribute values are sent as `dropdownValue: {id: <AttributeValue id>}`.
- **`html_color` is NOT synced** in the MVP (it can be empty; swatch support is a
  future enhancement).
- **`create_variant = 'no_variant'` attributes are skipped** (these are
  product-level attributes like "composition: 100% cotton," not variant-defining
  ones) — a future enhancement.

## Alternatives considered

- **Map `display_type` → `inputType` (color→SWATCH, etc.).** Rejected: SWATCH
  requires a hex value/file and adds branching to create/resolve logic without
  adding value for the MVP.
- **NUMERIC for shoe sizes.** Rejected: sizes are selected from a list, so DROPDOWN
  is sufficient; NUMERIC would complicate value resolution.

## Consequences

**Pros:** a single shape for all the mutations involved (create attribute, create
value, assign, variant attributes) — minimal branching, predictable.

**Cons:** color swatches on the storefront will render as text ("Red") rather than
a color chip — a UX gap to be addressed in a future iteration (SWATCH +
html_color). Numeric/text attributes aren't supported yet. Marked as out of scope
for now.
