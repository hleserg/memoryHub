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

from atman.adapters.agent.config import AgentConfig
from atman.adapters.agent.deps import AtmanDeps
from atman.core.exceptions import SessionAlreadyFinishedError, SessionNotFoundError
from atman.core.models import EmotionalDepth, KeyMomentInput

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


def _check_restart_signal(messages: list) -> tuple[bool, str]:
    """Return (requested, reason) from agent messages after agent.run()."""
    for msg in messages:
        for part in getattr(msg, "parts", []):
            content = getattr(part, "content", None)
            if isinstance(content, str) and content.startswith("__ATMAN_RESTART_REQUESTED__"):
                return True, content[len("__ATMAN_RESTART_REQUESTED__"):]
    return False, ""


def _check_wait_signal(messages: list) -> int:
    """Return wait minutes from agent messages, or 0 if not requested."""
    for msg in messages:
        for part in getattr(msg, "parts", []):
            content = getattr(part, "content", None)
            if isinstance(content, str) and content.startswith("__ATMAN_WAIT_REQUESTED__"):
                try:
                    return int(content[len("__ATMAN_WAIT_REQUESTED__"):])
                except ValueError:
                    return 0
    return 0


def _build_context_warning(remaining: int, urgency: str = "") -> str:
    if urgency == "urgent":
        return f"⚠️ Осталось ~{remaining} токенов. Нужно завершать."
    if urgency == "alert":
        return f"⚠️ Осталось ~{remaining} токенов."
    return (
        f"[Системное уведомление]\n"
        f"Контекст сессии заполняется — осталось около {remaining} токенов.\n"
        "Сообщи пользователю, что разговор скоро нужно продолжить в новой сессии.\n"
        "Если есть что-то важное, что ещё не зафиксировано — сделай это сейчас "
        "через record_key_moment, иначе это не перейдёт в следующую сессию.\n"
        "Всё что уже записано — вернётся автоматически. Когда будешь готов — "
        "вызови restart_session. Новая сессия откроется с твоей памятью и хвостом этого разговора."
    )


def _build_free_time_menu(enable_free_time: bool) -> str:
    cmds = "reflect() | review_facts() | wait(minutes) | sleep() | save_to_memory(content)"
    if enable_free_time:
        cmds += " | free_time()"
    return (
        "[Системное уведомление] Похоже, пользователь отошёл. "
        "Ты предоставлен самому себе.\n"
        f"Вызови одну из команд: {cmds}"
    )


def _build_restart_package(
    experience_record,
    tail_messages: list,
    unexamined_count: int,
    restart_reason: str,
) -> str:
    exp = experience_record.experience if experience_record else None
    lines = ["[system-handoff] Сессия перезапущена."]
    if restart_reason:
        lines.append(f"\nТы сам инициировал перезапуск. Причина: {restart_reason}")
    if exp:
        lines.append(f"\nЭмоциональный тон прошлой сессии: {exp.fact_refs and 'есть факты' or 'нет данных'}")
        lines.append(f"Ключевых моментов: {len(exp.key_moments)}")
    if unexamined_count:
        lines.append(f"Факты без осознанного отношения: {unexamined_count} шт.")
    if tail_messages:
        lines.append("\n--- Хвост разговора ---")
        for msg in tail_messages:
            for part in getattr(msg, "parts", []):
                content = getattr(part, "content", None)
                if isinstance(content, str) and content.strip():
                    lines.append(content[:300])
    return "\n".join(lines)


def _build_prev_session_context(experience_record) -> str | None:
    """Build first-message context from previous session's close_reason."""
    if experience_record is None:
        return None
    exp = experience_record.experience
    reason = exp.close_reason
    if reason is None:
        return None
    if reason == "timeout_sleep":
        recap = f" Пересказ: {exp.agent_recap}" if exp.agent_recap else ""
        return f"[Контекст] Ты задремал — пользователь отошёл, ты решил поспать.{recap}"
    if reason == "restart":
        r = f" Причина: {exp.restart_reason}" if exp.restart_reason else ""
        return f"[Контекст] Ты сам инициировал перезапуск.{r}"
    if reason == "forced":
        return "[Контекст] Контекст переполнился принудительно — ты не успел завершить сессию осознанно."
    if reason == "interrupted":
        return "[Контекст] Сессия была прервана внешним сигналом — ты не участвовал в закрытии."
    return None


