"""Webhook payload models and processing functions.

Pydantic models for typed validation. Processing dispatches to agents
via planner-driven background orchestration.
"""

import asyncio
import hmac
import os
from datetime import datetime

import structlog
from pydantic import BaseModel, Field, ValidationError  # noqa: F401

logger = structlog.get_logger(__name__)


class TranscriptPayload(BaseModel):
    """Meeting transcript webhook payload."""

    title: str = Field(..., description="Meeting title")
    transcript: str = Field(..., description="Full transcript text")
    participants: list[str] = Field(default_factory=list, description="Meeting participants")
    meeting_date: datetime | None = Field(None, description="When the meeting occurred")
    source: str = Field("unknown", description="Transcript source (otter, zoom, manual)")
    duration_minutes: int | None = Field(None, description="Meeting duration")


class EmailWebhookPayload(BaseModel):
    """Email notification webhook payload."""

    message_id: str = Field(..., description="Email message ID")
    subject: str = Field("", description="Email subject")
    sender: str = Field("", description="Sender email address")
    snippet: str = Field("", description="Email preview snippet")
    labels: list[str] = Field(default_factory=list, description="Current labels")
    provider: str = Field("gmail", description="Email provider (gmail, yahoo)")


class PaperlessWebhookPayload(BaseModel):
    """Paperless-ngx document event webhook payload."""

    document_id: int = Field(..., description="Paperless document ID")
    title: str = Field("", description="Document title")
    correspondent: str = Field("", description="Document correspondent")
    document_type: str = Field("", description="Document type")
    tags: list[str] = Field(default_factory=list, description="Document tags")


class FinanceWebhookPayload(BaseModel):
    """Finance reconciliation trigger payload."""

    trigger: str = Field(..., description="Trigger type (nightly_reconcile, manual)")
    date_range_start: str | None = Field(None, description="Start date (YYYY-MM-DD)")
    date_range_end: str | None = Field(None, description="End date (YYYY-MM-DD)")


class WebhookResponse(BaseModel):
    """Standard webhook response."""

    status: str  # "accepted", "processed", "error"
    webhook_type: str
    message: str | None = None
    memories_saved: int = 0


def verify_webhook_secret(header_secret: str) -> bool:
    """Verify webhook authentication via constant-time comparison.

    Reads WEBHOOK_SECRET at call time (not import time) so that secrets
    injected by CredentialStore.inject() are picked up correctly.

    Returns False (fail closed) if WEBHOOK_SECRET is empty/unset.
    """
    secret = os.environ.get("WEBHOOK_SECRET", "")
    if not secret:
        return False
    if not header_secret:
        return False
    return hmac.compare_digest(header_secret, secret)


def _emit_routing_decision(agent: str, webhook_type: str, query_preview: str) -> None:
    """Emit a routing_decision event for webhook-triggered agent dispatch.

    Best-effort — never breaks webhook processing for observability.
    """
    try:
        # Lazy import: corvus.server imports corvus.webhooks, so importing server
        # at module level creates a circular dependency.
        from corvus.server import emitter

        asyncio.get_running_loop().create_task(
            emitter.emit(
                "routing_decision",
                agent=agent,
                source="webhook",
                webhook_type=webhook_type,
                query_preview=query_preview[:200],
            )
        )
    except Exception:
        logger.debug("routing_decision_emit_failed", exc_info=True)


async def _dispatch_to_agent(
    agent: str,
    webhook_type: str,
    prompt: str,
    error_message: str,
    *,
    target_agents: list[str] | None = None,
    dispatch_mode: str = "direct",
    requested_model: str | None = None,
    source: str = "webhook",
    session_user: str | None = None,
) -> WebhookResponse | None:
    """Dispatch a prompt through the shared planner-driven background runner."""
    from corvus.config import ALLOWED_USERS, MAX_PARALLEL_AGENT_RUNS
    from corvus.gateway.background_dispatch import (
        DispatchValidationError,
        execute_planned_background_dispatch,
    )
    from corvus.gateway.options import any_llm_configured
    from corvus.server import runtime

    if not any_llm_configured():
        return WebhookResponse(
            status="error",
            webhook_type=webhook_type,
            message="No LLM backend configured",
        )

    session_owner = session_user or (ALLOWED_USERS[0] if ALLOWED_USERS else "system")
    try:
        summary = await execute_planned_background_dispatch(
            runtime=runtime,
            session_owner=session_owner,
            prompt=prompt,
            initial_agent=agent,
            webhook_type=webhook_type,
            target_agents=target_agents,
            dispatch_mode=dispatch_mode,
            requested_model=requested_model,
            source=source,
            max_parallel_agent_runs=MAX_PARALLEL_AGENT_RUNS,
        )
    except DispatchValidationError as exc:
        return WebhookResponse(
            status="error",
            webhook_type=webhook_type,
            message=str(exc),
        )
    except asyncio.CancelledError:
        logger.warning("webhook_dispatch_cancelled", webhook_type=webhook_type)
        return WebhookResponse(
            status="error",
            webhook_type=webhook_type,
            message=error_message,
        )
    except Exception:
        logger.exception("webhook_processing_failed", webhook_type=webhook_type)
        return WebhookResponse(
            status="error",
            webhook_type=webhook_type,
            message=error_message,
        )

    if summary.status != "done":
        return WebhookResponse(
            status="error",
            webhook_type=webhook_type,
            message=error_message,
        )
    return None


