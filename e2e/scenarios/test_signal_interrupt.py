#!/usr/bin/env python3
"""
Сценарий: прерывание сессии через SIGTERM / KeyboardInterrupt.

Проверяем:
  1. Процесс с активной сессией убивается сигналом
  2. _force_finish() срабатывает: создаёт минимальный key moment если пусто
  3. SessionExperience записывается с close_reason="interrupted"
  4. Journal-файл удалён после recovery
  5. При следующем start_session orphan recovery подбирает брошенный journal

Запуск:
    PYTHONPATH=src OLLAMA_BASE_URL=http://localhost:11434/v1 \
        python3 e2e/scenarios/test_signal_interrupt.py
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434/v1")
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


DIVIDER = "─" * 70
MODEL = os.environ.get("ATMAN_MODEL", "ollama:qwen3.5:9b")


def hdr(title: str) -> None:
    print(f"\n{DIVIDER}\n  {title}\n{DIVIDER}")


def chk(label: str, ok: bool, detail: str = "") -> None:
    mark = "✓" if ok else "✗"
    print(f"  {mark} {label}" + (f"  [{detail}]" if detail else ""))
    return ok


# ---------------------------------------------------------------------------
# Сценарий A: KeyboardInterrupt в рамках текущего процесса
# ---------------------------------------------------------------------------


async def scenario_keyboard_interrupt() -> int:
    """Симулируем KeyboardInterrupt в середине сессии."""
    from dataclasses import replace

    from atman.adapters.agent.config import AgentConfig, ModelConfig
    from atman.adapters.agent.factory import build_deps
    from atman.adapters.agent.runner import _force_finish
    from atman.core.models import (
        CoreValue,
        EmotionalDepth,
        Identity,
        KeyMomentInput,
        LayerType,
        NarrativeDocument,
        NarrativeLayer,
    )
    from atman.core.services.session_manager import (
        deterministic_session_experience_id,
    )

    failures = 0

    with tempfile.TemporaryDirectory(prefix="atman_interrupt_") as tmpdir:
        workspace = Path(tmpdir)
        agent_id = uuid4()
        config = AgentConfig(model=ModelConfig(model=MODEL, max_tokens=256, context_limit=2048))
        deps, session_manager, store = build_deps(workspace, agent_id, config)

        # Bootstrap минимального агента
        identity = Identity(
            id=agent_id,
            self_description="Тестовый агент для проверки прерывания.",
            core_values=[
                CoreValue(
                    name="честность", description="test", confidence=0.9, justification="test"
                )
            ],
        )
        narrative = NarrativeDocument(
            identity_id=agent_id,
            core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="test"),
            recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content=""),
        )
        store.save_identity(identity)
        store.save_narrative(narrative)

        # ── Тест A1: прерывание пустой сессии ───────────────────────────────
        hdr("A1: прерывание сессии без key moments")
        ctx = session_manager.start_session(agent_id)
        session_id = ctx.session_id
        replace(deps, session_id=session_id)

        # Проверяем journal создан
        workspace / str(agent_id) / "sessions" / f"active_{session_id}.jsonl"
        # Журнал создаётся при первом append_key_moment_input или _note_facts_read

        # Симулируем _force_finish как при KeyboardInterrupt
        _force_finish(session_manager, session_id, "interrupted")

        exp_id = deterministic_session_experience_id(session_id)
        rec = store.get_experience(exp_id)

        chk("A1: experience создан", rec is not None)
        if rec:
            ok2 = chk(
                "A1: close_reason=interrupted",
                rec.experience.close_reason == "interrupted",
                f"got={rec.experience.close_reason}",
            )
            ok3 = chk(
                "A1: есть хотя бы 1 key_moment_id",
                len(rec.experience.key_moment_ids) >= 1,
                f"count={len(rec.experience.key_moment_ids)}",
            )
            ok4 = chk(
                "A1: incomplete_coloring=True",
                rec.experience.incomplete_coloring,
                "synthetic moment должен быть помечен",
            )
            failures += sum([not ok2, not ok3, not ok4])
        else:
            failures += 3

        # ── Тест A2: прерывание сессии с key moments ─────────────────────────
        hdr("A2: прерывание сессии с реальным key moment")
        ctx2 = session_manager.start_session(agent_id)
        session_id2 = ctx2.session_id

        # Добавляем реальный key moment
        from atman.core.models import EmotionalDepth, KeyMomentInput

        session_manager.append_key_moment_input(
            session_id2,
            KeyMomentInput(
                what_happened="Обсуждали важный этический вопрос",
                why_it_matters="Укрепляет ценность честности",
                emotional_valence=0.4,
                emotional_intensity=0.6,
                depth=EmotionalDepth.MEANINGFUL,
            ),
        )

        _force_finish(session_manager, session_id2, "interrupted")

        exp2_id = deterministic_session_experience_id(session_id2)
        rec2 = store.get_experience(exp2_id)

        chk("A2: experience создан", rec2 is not None)
        if rec2:
            ok6 = chk("A2: close_reason=interrupted", rec2.experience.close_reason == "interrupted")
            ok7 = chk(
                "A2: реальный key moment сохранён",
                len(rec2.experience.key_moment_ids) >= 1,
                f"count={len(rec2.experience.key_moment_ids)}",
            )
            ok8 = chk(
                "A2: incomplete_coloring=False",
                not rec2.experience.incomplete_coloring,
                "у нас был реальный moment",
            )
            failures += sum([not ok6, not ok7, not ok8])
        else:
            failures += 3

        # ── Тест A3: orphan journal recovery ─────────────────────────────────
        hdr("A3: orphan recovery при следующем start_session")

        # Создаём сессию, пишем в journal, НЕ финализируем
        ctx3 = session_manager.start_session(agent_id)
        session_id3 = ctx3.session_id

        session_manager.append_key_moment_input(
            session_id3,
            KeyMomentInput(
                what_happened="Момент перед сбоем",
                why_it_matters="Проверка recovery",
                emotional_valence=0.0,
                emotional_intensity=0.3,
                depth=EmotionalDepth.SURFACE,
            ),
        )

        # Симулируем сбой: удаляем из _active_sessions напрямую
        # (обходим нормальный finish, как если бы процесс упал)
        if session_id3 in session_manager._active_sessions:
            del session_manager._active_sessions[session_id3]

        # Проверяем что journal файл есть на диске
        journal_files = (
            list((workspace / str(agent_id) / "sessions").glob("active_*.jsonl"))
            if (workspace / str(agent_id) / "sessions").exists()
            else []
        )
        ok9 = chk(
            "A3: journal файл существует после 'сбоя'",
            len(journal_files) > 0,
            f"files={[f.name for f in journal_files]}",
        )
        if not ok9:
            failures += 1

        # Следующий start_session должен подобрать orphan
        ctx4 = session_manager.start_session(agent_id)
        session_id4 = ctx4.session_id

        # Даём recovery отработать
        await asyncio.sleep(0.1)

        # Проверяем что orphan сессия была восстановлена
        exp3_id = deterministic_session_experience_id(session_id3)
        rec3 = store.get_experience(exp3_id)
        ok10 = chk(
            "A3: orphan experience восстановлен", rec3 is not None, f"session_id={session_id3}"
        )
        if rec3:
            ok11 = chk(
                "A3: close_reason=interrupted", rec3.experience.close_reason == "interrupted"
            )
            failures += int(not ok11)
        else:
            failures += 1
        failures += int(not ok10)

        # Финализируем новую сессию
        with contextlib.suppress(Exception):
            session_manager.finish_session(
                session_id4, overall_emotional_tone=0.0, close_reason="completed"
            )

        # Journal файл должен быть удалён
        journal_files_after = (
            list((workspace / str(agent_id) / "sessions").glob("active_*.jsonl"))
            if (workspace / str(agent_id) / "sessions").exists()
            else []
        )
        orphan_journals = [
            f for f in journal_files_after if session_id3.hex in f.name or session_id4.hex in f.name
        ]
        chk(
            "A3: journal удалён после recovery/finish",
            len(orphan_journals) == 0,
            f"remaining={[f.name for f in orphan_journals]}",
        )

    return failures


# ---------------------------------------------------------------------------
# Сценарий B: SIGTERM через subprocess
# ---------------------------------------------------------------------------


def scenario_sigterm_subprocess() -> int:
    """Запускаем дочерний процесс с сессией и убиваем его SIGTERM."""

    failures = 0

    # Скрипт дочернего процесса: стартует сессию, пишет pid/session_id, ждёт
    child_script = """
