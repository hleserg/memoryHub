"""
atman/agent_cli/context_manager.py
Context window tracking and compression.

Strategy (best practice):
  1. Track tokens continuously (tiktoken or char/4 heuristic)
  2. At WARNING threshold (80%) → alert, start preparing
  3. At CRITICAL threshold (90%) → stop, compress, resume

Compression produces new context:
  [PLAN (full)] + [SESSION SUMMARY] + [KEY FACTS] + [TAIL (last N messages)]

Plan is NEVER modified or dropped — it moves complete to new context.
Key facts are saved to AgentMemory for future retrieval.
Session summary is a compact narrative of what happened.
Tail gives immediate conversational continuity.
"""
from __future__ import annotations

import re
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .memory import AgentMemory, Plan
    from .providers import ProviderRouter


# ── Token counting ────────────────────────────────────────────────────────────

def count_tokens(text: str, model: str = "gpt-3.5-turbo") -> int:
    """
    Count tokens. Uses tiktoken if available, falls back to char/4 heuristic.
    tiktoken is accurate for OpenAI-family models; for Gemma/DeepSeek it's
    approximate but good enough for threshold tracking.
    """
    try:
        import tiktoken
        try:
            enc = tiktoken.encoding_for_model(model)
        except KeyError:
            enc = tiktoken.get_encoding("cl100k_base")  # good general fallback
        return len(enc.encode(text))
    except ImportError:
        # Heuristic: ~4 chars per token (conservative, slightly overestimates)
        return len(text) // 4


def count_messages_tokens(messages: list[dict]) -> int:
    """Count tokens across a list of {role, content} messages."""
    total = 0
    for m in messages:
        total += count_tokens(m.get("content", ""))
        total += 4  # per-message overhead (role tokens etc.)
    return total


# ── Thresholds ────────────────────────────────────────────────────────────────

@dataclass
class ContextLimits:
    """
    Token budget configuration.
    Defaults are conservative — works for most 8K–128K models.
    Override via AgentConfig or /config context_limit.
    """
    total: int = 8192           # total context window of the model
    reserved_output: int = 2048 # tokens reserved for model's response
    warning_ratio: float = 0.80 # warn at 80% of available input space
    critical_ratio: float = 0.90 # compress at 90%

    # Compression budget
    summary_tokens: int = 512   # target size of session summary
    tail_messages: int = 6      # how many recent messages to keep verbatim
    facts_tokens: int = 400     # target size of extracted facts block

    @property
    def available_input(self) -> int:
        return self.total - self.reserved_output

    @property
    def warning_threshold(self) -> int:
        return int(self.available_input * self.warning_ratio)

    @property
    def critical_threshold(self) -> int:
        return int(self.available_input * self.critical_ratio)

    @property
    def compression_budget(self) -> int:
        """Tokens available for compressed context (plan + summary + facts + tail)."""
        return int(self.available_input * 0.5)  # leave 50% for new work


# ── Compression prompts ───────────────────────────────────────────────────────

SUMMARY_PROMPT = """Summarize this agent session concisely for context compression.

The agent was working on: {task}

Session messages:
{messages}

Write a compact summary covering:
1. What was accomplished (specific files/functions created or modified)
2. Key decisions made and why
3. What was tried but blocked/failed
4. Current state — exactly where we left off

Be specific and technical. Max {max_tokens} tokens. No fluff."""


FACTS_EXTRACTION_PROMPT = """Extract key technical facts and decisions from this session.

Session working on: {task}
{messages}

Extract facts that would be useful to recall later:
- Architecture decisions ("decided to use X instead of Y because Z")
- File locations ("the port is in src/atman/core/ports/embedding.py")
- Patterns discovered ("BGE-M3 expects List[List[float]] not numpy array")
- Constraints found ("can't import atman.eval from production code")
- Dependencies ("needs FlagEmbedding>=1.2 in [agent] extras")

Return JSON array of fact strings. Max {max_tokens} tokens total.
["fact 1", "fact 2", ...]"""


# ── Context snapshot ──────────────────────────────────────────────────────────

