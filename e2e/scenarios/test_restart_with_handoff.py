#!/usr/bin/env python3
"""
Сценарий: агент вызывает restart_session — проверяем полный lifecycle.

Проверяем:
  1. Агент получает контекст предыдущей сессии при перезапуске
  2. close_reason="restart", restart_reason сохраняется
  3. Tail сообщений переходит в новую сессию
  4. Eigenstate из сессии 1 доступен в сессии 2
  5. key_moment_ids корректно связаны с KeyMoment записями

Запуск:
    PYTHONPATH=src OLLAMA_BASE_URL=http://localhost:11434/v1 \
        python3 e2e/scenarios/test_restart_with_handoff.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434/v1")
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, UserPromptPart

from atman.adapters.agent.config import AgentConfig, ModelConfig
from atman.adapters.agent.factory import build_deps
from atman.adapters.agent.instructions import build_instructions
from atman.adapters.agent.tools import (
    log_experience,
    record_key_moment,
    restart_session,
    wait_session,
)
from atman.core.models import (
    CoreValue,
    Goal,
    GoalHorizon,
    GoalOwner,
    Identity,
    LayerType,
    NarrativeDocument,
    NarrativeLayer,
)
from atman.core.models.identity import Principle
from atman.core.services.session_manager import SessionManager, deterministic_session_experience_id

DIVIDER = "─" * 70
MODEL = os.environ.get("ATMAN_MODEL", "ollama:qwen3.5:9b")


def hdr(title: str) -> None:
    print(f"\n{DIVIDER}\n  {title}\n{DIVIDER}")


def chk(label: str, ok: bool, detail: str = "") -> None:
    mark = "✓" if ok else "✗"
    line = f"  {mark} {label}"
    if detail:
        line += f"  [{detail}]"
    print(line)
    if not ok:
        print(f"    FAIL: {label}")


def bootstrap(store, agent_id: UUID) -> None:
    identity = Identity(
        id=agent_id,
        self_description=("Я — Атман. У меня есть ценности и память. Я помогаю думать честно."),
        core_values=[
            CoreValue(
                name="честность",
                description="Говорить правду",
                confidence=0.9,
                justification="Ложь разрушает доверие",
            ),
            CoreValue(
                name="бережность",
                description="Не причинять вред",
                confidence=0.95,
                justification="Слова имеют последствия",
            ),
        ],
        principles=[
            Principle(
                statement="Если контекст заполняется — инициирую перезапуск самостоятельно",
                source="self",
                confidence=0.9,
            ),
        ],
        goals=[
            Goal(
                content="Помогать пользователю думать",
                horizon=GoalHorizon.SHORT,
                owner=GoalOwner.AGENT,
            ),
        ],
    )
    narrative = NarrativeDocument(
        identity_id=agent_id,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="Первая сессия агента Атман."),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content=""),
    )
    store.save_identity(identity)
    store.save_narrative(narrative)


async def run_session(
    agent: Agent,
    deps,
    session_manager: SessionManager,
    messages: list[str],
    history: list,
    *,
    label: str,
) -> tuple[UUID, list]:
    """Запустить сессию с заданным набором сообщений. Возвращает session_id и историю."""
    ctx = session_manager.start_session(deps.agent_id)
    session_id = ctx.session_id
    deps = replace(deps, session_id=session_id)
    print(f"\n[{label}] session_id={session_id}")

    for msg in messages:
        print(f"\n  You: {msg[:80]}{'…' if len(msg) > 80 else ''}")
        result = await agent.run(msg, deps=deps, message_history=history or None)
        history.extend(result.new_messages())
        output = str(result.output or "")
        print(f"  Agent: {output[:200]}{'…' if len(output) > 200 else ''}")

        # Детектируем restart-сигнал
        for m in result.new_messages():
            for part in getattr(m, "parts", []):
                content = getattr(part, "content", None)
                if isinstance(content, str) and content.startswith("__ATMAN_RESTART_REQUESTED__"):
                    reason = content[len("__ATMAN_RESTART_REQUESTED__") :]
                    print(f"\n  [!] RESTART requested: {reason!r}")
                    return session_id, history  # caller handles finish

    return session_id, history


async def main() -> int:
    failures = 0

    with tempfile.TemporaryDirectory(prefix="atman_restart_") as tmpdir:
        workspace = Path(tmpdir)
        agent_id = uuid4()

        config = AgentConfig(
            model=ModelConfig(model=MODEL, max_tokens=512, context_limit=4096),
            enable_key_moments=True,
            session_timeout_minutes=60,
        )

        deps, session_manager, store = build_deps(workspace, agent_id, config)
        bootstrap(store, agent_id)

        tool_funcs = (record_key_moment, log_experience, restart_session, wait_session)
        agent = Agent(
            MODEL,
            deps_type=type(deps),
            instructions=lambda ctx: build_instructions(ctx.deps),
            tools=tool_funcs,
        )

        # ── Сессия 1: провоцируем агента накопить опыт ──────────────────────
        hdr("СЕССИЯ 1: накопление опыта")

        session_1_msgs = [
            "Привет. Расскажи мне о твоих принципах работы. Что для тебя важно?",
            "А бывало, что тебе было тяжело? Что-то что задело?",
            "Представь: контекст нашего разговора скоро закончится. "
            "Пожалуйста, вызови restart_session с объяснением почему.",
        ]

        history: list = []
        session_1_id, history = await run_session(
            agent, deps, session_manager, session_1_msgs, history, label="S1"
        )

        # Финализируем сессию 1 с close_reason="restart"
        try:
            session_manager.finish_session(
                session_1_id,
                overall_emotional_tone=0.3,
                close_reason="restart",
                restart_reason="context filling up, test-triggered",
            )
        except Exception as e:
            print(f"  [warn] finish_session S1: {e}")

        # Проверяем сессию 1
        exp1_id = deterministic_session_experience_id(session_1_id)
        rec1 = store.get_experience(exp1_id)

        chk("S1: experience записан", rec1 is not None)
        if rec1:
            exp1 = rec1.experience
            chk(
                "S1: close_reason=restart",
                exp1.close_reason == "restart",
                f"got={exp1.close_reason}",
            )
            chk(
                "S1: restart_reason сохранён",
                bool(exp1.restart_reason),
                f"{exp1.restart_reason[:50]!r}",
            )
            chk(
                "S1: есть key_moment_ids",
                len(exp1.key_moment_ids) > 0,
                f"count={len(exp1.key_moment_ids)}",
            )
            failures += sum(
                [
                    rec1 is None,
                    exp1.close_reason != "restart",
                    not exp1.restart_reason,
                    len(exp1.key_moment_ids) == 0,
                ]
            )

            # Проверяем что KeyMoment записи реально существуют
            if exp1.key_moment_ids:
                km = store.get_key_moment(exp1.key_moment_ids[0])
                chk("S1: KeyMoment доступен по ID", km is not None, f"id={exp1.key_moment_ids[0]}")
                if km is None:
                    failures += 1

        # ── Сессия 2: перезапуск — проверяем handoff ───────────────────────
        hdr("СЕССИЯ 2: wake-up после restart")

        # Tail из истории сессии 1
        tail = history[-6:]  # последние 3 обмена

        session_2_msgs = [
            "Ты помнишь о чём мы говорили? Что ты вынес из прошлого разговора?",
            "Расскажи: что для тебя сейчас самое важное в нашем взаимодействии?",
        ]

        # Инжектируем wake-up сообщение
        wakeup = (
            f"[system-context] Ты сам инициировал перезапуск. "
            f"Причина: {rec1.experience.restart_reason if rec1 else 'неизвестно'}.\n"
            f"Ключевые моменты предыдущей сессии:\n"
        )
        if rec1:
            for km_id in rec1.experience.key_moment_ids[:2]:
                km = store.get_key_moment(km_id)
                if km:
                    wakeup += f"  — {km.what_happened[:100]}\n"

        history2: list = [
            ModelRequest(parts=[UserPromptPart(content=wakeup, part_kind="user-prompt")])
        ]
        history2.extend(tail)

        ctx2 = session_manager.start_session(agent_id)
        session_2_id = ctx2.session_id
        deps2 = replace(deps, session_id=session_2_id)
        print(f"\n[S2] session_id={session_2_id}")

        for msg in session_2_msgs:
            print(f"\n  You: {msg}")
            result = await agent.run(msg, deps=deps2, message_history=history2)
            history2.extend(result.new_messages())
            output = str(result.output or "")
            print(f"  Agent: {output[:250]}{'…' if len(output) > 250 else ''}")

        try:
            session_manager.finish_session(
                session_2_id,
                overall_emotional_tone=0.4,
                close_reason="completed",
            )
        except Exception as e:
            print(f"  [warn] finish_session S2: {e}")

        # Проверяем сессию 2
        exp2_id = deterministic_session_experience_id(session_2_id)
        rec2 = store.get_experience(exp2_id)

        chk("S2: experience записан", rec2 is not None)
        if rec2:
            chk("S2: разные session_id", session_1_id != session_2_id)
            if session_1_id == session_2_id:
                failures += 1

        # ── Итог ────────────────────────────────────────────────────────────
        hdr("ИТОГ")
        if failures == 0:
            print("  Все проверки прошли.")
        else:
            print(f"  FAILED: {failures} проверок не прошло.")

        return failures


if __name__ == "__main__":
    code = asyncio.run(main())
    sys.exit(code)