class AtmanRunner:
    """
    Pydantic-AI based REPL runner wired to FileStateStore workspace and SessionManager.

    Used by ``src/run_agent.py`` to run an interactive session for a persisted agent.
    """

    def __init__(self, workspace: Path, agent_id: UUID, config: AgentConfig) -> None:
        self._workspace = workspace
        self._agent_id = agent_id
        self._config = config

    def _make_agent(self, tool_funcs: tuple) -> Agent:
        from atman.adapters.agent.instructions import build_instructions

        return Agent(
            self._config.model.model,
            deps_type=AtmanDeps,
            instructions=lambda ctx: build_instructions(ctx.deps),
            tools=tool_funcs,
            model_settings={"temperature": self._config.model.temperature}
            if hasattr(Agent, "model_settings")
            else {},
        )

    async def _do_restart(
        self,
        session_manager,
        session_id: UUID,
        deps: AtmanDeps,
        history: list,
        restart_reason: str,
    ) -> tuple[UUID, AtmanDeps]:
        """Finish current session, start new one, rebuild history with restart package."""
        # Ensure at least one key moment
        session_result = session_manager.get_active_session(session_id)
        if session_result is not None and not session_result.key_moments:
            session_manager.append_key_moment_input(
                session_id,
                KeyMomentInput(
                    what_happened="Сессия завершена по запросу перезапуска.",
                    why_it_matters="Continuity preserved via restart.",
                    emotional_valence=0.0,
                    emotional_intensity=0.1,
                    depth=EmotionalDepth.SURFACE,
                    incomplete_coloring=True,
                ),
            )

        try:
            session_manager.finish_session(
                session_id,
                overall_emotional_tone=0.0,
                close_reason="restart",
                restart_reason=restart_reason,
            )
        except (SessionAlreadyFinishedError, SessionNotFoundError):
            pass

        from atman.adapters.storage.file_state_store import FileStateStore

        store = FileStateStore(workspace=self._workspace)
        exp_id = __import__(
            "atman.core.services.session_manager", fromlist=["deterministic_session_experience_id"]
        ).deterministic_session_experience_id(session_id)
        exp_record = store.get_experience(exp_id)

        tail_n = self._config.context_tail_messages * 2
        tail = list(history[-tail_n:]) if history else []

        unexamined_count = len(exp_record.experience.unexamined_fact_refs) if exp_record else 0
        package = _build_restart_package(exp_record, tail, unexamined_count, restart_reason)

        # New session
        new_ctx = session_manager.start_session(self._agent_id)
        new_session_id = new_ctx.session_id
        new_deps = replace(deps, session_id=new_session_id)

        # Rebuild history: restart package first, then tail
        history.clear()
        from pydantic_ai.messages import ModelRequest, UserPromptPart

        history.append(
            ModelRequest(parts=[UserPromptPart(content=package, part_kind="user-prompt")])
        )
        history.extend(tail)

        return new_session_id, new_deps

    async def _run_free_time_menu(
        self,
        agent: Agent,
        deps: AtmanDeps,
        history: list,
        session_manager,
        session_id: UUID,
    ) -> tuple[bool, str | None]:
        """
        Run one free-time menu iteration.

        Returns (should_sleep, agent_recap_if_sleep).
        """
        from atman.term import print_info, print_warn

        menu_text = _build_free_time_menu(self._config.enable_free_time)
        if self._config.show_agent_monologue:
            print_info(f"\n{menu_text}\n")

        try:
            result = await agent.run(menu_text, deps=deps, message_history=history)
        except Exception as exc:
            _LOG.warning("Free-time agent run failed: %s", exc)
            return False, None

        output = str(result.output or "")

        # Check for sleep signal (either tool call or text "sleep()")
        if "sleep" in output.lower() or "__ATMAN_SLEEP__" in output:
            return True, output if output.strip() else None

        # Check wait signal
        wait_mins = _check_wait_signal(result.all_messages())
        if wait_mins:
            print_info(f"[Свободное время] Агент решил подождать ещё {wait_mins} мин.")
            return False, None

        if self._config.show_agent_monologue and output:
            print_info(f"[Агент] {output}")

        return False, None

    async def chat(self) -> None:
        """Run an interactive chat loop with token monitoring, timeout, and restart support."""
        from atman.adapters.agent.factory import build_deps
        from atman.adapters.agent.tools import (
            log_experience,
            record_key_moment,
            restart_session,
            wait_session,
        )
        from atman.term import print_err, print_info, print_plain, print_warn

        deps, session_manager, store = build_deps(self._workspace, self._agent_id, self._config)
        session_id: UUID | None = None
        interrupted = False
        exit_code = 0

        def _sigterm_handler(signum: int, frame: object) -> None:
            nonlocal interrupted
            _ = (signum, frame)
            _LOG.info("SIGTERM received")
            interrupted = True

        original_sigterm = signal.signal(signal.SIGTERM, _sigterm_handler)

        try:
            # Inject previous session context if available
            prev_context_msg: str | None = None
            try:
                from atman.core.services.session_manager import deterministic_session_experience_id

                recent = store.list_recent_experiences(limit=1)
                if recent:
                    prev_context_msg = _build_prev_session_context(recent[0])
            except Exception:
                pass

            session_ctx = session_manager.start_session(self._agent_id)
            session_id = session_ctx.session_id
            deps = replace(deps, session_id=session_id)

            tool_funcs: tuple
            if self._config.enable_key_moments:
                tool_funcs = (record_key_moment, log_experience, restart_session, wait_session)
            else:
                tool_funcs = (log_experience, restart_session, wait_session)

            agent = self._make_agent(tool_funcs)
            history: list = []
            context_thresholds_hit: set[int] = set()
            limit = self._config.model.context_limit

            print_info("Session started. Empty line or Ctrl-D to exit.\n")

            if prev_context_msg:
                print_info(f"{prev_context_msg}\n")

            while True:
                if interrupted:
                    break

                timeout_sec = self._config.session_timeout_minutes * 60
                try:
                    user_text = await asyncio.wait_for(
                        asyncio.to_thread(input, "You: "),
                        timeout=timeout_sec,
                    )
                except asyncio.TimeoutError:
                    # User went away — free time menu
                    print_info("\n[Пользователь отошёл. Переходим в режим свободного времени.]")
                    sleep_requested, agent_recap = await self._run_free_time_menu(
                        agent, deps, history, session_manager, session_id
                    )
                    if sleep_requested:
                        # Soft close
                        try:
                            session_manager.finish_session(
                                session_id,
                                overall_emotional_tone=0.0,
                                close_reason="timeout_sleep",
                                agent_recap=agent_recap,
                            )
                        except ValueError:
                            _force_finish(session_manager, session_id, "timeout_sleep")
                        except (SessionAlreadyFinishedError, SessionNotFoundError):
                            pass
                        session_id = None
                        break
                    continue
                except EOFError:
                    break

                if not user_text.strip():
                    break

                try:
                    result = await agent.run(
                        user_text,
                        deps=deps,
                        message_history=history if history else None,
                    )
                except Exception as exc:
                    print_err(f"Run failed: {exc!s}")
                    continue

                history.extend(result.all_messages())
                print_plain(str(result.output))
                print_plain("")

                # Token monitoring
                try:
                    usage = result.usage()
                    input_tokens = getattr(usage, "input_tokens", None) or 0
                    if limit and input_tokens:
                        ratio = input_tokens / limit
                        remaining = limit - input_tokens

                        if ratio >= 0.95 and 95 not in context_thresholds_hit:
                            context_thresholds_hit.add(95)
                            _LOG.warning("Context 95%% full (%d tokens), forcing restart", input_tokens)
                            session_id, deps = await self._do_restart(
                                session_manager, session_id, deps, history, "forced_95pct"
                            )
                            context_thresholds_hit = set()
                            continue

                        elif ratio >= 0.90 and 90 not in context_thresholds_hit:
                            context_thresholds_hit.add(90)
                            warning = _build_context_warning(remaining, urgency="urgent")
                            history.append(
                                __import__(
                                    "pydantic_ai.messages",
                                    fromlist=["ModelRequest", "UserPromptPart"],
                                ).ModelRequest(
                                    parts=[
                                        __import__(
                                            "pydantic_ai.messages",
                                            fromlist=["UserPromptPart"],
                                        ).UserPromptPart(content=warning, part_kind="user-prompt")
                                    ]
                                )
                            )

                        elif ratio >= 0.80 and 80 not in context_thresholds_hit:
                            context_thresholds_hit.add(80)
                            warning = _build_context_warning(remaining, urgency="alert")
                            from pydantic_ai.messages import ModelRequest, UserPromptPart

                            history.append(
                                ModelRequest(
                                    parts=[UserPromptPart(content=warning, part_kind="user-prompt")]
                                )
                            )

                        elif ratio >= 0.70 and 70 not in context_thresholds_hit:
                            context_thresholds_hit.add(70)
                            warning = _build_context_warning(remaining)
                            from pydantic_ai.messages import ModelRequest, UserPromptPart

                            history.append(
                                ModelRequest(
                                    parts=[UserPromptPart(content=warning, part_kind="user-prompt")]
                                )
                            )
                except Exception:
                    pass  # token monitoring must never break the chat loop

                # Restart signal check
                try:
                    restart_requested, restart_reason = _check_restart_signal(result.all_messages())
                    if restart_requested:
                        print_info("[Перезапуск сессии…]")
                        session_id, deps = await self._do_restart(
                            session_manager, session_id, deps, history, restart_reason
                        )
                        context_thresholds_hit = set()
                except Exception:
                    pass  # restart detection must never break the chat loop

        except KeyboardInterrupt:
            print_warn("\nInterrupted.")
            interrupted = True

        except SystemExit as exc:
            interrupted = True
            exit_code = exc.code if isinstance(exc.code, int) else 1

        finally:
            signal.signal(signal.SIGTERM, original_sigterm)

            if session_id is not None:
                close_r = "interrupted" if interrupted else None
                try:
                    session_manager.finish_session(
                        session_id,
                        overall_emotional_tone=0.0,
                        key_insight="",
                        alignment_check=True,
                        alignment_notes="",
                        close_reason=close_r,
                    )
                except ValueError as exc:
                    if "Cannot finish session without key moments" in str(exc):
                        _force_finish(session_manager, session_id, close_r or "completed")
                    else:
                        _LOG.exception("finish_session failed")
                except (SessionAlreadyFinishedError, SessionNotFoundError):
                    pass

            if exit_code:
                sys.exit(exit_code)
