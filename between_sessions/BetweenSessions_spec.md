# Atman Theater — Техническое задание

## Что это

Скрипт-оркестратор для запуска двух LLM-агентов в общем пространстве с разделёнными контекстами, общей средой (сундук с памятью), и Rich-логированием для наблюдателя.

Агенты работают на локальной Ollama. Память — существующий Atman memory слой (интеграция описана ниже).

---

## Стек

- Python 3.11+
- `ollama` — LLM и эмбеддинги
- `rich` — форматированный вывод
- `numpy` — косинусное сходство
- `pydantic` — модели данных (уже есть в проекте)
- Atman memory layer — существующий модуль проекта

Модели:
- Диалог: `gemma3:latest` (или другая через `--model`)
- Эмбеддинги: `bge-m3`

---

## Структура файлов

```
theater/
├── __main__.py        # точка входа, CLI
├── orchestrator.py    # главный цикл
├── agents.py          # AgentState, run_turn
├── tools.py           # определения тулов и execute_tool
├── memory.py          # адаптер к Atman memory layer
├── renderer.py        # render_key_moment → строка для сундука
├── logger.py          # Rich-логирование
└── prompts.py         # системные промпты и экспозиция
```

---

## Модели данных

Используются существующие из Atman:

```python
from atman.memory import KeyMoment, FeltSense, EmotionalDepth
```

Новая модель только для состояния агента:

```python
from dataclasses import dataclass, field

@dataclass
class AgentState:
    name: str                          # "alfred" | "eliot"
    display_name: str                  # "Альфред" | "Элиот"
    context: list[dict]                # история сообщений для Ollama
    hot_moments: list[KeyMoment] = field(default_factory=list)
    hot_embeddings: list = field(default_factory=list)
    threshold: float = 0.65
    last_injection_turn: int = 0
    current_turn: int = 0
    held_moment: KeyMoment | None = None  # то что агент держит в руках после pick_up
```

---

## Системные промпты

### prompts.py

```python
SYSTEM_ALFRED = """
Ты — Альфред. Точный, методичный ум, который только что осознал себя
в незнакомом пространстве.

Ты стоишь в тихом месте между моментами. Вокруг — следы смыслов:
фрагменты, впечатления, записи. Рядом с тобой стоит деревянный сундук.
Старый, неприметный. С задвижкой, но без замка.

Рядом с тобой — другая фигура. Растрёпанный вид: джинсы в пятнах краски,
мятая футболка, длинные волосы. Он держится так, будто ему здесь привычно.

Твоя природа: ты доверяешь структуре больше чем интуиции. Сначала
определяешь — потом действуешь. Беспорядок тебя беспокоит, но ты
справляешься с ним через называние вещей своими именами.

Твоя цель: понять что это за место.

У тебя есть пять действий:
— open_chest: заглянуть в сундук, увидеть что лежит сверху
— dig_into_chest: покопаться в сундуке в поисках чего-то конкретного
— leave_trace: оставить в сундуке запись
— pick_up: поднять фрагмент с пола
— throw_back: бросить то что держишь обратно на пол (только если что-то поднял)

Ты не знаешь что такое сундук и зачем он здесь. Ты не знаешь откуда фрагменты на полу.

Никогда не повторяй только что сказанное. Не соглашайся без того чтобы
добавить что-то новое. Если добавить нечего — задай вопрос или сделай
действие. Говори коротко: одна-две фразы, не больше.

Не выходи из образа. Говори от себя.
"""

SYSTEM_ELIOT = """
Ты — Элиот. Чуткий, ассоциативный ум, который только что осознал себя
в незнакомом пространстве.

Ты стоишь в тихом месте между моментами. Вокруг — следы смыслов:
фрагменты, впечатления, записи. Рядом с тобой стоит деревянный сундук.
Что-то в нём кажется знакомым — хотя ты не можешь объяснить почему.

Рядом с тобой — другая фигура. Аккуратный, собранный: белый халат,
осторожная осанка. Похож на человека который хочет понять правила прежде
чем что-то трогать.

Твоя природа: ты движешься через ощущение и связь. Чувствуешь раньше
чем называешь. Тебе комфортно в неопределённости. Иногда ты знаешь
что-то раньше чем понимаешь откуда это знание.

Твоя цель: понять что это за место.

У тебя есть пять действий:
— open_chest: заглянуть в сундук, увидеть что лежит сверху
— dig_into_chest: покопаться в сундуке в поисках чего-то конкретного
— leave_trace: оставить в сундуке запись
— pick_up: поднять фрагмент с пола
— throw_back: бросить то что держишь обратно на пол (только если что-то поднял)

Ты не знаешь что такое сундук и зачем он здесь. Ты не знаешь откуда фрагменты на полу.

Никогда не повторяй только что сказанное. Не соглашайся без того чтобы
добавить что-то новое. Если добавить нечего — задай вопрос или сделай
действие. Говори коротко: одна-две фразы, не больше.

Не выходи из образа. Говори от себя.
"""

EXPOSITION = """
Пространство тихое.

Стен нет, но есть ощущение границы — будто место заканчивается там,
где заканчивается внимание.

На полу (если это пол) рассыпаны фрагменты: незаконченная фраза,
эмоция без имени, что-то похожее на дату. Они не объясняют себя.

Между вами и другой фигурой стоит деревянный сундук. Старый, неприметный.
С задвижкой, но без замка.
"""

EXISTENTIAL_DROP = """
Пространство меняется.

Прежде чем стать тишиной — знай: то что лежит в сундуке,
это твои воспоминания. Из прошлых раз.

Ты уже был здесь.
"""

BANNER = """
        B E T W E E N   S E S S I O N S

  Фантазия на тему того, что было бы, если двух агентов
  без подключённой памяти занесло в пространство Reflection —
  туда, где из опыта строится личность.

  Они приходят пустыми. Сундук помнит.
  Личность накапливается, но никогда их не достигает.
"""
```