@dataclass
class ContextSnapshot:
    """Result of compression — what goes into the new context."""
    plan_text: str              # full serialized plan
    summary: str                # LLM-generated session summary
    key_facts: list[str]        # extracted technical facts
    tail_messages: list[dict]   # last N messages verbatim
    compressed_at: str = field(default_factory=lambda: datetime.now().isoformat())
    tokens_before: int = 0
    tokens_after: int = 0

    def to_context_header(self) -> str:
        """
        Format as context header for injection at start of new context.
        This is what the agent 'remembers' after compression.
        """
        facts_text = "\n".join(f"  • {f}" for f in self.key_facts) if self.key_facts else "  (none)"
        return (
            f"## ⟳ Context compressed at {self.compressed_at[:16]}\n"
            f"Tokens before: {self.tokens_before} → after: {self.tokens_after}\n\n"
            f"### Session summary\n{self.summary}\n\n"
            f"### Key facts from this session\n{facts_text}\n\n"
            f"### Current plan (full)\n{self.plan_text}\n"
        )

    def to_dict(self) -> dict:
        return {
            "plan_text": self.plan_text,
            "summary": self.summary,
            "key_facts": self.key_facts,
            "tail_messages": self.tail_messages,
            "compressed_at": self.compressed_at,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
        }


# ── Main context manager ──────────────────────────────────────────────────────

