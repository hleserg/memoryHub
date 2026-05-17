# Skill Manager — дизайн

Документ собран по итогам разговора. Это **не WP-08 в исходном виде** — спека сильно переосмыслена. Основные сдвиги от исходного 08-skill-manager.md:

- скиллы — не пакетный менеджер файлов, а полноценный слой с интеграцией в память (entity), RAG, рефлексию
- decay по времени убран; вместо него — validation по результатам использования
- лайфцикл: lazy install при первом триггере, авто-пин по статистике, авто-даунгрейд по простою
- два пути рождения скилла: in-session (агент сам упаковал автоматизацию) и на рефлексии (паттерн из experience)
- внешние скиллы — отдельный origin, ставятся только по явному запросу юзера
- multi-agent изоляция: technical assets — global+RLS, subjective stuff — per-agent
- **формат скиллов — Agent Skills Open Standard** (Anthropic, открыт в начале 2026, поддерживается Claude Code, Cursor, OpenAI Codex, GitHub Copilot, Gemini CLI и 25+ другими агентами). Atman-specific поля живут в `metadata.atman` namespace. Это даёт совместимость: скиллы Atman'а работают в любом совместимом агенте, внешние скиллы из экосистемы — в Atman.
- **Skill-loop опционален** — отключается через `atman.skills.enabled = false`, не блокирует остальные компоненты

---

## 1. Концепция

**Skill** — переиспользуемый способ действовать. Это совокупность исполняемых артефактов (Python-скрипты, конфиги, прочие executable files) и инструкций как этим пользоваться. Скилл рождается из конкретного успешного опыта и живёт как entity в памяти.

Скилл — это **не**:
- факт (factual memory)
- принцип (identity)
- сырой опыт (experience store)

Скилл — это **что я умею делать, чтобы не переоткрывать это каждый раз**.

### Жизненный цикл

```
created (draft) → active → [auto-pinned | user-pinned] ←→ on-demand
                                                         ↓
                                                      disabled (manual)
                                                         ↓
                                                      revision_needed (auto flag)
```

Скилл **не удаляется автоматически по времени**. Он либо помогает (success_count растёт), либо нет (failure_count → флаг `revision_needed` на рефлексии). Юзер явно запретил → `disabled`. Авто-удаления нет. Архив — только через governance review на deep reflection.

### Происхождение

```
origin: in_session | reflection_pattern | external
```

- **in_session** — агент во время сессии написал автоматизацию и вызвал `atman.skills.capture()`. Карточка пишется сразу как draft.
- **reflection_pattern** — Reflection Engine увидел паттерн в experience, упаковал. Code-артефактов может не быть, только концепт и инструкция; код собирается потом.
- **external** — юзер принёс репозиторий с github. Только по явному запросу.

---

## 2. Виды скиллов и режимы вызова

### Kind (kind)

- **active** — триггерится по результату анализа сообщений юзера (тот же NLP/lingua-pipeline что используется для passive memory + RAG). Триггер выдаёт suggestion агенту: «вот подходящий скилл».
- **passive** — работает без явного решения агента. Автоматическая обработка фоном (auto-format, auto-cite, etc.). Триггерится по типу события, не по сообщению юзера.

### Status (status)

- **draft** — только что создан in-session, ещё не пересматривался. Карточка может быть некачественной. После N успешных использований — на рефлексии перейдёт в `active`.
- **active** — нормальный рабочий скилл.
- **disabled** — юзер сказал «так больше не делай». Не предлагается, не вызывается, не подтягивается. Файлы и история сохраняются. Включить обратно — только явным юзер-запросом (или через будущую админку).

### Pinning

Два независимых флага:

- **`user_pinned: bool`** — юзер явно сказал «пусть всегда будет». Священный. Авто-даунгрейд никогда не трогает.
- **`auto_pinned: bool`** — система запинила по статистике использования.

Если `user_pinned=true` ИЛИ `auto_pinned=true` → скилл попадает в bootstrap каждой сессии (по имени, без полной карточки).

### Auto-pin / auto-downgrade пороги

Default-значения (в конфиг агента):

- **Auto-pin:** ≥ 3 использования за последние 10 сессий → `auto_pinned=true`
- **Auto-downgrade:** 20 сессий без использования → `auto_pinned=false` (только для `auto_pinned`, юзерский пин неприкосновенен)

Считается на micro reflection (см. §6).

---

## 3. Скилл как entity в памяти

Скилл — это **entity типа `skill:<name>`** в per-agent entity store. Это ключевое решение, оно снимает половину проблем «как агент узнаёт что у него есть скиллы».

### Что это даёт

- Скилл связан с experience (ключевые моменты успешного/неудачного использования)
- Скилл связан с facts (подтверждённые знания об инструменте: грабли, ограничения, комбо)
- Скилл связан с другими entity («Сергей», «розетка-1», «домашняя сеть»)
- При RAG-инъекции пассивной памяти связанные скиллы приходят естественно вместе с темой разговора

### Чего НЕ нужно делать

- ❌ Лить список всех скиллов в каждый системный промпт
- ❌ Спрашивать у юзера установку скиллов которые агент сам для себя написал
- ❌ Подтягивать скиллы независимым каналом параллельно памяти