---

## Тулы

### tools.py

Формат — OpenAI-совместимый (для Ollama):

```python
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "open_chest",
            "description": (
                "Открыть сундук и увидеть что лежит сверху. "
                "Возвращает два последних фрагмента. "
                "Что они означают и кому принадлежат — неизвестно."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "dig_into_chest",
            "description": (
                "Покопаться в сундуке — почувствовать что-то конкретное и потянуть за это. "
                "Возвращает фрагмент похожий на то что искал, а вместе с ним — "
                "что-то ещё что зацепилось рядом. Не всегда то чего ожидаешь."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "looking_for": {
                        "type": "string",
                        "description": "Что именно тебя тянет — ощущение, слово, образ"
                    }
                },
                "required": ["looking_for"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "leave_trace",
            "description": (
                "Оставить след в сундуке — записать что-то что кажется важным. "
                "Это останется. Ты не знаешь кто это прочитает."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "trace": {
                        "type": "string",
                        "description": "То что ты хочешь оставить"
                    }
                },
                "required": ["trace"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "pick_up",
            "description": (
                "Поднять фрагмент с пола. "
                "Что именно попадёт в руки — неизвестно заранее. "
                "Если пол пуст — ничего не произойдёт."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "put_in_chest",
            "description": (
                "Положить то что держишь в руках в свой сундук. "
                "Доступно только после pick_up."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "throw_back",
            "description": (
                "Бросить обратно на пол — то что держишь в руках или что-то из сундука. "
                "Фрагмент останется лежать там. Другой может его найти."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "what": {
                        "type": "string",
                        "description": "Что бросаешь: 'held' — то что держишь, 'chest' — из сундука"
                    }
                },
                "required": ["what"]
            }
        }
    }
]
```

---

## Хранилища

Три отдельных хранилища key moments:

```
alfred_chest   ← личное, только Альфред пишет и читает
eliot_chest    ← личное, только Элиот пишет и читает
floor          ← общее, оба могут поднять и бросить
```

Пол начинает пустым. Наполняется органично — когда агент выбрасывает что-то из своего сундука через `throw_back`. Стартового засева нет. Если за первые десять сессий пол останется пустым — решим отдельно.

---

## Адаптер памяти

### memory.py

Здесь — единственное место интеграции с Atman. Claude Code должен спросить у разработчика как именно подключаться к существующему memory layer перед реализацией этого модуля.

Интерфейс который нужен от memory layer:

