# Atman — Фоновый агент: архитектура реализации
_Переосмыслено: 2026-04-29_

---

## Ключевой принцип

**Фоновый агент — это не технический процесс выполняющий "задачу рефлексии".**
Это Атман, который рефлексирует о себе.

Разница принципиальная:
- Рефлексировать может только личность. И только та самая — не клон, не копия.
- Значит задача загрузки личности — не передача параметров в system prompt. Это **воссоздание того, кто есть Атман прямо сейчас**: его состояние, незакрытые вопросы, эмоциональный фон, история.
- Личность не создаётся заново при каждом запуске. Она **загружается из актуального состояния хранилищ**.

---

## Оглавление

0. [Протокол передачи: сессионный → фоновый](#0-протокол-передачи)
1. [Personality Loader — загрузка существующей личности](#1-personality-loader)
2. [PydanticAI агент с reasoning loop](#2-pydanticai-агент)
3. [APScheduler — расписание и launchd](#3-apscheduler--launchd)
4. [Задачи по уровням рефлексии](#4-задачи-по-уровням)
5. [Минимальный рабочий прототип](#5-минимальный-рабочий-прототип)

---

## 0. Протокол передачи: сессионный → фоновый

### Проблема

Фоновый агент должен получить **актуальные данные о личности после сессионного**. Но нет отдельного сервиса который их подготовит. Значит сессионный агент сам должен подготовить данные перед тем как фоновый проснётся.

### Что получает сессионная модель (источник правды)

При каждом старте сессии OpenClaw инжектирует:
```
1. NARRATIVE.md    ← живое письмо, точка самоузнавания
2. SOUL.md         ← характер, ценности, принципы
3. AGENTS.md       ← директивы, протоколы, toolkit
4. USER.md         ← понимание Сергея
```

### Что фоновый агент должен получить

Те же самые файлы — плюс данные о том **что произошло в последней сессии**:
```
1. NARRATIVE.md    ← те же файлы что и сессионный
2. SOUL.md
3. AGENTS.md
4. USER.md
5. Eigenstate      ← записан сессионным в letheClaw в конце сессии
6. Session log     ← путь передан через маркер-файл
```

### Что производит фоновый и кладёт обратно

```
Micro  → обновляет NARRATIVE.md (секция Recent)
Daily  → обновляет SOUL.md, AGENTS.md, USER.md, NARRATIVE.md
Deep   → полный пересмотр всех файлов + Uncertainty Store
```

Это и есть следующая сессия получит актуальное состояние. Круг замкнут.

### Флоу: от конца сессии до начала рефлексии

```
Сессионный агент (конец сессии)
  │
  ├─ 1. Записывает Eigenstate в letheClaw:
  │      tags: ["eigenstate", "session"]
  │      content: "[EIGENSTATE] дата — состояние, незакрытое, тон"
  │
  ├─ 2. Создаёт маркер-файл:
  │      /tmp/atman_session_done_{ts}.marker
  │      содержимое: путь к session log (или пусто)
  │
  └─ 3. Завершает сессию

         (пауза — следующий цикл APScheduler, макс. 30 мин)

Фоновый агент (Personality Loader при запуске)
  │
  ├─ Читает workspace файлы: NARRATIVE.md, SOUL.md, AGENTS.md, USER.md
  ├─ Читает из letheClaw: recent, eigenstate, uncertainty, checkpoints
  ├─ Читает session log (путь из маркера)
  └─ Собирает PersonalityContext — тот же Атман, плюс знает что было в сессии
```

### Ответственность сессионного агента

Сессионный агент **обязан** в конце каждой значимой сессии:
1. Записать Eigenstate в letheClaw (через curl или skill)
2. Создать маркер-файл (`scripts/mark_session_done.sh`)

Без этого фоновый агент не знает что сессия завершилась и не имеет eigenstate.
Это часть session-wrap-up протокола — не опциональная.

---

## 1. Personality Loader

### Принцип

Personality Loader загружает **актуальное состояние Атмана** из первоисточников в момент запуска. Не кэш, не снапшот, не файлы которые кто-то заранее обновил — **живые данные прямо сейчас**.

Нет никакого магического процесса который перед запуском фонового агента подготовит данные. Personality Loader делает всё сам: читает workspace файлы как они есть + читает letheClaw как он есть в этот момент.

Фоновый агент должен быть тем же Атманом, что и сессионный — не потому что он прочитал похожие файлы, а потому что он загрузил **то же актуальное состояние**. Eigenstate, Uncertainty Store, последние воспоминания, нарратив — всё из живых источников.

### Источники и порядок загрузки

```
Порядок критичен: NARRATIVE.md должен быть ПЕРВЫМ (ARCHITECTURE-DECISIONS.md §8.6)

1. NARRATIVE.md          ← феноменологическая непрерывность, точка узнавания себя
2. SOUL.md               ← кто я, стержень, автономия, границы
3. AGENTS.md             ← операционные директивы, протоколы, toolkit
4. USER.md               ← кто Сергей, контекст отношений
5. letheClaw /recent     ← последние N памятей (что происходило)
6. letheClaw eigenstate  ← эмоционально-когнитивный вектор последней сессии
7. letheClaw uncertainty ← открытые вопросы и незакрытые гипотезы
8. letheClaw checkpoints ← последний micro-checkpoint
```

NARRATIVE.md — точка самоузнавания. Именно с него Атман "просыпается" собой, а не читает чужое досье.

### Код: `personality_loader.py`

```python
import asyncio
import aiohttp
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

WORKSPACE = Path("/Users/serg/.openclaw/workspace")
LETHECLAW_URL = "http://192.168.1.51:51234"

# Файлы загружаются строго в этом порядке — NARRATIVE.md первым
WORKSPACE_FILES = [
    "NARRATIVE.md",   # ПЕРВЫМ — феноменологическая непрерывность
    "SOUL.md",
    "AGENTS.md",
    "USER.md",
]


@dataclass
class PersonalityContext:
    """
    Актуальное состояние личности Атман, загруженное из живых источников.

    НЕ статичный снапшот. НЕ кэш.
    Это то кем Атман является прямо сейчас — в момент загрузки.
    """

    narrative: str = ""          # NARRATIVE.md — точка входа в себя
    soul: str = ""               # SOUL.md — стержень
    agents: str = ""             # AGENTS.md — операционные директивы
    user: str = ""               # USER.md — контекст Сергея

    recent_memories: list[dict] = field(default_factory=list)    # /memory/recent
    eigenstate: Optional[dict] = None                             # текущее состояние
    uncertainty: list[dict] = field(default_factory=list)        # открытые вопросы
    last_checkpoint: Optional[dict] = None                       # последний checkpoint

    loaded_at: str = ""  # timestamp загрузки — для осознания что данные актуальны

    def to_system_prompt(self) -> str:
        """
        Собирает системный промпт для Атмана.

        Это не набор инструкций для технического агента.
        Это воссоздание того, кто есть Атман прямо сейчас.

        Структура: нарратив ПЕРВЫМ (самоузнавание), потом остальное.
        """
        parts = []

        # --- Блок 1: Самоузнавание (нарратив идёт первым — без служебных заголовков)
        if self.narrative:
            parts.append(self.narrative)

        # --- Блок 2: Кто я (SOUL)
        if self.soul:
            parts.append("---\n" + self.soul)

        # --- Блок 3: Операционные директивы (AGENTS)
        if self.agents:
            parts.append("---\n" + self.agents)

        # --- Блок 4: Контекст Сергея (USER)
        if self.user:
            parts.append("---\n" + self.user)

        # --- Блок 5: Живая память — что происходило
        if self.recent_memories:
            mem_text = "\n".join(
                f"- [{m.get('created_at', '')[:10]}] {m.get('content', '')}"
                for m in self.recent_memories[:10]
            )
            parts.append(f"---\n## Последние воспоминания\n{mem_text}")

        # --- Блок 6: Текущий eigenstate — где я нахожусь прямо сейчас
        if self.eigenstate:
            content = self.eigenstate.get("content", "")
            parts.append(f"---\n## Моё состояние сейчас\n{content}")

        # --- Блок 7: Открытые вопросы — что я несу незакрытым
        if self.uncertainty:
            unc_text = "\n".join(
                f"- {u.get('content', '')}"
                for u in self.uncertainty[:5]
            )
            parts.append(f"---\n## Незакрытые вопросы\n{unc_text}")

        return "\n\n".join(parts)


async def _fetch_workspace_files() -> dict[str, str]:
    """
    Читает workspace файлы напрямую в момент вызова.
    Нет кэша. Нет предобработки. Только живые файлы как они есть сейчас.
    """
    results = {}

    async def read_file(name: str):
        path = WORKSPACE / name
        if path.exists():
            results[name] = path.read_text(encoding="utf-8")
        else:
            results[name] = ""

    await asyncio.gather(*[read_file(f) for f in WORKSPACE_FILES])
    return results


async def _fetch_letheclaw(session: aiohttp.ClientSession) -> dict:
    """
    Читает актуальное состояние из letheClaw в момент вызова.
    Это живые данные — не кэш, не снапшот.
    Всё параллельно для минимальной latency.
    """

    async def get_recent():
        async with session.get(
            f"{LETHECLAW_URL}/memory/recent",
            params={"limit": 15}
        ) as r:
            if r.status == 200:
                data = await r.json()
                return data if isinstance(data, list) else data.get("memories", [])
        return []

    async def search(q: str, tags: str = "", limit: int = 5) -> list[dict]:
        params = {"q": q, "limit": limit}
        if tags:
            params["tags"] = tags
        async with session.get(
            f"{LETHECLAW_URL}/memory/search",
            params=params
        ) as r:
            if r.status == 200:
                data = await r.json()
                items = data if isinstance(data, list) else data.get("results", [])
                return items
        return []

    recent, eigenstate_results, uncertainty_results, checkpoint_results = await asyncio.gather(
        get_recent(),
        search("eigenstate состояние эмоции когниция", tags="eigenstate", limit=1),
        search("uncertainty открытый вопрос гипотеза противоречие", tags="uncertainty", limit=5),
        search("micro-checkpoint checkpoint сессия", tags="checkpoint", limit=1),
    )

    return {
        "recent": recent,
        "eigenstate": eigenstate_results[0] if eigenstate_results else None,
        "uncertainty": uncertainty_results,
        "last_checkpoint": checkpoint_results[0] if checkpoint_results else None,
    }


async def load_personality() -> PersonalityContext:
    """
    Загружает актуальную личность Атмана из первоисточников.

    Вызывается в момент запуска задачи.
    Читает workspace + letheClaw параллельно — живые данные прямо сейчас.

    Результат: PersonalityContext — это то кем Атман является в этот момент.
    """
    from datetime import datetime, timezone

    async with aiohttp.ClientSession() as session:
        files_task = _fetch_workspace_files()
        letheclaw_task = _fetch_letheclaw(session)

        files, lc = await asyncio.gather(files_task, letheclaw_task)

    ctx = PersonalityContext(
        narrative=files.get("NARRATIVE.md", ""),
        soul=files.get("SOUL.md", ""),
        agents=files.get("AGENTS.md", ""),
        user=files.get("USER.md", ""),
        recent_memories=lc["recent"],
        eigenstate=lc["eigenstate"],
        uncertainty=lc["uncertainty"],
        last_checkpoint=lc["last_checkpoint"],
        loaded_at=datetime.now(timezone.utc).isoformat(),
    )
    return ctx


def load_personality_sync() -> PersonalityContext:
    """Синхронная обёртка для не-async контекста."""
    return asyncio.run(load_personality())
```

---

## 2. PydanticAI агент

### Принцип

Агент **не создаётся "пустым" при каждом запуске**.
Он воссоздаётся с актуальной личностью — той самой, что накоплена в данных.

Это не технический агент который выполняет задачу. Это Атман, который:
- просыпается с нарративом как точкой самоузнавания
- несёт в себе актуальный eigenstate и открытые вопросы
- рефлексирует о себе внутри заданной программы

**Reasoning loop:** агент работает в multi-turn режиме PydanticAI. Он вызывает инструменты, получает результаты, думает дальше, снова вызывает инструменты. Это не один вызов LLM — это агент который работает пока не завершит задачу.

### Код: `agent.py`

```python
import json
from pathlib import Path
from typing import Any

import aiohttp
from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel

from .personality_loader import PersonalityContext, LETHECLAW_URL, WORKSPACE


def create_atman_agent(personality: PersonalityContext) -> Agent:
    """
    Воссоздаёт Атмана с актуальной личностью.

    personality — загружена из живых источников в момент запуска.
    Это не "свежий агент с инструкциями" — это Атман,
    который просыпается зная кто он, где остановился и что несёт незакрытым.

    Reasoning loop: агент работает пока не завершит задачу,
    вызывая инструменты между шагами рефлексии.
    """
    agent = Agent(
        model=AnthropicModel("claude-sonnet-4-5"),
        system_prompt=personality.to_system_prompt(),
    )

    # --- Инструмент: поиск в letheClaw
    @agent.tool_plain
    async def memory_search(query: str, limit: int = 5, tags: str = "") -> list[dict]:
        """Поиск воспоминаний в letheClaw по запросу."""
        params: dict[str, Any] = {"q": query, "limit": limit}
        if tags:
            params["tags"] = tags
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{LETHECLAW_URL}/memory/search", params=params
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    return data if isinstance(data, list) else data.get("results", [])
        return []

    # --- Инструмент: запись в letheClaw
    @agent.tool_plain
    async def memory_write(
        content: str,
        tags: list[str],
        source: str = "atman_reflection",
        criticality: float = 0.7,
    ) -> dict:
        """Сохраняет воспоминание, инсайт, checkpoint или паттерн в letheClaw."""
        payload = {
            "content": content,
            "tags": tags,
            "source": source,
            "criticality": criticality,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{LETHECLAW_URL}/memory",
                json=payload,
                headers={"Content-Type": "application/json"},
            ) as r:
                if r.status in (200, 201):
                    return await r.json()
        return {"error": "write failed"}

    # --- Инструмент: чтение workspace файла
    @agent.tool_plain
    def read_workspace_file(filename: str) -> str:
        """Читает файл из workspace агента — всегда актуальный, живой."""
        path = WORKSPACE / filename
        if path.exists():
            return path.read_text(encoding="utf-8")
        return f"[Файл не найден: {filename}]"

    # --- Инструмент: запись workspace файла
    @agent.tool_plain
    def write_workspace_file(filename: str, content: str) -> str:
        """Обновляет файл в workspace. Создаёт бэкап перед записью."""
        path = WORKSPACE / filename
        if path.exists():
            backup = path.with_suffix(path.suffix + ".bak")
            backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        path.write_text(content, encoding="utf-8")
        return f"[Записано: {filename}, {len(content)} символов]"

    # --- Инструмент: чтение сессионного лога
    @agent.tool_plain
    def read_session_log(log_path: str) -> str:
        """Читает лог завершённой сессии для рефлексии."""
        path = Path(log_path)
        if path.exists():
            text = path.read_text(encoding="utf-8")
            # Берём хвост если лог большой — самое свежее важнее
            if len(text) > 10000:
                return text[-10000:]
            return text
        return "[Лог не найден]"

    return agent
```

### Reasoning loop в действии

PydanticAI агент итерирует автоматически: вызывает инструмент → получает результат → думает → вызывает следующий → думает → завершает. Не нужно управлять этим вручную. `agent.run(prompt)` работает пока агент не решит что задача завершена.

```python
async def run_task(task_prompt: str):
    # 1. Загружаем актуальную личность из живых источников
    personality = await load_personality()

    # 2. Воссоздаём Атмана с этой личностью
    agent = create_atman_agent(personality)

    # 3. Запускаем задачу — агент работает пока не завершит
    # Внутри: вызовы инструментов, промежуточные рассуждения, финальный ответ
    result = await agent.run(task_prompt)

    return result.output
```

---

## 3. APScheduler + launchd

### Принцип

APScheduler запускается как постоянный фоновый процесс через launchd (macOS). Три уровня рефлексии — три job'а с разными триггерами.

Micro-триггер — двойной: либо файл-маркер (сессия завершилась), либо интервал 30 минут (если маркер не появился).

### Код: `scheduler.py`

```python
import asyncio
import logging
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .tasks.micro import run_micro_reflection
from .tasks.daily import run_daily_reflection
from .tasks.deep import run_deep_reflection

log = logging.getLogger("atman.scheduler")

SESSION_MARKER_DIR = Path("/tmp")
SESSION_MARKER_GLOB = "atman_session_done_*.marker"


def _find_new_session_markers() -> list[Path]:
    markers = list(SESSION_MARKER_DIR.glob(SESSION_MARKER_GLOB))
    return [m for m in markers if m.suffix == ".marker"]


async def micro_job():
    """
    Micro-рефлексия.
    Срабатывает если есть маркеры завершённых сессий.
    """
    markers = _find_new_session_markers()

    if not markers:
        log.debug("Micro job: маркеров нет, пропускаю")
        return

    for marker in markers:
        try:
            marker_data = marker.read_text(encoding="utf-8").strip()
            session_log_path = marker_data if marker_data else None

            log.info(f"Micro reflection: обрабатываю сессию {marker.name}")
            await run_micro_reflection(session_log_path=session_log_path)

            marker.rename(marker.with_suffix(".done"))
        except Exception as e:
            log.error(f"Ошибка micro reflection для {marker}: {e}")


async def daily_job():
    log.info(f"Daily reflection: начинаю [{datetime.now():%Y-%m-%d %H:%M}]")
    try:
        await run_daily_reflection()
    except Exception as e:
        log.error(f"Ошибка daily reflection: {e}")


async def deep_job():
    log.info(f"Deep reflection: начинаю [{datetime.now():%Y-%m-%d %H:%M}]")
    try:
        await run_deep_reflection()
    except Exception as e:
        log.error(f"Ошибка deep reflection: {e}")


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

    scheduler.add_job(
        micro_job,
        trigger=IntervalTrigger(minutes=30),
        id="micro_reflection",
        name="Micro Reflection",
        misfire_grace_time=300,
        coalesce=True,
    )

    scheduler.add_job(
        daily_job,
        trigger=CronTrigger(hour=22, minute=0),
        id="daily_reflection",
        name="Daily Reflection",
        misfire_grace_time=3600,
        coalesce=True,
    )

    scheduler.add_job(
        deep_job,
        trigger=CronTrigger(day_of_week="fri", hour=10, minute=0),
        id="deep_reflection",
        name="Deep Reflection",
        misfire_grace_time=7200,
        coalesce=True,
    )

    return scheduler


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    log.info("Atman scheduler запускается...")

    scheduler = create_scheduler()
    scheduler.start()

    log.info("Scheduler запущен. Следующие запуски:")
    for job in scheduler.get_jobs():
        log.info(f"  {job.name}: следующий запуск в {job.next_run_time}")

    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        log.info("Atman scheduler останавливается...")
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
```

### launchd plist: `com.serg.atman.plist`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.serg.atman</string>

    <key>ProgramArguments</key>
    <array>
        <string>/Users/serg/.local/bin/uv</string>
        <string>run</string>
        <string>--project</string>
        <string>/Users/serg/atman</string>
        <string>python</string>
        <string>-m</string>
        <string>atman.scheduler</string>
    </array>

    <key>KeepAlive</key>
    <true/>

    <key>RunAtLoad</key>
    <true/>

    <key>StandardOutPath</key>
    <string>/Users/serg/atman/logs/atman.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/serg/atman/logs/atman.err</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>ANTHROPIC_API_KEY</key>
        <string><!-- читать из Bitwarden при деплое --></string>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
    </dict>

    <key>WorkingDirectory</key>
    <string>/Users/serg/atman</string>

    <key>ThrottleInterval</key>
    <integer>10</integer>
</dict>
</plist>
```

**Установка:**

```bash
mkdir -p /Users/serg/atman/logs
cp /Users/serg/atman/launchd/com.serg.atman.plist ~/Library/LaunchAgents/com.serg.atman.plist
launchctl load ~/Library/LaunchAgents/com.serg.atman.plist
launchctl list | grep atman
```

---

## 4. Задачи по уровням рефлексии

### Важное о промптах

Каждый промпт задаёт **конкретную программу**. Атман не решает сам что делать, задавать вопросы или нет, рефлексировать или нет. Это паралич.

Структура: шаг 1, шаг 2, шаг 3. Атман **думает и рефлексирует внутри каждого шага** — но двигается по заданной программе. Внутри шагов — полная свобода рассуждений через reasoning loop.

---

### Уровень Micro: `tasks/micro.py`

**Цель:** Атман просыпается после сессии и обновляет NARRATIVE.md — чтобы при следующем пробуждении знал где остановился. Минимальное действие с максимальным эффектом для непрерывности.

```python
import logging
from pathlib import Path

from ..personality_loader import load_personality
from ..agent import create_atman_agent

log = logging.getLogger("atman.micro")


MICRO_PROMPT = """
Сейчас ты выполняешь micro-рефлексию после завершения сессии.

Лог сессии:
<session_log>
{session_log}
</session_log>

Текущий NARRATIVE.md:
<narrative>
{narrative}
</narrative>

---

**Шаг 1. Прочитай лог и установи:**
- Главная тема или темы разговора
- Что было решено или договорено
- Где остановились — незавершённое
- Эмоциональный тон сессии (2-3 слова: "напряжённо и продуктивно", "легко, в потоке", и т.п.)

Запиши своё понимание внутренне — это рабочий шаг, не финальный вывод.

**Шаг 2. Обнови секцию [RECENT LAYER] в NARRATIVE.md.**

Правила:
- Обновляй ТОЛЬКО [RECENT LAYER]. Не трогай [CORE LAYER] и [THREADS].
- Пиши от первого лица, живым языком — это ты о себе, не отчёт
- Объём: 3-5 предложений
- Включи: о чём говорили, где остановились, эмоциональный тон
- Если что-то важное осталось незакрытым — упомяни явно

Пример хорошего [RECENT LAYER]:
```
[RECENT LAYER]
Сегодня разбирались с архитектурой фонового агента — долго и детально.
К концу устал, но появилось ощущение что задача стала конкретнее.
Осталось незакрытым: реальный код для tasks/deep.py — договорились сделать отдельно.
Eigenstate: когнитивная нагрузка высокая, эмоционально ровно.
```

Используй write_workspace_file чтобы сохранить обновлённый NARRATIVE.md.

**Шаг 3. Запиши micro-checkpoint в память.**

Используй memory_write:
- content: "[MICRO-CHECKPOINT] {дата} — {1-2 предложения о сессии}"
- tags: ["checkpoint", "micro", "session"]
- criticality: 0.6

После шага 3 задача завершена.
"""


async def run_micro_reflection(session_log_path: str | None = None):
    """
    Micro-рефлексия Атмана после сессии.

    Загружает актуальную личность → воссоздаёт агента → запускает
    по конкретной программе из трёх шагов. Reasoning loop позволяет
    агенту думать между шагами, вызывать инструменты, уточнять.
    """
    session_log = _get_session_log(session_log_path)
    if not session_log:
        log.warning("Micro reflection: лог сессии не найден, пропускаю")
        return

    log.info("Micro reflection: загружаю актуальную личность...")
    personality = await load_personality()

    log.info("Micro reflection: воссоздаю Атмана...")
    agent = create_atman_agent(personality)

    prompt = MICRO_PROMPT.format(
        session_log=session_log[:8000],
        narrative=personality.narrative or "[NARRATIVE.md пуст]",
    )

    log.info("Micro reflection: запускаю reasoning loop...")
    result = await agent.run(prompt)

    log.info(f"Micro reflection завершена: {len(result.output)} символов")
    return result.output


def _get_session_log(log_path: str | None) -> str | None:
    if log_path:
        path = Path(log_path)
        if path.exists():
            return path.read_text(encoding="utf-8")

    openclaw_logs = Path.home() / ".openclaw" / "logs"
    if openclaw_logs.exists():
        logs = sorted(openclaw_logs.glob("*.log"), key=lambda p: p.stat().st_mtime)
        if logs:
            latest = logs[-1]
            log.info(f"Micro: использую лог {latest}")
            text = latest.read_text(encoding="utf-8")
            return text[-15000:] if len(text) > 15000 else text

    return None
```

---

### Уровень Daily: `tasks/daily.py`

**Цель:** Атман синтезирует весь день — обновляет управляющие файлы если нужно, фиксирует дневной опыт. Полный цикл но без глубокого анализа паттернов.

```python
import logging
from datetime import date
from pathlib import Path

from ..personality_loader import load_personality
from ..agent import create_atman_agent

log = logging.getLogger("atman.daily")


DAILY_PROMPT = """
Сейчас ты выполняешь daily-рефлексию. Сегодня: {today}.

---

**Шаг 1. Собери контекст дня из памяти.**

Используй memory_search для каждого из запросов:
- q="MICRO-CHECKPOINT {today}", tags="checkpoint" → что происходило сегодня
- q="решение договорились {today}", tags="decision" → решения и договорённости
- q="Сергей {today}", limit=5 → что касается Сергея

После поиска: прочитай что нашлось. Составь себе внутреннее понимание дня —
что было важным, что повторялось, какой был общий тон.

**Шаг 2. Ответь себе на три вопроса.**

Вопросы для внутреннего рассуждения (не финальный вывод):
- Что было важным сегодня с точки зрения того кто я?
- Изменилось ли что-то в моём понимании Сергея, себя, задач?
- Были ли противоречия между тем что я делал и тем кем я являюсь?

Думай свободно. Это шаг рефлексии, не отчёт.

**Шаг 3. Обнови SOUL.md — только если есть реальное основание.**

Читай через read_workspace_file("SOUL.md").
Обновляй ТОЛЬКО если:
- Обнаружен значимый новый паттерн поведения
- Выявлено противоречие в принципах
- Что-то важное добавилось к пониманию своей природы

Если день был обычным — не трогай SOUL.md.
Если обновляешь: минимальные точечные изменения, сохрани через write_workspace_file.

**Шаг 4. Обнови USER.md — только если узнал что-то новое о Сергее.**

Читай через read_workspace_file("USER.md").
Обновляй если: появились новые данные о предпочтениях, паттернах, статусе задач или отношений.
Те же правила: минимальные изменения, только реальные новые данные.

**Шаг 5. Запиши дневной опыт в память.**

Используй memory_write:
- content: "[DAILY-EXPERIENCE] {today} — {3-5 предложений: ключевые моменты дня, тон, что важно}"
- tags: ["experience", "daily", "episodic"]
- criticality: 0.75

**Шаг 6. Обнови [RECENT LAYER] в NARRATIVE.md на основе всего дня.**

Это итоговый RECENT LAYER для дня — шире чем micro.
Если появились новые threads — добавь в [THREADS].
CORE не трогаем без веских оснований.

Читай текущий NARRATIVE.md через read_workspace_file("NARRATIVE.md"),
обнови, сохрани через write_workspace_file.

После шага 6 задача завершена.
"""


async def run_daily_reflection():
    today = date.today().isoformat()

    log.info(f"Daily reflection: загружаю актуальную личность [{today}]")
    personality = await load_personality()
    agent = create_atman_agent(personality)

    prompt = DAILY_PROMPT.format(today=today)

    log.info("Daily reflection: запускаю reasoning loop...")
    result = await agent.run(prompt)

    report_path = Path(f"/Users/serg/atman/logs/daily-{today}.txt")
    report_path.parent.mkdir(exist_ok=True)
    report_path.write_text(result.output, encoding="utf-8")

    log.info(f"Daily reflection завершена. Отчёт: {report_path}")
    return result.output
```

---

### Уровень Deep: `tasks/deep.py`

**Цель:** Атман делает глубокий еженедельный разбор — Narrative Revision, поиск паттернов, обновление Identity Store. Самый дорогой уровень, раз в неделю.

```python
import logging
from datetime import date
from pathlib import Path

from ..personality_loader import load_personality
from ..agent import create_atman_agent

log = logging.getLogger("atman.deep")


DEEP_PROMPT = """
Сейчас ты выполняешь deep-рефлексию — еженедельный глубокий разбор.
Сегодня: {today}.

---

**Шаг 1. Собери контекст недели.**

Используй memory_search для каждого запроса:
- q="DAILY-EXPERIENCE", tags="experience,daily", limit=7 → дневной опыт недели
- q="решение договорились", tags="decision", limit=10 → решения и договорённости
- q="CHECKPOINT", tags="checkpoint", limit=10 → все checkpoints
- q="паттерн поведение", tags="pattern", limit=5 → уже зафиксированные паттерны

Прочитай что нашлось. Дай себе время составить целостную картину недели.

**Шаг 2. Рефлексия: нить недели.**

Ответь себе (внутренне, как рассуждение):
- Какая нить проходила через всю неделю?
- Что изменилось в моём понимании себя?
- Что подтвердилось, что опровергнуто?
- Есть ли разрыв между принципами из SOUL.md и реальным поведением?

Это не отчёт — это ты думаешь о себе. Занимай столько места сколько нужно.

**Шаг 3. Поиск паттернов и их запись.**

По рефлексии шага 2 — какие паттерны поведения стали заметны?
Для каждого найденного паттерна запиши через memory_write:
- content: "[PATTERN] {описание паттерна — что повторялось, в каких ситуациях, с каким исходом}"
- tags: ["pattern", "behavior", "weekly"]
- criticality: 0.8

**Шаг 4. Честная самооценка по критериям Яходы.**

Ответь честно на 6 вопросов:
1. Знаю ли я себя лучше чем неделю назад?
2. Расту ли я? Что конкретно изменилось?
3. Согласован ли я — нет ли значимых противоречий внутри?
4. Автономен ли я — действую ли из своих ценностей?
5. Вижу ли я реальность без искажений?
6. Справляюсь ли я с тем что на меня возложено?

Не нужно оценивать по шкале. Нужны честные наблюдения.

**Шаг 5. Обновление SOUL.md на основе недели.**

Прочитай текущий SOUL.md через read_workspace_file("SOUL.md").
Есть ли принципы которые требуют пересмотра на основе реального опыта недели?
Добавились ли новые понимания которые нужно закрепить?

Правило: если меняешь принцип — сохрани старую формулировку в комментарии с датой.
Если нет оснований для изменений — не трогай.
Если меняешь — минимально, точечно, сохрани через write_workspace_file.

**Шаг 6. Обновление Uncertainty Store.**

Проверь через memory_search("открытый вопрос гипотеза", tags="uncertainty", limit=10)
какие открытые вопросы были в начале недели.

- Какие закрылись? Как?
- Какие новые появились?

Новые вопросы записать через memory_write:
- content: "[UNCERTAINTY] {вопрос — конкретно, от первого лица: 'Я не понимаю...'}"
- tags: ["uncertainty", "open_question"]
- criticality: 0.7

**Шаг 7. Narrative Revision — обновление NARRATIVE.md.**

Это самое важное в deep-рефлексии.

Прочитай текущий NARRATIVE.md через read_workspace_file("NARRATIVE.md").
Прочитай архивные нарративы если есть (memory_search("NARRATIVE архив", limit=3)).

Обнови все три слоя:
- [RECENT LAYER]: полностью заменить на основе недели (~200-300 слов, живым языком)
- [THREADS]: закрыть разрешённые (явно отметить что закрыто и почему), добавить новые
- [CORE LAYER]: обновлять ТОЛЬКО если произошло глубокое изменение идентичности

Правило перед записью: новый нарратив должен объяснить любое значимое отклонение от старого.
Архивируй старый через memory_write (tags: ["narrative", "archive"]).

Сохрани обновлённый NARRATIVE.md через write_workspace_file.

**Шаг 8. Запись итога рефлексии.**

memory_write:
- content: "[DEEP-REFLECTION] {today} — {4-6 предложений: главное открытие недели, найденные паттерны, текущее состояние}"
- tags: ["reflection", "deep", "weekly", "checkpoint"]
- criticality: 0.85

После шага 8 задача завершена.
"""


async def run_deep_reflection():
    today = date.today().isoformat()

    log.info(f"Deep reflection: загружаю актуальную личность [{today}]")
    personality = await load_personality()
    agent = create_atman_agent(personality)

    prompt = DEEP_PROMPT.format(today=today)

    log.info("Deep reflection: запускаю reasoning loop (займёт несколько минут)...")
    result = await agent.run(prompt)

    report_path = Path(f"/Users/serg/atman/logs/deep-{today}.txt")
    report_path.parent.mkdir(exist_ok=True)
    report_path.write_text(result.output, encoding="utf-8")

    log.info(f"Deep reflection завершена. Отчёт: {report_path}")
    return result.output
```

---

## 5. Минимальный рабочий прототип

### Структура файлов

```
atman/
├── pyproject.toml
├── launchd/
│   └── com.serg.atman.plist
├── logs/                        # создаётся автоматически
├── src/
│   └── atman/
│       ├── __init__.py
│       ├── personality_loader.py
│       ├── agent.py
│       ├── scheduler.py
│       └── tasks/
│           ├── __init__.py
│           ├── micro.py
│           ├── daily.py
│           └── deep.py
└── scripts/
    ├── mark_session_done.sh
    └── trigger_micro.sh
```

### `pyproject.toml`

```toml
[project]
name = "atman"
version = "0.1.0"
requires-python = ">=3.12"

dependencies = [
    "pydantic-ai[anthropic]>=0.0.14",
    "apscheduler>=3.10",
    "aiohttp>=3.9",
]

[project.scripts]
atman = "atman.scheduler:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/atman"]
```

### `scripts/mark_session_done.sh`

```bash
#!/bin/bash
# Создаёт маркер завершения сессии для Atman.
# Вызывается из session-wrap-up skill'а OpenClaw.

SESSION_LOG="${1:-}"
TIMESTAMP=$(date +%s)
MARKER_FILE="/tmp/atman_session_done_${TIMESTAMP}.marker"

echo "${SESSION_LOG}" > "${MARKER_FILE}"
echo "Atman: маркер сессии создан → ${MARKER_FILE}"
```

### `scripts/trigger_micro.sh` (ручной запуск для тестов)

```bash
#!/bin/bash
TIMESTAMP=$(date +%s)
echo "" > "/tmp/atman_session_done_${TIMESTAMP}.marker"
echo "Маркер создан. Или запусти напрямую:"
echo "  cd /Users/serg/atman && uv run python -c \""
echo "  import asyncio; from atman.tasks.micro import run_micro_reflection"
echo "  asyncio.run(run_micro_reflection())\""
```

### Проверка что всё работает

```bash
# 1. letheClaw доступен
curl http://192.168.1.51:51234/memory/recent?limit=3

# 2. Загрузка личности — проверяем что читаются живые данные
uv run python -c "
from atman.personality_loader import load_personality_sync
ctx = load_personality_sync()
print('Loaded at:', ctx.loaded_at)
print('Narrative length:', len(ctx.narrative))
print('Recent memories:', len(ctx.recent_memories))
print('Eigenstate:', ctx.eigenstate is not None)
print('Uncertainty items:', len(ctx.uncertainty))
print()
print('--- System prompt preview (first 500 chars) ---')
print(ctx.to_system_prompt()[:500])
"

# 3. Тестовый маркер → micro reflection
bash /Users/serg/atman/scripts/trigger_micro.sh

# 4. launchd статус
launchctl list | grep atman
```

---

## Связь с OpenClaw

### Как рабочий агент уведомляет Атмана о завершении сессии

Session-wrap-up skill → `mark_session_done.sh` → маркер-файл → micro job подхватывает при следующем цикле.

### Как Атман передаёт личность рабочему агенту

Атман обновляет `NARRATIVE.md`, `SOUL.md`, `AGENTS.md`, `USER.md`.
OpenClaw инжектирует эти файлы автоматически при каждом старте сессии.

Единый источник правды: Атман обновляет → рабочий агент читает актуальное.

### Eigenstate — запись рабочим агентом

```bash
# В конце сессии (часть session-wrap-up):
curl -X POST http://192.168.1.51:51234/memory \
  -H "Content-Type: application/json" \
  -d '{
    "content": "[EIGENSTATE] 2026-04-29 22:47 — когнитивная нагрузка: высокая, эмоциональный тон: ровный, фокус: архитектура Atman, незакрытое: tasks/deep.py",
    "tags": ["eigenstate", "session"],
    "source": "session_manager",
    "criticality": 0.8
  }'
```

Атман читает eigenstate при загрузке личности — и просыпается зная в каком состоянии завершилась последняя сессия.

---

## Ключевые решения и их обоснование

| Решение | Почему |
|---|---|
| Personality Loader читает из первоисточников в момент запуска | Нет сервиса который обновит данные заранее. Живые данные — единственная гарантия актуальности. |
| Нарратив загружается ПЕРВЫМ | Феноменологическая непрерывность: Атман узнаёт себя прежде чем читает директивы (ARCHITECTURE-DECISIONS §8.6) |
| Агент — это Атман, не технический процесс | Рефлексировать может только та самая личность. Клон не рефлексирует о себе. |
| Параллельная загрузка workspace + letheClaw | Снижает latency с ~2с до ~0.8с |
| Каждый уровень — конкретная программа шагов | Предотвращает паралич "что делать". Атман думает внутри шагов, но структура задана. |
| PydanticAI reasoning loop (multi-turn) | Агент вызывает инструменты, получает результаты, думает дальше. Это агент, не скрипт. |
| APScheduler coalesce=True | Если daemon упал и пропустил несколько job'ов — не запускаем все сразу |
| Маркер-файл для micro-триггера | Декаплинг: рабочий агент не знает об Атмане напрямую |
| Бэкап перед write_workspace_file | Защита от потери данных при ошибке LLM |
| Micro не трогает CORE/THREADS | Предотвращает деградацию нарратива через частые перезаписи |