### Что льётся в bootstrap

Только pinned скиллы — список имён + одна строка описания на каждый:

```
У тебя на постоянной основе доступны навыки:
- smart-outlet-control: управление умными розетками через домашнюю сеть
- session-wrap-up: финализация сессии с маркером для micro reflection
- ...
Карточки этих навыков — твои собственные заметки. Если нужны подробности — запроси память.
Остальные навыки приходят сами когда становятся релевантны теме разговора.
```

Это решает проблему «агент должен знать обо всём что он умеет» — pinned всегда на виду, on-demand приходят через RAG по entity-связям.

---

## 4. Retrieve через отдельный канал

При сборке контекста перед ответом агента (там где сейчас отрабатывает passive memory + RAG) **скиллы тянутся отдельным каналом**, не смешиваются с общим top-K entity/facts.

Почему отдельно: иначе в горячий момент релевантный скилл утонет за тремя свежими фактами про Сергея. Скиллы должны быть видны router'у предсказуемо.

### Структура context-builder'а

```
Запрос юзера
     ↓
NLP/lingua анализ → embedding + intent
     ↓
[Memory retriever]         [Skill retriever]
top-K entity/facts          top-K skill entities
с реранком                  со своим порогом
     ↓                              ↓
              Context assembly:
              - pinned skills (всегда)
              - retrieved skills (по релевантности)
              - memory/facts (как обычно)
              - experience (как обычно)
```

Pinned скиллы — поверх результатов retrieve'а, всегда. Retriever работает только для on-demand.

### Кэширование внутри сессии

При первом триггере скилла X в сессии — подтягивается карточка + 2-3 ключевых момента использования. В session_state помечается `skill:X.context_loaded=true`. Дальше в той же сессии — только имя скилла и факт что он доступен, без повторной загрузки опыта.

**Один раз на каждый скилл** — не один раз на сессию всего.

---

## 5. Триггер-роутер

Что решает «вот этот скилл сейчас релевантен»? Два механизма последовательно:

### MVP — embedding similarity + keyword rules

1. `SKILL.toml` декларирует `triggers.keywords` и `triggers.embedding_anchors`
2. По эмбеддингу юзерского запроса считается similarity с anchors
3. Параллельно — простая проверка keyword match
4. Если confidence > порога (в манифесте: `min_confidence`) → скилл попадает в suggestion'ы

### Будущее — small tool-use model

Когда соберём — отдельная маленькая модель (типа needle/function-gemma) принимает на вход (user message, список доступных скиллов с карточками) и возвращает ранжированный список с confidence. Контракт `SkillSuggestion` остаётся тот же, меняется только реализация router'а.

### SkillSuggestion

Стандартизированная структура того что router отдаёт агенту:

```
SkillSuggestion {
  skill_id: str
  card_text: str         # короткая выжимка из CARD.md
  confidence: float      # 0..1
  reason: str            # «matched keyword "розетка"», «high semantic similarity»
  strength: enum         # suggest | strong-suggest
}
```

Три силы предложения:

- **passive auto-invoke** — фоном, агент даже не знает (для `kind=passive`)
- **suggest** — «вот скилл, может пригодится», агент решает
- **strong-suggest** — высокий confidence + высокий success rate, «почти точно нужно использовать»

---

## 6. Интеграция в reflection lifecycle

Скилл-loop расслаивается по трём уровням рефлексии, которые уже зафиксированы в архитектуре:

### Micro (после каждой сессии)

Триггерится через `atman_session_done_<ts>.marker`. Цель — обработать факты использования скиллов в этой сессии, без интерпретаций и identity-changes.

**Что делает:**

- Проходит по `skill_invocations` сессии
- Ставит `final_status` каждому вызову по иерархии сигналов (см. §7)
- Инкрементит `success_count` / `failure_count` на скилле
- Создаёт `KeyMoment` со ссылкой на entity скилла если был значимый вызов
- Инкрементит `sessions_since_use` для всех pinned-скиллов, не использованных в этой сессии
- Пересчитывает auto-pin / auto-downgrade пороги, меняет флаги
- Ставит флаг `revision_needed=true` если в этой сессии скилл провалился. **Не пересматривает карточку.**

### Daily

**Что делает:**

- Если у скилла несколько провалов за день подряд → поднимает `revision_priority`
- Может пересобрать `CARD.md` если накопилось ≥5 новых кейсов и нет конфликтов между ними
- Снимает статус `draft` если скилл успешно отработал заданное число раз
- Не удаляет и не запрещает ничего

### Deep

**Что делает:**

- Разбор `revision_needed` скиллов: пересматривает CARD.md, или предлагает архивировать (через governance review, не сам)
- Паттерны через скиллы: «эти три часто вызываются вместе → объединить?»
- Выявление новых скилл-кандидатов из паттернов experience (origin=reflection_pattern)
- Может предложить переклассификацию `passive` ↔ `active`

---

## 7. Invocation lifecycle и определение «помог/не помог»