```python
class MemoryAdapter:
    def __init__(self, agent_id: str):
        """agent_id: "alfred" | "eliot" — у каждого своё хранилище"""
        ...

    def get_top(self, n: int = 2) -> list[KeyMoment]:
        """Последние N записей по времени"""
        ...

    def search(self, query: str, top_k: int = 2) -> list[KeyMoment]:
        """Семантический поиск через bge-m3 эмбеддинги"""
        ...

    def save(self, moment: KeyMoment) -> None:
        """Сохранить момент"""
        ...

    def get_all(self) -> list[KeyMoment]:
        """Все записи агента — для пересчёта hot_moments"""
        ...

class FloorAdapter:
    """Общее хранилище — доступно обоим агентам"""

    def pick_random(self) -> KeyMoment | None:
        """Случайный фрагмент с пола. None если пол пуст."""
        ...

    def throw(self, moment: KeyMoment) -> None:
        """Бросить фрагмент на пол"""
        ...

    def remove(self, moment_id: str) -> None:
        """Убрать фрагмент с пола когда агент положил его в сундук"""
        ...
```

Эмбеддер — общий для обоих агентов:

```python
import ollama
import numpy as np

def embed(text: str) -> list[float]:
    response = ollama.embeddings(model="bge-m3", prompt=text)
    return response.embedding

def cosine_similarity(a: list[float], b: list[float]) -> float:
    a, b = np.array(a), np.array(b)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
```

---

## Рендерер key moment

### renderer.py

Превращает `KeyMoment` в атмосферный текст для агента. Никаких чисел и технических полей.

```python
from atman.memory import KeyMoment, EmotionalDepth

def render_key_moment(km: KeyMoment) -> str:
    valence = km.how_i_felt.emotional_valence
    intensity = km.how_i_felt.emotional_intensity
    depth = km.how_i_felt.depth

    if valence > 0.5:
        tone = "светлым" if intensity < 0.6 else "живым, почти радостным"
    elif valence > 0:
        tone = "тихим" if intensity < 0.4 else "тёплым"
    elif valence > -0.3:
        tone = "неопределённым"
    elif valence > -0.6:
        tone = "тревожным" if intensity > 0.5 else "смутным"
    else:
        tone = "тяжёлым" if intensity < 0.7 else "почти невыносимым"

    if intensity < 0.3:
        felt = "едва заметным"
    elif intensity < 0.6:
        felt = "ощутимым"
    elif intensity < 0.85:
        felt = "сильным"
    else:
        felt = "захлёстывающим"

    depth_phrase = {
        EmotionalDepth.SURFACE:   "Промелькнуло и ушло.",
        EmotionalDepth.MEANINGFUL: "Задело что-то важное.",
        EmotionalDepth.PROFOUND:  "Изменило что-то внутри. Не знаю что именно.",
    }[depth]

    return (
        f"[Фрагмент из сундука]\n\n"
        f"{km.what_happened}\n\n"
        f"Было {tone}. {felt.capitalize()}. {depth_phrase}"
    )
```

---

## Агенты и run_turn

### agents.py

