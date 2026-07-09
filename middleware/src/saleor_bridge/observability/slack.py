"""Slack alert sender (ADR-0008). No-op если webhook URL пуст."""

from __future__ import annotations

import httpx
import structlog

log = structlog.get_logger()


async def send_slack_alert(webhook_url: str, text: str) -> None:
    if not webhook_url:
        log.debug("slack_skipped", reason="no webhook url")
        return
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(webhook_url, json={"text": text})
            r.raise_for_status()
        log.info("slack_sent")
    except Exception as e:  # noqa: BLE001
        log.warning("slack_failed", error=str(e))
