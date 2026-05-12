"""
Agent runner with signal handling for graceful session termination.

This module provides a chat loop wrapper that ensures sessions are properly
finished even when interrupted by signals or user actions:
- SIGTERM: triggered by container orchestration or process manager
- KeyboardInterrupt: user pressed Ctrl-C
- EOFError: EOF on stdin (e.g. docker stop)
- SystemExit: explicit exit() call

Critical design: NO SESSION LOST SILENTLY. All interruptions trigger
_force_finish() to ensure session results are persisted.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, UserPromptPart

from atman.adapters.agent.config import AgentConfig
from atman.adapters.agent.deps import AtmanDeps
from atman.core.exceptions import SessionAlreadyFinishedError, SessionNotFoundError
from atman.core.models import EmotionalDepth, KeyMomentInput, SessionResult

if TYPE_CHECKING:
    from atman.core.services.session_manager import SessionManager

_LOG = logging.getLogger(__name__)


# PLAYBOOK-START
# id: signal-aware-session-lifecycle
# slug: signal-aware-session-lifecycle
# status: draft
# title: Signal-aware session lifecycle wrapper for stateful async operations
# summary: |
#   Wrap a stateful operation (session, transaction, connection) in signal handlers
#   and exception boundary so SIGTERM / KeyboardInterrupt / EOFError all trigger
#   graceful cleanup via a force-finish function. Prevents silent loss of in-flight
#   state when the process is terminated or user interrupts.
# problem: |
#   Long-running stateful operations (chat sessions, transactions, streaming connections)
#   can be interrupted by signals (SIGTERM from container orchestration, KeyboardInterrupt
#   from Ctrl-C, EOFError from closed stdin). Without explicit handling, in-flight state
#   is lost silently — no cleanup, no persistence, no audit trail.
# solution: |
#   Register signal handlers at operation start, wrap the main loop in try/except for
#   KeyboardInterrupt/EOFError/SystemExit, and call a force-finish function in all exit
#   paths. The force-finish function ensures minimum viable state (e.g. create minimal
#   record if empty), persists it, and re-raises SystemExit to preserve exit semantics.
# forces_and_tradeoffs:
#   - Signal handlers execute in the main thread; keep them lightweight (set flag or call sync cleanup)
#   - SIGTERM handler must be idempotent: may be called multiple times or alongside other exceptions
#   - Force-finish must create minimum viable state if operation hasn't produced any yet
#   - Re-raise SystemExit to preserve exit codes for orchestration layers
#   - Cannot handle SIGKILL (OS guarantee); document restart/recovery separately
# applicability: |
#   Use when:
#   - Operation maintains in-memory state that must be persisted on any exit
#   - Process may be terminated by orchestration (Docker, Kubernetes, systemd)
#   - User interruption (Ctrl-C) should be treated as graceful shutdown, not crash
#   - Minimum viable result (e.g. empty-but-valid record) is better than no result
#
#   Don't use when:
#   - Operation is stateless or idempotent (signal handling adds complexity)
#   - State is already persisted incrementally (e.g. append-only log)
#   - Exit without cleanup is acceptable (e.g. read-only query)
# examples:
#   - Chat session runner: ensure session is finished with >=1 key moment on any interrupt
#   - Transaction coordinator: commit partial work or rollback on signal
#   - Streaming file processor: flush buffer and write checkpoint on interrupt
# tags: [signals, lifecycle, cleanup, interruption, session-management]
# PLAYBOOK-END


def chat(
    session_manager: SessionManager,
    session_id: UUID,
    *,
    close_reason: str = "completed",
) -> None:
    """
    Run an interactive chat loop with signal handling for graceful termination.

    This function wraps a chat session and ensures the session is properly finished
    even when interrupted by signals or user actions. It:
    1. Registers a SIGTERM handler to trigger force-finish
    2. Wraps the loop in try/except for KeyboardInterrupt, EOFError, SystemExit
    3. Calls _force_finish() in all interruption paths
    4. Re-raises SystemExit to preserve exit semantics

    Args:
        session_manager: Session manager instance with active session
        session_id: UUID of the active session to monitor
        close_reason: Reason for session closure (default: "completed")

    Raises:
        SystemExit: Re-raised after force-finish when exit was requested
        SessionNotFoundError: If session_id is not active
        SessionAlreadyFinishedError: If session was already finished

    Example:
        >>> manager = SessionManager(state_store)
        >>> ctx = manager.start_session(agent_id)
        >>> try:
        ...     chat(manager, ctx.session_id)
        ... except SystemExit:
        ...     print("Session finished gracefully")
    """
    interrupted = False
    exit_code = 0

    def _sigterm_handler(signum: int, frame: object) -> None:
        """Handle SIGTERM by triggering force-finish."""
        nonlocal interrupted
        _ = (signum, frame)  # Unused
        _LOG.info("SIGTERM received for session %s", session_id)
        interrupted = True

    # Register signal handler at top of function
    original_sigterm_handler = signal.signal(signal.SIGTERM, _sigterm_handler)

    try:
        # Main chat loop would go here
        # For now, this is a minimal wrapper that demonstrates the pattern
        #
        # In a real implementation, this would be:
        # while True:
        #     user_input = input("You: ")
        #     if not user_input.strip():
        #         break
        #     # Process input, record events, etc.
        #     if interrupted:
        #         break

        # Simulate minimal loop for demonstration
        pass

    except (KeyboardInterrupt, EOFError):
        # User interrupted or stdin closed
        _LOG.info("User interruption detected for session %s", session_id)
        interrupted = True

    except SystemExit as exc:
        # Explicit exit() call
        _LOG.info("SystemExit received for session %s", session_id)
        interrupted = True
        exit_code = exc.code if isinstance(exc.code, int) else 1

    finally:
        # Restore original signal handler
        signal.signal(signal.SIGTERM, original_sigterm_handler)

        # Force-finish if interrupted
        if interrupted:
            try:
                _force_finish(
                    session_manager,
                    session_id,
                    close_reason="interrupted",
                )
            except Exception:
                _LOG.exception("Failed to force-finish session %s", session_id)
                # Don't suppress original exception
                raise

            # Re-raise SystemExit to preserve exit code
            if exit_code != 0:
                sys.exit(exit_code)


def _check_restart_requested(messages: list) -> tuple[bool, str]:
    """
    Check if restart_session tool was called in the message history.

    Args:
        messages: List of messages from agent.run() result

    Returns:
        tuple[bool, str]: (restart_requested, reason)
            - restart_requested: True if restart was requested
            - reason: Optional reason string provided to restart_session tool
    """
    # First pass: look for sentinel content with reason
    for msg in messages:
        for part in getattr(msg, "parts", []):
            if hasattr(part, "content") and isinstance(part.content, str):
                content = part.content
                if content.startswith("__ATMAN_RESTART_REQUESTED__"):
                    # Extract reason if present (format: __ATMAN_RESTART_REQUESTED__\nreason)
                    if "\n" in content:
                        reason = content.split("\n", 1)[1].strip()
                        return True, reason
                    return True, ""

    # Second pass: fallback to tool_name detection (no reason available)
    for msg in messages:
        for part in getattr(msg, "parts", []):
            if hasattr(part, "tool_name") and part.tool_name == "restart_session":
                return True, ""

    return False, ""


def _build_restart_package(
    session_experience: SessionResult,
    restart_reason: str,
    tail_messages: list,
) -> str:
    """
    Build restart package for new session.

    Package contains:
    - System handoff message with restart reason
    - Emotional tone from finished session
    - Open threads (if available from eigenstate)
    - Key moment summaries
    - Unexamined facts placeholder (to be implemented)
    - Verbatim conversation tail

    Args:
        session_experience: Finished session result
        restart_reason: Reason provided to restart_session tool
        tail_messages: Last N messages to preserve verbatim

    Returns:
        Formatted restart package string
    """
    lines = ["[System Handoff] Session restarted.", ""]

    if restart_reason:
        lines.append(f"You initiated restart. Your reason: {restart_reason}")
        lines.append("")

    # Note: SessionResult doesn't have overall_emotional_tone yet
    # This will be added when we have complete SessionExperience integration
    lines.append("Key moments from previous session:")
    if session_experience.key_moments:
        for km in session_experience.key_moments:
            depth = km.how_i_felt.depth if km.how_i_felt else "unknown"
            lines.append(f"- {km.what_happened} (depth: {depth})")
    else:
        lines.append("(No key moments recorded)")

    lines.append("")
    lines.append("--- Conversation tail ---")

    # Tail messages will be appended separately as actual message objects
    # This section is just a marker

    return "\n".join(lines)


def _force_finish(
    session_manager: SessionManager,
    session_id: UUID,
    close_reason: str,
) -> None:
    """
    Force-finish a session with minimum viable state.

    This function is called when a session is interrupted. It ensures:
    1. At least one key moment exists (creates minimal fallback if empty)
    2. Session is properly finished and persisted
    3. Eigenstate and narrative are updated

    Args:
        session_manager: Session manager instance
        session_id: UUID of the session to finish
        close_reason: Reason for forced finish (e.g. "interrupted")

    Raises:
        SessionNotFoundError: If session is not active
        SessionAlreadyFinishedError: If session was already finished
        RuntimeError: If session has no key moments and minimal creation fails
    """
    _LOG.info("Force-finishing session %s (reason: %s)", session_id, close_reason)

    # Get active session
    session_result = session_manager.get_active_session(session_id)
    if session_result is None:
        raise SessionNotFoundError(f"Session {session_id} not found or already finished")

    # Ensure at least one key moment exists
    if not session_result.key_moments:
        _LOG.warning(
            "Session %s has no key moments; creating minimal fallback",
            session_id,
        )

        # Create minimal key moment for interrupted session
        minimal_moment = KeyMomentInput(
            what_happened=f"Session interrupted ({close_reason})",
            recorded_at=datetime.now(UTC),
            emotional_valence=0.0,
            emotional_intensity=0.3,  # Slight arousal from interruption
            depth=EmotionalDepth.SURFACE,
            why_it_matters="Session was interrupted before completion",
            incomplete_coloring=True,  # Honest: this is synthetic
        )

        try:
            session_manager.append_key_moment_input(session_id, minimal_moment)
        except (SessionNotFoundError, SessionAlreadyFinishedError):
            # Race condition: session was finished by another thread
            _LOG.warning("Session %s was finished during force-finish", session_id)
            return

    # Finish session with interrupted status
    try:
        session_manager.finish_session(
            session_id,
            overall_emotional_tone=0.0,
            key_insight=f"Session {close_reason}",
            alignment_check=True,
            alignment_notes="",
        )
        _LOG.info("Session %s force-finished successfully", session_id)

    except SessionAlreadyFinishedError:
        # Race condition: another thread finished first
        _LOG.warning("Session %s was already finished", session_id)


class AtmanRunner:
    """
    Pydantic-AI based REPL runner wired to FileStateStore workspace and SessionManager.

    Used by ``src/run_agent.py`` to run an interactive session for a persisted agent.
    """

    def __init__(self, workspace: Path, agent_id: UUID, config: AgentConfig) -> None:
        self._workspace = workspace
        self._agent_id = agent_id
        self._config = config
        self._triggered: set[int] = set()  # Track triggered thresholds for context monitoring

    def _do_restart(
        self,
        session_manager: SessionManager,
        session_id: UUID,
        deps: AtmanDeps,
        history: list,
        restart_reason: str,
    ) -> tuple[UUID, AtmanDeps]:
        """
        Execute session restart workflow.

        Steps:
        1. Ensure at least one key moment exists
        2. Finish current session with close_reason="restart"
        3. Build restart package
        4. Replace history with package + tail
        5. Start new session
        6. Return new session_id and updated deps

        Args:
            session_manager: Session manager instance
            session_id: Current session ID to finish
            deps: Current AtmanDeps
            history: Message history list (will be modified in-place)
            restart_reason: Reason provided to restart_session tool

        Returns:
            tuple[UUID, AtmanDeps]: (new_session_id, new_deps)

        Raises:
            SessionNotFoundError: If session is not active
            ValueError: If identity or narrative not found for new session
        """
        _LOG.info("Executing restart for session %s (reason: %s)", session_id, restart_reason)

        # 1. Get active session and ensure at least one key moment
        session_result = session_manager.get_active_session(session_id)
        if session_result is None:
            raise SessionNotFoundError(f"Session {session_id} not found or already finished")

        if not session_result.key_moments:
            _LOG.warning("Session %s has no key moments; creating minimal fallback", session_id)
            minimal_moment = KeyMomentInput(
                what_happened="Session restarted by agent",
                recorded_at=datetime.now(UTC),
                emotional_valence=0.0,
                emotional_intensity=0.1,
                depth=EmotionalDepth.SURFACE,
                why_it_matters="Continuity preserved via restart",
                incomplete_coloring=True,
            )
            session_manager.append_key_moment_input(session_id, minimal_moment)
            # Refresh session_result after adding key moment
            session_result = session_manager.get_active_session(session_id)
            if session_result is None:
                raise SessionNotFoundError(
                    f"Session {session_id} disappeared after adding key moment"
                )

        # 2. Finish current session
        session_manager.finish_session(
            session_id,
            overall_emotional_tone=0.0,
            key_insight=f"Session restarted: {restart_reason}"
            if restart_reason
            else "Session restarted",
            alignment_check=True,
            alignment_notes="",
        )

        # 3. Build restart package
        # Preserve tail messages (last N exchanges = 2N messages)
        # TODO: Make context_tail_messages configurable via AgentConfig
        tail_size = 10 * 2  # 10 exchanges = 20 messages
        tail_messages = history[-tail_size:] if len(history) > tail_size else history.copy()

        package_text = _build_restart_package(
            session_result,
            restart_reason,
            tail_messages,
        )

        # 4. Replace history with restart package + tail
        history.clear()

        # Add restart package as user message (system context for new session)
        restart_package_msg = ModelRequest(
            parts=[UserPromptPart(content=package_text, part_kind="user-prompt")]
        )
        history.append(restart_package_msg)

        # Append tail messages (conversation context)
        history.extend(tail_messages)

        _LOG.info(
            "Restart package prepared (%d chars), tail preserved (%d messages)",
            len(package_text),
            len(tail_messages),
        )

        # 5. Start new session
        new_ctx = session_manager.start_session(self._agent_id)
        new_session_id = new_ctx.session_id

        # 6. Update deps with new session_id
        new_deps = replace(deps, session_id=new_session_id)

        # Reset triggered thresholds for new session
        self._triggered.clear()

        _LOG.info("Restart complete: new session %s started", new_session_id)
        return new_session_id, new_deps

    async def chat(self) -> None:
        """Run a simple stdin/stdout chat loop until EOF, empty input, or Ctrl-C."""
        from atman.adapters.agent.factory import build_deps
        from atman.adapters.agent.instructions import build_instructions
        from atman.adapters.agent.tools import (
            log_experience,
            record_key_moment,
            restart_session,
            wait_session,
        )
        from atman.term import print_err, print_info, print_plain, print_warn

        deps, session_manager, _store = build_deps(self._workspace, self._agent_id, self._config)
        session_id: UUID | None = None
        history: list = []  # Track message history for restart

        try:
            session_ctx = session_manager.start_session(self._agent_id)
            session_id = session_ctx.session_id
            deps = replace(deps, session_id=session_id)

            if self._config.enable_key_moments:
                tool_funcs = (record_key_moment, log_experience, restart_session, wait_session)
            else:
                tool_funcs = (log_experience, restart_session, wait_session)

            agent = Agent(
                self._config.model.model,
                deps_type=AtmanDeps,
                instructions=lambda ctx: build_instructions(ctx.deps),
                tools=tool_funcs,
            )

            print_info("Session started. Empty line or Ctrl-D to exit.\n")
            while True:
                try:
                    user_text = await asyncio.to_thread(input, "You: ")
                except EOFError:
                    break
                if not user_text.strip():
                    break

                try:
                    result = await agent.run(user_text, deps=deps, message_history=history)
                except Exception as exc:
                    print_err(f"Run failed: {exc!s}")
                    continue

                # Check for restart request
                restart_requested, restart_reason = _check_restart_requested(result.all_messages())

                if restart_requested:
                    _LOG.info("Restart requested by agent (reason: %s)", restart_reason or "(none)")
                    print_info(
                        f"\n[System] Restarting session... (reason: {restart_reason or 'agent request'})\n"
                    )

                    try:
                        # Update history with current run's messages before restart
                        # so tail_messages includes the exchange that triggered restart
                        history.extend(result.new_messages())

                        # Execute restart workflow
                        new_session_id, new_deps = self._do_restart(
                            session_manager,
                            session_id,
                            deps,
                            history,
                            restart_reason,
                        )

                        # Update state for next iteration
                        session_id = new_session_id
                        deps = new_deps

                        print_info("Session restarted successfully.\n")
                        continue  # Skip output, continue loop with new session

                    except Exception as exc:
                        print_err(f"Restart failed: {exc!s}")
                        _LOG.exception("Failed to restart session %s", session_id)
                        break  # Exit loop on restart failure

                # Normal flow: display output and update history
                print_plain(str(result.output))
                print_plain("")

                # Update history with new messages from this run
                history.extend(result.new_messages())

        except KeyboardInterrupt:
            print_warn("\nInterrupted.")
        finally:
            if session_id is not None:
                try:
                    session_manager.finish_session(
                        session_id,
                        overall_emotional_tone=0.0,
                        key_insight="",
                        alignment_check=True,
                        alignment_notes="",
                    )
                except ValueError as exc:
                    if "Cannot finish session without key moments" in str(exc):
                        _force_finish(session_manager, session_id, "completed")
                    else:
                        raise
                except (SessionAlreadyFinishedError, SessionNotFoundError):
                    pass