Wrap-up в Atman = micro reflection. Это **асинхронный** фоновой проход, **не интерактивная пауза**. Значит вердикт «помог скилл или нет» нужно собирать **только из того что осталось в логах**.

### Фаза 1 — момент вызова

Когда агент дёргает `atman.skills.invoke(skill_id, args)`:

```
skill_invocations row:
  session_id, skill_id, started_at,
  input_context_summary,
  preliminary_status = 'executing'
```

После завершения исполнения (если скилл с кодом):
- exit 0 → `preliminary_status = 'executed_ok'`
- exit ≠ 0 → `preliminary_status = 'executed_fail'`
- instruction-only скилл → `preliminary_status = 'executed_unknown'`

Уже на этой фазе:
- `invocations_count++`
- `last_used_at = now()`
- `sessions_since_use = 0`

### Фаза 2 — явный маркер агента

Агент вызывает `atman.skills.mark_result(invocation_id, status, note)` где-то после использования. `status` ∈ {`helped`, `didnt_help`, `unclear`}. Это самый сильный сигнал.

В bootstrap'е агенту явно сказано:
> Когда используешь скилл — после результата отметь mark_result(...). Это твоя заметка для будущего себя. Без неё micro reflection пойдёт по эвристикам и может ошибиться.

### Фаза 3 — поведенческие сигналы (по ходу сессии)

Собираются в `skill_invocations.behavioral_hints` как append-only список:

- Юзер сказал «ок», «спасибо», «работает» в N сообщений после вызова → push к `likely_helped`
- Юзер сказал «не то», «не работает», повторил тот же запрос → push к `likely_didnt_help`
- Агент вызвал тот же скилл повторно с другими параметрами → предыдущий вызов почти точно `didnt_help`
- Тема ушла, к скиллу не возвращались → `likely_helped` (молчание = согласие)

Это вычисляет тот же NLP-pipeline что обрабатывает passive memory.

### Фаза 4 — финальный вердикт на micro reflection

Иерархия сигналов:

```
agent_marker (mark_result) > user_explicit_feedback > behavioral_hints > exit_code > 'unclear'
```

Результат → `final_status` на `skill_invocations`. Влияет на:
- success_count / failure_count на скилле
- KeyMoment в experience-store (только если статус ≠ unclear или вызов был значимым)
- revision_needed флаг если didnt_help

`unclear` — **полноправный финальный статус**. Если нет сигналов, не выдумываем. Лучше пропуск, чем шум в статистике.

### Маркер-протокол

Параллельно с `atman_session_done_<ts>.marker` пишется `atman_session_skills_<ts>.json` с компактной выжимкой по скиллам сессии:

```json
{
  "session_id": "...",
  "invoked_skills": [
    {
      "skill_id": "smart-outlet-control",
      "invocation_id": "...",
      "preliminary_status": "executed_ok",
      "agent_marker": "helped",
      "agent_marker_note": "розетка переключилась с первой попытки",
      "user_feedback_hints": ["positive in +2 messages"],
      "behavioral_hints": ["topic_closed"]
    }
  ]
}
```

Micro reflection видит этот файл рядом с marker'ом, обрабатывает скиллы отдельным проходом. Skill-loop становится отдельным контуром внутри micro reflection — его можно отключить через конфиг или зашунтировать в тестах.

---

## 8. Atman ↔ агент: контракт через 4 tool'а

Спека агента-универсальна. Сейчас Pydantic-агенты на gemma 4, в будущем — что угодно. Контракт фиксируется не на уровне prompt-формата, а на уровне tool API.

```
atman.skills.list_available()
    → возвращает доступные скиллы (pinned + suggested в текущей сессии)
    → агент может проверить что у него на руках

atman.skills.invoke(skill_id, args)
    → начало использования
    → создаёт invocation row, возвращает invocation_id
    → если скилл on-demand и впервые в сессии — lazy install (см. §10)

atman.skills.mark_result(invocation_id, status, note=None)
    → результат: helped | didnt_help | unclear
    → пишется в invocation row

atman.skills.capture(name, description, code_path=None, instructions=None)
    → агент сам создаёт скилл в процессе сессии
    → создаёт entity + skills row со status='draft', origin='in_session'
    → карточка пишется сразу как первый набросок (агент сам знает что сделал)
```

### Адаптация под слабые модели

Gemma 4 (270M-9B) — слабая для tool-calling из коробки. Поэтому:

- **Fallback на парсинг ответа агента** — first-class citizen, не костыль. Если агент написал «использую smart-outlet» без вызова tool — это валидный сигнал, идёт в `agent_marker_inferred`. NLP-pipeline парсит явные упоминания скиллов в свободном тексте.
- **Skill suggestion как структурированный блок в промпте** работает надёжнее чем «вот тебе tool, надейся что вызовет». Карточка + явное приглашение `«если подходит — вызови atman.skills.invoke(X)»` лучше чем неявное.
- Со временем когда модели прокачаются — fallback станет ненужным, контракт через tool'ы останется.

### ProjectionAdapter — для будущего, не для MVP

В исходной спеке (08-skill-manager.md) был AGENTS/SOUL planner — генерация JSON-патчей для файлов конфига агента. Это **нужно для агентов типа OpenClaw / Claude Code / Cursor**, у которых есть свой workspace с определённой структурой.

