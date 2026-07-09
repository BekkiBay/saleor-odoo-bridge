"""Email alert sender (ADR-0008). No-op when the ops email / SMTP host is unset.

SMTP config is optional — without it, failures are logged and nothing is sent.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

import structlog

log = structlog.get_logger()


def send_email_alert(
    *,
    ops_email: str,
    subject: str,
    body: str,
    smtp_host: str = "",
    smtp_port: int = 25,
    smtp_user: str = "",
    smtp_password: str = "",
    from_addr: str = "saleor-bridge@localhost",
) -> None:
    if not ops_email or not smtp_host:
        log.debug("email_skipped", reason="no ops_email or smtp_host")
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ops_email
    msg.set_content(body)
    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as s:
            if smtp_user:
                s.starttls()
                s.login(smtp_user, smtp_password)
            s.send_message(msg)
        log.info("email_sent", to=ops_email)
    except Exception as e:  # noqa: BLE001
        log.warning("email_failed", error=str(e))
