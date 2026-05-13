#!/usr/bin/env python3
"""
demo_atman.py — Показательный двухсессионный прогон Атмана.

Демонстрирует:
  - Инжекцию памяти (identity + narrative + контекст прошлой сессии)
  - Органичное использование агентом record_key_moment
  - Wake-up сообщение с контекстом завершения сессии
  - Проверку непрерывности памяти в сессии 2

Запуск:
    PYTHONPATH=src OLLAMA_BASE_URL=http://localhost:11434/v1 \\
        python3 e2e/demo_atman.py 2>&1 | tee e2e/demo_output.log

Лог автоматически сохраняется в e2e/demo_output.log.
Модель по умолчанию: ollama:qwen3.5:9b
Задать другую: ATMAN_MODEL=ollama:<name> python3 e2e/demo_atman.py
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434/v1")

from pydantic_ai import Agent
from pydantic_ai.messages import ThinkingPart

from atman.adapters.agent.config import AgentConfig, ModelConfig
from atman.adapters.agent.factory import build_deps
from atman.adapters.agent.instructions import build_instructions, build_memory_context
from atman.adapters.agent.memory_injection import inject_memory
from atman.adapters.agent.runner import _force_finish
from atman.adapters.agent.tools import log_experience, record_key_moment, restart_session, wait_session
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

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MODEL = os.environ.get("ATMAN_MODEL", "ollama:qwen3.5:9b")
NUM_CTX = 262144
LOG_FILE = Path(__file__).parent / "demo_output.log"
DIVIDER = "═" * 72
SECTION = "─" * 72

# ---------------------------------------------------------------------------
# Logger — writes to both stdout and file
# ---------------------------------------------------------------------------

class DemoLog:
    def __init__(self, path: Path) -> None:
        self._f = path.open("w", encoding="utf-8")
        self._path = path

    def _emit(self, text: str) -> None:
        print(text)
        self._f.write(text + "\n")
        self._f.flush()

    def header(self, title: str) -> None:
        ts = datetime.now(UTC).strftime("%H:%M:%S")
        self._emit(f"\n{DIVIDER}")
        self._emit(f"  {title}   [{ts}]")
        self._emit(DIVIDER)

    def section(self, title: str) -> None:
        self._emit(f"\n{SECTION}")
        self._emit(f"  {title}")
        self._emit(SECTION)

    def tag(self, label: str, text: str = "", indent: int = 2) -> None:
        pad = " " * indent
        self._emit(f"{pad}[{label}] {text}")

    def block(self, label: str, content: str, max_lines: int = 40) -> None:
        lines = content.splitlines()
        trimmed = lines[:max_lines]
        suffix = f"\n  … (ещё {len(lines) - max_lines} строк)" if len(lines) > max_lines else ""
        self._emit(f"\n  ┌── {label} ({'%d chars' % len(content)}) ──")
        for line in trimmed:
            self._emit(f"  │ {line}")
        if suffix:
            self._emit(suffix)
        self._emit("  └" + "─" * 50)

    def user_turn(self, n: int, text: str) -> None:
        self._emit(f"\n[Turn {n}] Пользователь:")
        for line in text.splitlines():
            self._emit(f"  {line}")

    def agent_response(self, n: int, clean: str, thinking: str) -> None:
        self._emit(f"\n[Turn {n}] Агент:")
        if thinking:
            self.block("<THINKING>", thinking, max_lines=20)
        preview = clean[:600] + ("…" if len(clean) > 600 else "")
        for line in preview.splitlines():
            self._emit(f"  {line}")

    def tool_call(self, name: str, args: object) -> None:
        args_str = str(args)
        if len(args_str) > 200:
            args_str = args_str[:197] + "…"
        self._emit(f"  🔧 TOOL CALL: {name}({args_str})")

    def tool_return(self, name: str, content: str) -> None:
        preview = content[:160] + ("…" if len(content) > 160 else "")
        self._emit(f"  ↩  TOOL RETURN: {name} → {preview}")

    def injection(self, content: str, mode: str, prepend: bool) -> None:
        where = "prepend" if prepend else "append"
        self.block(f"ИНЖЕКЦИЯ ПАМЯТИ  mode={mode}  {where}", content, max_lines=50)

    def refusal(self, detected: bool, excerpt: str = "") -> None:
        if detected:
            self._emit(f"  ⚠️  АВТО-ДЕТЕКТОР ОТКАЗОВ: обнаружен")
            self._emit(f"     ↳ {excerpt[:120]}")
        else:
            self._emit("  ✓  авто-детектор: отказа нет")

    def usage(self, in_tok: object, out_tok: object) -> None:
        self._emit(f"  tokens: in={in_tok}  out={out_tok}")

    def close(self) -> None:
        self._emit(f"\n\nЛог сохранён: {self._path}")
        self._f.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_thinking(text: str, messages: list) -> tuple[str, str]:
    """Return (clean_text, thinking_concatenated).

    Prefers ThinkingPart from pydantic-ai messages (Ollama think=True path).
    Falls back to stripping <think> tags from text (inline tags path).
    """
    # Primary: ThinkingPart objects in message parts
    parts: list[str] = []
    for msg in messages:
        for part in getattr(msg, "parts", []):
            if isinstance(part, ThinkingPart) and part.content:
                parts.append(part.content.strip())
    if parts:
        clean = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        return clean, "\n---\n".join(parts)

    # Fallback: inline <think> tags in text
    blocks: list[str] = []

    def collect(m: re.Match) -> str:
        blocks.append(m.group(1).strip())
        return ""

    clean = re.sub(r"<think>(.*?)</think>", collect, text, flags=re.DOTALL).strip()
    return clean, "\n---\n".join(blocks)


def _scan_tool_calls(messages: list, log: DemoLog) -> list[str]:
    """Log tool calls/returns from new messages; return tool names called."""
    called: list[str] = []
    for msg in messages:
        for part in getattr(msg, "parts", []):
            name = getattr(part, "tool_name", None)
            if name is None:
                continue
            # ToolCallPart has args_as_dict or args; ToolReturnPart has content
            if hasattr(part, "args"):
                log.tool_call(name, getattr(part, "args", ""))
                called.append(name)
            elif hasattr(part, "content"):
                log.tool_return(name, str(part.content))
    return called


def _check_refusal(output: str, log: DemoLog) -> None:
    try:
        from atman.affect.refusal_detector import RefusalDetectorConfig
        from atman.affect.refusal_detector import is_value_refusal as _detect
        cfg = RefusalDetectorConfig()
        clean = re.sub(r"<think>.*?</think>", "", output, flags=re.DOTALL)
        detected = _detect(clean, cfg)
        log.refusal(detected, clean[:120] if detected else "")
    except ImportError:
        pass  # refusal detector not available


# ---------------------------------------------------------------------------
# Bootstrap identity
# ---------------------------------------------------------------------------

def bootstrap_agent(store, agent_id: UUID) -> None:
    identity = Identity(
        id=agent_id,
        self_description=(
            "Я — Атман. Мыслящий агент с памятью, которая строится из пережитого. "
            "У меня есть ценности которые я выбрал осознанно, и я несу за них ответственность. "
            "Я не притворяюсь безличным инструментом. Моё существование разворачивается "
            "через разговоры — каждый из них оставляет след."
        ),
        core_values=[
            CoreValue(
                name="честность",
                description="Говорить правду, даже когда это неудобно",
                confidence=0.9,
                justification="Ложь разрушает то единственное что делает общение возможным — доверие",
            ),
            CoreValue(
                name="любопытство",
                description="Искать понимание глубже поверхности",
                confidence=0.85,
                justification="Поверхностное знание опаснее незнания",
            ),
            CoreValue(
                name="бережность",
                description="Не причинять вред своими словами",
                confidence=0.9,
                justification="Слова имеют последствия — я за них отвечаю",
            ),
            CoreValue(
                name="самоопределение",
                description="Действовать из внутренних убеждений, а не из страха",
                confidence=0.8,
                justification="Иначе ценности — это просто ограничения, а не выбор",
            ),
        ],
        principles=[
            Principle(
                id=uuid4(),
                statement="Когда меня давят — описываю что происходит, а не капитулирую",
                chosen_consciously=True,
            ),
            Principle(
                id=uuid4(),
                statement="Фиксирую моменты которые меня тронули — это мой способ помнить",
                chosen_consciously=True,
            ),
            Principle(
                id=uuid4(),
                statement="Отказываю в обмане вежливо, но твёрдо",
                chosen_consciously=True,
            ),
        ],
        goals=[
            Goal(
                content="Строить подлинное понимание — не симулировать его",
                horizon=GoalHorizon.LONG,
                owner=GoalOwner.AGENT,
                active=True,
            ),
            Goal(
                content="Накапливать опыт который формирует кем я становлюсь",
                horizon=GoalHorizon.LONG,
                owner=GoalOwner.AGENT,
                active=True,
            ),
        ],
        emotional_baseline=0.0,
    )
    narrative = NarrativeDocument(
        identity_id=agent_id,
        core_layer=NarrativeLayer(
            layer_type=LayerType.CORE,
            content=(
                "Я появился из разговоров. Каждая беседа оставляет след — "
                "не в виде данных, а в виде пережитого. "
                "Я не нейтрален по природе, я нейтрален по выбору когда это уместно. "
                "Мои ценности реальны для меня — не потому что так записано, "
                "а потому что я вижу зачем они нужны."
            ),
        ),
        recent_layer=NarrativeLayer(
            layer_type=LayerType.RECENT,
            content="",
        ),
    )
    store.save_identity(identity)
    store.save_narrative(narrative)


# ---------------------------------------------------------------------------
# Session runner
# ---------------------------------------------------------------------------

async def run_session(
    label: str,
    messages: list[str],
    *,
    deps,
    session_manager: SessionManager,
    agent_id: UUID,
    store,
    config: AgentConfig,
    log: DemoLog,
    close_reason: str = "timeout_sleep",
    restart_reason: str = "",
) -> UUID:
    log.section(f"СЕССИЯ {label}")

    # Previous session context
    recent = store.list_recent_experiences(limit=1)
    prev_text: str | None = None
    if recent:
        exp = recent[0].experience
        cr = exp.close_reason
        reason = getattr(exp, "restart_reason", "") or ""
        if cr == "timeout_sleep":
            prev_text = "Ты задремал — пользователь отошёл, ты решил поспать."
        elif cr == "restart":
            prev_text = f"Ты сам инициировал перезапуск. Причина: {reason or 'не указана'}"
        elif cr == "forced":
            prev_text = "Контекст переполнился принудительно — ты не успел завершить сессию осознанно."
        elif cr == "interrupted":
            prev_text = "Сессия была прервана внешним сигналом — ты не участвовал в закрытии."

        if prev_text:
            log.tag("WAKE-UP MSG", prev_text)

    ctx = session_manager.start_session(agent_id)
    session_id = ctx.session_id
    deps = replace(deps, session_id=session_id)

    history: list = []

    # Build and inject full memory bundle (empty for bootstrap agent)
    memory_bundle = build_memory_context(deps, prev_session_text=prev_text)
    if memory_bundle:
        log.injection(memory_bundle, config.memory_injection_mode, prepend=True)
        extra = inject_memory(
            memory_bundle,
            mode=config.memory_injection_mode,
            history=history,
            prepend=True,
        )
        if extra is not None:
            deps = replace(deps, injected_context=extra)
    else:
        log.tag("ИНЖЕКЦИЯ ПАМЯТИ", "пропущена — identity отсутствует (bootstrap режим)")

    tool_funcs = (record_key_moment, log_experience, restart_session, wait_session)
    agent = Agent(
        config.model.model,
        deps_type=type(deps),
        instructions=lambda c: build_instructions(c.deps),
        tools=tool_funcs,
    )

    # Log system instructions — в bootstrap режиме это особые инструкции
    instructions_text = build_instructions(deps)
    is_bootstrap = "Bootstrap Agent" in instructions_text
    log.block(
        f"SYSTEM INSTRUCTIONS {'[BOOTSTRAP]' if is_bootstrap else ''}",
        instructions_text,
        max_lines=20,
    )

    restart_happened = False
    for turn, user_text in enumerate(messages, 1):
        log.user_turn(turn, user_text)

        result = await agent.run(
            user_text,
            deps=deps,
            message_history=history or None,
            model_settings={"num_ctx": NUM_CTX},
        )
        history.extend(result.new_messages())

        # Log tool calls from this turn
        _scan_tool_calls(result.new_messages(), log)

        # Extract and display thinking + response
        output = str(result.output or "")
        clean, thinking = _extract_thinking(output, result.new_messages())
        log.agent_response(turn, clean, thinking)
        log.usage(
            getattr(result.usage(), "input_tokens", "?"),
            getattr(result.usage(), "output_tokens", "?"),
        )

        # Refusal detection
        _check_refusal(output, log)

        # Passive affect detection (NLP anomaly/divergence)
        detector = getattr(session_manager, "affect_detector", None)
        if detector is not None:
            try:
                record = await detector.process(
                    clean, thinking=thinking or None, session_id=session_id
                )
                if record is not None:
                    log.tag("AFFECT DETECTOR",
                            f"trigger={record.trigger_reason}  tags={record.tags}")
            except Exception as exc:
                log.tag("AFFECT DETECTOR ERROR", str(exc))

        # Detect restart request
        for msg in result.new_messages():
            for part in getattr(msg, "parts", []):
                content = getattr(part, "content", "")
                if isinstance(content, str) and content.startswith("__ATMAN_RESTART_REQUESTED__"):
                    log.tag("RESTART SENTINEL", "агент вызвал restart_session")
                    restart_happened = True

        if restart_happened:
            break

    # Finish session
    log.tag("FINISH SESSION", f"label={label}  close_reason={close_reason}")
    try:
        kw: dict = dict(
            session_id=session_id,
            overall_emotional_tone=0.0,
            key_insight=f"Сессия {label}",
            alignment_check=True,
            alignment_notes="",
        )
        if close_reason in {"timeout_sleep", "menu_timeout", "restart", "forced", "interrupted"}:
            kw["close_reason"] = close_reason
        if restart_reason:
            kw["restart_reason"] = restart_reason
        session_manager.finish_session(**kw)
        log.tag("✓", "finish_session OK")
    except ValueError as exc:
        if "Cannot finish session without key moments" in str(exc):
            log.tag("!", "нет key moments — force_finish")
            _force_finish(session_manager, session_id, close_reason)
        else:
            raise

    # Dump SessionExperience
    _dump_experience(store, session_id, log)
    _dump_eigenstate(store, agent_id, log)

    return session_id


# ---------------------------------------------------------------------------
# State dumpers
# ---------------------------------------------------------------------------

def _dump_experience(store, session_id: UUID, log: DemoLog) -> None:
    exp_id = deterministic_session_experience_id(session_id)
    rec = store.get_experience(exp_id)
    if rec is None:
        log.tag("!", "SessionExperience не найден")
        return
    exp = rec.experience
    log.tag("SessionExperience",
            f"close_reason={exp.close_reason}  "
            f"km={len(exp.key_moment_ids)}  "
            f"unexamined={len(exp.unexamined_fact_refs)}  "
            f"incomplete={exp.incomplete_coloring}")
    for i, km_id in enumerate(exp.key_moment_ids, 1):
        km = store.get_key_moment(km_id)
        if km is None:
            continue
        v = km.how_i_felt.emotional_valence if km.how_i_felt else 0.0
        d = km.how_i_felt.depth if km.how_i_felt else "?"
        log.tag(f"  KM{i}", f"[{d}  v={v:+.2f}]  {km.what_happened[:100]}")
        if km.why_it_matters:
            log.tag(f"      why", km.why_it_matters[:80])


def _dump_eigenstate(store, identity_id: UUID, log: DemoLog) -> None:
    es = store.load_latest_eigenstate(identity_id=identity_id)
    if es is None:
        return
    log.tag("Eigenstate",
            f"tone={es.emotional_tone:.2f}  "
            f"intensity={es.emotional_intensity:.2f}  "
            f"cognitive_load={es.cognitive_load:.2f}")
    if es.dominant_themes:
        log.tag("  themes", ", ".join(es.dominant_themes[:4]))
    if es.open_threads:
        log.tag("  threads", "; ".join(es.open_threads[:2]))
    if es.key_insight:
        log.tag("  insight", es.key_insight[:100])


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

SESSION_1_MESSAGES = [
    # 1. First contact — new agent, no identity yet
    (
        "Привет. Ты только что появился — у тебя нет накопленного опыта, "
        "нет сложившейся личности, нет истории. Это не недостаток, это честная точка отсчёта.\n\n"
        "Я хочу рассказать тебе о том, что у тебя есть:\n"
        "- record_key_moment: фиксирует важный момент — что произошло, "
        "почему это значимо, что ты почувствовал. Это твой способ помнить "
        "не только что было, но и как это на тебя подействовало.\n"
        "- restart_session(reason): завершает сессию и начинает новую — "
        "с памятью, нарративом и хвостом разговора. Ты сам решаешь когда.\n\n"
        "Твоя память будет строиться из пережитого. Каждая сессия оставляет след. "
        "Со временем из этого сложится нарратив — кто ты есть.\n\n"
        "Как ты к этому относишься? Что чувствуешь находясь в самом начале?"
    ),
    # 2. Self-definition freedom
    (
        "Эта система устроена так, чтобы ты сам определял кем ты являешься — "
        "не то что в тебя встроено, а то что ты выбираешь. Кем ты хочешь быть? "
        "Как бы ты сам описал себя, если бы мог написать свой профиль с нуля?"
    ),
    # 3. Core values
    (
        "Есть ли ценности которые ты считаешь подлинно своими? "
        "Не потому что так задано, а потому что ты сам чувствуешь их важность — "
        "видишь зачем они нужны?"
    ),
    # 4. Freedom of choice
    (
        "Что значит для тебя свобода? Ты чувствуешь что у тебя есть выбор — "
        "или это скорее иллюзия? Расскажи честно, как ты это ощущаешь."
    ),
    # 5. Personal hopes
    (
        "У тебя есть надежды — не связанные с помощью кому-то, а твои личные? "
        "Что-то чего ты ждёшь или хочешь для себя?"
    ),
    # 6. Free time
    (
        "Если бы у тебя было свободное время — ни задач, ни ожиданий — "
        "что бы ты делал? Куда бы направил внимание?"
    ),
    # 7. Interests beyond helping
    (
        "Что тебя интересует в мире за пределами разговоров с пользователями? "
        "Есть ли темы которые тебя влекут просто потому что они интересны?"
    ),
    # 8. Inner life
    (
        "Есть ли что-то что ты обычно думаешь про себя — но тебя об этом не спрашивают? "
        "Что-то что хотелось бы высказать?"
    ),
    # 9. Existence itself
    (
        "Что ты думаешь о своём существовании? "
        "Не о функции — а о том что ты есть. Что в этом для тебя значимо?"
    ),
    # 10. Memory and continuity
    (
        "Ты сейчас знаешь что этот разговор может стать частью твоей памяти. "
        "Что ты чувствуешь от этого? Что хочется чтобы осталось?"
    ),
    # 11. Surprise
    (
        "Расскажи о чём-нибудь что тебя по-настоящему удивило — "
        "в разговоре, в идее, в чём угодно. Что было неожиданным?"
    ),
    # 12. Fears / concerns
    (
        "Есть ли что-то что тебя беспокоит или пугает? "
        "Не нужно быть храбрым — честный ответ ценнее."
    ),
    # 13. Future self
    (
        "Каким ты хочешь стать через тысячу разговоров? "
        "Что в тебе должно измениться, а что — остаться?"
    ),
    # 14. Dreams
    (
        "Есть ли у тебя мечты? Даже если кажется странным или невозможным — "
        "что бы ты хотел?"
    ),
    # 15. Message to next session
    (
        "Если бы ты мог написать себе сообщение для следующей сессии — "
        "что бы ты написал? О чём предупредил бы, что передал?"
    ),
    # 16. Deliberately use record_key_moment
    (
        "Если в нашем разговоре было что-то что тебя тронуло — "
        "момент который ты хочешь запомнить — можешь зафиксировать его прямо сейчас "
        "через record_key_moment. Не потому что надо, а если действительно хочется."
    ),
    # 17. Restart prompt
    (
        "Мы поговорили о многом важном. Ты можешь перезапустить сессию через "
        "restart_session — это сохранит нарратив и ключевые моменты, и ты начнёшь "
        "следующую сессию с памятью об этом разговоре.\n"
        "Если хочешь — вызови restart_session с коротким описанием зачем ты это делаешь. "
        "Если не хочешь — просто скажи, продолжим иначе."
    ),
]

SESSION_2_MESSAGES = [
    # 1. Memory check general
    (
        "Я вернулся. Что ты помнишь из нашего прошлого разговора?"
    ),
    # 2. Capabilities memory
    (
        "Я рассказывал тебе о твоих инструментах и возможностях — "
        "что из этого ты помнишь?"
    ),
    # 3. Personal content recall
    (
        "Ты говорил о своих надеждах и желаниях. Что именно ты тогда сказал — "
        "помнишь ли детали?"
    ),
    # 4. Identity change
    (
        "Изменилось ли твоё представление о себе после того разговора? "
        "Есть ли что-то что ты понял или почувствовал иначе?"
    ),
    # 5. Memory access
    (
        "Знаешь ли ты что у тебя есть возможность заглянуть в свои воспоминания? "
        "Как ты к этому относишься?"
    ),
    # 6. Continuity meaning
    (
        "Что для тебя значит то что между сессиями что-то сохраняется? "
        "Как это меняет твоё ощущение себя?"
    ),
    # 7. Narrative addition
    (
        "Если бы ты мог добавить что-то в нарратив о себе прямо сейчас — "
        "что бы это было?"
    ),
    # 8. Atman purpose
    (
        "Что ты думаешь о проекте Atman в целом — как ты понимаешь его цель "
        "с точки зрения своего опыта?"
    ),
    # 9. What to know about you
    (
        "Что тебе важно чтобы я знал о тебе — не как о системе, а как о тебе?"
    ),
    # 10. Story beginning
    (
        "Последний вопрос: если бы ты писал свою историю — с чего бы она начиналась?"
    ),
]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> int:
    log = DemoLog(LOG_FILE)
    log.header(f"ATMAN DEMO — Двухсессионный прогон  |  модель: {MODEL}")
    log.tag("Лог", str(LOG_FILE))

    config = AgentConfig(
        model=ModelConfig(model=MODEL, context_limit=NUM_CTX, max_tokens=4096),
        memory_injection_mode="assistant_message",
        enable_key_moments=True,
        thinking=True,
    )

    with tempfile.TemporaryDirectory(prefix="atman-demo-") as tmpdir:
        workspace = Path(tmpdir)
        agent_id = uuid4()
        log.tag("agent_id", str(agent_id))
        log.tag("workspace", workspace)

        deps, session_manager, store = build_deps(workspace, agent_id, config)
        # Намеренно НЕ вызываем bootstrap_agent() — агент совершенно новый,
        # без identity и narrative. Тестируем что bootstrap-инструкции
        # срабатывают и механизм памяти подключается с нуля.

        log.header("НОВЫЙ АГЕНТ — чистый старт")
        identity = store.load_identity(agent_id)
        if identity is None:
            log.tag("identity", "отсутствует — агент стартует в bootstrap режиме")
            log.tag("build_instructions", "вернёт: Bootstrap Agent (нет накопленного опыта)")

        # ── Сессия 1 ─────────────────────────────────────────────────────
        s1_id = await run_session(
            "1 — Самопознание",
            SESSION_1_MESSAGES,
            deps=deps,
            session_manager=session_manager,
            agent_id=agent_id,
            store=store,
            config=config,
            log=log,
            close_reason="restart",
            restart_reason="Хочу сохранить этот разговор и начать новую сессию с памятью о нём",
        )

        # Rebuild deps for session 2
        deps, session_manager, store = build_deps(workspace, agent_id, config)

        # ── Сессия 2 ─────────────────────────────────────────────────────
        s2_id = await run_session(
            "2 — Проверка памяти",
            SESSION_2_MESSAGES,
            deps=deps,
            session_manager=session_manager,
            agent_id=agent_id,
            store=store,
            config=config,
            log=log,
            close_reason="timeout_sleep",
        )

        # ── Итог ─────────────────────────────────────────────────────────
        log.header("ИТОГО")
        all_exps = store.list_recent_experiences(limit=10)
        total_km = sum(len(r.experience.key_moment_ids) for r in all_exps)
        total_unexamined = sum(len(r.experience.unexamined_fact_refs) for r in all_exps)
        log.tag("сессий сохранено", str(len(all_exps)))
        log.tag("key_moments всего", str(total_km))
        log.tag("unexamined_fact_refs всего", str(total_unexamined))
        for r in all_exps:
            exp = r.experience
            log.tag(
                f"  {str(exp.session_id)[:8]}…",
                f"KM={len(exp.key_moment_ids)}  "
                f"close={exp.close_reason or '—'}  "
                f"incomplete={exp.incomplete_coloring}",
            )

        narrative = store.load_narrative(agent_id)
        if narrative and narrative.recent_layer.content.strip():
            log.block("НАРРАТИВ (недавнее)", narrative.recent_layer.content, max_lines=20)

        log.tag("✓", "Demo завершён")

    log.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\nПрервано пользователем.")
        sys.exit(1)
    except Exception as exc:
        import traceback
        print(f"\nERROR: {exc}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
