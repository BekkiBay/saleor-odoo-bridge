"""CLI: bulk seed the Odoo catalog → Saleor (ADR-0013).

    python -m saleor_bridge.cli.bulk_seed bulk-seed
    python -m saleor_bridge.cli.bulk_seed bulk-seed --dry-run
    python -m saleor_bridge.cli.bulk_seed wipe --yes        # wipe the Saleor catalog
"""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, TaskID, TextColumn
from rich.table import Table

from saleor_bridge.adapters.odoo.binding import BindingRepository
from saleor_bridge.adapters.saleor.catalog_admin import wipe_catalog
from saleor_bridge.adapters.saleor.factory import get_saleor_client
from saleor_bridge.config import get_settings
from saleor_bridge.odoo.client import OdooClient
from saleor_bridge.usecases.bulk_seed import run_bulk_seed, run_retry_failed
from saleor_bridge.usecases.bulk_seed_stocks import run_bulk_seed_stocks
from saleor_bridge.usecases.bulk_seed_variants import run_bulk_seed_variants
from saleor_bridge.usecases.reconcile_stocks import run_reconcile_stocks

app = typer.Typer(add_completion=False, help="Odoo → Saleor catalog seed.")
console = Console()


def _print_summary(summary: dict) -> None:
    table = Table(title="Bulk seed summary" + (" (DRY-RUN)" if summary["dry_run"] else ""))
    table.add_column("Entity")
    table.add_column("Total", justify="right")
    table.add_column("Create", justify="right")
    table.add_column("Update", justify="right")
    table.add_column("Skip", justify="right")
    table.add_column("Failed", justify="right")
    c = summary["categories"]
    p = summary["products"]
    table.add_row("Categories", str(c["total"]), str(c["create"]), str(c["update"]), "-", str(c["failed"]))
    table.add_row(
        "Products", str(p["total"]), str(p["create"]), str(p["update"]), str(p["skip"]), str(p["failed"])
    )
    console.print(table)
    pt = summary.get("product_type")
    ch = summary.get("channel")
    console.print(f"ProductType: [cyan]{pt}[/cyan]")
    console.print(f"Channel:     [cyan]{ch}[/cyan]")
    if summary.get("errors"):
        console.print("[red]Errors:[/red]")
        for e in summary["errors"]:
            console.print(f"  • {e}")


@app.command("bulk-seed")
def bulk_seed(dry_run: bool = typer.Option(False, "--dry-run", help="Plan without making changes.")) -> None:
    """Seed the entire Odoo catalog into Saleor (idempotent)."""
    settings = get_settings()

    async def _run() -> dict:
        if dry_run:
            return await run_bulk_seed(settings, dry_run=True)
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            console=console,
        ) as progress:
            bars: dict[str, TaskID] = {}

            def cb(stage: str, cur: int, total: int) -> None:
                if stage not in bars:
                    bars[stage] = progress.add_task(stage, total=total)
                progress.update(bars[stage], completed=cur, total=total)

            return await run_bulk_seed(settings, dry_run=False, progress=cb)

    summary = asyncio.run(_run())
    _print_summary(summary)
    failed = summary["categories"]["failed"] + summary["products"]["failed"]
    raise typer.Exit(code=1 if failed else 0)


@app.command("wipe")
def wipe(yes: bool = typer.Option(False, "--yes", help="Skip the confirmation prompt.")) -> None:
    """DESTRUCTIVE: delete EVERY product and category in the Saleor instance.

    This is not scoped to the configured channel and does not spare catalog data
    that this bridge never synced. Point it only at a store you own end to end.
    """
    if not yes:
        typer.secho(
            "This deletes EVERY product and root category in the Saleor instance "
            f"at {get_settings().saleor_api_url} — including catalog data this "
            "bridge never synced. It cannot be undone.",
            fg=typer.colors.RED,
        )
        if not typer.confirm("Proceed?"):
            raise typer.Abort()
    settings = get_settings()

    async def _run() -> dict:
        client = await get_saleor_client(settings)
        res = await wipe_catalog(client)
        # Clear outbound bindings, else bulk-seed would try to update dead ids.
        odoo = OdooClient(url=settings.odoo_url, db=settings.odoo_db, api_key=settings.odoo_api_key)
        res["bindings_deleted"] = await BindingRepository(odoo).delete_outbound()
        return res

    res = asyncio.run(_run())
    console.print(
        f"[yellow]Wiped[/yellow]: products={res['products']} "
        f"root_categories={res['root_categories']} bindings_deleted={res['bindings_deleted']}"
    )


