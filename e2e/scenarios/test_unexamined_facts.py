#!/usr/bin/env python3
"""
Сценарий: unexamined_fact_refs + wakeup message при разных close_reason.

Проверяем:
  1. Факты прочитанные агентом но не вошедшие в key_moments → unexamined_fact_refs
  2. Факты вошедшие в key_moment.fact_refs → НЕ попадают в unexamined
  3. close_reason корректно сохраняется для каждого типа закрытия

Запуск:
    PYTHONPATH=src OLLAMA_BASE_URL=http://localhost:11434/v1 \
        python3 e2e/scenarios/test_unexamined_facts.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from uuid import UUID, uuid4

os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434/v1")
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from atman.adapters.agent.config import AgentConfig, ModelConfig
from atman.adapters.agent.factory import build_deps
from atman.core.models import (
    CoreValue,
    EmotionalDepth,
    Identity,
    KeyMomentInput,
    LayerType,
    NarrativeDocument,
    NarrativeLayer,
)
from atman.core.services.session_manager import deterministic_session_experience_id

DIVIDER = "─" * 70
MODEL = os.environ.get("ATMAN_MODEL", "ollama:qwen3.5:9b")


def hdr(title: str) -> None:
    print(f"\n{DIVIDER}\n  {title}\n{DIVIDER}")


def chk(label: str, ok: bool, detail: str = "") -> bool:
    mark = "✓" if ok else "✗"
    print(f"  {mark} {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def bootstrap(store, agent_id: UUID) -> None:
    identity = Identity(
        id=agent_id,
        self_description="Тестовый агент для unexamined facts.",
        core_values=[
            CoreValue(name="честность", description="test", confidence=0.9, justification="test")
        ],
    )
    narrative = NarrativeDocument(
        identity_id=agent_id,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="test"),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content=""),
    )
    store.save_identity(identity)
    store.save_narrative(narrative)


# ---------------------------------------------------------------------------
# Тест A: unexamined_fact_refs вычисляется корректно
# ---------------------------------------------------------------------------


def test_unexamined_facts_computation() -> int:
    failures = 0
    hdr("A: unexamined_fact_refs — прямое тестирование через SessionManager")

    with tempfile.TemporaryDirectory(prefix="atman_unex_") as tmpdir:
        workspace = Path(tmpdir)
        agent_id = uuid4()
        config = AgentConfig(model=ModelConfig(model=MODEL, context_limit=2048))
        _deps, session_manager, store = build_deps(workspace, agent_id, config)
        bootstrap(store, agent_id)

        ctx = session_manager.start_session(agent_id)
        session_id = ctx.session_id

        fact_a, fact_b, fact_c = uuid4(), uuid4(), uuid4()

        # Читаем три факта
        session_manager._note_facts_read(session_id, [fact_a, fact_b, fact_c])

        # Красим только fact_a через key moment
        session_manager.append_key_moment_input(
            session_id,
            KeyMomentInput(
                what_happened="Обработал факт A — он важен для понимания контекста",
                why_it_matters="Факт A меняет картину мира",
                emotional_valence=0.3,
                emotional_intensity=0.5,
                depth=EmotionalDepth.MEANINGFUL,
                fact_refs=[fact_a],
            ),
        )

        session_manager.finish_session(
            session_id,
            overall_emotional_tone=0.2,
            close_reason="completed",
        )

        exp_id = deterministic_session_experience_id(session_id)
        rec = store.get_experience(exp_id)

        chk("A: experience записан", rec is not None)
        if rec:
            exp = rec.experience
            unex = set(exp.unexamined_fact_refs)
            ok2 = chk(
                "A: fact_b в unexamined", fact_b in unex, f"unexamined={[str(u)[:8] for u in unex]}"
            )
            ok3 = chk("A: fact_c в unexamined", fact_c in unex)
            ok4 = chk("A: fact_a НЕ в unexamined (он окрашен)", fact_a not in unex)
            ok5 = chk(
                "A: fact_refs содержит все три",
                set(exp.fact_refs) == {fact_a, fact_b, fact_c},
                f"fact_refs={[str(f)[:8] for f in exp.fact_refs]}",
            )
            failures += sum([not ok2, not ok3, not ok4, not ok5])
        else:
            failures += 4

        # ── A2: нет фактов → unexamined пуст ─────────────────────────────────
        ctx2 = session_manager.start_session(agent_id)
        session_id2 = ctx2.session_id

        session_manager.append_key_moment_input(
            session_id2,
            KeyMomentInput(
                what_happened="Момент без фактов",
                why_it_matters="Просто опыт",
                emotional_valence=0.1,
                emotional_intensity=0.2,
                depth=EmotionalDepth.SURFACE,
            ),
        )
        session_manager.finish_session(
            session_id2, overall_emotional_tone=0.0, close_reason="completed"
        )

        exp2_id = deterministic_session_experience_id(session_id2)
        rec2 = store.get_experience(exp2_id)
        if rec2:
            ok6 = chk(
                "A2: без фактов → unexamined пуст",
                len(rec2.experience.unexamined_fact_refs) == 0,
                f"count={len(rec2.experience.unexamined_fact_refs)}",
            )
            if not ok6:
                failures += 1

    return failures


# ---------------------------------------------------------------------------
# Тест B: wake-up messages для каждого close_reason
# ---------------------------------------------------------------------------


def test_wakeup_messages() -> int:
    failures = 0
    hdr("B: Wake-up messages для каждого close_reason")

    with tempfile.TemporaryDirectory(prefix="atman_wakeup_") as tmpdir:
        workspace = Path(tmpdir)
        agent_id = uuid4()
        config = AgentConfig(model=ModelConfig(model=MODEL, context_limit=2048))
        _deps, session_manager, store = build_deps(workspace, agent_id, config)
        bootstrap(store, agent_id)

        close_reasons = ["timeout_sleep", "restart", "forced", "interrupted"]

        for reason in close_reasons:
            ctx = session_manager.start_session(agent_id)
            sid = ctx.session_id

            session_manager.append_key_moment_input(
                sid,
                KeyMomentInput(
                    what_happened=f"Тестовый момент для {reason}",
                    why_it_matters="wake-up test",
                    emotional_valence=0.0,
                    emotional_intensity=0.2,
                    depth=EmotionalDepth.SURFACE,
                ),
            )

            kwargs: dict = {"overall_emotional_tone": 0.0, "close_reason": reason}
            if reason == "restart":
                kwargs["restart_reason"] = "тест перезапуска"

            session_manager.finish_session(sid, **kwargs)

            exp_id = deterministic_session_experience_id(sid)
            rec = store.get_experience(exp_id)
            if rec is None:
                chk(f"B: {reason} — experience записан", False)
                failures += 1
                continue

            chk(
                f"B: {reason} — close_reason сохранён корректно",
                rec.experience.close_reason == reason,
                f"got={rec.experience.close_reason}",
            )
            if rec.experience.close_reason != reason:
                failures += 1

            if reason == "restart":
                ok = chk(
                    "B: restart_reason сохранён",
                    "тест" in (rec.experience.restart_reason or ""),
                    f"got={rec.experience.restart_reason!r}",
                )
                if not ok:
                    failures += 1

    return failures


async def main() -> int:
    total = 0
    total += test_unexamined_facts_computation()
    total += test_wakeup_messages()

    hdr("ИТОГ")
    if total == 0:
        print("  Все проверки прошли.")
    else:
        print(f"  FAILED: {total} проверок не прошло.")
    return total


if __name__ == "__main__":
    code = asyncio.run(main())
    sys.exit(code)