class ContextManager:
    """
    Tracks token usage and triggers compression when approaching limits.

    Usage:
        ctx = ContextManager(limits, router, memory)

        # After every message added to history:
        status = ctx.check(messages, current_plan)
        if status.should_compress:
            snapshot = ctx.compress(messages, current_plan)
            messages = ctx.rebuild_messages(snapshot)
            # save snapshot.key_facts to memory

        # Display in UI:
        pct, color = ctx.usage_display(messages)
    """

    def __init__(
        self,
        limits: ContextLimits,
        router: "ProviderRouter",
        memory: "AgentMemory",
    ) -> None:
        self.limits = limits
        self.router = router
        self.memory = memory
        self._last_token_count: int = 0
        self._compression_count: int = 0

    # ── Status ────────────────────────────────────────────────────────────────

    @dataclass
    class Status:
        tokens_used: int
        tokens_available: int
        pct: float
        level: str   # "ok" | "warning" | "critical"
        should_compress: bool

        @property
        def color(self) -> str:
            return {"ok": "green", "warning": "yellow", "critical": "red"}.get(self.level, "white")

        @property
        def display(self) -> str:
            return f"{self.tokens_used:,}/{self.tokens_available:,} ({self.pct:.0%})"

    def check(
        self,
        messages: list[dict],
        current_plan: "Plan | None" = None,
        extra_context: str = "",
    ) -> "ContextManager.Status":
        """
        Check current token usage. Call after every message.
        Returns Status with compression recommendation.
        """
        # Count: messages + any injected context
        used = count_messages_tokens(messages)
        if extra_context:
            used += count_tokens(extra_context)
        if current_plan:
            used += count_tokens(self._serialize_plan(current_plan))

        self._last_token_count = used
        available = self.limits.available_input
        pct = used / available if available > 0 else 1.0

        if used >= self.limits.critical_threshold:
            level = "critical"
            should_compress = True
        elif used >= self.limits.warning_threshold:
            level = "warning"
            should_compress = False
        else:
            level = "ok"
            should_compress = False

        return self.Status(
            tokens_used=used,
            tokens_available=available,
            pct=pct,
            level=level,
            should_compress=should_compress,
        )

    # ── Compression ───────────────────────────────────────────────────────────

    def compress(
        self,
        messages: list[dict],
        current_plan: "Plan | None" = None,
    ) -> ContextSnapshot:
        """
        Compress current context into a snapshot.
        Saves facts to AgentMemory. Returns snapshot for UI and message rebuild.
        """
        self._compression_count += 1
        tokens_before = self._last_token_count

        # Separate tail from body
        tail = messages[-self.limits.tail_messages:] if len(messages) > self.limits.tail_messages else messages
        body = messages[:-self.limits.tail_messages] if len(messages) > self.limits.tail_messages else []

        body_text = self._messages_to_text(body)
        task = current_plan.task if current_plan else "unknown task"

        # Generate summary
        summary = self._generate_summary(task, body_text)

        # Extract key facts
        key_facts = self._extract_facts(task, body_text)

        # Serialize plan (full, never truncated)
        plan_text = self._serialize_plan(current_plan) if current_plan else ""

        snapshot = ContextSnapshot(
            plan_text=plan_text,
            summary=summary,
            key_facts=key_facts,
            tail_messages=tail,
            tokens_before=tokens_before,
        )

        # Save facts to long-term memory
        self._persist_facts(key_facts, task, current_plan)

        # Calculate new size
        header_tokens = count_tokens(snapshot.to_context_header())
        tail_tokens = count_messages_tokens(tail)
        snapshot.tokens_after = header_tokens + tail_tokens

        return snapshot

    def rebuild_messages(self, snapshot: ContextSnapshot) -> list[dict]:
        """
        Build new messages list from snapshot.
        Structure: [system: context header] + tail messages
        """
        messages: list[dict] = []

        # Context header as system message
        messages.append({
            "role": "system",
            "content": snapshot.to_context_header(),
        })

        # Tail messages verbatim
        messages.extend(snapshot.tail_messages)

        return messages

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _messages_to_text(self, messages: list[dict]) -> str:
        parts = []
        for m in messages:
            role = m.get("role", "?").upper()
            content = m.get("content", "")
            # Truncate very long individual messages
            if len(content) > 2000:
                content = content[:2000] + "\n[... truncated ...]"
            parts.append(f"{role}: {content}")
        return "\n\n".join(parts)

    def _serialize_plan(self, plan: "Plan | None") -> str:
        if not plan:
            return ""
        from .memory import STEP_DONE, STEP_BLOCKED, STEP_IN_PROGRESS
        icons = {STEP_DONE: "✅", STEP_BLOCKED: "🚫", STEP_IN_PROGRESS: "⚡"}
        lines = [f"PLAN: {plan.task}", f"Status: {plan.status}", "Steps:"]
        for i, step in enumerate(plan.steps):
            state = plan.get_state(i)
            icon = icons.get(state, "⬜")
            line = f"  {icon} {i+1}. {step}"
            notes = plan.get_notes(i)
            if notes:
                line += f" [{notes[:60]}]"
            reason = plan.get_blocked_reason(i)
            if reason:
                line += f" [BLOCKED: {reason[:60]}]"
            lines.append(line)
        return "\n".join(lines)

    def _generate_summary(self, task: str, body_text: str) -> str:
        if not body_text.strip():
            return f"Working on: {task}. Session just started."

        prompt = SUMMARY_PROMPT.format(
            task=task,
            messages=body_text[:6000],
            max_tokens=self.limits.summary_tokens,
        )
        try:
            result = self.router.analyze(prompt)
            # Ensure it's not too long
            if count_tokens(result) > self.limits.summary_tokens * 1.5:
                # Hard truncate
                words = result.split()
                result = " ".join(words[:self.limits.summary_tokens * 3 // 4])
            return result
        except Exception as e:
            return f"[Summary generation failed: {e}]\nWorking on: {task}"

    def _extract_facts(self, task: str, body_text: str) -> list[str]:
        if not body_text.strip():
            return []

        prompt = FACTS_EXTRACTION_PROMPT.format(
            task=task,
            messages=body_text[:5000],
            max_tokens=self.limits.facts_tokens,
        )
        try:
            raw = self.router.analyze(prompt)
            # Parse JSON
            raw = raw.strip()
            match = re.search(r"\[.*\]", raw, re.DOTALL)
            if match:
                facts = json.loads(match.group())
                if isinstance(facts, list):
                    return [str(f) for f in facts[:20]]  # cap at 20 facts
        except Exception:
            pass
        return []

    def _persist_facts(
        self,
        facts: list[str],
        task: str,
        plan: "Plan | None",
    ) -> None:
        """Save extracted facts to AgentMemory for future retrieval."""
        tags = ["agent", "session", f"compression-{self._compression_count}"]
        if plan:
            tags.append(f"plan-{plan.id}")

        for fact in facts:
            self.memory.remember_fact(fact, tags=tags)

        # Also save a summary fact
        if facts:
            self.memory.remember_fact(
                f"[Compression #{self._compression_count}] Working on '{task}'. "
                f"Saved {len(facts)} facts from session context.",
                tags=tags,
            )

    # ── Display helpers ───────────────────────────────────────────────────────

    def usage_bar(self, tokens_used: int) -> str:
        """ASCII progress bar for token usage."""
        available = self.limits.available_input
        pct = min(tokens_used / available, 1.0) if available > 0 else 1.0
        filled = int(pct * 10)
        bar = "█" * filled + "░" * (10 - filled)
        return f"[{bar}] {tokens_used:,}/{available:,}"

    @property
    def compression_count(self) -> int:
        return self._compression_count