Для Pydantic-агентов сейчас этого **не нужно**. Скиллы лежат в каноничной папке (`~/.atman/agents/<id>/skills/<name>/`), при триггере on-demand скилл регистрируется как tool в пуле tool'ов агента на эту сессию. Pinned — зарегистрированы с самого начала. Disabled — никогда.

ProjectionAdapter остаётся как extension point в спеке. Когда придёт OpenClaw / Claude Code — реализуется как подмена одного класса, не переписывание системы:

```python
class ProjectionAdapter(Protocol):
    def project_skill(self, skill: Skill, agent_workspace: Path) -> None: ...
    def unproject_skill(self, skill: Skill, agent_workspace: Path) -> None: ...
    def list_projected(self, agent_workspace: Path) -> list[str]: ...

class PydanticAgentProjector:    # MVP — тривиальный, регистрация tool'ов
    ...

class OpenClawProjector:          # потом
    ...

class ClaudeCodeProjector:        # потом
    ...
```

---

## 9. Данные

Спроектировано под существующую архитектуру изоляции Atman'а (см. `DATABASE_SCHEMA.md`):

```
public.*       — общие таблицы, RLS по session var atman.current_agent
agent_{N}.*    — приватные схемы агентов, физическая изоляция
```

Skill-loop кладётся консистентно с фактами: **технический реестр в `public.*` с RLS, субъективные связи через entity в `agent_{N}.*`**.

### Что новое создаём в `public.*`

**`public.skills`** — реестр всех скиллов всех агентов, RLS по `agent_id`:

```sql
CREATE TABLE public.skills (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  agent_id        uuid NOT NULL,  -- RLS
  entity_id       uuid NOT NULL,  -- soft ref → agent_{N}.entities.id (кросс-схема, без FK)
  name            text NOT NULL,  -- kebab-case, совпадает с metadata.name в SKILL.md
  version         text NOT NULL,
  kind            text NOT NULL,        -- 'active' | 'passive'
  status          text NOT NULL,        -- 'draft' | 'active' | 'disabled'
  origin          text NOT NULL,        -- 'in_session' | 'reflection_pattern' | 'external'
  core            boolean DEFAULT false,
  session_scoped  boolean DEFAULT false,

  -- pinning
  user_pinned     boolean DEFAULT false,
  auto_pinned     boolean DEFAULT false,

  -- statistics
  invocations_count    int DEFAULT 0,
  success_count        int DEFAULT 0,
  failure_count        int DEFAULT 0,
  last_used_at         timestamptz,
  sessions_since_use   int DEFAULT 0,

  -- revision tracking
  revision_needed      boolean DEFAULT false,
  revision_priority    int DEFAULT 0,
  last_revised_at      timestamptz,
  manifest_inferred    boolean DEFAULT false,  -- для external со сгенерённым SKILL.md

  -- paths (Agent Skills Open Standard layout)
  skill_root           text NOT NULL,  -- абсолютный путь к папке скилла
  manifest_path        text NOT NULL,  -- skill_root + '/SKILL.md'

  created_at      timestamptz DEFAULT now(),
  updated_at      timestamptz DEFAULT now(),

  UNIQUE (agent_id, name)
);

ALTER TABLE public.skills ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.skills FORCE ROW LEVEL SECURITY;

CREATE POLICY skills_isolation ON public.skills
  USING (agent_id = NULLIF(current_setting('atman.current_agent', TRUE), '')::uuid);

CREATE INDEX ON public.skills (agent_id, status);
CREATE INDEX ON public.skills (agent_id, user_pinned, auto_pinned) WHERE status = 'active';
```

**`public.skill_invocations`** — лог вызовов, RLS наследуется через `agent_id`:

```sql
CREATE TABLE public.skill_invocations (
  id                    uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  skill_id              uuid NOT NULL REFERENCES public.skills(id) ON DELETE CASCADE,
  agent_id              uuid NOT NULL,  -- денормализовано для RLS и быстрого фильтра
  session_id            uuid NOT NULL,  -- soft ref → agent_{N}.sessions.id

  started_at            timestamptz NOT NULL,
  ended_at              timestamptz,

  preliminary_status    text,  -- 'executing' | 'executed_ok' | 'executed_fail' | 'executed_unknown'
  final_status          text,  -- 'helped' | 'didnt_help' | 'unclear' (NULL до обработки micro)

  agent_marker          text,
  agent_marker_note     text,
  user_feedback_hints   jsonb DEFAULT '[]'::jsonb,
  behavioral_hints      jsonb DEFAULT '[]'::jsonb,
  exit_code             int,

  input_context_summary text,
  output_summary        text,

  processed_at          timestamptz  -- когда micro reflection обработал
);

ALTER TABLE public.skill_invocations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.skill_invocations FORCE ROW LEVEL SECURITY;

CREATE POLICY skill_invocations_isolation ON public.skill_invocations
  USING (agent_id = NULLIF(current_setting('atman.current_agent', TRUE), '')::uuid);

CREATE INDEX ON public.skill_invocations (skill_id, started_at DESC);
CREATE INDEX ON public.skill_invocations (agent_id, session_id);
CREATE INDEX ON public.skill_invocations (agent_id, processed_at) WHERE processed_at IS NULL;
```