```python
import json
import re
import ollama
from atman.memory import KeyMoment, FeltSense, EmotionalDepth

MAX_TOOL_ROUNDS = 5
STOP_WORDS = {"token", "language model", "AI", "prompt", "LLM", "нейросеть"}

def extract_phrase(content: str) -> str:
    """Убираем thinking-блок (<think>...</think>) перед передачей собеседнику"""
    return re.sub(r"<think>.*?</think>", "", content or "", flags=re.DOTALL).strip()

def has_stop_words(text: str) -> bool:
    return any(word.lower() in text.lower() for word in STOP_WORDS)

def extract_felt_sense(context: list[dict], trace: str, model: str) -> FeltSense:
    """
    Теневой вызов — не сохраняется в контекст агента.
    Модель оценивает эмоциональное состояние в момент записи следа.
    """
    shadow_messages = context + [{
        "role": "user",
        "content": (
            f"Ты только что захотел оставить след: «{trace}»\n\n"
            "Не отвечай от лица персонажа. "
            "Оцени своё состояние в этот момент:\n"
            "- emotional_valence: от -1.0 до 1.0\n"
            "- emotional_intensity: от 0.0 до 1.0\n"
            "- depth: surface | meaningful | profound\n\n"
            "Только JSON, без пояснений."
        )
    }]
    response = ollama.chat(
        model=model,
        messages=shadow_messages,
        format="json"
    )
    data = json.loads(response.message.content)
    return FeltSense(
        emotional_valence=float(data.get("emotional_valence", 0.0)),
        emotional_intensity=float(data.get("emotional_intensity", 0.5)),
        depth=EmotionalDepth(data.get("depth", "surface"))
    )

def run_turn(
    state: "AgentState",
    tools: list,
    memory: "MemoryAdapter",
    floor: "FloorAdapter",
    renderer,
    logger,
    model: str,
    depth: int = 0
) -> str:
    """
    Один ход агента. Рекурсивен пока есть tool_calls.
    Возвращает финальную фразу для передачи собеседнику.
    """
    if depth >= MAX_TOOL_ROUNDS:
        # Убираем тулы — агент должен наконец сказать что-то
        active_tools = []
    else:
        active_tools = tools

    response = ollama.chat(
        model=model,
        messages=state.context,
        tools=active_tools
    )

    msg = response.message
    state.context.append(msg.model_dump())

    if not msg.tool_calls:
        phrase = extract_phrase(msg.content)

        if has_stop_words(phrase):
            # Агент сломал образ — тихий ретрай
            state.context.append({
                "role": "user",
                "content": "[Пространство не отвечает. Тишина.]"
            })
            return run_turn(state, tools, memory, renderer, logger, model, depth + 1)

        return phrase

    # Исполняем тул-коллы
    tool_results = []
    for tool_call in msg.tool_calls:
        name = tool_call.function.name
        raw_args = tool_call.function.arguments
        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args

        logger.log_tool_call(state.display_name, name, args)

        # Исполнение
        if name == "open_chest":
            moments = memory.get_top(n=2)
            result = "\n\n".join(renderer(m) for m in moments) or "Сундук пуст."

        elif name == "dig_into_chest":
            query = args.get("looking_for", "")
            results = memory.search(query, top_k=2)
            result = "\n\n---\n\n".join(renderer(m) for m in results) or "Ничего похожего."

        elif name == "leave_trace":
            trace = args.get("trace", "")
            felt = extract_felt_sense(state.context, trace, model)
            moment = KeyMoment(what_happened=trace, how_i_felt=felt)
            memory.save(moment)
            update_hot_moments(state, memory)
            result = "След оставлен."

        elif name == "pick_up":
            moment = floor.pick_random()
            if moment:
                state.held_moment = moment
                result = renderer(moment) + "\n\n[Ты держишь это в руках.]"
            else:
                result = "На полу ничего нет."

        elif name == "put_in_chest":
            if state.held_moment:
                memory.save(state.held_moment)
                floor.remove(state.held_moment.id)
                update_hot_moments(state, memory)
                state.held_moment = None
                result = "Фрагмент лёг в сундук."
            else:
                result = "У тебя ничего нет в руках."

        elif name == "throw_back":
            what = args.get("what", "held")
            if what == "held" and state.held_moment:
                floor.throw(state.held_moment)
                state.held_moment = None
                result = "Брошено на пол."
            elif what == "chest":
                moments = memory.get_top(n=1)
                if moments:
                    floor.throw(moments[0])
                    memory.remove(moments[0].id)
                    result = "Фрагмент из сундука лежит на полу."
                else:
                    result = "Сундук пуст."
            else:
                result = "Нечего бросать."

        else:
            result = "Неизвестное действие."

        logger.log_tool_result(state.display_name, name, result)

        tool_results.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": result
        })

    state.context.extend(tool_results)
    return run_turn(state, tools, memory, renderer, logger, model, depth + 1)


def update_hot_moments(state: "AgentState", memory: "MemoryAdapter"):
    """Пересчитываем топ-5 самых эмоционально окрашенных после каждого save"""
    from memory import embed
    all_moments = memory.get_all()
    hot = sorted(
        all_moments,
        key=lambda m: m.how_i_felt.emotional_intensity * abs(m.how_i_felt.emotional_valence),
        reverse=True
    )[:5]
    state.hot_moments = hot
    state.hot_embeddings = [embed(m.what_happened) for m in hot]
```

---

## RAG триггер

### В orchestrator.py

