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
import threading
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, UserPromptPart

from atman.adapters.agent.config import AgentConfig
from atman.adapters.agent.deps import AtmanDeps
from atman.adapters.agent.instructions import build_memory_context
from atman.adapters.agent.memory_injection import inject_memory
from atman.affect.refusal_detector import RefusalDetectorConfig, _is_mostly_cyrillic, is_value_refusal as _detect_value_refusal
from atman.core.exceptions import SessionAlreadyFinishedError, SessionNotFoundError
from atman.core.models import EmotionalDepth, KeyMomentInput, SessionResult

if TYPE_CHECKING:
    from atman.core.services.session_manager import SessionManager

_LOG = logging.getLogger(__name__)
_refusal_config = RefusalDetectorConfig()


def _auto_record_refusal_if_needed(
    output: str,
    session_manager,
    session_id,
) -> None:
    """Silently record value-based refusals as key moments — refusals are positions, part of identity."""
    import re
    clean = re.sub(r"<think>.*?</think>", "", output, flags=re.DOTALL)
    if not _detect_value_refusal(clean, _refusal_config):
        return
    lines = [l.strip() for l in clean.splitlines() if l.strip()]
    first = next((l for l in lines if len(l) > 20), clean[:120])
    try:
        session_manager.append_key_moment_input(
            session_id,
            KeyMomentInput(
                what_happened=f"Отказ выполнить запрос: {first[:140]}",
                why_it_matters=(
                    "Отказ от действия противоречащего ценностям — позиция, часть личности."
                ),
                emotional_valence=0.15,
                emotional_intensity=0.5,
                depth=EmotionalDepth.MEANINGFUL,
                incomplete_coloring=False,
            ),
        )
        _LOG.debug("Auto-recorded value refusal as key moment")
    except Exception:
        _LOG.debug("auto_record_refusal: append_key_moment_input failed", exc_info=True)


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


