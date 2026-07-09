"""arq worker definition. Run: python -m arq saleor_bridge.queue.arq_worker.WorkerSettings"""

from __future__ import annotations

import structlog
from arq import cron
from arq.connections import RedisSettings

from saleor_bridge.config import get_settings
from saleor_bridge.queue import tasks

log = structlog.get_logger()


async def on_startup(ctx: dict) -> None:
    ctx["settings"] = get_settings()
    log.info("arq_worker_started")


async def on_shutdown(ctx: dict) -> None:
    log.info("arq_worker_stopped")


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


class WorkerSettings:
    functions = [
        tasks.process_customer_created,
        tasks.process_customer_updated,
        tasks.process_order_created,
        tasks.process_order_paid,
        tasks.process_order_cancelled,
        tasks.sync_odoo_record_to_saleor,
    ]
    # Stock reconcile (ADR-0018): daily 02:00 (контейнер в UTC) — dry-run, лог дрейфа.
    cron_jobs = [cron(tasks.reconcile_stock_drift, hour=2, minute=0)]
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = _redis_settings()
    max_tries = 3
    # backoff: arq default exponential. retry delays ~ (job_try^2). См. spec 1s/4s/16s.
    retry_jobs = True
    keep_result = 3600