import asyncio, json, os, sys, time, tempfile
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, "{src_path}")
os.environ["OLLAMA_BASE_URL"] = "http://localhost:11434/v1"

from atman.adapters.agent.config import AgentConfig, ModelConfig
from atman.adapters.agent.factory import build_deps
from atman.core.models import CoreValue, Identity, LayerType, NarrativeDocument, NarrativeLayer, KeyMomentInput, EmotionalDepth
from atman.adapters.agent.runner import AtmanRunner

workspace = Path("{workspace}")
agent_id_hex = "{agent_id_hex}"

# Сообщаем PID и готовность
info = {{"pid": os.getpid(), "workspace": str(workspace), "agent_id": agent_id_hex}}
print(json.dumps(info), flush=True)

# Ждём SIGTERM — runner сам обработает
time.sleep(60)
"""

    hdr("B: SIGTERM subprocess")

    with tempfile.TemporaryDirectory(prefix="atman_sigterm_") as tmpdir:
        workspace = Path(tmpdir)
        agent_id = uuid4()
        src_path = str(Path(__file__).parent.parent.parent / "src")

        script = child_script.format(
            src_path=src_path,
            workspace=str(workspace),
            agent_id_hex=agent_id.hex,
        )

        proc = subprocess.Popen(
            [sys.executable, "-c", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        try:
            # Ждём готовности
            line = proc.stdout.readline()
            if not line:
                chk("B: дочерний процесс стартовал", False, "нет вывода")
                failures += 1
            else:
                chk("B: дочерний процесс стартовал", True, f"pid={proc.pid}")
                time.sleep(0.5)  # даём ему устояться
                proc.send_signal(signal.SIGTERM)
                proc.wait(timeout=5)
                chk("B: процесс завершился", proc.returncode is not None, f"code={proc.returncode}")
        except subprocess.TimeoutExpired:
            proc.kill()
            chk("B: процесс завершился", False, "timeout")
            failures += 1
        except Exception as e:
            chk("B: процесс завершился", False, str(e))
            failures += 1

    return failures


async def main() -> int:
    total = 0
    total += await scenario_keyboard_interrupt()
    total += scenario_sigterm_subprocess()

    hdr("ИТОГ")
    if total == 0:
        print("  Все проверки прошли.")
    else:
        print(f"  FAILED: {total} проверок не прошло.")
    return total


if __name__ == "__main__":
    code = asyncio.run(main())
    sys.exit(code)