async def process_transcript(payload: TranscriptPayload) -> WebhookResponse:
    """Process a meeting transcript via the work agent."""
    _emit_routing_decision("work", "transcript", payload.title)

    prompt = (
        f"Process this meeting transcript and extract key points, decisions, "
        f"and action items. Save important items to memory.\n\n"
        f"Title: {payload.title}\n"
        f"Participants: {', '.join(payload.participants) or 'unknown'}\n"
        f"Date: {payload.meeting_date or 'today'}\n"
        f"Source: {payload.source}\n\n"
        f"Transcript:\n{payload.transcript[:8000]}"
    )

    error = await _dispatch_to_agent(
        "work",
        "transcript",
        prompt,
        f"Processing failed for '{payload.title}'",
    )
    if error:
        return error

    return WebhookResponse(
        status="processed",
        webhook_type="transcript",
        message=f"Transcript '{payload.title}' processed by work agent",
    )


async def process_email(payload: EmailWebhookPayload) -> WebhookResponse:
    """Process an email notification via the email agent."""
    _emit_routing_decision("email", "email", payload.subject)

    prompt = (
        f"New email received. Triage this message and determine if it needs action.\n\n"
        f"From: {payload.sender}\n"
        f"Subject: {payload.subject}\n"
        f"Preview: {payload.snippet}\n"
        f"Labels: {', '.join(payload.labels)}\n"
        f"Message ID: {payload.message_id}\n\n"
        f"Categorize as: action, delegate, archive, or delete. "
        f"If action is needed, save a reminder to memory."
    )

    error = await _dispatch_to_agent(
        "email",
        "email",
        prompt,
        f"Processing failed for email from {payload.sender}",
    )
    if error:
        return error

    return WebhookResponse(
        status="processed",
        webhook_type="email",
        message=f"Email from {payload.sender} triaged by email agent",
    )


async def process_paperless(payload: PaperlessWebhookPayload) -> WebhookResponse:
    """Process a new Paperless document via the docs agent."""
    _emit_routing_decision("docs", "paperless", payload.title)

    prompt = (
        f"A new document has been scanned and added to Paperless-ngx. "
        f"Review and classify it.\n\n"
        f"Document ID: {payload.document_id}\n"
        f"Title: {payload.title}\n"
        f"Correspondent: {payload.correspondent or 'unknown'}\n"
        f"Type: {payload.document_type or 'unclassified'}\n"
        f"Tags: {', '.join(payload.tags) or 'none'}\n\n"
        f"Suggest appropriate tags and correspondent if missing."
    )

    error = await _dispatch_to_agent(
        "docs",
        "paperless",
        prompt,
        f"Processing failed for document {payload.document_id}",
    )
    if error:
        return error

    return WebhookResponse(
        status="processed",
        webhook_type="paperless",
        message=f"Document '{payload.title}' classified by docs agent",
    )


async def process_finance(payload: FinanceWebhookPayload) -> WebhookResponse:
    """Process a finance reconciliation trigger via the finance agent."""
    _emit_routing_decision("finance", "finance", payload.trigger)

    date_range = ""
    if payload.date_range_start and payload.date_range_end:
        date_range = f"\nDate range: {payload.date_range_start} to {payload.date_range_end}"

    prompt = (
        f"Finance reconciliation triggered ({payload.trigger}).{date_range}\n\n"
        f"Review recent transactions, categorize uncategorized ones, "
        f"and flag any anomalies. Save a summary to memory."
    )

    error = await _dispatch_to_agent(
        "finance",
        "finance",
        prompt,
        "Finance reconciliation failed",
    )
    if error:
        return error

    return WebhookResponse(
        status="processed",
        webhook_type="finance",
        message=f"Finance reconciliation ({payload.trigger}) processed",
    )