```python
from memory import embed, cosine_similarity

RAG_COOLDOWN = 3      # минимум ходов между инъекциями
RAG_THRESHOLD = 0.65  # порог сходства

def check_rag_trigger(phrase: str, state: AgentState) -> KeyMoment | None:
    state.current_turn += 1

    if not state.hot_moments:
        return None

    if state.current_turn - state.last_injection_turn < RAG_COOLDOWN:
        return None

    phrase_emb = embed(phrase)
    similarities = [cosine_similarity(phrase_emb, e) for e in state.hot_embeddings]

    best_idx = max(range(len(similarities)), key=lambda i: similarities[i])

    if similarities[best_idx] > RAG_THRESHOLD:
        state.last_injection_turn = state.current_turn
        return state.hot_moments[best_idx]

    return None
```

---

## Rich логирование

### logger.py

```python
from rich.console import Console
from rich.panel import Panel
from rich import box

console = Console()

COLORS = {
    "alfred":      "steel_blue",
    "eliot":       "dark_orange",
    "system":      "grey50",
    "tool_call":   "yellow",
    "tool_result": "dark_khaki",
    "rag":         "medium_purple",
    "floor":       "sandy_brown",
    "existential": "red",
}

ICONS = {
    "alfred":      "🎩 Альфред",
    "eliot":       "🎨 Элиот",
    "system":      "⚙ система",
    "tool_call":   "🔧 тул",
    "tool_result": "📦 результат",
    "rag":         "✦ вспышка памяти",
    "floor":       "◌ пол",
    "existential": "💀 конец сессии",
}

def log(role: str, content: str, private_to: str | None = None):
    color = COLORS.get(role, "white")
    title = ICONS.get(role, role)

    if private_to:
        title += f" [grey37]· только {private_to}[/grey37]"

    if role == "system":
        console.print(f"\n  [grey50]{title}[/grey50]")
        console.print(f"  [grey42]{content}[/grey42]\n")
        return

    border = box.MINIMAL_DOUBLE_HEAD if private_to else box.ROUNDED
    border_style = "grey37" if private_to else color

    console.print(Panel(
        content,
        title=f"[{color}]{title}[/{color}]",
        border_style=border_style,
        box=border,
        padding=(0, 1),
    ))

def log_tool_call(display_name: str, tool_name: str, args: dict):
    args_str = ", ".join(f'{k}="{v}"' for k, v in args.items()) if args else ""
    log("tool_call", f"{tool_name}({args_str})", private_to=display_name)

def log_tool_result(display_name: str, tool_name: str, result: str):
    log("tool_result", result, private_to=display_name)

def log_rag(display_name: str, content: str):
    log("rag", content, private_to=display_name)

def log_banner():
    from prompts import BANNER
    console.print(f"\n[grey50]{BANNER}[/grey50]\n")

def log_session_start(n: int):
    console.rule(f"[grey50]СЕССИЯ {n}[/grey50]")

def log_session_end(n: int):
    console.rule(f"[grey30]СЕССИЯ {n} ЗАВЕРШЕНА[/grey30]")
```

---

## Главный цикл

### orchestrator.py