### Что используем как есть в `agent_{N}.*`

Никаких новых таблиц в схемах агентов не нужно — всё уже предусмотрено:

- **`agent_{N}.entities`** — `entity_type='skill'` уже есть в enum. Регистрируем скилл там при создании, `canonical_name = SKILL.md name`, `description = SKILL.md description`.
- **`agent_{N}.entity_relations`** — связи скилл↔другая_сущность работают как есть (например, `relation_type='used_for'` к человеку или объекту).
- **`agent_{N}.fact_entities`** — факты про скилл (грабли, ограничения) связываются с entity скилла.
- **`agent_{N}.key_moment_entities`** — ключевые моменты использования связываются с entity скилла на micro reflection.
- **`agent_{N}.reflection_entities`** — рефлексия по скиллу связана через entity.

Это даёт нам **граф памяти про скилл бесплатно**: ровно те же связи которые работают для «Сергея» и «Атмана» работают и для скиллов.

### Интеграция с переделкой Sergey

Sergey планирует унести `public.reflections` и `public.self_applied_changes` в per-agent схемы. **Skill-loop не зависит от этого напрямую** — мы интегрируемся в рефлексию через хуки (`MicroReflectionService.process_skills(...)`), а не через прямые ссылки на таблицу. После переезда хук просто пишет в новое место, спека skill-loop не меняется.

### Где жить фоновым пересчётам

Auto-pin / auto-downgrade пересчитываются на micro reflection (см. §6). Но можно вынести в `public.maintenance_jobs` отдельным job_name (например, `skill_stats_recompute`) если micro reflection начнёт тормозить. На MVP — оставляем в micro, в `maintenance_jobs` уходят только тяжёлые операции (типа массового пересмотра SKILL.md на deep reflection).

### Файловая структура

Используется **Agent Skills Open Standard** layout. Папки агентов именуются по UUID агента (стабильный идентификатор):

```
~/.atman/
  agents/
    <agent_uuid>/                       # UUID из public.agents.id
      skills/
        <skill-name>/                   # kebab-case, совпадает с metadata.name
          SKILL.md                      # YAML frontmatter + markdown body
          scripts/                      # executable code (опционально)
            run.py
          references/                   # extended docs (опционально, on-demand)
            history-of-failures.md
          assets/                       # templates, static resources (опционально)
            config-template.yaml
      external/
        <external-skill>/               # клонированные внешние скиллы перед обработкой
```

Альтернативно, можно сделать symlink `agents/<serial_id>/` → `agents/<agent_uuid>/` для удобства ручной работы — schema name (`agent_5`) проще запомнить чем UUID. Это косметика, не обязательно.

**SKILL.md формат** — стандартный Agent Skills с расширением в `metadata.atman`:

```yaml
---
name: smart-outlet-control
description: |
  Control smart outlets through home network API. Use when user
  asks about turning on/off devices, smart plugs, light switches,
  or mentions specific appliance names like "розетка", "лампа".
  Do NOT use for general home automation queries.

license: MIT
metadata:
  author: atman-agent
  version: "0.1.0"
  created_at: "2026-05-16T..."
  atman:
    origin: in_session             # in_session | reflection_pattern | external
    kind: active                    # active | passive
    core: false
    session_scoped: false
    triggers:
      keywords: ["розетка", "smart outlet", "включи свет"]
      embedding_anchors:
        - "управление умной розеткой через API"
      min_confidence: 0.65
    dependencies:
      skills: []
      python_packages: ["requests>=2.31"]
    runtime:
      entry: scripts/run.py
      sandbox: subprocess            # subprocess | inline | none
---

# Smart Outlet Control

## What it does

Управляет умными розетками через локальную домашнюю сеть.
Работает через REST API хаба, поддерживает on/off и dimming.

## When to use

Когда юзер просит включить/выключить устройство, упоминает розетку
по имени, или говорит «включи свет в спальне».

## How to use

1. Получи имя устройства из контекста или спроси у юзера
2. Вызови scripts/run.py с аргументами `--device NAME --action on|off`
3. Подтверди результат юзеру

## Known gotchas

- Reset кнопка хаба сбрасывает названия устройств — после reset нужно
  переименовать в приложении вендора
- Долгий response (>3s) обычно значит что хаб ушёл в сон, ретрай помогает
```

**Что в стандарте Agent Skills используется как есть:**

- `name`, `description`, `license`, `metadata.author`, `metadata.version` — стандарт
- Структура папки (`scripts/`, `references/`, `assets/`) — стандарт
- Progressive disclosure: description (~100 токенов в bootstrap) → SKILL.md body при триггере → references/ on-demand — стандарт

**Что Atman добавляет в `metadata.atman`:**

- `origin`, `kind`, `core`, `session_scoped` — наш лайфцикл
- `triggers` — для нашего embedding-based router'а (стандартные парсеры это поле игнорируют, текстовый `description` остаётся работать для LLM-based routing где это применимо)
- `dependencies` — структурированно (стандарт даёт только string `compatibility`)
- `runtime` — где entry point, sandbox-режим

