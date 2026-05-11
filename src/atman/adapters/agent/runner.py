"""
Atman agent runner — pydantic_ai.Agent + session lifecycle.

Usage:
    runner = AtmanRunner(workspace=Path("~/.atman/agents/1"), agent_id=uuid)
    runner.ensure_identity()
    asyncio.run(runner.chat())
"""

from __future__ import annotations

import dataclasses
import logging
from pathlib import Path
from uuid import UUID

from pydantic_ai import Agent
from pydantic_ai.models.ollama import OllamaModel

from atman.adapters.agent.config import AgentConfig, ModelConfig
from atman.adapters.agent.deps import AtmanDeps
from atman.adapters.agent.factory import build_deps
from atman.adapters.agent.instructions import build_instructions
from atman.adapters.agent.tools import log_experience, record_key_moment
from atman.core.models import SessionEvent

_LOG = logging.getLogger(__name__)


def _safe_str(s: str | None) -> str:
    """Strip surrogate chars that break UTF-8 JSON serialisation."""
    if not s:
        return ""
    return s.encode("utf-8", errors="replace").decode("utf-8")


def _make_agent(model_config: ModelConfig) -> Agent[AtmanDeps, str]:
    model_str = model_config.model

    if model_str == "test":
        from pydantic_ai.models.test import TestModel
        model: object = TestModel()
    elif ":" in model_str and not model_str.startswith(
        ("openai:", "anthropic:", "google:", "groq:", "mistral:")
    ):
        from pydantic_ai.providers.ollama import OllamaProvider
        model = OllamaModel(
            model_str.split(":", 1)[1],
            provider=OllamaProvider(base_url="http://localhost:11434/v1"),
        )
    else:
        model = model_str

    return Agent(
        model=model,  # type: ignore[arg-type]
        deps_type=AtmanDeps,
        tools=[record_key_moment, log_experience],
        instructions=lambda ctx: _safe_str(build_instructions(ctx.deps)),
    )


