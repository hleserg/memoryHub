"""
Agent tools for Atman — functions the agent can call during a session.

These tools allow the agent to:
1. Record key moments during the session
2. Log experiences to the experience store
3. Search similar experiences (read-only)
4. Get identity snapshot (read-only)

All tools receive RunContext[AtmanDeps] as the first parameter,
giving them access to services and session state.
"""

from datetime import UTC, datetime
from uuid import UUID

from pydantic_ai import RunContext

from atman.adapters.agent.deps import AtmanDeps
from atman.affect.models import AgentMemoryReport
from atman.core.models.experience import EmotionalDepth
from atman.core.models.pending_human_review import PendingReviewResolution
from atman.core.models.reflection_request import (
    ReflectionRequest,
    ReflectionRequestLevel,
)
from atman.core.reflection_run_keys import agent_driven_run_key

# PLAYBOOK-START
# id: error-returning-tool-callbacks
# category: design-patterns
# title: Error-Returning Tool Callbacks for LLM Self-Correction
# status: draft
#
# Pattern: tool functions exposed to an LLM agent never raise — instead
# they validate inputs and return either a success message or a
# human-readable error string. Validation errors (out-of-range numbers,
# missing prerequisites like an active session) and downstream service
# exceptions are converted to "Error: …" return values. The LLM sees the
# error in the conversation, can read it, and retries the tool call with
# corrected arguments.
#
# Why generalizable: applies to any LLM-agent framework with tool use
# (Pydantic AI, OpenAI function-calling, Anthropic tool use, MCP
# servers). Raising exceptions inside a tool aborts the agent run and
# loses the LLM's ability to self-correct; returning structured error
# strings keeps the run alive and gives the LLM the signal it needs.
#
# Trade-offs: errors are observable to the model but easier to overlook
# in production logs — pair with out-of-band logging when used at scale.
# Also requires explicit input validation up-front, since you can't rely
# on Pydantic's "raise on invalid" behavior.
# PLAYBOOK-END
_DEPTH_ALIASES: dict[str, str] = {
    "significant": "meaningful",
    "important": "meaningful",
    "notable": "meaningful",
    "moderate": "meaningful",
    "identity": "profound",
    "existential": "profound",
    "deep": "profound",
    "fundamental": "profound",
    "transformative": "profound",
    "core": "profound",
    "minor": "surface",
    "light": "surface",
    "casual": "surface",
    "trivial": "surface",
    "superficial": "surface",
    "shallow": "surface",
}


async def record_key_moment(
    ctx: RunContext[AtmanDeps],
    what_happened: str,
    why_it_matters: str,
    emotional_valence: float = 0.0,
    emotional_intensity: float = 0.5,
    depth: str = "meaningful",
) -> str:
    """
    Record a key moment during the current session.

    Args:
        ctx: Run context with AtmanDeps
        what_happened: Description of what happened
        why_it_matters: Why this moment is significant
        emotional_valence: Emotional tone (-1.0 negative to +1.0 positive)
        emotional_intensity: Intensity of emotion (0.0 to 1.0)
        depth: How deeply this touched the agent's identity.
            Must be one of: "surface", "meaningful", "profound".

    Returns:
        Confirmation message

    This tool allows the agent to mark significant moments as they happen.
    These moments will be packaged into SessionExperience at session end.
    """
    if not ctx.deps.session_id:
        return "Error: No active session. Cannot record key moment outside of a session."

    depth = _DEPTH_ALIASES.get(depth.lower(), depth.lower())
    try:
        EmotionalDepth(depth)
    except ValueError:
        return f"Error: invalid depth {depth!r}. Use one of: 'surface', 'meaningful', 'profound'."

    # Validate emotional values
    if not -1.0 <= emotional_valence <= 1.0:
        return f"Error: emotional_valence must be between -1.0 and 1.0, got {emotional_valence}"

    if not 0.0 <= emotional_intensity <= 1.0:
        return f"Error: emotional_intensity must be between 0.0 and 1.0, got {emotional_intensity}"

    # Reject the both-zero case here with an LLM-actionable message. The
    # underlying SessionManager raises ValueError("set incomplete_coloring=True")
    # for this combination, but the agent has no way to set that flag through
    # this tool, so we surface a more useful instruction instead.
    if emotional_valence == 0.0 and emotional_intensity == 0.0:
        return (
            "Error: emotional_valence and emotional_intensity cannot both be 0.0. "
            "Provide non-zero emotional coloring "
            "(valence in [-1.0, 1.0], intensity in (0.0, 1.0]) "
            "to record a key moment."
        )

    det = ctx.deps.session_manager.affect_detector
    if det is None:
        return (
            "Error: AffectDetector is not configured on SessionManager "
            "(requires affect_workspace + affect_config). Cannot record key moment."
        )

    try:
        report = AgentMemoryReport(
            content=what_happened,
            emotional_valence=emotional_valence,
            emotional_intensity=emotional_intensity,
            emotional_depth=EmotionalDepth(depth),
            why_it_matters=why_it_matters,
            tags=[f"depth:{depth}"],
        )
        await det.submit_self_report(report, session_id=ctx.deps.session_id)
        summary = what_happened if len(what_happened) <= 50 else f"{what_happened[:50]}..."
        return f"Key moment recorded via AffectDetector: {summary}"
    except Exception as e:
        return f"Error recording key moment: {e!s}"