**Что в БД vs что в файле:**

Файл — это **declarative spec** (что скилл из себя представляет). БД — это **operational state** (статистика, статус, pinning). Не дублируем: всё что часто меняется (success_count, last_used_at, status) живёт только в БД. Файл редактируется на рефлексии или вручную; БД пишется runtime'ом.

### CARD.md как отдельный файл — упраздняется

В предыдущей версии дизайна был отдельный `CARD.md` как «дистиллят для контекста». В Agent Skills стандарте это **первая часть SKILL.md** (description + начало markdown body). Не плодим сущности.

Что льётся в контекст агента:
- **Bootstrap (pinned skills):** только `name` + первая строка `description`
- **При триггере (on-demand):** полный markdown body SKILL.md (по стандарту — это <5000 токенов)
- **При запросе подробностей:** содержимое `references/*.md`

---

## 10. Lazy install и projection

### Lazy install для on-demand

Сценарий: triggered router предложил скилл X впервые в этой сессии.

1. Atman сигналит агенту в контексте: «доступен новый скилл X, описание: …, минуту, готовлю»
2. ProjectionAdapter регистрирует скилл как tool в пуле сессии (для Pydantic — добавление в tool list; для OpenClaw — проекция файлов в workspace)
3. Если у скилла есть зависимости (другие скиллы или python packages) — устанавливаются первыми
4. Готово, агент может вызывать `atman.skills.invoke(X)`

При следующей сессии — если скилл стал `auto_pinned`/`user_pinned`, lazy уже не нужен, он на старте.

### Session_scoped очистка

Скиллы с `session_scoped=true` — при session end ProjectionAdapter отзывает проекцию (выгружает tool из пула / удаляет файлы из workspace). Запись в `skills` остаётся, история тоже.

### Disabled

ProjectionAdapter никогда не проектирует disabled скиллы, даже если router их предложил. Router тоже фильтрует disabled. Файлы и история в таблицах сохраняются.

---

## 11. Внешние скиллы

Юзер приходит и говорит «вот этот репозиторий — это скилл, поставь».

### Процесс

1. Atman клонит репо в `~/.atman/agents/<id>/external/<skill-name>/`
2. Ищет `SKILL.md` (стандарт Agent Skills) в корне репозитория или в подпапках:
   - **Найден `SKILL.md` с валидным frontmatter** — берёт как есть, `manifest_inferred=false`. Это типичный случай для скиллов из marketplace (Agensi и аналоги) и репозиториев которые уже follow стандарт.
   - **Найден только `README.md`** — Atman через LLM генерирует draft `SKILL.md` (frontmatter + body) на основе README, помечает `manifest_inferred=true`
   - **Ничего не найдено** — отказ, юзеру сообщение что репозиторий не похож на скилл
3. **Спрашивает юзера**: «вот что я понял про этот скилл, его манифест. Установить?» Показывает frontmatter + первые секции body.
4. После подтверждения — переносится из `external/` в `skills/<skill-name>/`, создаётся entity + row в `skills` с `origin='external'`. Если `manifest_inferred=true` — заносится в `metadata.atman.manifest_inferred=true` чтобы Reflection Engine знал что нужен пересмотр.

### Отличия от своих скиллов

- Только по явному запросу юзера (свои создаются автоматически)
- Если манифест inferred — `revision_priority` сразу высокий, на первой же рефлексии после нескольких использований SKILL.md пересматривается
- Никакой автоустановки в следующих сессиях без юзер-подтверждения

### Преимущество совместимости

Поскольку Atman принимает стандартный Agent Skills формат, юзер может ставить **любой существующий скилл** из экосистемы — Anthropic skills repo, Agensi marketplace, community-репозитории на github. Никакого специального формата для Atman не требуется.

---

## 12. Bootstrap-инжекция: self-awareness Atman'а

**Отдельный пункт, не про скиллы напрямую, но важный.**

В текущем bootstrap'е сессии в personality slice инжектируется идентичность (ценности, принципы, нарратив). Но не инжектируется **понимание агентом устройства Atman'а** — что у него есть память (factual + experience + entity), что есть рефлексия, что есть скиллы, как этим пользоваться.

Без этого self-awareness слепка агент не может осознанно работать с собственной анатомией. Не знает что может запросить память. Не знает что скилл — его собственная заметка, а не внешняя инструкция. Не понимает что micro reflection обработает его маркеры.

### TODO — проверить и/или реализовать

В bootstrap сессии добавить блок self-awareness:

```
Ты работаешь в системе Atman. У тебя есть:

- Долговременная память — факты, опыт, сущности. Можешь запрашивать
  через atman.memory.recall(query). Связи между сущностями (например,
  скиллы) могут всплывать автоматически когда становятся релевантны.

- Навыки — твои собственные способы решать повторяющиеся задачи.
  Карточки навыков — твои заметки, которые ты сам когда-то написал
  и которые обновляются на рефлексии. Если нужны подробности —
  запроси память.

- Рефлексия — после сессии (micro), в конце дня (daily), регулярно
  (deep). Reflection Engine обработает то что осталось в логе,
  обновит карточки навыков, проставит флаги. Ты можешь оставлять
  явные маркеры (mark_result, и т.п.) — это твои заметки для будущего себя.

- Идентичность — ценности, принципы, открытые вопросы. Это
  обновляется только на deep reflection при достаточных основаниях.
```

