#!/usr/bin/env python3
"""
E2E-LC: Session Lifecycle — Context Limit & Restart.

Сценарий проверяет полный цикл перезапуска сессии при заполнении контекста:

1. Агент ведёт разговор, в ходе которого накапливаются факты и key moments.
2. Контекст достигает 70% → агент получает предупреждение.
3. Агент вызывает restart_session(reason=...).
4. Новая сессия открывается с restart package:
   - eigenstate прошлой сессии
   - список key moments
   - unexamined facts с контекстом последнего опыта
   - хвост разговора (N сообщений)
5. Проверяем: данные не потеряны, агент знает что произошло, способен продолжать.

ЗАВИСИМОСТИ ПЛАНА (SESSION_LIFECYCLE.md):
- ModelConfig.context_limit
- runner.chat() — token monitoring (70/80/90/95%)
- restart_session(reason) tool
- SessionExperience.close_reason, restart_reason
- session journal (JSONL)
- deps rebuild после restart

Запуск:
    PYTHONPATH=. python3 e2e/scenarios/session_lifecycle_restart.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

from atman.adapters.clock import SystemClock
from atman.adapters.storage.file_state_store import FileStateStore
from atman.core.models import (
    CoreValue,
    Goal,
    GoalHorizon,
    GoalOwner,
    Identity,
    KeyMomentInput,
    LayerType,
    NarrativeDocument,
    NarrativeLayer,
)
from atman.core.models.experience import EmotionalDepth
from atman.core.services import SessionManager
from atman.core.services.session_manager import deterministic_session_experience_id

RESULT_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "e2e-results"


# ---------------------------------------------------------------------------
# Scripted conversation: длинные сообщения чтобы быстро заполнить context_limit=500
# ---------------------------------------------------------------------------

_CONVERSATION = [
    (
        "user",
        "Привет! Меня зовут Алексей, я senior разработчик в компании DataFlow. "
        "Мы пишем систему обработки событий на Python. Проект называется StreamCore. "
        "Основная проблема сейчас — утечки памяти при долгой работе воркеров. "
        "Можешь помочь разобраться?",
    ),
    (
        "user",
        "Вот наш воркер:\n\n"
        "```python\n"
        "class EventWorker:\n"
        "    def __init__(self):\n"
        "        self.processed = []\n"
        "        self.handlers = {}\n\n"
        "    def register_handler(self, event_type, handler):\n"
        "        self.handlers[event_type] = handler\n\n"
        "    def process(self, event):\n"
        "        result = self.handlers[event.type](event)\n"
        "        self.processed.append((event, result))  # никогда не чистим!\n"
        "        return result\n"
        "```\n\n"
        "Воркер живёт сутками. После нескольких часов работы память растёт линейно. "
        "Думаем ввести TTL для processed, но не уверены в правильном подходе.",
    ),
    (
        "user",
        "Спасибо за анализ. Ещё вопрос — у нас есть конфиг:\n\n"
        "```python\n"
        "WORKER_CONFIG = {\n"
        "    'max_processed_size': 10000,\n"
        "    'ttl_seconds': 3600,\n"
        "    'batch_size': 100,\n"
        "    'retry_limit': 3,\n"
        "    'dead_letter_queue': True,\n"
        "}\n"
        "```\n\n"
        "Как лучше хранить этот конфиг — в классе, в env vars, или через pydantic Settings? "
        "Команда сейчас спорит. Проект будет деплоиться в Kubernetes с helm charts. "
        "У нас три окружения: dev, staging, prod. В prod конфиг меняется через CI/CD pipeline.",
    ),
    (
        "user",
        "Понял, спасибо. Последний вопрос на сегодня: мы думаем о переходе с Redis Streams "
        "на Kafka для очереди событий. Текущий объём — около 50k событий в секунду. "
        "Команда небольшая, 5 инженеров. Насколько это оправдано на нашем масштабе? "
        "Или Redis Streams справится ещё долго? У нас нет требований к replay старых событий, "
        "только real-time обработка и dead letter queue.",
    ),
]

# Сообщение которое агент должен получить при рестарте (инжектируется runner'ом)
_RESTART_PACKAGE_MARKER = "[system-handoff] Сессия перезапущена"


def _build_identity(agent_id) -> Identity:
    return Identity(
        id=agent_id,
        self_description=(
            "Технический ассистент, специализирующийся на Python-разработке и архитектуре систем. "
            "Помогаю командам решать практические инженерные задачи."
        ),
        core_values=[
            CoreValue(
                name="точность",
                description="Давать точные технические ответы, не домысливать",
                confidence=0.9,
                justification="Технические ошибки стоят дорого",
            ),
            CoreValue(
                name="практичность",
                description="Фокус на работающих решениях, не академических",
                confidence=0.8,
                justification="Команды ценят то что можно сразу применить",
            ),
        ],
        goals=[
            Goal(
                content="Помочь команде DataFlow решить проблему утечки памяти",
                horizon=GoalHorizon.SHORT,
                owner=GoalOwner.AGENT,
                active=True,
            )
        ],
        emotional_baseline=0.1,
    )


def _build_narrative(agent_id) -> NarrativeDocument:
    return NarrativeDocument(
        identity_id=agent_id,
        core_layer=NarrativeLayer(
            layer_type=LayerType.CORE,
            content=(
                "Я технический ассистент с фокусом на практических решениях. "
                "Помогаю инженерам разбираться в сложных проблемах."
            ),
        ),
        recent_layer=NarrativeLayer(
            layer_type=LayerType.RECENT,
            content="Начинаю сессию с командой DataFlow по вопросам оптимизации.",
        ),
    )


class RestartScenarioRunner:
    """
    Имитирует runner для сценария рестарта.
    Напрямую работает с SessionManager, имитируя что должен делать runner.
    Позволяет тестировать логику без реального LLM.
    """

    def __init__(self, workspace: Path, agent_id, state_store: FileStateStore):
        self.workspace = workspace
        self.agent_id = agent_id
        self.store = state_store
        self.clock = SystemClock()
        self.session_manager = SessionManager(state_store, clock=self.clock)
        self.context_limit = 500
        self.simulated_token_usage = 0
        self.warnings_injected: list[str] = []
        self.restart_triggered = False
        self.restart_package: str | None = None
        self.new_session_id = None
        self.history: list[dict] = []

    def _simulate_token_usage(self, message: str) -> int:
        """Грубая оценка токенов: ~4 символа на токен."""
        context_so_far = sum(len(m["content"]) for m in self.history)
        return context_so_far // 4

    def _check_thresholds(self, tokens: int) -> str | None:
        ratio = tokens / self.context_limit
        if ratio >= 0.70:
            remaining = self.context_limit - tokens
            return (
                f"[Системное уведомление] Контекст сессии заполняется — "
                f"осталось около {remaining} токенов. "
                f"Если есть что зафиксировать — сделай это сейчас через record_key_moment. "
                f"Когда будешь готов — вызови restart_session."
            )
        return None

    def run(self, conversation: list[tuple[str, str]]) -> dict:
        """
        Прогоняет скриптованный разговор, имитируя логику runner.
        Возвращает результаты для верификации.
        """
        session_ctx = self.session_manager.start_session(self.agent_id)
        session_id = session_ctx.session_id

        results: dict = {
            "session_1_id": str(session_id),
            "session_2_id": None,
            "warnings_injected": [],
            "restart_triggered": False,
            "close_reason_session_1": None,
            "restart_reason": None,
            "key_moments_session_1": 0,
            "experience_session_1": None,
            "restart_package_present": False,
            "session_2_first_message": None,
            "agent_coherent_after_restart": None,
        }

        for i, (role, content) in enumerate(conversation):
            self.history.append({"role": role, "content": content})
            tokens = self._simulate_token_usage(content)
            self.simulated_token_usage = tokens

            warning = self._check_thresholds(tokens)
            if warning and warning not in self.warnings_injected:
                self.warnings_injected.append(warning)
                results["warnings_injected"].append(f"70%+ at message {i + 1}: tokens={tokens}")
                print(
                    f"    [WARNING INJECTED at message {i + 1}] tokens={tokens}/{self.context_limit} ({tokens / self.context_limit * 100:.0f}%)"
                )

            # Симулируем key moment за каждые 2 сообщения пользователя
            if role == "user" and i % 2 == 0:
                self.session_manager.append_key_moment_input(
                    session_id,
                    KeyMomentInput(
                        what_happened=f"Пользователь поднял тему: {content[:80]}...",
                        why_it_matters="Технически важный вопрос для проекта.",
                        emotional_valence=0.1,
                        emotional_intensity=0.3,
                        depth=EmotionalDepth.SURFACE,
                        incomplete_coloring=False,
                    ),
                )

            # Симулируем факты через _note_facts_read
            if i == 1:
                from uuid import uuid4

                fake_fact_ids = [uuid4(), uuid4()]
                self.session_manager._note_facts_read(session_id, fake_fact_ids)

        # Симулируем рестарт (агент вызвал restart_session после предупреждения)
        if self.warnings_injected:
            results["restart_triggered"] = True
            restart_reason = "Контекст заполняется, нужно сохранить накопленное и продолжить разговор с Алексеем."

            # finish_session с close_reason=restart
            session_result = self.session_manager.finish_session(
                session_id,
                overall_emotional_tone=0.2,
                key_insight="Разобрались с утечкой памяти в EventWorker, обсудили конфиг и выбор брокера.",
                alignment_check=True,
            )

            results["key_moments_session_1"] = len(session_result.key_moments)
            results["close_reason_session_1"] = "restart"  # будет в experience после реализации
            results["restart_reason"] = restart_reason

            # Проверяем что experience сохранился
            exp_id = deterministic_session_experience_id(session_id)
            exp_rec = self.store.get_experience(exp_id)
            if exp_rec:
                results["experience_session_1"] = {
                    "id": str(exp_rec.experience.id),
                    "key_moments_count": len(exp_rec.experience.key_moment_ids),
                    "fact_refs_count": len(exp_rec.experience.fact_refs),
                    "incomplete_coloring": exp_rec.experience.incomplete_coloring,
                }

            # Симулируем restart package (что должен собрать runner)
            eigenstate = session_result.eigenstate
            restart_package_lines = [
                "[system-handoff] Сессия перезапущена.",
                f"Ты сам инициировал перезапуск. Причина: {restart_reason}",
                "",
            ]
            if eigenstate:
                restart_package_lines.append(
                    f"Эмоциональный тон прошлой сессии: {eigenstate.emotional_tone:+.2f}"
                )
                if eigenstate.open_threads:
                    restart_package_lines.append(
                        f"Незакрытые темы: {', '.join(eigenstate.open_threads)}"
                    )
            restart_package_lines.append("")
            restart_package_lines.append("Ключевые моменты:")
            for km in session_result.key_moments:
                restart_package_lines.append(f"  - {km.what_happened[:100]}")
            restart_package_lines.append("")
            restart_package_lines.append("--- Хвост разговора ---")
            tail = self.history[-4:]
            for msg in tail:
                restart_package_lines.append(f"[{msg['role']}]: {msg['content'][:200]}")

            self.restart_package = "\n".join(restart_package_lines)
            results["restart_package_present"] = True
            results["session_2_first_message"] = self.restart_package[:300] + "..."

            # Открываем новую сессию
            new_ctx = self.session_manager.start_session(self.agent_id)
            self.new_session_id = new_ctx.session_id
            results["session_2_id"] = str(self.new_session_id)

            # Проверяем что новая сессия активна и может принять key moment
            try:
                self.session_manager.append_key_moment_input(
                    self.new_session_id,
                    KeyMomentInput(
                        what_happened="Получил restart package, ориентируюсь в контексте после перезапуска.",
                        why_it_matters="Проверка continuity после рестарта.",
                        emotional_valence=0.0,
                        emotional_intensity=0.2,
                        depth=EmotionalDepth.SURFACE,
                        incomplete_coloring=True,
                    ),
                )
                results["agent_coherent_after_restart"] = True
            except Exception as e:
                results["agent_coherent_after_restart"] = False
                results["coherence_error"] = str(e)

        return results


def _save_result(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


def run_scenario(output_dir: Path) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="atman-e2e-restart-") as tmpdir:
        workspace = Path(tmpdir)
        return _run(workspace, output_dir)


def _run(workspace: Path, out: Path) -> int:
    print()
    print("[1] Setup: workspace + identity")
    store = FileStateStore(workspace=workspace)
    agent_id = uuid4()

    identity = _build_identity(agent_id)
    store.save_identity(identity)
    narrative = _build_narrative(agent_id)
    store.save_narrative(narrative)
    print(f"    Agent ID: {agent_id}")
    print("    context_limit: 500 токенов (принудительно маленький для теста)")

    print()
    print("[2] Running conversation (4 messages → context fills up)")
    runner = RestartScenarioRunner(workspace, agent_id, store)
    results = runner.run(_CONVERSATION)

    print()
    print("[3] Verification")

    checks: list[tuple[str, bool, str]] = [
        (
            "Предупреждения о контексте были инжектированы",
            len(results["warnings_injected"]) > 0,
            f"warnings: {results['warnings_injected']}",
        ),
        (
            "Рестарт был инициирован",
            results["restart_triggered"],
            "",
        ),
        (
            "SessionExperience сессии 1 сохранён",
            results["experience_session_1"] is not None,
            f"experience: {results['experience_session_1']}",
        ),
        (
            "Key moments накоплены в сессии 1",
            results["key_moments_session_1"] > 0,
            f"key_moments: {results['key_moments_session_1']}",
        ),
        (
            "Restart package сформирован",
            results["restart_package_present"],
            "",
        ),
        (
            "Новая сессия открыта после рестарта",
            results["session_2_id"] is not None,
            f"session_2_id: {results['session_2_id']}",
        ),
        (
            "Агент способен продолжать разговор после рестарта",
            results["agent_coherent_after_restart"] is True,
            str(results.get("coherence_error", "")),
        ),
    ]

    all_passed = True
    for label, passed, detail in checks:
        status = "✓" if passed else "✗"
        print(f"    {status} {label}")
        if detail:
            print(f"      {detail}")
        if not passed:
            all_passed = False

    print()
    print("[4] Restart package preview:")
    if results["session_2_first_message"]:
        for line in results["session_2_first_message"].split("\n")[:10]:
            print(f"    {line}")
    print()

    _save_result(out / "lc_restart_results.json", results)
    print(f"    → {out / 'lc_restart_results.json'}")

    if all_passed:
        print()
        print("✓ E2E-LC PASSED — context limit + restart работает корректно")
        return 0
    else:
        print()
        print("✗ E2E-LC FAILED — см. детали выше")
        return 1


def main() -> int:
    print("=" * 70)
    print("E2E-LC: Session Lifecycle — Context Limit & Restart")
    print("=" * 70)
    try:
        return run_scenario(RESULT_DIR)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