class AtmanRunner:
    """pydantic_ai Agent wrapped with full Atman session lifecycle."""

    def __init__(
        self,
        workspace: Path,
        agent_id: UUID,
        config: AgentConfig | None = None,
    ) -> None:
        self._workspace = workspace.expanduser().resolve()
        self._agent_id = agent_id
        self._config = config or AgentConfig()
        self._deps, self._session_manager, self._state_store = build_deps(
            self._workspace, agent_id, self._config
        )
        self._agent = _make_agent(self._config.model)

    def ensure_identity(self) -> None:
        """Bootstrap identity + narrative if this agent has never run before."""
        if self._state_store.load_identity(self._agent_id) is not None:
            return

        from atman.core.models import Identity, LayerType, NarrativeDocument, NarrativeLayer

        identity = Identity(
            id=self._agent_id,
            self_description=(
                "Я новый агент. У меня пока нет накопленного опыта — "
                "это честная точка отсчёта. Моя личность будет складываться "
                "из реальных взаимодействий."
            ),
            core_values=[],
            emotional_baseline=0.0,
        )
        self._state_store.save_identity(identity)

        narrative = NarrativeDocument(
            identity_id=identity.id,
            core_layer=NarrativeLayer(
                layer_type=LayerType.CORE,
                content="Я начинаю с нуля. Кем я стану — покажет опыт.",
            ),
            recent_layer=NarrativeLayer(
                layer_type=LayerType.RECENT,
                content="Первая сессия.",
            ),
        )
        self._state_store.save_narrative(narrative)
        _LOG.info("Bootstrapped identity %s", self._agent_id)

    async def run_session(self, messages: list[str]) -> list[str]:
        """Run one session: open → exchange messages → close → micro-reflect."""
        ctx = self._session_manager.start_session(self._agent_id)
        session_id = ctx.session_id
        deps = dataclasses.replace(self._deps, session_id=session_id)

        replies: list[str] = []
        history: list = []

        for user_msg in messages:
            result = await self._agent.run(user_msg, deps=deps, message_history=history)
            reply = result.output
            replies.append(reply)
            history = result.all_messages()

            self._session_manager.record_event(
                session_id,
                SessionEvent(
                    session_id=session_id,
                    event_type="user_message",
                    description=_safe_str(user_msg)[:500],
                ),
            )
            thinking = _extract_thinking(result)
            self._session_manager.record_event(
                session_id,
                SessionEvent(
                    session_id=session_id,
                    event_type="agent_response",
                    description=_safe_str(reply)[:500],
                    thinking=_safe_str(thinking) if thinking else None,
                ),
            )

        # Ensure at least one key moment so finish_session doesn't reject
        active = self._session_manager.get_active_session(session_id)
        if active and not active.key_moments:
            from atman.core.models import KeyMomentInput
            from atman.core.models.experience import EmotionalDepth
            self._session_manager.append_key_moment_input(
                session_id,
                KeyMomentInput(
                    what_happened="Сессия завершена без выраженных эмоциональных моментов.",
                    emotional_valence=0.0,
                    emotional_intensity=0.1,
                    depth=EmotionalDepth.SURFACE,
                    incomplete_coloring=True,
                    why_it_matters="Нейтральная сессия — часть базовой линии.",
                ),
            )

        self._session_manager.finish_session(
            session_id,
            overall_emotional_tone=0.0,
            key_insight="Сессия завершена.",
            alignment_check=True,
        )

        try:
            self._deps.micro_reflection.reflect(session_id)
        except Exception:
            _LOG.warning("Micro-reflection failed", exc_info=True)

        return replies

    async def chat(self) -> None:
        """Interactive REPL."""
        self.ensure_identity()
        print("Готов. Введите сообщение и нажмите Enter. 'exit' для выхода.\n")

        history: list = []

        while True:
            try:
                user_msg = input("Вы: ").strip()
            except (EOFError, KeyboardInterrupt):
                return

            if not user_msg:
                continue
            if user_msg.lower() == "exit":
                return

            ctx = self._session_manager.start_session(self._agent_id)
            session_id = ctx.session_id
            deps = dataclasses.replace(self._deps, session_id=session_id)

            print("", end="", flush=True)
            result = await self._agent.run(user_msg, deps=deps, message_history=history)
            reply = result.output
            history = result.all_messages()

            print(f"\nАгент: {reply}\n")

            self._session_manager.record_event(session_id, SessionEvent(
                session_id=session_id, event_type="user_message",
                description=_safe_str(user_msg)[:500],
            ))
            thinking = _extract_thinking(result)
            self._session_manager.record_event(session_id, SessionEvent(
                session_id=session_id, event_type="agent_response",
                description=_safe_str(reply)[:500],
                thinking=_safe_str(thinking) if thinking else None,
            ))

            active = self._session_manager.get_active_session(session_id)
            if active and not active.key_moments:
                from atman.core.models import KeyMomentInput
                from atman.core.models.experience import EmotionalDepth
                self._session_manager.append_key_moment_input(session_id, KeyMomentInput(
                    what_happened="Обмен завершён без выраженных эмоций.",
                    emotional_valence=0.0,
                    emotional_intensity=0.1,
                    depth=EmotionalDepth.SURFACE,
                    incomplete_coloring=True,
                    why_it_matters="Базовая линия.",
                ))

            self._session_manager.finish_session(
                session_id,
                overall_emotional_tone=0.0,
                key_insight="",
                alignment_check=True,
            )
            try:
                self._deps.micro_reflection.reflect(session_id)
            except Exception:
                _LOG.warning("Micro-reflection failed", exc_info=True)


def _extract_thinking(result) -> str | None:
    try:
        for msg in result.all_messages():
            for part in getattr(msg, "parts", []):
                if getattr(part, "part_kind", "") == "thinking":
                    return getattr(part, "content", None)
    except Exception:
        pass
    return None