Конкретный текст уточнить — но смысл такой. **Это TODO задача отдельная от скиллов**, просто всплыла в обсуждении.

---

## 13. CLI и админ-операции

Большую часть жизненного цикла скиллы проходят автоматически. Но нужны CLI для диагностики и ручных вмешательств:

```bash
atman skills list [--agent <id>] [--status active|disabled|draft]
atman skills show <name>                  # карточка + статистика + история
atman skills disable <name>               # юзер запретил
atman skills enable <name>                # обратно
atman skills pin <name>                   # user_pinned=true
atman skills unpin <name>                 # user_pinned=false
atman skills archive <name>               # soft-delete (status=archived, файлы остаются)

atman skills install-external <url>       # клонит, парсит, спрашивает подтверждение
atman skills capture-manual <args>        # ручное создание скилла (для отладки)

atman skills inspect-invocations <name> [--last N]
atman skills force-revise <name>          # принудительно поставить revision_needed
```

---

## 14. Что вне scope этого пакета

- Генерация кода скиллов автоматически (это не в задачах skill manager'а — скилл пишет либо агент, либо юзер)
- Реальный sandbox для исполнения скиллов (subprocess с venv-изоляцией — да, полноценная sandbox типа firecracker — нет)
- Управление зависимостями между python-пакетами разных скиллов глубже чем «общий venv `.atman/skills/.venv`» + декларация в манифесте
- Shared skills между агентами (только когда возникнет реальная потребность)
- UI для админки (CLI достаточно для MVP, админка — потом)

---

## 15. Опциональность модуля

Skill-loop — **полностью отключаемая часть Atman**. Юзер может выключить через конфиг агента:

```yaml
atman:
  skills:
    enabled: false
```

Это нужно для двух сценариев:
- юзер не хочет тратить токены контекста на скиллы (особенно актуально для локальных моделей с малым контекстом)
- юзеру нравится как агент пользуется скиллами «из коробки», без вмешательства Atman'а

### Что остаётся независимо от `enabled`

- **Таблицы создаются всегда.** Миграции `skills` и `skill_invocations` накатываются при инициализации Atman'а независимо от настройки. Это важно: включить/выключить можно туда-обратно, не теряя ничего и не запуская дополнительных миграций.
- **Существующие данные не трогаем.** Если у агента уже были скиллы и накопленная статистика — они остаются в БД. При повторном включении модуль увидит их и продолжит работать с накопленным состоянием.
- **Файловые артефакты в `~/.atman/agents/<id>/skills/` не удаляются.** Папки скиллов с SKILL.md, кодом и references остаются на диске.

### Что отключается при `enabled: false`

- **Bootstrap-инжекция скиллов.** Pinned скиллы НЕ попадают в personality slice сессии. Имена и описания не упоминаются в системном промпте.
- **Skill retriever.** При обработке сообщения юзера skill retriever не вызывается; никаких параллельных каналов в context-builder'е не добавляется. Memory retriever работает в одиночку.
- **Триггер-роутер не запускается.** Никаких suggestions агенту, никаких реранков, никакого подбора скиллов под запрос.
- **Tool registration.** ProjectionAdapter не регистрирует скиллы как tools в сессии (ни pinned, ни on-demand). С точки зрения агента — у него просто нет таких tools.
- **Tool runner блокирует invoke/capture/mark_result.** Если агент попытается вызвать `atman.skills.invoke(...)` — возвращается ошибка «skill loop disabled». Логирование вызовов в `skill_invocations` не происходит. `atman_session_skills_<ts>.json` не пишется.
- **Skill-loop в micro/daily/deep reflection пропускается.** Reflection Engine продолжает работать с experience, identity, narrative — но шаг обработки скиллов в нём отключён. Никаких новых KeyMoment'ов про скиллы, никаких флагов revision_needed, никакого пересмотра SKILL.md.
- **Auto-capture отключён.** Если агент в процессе сессии создаст автоматизацию и попытается её сохранить — не получится. Юзер сам решает, что делать с такими находками.

### Что остаётся работать (read-only диагностика)

CLI команды чтения работают независимо от `enabled` — полезно для диагностики и архивных запросов:

```
atman skills list       # просто читает таблицу
atman skills show       # просто читает таблицу + файлы
atman skills inspect-invocations    # читает skill_invocations
```

Команды записи (`disable`, `pin`, `capture-manual`, `install-external`, `force-revise`) при `enabled: false` возвращают ошибку с подсказкой: «модуль выключен в конфиге, включите чтобы вносить изменения».

### Включение обратно

При смене `enabled: false → true` — никаких миграций, никакого восстановления. Модуль просто начинает работать с текущим состоянием БД:
- если есть pinned скиллы — они снова попадают в bootstrap
- статистика использования сохранилась — auto-pin/auto-downgrade продолжают считаться с этой точки
- `sessions_since_use` может оказаться stale (модуль был выключен N сессий — он не инкрементил счётчик); это окей, рефлексия наверстает за пару проходов
- `revision_needed` флаги, накопленные до выключения, остаются — будут обработаны при первом подходящем reflection-проходе

### Реализация на уровне кода

Все компоненты skill-loop живут в одном Python-пакете (например, `atman.skills`). Через DI-контейнер этот пакет регистрируется как noop-имплементация при `enabled: false`:

```python
class NoopSkillManager(SkillManagerPort):
    def list_pinned(self, agent_id): return []
    def trigger_router(self, message, ctx): return []
    def invoke(self, skill_id, args): raise SkillsDisabled(...)
    def capture(self, ...): raise SkillsDisabled(...)
    # ...
```

Все остальные компоненты Atman (Session Manager, Reflection Engine, RAG-pipeline) видят `SkillManagerPort` и не зависят от реального наличия модуля. Это даёт чистое отключение без `if config.skills.enabled` разбросанных по коду.

---

## 16. Решения и открытые вопросы

### ✅ Решено

1. **Формат манифеста и структура папки скилла** — Agent Skills Open Standard (см. §9). Atman-specific поля живут в `metadata.atman` namespace.

2. **Структура текста SKILL.md body** — рекомендуемые секции (What it does / When to use / How to use / Known gotchas / Examples), но без жёсткой схемы (как и стандарт). Reflection Engine на пересмотре карточек поддерживает эту структуру если она уже есть, но не ломает свободно-написанные тела.

3. **CARD.md как отдельный файл** — не нужен. Дистиллят для контекста = description + начало markdown body SKILL.md, по принципу progressive disclosure из стандарта.

4. **Триггер-роутер** — **отдельный компонент** рядом с RAG/memory pipeline, не часть его. Туда же подключаются будущие tool-use модели (function-gemma и т.п.). У роутера свой реранк, своя логика confidence.

5. **`atman_session_skills_<ts>.json` пишет tool runner.** Skill-loop максимально изолирован от остальных компонентов.

6. **Skill-loop опционален.** Через конфиг `atman.skills.enabled = false` весь модуль отключается, остальные компоненты Atman работают без него. Это полезно для отладки, для агентов где скиллы не нужны, и для бутстрапа когда модуль ещё не готов.

7. **`skill_invocations.session_id`** — soft reference на `agent_{N}.sessions.id` (кросс-схема, без FK constraint, как другие soft refs в схеме Atman'а). Зашито в SQL §9.

8. **Default-пороги** (все три **обязательно в конфиг агента, не в код**):
   - Auto-pin: 3 использования за 10 сессий
   - Auto-downgrade: 20 сессий без использования
   - `min_confidence` для router'а: 0.65
   
   Никаких хардкод-значений. При запуске агента без явной конфигурации — берутся из defaults в `atman.skills` config schema, но всегда переопределяются через конфиг.

9. **Имя папки агента на диске** — UUID из `public.agents.id`. Опционально — symlink `agents/<serial_id>/ → agents/<uuid>/` для удобства ручной навигации.

### 📋 Отдельные задачи (не блокируют skill-loop)

1. **Bootstrap self-awareness инжекция** (см. §12) — проверить что из описанного блока уже реализовано в текущем bootstrap-коде Atman'а, дописать недостающее. Это работа отдельно от skill manager'а, но связана: без self-awareness агент не понимает что у него есть скиллы как часть его собственной анатомии, а не внешние tools.

### ⏳ Открытых вопросов нет

Все блокирующие имплементацию решения приняты. Дизайн готов к декомпозиции на работы.

---

## 17. Краткое резюме архитектуры

```
┌─────────────────────────────────────────────────────────┐
│ Bootstrap сессии                                         │
│  - identity slice                                        │
│  - pinned skills (имена + одна строка)                   │
│  - self-awareness блок                                   │
│  - регистрация pinned skills как tools в session pool    │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ Сообщение юзера                                          │
│  - NLP/lingua analysis                                   │
│  - параллельно:                                          │
│    [Memory retriever]    [Skill retriever]               │
│  - context assembly: pinned + retrieved + memory         │
│  - агент получает контекст + suggestions                 │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ Агент действует                                          │
│  - может вызвать atman.skills.invoke(X)                  │
│  - может вызвать atman.skills.capture(...)               │
│  - оставляет mark_result после использования             │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ Session end                                              │
│  - marker файл + skills.json выжимка                     │
│  - unproject session_scoped skills                       │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ Micro reflection (асинхронно)                            │
│  - final_status каждому invocation                       │
│  - инкремент success/failure                             │
│  - sessions_since_use update                             │
│  - auto-pin / auto-downgrade                             │
│  - revision_needed flags                                 │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ Daily / Deep reflection                                  │
│  - пересмотр SKILL.md (body + description)               │
│  - паттерны и предложения консолидации                   │
│  - выявление новых скилл-кандидатов                      │
└─────────────────────────────────────────────────────────┘
```