def log_experience(
    ctx: RunContext[AtmanDeps],
    description: str,
    key_insight: str = "",
) -> str:
    """
    Log an experience directly to the experience store.

    Args:
        ctx: Run context with AtmanDeps
        description: Description of the experience
        key_insight: Main insight from this experience

    Returns:
        Confirmation message

    This is typically called automatically at session end,
    but can be used manually for out-of-band experiences.
    """
    # This is a simplified version - normally SessionManager handles this
    # via finish_session which creates a complete SessionExperience
    _ = ctx, key_insight  # currently unused; reserved for future direct-log path
    summary = description if len(description) <= 30 else f"{description[:30]}..."
    return (
        "Experience logging is handled automatically at session end. "
        f"Use record_key_moment (AffectDetector-backed) to capture significant moments: {summary}"
    )


def restart_session(ctx: RunContext[AtmanDeps], reason: str = "") -> str:
    """
    Request immediate session restart.

    Args:
        ctx: Run context with AtmanDeps
        reason: Optional reason for restart

    Returns:
        Sentinel string indicating restart was requested

    This tool returns a sentinel string that the session runner will detect
    and use to trigger session restart logic. The runner is responsible for
    handling the actual restart workflow (E22.5).

    The sentinel format uses newline as delimiter when reason is provided
    to ensure unambiguous parsing.
    """
    _ = ctx  # Unused; reserved for future validation
    if reason:
        return f"__ATMAN_RESTART_REQUESTED__\n{reason}"
    return "__ATMAN_RESTART_REQUESTED__"


def wait_session(ctx: RunContext[AtmanDeps], minutes: int) -> str:
    """
    Request session pause for specified minutes.

    Args:
        ctx: Run context with AtmanDeps
        minutes: Number of minutes to wait (must be > 0)

    Returns:
        Sentinel string indicating wait was requested, or error message

    This tool returns a sentinel string that the session runner will detect
    and use to trigger wait/pause logic. The runner is responsible for
    handling the actual wait workflow (E22.5).
    """
    _ = ctx  # Unused; reserved for future validation

    if minutes <= 0:
        return f"Error: minutes must be positive, got {minutes}"

    return f"__ATMAN_WAIT_REQUESTED__{minutes}"


_RESOLUTION_ALIASES: dict[str, PendingReviewResolution] = {
    "accept": PendingReviewResolution.ACCEPTED,
    "accepted": PendingReviewResolution.ACCEPTED,
    "yes": PendingReviewResolution.ACCEPTED,
    "approve": PendingReviewResolution.ACCEPTED,
    "reject": PendingReviewResolution.REJECTED,
    "rejected": PendingReviewResolution.REJECTED,
    "no": PendingReviewResolution.REJECTED,
    "decline": PendingReviewResolution.REJECTED,
    "modify": PendingReviewResolution.MODIFIED,
    "modified": PendingReviewResolution.MODIFIED,
    "dismiss": PendingReviewResolution.DISMISSED,
    "dismissed": PendingReviewResolution.DISMISSED,
    "skip": PendingReviewResolution.DISMISSED,
}


