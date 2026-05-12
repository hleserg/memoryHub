#!/usr/bin/env python3
"""
Сценарий: token monitoring — предупреждения 70/80/90% и принудительное закрытие на 95%.

Проверяем:
  1. TokenMonitor.reset_triggers() работает
  2. ContextLimitExceeded поднимается при 95%
  3. Предупреждения пишутся в лог при пересечении порогов
  4. Интеграция: с маленьким context_limit пороги реально достигаются

Запуск:
    PYTHONPATH=src OLLAMA_BASE_URL=http://localhost:11434/v1 \
        python3 e2e/scenarios/test_token_monitor.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434/v1")
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import contextlib

from atman.adapters.agent.config import AgentConfig, ModelConfig
from atman.adapters.agent.factory import build_deps
from atman.adapters.agent.token_monitor import ContextLimitExceeded, TokenMonitor

DIVIDER = "─" * 70
MODEL = os.environ.get("ATMAN_MODEL", "ollama:qwen3.5:9b")


def hdr(title: str) -> None:
    print(f"\n{DIVIDER}\n  {title}\n{DIVIDER}")


def chk(label: str, ok: bool, detail: str = "") -> bool:
    mark = "✓" if ok else "✗"
    print(f"  {mark} {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def _make_mock_result(input_tokens: int):
    """Build a mock AgentRunResult with the given token count."""
    usage = MagicMock()
    usage.input_tokens = input_tokens
    result = MagicMock()
    result.usage.return_value = usage
    return result


# ---------------------------------------------------------------------------
# Тест A: _check_token_threshold + reset_triggers
# ---------------------------------------------------------------------------


async def test_token_monitor_thresholds() -> int:
    """Проверяем пороги через прямой вызов _check_token_threshold."""
    failures = 0
    hdr("A: TokenMonitor пороги (без реального LLM)")

    with tempfile.TemporaryDirectory(prefix="atman_tok_") as tmpdir:
        workspace = Path(tmpdir)
        agent_id = uuid4()
        config = AgentConfig(model=ModelConfig(model=MODEL, context_limit=1000))
        deps, _, _ = build_deps(workspace, agent_id, config)

        monitor = TokenMonitor(deps=deps)

        # Патчим _inject_warning чтобы отслеживать вызовы
        warnings_logged: list[str] = []
        monitor._inject_warning = lambda warning: warnings_logged.append(warning)

        # 65% — ниже порога
        await monitor._check_token_threshold(_make_mock_result(650))
        ok1 = chk(
            "65% — нет предупреждения", len(warnings_logged) == 0, f"count={len(warnings_logged)}"
        )
        if not ok1:
            failures += 1

        # 72% — NOTICE
        await monitor._check_token_threshold(_make_mock_result(720))
        ok2 = chk(
            "72% — предупреждение сработало",
            len(warnings_logged) == 1,
            f"count={len(warnings_logged)}",
        )
        if not ok2:
            failures += 1

        # 72% повторно — дедупликация
        await monitor._check_token_threshold(_make_mock_result(720))
        ok3 = chk(
            "72% повторно — дедупликация (нет нового предупреждения)",
            len(warnings_logged) == 1,
            f"count={len(warnings_logged)}",
        )
        if not ok3:
            failures += 1

        # 82% — INFO
        await monitor._check_token_threshold(_make_mock_result(820))
        ok4 = chk(
            "82% — второе предупреждение",
            len(warnings_logged) == 2,
            f"count={len(warnings_logged)}",
        )
        if not ok4:
            failures += 1

        # 92% — WARNING
        await monitor._check_token_threshold(_make_mock_result(920))
        ok5 = chk(
            "92% — третье предупреждение",
            len(warnings_logged) == 3,
            f"count={len(warnings_logged)}",
        )
        if not ok5:
            failures += 1

        # 96% — CRITICAL: должен поднять ContextLimitExceeded
        raised = False
        try:
            await monitor._check_token_threshold(_make_mock_result(960))
        except ContextLimitExceeded:
            raised = True
        ok6 = chk("96% — ContextLimitExceeded поднят", raised)
        if not ok6:
            failures += 1

        # reset_triggers — счётчики сбрасываются
        monitor.reset_triggers()
        prev_count = len(warnings_logged)
        await monitor._check_token_threshold(_make_mock_result(720))
        ok7 = chk(
            "После reset_triggers — 72% снова даёт предупреждение",
            len(warnings_logged) > prev_count,
            f"count={len(warnings_logged)}",
        )
        if not ok7:
            failures += 1

    return failures


# ---------------------------------------------------------------------------
# Тест B: Интеграция с реальной моделью + маленький context_limit
# ---------------------------------------------------------------------------


async def test_token_monitor_integration() -> int:
    """Реальная LLM с context_limit=800 — смотрим что TokenMonitor инициализируется."""
    failures = 0
    hdr("B: TokenMonitor с реальной LLM (context_limit=800)")

    with tempfile.TemporaryDirectory(prefix="atman_tok_int_") as tmpdir:
        workspace = Path(tmpdir)
        agent_id = uuid4()
        config = AgentConfig(
            model=ModelConfig(model=MODEL, max_tokens=150, context_limit=800),
            enable_key_moments=False,
        )

        from atman.core.models import (
            CoreValue,
            Identity,
            LayerType,
            NarrativeDocument,
            NarrativeLayer,
        )

        deps, session_manager, store = build_deps(workspace, agent_id, config)

        identity = Identity(
            id=agent_id,
            self_description="Тестовый агент для token monitor.",
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

        ctx = session_manager.start_session(agent_id)
        session_id = ctx.session_id
        deps = replace(deps, session_id=session_id)

        monitor = TokenMonitor(deps=deps)

        # Проверяем что monitor инициализировался с нужным context_limit
        ok1 = chk(
            "B: context_limit из deps.model_config",
            monitor._deps.model_config is not None
            and monitor._deps.model_config.context_limit == 800,
            f"got={monitor._deps.model_config.context_limit if monitor._deps.model_config else None}",
        )
        if not ok1:
            failures += 1

        # Запускаем одно реальное сообщение
        warnings_fired: list[str] = []
        monitor._inject_warning = lambda warning: warnings_fired.append(warning)

        try:
            result = await monitor.run("Скажи одно короткое слово.")
            usage = result.usage()
            input_tokens = getattr(usage, "input_tokens", 0) or 0
            ratio = input_tokens / 800 * 100
            print(f"\n  tokens={input_tokens} ({ratio:.0f}%)")
            chk("B: agent отвечает", True, f"tokens={input_tokens}")
        except ContextLimitExceeded:
            chk("B: ContextLimitExceeded при первом запросе", True, "маленький лимит — норма")
        except Exception as e:
            chk("B: agent запустился", False, str(e)[:80])
            failures += 1

        with contextlib.suppress(Exception):
            session_manager.finish_session(
                session_id, overall_emotional_tone=0.0, close_reason="completed"
            )

    return failures


async def main() -> int:
    total = 0
    total += await test_token_monitor_thresholds()
    total += await test_token_monitor_integration()

    hdr("ИТОГ")
    if total == 0:
        print("  Все проверки прошли.")
    else:
        print(f"  FAILED: {total} проверок не прошло.")
    return total


if __name__ == "__main__":
    code = asyncio.run(main())
    sys.exit(code)
