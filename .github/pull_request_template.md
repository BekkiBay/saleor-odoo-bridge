<!-- Thanks! Two asks before review: -->

## What & why

<!-- One paragraph. If this changes a recorded decision, link the ADR. -->

## Checklist

- [ ] `cd middleware && ruff check . && mypy src && pytest -q` is green
- [ ] Behavioural change → covered by a test
- [ ] Renamed/removed a stored Odoo field → migration included, `__manifest__.py` version bumped (see CONTRIBUTING.md)
- [ ] User-facing change → CHANGELOG.md updated