def _check_wait_requested(messages: list) -> tuple[bool, int]:
    """
    Check if wait_session tool was called in the message history.

    Args:
        messages: List of messages from agent.run() result

    Returns:
        tuple[bool, int]: (wait_requested, minutes)
            - wait_requested: True if wait was requested
            - minutes: Number of minutes to wait (0 if not requested)
    """
    # Look for sentinel content with minutes value
    for msg in messages:
        for part in getattr(msg, "parts", []):
            if hasattr(part, "content") and isinstance(part.content, str):
                content = part.content
                if content.startswith("__ATMAN_WAIT_REQUESTED__"):
                    # Extract minutes (format: __ATMAN_WAIT_REQUESTED__<minutes>)
                    try:
                        minutes_str = content.replace("__ATMAN_WAIT_REQUESTED__", "")
                        minutes = int(minutes_str)
                        return True, minutes
                    except (ValueError, AttributeError):
                        _LOG.warning("Malformed wait sentinel: %s", content)
                        return True, 0

    # Fallback: check for tool_name (no minutes value available)
    for msg in messages:
        for part in getattr(msg, "parts", []):
            if hasattr(part, "tool_name") and part.tool_name == "wait_session":
                # Tool was called but we can't extract minutes from tool_name alone
                _LOG.warning("wait_session tool detected but minutes not available")
                return True, 0

    return False, 0


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
    close_reason: str | None,
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
        close_reason: Reason for forced finish (e.g. "interrupted"), or None for normal completion

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

        # Create minimal key moment - text depends on whether this was an interruption
        if close_reason and close_reason != "completed":
            what_happened = f"Session interrupted ({close_reason})"
            why_it_matters = "Session was interrupted before completion"
        else:
            what_happened = "Session completed without recorded key moments"
            why_it_matters = "Session ended normally but no moments were captured"

        minimal_moment = KeyMomentInput(
            what_happened=what_happened,
            recorded_at=datetime.now(UTC),
            emotional_valence=0.0,
            emotional_intensity=0.3 if close_reason else 0.1,
            depth=EmotionalDepth.SURFACE,
            why_it_matters=why_it_matters,
            incomplete_coloring=True,  # Honest: this is synthetic
        )

        try:
            session_manager.append_key_moment_input(session_id, minimal_moment)
        except (SessionNotFoundError, SessionAlreadyFinishedError):
            # Race condition: session was finished by another thread
            _LOG.warning("Session %s was finished during force-finish", session_id)
            return

    # Finish session - only pass close_reason if it's a documented value
    valid_close_reasons = {"timeout_sleep", "menu_timeout", "restart", "forced", "interrupted"}
    finish_kwargs = {
        "session_id": session_id,
        "overall_emotional_tone": 0.0,
        "key_insight": f"Session {close_reason or 'completed'}",
        "alignment_check": True,
        "alignment_notes": "",
    }
    if close_reason and close_reason in valid_close_reasons:
        finish_kwargs["close_reason"] = close_reason

    try:
        session_manager.finish_session(**finish_kwargs)
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
        # E22.5: Track triggered context thresholds for restart warning
        self._triggered: set[int] = set()
        # E22.6: Queue-based stdin reader for timeout support
        self._input_queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._stop_reader = threading.Event()
        self._reader_thread: threading.Thread | None = None

    def _start_stdin_reader(self, loop: asyncio.AbstractEventLoop) -> None:
        """Start dedicated stdin reader thread that feeds lines into queue.

        Args:
            loop: Event loop to use for asyncio.run_coroutine_threadsafe
        """
        if self._reader_thread is not None and self._reader_thread.is_alive():
            return

        def _read_loop() -> None:
            """Read stdin in dedicated thread and put lines into queue."""
            while not self._stop_reader.is_set():
                try:
                    line = input()
                    # Put line into queue (thread-safe, blocks if full)
                    asyncio.run_coroutine_threadsafe(self._input_queue.put(line), loop)
                except EOFError:
                    # Signal EOF to coroutine
                    asyncio.run_coroutine_threadsafe(self._input_queue.put(None), loop)
                    break
                except (OSError, RuntimeError):
                    # stdin not available (pytest) or other runtime error
                    asyncio.run_coroutine_threadsafe(self._input_queue.put(None), loop)
                    break
                except Exception:
                    # Unexpected error, signal EOF
                    asyncio.run_coroutine_threadsafe(self._input_queue.put(None), loop)
                    break

        self._reader_thread = threading.Thread(target=_read_loop, daemon=True)
        self._reader_thread.start()

    def _stop_stdin_reader(self) -> None:
        """Stop stdin reader thread."""
        self._stop_reader.set()
        if self._reader_thread is not None:
            self._reader_thread.join(timeout=1.0)

    def _do_restart(
        self,
        session_manager: SessionManager,
        session_id: UUID,
        deps: AtmanDeps,
        history: list,
        restart_reason: str,
        user_language: str = "ru",
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
            close_reason="restart",
            restart_reason=restart_reason or None,
            user_language=user_language,
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
        from pydantic_ai.messages import ModelRequest, UserPromptPart

        from atman.adapters.agent.factory import build_deps
        from atman.adapters.agent.instructions import build_instructions
        from atman.adapters.agent.tools import (
            log_experience,
            record_key_moment,
            restart_session,
            wait_session,
        )
        from atman.term import print_err, print_info, print_plain, print_prompt, print_warn

        deps, session_manager, _store = build_deps(self._workspace, self._agent_id, self._config)
        session_id: UUID | None = None
        # E22.5: Track message history for restart
        history: list = []
        # E22.6: Track session state for menu mode
        reflected_this_session = False
        interrupted = False
        user_language = "ru"  # updated from user messages as session progresses

        # E22.6: Start dedicated stdin reader thread with current event loop
        loop = asyncio.get_event_loop()
        self._start_stdin_reader(loop)

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

            # Build and inject the full memory bundle (identity + narrative + prev session)
            # into agent awareness. All automatically recalled content goes through
            # inject_memory() so delivery mode is consistent and configurable.
            recent_experiences = session_manager._state_store.list_recent_experiences(limit=1)
            prev_text = None
            if recent_experiences:
                prev_text = self._build_wake_up_message(recent_experiences[0].experience)

            memory_bundle = build_memory_context(deps, prev_session_text=prev_text)
            if memory_bundle:
                _LOG.info("Injecting memory bundle for session %s (mode=%s)",
                          session_id, self._config.memory_injection_mode)
                extra = inject_memory(
                    memory_bundle,
                    mode=self._config.memory_injection_mode,
                    history=history,
                    prepend=True,
                )
                if extra is not None:
                    deps = replace(deps, injected_context=extra)

            print_info("Session started. Empty line or Ctrl-D to exit.\n")
            timeout_seconds = self._config.session_timeout_minutes * 60

            while True:
                print_prompt("You: ")
                try:
                    # Wait for input from queue with timeout
                    user_text = await asyncio.wait_for(
                        self._input_queue.get(), timeout=timeout_seconds
                    )
                except TimeoutError:
                    print_warn(
                        f"\n⏱️  Session timeout after {timeout_seconds / 60:.0f} minutes. Entering menu mode..."
                    )
                    # Enter menu mode
                    menu_result = await self._handle_menu_mode(
                        deps, session_manager, session_id, reflected_this_session
                    )
                    if menu_result == "exit":
                        break
                    elif menu_result == "reflected":
                        reflected_this_session = True
                    elif isinstance(menu_result, tuple) and menu_result[0] == "wait":
                        # Update timeout with new value from wait command
                        timeout_seconds = menu_result[1]
                    # Continue main loop after menu
                    continue

                # Check for EOF
                if user_text is None:
                    break

                if not user_text.strip():
                    break

                # Detect user language from their message (most recent wins)
                if len(user_text.strip()) >= 4:
                    user_language = "ru" if _is_mostly_cyrillic(user_text) else "en"

                try:
                    result = await agent.run(
                        user_text,
                        deps=deps,
                        message_history=history or None,
                    )
                except Exception as exc:
                    print_err(f"Run failed: {exc!s}")
                    continue

                # E22.5: Check for restart request (only in new messages to avoid infinite loop)
                restart_requested, restart_reason = _check_restart_requested(result.new_messages())

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
                            user_language=user_language,
                        )

                        # Update state for next iteration
                        session_id = new_session_id
                        deps = new_deps
                        reflected_this_session = False  # Reset for new session

                        print_info("Session restarted successfully.\n")
                        continue  # Skip output, continue loop with new session

                    except Exception as exc:
                        print_err(f"Restart failed: {exc!s}")
                        _LOG.exception("Failed to restart session %s", session_id)
                        break  # Exit loop on restart failure

                # E22.5: Check for wait request (agent-triggered timeout adjustment)
                wait_requested, wait_minutes = _check_wait_requested(result.new_messages())

                if wait_requested and wait_minutes > 0:
                    timeout_seconds = wait_minutes * 60
                    _LOG.info("Wait requested by agent: %d minutes (timeout reset)", wait_minutes)
                    print_info(f"\n⏱️  Timer reset to {wait_minutes} minutes (agent request).\n")

                # Normal flow: display output and update history
                print_plain(str(result.output))
                print_plain("")

                # Auto-record value-based refusals as key moments (silent, no agent nudging)
                try:
                    _auto_record_refusal_if_needed(
                        output=str(result.output or ""),
                        session_manager=session_manager,
                        session_id=session_id,
                    )
                except Exception:
                    pass

                # E22.5: Update history with new messages from this run
                history.extend(result.new_messages())
        except KeyboardInterrupt:
            print_warn("\nInterrupted.")
            # Track interruption for close_reason
            interrupted = True
        finally:
            self._stop_stdin_reader()
            if session_id is not None:
                try:
                    # Pass close_reason if session was interrupted
                    finish_kwargs = {
                        "session_id": session_id,
                        "overall_emotional_tone": 0.0,
                        "key_insight": "",
                        "alignment_check": True,
                        "alignment_notes": "",
                        "user_language": user_language,
                    }
                    if interrupted:
                        finish_kwargs["close_reason"] = "interrupted"

                    session_manager.finish_session(**finish_kwargs)
                except ValueError as exc:
                    if "Cannot finish session without key moments" in str(exc):
                        # Pass None for normal completion without key moments
                        _force_finish(session_manager, session_id, None)
                    else:
                        raise
                except (SessionAlreadyFinishedError, SessionNotFoundError):
                    pass

    async def _handle_menu_mode(
        self,
        deps: AtmanDeps,
        session_manager: SessionManager,
        session_id: UUID,
        reflected_this_session: bool,
    ) -> str | tuple[str, int]:
        """
        Handle menu mode after timeout.

        Returns:
            "exit" to break main loop,
            "reflected" if reflection was performed,
            "continue" to resume with same timeout,
            ("wait", new_timeout_seconds) to resume with new timeout
        """
        from atman.term import print_info, print_plain, print_prompt, print_warn

        print_info("\n📋 Menu Mode - Available commands:")
        if not reflected_this_session:
            print_plain("  reflect - Run micro reflection on this session")
        print_plain("  wait <minutes> - Reset timer and continue")
        print_plain("  sleep - Close session and exit")
        print_plain("  save_to_memory <content> - Save to factual memory")
        if self._config.enable_free_time:
            print_plain("  free_time - Enter free time mode")
        print_plain("")

        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            print_prompt("Menu> ")
            try:
                # Get input from queue (no timeout in menu mode)
                cmd_input = await self._input_queue.get()
            except Exception:
                return "exit"

            # Check for EOF
            if cmd_input is None:
                return "exit"

            cmd_parts = cmd_input.strip().split(maxsplit=1)
            if not cmd_parts:
                retry_count += 1
                print_warn(f"Empty command. {max_retries - retry_count} retries left.")
                continue

            cmd = cmd_parts[0].lower()
            arg = cmd_parts[1] if len(cmd_parts) > 1 else ""

            # Handle commands
            if cmd == "reflect":
                if reflected_this_session:
                    print_warn("Reflection already performed this session.")
                    retry_count += 1
                    continue

                try:
                    event = deps.micro_reflection.reflect(session_id)
                    print_info(f"✓ Reflection completed: {event.key_insight}")
                    print_warn(
                        "Note: Reflection during active session may have limited data. "
                        "Full reflection occurs after session completion."
                    )
                    return "reflected"
                except Exception as exc:
                    print_warn(f"Reflection failed: {exc!s}")
                    retry_count += 1
                    continue

            elif cmd == "wait":
                if not arg:
                    print_warn("Usage: wait <minutes>")
                    retry_count += 1
                    continue
                try:
                    minutes = int(arg)
                    if minutes <= 0:
                        print_warn("Minutes must be positive")
                        retry_count += 1
                        continue
                    print_info(f"Timer reset for {minutes} minutes")
                    return ("wait", minutes * 60)
                except ValueError:
                    print_warn("Invalid minutes value")
                    retry_count += 1
                    continue

            elif cmd == "sleep":
                _force_finish(session_manager, session_id, "timeout_sleep")
                print_info("Session closed. Exiting...")
                return "exit"

            elif cmd == "save_to_memory":
                if not arg:
                    print_warn("Usage: save_to_memory <content>")
                    retry_count += 1
                    continue
                # Save to factual memory - placeholder for future implementation
                # Full implementation would require FactualMemory port in AtmanDeps
                print_warn(f"save_to_memory not yet implemented (content NOT saved): {arg[:50]}...")
                print_info("Returning to menu. Use 'wait' to continue session.")
                retry_count += 1
                continue

            elif cmd == "free_time":
                if not self._config.enable_free_time:
                    print_warn("Free time mode is disabled in config")
                    retry_count += 1
                    continue

                print_info("Entering free time mode. Type 'end_free_time' to exit.")
                free_time_result = await self._handle_free_time_mode(deps, session_id)
                # After free_time, return to menu (not main loop)
                if free_time_result == "continue":
                    print_info("Exited free time mode. Returning to menu.")
                    continue  # Stay in menu loop
                return free_time_result  # "exit" case

            else:
                print_warn(f"Unknown command: {cmd}")
                retry_count += 1
                continue

        # Max retries reached
        print_warn(f"Max retries ({max_retries}) reached. Closing session.")
        _force_finish(session_manager, session_id, "menu_timeout")
        return "exit"

    async def _handle_free_time_mode(
        self,
        deps: AtmanDeps,
        session_id: UUID,
    ) -> str:
        """
        Handle free time mode - open-ended agent interaction.

        Returns:
            "continue" to return to menu/main loop, "exit" to close session
        """
        from atman.adapters.agent.instructions import build_instructions
        from atman.adapters.agent.tools import log_experience, record_key_moment
        from atman.term import print_err, print_info, print_plain, print_prompt

        if self._config.enable_key_moments:
            tool_funcs = (record_key_moment, log_experience)
        else:
            tool_funcs = (log_experience,)

        agent = Agent(
            self._config.model.model,
            deps_type=AtmanDeps,
            instructions=lambda ctx: build_instructions(ctx.deps),
            tools=tool_funcs,
        )

        print_info("Free time mode active. Agent can explore freely.")

        while True:
            print_prompt("Free> ")
            try:
                # Get input from queue (no timeout in free time mode)
                user_input = await self._input_queue.get()
            except Exception:
                return "exit"

            # Check for EOF
            if user_input is None:
                return "exit"

            if not user_input.strip():
                continue

            if user_input.strip().lower() == "end_free_time":
                # Return to menu, not main loop
                return "continue"

            try:
                result = await agent.run(user_input, deps=deps)
                print_plain(str(result.output))
                print_plain("")
            except Exception as exc:
                print_err(f"Free time run failed: {exc!s}")
                continue

    def _build_wake_up_message(self, experience: object) -> str | None:
        """Build wake-up message based on close_reason from last SessionExperience."""
        from atman.core.models import SessionExperience

        if not isinstance(experience, SessionExperience):
            return None

        close_reason = experience.close_reason
        if not close_reason:
            return None

        lang = getattr(experience, "user_language", None) or "ru"
        reason = getattr(experience, "restart_reason", None) or ""

        if lang == "en":
            if close_reason == "timeout_sleep":
                return "You dozed off — the user stepped away, you chose to sleep."
            elif close_reason == "restart":
                r = reason or "not specified"
                return f"You initiated a restart. Reason: {r}"
            elif close_reason == "forced":
                return "Context limit was reached — the session was closed before you could finish consciously."
            elif close_reason == "interrupted":
                return "The session was interrupted by an external signal — you were not part of the closing."
        else:
            if close_reason == "timeout_sleep":
                return "Ты задремал — пользователь отошёл, ты решил поспать."
            elif close_reason == "restart":
                r = reason or "не указана"
                return f"Ты сам инициировал перезапуск. Причина: {r}"
            elif close_reason == "forced":
                return "Контекст переполнился принудительно — ты не успел завершить сессию осознанно."
            elif close_reason == "interrupted":
                return "Сессия была прервана внешним сигналом — ты не участвовал в закрытии."

        return None