@app.command("retry-failed")
def retry_failed() -> None:
    """Re-sync all saleor.binding records with state='failed' (outbound)."""
    settings = get_settings()
    res = asyncio.run(run_retry_failed(settings))
    console.print(
        f"Retry failed bindings: found={res['found']} ok={res['ok']} "
        f"failed={res['failed']} skipped={res['skipped']}"
    )
    if res.get("errors"):
        console.print("[red]Errors:[/red]")
        for e in res["errors"]:
            console.print(f"  • {e}")
    raise typer.Exit(code=1 if res["failed"] else 0)


@app.command("bulk-seed-stocks")
def bulk_seed_stocks() -> None:
    """Seed stock levels for all active Odoo variants → Saleor (idempotent)."""
    settings = get_settings()

    async def _run() -> dict:
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            console=console,
        ) as progress:
            bars: dict[str, TaskID] = {}

            def cb(stage: str, cur: int, total: int) -> None:
                if stage not in bars:
                    bars[stage] = progress.add_task(stage, total=total)
                progress.update(bars[stage], completed=cur, total=total)

            return await run_bulk_seed_stocks(settings, progress=cb)

    summary = asyncio.run(_run())
    table = Table(title="Stock seed summary")
    table.add_column("Total", justify="right")
    table.add_column("Synced", justify="right")
    table.add_column("Skip", justify="right")
    table.add_column("Failed", justify="right")
    table.add_row(
        str(summary["total"]), str(summary["synced"]), str(summary["skip"]), str(summary["failed"])
    )
    console.print(table)
    console.print(f"Safety buffer: [cyan]{summary['safety_buffer']}[/cyan]")
    if summary.get("errors"):
        console.print("[red]Errors:[/red]")
        for e in summary["errors"]:
            console.print(f"  • {e}")
    raise typer.Exit(code=1 if summary["failed"] else 0)


@app.command("bulk-seed-variants")
def bulk_seed_variants() -> None:
    """Migrate existing single-variant products → variant bindings (ADR-0025).

    Reconciles the variant set for each synced template: adopts the dummy variant
    and creates a product.product → Saleor variant binding. Idempotent.
    """
    settings = get_settings()

    async def _run() -> dict:
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            console=console,
        ) as progress:
            bars: dict[str, TaskID] = {}

            def cb(stage: str, cur: int, total: int) -> None:
                if stage not in bars:
                    bars[stage] = progress.add_task(stage, total=total)
                progress.update(bars[stage], completed=cur, total=total)

            return await run_bulk_seed_variants(settings, progress=cb)

    summary = asyncio.run(_run())
    table = Table(title="Variant seed summary")
    table.add_column("Templates", justify="right")
    table.add_column("Reconciled", justify="right")
    table.add_column("Failed", justify="right")
    table.add_column("Variant bindings", justify="right")
    table.add_row(
        str(summary["templates"]), str(summary["reconciled"]),
        str(summary["failed"]), str(summary["variant_bindings"]),
    )
    console.print(table)
    if summary.get("errors"):
        console.print("[red]Errors:[/red]")
        for e in summary["errors"]:
            console.print(f"  • {e}")
    raise typer.Exit(code=1 if summary["failed"] else 0)


@app.command("reconcile-stocks")
def reconcile_stocks(
    apply: bool = typer.Option(False, "--apply", help="Fix drift (otherwise dry-run)."),
) -> None:
    """Reconcile stock levels between Odoo and Saleor (ADR-0018). Dry-run by default.

    Exit 1 on drift (dry-run) or on a fix error (--apply); otherwise 0.
    """
    settings = get_settings()
    summary = asyncio.run(run_reconcile_stocks(settings, apply=apply))

    title = "Stock reconcile" + (" (APPLY)" if apply else " (dry-run)")
    table = Table(title=title)
    table.add_column("SKU")
    table.add_column("Warehouse")
    table.add_column("Odoo", justify="right")
    table.add_column("Saleor", justify="right")
    table.add_column("Diff", justify="right")
    table.add_column("Status")
    for r in summary["rows"]:
        status = "[red]❌ DRIFT[/red]" if r.drift else "[green](buffer — OK)[/green]"
        table.add_row(
            r.sku, r.warehouse, str(r.odoo_raw), str(r.saleor_qty),
            f"{r.diff:+d}", status,
        )
    console.print(table)
    console.print(
        f"checked={summary['checked']} ok={summary['ok']} "
        f"drift={summary['drift']} fixed={summary['fixed']}"
    )
    if summary.get("errors"):
        console.print("[red]Errors:[/red]")
        for e in summary["errors"]:
            console.print(f"  • {e}")

    if apply:
        raise typer.Exit(code=1 if summary["errors"] else 0)
    raise typer.Exit(code=1 if summary["drift"] else 0)


if __name__ == "__main__":
    app()
