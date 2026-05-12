"""
Token monitor for tracking agent context usage with progressive warnings.

This module provides token usage monitoring for Atman agent sessions:
- Tracks input_tokens vs context_limit after each agent.run()
- Progressive warnings at 70/80/90/95% thresholds
- Automatic session termination on 95% limit
- Stateful trigger tracking to avoid duplicate warnings

Implements E22.3: Token monitoring with progressive warnings.

Note: This is separate from runner.py (E22.2) which handles signal-based
session lifecycle. Future integration: runner.py chat loop can use TokenMonitor
to enforce context limits during interactive sessions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai import Agent

from atman.adapters.agent.deps import AtmanDeps
from atman.adapters.agent.instructions import build_instructions
from atman.adapters.agent.tools import log_experience, record_key_moment

if TYPE_CHECKING:
    from pydantic_ai.run import AgentRunResult


class TokenMonitor:
    """
    Token usage monitor for Pydantic AI agents.

    Tracks token consumption and enforces context limits with progressive
    warnings at 70%, 80%, 90% and forced closure at 95%.

    Usage:
        monitor = TokenMonitor(deps=deps)
        result = await monitor.run("User message")
    """

    def __init__(self, deps: AtmanDeps) -> None:
        """
        Initialize token monitor.

        Args:
            deps: Dependency container with services and configuration
        """
        self._deps = deps
        self._triggered: set[int] = set()

        # Get model identifier
        model = "test"
        if deps.model_config:
            model = deps.model_config.model

        # Initialize Pydantic AI agent
        self._agent: Agent[AtmanDeps, str] = Agent(
            model=model,
            deps_type=AtmanDeps,
            instructions=lambda ctx: build_instructions(ctx.deps),
            tools=[record_key_moment, log_experience],
        )

    async def run(self, user_message: str) -> AgentRunResult[str]:
        """
        Run agent with a user message and monitor token usage.

        Args:
            user_message: Message from the user

        Returns:
            AgentRunResult with agent response and usage data

        Raises:
            ContextLimitExceeded: If 95% threshold is reached
        """
        # Run agent
        result = await self._agent.run(user_message, deps=self._deps)

        # Check token usage after run
        await self._check_token_threshold(result)

        return result

    async def _check_token_threshold(self, result: AgentRunResult[str]) -> None:
        """
        Check token usage and inject warnings if thresholds are crossed.

        Args:
            result: Result from agent.run() containing usage data
        """
        usage = result.usage()
        if not usage or not usage.input_tokens:
            return

        # Get context limit from deps.model_config
        context_limit = 8192  # default
        if self._deps.model_config:
            context_limit = self._deps.model_config.context_limit

        # Calculate ratio
        ratio = usage.input_tokens / context_limit

        # Check 95% - force close
        if ratio >= 0.95 and 95 not in self._triggered:
            remaining = context_limit - usage.input_tokens
            warning = (
                "[SYSTEM CRITICAL] Context limit reached (95%). "
                f"Remaining: {remaining} tokens. Session will be terminated."
            )
            self._inject_warning(warning)
            self._triggered.add(95)
            raise ContextLimitExceeded(f"Context usage at {ratio:.1%} (95% threshold)")

        # Check 90%
        if ratio >= 0.90 and 90 not in self._triggered:
            remaining = context_limit - usage.input_tokens
            warning = (
                f"[SYSTEM WARNING] Context at 90% — {remaining} tokens left. "
                "Consider finishing soon."
            )
            self._inject_warning(warning)
            self._triggered.add(90)

        # Check 80%
        if ratio >= 0.80 and 80 not in self._triggered:
            remaining = context_limit - usage.input_tokens
            warning = f"[SYSTEM INFO] Context at 80% — {remaining} tokens remaining."
            self._inject_warning(warning)
            self._triggered.add(80)

        # Check 70% - full warning
        if ratio >= 0.70 and 70 not in self._triggered:
            remaining = context_limit - usage.input_tokens
            warning = (
                f"[SYSTEM NOTICE] Session context filling up — "
                f"approximately {remaining} tokens remaining.\n"
                "When ready — call restart_session."
            )
            self._inject_warning(warning)
            self._triggered.add(70)

    def _inject_warning(self, warning: str) -> None:
        """
        Inject warning message into agent context.

        For now, we log the warning. In a full implementation,
        this would append to the message history.

        Args:
            warning: Warning message to inject
        """
        import logging

        _LOG = logging.getLogger(__name__)
        _LOG.warning("Token threshold reached: %s", warning)

    def reset_triggers(self) -> None:
        """Reset triggered thresholds on session restart."""
        self._triggered.clear()


class ContextLimitExceeded(Exception):
    """Raised when context usage exceeds 95% threshold."""

    pass
