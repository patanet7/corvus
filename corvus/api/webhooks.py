"""Webhook ingress API.

Typed validation and dispatch to domain handlers is centralized here so
server.py stays focused on runtime composition.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from corvus.webhooks import (
    EmailWebhookPayload,
    FinanceWebhookPayload,
    PaperlessWebhookPayload,
    TranscriptPayload,
    process_email,
    process_finance,
    process_paperless,
    process_transcript,
    verify_webhook_secret,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

WEBHOOK_DISPATCH: dict[str, tuple] = {
    "transcript": (TranscriptPayload, process_transcript),
    "email": (EmailWebhookPayload, process_email),
    "paperless": (PaperlessWebhookPayload, process_paperless),
    "finance": (FinanceWebhookPayload, process_finance),
}


@router.post("/{webhook_type}")
async def webhook(webhook_type: str, request: Request):
    """Webhook endpoint for transcript ingestion, email events, and similar jobs."""
    secret = request.headers.get("X-Webhook-Secret", "")
    if not verify_webhook_secret(secret):
        return JSONResponse(
            {"status": "error", "message": "Invalid or missing webhook secret"},
            status_code=401,
        )

    body = await request.json()
    logger.info("webhook_received", webhook_type=webhook_type)

    if webhook_type not in WEBHOOK_DISPATCH:
        return JSONResponse(
            {"status": "error", "message": f"Unknown webhook type: {webhook_type}"},
            status_code=400,
        )

    payload_cls, handler = WEBHOOK_DISPATCH[webhook_type]
    try:
        payload = payload_cls(**body)
    except ValidationError as exc:
        return JSONResponse(
            {"status": "error", "message": str(exc)},
            status_code=422,
        )

    result = await handler(payload)
    return JSONResponse(result.model_dump(), status_code=200)
