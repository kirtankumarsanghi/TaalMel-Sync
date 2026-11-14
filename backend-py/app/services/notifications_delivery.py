"""Notification delivery.

A Notification row is the source of truth and is always written. Delivery is a
best-effort side effect over a configured channel:

- a webhook (works with SMS/push gateways, Slack, or a small relay), or
- SMTP email to the user's registered address.

When neither is configured, the row is retained with an explicit
``delivery_error="no delivery channel configured"``. That is deliberately visible:
"stored" must never be mistaken for "sent".
"""

from __future__ import annotations

import smtplib
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage

from sqlmodel import Session, select

from app.config import get_settings
from app.db.models import Notification, User

MAX_ATTEMPTS = 5


@dataclass(frozen=True)
class DeliveryResult:
    channel: str
    delivered: bool
    error: str | None = None


def _deliver_webhook(note: Notification, user: User, url: str, token: str) -> DeliveryResult:
    import httpx

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = {
        "notification_id": note.id,
        "user_id": user.id,
        "name": user.name,
        "phone": user.phone,
        "title": note.title,
        "body": note.body,
        "rule": note.rule,
    }
    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=5.0)
        response.raise_for_status()
        return DeliveryResult("webhook", True)
    except Exception as exc:  # network failures must not break the request
        return DeliveryResult("webhook", False, str(exc)[:300])


def _deliver_email(note: Notification, user: User, settings) -> DeliveryResult:
    if not user.email:
        return DeliveryResult("smtp", False, "user has no email address")
    if not settings.smtp_from:
        return DeliveryResult("smtp", False, "smtp_from is not configured")

    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = user.email
    message["Subject"] = f"Taalmel Sync: {note.title}"
    message.set_content(f"{note.body}\n\nOpen Taalmel Sync to review the record.")

    try:
        if settings.smtp_use_tls:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=8) as smtp:
                smtp.starttls()
                if settings.smtp_username:
                    smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=8) as smtp:
                if settings.smtp_username:
                    smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(message)
        return DeliveryResult("smtp", True)
    except Exception as exc:
        return DeliveryResult("smtp", False, str(exc)[:300])


def deliver(session: Session, note: Notification) -> DeliveryResult:
    """Attempt delivery of one notification, recording the outcome on the row."""
    settings = get_settings()
    user = session.get(User, note.user_id)
    if user is None:
        result = DeliveryResult("none", False, "user not found")
    elif settings.notification_webhook_url:
        result = _deliver_webhook(
            note, user, settings.notification_webhook_url, settings.notification_webhook_token
        )
    elif settings.smtp_host:
        result = _deliver_email(note, user, settings)
    else:
        result = DeliveryResult("none", False, "no delivery channel configured")

    note.channel = result.channel
    note.delivery_attempts += 1
    note.delivered_at = datetime.now(UTC) if result.delivered else None
    note.delivery_error = None if result.delivered else result.error
    note.updated_at = datetime.now(UTC)
    session.add(note)
    return result


def deliver_pending(session: Session, limit: int = 100) -> int:
    """Retry undelivered notifications. Safe to run on a schedule."""
    rows = session.exec(
        select(Notification)
        .where(
            Notification.delivered_at.is_(None),  # type: ignore[union-attr]
            Notification.delivery_attempts < MAX_ATTEMPTS,
        )
        .order_by(Notification.created_at)  # type: ignore[arg-type]
        .limit(limit)
    ).all()
    sent = 0
    for note in rows:
        if deliver(session, note).delivered:
            sent += 1
    session.commit()
    return sent