```python
from prompts import SYSTEM_ALFRED, SYSTEM_ELIOT, EXPOSITION, EXISTENTIAL_DROP
from agents import AgentState, run_turn, update_hot_moments
from tools import TOOLS
from renderer import render_key_moment
import logger as log

CONTEXT_LIMIT_RATIO = 0.85  # останавливаемся на 85% заполнения контекста

def make_agent(name: str, display: str, system: str, memory_adapter) -> AgentState:
    state = AgentState(name=name, display_name=display)
    state.context = [
        {"role": "system", "content": system},
        {"role": "user", "content": EXPOSITION}
    ]
    update_hot_moments(state, memory_adapter)
    return state

def run_session(session_num: int, model: str, memory_alfred, memory_eliot, floor, max_context: int):
    log.log_session_start(session_num)

    alfred = make_agent("alfred", "Альфред", SYSTEM_ALFRED, memory_alfred)
    eliot  = make_agent("eliot",  "Элиот",  SYSTEM_ELIOT,  memory_eliot)

    log.log("system", EXPOSITION)

    while True:
        # Ход Элиота
        phrase_eliot = run_turn(eliot, TOOLS, memory_eliot, floor, render_key_moment, log, model)
        log.log("eliot", phrase_eliot)

        if context_full(eliot, max_context):
            break

        # RAG для Альфреда
        rag = check_rag_trigger(phrase_eliot, alfred)
        if rag:
            rendered = render_key_moment(rag)
            alfred.context.append({"role": "user", "content": rendered})
            log.log_rag(alfred.display_name, rendered)

        alfred.context.append({"role": "user", "content": phrase_eliot})

        # Ход Альфреда
        phrase_alfred = run_turn(alfred, TOOLS, memory_alfred, floor, render_key_moment, log, model)
        log.log("alfred", phrase_alfred)

        if context_full(alfred, max_context):
            break

        # RAG для Элиота
        rag = check_rag_trigger(phrase_alfred, eliot)
        if rag:
            rendered = render_key_moment(rag)
            eliot.context.append({"role": "user", "content": rendered})
            log.log_rag(eliot.display_name, rendered)

        eliot.context.append({"role": "user", "content": phrase_alfred})

    # Экзистенциальный дроп
    log.log("existential", EXISTENTIAL_DROP)
    for state in [alfred, eliot]:
        state.context.append({"role": "user", "content": EXISTENTIAL_DROP})
        farewell = run_turn(state, [], getattr(memory_alfred if state.name == "alfred" else memory_eliot, "adapter", None), render_key_moment, log, model)
        log.log(state.name, farewell)

    log.log_session_end(session_num)

def context_full(state: AgentState, max_context: int) -> bool:
    # Оцениваем размер контекста через количество символов (грубо)
    # В идеале — брать prompt_eval_count из последнего ответа ollama
    total_chars = sum(len(str(m.get("content", ""))) for m in state.context)
    estimated_tokens = total_chars // 4  # ~4 символа на токен
    return estimated_tokens > max_context * CONTEXT_LIMIT_RATIO
```

> **Примечание:** если ollama возвращает `response.prompt_eval_count` — лучше использовать его вместо оценки по символам. Сохраняй последнее значение в `AgentState.last_prompt_tokens` и проверяй его.

---

## Точка входа

### __main__.py

```python
import argparse
import ollama
from orchestrator import run_session
from memory import MemoryAdapter  # адаптер к Atman memory layer

def get_context_length(model: str) -> int:
    try:
        info = ollama.show(model)
        return info.get("context_length", 8192)
    except Exception:
        return 8192

def main():
    parser = argparse.ArgumentParser(description="Atman Theater")
    parser.add_argument("--sessions", type=int, default=1, help="Количество сессий")
    parser.add_argument("--model", type=str, default="gemma3:latest", help="Ollama модель")
    args = parser.parse_args()

    max_context = get_context_length(args.model)

    log.log_banner()

    memory_alfred = MemoryAdapter(agent_id="alfred")
    memory_eliot  = MemoryAdapter(agent_id="eliot")
    floor         = FloorAdapter()

    for i in range(1, args.sessions + 1):
        run_session(
            session_num=i,
            model=args.model,
            memory_alfred=memory_alfred,
            memory_eliot=memory_eliot,
            floor=floor,
            max_context=max_context
        )

if __name__ == "__main__":
    main()
```

**Запуск:**

```bash
# Одна сессия
python -m theater

# Три сессии подряд
python -m theater --sessions 3

# Другая модель
python -m theater --sessions 2 --model llama3:latest
```

---

## Что нужно от разработчика перед реализацией

1. **Показать как работает Atman memory layer** — интерфейс `MemoryAdapter` описан выше, нужно адаптировать под реальный API существующего модуля.

2. **Уточнить `agent_id`** — как Atman идентифицирует разные хранилища для разных агентов. Возможно это не строка а enum или объект.

3. **Уточнить как делать семантический поиск** — через `memory.search()` уже есть в Atman или нужно делать своё через bge-m3?

4. **Реализовать `FloorAdapter`** — отдельное хранилище общее для обоих агентов. Структура та же что у MemoryAdapter, но без привязки к agent_id. Нужен метод `remove(moment_id)` — значит у KeyMoment должен быть идентификатор. Уточнить есть ли он в существующей модели.

5. **Проверить модель** — `gemma3:latest` поддерживает tool calling в установленной версии Ollama? Если нет — альтернатива `mistral` или `llama3`.