def resolve_pending_review(
    ctx: RunContext[AtmanDeps],
    review_id: str,
    decision: str,
    note: str,
) -> str:
    """
    Resolve a pending human review item raised by reflection.

    Use this tool to answer the questions surfaced at the start of the
    session. Pass the id shown in the "Перед тем как продолжить" section.

    Args:
        ctx: Run context with AtmanDeps
        review_id: UUID of the review item to resolve
        decision: One of "accepted" | "rejected" | "modified" | "dismissed".
            Common synonyms ("approve", "yes", "no", "skip") are also accepted.
        note: Brief explanation of the decision (required, non-empty)

    Returns:
        Confirmation message or "Error: …" string for self-correction.
    """
    inbox = ctx.deps.pending_review_inbox
    if inbox is None:
        return "Error: no pending review inbox is configured in this session"

    decision_norm = decision.strip().lower()
    resolution = _RESOLUTION_ALIASES.get(decision_norm)
    if resolution is None:
        return (
            f"Error: unknown decision '{decision}'. Use accepted | rejected | modified | dismissed."
        )

    note_clean = note.strip()
    if not note_clean:
        return "Error: note is required and must be non-empty"

    try:
        review_uuid = UUID(review_id)
    except (TypeError, ValueError):
        return f"Error: review_id is not a valid UUID: {review_id!r}"

    try:
        resolved = inbox.resolve(
            review_uuid,
            resolution=resolution,
            note=note_clean,
            resolved_at=datetime.now(UTC),
        )
    except KeyError:
        return f"Error: no pending review with id {review_id}"
    except ValueError as exc:
        return f"Error: {exc}"

    return f"Resolved review {resolved.id} as {resolution.value}. Note: {note_clean}"


_LEVEL_ALIASES: dict[str, ReflectionRequestLevel] = {
    "daily": ReflectionRequestLevel.DAILY,
    "day": ReflectionRequestLevel.DAILY,
    "deep": ReflectionRequestLevel.DEEP,
    "weekly": ReflectionRequestLevel.DEEP,
}


def request_reflection(
    ctx: RunContext[AtmanDeps],
    reason: str,
    level: str = "daily",
) -> str:
    """
    Request that reflection look at something specific later.

    Use this when something happens in a session that you sense should be
    revisited in a calmer moment — not now, not as part of the current turn.
    The reason will be threaded into the startup context of the next
    reflection job at the requested level.

    Same reason inside the same hour is collapsed to one request: it is fine
    to call this without checking whether you've asked already.

    Args:
        ctx: Run context with AtmanDeps
        reason: Why this matters and what to look at. Required.
        level: "daily" (default) or "deep".

    Returns:
        Confirmation or "Error: …" for self-correction.
    """
    queue = ctx.deps.reflection_request_queue
    if queue is None:
        return "Error: no reflection request queue is configured in this session"

    reason_clean = reason.strip()
    if not reason_clean:
        return "Error: reason is required and must be non-empty"

    level_norm = level.strip().lower()
    resolved_level = _LEVEL_ALIASES.get(level_norm)
    if resolved_level is None:
        return f"Error: unknown level '{level}'. Use 'daily' or 'deep'."

    now = datetime.now(UTC)
    run_key = agent_driven_run_key(resolved_level.value, reason_clean, now)
    request = ReflectionRequest(
        level=resolved_level,
        reason=reason_clean,
        run_key=run_key,
        requested_at=now,
    )
    try:
        stored = queue.enqueue(request)
    except Exception as exc:
        return f"Error queuing reflection request: {exc!s}"
    if stored.id != request.id:
        return (
            f"Already queued (same reason within the hour): "
            f"id={stored.id}, level={stored.level.value}"
        )
    return f"Queued reflection request {stored.id} at level={stored.level.value}"
