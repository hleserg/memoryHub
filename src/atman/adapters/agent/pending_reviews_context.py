"""Helpers for surfacing pending human review items into agent context."""

from __future__ import annotations

import json

from atman.core.ports.pending_human_review import PendingHumanReviewInbox


def format_pending_reviews_block(
    inbox: PendingHumanReviewInbox | None,
    *,
    limit: int = 3,
) -> str | None:
    """
    Build the "before we start" section listing unresolved review items.

    Returns ``None`` when inbox is missing or has no unresolved items, so
    callers can cheaply gate their formatting.

    The section is intentionally short and per-item bullet-pointed: it is
    surfaced as the first system message and competes for attention with the
    user's first turn. Heavy context belongs in `PendingReview.context` and is
    consulted through the `resolve_pending_review` tool, not crammed in here.
    """
    if inbox is None:
        return None
    items = inbox.list_unresolved(limit=limit)
    if not items:
        return None

    lines: list[str] = [
        "# Перед тем как продолжить",
        (
            "У меня (рефлексии) есть открытые вопросы, по которым я сама не была "
            "уверена и оставила их тебе. Если есть время — посмотри и ответь "
            "через `resolve_pending_review`. Если нет — просто продолжай, они подождут."
        ),
        "",
    ]
    for review in items:
        lines.append(f"## {review.kind.value} — id `{review.id}`")
        lines.append(f"_{review.created_by}, priority={review.priority.value}_")
        lines.append("")
        lines.append(review.question)
        if review.context:
            preview = _format_context_preview(review.context)
            if preview:
                lines.append("")
                lines.append("Контекст:")
                lines.append(preview)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _format_context_preview(context: dict) -> str:
    """Format a small structured preview of the context dict.

    Long string values are truncated. Nested objects are JSON-serialized in
    compact form so the section stays readable.
    """
    parts: list[str] = []
    for key, value in context.items():
        if isinstance(value, str):
            shown = value if len(value) <= 280 else value[:277] + "..."
            parts.append(f"- **{key}**: {shown}")
        else:
            try:
                rendered = json.dumps(value, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                rendered = repr(value)
            if len(rendered) > 280:
                rendered = rendered[:277] + "..."
            parts.append(f"- **{key}**: `{rendered}`")
    return "\n".join(parts)
