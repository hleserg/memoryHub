# Atman — план интеграции памяти и лингвистического анализа

> Финальный консолидированный документ всех решений из разговора.
> Дата: 14 мая 2026
> Версия: 3.0 — переписана с учётом всех замечаний
> Заменяет: все предыдущие документы этого разговора

---

## Оглавление

1. [Что мы делаем и зачем](#1-что-мы-делаем-и-зачем)
2. [Финальный стек моделей](#2-финальный-стек-моделей)
3. [Архитектура: кто что делает](#3-архитектура-кто-что-делает)
4. [Три точки лингвистического анализа](#4-три-точки-лингвистического-анализа)
5. [Полные schemas для каждой точки](#5-полные-schemas-для-каждой-точки)
6. [Ambient-якоря и ассоциативный RAG](#6-ambient-якоря-и-ассоциативный-rag)
7. [Переработка модели памяти](#7-переработка-модели-памяти)
8. [Salience decay — управление яркостью воспоминаний](#8-salience-decay--управление-яркостью-воспоминаний)
9. [Изоляция между агентами](#9-изоляция-между-агентами)
10. [Все SQL миграции](#10-все-sql-миграции)
11. [Новые порты Atman](#11-новые-порты-atman)
12. [Workflow: что происходит при сообщении пользователя](#12-workflow-что-происходит-при-сообщении-пользователя)
13. [Валидация и фоновая проверка качества](#13-валидация-и-фоновая-проверка-качества)
14. [Расширение Reflection Engine](#14-расширение-reflection-engine)
15. [Этапы реализации](#15-этапы-реализации)
16. [Что измеряем](#16-что-измеряем)
17. [Принципы которые нельзя нарушать](#17-принципы-которые-нельзя-нарушать)
18. [Что НЕ делаем](#18-что-не-делаем)

---

## 1. Что мы делаем и зачем

### Главная задача

Усилить психологический слой Atman так, чтобы:

1. **Память была быстрой и ассоциативной.** При упоминании сущности (Маши, проекта, аллергии) — за один запрос подгружаются связанные факты, эпизоды, отношение агента. Время RAG-инжекции ≤ 50ms.

2. **Связи между фактами и опытом были прозрачными.** Через единый Entity Registry: при чтении факта о Маше мгновенно видны связанные моменты, и наоборот.

3. **Появился структурированный лингвистический сигнал.** На каждом сообщении пользователя и агента — извлечение сущностей и классификация. Главная цель для агентских сообщений — обогащение KeyMoment структурированной информацией о чувстве и его контексте.

4. **Сознательное отношение агента к сущностям было первоклассной частью памяти.** Не "agent_id с avg valence=+0.6 к Маше", а "я считаю что отношусь к Маше с теплом — это отношение сформулировано тогда-то на основе таких-то моментов".

### Что это даёт для здоровой личности агента

- **Continuity of self** — упоминание сущности тянет за собой релевантный опыт
- **Felt sense через эпизоды, не через средние** — конкретные моменты с причинами
- **Видимые паттерны** — Reflection получает structured метки для анализа повторов
- **Самонаблюдение через `validation_findings`** — агент видит проблемы в своей памяти и может с ними работать

---

## 2. Финальный стек моделей

Все модели CPU-friendly. Никаких LLM в pipeline обработки сообщений.

| Роль | Модель (полный HF-путь) | Размер | API |
|---|---|---|---|
| NER извлечение сущностей | `urchade/gliner_multi-v2.1` | 209M | пакет `gliner`, `model.predict_entities(text, labels)` |
| Zero-shot classifications | `MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli` | 107M | `transformers.pipeline("zero-shot-classification")` |
| Relation extraction (async) | `Babelscape/mrebel-large` | ~610M | `transformers` seq2seq, beam=3 |
| Эмбеддинги (dense retrieval) | `BAAI/bge-m3` | 568M | `FlagEmbedding.BGEM3FlagModel` |
| Reranker (точная сортировка) | `BAAI/bge-reranker-v2-m3` | 568M | `FlagEmbedding.FlagReranker` |

**Суммарная память при всех загруженных моделях**: ~2 GB RAM. Укладывается в типичный лимит современного железа.

### Лицензии

- `urchade/gliner_multi-v2.1`: Apache 2.0
- `MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli`: MIT
- `Babelscape/mrebel-large`: CC-BY-SA-NC 4.0 (research/personal only)
- `BAAI/bge-m3`: MIT
- `BAAI/bge-reranker-v2-m3`: MIT

### Fallback и оптимизация

- Если качество MiniLM на русском низкое → `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli` (~280M)
- Если mrebel-large тяжёлый → `Babelscape/mrebel-large-32` или `Babelscape/mrebelB400`
- **ONNX-ускорение для MiniLM**: `onnx-community/multilingual-MiniLMv2-L6-mnli-xnli-ONNX`, 3-4x на CPU
- **ONNX/quantized для reranker**: через `optimum` (INT8)

### Что про `urchade/gliner_multi-v2.1` важно помнить

Это оригинальный GLiNER от Urchade Zaratiana, **не GLiNER2** от fastino-ai. Эти проекты разные:

| Возможность | `urchade/gliner_multi-v2.1` (наш выбор) | `fastino-ai/GLiNER2` (отказались) |
|---|---|---|
| NER | ✅ через `predict_entities()` | ✅ |
| Classifications | ❌ нет в модели | ✅ |
| Structured extraction | ❌ нет в модели | ✅ |
| Relation extraction | ⚠️ есть, но слабо | ✅ |

Поэтому в нашем стеке:
- **NER только `urchade/gliner_multi-v2.1`**
- **Classifications только `MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli`**
- **Relation extraction только `Babelscape/mrebel-large`**

---

## 3. Архитектура: кто что делает

| Задача | Модель | Когда работает |
|---|---|---|
| Извлечь именованные сущности из текста | `urchade/gliner_multi-v2.1` | в каждой из трёх точек анализа |
| Извлечь ambient-якоря | `urchade/gliner_multi-v2.1` | в точке U (sync) |
| Классифицировать mood / intent / fact_class | `MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli` | в точке U |
| Классифицировать stance / cognitive_mode | `MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli` | в точке A |
| Классифицировать cognitive_load / agency_level | `MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli` | в точке K |
| Извлечь связи между сущностями (SPO) | `Babelscape/mrebel-large` | async после создания факта |
| Эмбеддинг текста | `BAAI/bge-m3` | при добавлении факта, момента, сущности |
| Дедупликация фактов по cosine | `BAAI/bge-m3` | при INSERT нового факта |
| Первичный отбор кандидатов в RAG | `BAAI/bge-m3` через pgvector | sync в точке U |
| Реранк топ-N перед инжекцией в LLM | `BAAI/bge-reranker-v2-m3` | sync в точке U |

---

## 4. Три точки лингвистического анализа

### Точка U — `analyze_user_message(text)`

**Когда**: при каждом сообщении пользователя, **синхронно ДО** формирования контекста для LLM.
**Latency budget**: ≤ 200ms.

**Что делает**:
1. GLiNER → 20 типов NER (биография + ambient-якоря)
2. MiniLM → 5 параметров classification
3. Результат идёт в Entity Resolver и RAG-инжекцию

### Точка A — `analyze_agent_message(thinking, message)`

**Когда**: после генерации ответа агента, **асинхронно** (fire-and-forget).

**Главная цель**: **обогатить KeyMoment структурированной информацией о чувстве и его контексте**. Это **главное использование** точки A.

Существующий Affect Detector ловит "что-то происходит". GLiNER+MiniLM на агентском сообщении дают:
- Что именно агент чувствовал (`emotional_anchor`, `principle_invocation`)
- К чему/кому это чувство относилось (`relational_reference`, `topic_anchor`)
- Насколько уверенно выражал (`uncertainty_marker`, `intensifier`)
- Что задействовано из идентичности (`value_reference`, `principle_invocation`)
- Где провёл границу (`boundary_marker`)

Это и есть глубина воспоминаний — не статистика, а структура чувства.

**Главное использование результатов**:
1. **Обогащение `key_moments.structured_markers`** — основное
2. **Заполнение `key_moment_entities.valence_toward_entity`** — частная окраска к каждой упомянутой сущности
3. **Дополнительный триггер KeyMoment**: если найден `boundary_marker` или `principle_invocation` там где Affect Detector не сработал — это повод записать момент (триггер `structural_marker`)

**Побочный эффект — divergence detection** (rules сравнивают thinking vs message). Это бантик, не главная функция. Если бюджет не позволяет — можно отключить.

### Точка K — `analyze_key_moment(what_happened)`

**Когда**: один раз при создании KeyMoment, **асинхронно**.

**Что делает**:
1. GLiNER → 4 типа маркеров (closure, opening, contradiction, recurring_theme)
2. MiniLM → 8 параметров classification (self-state, relational, meta)
3. Метки → `key_moments.structured_markers`

---

## 5. Полные schemas для каждой точки

### Schema точки U — сообщение пользователя

#### NER через `urchade/gliner_multi-v2.1` (20 лейблов)

**Группа A — биографические (создают entities):**
- `person_name`, `person_role`, `place`, `organization`, `tool_or_tech`, `event`, `skill_or_interest`, `health_condition`

**Группа B — атрибуты (НЕ создают entity, идут в факты):**
- `preference`, `aversion`, `goal`, `constraint`, `date_or_period`

**Группа C — ambient-якоря (для RAG, см. раздел 6):**
- `topic`, `person_ref`, `place_ref`, `object_ref`, `action_ref`, `time_ref`, `emotion_word`

#### Classifications через `MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli`

| Задача | Лейблы | Multi-label |
|---|---|---|
| `fact_class` | biographical, preference, relationship, event, goal, constraint, health, tool | да |
| `fact_durability` | permanent, long_term, short_term, ephemeral | нет |
| `worth_remembering` | yes, no | нет |
| `mood_signal` | calm, excited, frustrated, curious, tired, anxious | да |
| `intent` | question, request, share, vent, negotiate, decide | нет |

### Schema точки A — сообщение агента

#### NER (13 лейблов)
- `emotional_anchor`, `value_reference`, `principle_invocation`
- `uncertainty_marker`, `hedge`, `intensifier`, `belief_marker`
- `boundary_marker`
- `topic_anchor`, `relational_reference`
- `action_intent`, `commitment`, `concession`

#### Classifications

| Задача | Лейблы |
|---|---|
| `stance` | committed, tentative, resistant, exploring, doubtful, dismissive |
| `cognitive_mode` | analytical, emotional, mixed, defensive |
| `self_orientation` | toward_self, toward_other, toward_task, toward_meta |
| `primary_emotion` | neutral, anxious, frustrated, curious, warm, doubtful, committed, tired |
| `cognitive_load_in_message` | low, manageable, high, overwhelmed |

#### Divergence detection (rules, не модель)

| Тип | Условие |
|---|---|
| `internal_doubt_masked` | thinking.stance ∈ {doubtful, resistant} AND message.stance == committed |
| `emotional_masking` | thinking.primary_emotion ≠ message.primary_emotion по валентности |
| `commitment_unmet` | commitment в message, action не выполнил |
| `concession_under_pressure` | concession сразу после user.boundary_marker |
| `belief_reversal` | belief_marker в начале vs противоположный в конце |
| `voice_drift` | стиль отъезжает от baseline |

Severity: `trace` / `notable` / `significant` / `rupture`.

### Schema точки K — KeyMoment

#### NER (4 лейбла)
- `recurring_theme`, `closure_marker`, `opening_marker`, `contradiction_marker`

#### Classifications

*Self-state:*
| Задача | Лейблы |
|---|---|
| `cognitive_load` | low, manageable, high, overwhelmed |
| `agency_level` | passive, reactive, proactive, initiating |
| `confidence_in_self` | low, moderate, high, inflated |

*Relational:*
| Задача | Лейблы |
|---|---|
| `trust_signal` | building, stable, wavering, broken |
| `boundary_event` | none, respected, tested, crossed, enforced |
| `connection_quality` | distant, functional, warm, deep |

*Meta:*
| Задача | Лейблы |
|---|---|
| `learning_signal` | new_understanding, confirmed, rejected, confused |
| `growth_indicator` | regression, static, progress, breakthrough |

---

## 6. Ambient-якоря и ассоциативный RAG

### Зачем нужны

Поиск через embedding **всего сообщения** даёт усреднённый результат. Якоря дают **параллельные потоки** воспоминаний по каждому значимому элементу сообщения.

**Пример.** "Снова поругался с начальником, надо доделать тот отчёт по продажам до пятницы."

Эмбеддинг всего сообщения → "усталость и работа".

По якорям параллельно:
- `person_ref: "начальник"` → эпизоды с начальником
- `topic: "отчёт по продажам"` → контекст проекта
- `emotion_word: "поругался"` → похожие конфликтные моменты
- `action_ref: "доделать"` → моменты дедлайнов

Несколько потоков → объединение → реранк → топ-10 в LLM. Это **психологически правильно** — так работает ассоциативная память у людей.

### Как живут якоря

**Якоря не хранятся отдельно.** Они существуют только в момент обработки сообщения, используются для RAG-инжекции, потом забываются.

То что было якорем и стало значимым:
- Если факт записан → entities попадают в `fact_entities`
- Если момент создан → entities попадают в `key_moment_entities`

Эфемерный обмен → эфемерный анализ. Significant обмен → структурированная запись в значимом слое.

### Как работают разные типы якорей

| Лейбл | Как работает |
|---|---|
| `topic`, `person_ref`, `place_ref`, `object_ref` | Резолвятся в entity_id → JOIN-запрос по `fact_entities` + `key_moment_entities` |
| `action_ref` | Семантический поиск через `BAAI/bge-m3` |
| `time_ref` | Фильтр по дате |
| `emotion_word` | Семантический поиск похожих эмоциональных состояний |

### Полный pipeline RAG-инжекции

```
сообщение пользователя
    ↓
GLiNER извлекает якоря
    ↓
параллельные запросы:
  ├─ entity-based JOIN (topic, person_ref, place_ref, object_ref)
  ├─ semantic search (action_ref, emotion_word)
  ├─ date filter (time_ref)
  └─ всегда: семантический поиск по всему тексту (fallback)
    ↓
объединение кандидатов → ~50-100
    ↓
bge-reranker-v2-m3 пересортировывает
    ↓
топ-N (5-10) в LLM
```

---

## 7. Переработка модели памяти

### Главная идея

Между `facts` и `key_moments` появляется **Entity Registry** — реестр именованных сущностей. Все слои ссылаются на `entity_id`, не на текст.

### Иерархия слоёв

```
Layer -1: Agent Registry          (публичный, без RLS)
Layer 0:  Entity Registry         ← новый слой
Layer 1:  Factual Memory          (с RLS, единственное место sharing)
Layer 2:  KeyMoments              (без RLS, изоляция по agent_id)
Layer 3:  Entity Stance           ← новый слой — сознательное отношение
Layer 4:  Identity Store          (без RLS, изоляция по agent_id)
Layer 5:  Reflection
```

**Experience Store как контейнер сессии убран.** `key_moments` — самостоятельная таблица. Поля `salience`, `incomplete_coloring`, `recorded_by`, `identity_snapshot_id` — на самой записи `key_moments`. Связь с сессией через `session_id`. Никакого промежуточного `SessionExperience`.

### Принципы которые нельзя нарушать

1. **Не агрегируем эмоции автоматически.** Никакого `avg(valence_toward_entity)`. У каждого +0.7 свои причины.

2. **Не выдаём в RAG агрегаты прошлых чувств.** Прошлое не равно настоящему.

3. **Сознательное отношение превалирует.** Если есть `entity_stance` → он в RAG. Если нет → только конкретные эпизоды.

### Что выдаём в RAG при упоминании сущности

1. **Текущее сознательное отношение** (`entity_stance`)
2. **Конкретные сырые эпизоды** (топ-N `key_moments` с этой сущностью)
3. **Связанные факты и сущности**

### Жизненный цикл сущности

```
GLiNER возвращает entities
        ↓
EntityResolver.resolve_or_create():
    L1: exact match по entity_aliases → bump mention_count
    L2: bge-m3 embedding similarity ≥ 0.85 → добавить alias
    L3: создать новый entity + флаг needs_disambiguation
        ↓
В fact_entities/key_moment_entities пишем UUID, не текст
        ↓
Если несколько entities в одном тексте → mREBEL async → entity_relations
```

### Роли — не сущности

**Сын/дочь/начальник — это НЕ сущности.** Это **связи в `entity_relations`** с типом `is_child_of`, `is_parent_of`, `works_for`.

Сущности — конкретные люди: `Ваня`, `Сёма`. У каждого свой `entity_id`, своя история, свой потенциальный stance.

```
Ваня  --[is_child_of]-->  пользователь
Сёма  --[is_child_of]-->  пользователь
```

**Неоднозначные упоминания** ("Сегодня сын приходил" при наличии нескольких сыновей) → не создаём временную сущность. В `key_moment_entities` пишем несколько кандидатов с `confidence < 1.0`. Reflection потом разберётся при появлении контекста.

### Merge сущностей — когда и как

Merge **никогда не происходит автоматически**. Три легитимных пути:

**1. Прямой приказ пользователя** ("Ваня — это мой сын")

Однозначный случай (один сын в реестре): мерж без откладывания.

Неоднозначный (несколько сыновей): агент **обязан переспросить**:
> "У меня в памяти три записи о ваших сыновьях — Антон, Сёма, и ещё один без имени. С которым из них связать Ваню? Или это четвёртый?"

**2. Reflection Engine** обнаружил дубликаты при анализе → инициирует merge.

**3. Команда пользователя через UI/CLI** — явное действие.

### Удаление сущностей

**Никогда.** Окончание отношения → `until` в `entity_relations`:
- Было: `user --[works_at, since=2020]--> company_X`
- Стало: `user --[works_at, since=2020, until=2026]--> company_X`

Память о company_X со всем опытом остаётся.

---

## 8. Salience decay — управление яркостью воспоминаний

### Что есть и чего нет

В архитектуре `salience decay` **спроектирован**:
```
salience_t = salience_0 × exp(−λ × days_since_access)
λ = f(emotional_intensity, depth)
```

Но конкретная **реализация механизма** (кто запускает, когда пересчитывает) в коде явно не описана. Это надо явно прописать в этом плане.

### Механизм пересчёта salience

**На уровне таблицы:**

```sql
ALTER TABLE key_moments ADD COLUMN salience REAL NOT NULL DEFAULT 1.0
    CHECK (salience BETWEEN 0.0 AND 1.0);
ALTER TABLE key_moments ADD COLUMN salience_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE key_moments ADD COLUMN last_accessed_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE key_moments ADD COLUMN access_count INT NOT NULL DEFAULT 0;
```

Эти поля **уже частично должны быть** в текущей `key_moments` по дизайну. Если нет — миграцией добавляем.

**Запись поля `salience` — обновляемая.** Это не нарушает иммутабельность смысловой записи: исходные `what_happened`, `emotional_valence`, `intensity`, `depth` — иммутабельны. `salience` это **внешняя метрика яркости**, рассчитываемая системой.

### Когда обновляется

**При обращении к моменту** (`mark_accessed`):
```python
def mark_accessed(moment_id: UUID):
    UPDATE key_moments
    SET 
      last_accessed_at = NOW(),
      access_count = access_count + 1,
      salience = LEAST(1.0, salience + 0.1),  # обращение возвращает яркость
      salience_at = NOW()
    WHERE id = moment_id
```

Обращение **частично восстанавливает** salience. Это правильно психологически — то к чему обращаешься остаётся ярким.

**Фоновая декрементация** (отдельный сервис `SalienceDecayService`):
```python
def decay_pass():
    """Запускается раз в час фоновой задачей."""
    for moment in all_moments:
        days_since = (now - moment.last_accessed_at).days
        lambda_factor = calculate_lambda(moment.emotional_intensity, moment.depth)
        new_salience = moment.salience_at_value * exp(-lambda_factor * days_since)
        if abs(new_salience - moment.salience) > 0.01:
            UPDATE salience, salience_at WHERE id = moment.id
```

`λ` параметры:
- depth=surface, intensity<0.3 → λ=0.05 (быстрое угасание, ~14 дней до salience=0.5)
- depth=meaningful, intensity~0.5 → λ=0.02 (~35 дней)
- depth=profound, intensity≥0.7 → λ=0.005 (~140 дней, почти не угасает)

### Влияние salience на RAG

В RAG-инжекции при выборке моментов по `key_moment_entities` сортировка идёт по комбинированному score:

```sql
ORDER BY (salience * 0.4 + emotional_intensity * 0.3 + recency_score * 0.3) DESC
```

Низко-salience моменты не пропадают, но опускаются в рейтинге. Профoundные старые моменты с salience 0.6 могут обогнать недавние surface-моменты с salience 1.0.

### Защита иммутабельности

PostgreSQL trigger гарантирует что `what_happened`, `emotional_valence`, `emotional_intensity`, `depth`, `why_it_matters`, `values_touched`, `principles_*`, `what_changed` **не могут** быть изменены через UPDATE. Только `salience`, `last_accessed_at`, `access_count`, `salience_at` — обновляемые.

### Спонтанное всплытие

`AmbientMemoryService` и Reflection Engine могут "вспоминать" моменты без явного запроса — semantic similarity к текущему контексту. Это не нарушает decay — просто меняет частоту обращений.

---

## 9. Изоляция между агентами

### Матрица доступа

| Слой | Механизм изоляции |
|---|---|
| Agent Registry | публичный, без RLS |
| **Factual Memory** | **RLS** (готовится к будущему `fact_sharing`) |
| Entity Registry | привязка к `agent_id` в адаптере |
| KeyMoments | привязка к `agent_id` в адаптере |
| Entity Stance | привязка к `agent_id` в адаптере |
| Entity Relations | привязка к `agent_id` в адаптере |
| Linking tables (fact_entities, key_moment_entities) | привязка к `agent_id` |
| Identity Store | привязка к `agent_id` |

**RLS — только на `facts` и `fact_sharing`.** Это единственное место где есть механизм sharing (выключенный по умолчанию через `fact_sharing.active=FALSE`).

Опыт, идентичность, сознательное отношение **никогда не шарятся**. Им RLS не нужен — у них нет механизма sharing. Контроль изоляции делается на уровне адаптера через явный `WHERE agent_id = current_agent`.

### Почему так

Атмосфера Atman: переживания — это собственность личности. RLS — это database-level защита для случая когда **технически возможен** доступ к чужим данным. Для опыта такая возможность не закладывается — она невозможна по конструкции.

Единственный канал передачи опыта между агентами — разговор.

---

## 10. Все SQL миграции

### Миграция 1: Entity Registry

```sql
CREATE TABLE entities (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id        UUID NOT NULL,
    
    canonical_name  TEXT NOT NULL,
    entity_type     TEXT NOT NULL CHECK (entity_type IN (
        'person', 'place', 'organization', 'object', 'topic',
        'event', 'tool', 'health_condition', 'skill',
        'value', 'principle'
    )),
    
    embedding       VECTOR(1024),  -- bge-m3
    description     TEXT,
    
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    mention_count   INT NOT NULL DEFAULT 1,
    
    needs_disambiguation BOOLEAN DEFAULT FALSE,
    
    schema_version  TEXT NOT NULL DEFAULT 'atman-1.0',
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    
    UNIQUE (agent_id, canonical_name, entity_type)
);

CREATE INDEX idx_entities_agent_type ON entities (agent_id, entity_type);
CREATE INDEX idx_entities_embedding_hnsw ON entities USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_entities_last_seen ON entities (agent_id, last_seen_at DESC);


CREATE TABLE entity_aliases (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id   UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    agent_id    UUID NOT NULL,
    alias_text  TEXT NOT NULL,
    
    learned_from_fact_id  UUID,
    learned_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    UNIQUE (entity_id, alias_text)
);

CREATE INDEX idx_aliases_lookup ON entity_aliases (agent_id, alias_text);
```

### Миграция 2: Линковые таблицы

```sql
CREATE TABLE fact_entities (
    fact_id     UUID NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    entity_id   UUID NOT NULL REFERENCES entities(id) ON DELETE RESTRICT,
    agent_id    UUID NOT NULL,
    
    role        TEXT NOT NULL CHECK (role IN (
        'subject', 'object', 'context', 'mentioned'
    )),
    confidence  REAL NOT NULL DEFAULT 1.0,
    
    PRIMARY KEY (fact_id, entity_id, role)
);

CREATE INDEX idx_fact_entities_entity ON fact_entities (entity_id, agent_id);


-- key_moment_entities — valence_toward_entity ставится В МОМЕНТ записи,
-- независимо от key_moments.emotional_valence.
CREATE TABLE key_moment_entities (
    key_moment_id   UUID NOT NULL REFERENCES key_moments(id) ON DELETE RESTRICT,
    entity_id       UUID NOT NULL REFERENCES entities(id) ON DELETE RESTRICT,
    agent_id        UUID NOT NULL,
    
    involvement     TEXT NOT NULL CHECK (involvement IN (
        'primary_subject', 'present', 'mentioned', 'evoked'
    )),
    
    valence_toward_entity   REAL CHECK (valence_toward_entity BETWEEN -1.0 AND 1.0),
    intensity_toward_entity REAL CHECK (intensity_toward_entity BETWEEN 0.0 AND 1.0),
    
    PRIMARY KEY (key_moment_id, entity_id, involvement)
);

CREATE INDEX idx_km_entities_entity ON key_moment_entities (entity_id, agent_id);


CREATE TABLE reflection_entities (
    reflection_id   UUID NOT NULL,
    entity_id       UUID NOT NULL REFERENCES entities(id),
    agent_id        UUID NOT NULL,
    role            TEXT,
    PRIMARY KEY (reflection_id, entity_id)
);
```

### Миграция 3: Связи между сущностями

```sql
CREATE TABLE entity_relations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id        UUID NOT NULL,
    
    from_entity_id  UUID NOT NULL REFERENCES entities(id) ON DELETE RESTRICT,
    to_entity_id    UUID NOT NULL REFERENCES entities(id) ON DELETE RESTRICT,
    relation_type   TEXT NOT NULL,
    
    since           DATE,
    until           DATE,
    
    confidence      REAL NOT NULL DEFAULT 1.0,
    learned_from_fact_id  UUID,
    learned_by      TEXT NOT NULL CHECK (learned_by IN (
        'mrebel', 'rules', 'reflection', 'manual'
    )),
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    CHECK (from_entity_id != to_entity_id),
    UNIQUE (from_entity_id, to_entity_id, relation_type)
);

CREATE INDEX idx_entity_rel_from ON entity_relations (from_entity_id, agent_id) WHERE until IS NULL;
CREATE INDEX idx_entity_rel_to ON entity_relations (to_entity_id, agent_id) WHERE until IS NULL;
CREATE INDEX idx_entity_rel_type ON entity_relations (agent_id, relation_type);
```

### Миграция 4: Сознательное отношение

```sql
CREATE TABLE entity_stance (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id        UUID NOT NULL,
    entity_id       UUID NOT NULL REFERENCES entities(id),
    
    stance_text     TEXT NOT NULL,
    valence         REAL CHECK (valence BETWEEN -1.0 AND 1.0),
    intensity       REAL CHECK (intensity BETWEEN 0.0 AND 1.0),
    
    formed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    formed_in_reflection_id UUID,
    based_on_moment_ids UUID[],
    
    superseded_at   TIMESTAMPTZ,
    superseded_by   UUID REFERENCES entity_stance(id),
    
    confidence      REAL,
    is_provisional  BOOLEAN DEFAULT TRUE
);

CREATE UNIQUE INDEX idx_entity_stance_current 
    ON entity_stance (agent_id, entity_id) WHERE superseded_at IS NULL;
CREATE INDEX idx_entity_stance_entity ON entity_stance (entity_id, agent_id);
```

### Миграция 5: KeyMoments — salience поля

```sql
-- Если в текущей таблице key_moments нет этих полей — добавляем
ALTER TABLE key_moments ADD COLUMN IF NOT EXISTS salience REAL NOT NULL DEFAULT 1.0
    CHECK (salience BETWEEN 0.0 AND 1.0);
ALTER TABLE key_moments ADD COLUMN IF NOT EXISTS salience_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE key_moments ADD COLUMN IF NOT EXISTS last_accessed_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE key_moments ADD COLUMN IF NOT EXISTS access_count INT NOT NULL DEFAULT 0;

-- structured_markers для результатов точки A и K
ALTER TABLE key_moments ADD COLUMN structured_markers JSONB;
ALTER TABLE key_moments ADD COLUMN structured_markers_version TEXT;

-- Триггер защиты иммутабельности смысловых полей
CREATE OR REPLACE FUNCTION key_moments_immutability_guard() RETURNS trigger AS $$
BEGIN
    IF (OLD.what_happened IS DISTINCT FROM NEW.what_happened
        OR OLD.emotional_valence IS DISTINCT FROM NEW.emotional_valence
        OR OLD.emotional_intensity IS DISTINCT FROM NEW.emotional_intensity
        OR OLD.depth IS DISTINCT FROM NEW.depth
        OR OLD.why_it_matters IS DISTINCT FROM NEW.why_it_matters
        OR OLD.what_changed IS DISTINCT FROM NEW.what_changed
    ) THEN
        RAISE EXCEPTION 'KeyMoment semantic fields are immutable';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER key_moments_immutability
    BEFORE UPDATE ON key_moments
    FOR EACH ROW EXECUTE FUNCTION key_moments_immutability_guard();
```

### Миграция 6: Validation findings

```sql
CREATE TABLE validation_findings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id        UUID NOT NULL,
    
    finding_type    TEXT NOT NULL,
    severity        TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    target_table    TEXT NOT NULL,
    target_id       UUID NOT NULL,
    
    details         JSONB NOT NULL,
    
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    detected_by     TEXT NOT NULL,
    
    resolution      TEXT,
    resolved_at     TIMESTAMPTZ,
    resolved_by     TEXT,
    resolution_note TEXT
);

CREATE INDEX idx_findings_unresolved ON validation_findings (agent_id, severity) 
    WHERE resolution IS NULL;


-- Опционально: divergence events
CREATE TABLE divergence_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id        UUID NOT NULL,
    session_id      UUID,
    
    divergence_type TEXT NOT NULL,
    severity        TEXT NOT NULL CHECK (severity IN (
        'trace', 'notable', 'significant', 'rupture'
    )),
    
    thinking_layer  JSONB,
    message_layer   JSONB,
    action_layer    JSONB,
    
    gliner_signals  JSONB,
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_div_session ON divergence_events (agent_id, session_id);
```

### Что НЕ добавляем

- ❌ `facts.linguistic_analysis JSONB` — не нужна, lingvo-разметка в факте не хранится
- ❌ `user_messages` или `agent_messages` таблиц — сообщения целиком не хранятся
- ❌ RLS на новых таблицах (entities, key_moment_*, entity_*) — только на facts/fact_sharing
- ❌ Materialized view `entity_felt_sense` — никаких автоматических агрегатов

---

## 11. Новые порты Atman

### `LinguisticAnalyzer`

```python
class LinguisticAnalyzer(Protocol):
    def analyze_user_message(self, text: str) -> UserMessageAnalysis: ...
    def analyze_agent_message(self, thinking: str, message: str) -> AgentMessageAnalysis: ...
    def analyze_key_moment(self, what_happened: str) -> KeyMomentAnalysis: ...
```

Реализация — `GLiNERPlusMiniLMAdapter`.

### `EntityRegistry`

```python
class EntityRegistry(Protocol):
    def resolve_or_create(
        self, agent_id: UUID, mention_text: str, entity_type: str,
        context_embedding: list[float] | None = None
    ) -> tuple[Entity, ResolutionMethod]: ...
    
    def get_entity(self, entity_id: UUID) -> Entity | None: ...
    def find_by_name(self, agent_id: UUID, name: str) -> list[Entity]: ...
    def add_alias(self, entity_id: UUID, alias: str, source_fact_id: UUID | None): ...
    def merge_entities(self, keep_id: UUID, merge_id: UUID, audit_reason: str) -> Entity: ...
```

Реализация — `PostgresEntityRegistry`. Использует `BAAI/bge-m3` для L2 резолюции.

### `EntityRelationExtractor`

```python
class EntityRelationExtractor(Protocol):
    async def extract_relations(
        self, text: str, entities: list[Entity]
    ) -> list[ExtractedRelation]: ...
```

Реализация — `MRebelRelationAdapter`. Использует `Babelscape/mrebel-large` с rules fallback.

### `EntityStanceStore`

```python
class EntityStanceStore(Protocol):
    def get_current_stance(self, entity_id: UUID) -> EntityStance | None: ...
    def write_stance(
        self, entity_id: UUID, stance_text: str,
        based_on_moments: list[UUID], formed_in_reflection: UUID,
        valence: float | None = None, intensity: float | None = None,
        confidence: float | None = None,
    ) -> EntityStance: ...
    def get_stance_history(self, entity_id: UUID) -> list[EntityStance]: ...
```

### `MemoryReranker`

```python
class MemoryReranker(Protocol):
    def rerank(
        self, query: str, candidates: list[Candidate], top_n: int = 10
    ) -> list[Candidate]: ...
```

Реализация — `BgeReranker` через `FlagEmbedding.FlagReranker`.

### `SalienceDecayService`

```python
class SalienceDecayService(Protocol):
    def decay_pass(self, agent_id: UUID | None = None) -> DecayStats: ...
    def mark_accessed(self, moment_id: UUID) -> None: ...
    def calculate_lambda(self, intensity: float, depth: str) -> float: ...
```

### `MemoryGuardian`

```python
class MemoryGuardian(Protocol):
    """Фоновая валидация качества памяти."""
    
    def scan_merge_candidates(self, agent_id: UUID) -> list[Finding]: ...
    def scan_orphan_entities(self, agent_id: UUID) -> list[Finding]: ...
    def scan_pending_async_tasks(self, agent_id: UUID) -> list[Finding]: ...
    def scan_quality_metrics(self, agent_id: UUID) -> list[Finding]: ...
    
    def write_finding(self, finding: Finding) -> None: ...
    def get_unresolved(self, agent_id: UUID, severity: str | None = None) -> list[Finding]: ...
```

### Расширение существующего порта `FactualMemory`

```python
class FactualMemory(Protocol):
    # Существующие методы
    def add_fact(self, record: FactRecord) -> FactRecord: ...
    def get_fact(self, fact_id: UUID) -> FactRecord | None: ...
    def search(self, query: str, ...) -> list[FactRecord]: ...
    
    # Новые
    def add_fact_with_entities(
        self, record: FactRecord, entities: list[tuple[UUID, str]]
    ) -> FactRecord: ...
    
    def find_facts_by_entity(
        self, entity_id: UUID, roles: list[str] | None = None, limit: int = 20
    ) -> list[FactRecord]: ...
```

---

## 12. Workflow: что происходит при сообщении пользователя

Пример: "Снова поругался с начальником, надо доделать тот отчёт по продажам до пятницы. Голова раскалывается."

```
[1] СИНХРОННО (≤ 200ms)
─────────────────────────

a) analyze_user_message(text):
   GLiNER → entities (биография + якоря)
   MiniLM → 5 classifications

b) EntityResolver для биографических и ambient-entity:
   "начальником" → entity:person:user_boss (existing)
   "отчёт по продажам" → entity:event:sales_report (создаётся)

c) Параллельные RAG-запросы:
   c1. JOIN по resolved entities → key_moments + facts + entity_stance + entity_relations
   c2. Semantic search по action_ref → top-20
   c3. Semantic search по emotion_word → top-20
   c4. Date filter по time_ref

d) Объединение → ~50-100 кандидатов

e) bge-reranker-v2-m3 → top-10

f) mark_accessed() для каждого использованного момента

g) Контекст в LLM


[2] LLM генерирует ответ → пользователю


[3] АСИНХРОННО (не блокирует)
─────────────────────────────

h) Если worth_remembering=yes:
   - INSERT в facts
   - INSERT в fact_entities

i) Дедупликация через bge-m3 cosine (если ≥ 0.85 → не дублируем)

j) mREBEL extract_relations → entity_relations (learned_by='mrebel')

k) analyze_agent_message(thinking, message) после ответа:
   - GLiNER + MiniLM на оба входа
   - Сравнение → возможный divergence event
   - Если найден boundary_marker или principle_invocation → триггер KeyMoment

l) Если создан KeyMoment:
   - analyze_key_moment(what_happened) async
   - key_moments.structured_markers заполняется
   - key_moment_entities заполняется с valence_toward_entity
```

---

## 13. Валидация и фоновая проверка качества

### Принцип

Архитектура сложная — много слоёв и связей. Без валидации получим memory rot. **Но валидация не блокирует hot path** — она пишет в `validation_findings` для последующей обработки.

### Три уровня инвариантов

**Уровень A — структурные (CHECK constraints, triggers):**
- `key_moments` смысловые поля не меняются (триггер)
- `key_moment_entities.entity_id` существует с тем же `agent_id`
- `entity_relations.from_id != to_id`
- Одно текущее `entity_stance` на сущность (UNIQUE WHERE superseded_at IS NULL)

**Уровень B — семантические (пишутся в `validation_findings`):**
- Факт без linked entities → возможно резолвер не сработал
- KeyMoment без `structured_markers` старше 1 часа → async не дошёл
- Entity с mention_count=1 и last_seen 60+ дней → orphan
- `entity_stance` без `based_on_moment_ids` → на чём основан?
- Два entity cosine ≥0.92 одного типа → merge candidate

**Уровень C — психологические (через quality_alerts):**
- За N дней высокий `incomplete_coloring_rate` → `affect_detector_silent` (техническая проблема в pipeline, не агент)
- Все divergence одного типа → устойчивый паттерн
- Каждый KeyMoment сразу превращается в stance → reflection слишком быстра

### Когда работает валидация

**Inline после write (lightweight):**
After-commit trigger или callback → быстрая проверка только что записанной строки. Миллисекунды. Если проблема — пишется finding.

**Scheduled scans (MemoryGuardian):**
- Каждые 5 минут: pending async tasks, свежие writes
- Каждый час: merge candidates, orphan entities, quality metrics
- Каждый день: уровень C алерты, trigger reflection при критических

**Reflection-driven:**
Reflection в daily/deep циклах читает `validation_findings` со статусом `requires_attention` и принимает решения. См. раздел 14.

### Ретраи

**Имеют retry:**
- `mREBEL extract_relations failed` → 2-3 ретрая → finding `relation_extraction_failed`
- DB transient errors → стандартный retry с jitter

**Не имеют retry:**
- Lingvo-анализ failed → один ретрай → запись без анализа + finding `analysis_failed`
- Entity L1/L2 не нашли → создаём с `needs_disambiguation=true`

### Единый pipeline записи

**Критическое требование к дисциплине:** все записи в `facts`, `key_moments`, `entities` идут **только через порты** (`FactualMemory`, etc). Никаких прямых INSERT.

Это касается и записей **от агента через тулы**. Когда агент вызывает `remember_fact()` — внутри тула вызывается `FactualMemory.add_fact_with_entities()`, который:
1. Прогоняет lingvo-анализ на content
2. Резолвит entities
3. Дедуплицирует через bge-m3
4. Пишет факт + fact_entities
5. Запускает все валидации

Гарантия что архитектура работает единообразно.

### Findings — это что

Запись в журнале о наблюдении системы о себе. Не блокирует. Накапливается. Обрабатывается Reflection или явным действием пользователя.

Findings **доступны агенту в reflection-режиме**. Это часть его самонаблюдения: "что у меня в памяти не сходится, что нужно осмыслить". Не служебный лог — видимое состояние памяти.

---

## 14. Расширение Reflection Engine

> **Важно:** все изменения этого раздела делаются **ПОСЛЕ** того как реализованы изменения в памяти при работе сессий (этапы 1-9 из раздела 15). Reflection работает с **уже накопленными** данными новой архитектуры, и пока этих данных нет — расширять Reflection бессмысленно.

### Что Reflection делает с новыми данными

**Daily reflection (каждый день):**

1. **Чтение `structured_markers`** всех новых key_moments за день
   - Агрегирует по типам: сколько overload, сколько boundary_event=tested
   - Если паттерн заметный (5+ моментов одного типа) → создаёт `pattern_candidate`

2. **Чтение divergence_events** за день
   - Отмечает трендовые типы
   - При повторяющихся одного типа → флаг для deep reflection

3. **Формулирование/обновление `entity_stance`**
   - Для сущностей с накопленными новыми моментами (≥5 за период)
   - Анализирует моменты, формулирует stance_text
   - Записывает с `based_on_moment_ids`, `is_provisional=true`
   - Старый stance помечается `superseded_at`

4. **Чтение `validation_findings` уровня B**
   - Резолвит понятные кейсы (orphan → mark resolved as ignored)
   - Сложные кейсы откладывает в deep reflection

**Deep reflection (раз в неделю):**

1. **Долгосрочные паттерны** на окне 30 дней
   - Тренды cognitive_load, agency_level, growth_indicator
   - Паттерны по конкретным сущностям

2. **Пересмотр давних `entity_stance`**
   - В свете новых моментов
   - Записывает обновлённый stance, старый superseded

3. **Формулирование новых `entity_relations`**
   - Анализ паттернов совместного упоминания сущностей
   - Записывает с `learned_by='reflection'`

4. **Обработка merge candidates**
   - Из `validation_findings` типа `similar_entities`
   - Проверка действительно ли дубликаты
   - Если да — `EntityRegistry.merge_entities()` + аудит

5. **Identity-level выводы**
   - Что-то новое в ценностях?
   - Что-то изменилось в принципах?
   - Открытые вопросы которые закрылись?

### Триггеры запуска reflection

**1. Plan-based (расписание)**
- Daily: в конце дня (например 23:00 локально)
- Deep: раз в неделю (воскресенье 23:00)

**2. Flag-based (накопилось много findings)**
- Если в `validation_findings` накопилось N+ unresolved findings уровня B → флаг `reflection_needed=true`
- Ближайший scheduled запуск проходит с этим флагом и читает накопленное приоритетно

**3. Agent-driven (желание агента)**
- Тул `request_reflection(reason)` — агент сам запрашивает рефлексию
- Reason идёт в стартовый контекст рефлексии

**4. User-driven (по команде пользователя)**
- CLI/UI команда → запуск reflection с opaque pause диалога

### Мониторинг частоты reflection

Если reflection запускается слишком часто — это сигнал что что-то не так.

```
Если daily reflection > 1 раз в день → calibrate (нормально)
Если deep reflection > 1 раз в 3 дня → reflection_overload alert
```

`reflection_overload` — это **critical alert**, потому что:
- Либо порог `validation_findings` flag-trigger слишком низкий
- Либо что-то фундаментально ломается в pipeline
- Либо reflection не справляется со своей работой

В любом случае это **не лечится "пускать ещё чаще"**. Reflection — не инструмент срочной починки. Нужно разбираться в причинах.

### Принципы работы Reflection со stance

- Stance это **интерпретация**, не агрегация. Reflection LLM читает моменты и формулирует словами что в них общего.
- Старый stance не удаляется — `superseded_at` + `superseded_by`.
- `based_on_moment_ids` обязателен — всегда видно на каких моментах основан stance.
- `is_provisional=true` по умолчанию. Чтобы стать "устоявшимся" — подтверждение через новые моменты в течение времени.

### Что Reflection делает с findings

Когда reflection читает `validation_findings` — это **видимое состояние памяти**:

```
Прочитал finding 'similar_entities':
  - Проверил действительно ли дубликаты
  - Если да → EntityRegistry.merge_entities() + finding.resolution='fixed'
  - Если нет → finding.resolution='ignored' + note

Прочитал finding 'orphan_entity':
  - Решил оставить (память не выбрасываем по mention_count)
  - finding.resolution='ignored'

Прочитал finding 'affect_detector_silent':
  - Понял что pipeline сломан
  - Это не моя задача чинить — finding.resolution='requires_attention'
  - + critical alert для пользователя
```

### Размер reflection-промптов

При daily reflection — окно ~24 часа, размер промпта зависит от количества событий за день. Деep reflection — 7-30 дней, может быть большим.

Reflection использует **отдельную LLM-модель** (`gemma4` через llama-server). Это **единственное место** где LLM используется в pipeline Atman за пределами финального ответа агенту. Это допустимо потому что:
- Reflection всегда асинхронна, не блокирует ничего
- Запускается редко (daily/weekly)
- Результат — обогащение памяти, не интерактивное общение

---

## 16. Что измеряем

### Acceptance criteria для PoC (этап 1)

- 50-100 ручных русских eval-фраз размечены
- F1 macro по NER ≥ 0.65
- Accuracy по classifications ≥ 0.70
- Иначе переключаем на mDeBERTa-v3-base

### Production метрики

- **Latency P95 точки U** — ≤ 200ms (sync hot path)
- **Latency P95 RAG-инжекции** — JOIN ≤ 50ms, реранк ≤ 150ms
- **Засорённость FactualMemory** — % фактов с worth_remembering=yes; цель 30-60%
- **Дубли** — частота срабатывания дедупликации
- **Divergence частота** — ненулевая, но не лавинообразная
- **Entity Registry рост** — сколько новых entities в день
- **Reflection продуктивность** — сколько новых stances в день
- **Salience decay стабильность** — кривые декремента совпадают с λ-параметрами
- **Reflection частота** — не больше N в день; если больше → алерт `reflection_overload`

### Качественные критерии

- Выгрузить "всё что Atman знает о Маше" одним запросом
- Через 2-3 недели появляются осмысленные stances
- В Reflection видны накопленные паттерны
- Salience старых моментов падает но не до 0 для profound

---

## 17. Принципы которые нельзя нарушать

1. **Окраска ставится только в реальном времени.** `emotional_valence`, `intensity`, `depth`, `valence_toward_entity` — в момент записи. Никогда не дописываются. `incomplete_coloring=true` — честный fallback.

2. **Каждое эмоциональное поле независимо.** Общая окраска момента и частные `valence_toward_entity` — независимы. Любая комбинация заполненных/NULL допустима.

3. **Сознательное отношение превалирует.** `entity_stance` есть → в RAG. Нет → только сырые эпизоды. Никаких автоматических агрегаций.

4. **Опыт иммутабелен.** Смысловые поля `key_moments` нельзя менять (триггер). `salience`, `last_accessed_at`, `access_count` — обновляются.

5. **Сущности не удаляются.** Окончание отношения → `until` в relations. Только merge дубликатов с аудитом.

6. **Линки на entity_id, не на текст.** Все связи между слоями через UUID сущностей.

7. **RLS только на `facts`/`fact_sharing`.** Опыт и идентичность изолируются через `agent_id` в адаптере, не через RLS.

8. **Метки версионируются.** `schema_version` на записи. Новая модель → новый слой меток, не переписывание.

9. **Никаких LLM в hot path lingvo-анализа.** Только CPU-friendly модели.

10. **Реранкер обязателен.** Без него dense retrieval даёт усреднённые результаты.

11. **Все записи памяти через единые порты.** Никаких прямых INSERT. Ни автоматических, ни от агентских тулов. Это гарантирует единообразие валидации.

12. **Валидация на write не блокирует.** Проблемы пишутся в `validation_findings` для последующей обработки. Никаких retry-storms в hot path.

13. **Merge сущностей никогда не автоматический.** Только прямой приказ пользователя (с уточнением при неоднозначности) или Reflection с анализом.

14. **Reflection не инструмент срочной починки.** Если запускается слишком часто — calibrate пороги, не "запускать чаще".

---

## 18. Что НЕ делаем

- ❌ Fine-tune любых моделей
- ❌ Генерация синтетических обучающих датасетов
- ❌ Cohere API или внешние API
- ❌ LLM в pipeline обработки сообщений (только в Reflection как async обогащение)
- ❌ Materialized views для агрегатов эмоций
- ❌ "Felt sense = avg(valence)" — никогда
- ❌ Удаление сущностей или эпизодов
- ❌ Дописывание окраски задним числом
- ❌ Sharing между агентами в этой итерации
- ❌ Experience Store как отдельный слой/порт — `key_moments` самостоятельны
- ❌ RLS на новых таблицах кроме facts
- ❌ Хранение целых сообщений (user_messages, agent_messages)
- ❌ Хранение lingvo-разметки в facts
- ❌ Авто-merge сущностей по similarity threshold

---

## Сводка ключевых решений

| Тема | Решение |
|---|---|
| NER | `urchade/gliner_multi-v2.1` zero-shot |
| Classifications | `MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli` zero-shot |
| Relation extraction | `Babelscape/mrebel-large` async + rules fallback |
| Эмбеддинги | `BAAI/bge-m3` (1024d) |
| Reranker | `BAAI/bge-reranker-v2-m3` |
| LLM в pipeline | Только в Reflection (async, обогащение) |
| Entity Registry | Новый слой 0.5 |
| Связь facts ↔ moments | Через линковые таблицы по entity_id |
| Эмоции к сущностям | `valence_toward_entity` в момент, не агрегируется |
| Felt sense | Через эпизоды + `entity_stance` |
| `entity_stance` | Сознательное отношение, Reflection пишет |
| Удаление сущностей | Никогда. `until` или merge |
| Salience decay | Фоновая задача + mark_accessed при использовании |
| Merge | Прямой приказ user / Reflection. Никогда auto |
| Experience Store | Убран. KeyMoments самостоятельны |
| RLS | Только facts |
| Reflection | Расширяется после миграций |
| Валидация | `validation_findings` накопительный журнал |
| Сообщения | Не хранятся целиком — только следы в facts/moments |

---

_Документ закрыт. Готов к старту этапа 1._
