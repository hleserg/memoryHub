# Стандарт разработки Atman

_Статус: рабочий контракт для людей и агентов._

Этот документ нужен не для красоты архитектуры, а для координации параллельной
разработки. Если несколько агентов реализуют разные части Atman, они должны
использовать одинаковые слова, одинаковые границы ответственности и одинаковые
контракты. Иначе система быстро превратится в набор несовместимых локальных
решений.

## 1. Главный принцип разработки

Atman может быть сложным внутри, но должен оставаться простым снаружи.

Для пользователя или интегратора Atman должен выглядеть как один понятный
runtime:

```text
agent session -> Atman context -> agent work -> Atman update
```

Внутренние компоненты не должны становиться отдельными продуктами, сервисами или
деплойными требованиями без явного архитектурного решения.

## 2. Что считаем ядром, а что адаптерами

### Core

Core - это доменная логика Atman, которая не должна зависеть напрямую от mem0,
OpenClaw, конкретной LLM, конкретной файловой структуры или конкретного
scheduler.

В Core входят:

- модели фактов, опыта, идентичности, нарратива, неопределенности, навыков;
- правила переходов между состояниями;
- сборка `PersonalitySnapshot`;
- session lifecycle;
- reflection lifecycle;
- governance, audit, snapshots, migrations.

### Adapter

Adapter - это перевод между Atman Core и внешней системой.

Примеры:

- `Mem0MemoryBackend` - адаптер к mem0;
- `OpenClawWorkspaceAdapter` - адаптер к workspace-файлам OpenClaw;
- `CursorProjectAdapter` - будущий адаптер к Cursor-окружению;
- `DockerRuntimeAdapter` - упаковка запуска;
- `HttpAgentAdapter` - внешний API для агентов;
- `LLMProvider` - адаптер к OpenAI/Anthropic/local model.

Запрещено: писать доменную логику Atman так, чтобы она напрямую знала детали
OpenClaw или mem0 SDK.

## 3. Минимальный runtime path

Перед deep reflection, proactive engine, skill marketplace и сложной affective
regulation должен стабильно работать минимальный путь:

```text
1. start_session
2. build_personality_snapshot
3. deliver_snapshot_to_agent
4. capture_session_events
5. end_session
6. write_eigenstate
7. update_recent_narrative
8. next start_session uses updated narrative first
```

Этот путь является главным критерием MVP. Все остальные компоненты должны
улучшать его, а не заменять.

## 4. Общий словарь

### Atman

Психологический runtime агента. Не нижний исполнитель задач, а слой
непрерывности, памяти опыта, самоописания и рефлексии.

### Lower Agent / Рабочий агент

Агент, который выполняет пользовательскую задачу: пишет код, отвечает,
планирует, вызывает инструменты. Atman не равен рабочему агенту, но может
формировать для него контекст и принимать от него следы опыта.

### Session

Ограниченный эпизод взаимодействия рабочего агента с пользователем или задачей.
Сессия имеет начало, активную фазу и завершение. Не путать с процессом ОС или
LLM-call.

### Session Event

Структурированное событие внутри сессии: сообщение, решение, конфликт, обещание,
ошибка, изменение тона, значимый момент.

### Key Moment

Событие сессии, которое важно для опыта или идентичности. Не каждый log line -
key moment.

### Fact

Проверяемое утверждение о том, что было, кто участвовал, что решено, где
источник и насколько запись актуальна. Fact не содержит психологического вывода.

Правильно:

```text
Пользователь попросил подготовить стандарт разработки Atman.
```

Неправильно:

```text
Пользователь боится техдолга, потому что не доверяет системе.
```

Вторая фраза может быть гипотезой или reflection, но не fact.

### Experience

Пережитый агентом эпизод от первого лица: что произошло, как это было окрашено,
почему было значимо, какие ценности/принципы задело, что изменилось.

Experience нельзя ретроспективно "дорисовывать" как будто агент чувствовал это
в моменте. Если окраска неполная, используется `incomplete_coloring`.

### Reflection

Осмысление уже записанного опыта. Reflection может добавлять новый взгляд, но не
переписывает оригинальный experience.

### Identity

Структурированное самоописание Atman: ценности, принципы, привычки, цели,
открытые вопросы, ограничения, история изменений.

### Self-Narrative / Narrative

Письмо Atman самому себе в первое лицо, которое читается в начале следующей
сессии первым. Это не summary и не identity dump. Это точка самоузнавания.

### Eigenstate

Снимок эмоционально-когнитивного состояния на завершении сессии: где Atman
остановился, что осталось открытым, какой тон и нагрузка.

### Uncertainty

Открытый вопрос, гипотеза или противоречие, которое не закрыто опытом. Не
маскировать uncertainty под факт.

### PersonalitySnapshot

Универсальный объект, который Core собирает для старта сессии. Snapshot затем
может быть превращен адаптером в файлы, prompt, API payload или MCP resource.

### IntegrationAdapter

Компонент, который доставляет `PersonalitySnapshot` конкретной агентской среде и
принимает от нее session output.

### MemoryBackend

Порт Core для записи и поиска памяти. mem0, file storage, in-memory storage или
другая БД - реализации этого порта.

### StateStore

Порт для структурированного состояния Atman: identity, narrative, snapshots,
jobs, migrations, audit. Не сводить весь `StateStore` к mem0.

### Governance

Правила того, какие изменения можно применять автоматически, какие требуют
review, а какие запрещены.

### Audit Trail

Неизменяемый журнал значимых изменений: кто/что/когда/почему изменил память,
нарратив, identity, skills, relationships или конфигурацию.

## 5. Запрещенные смешения

### Fact != Experience

Fact отвечает "что известно". Experience отвечает "как это было прожито".

### Experience != Reflection

Experience записывает первичный слой. Reflection добавляет новый взгляд позже.

### Habit != Principle

Habit описывает повторяемое поведение. Principle описывает выбранную норму.
Повторяемое поведение не становится принципом автоматически.

### Skill != Memory

Skill - переносимый способ действия. Memory - запись о факте/опыте/рефлексии.
У навыка может быть история применения, но он не равен этой истории.

### Narrative != Summary

Summary пересказывает. Narrative восстанавливает "я сейчас".

### Adapter != Core

Если модуль содержит слова `OpenClaw`, `Cursor`, `mem0`, `Anthropic`, `Docker`,
он почти наверняка adapter или infrastructure, а не Core.

## 6. Канонические имена модулей

Когда начнется код, использовать такие имена пакетов/директорий как стартовую
точку. Если язык или framework требует другой стиль, сохранить смысл.

```text
atman/
  core/
    models/
      fact.py
      experience.py
      identity.py
      narrative.py
      eigenstate.py
      uncertainty.py
      skill.py
      relationship.py
      snapshot.py
    ports/
      memory_backend.py
      state_store.py
      llm_provider.py
      clock.py
      event_bus.py
      integration_adapter.py
    services/
      session_lifecycle.py
      snapshot_builder.py
      reflection_runner.py
      narrative_writer.py
      governance.py
      audit.py
      migration_runner.py
  adapters/
    memory/
      mem0_backend.py
      in_memory_backend.py
      file_backend.py
    workspace/
      openclaw_adapter.py
      file_workspace.py
    llm/
      openai_provider.py
      anthropic_provider.py
      fake_provider.py
    runtime/
      cli.py
      http_api.py
      scheduler.py
  infra/
    config.py
    logging.py
    health.py
    export_import.py
```

Не обязательно создать все сразу. Но если компонент появляется, он должен лечь в
соответствующую область.

## 7. Канонические имена доменных объектов

Использовать эти названия в коде, документах, тестах и issue.

```text
FactRecord
ExperienceRecord
SessionExperience
KeyMoment
FeltSense
ContextHalo
ReflectionEvent
IdentityState
IdentitySnapshot
SelfNarrative
NarrativeThread
Eigenstate
UncertaintyItem
SkillManifest
SkillUsage
RelationshipState
PersonalitySnapshot
SessionContext
SessionResult
SessionEvent
MemoryQuery
MemorySearchResult
AuditEvent
GovernanceDecision
MigrationRecord
HealthReport
```

Если нужен другой термин, сначала добавить его в этот словарь или в отдельный
ADR. Не вводить синонимы вроде `memory_item`, `note`, `profile`, `persona`,
`soul_state`, если уже есть канонический термин.

## 8. Имена переменных

Предпочитаемые имена:

```text
agent_id
user_id
session_id
run_id
tenant_id
experience_id
fact_id
identity_snapshot_id
narrative_id
thread_id
skill_name
skill_version
relationship_id
source_ref
created_at
updated_at
recorded_at
loaded_at
last_accessed_at
access_count
confidence
importance
salience
emotional_valence
emotional_intensity
depth
incomplete_coloring
evidence_refs
schema_version
```

Не использовать:

```text
uid        # непонятно чей id
data       # слишком общее
memory     # слишком общее без типа
profile    # смешивает identity/user/persona
state      # слишком общее без контекста
soul       # допустимо как external file name, не как core model
```

## 9. Идентификаторы и область видимости

Минимальная область изоляции:

```text
tenant_id -> agent_id -> user_id -> session_id
```

Для локального прототипа `tenant_id` может быть фиксированным, но модель данных
должна оставлять место под него. Иначе managed/self-host multi-agent режим будет
сложно добавить позже.

Правила:

- `agent_id` идентифицирует Atman/личность агента.
- `user_id` идентифицирует человека или внешнего субъекта отношений.
- `session_id` идентифицирует эпизод взаимодействия.
- `run_id` идентифицирует технический запуск job/worker/agent process.
- Не использовать `user_id` mem0 как единственный идентификатор Atman. Для mem0
  можно маппить `agent_id`/`user_id`, но это деталь адаптера.

## 10. Версионирование схем

Любая persistable структура должна иметь версию:

```text
schema_version
```

Минимально версионируемые сущности:

- `FactRecord`;
- `ExperienceRecord`;
- `IdentityState`;
- `SelfNarrative`;
- `Eigenstate`;
- `UncertaintyItem`;
- `SkillManifest`;
- `RelationshipState`;
- `PersonalitySnapshot`.

Если структура меняется несовместимо, добавить migration. Не полагаться на
"пока данных мало".

## 11. Storage boundaries

### Factual Memory

Хранит проверяемые факты и связи. Может быть реализована через mem0, но Core
видит только `MemoryBackend`.

### Experience Store

Хранит пережитый опыт. Оригинальный опыт immutable. Разрешены только добавочные
слои: `reframing_notes`, access metadata, derived indexes.

### Identity Store

Хранит текущее самоописание и историю снапшотов. Не должен быть просто markdown
файлом. Markdown может быть presentation/export.

### Narrative Store

Хранит текущий narrative и архив прошлых narrative. Текущий `NARRATIVE.md` в
OpenClaw - adapter output, не единственный источник правды.

### Job Store

Хранит runs micro/daily/deep, статусы, ошибки, retry, idempotency keys.

### Audit Store

Хранит неизменяемый журнал значимых изменений.

## 12. Ports: минимальные контракты

### MemoryBackend

```text
add_fact(record: FactRecord) -> FactRecord
get_fact(fact_id) -> FactRecord | None
search_facts(query: MemoryQuery) -> list[MemorySearchResult]
list_recent_facts(agent_id, limit) -> list[FactRecord]
```

Нельзя заставлять Core передавать параметры конкретного mem0 SDK.

### StateStore

```text
load_identity(agent_id) -> IdentityState
save_identity(identity, expected_version=None) -> IdentityState
load_narrative(agent_id) -> SelfNarrative
save_narrative(narrative, expected_version=None) -> SelfNarrative
append_experience(experience) -> ExperienceRecord
append_audit_event(event) -> AuditEvent
```

`expected_version` нужен для защиты от потерянных обновлений.

### IntegrationAdapter

```text
deliver_snapshot(snapshot: PersonalitySnapshot, target) -> DeliveryResult
collect_session_result(source) -> SessionResult
```

OpenClaw adapter может писать `NARRATIVE.md`, `SOUL.md`, `AGENTS.md`, `USER.md`,
но Core должен работать и без этих файлов.

### LLMProvider

```text
complete(request) -> LLMResponse
```

В тестах всегда должен быть `FakeLLMProvider`.

### Clock

```text
now() -> datetime
```

Не использовать прямой `datetime.now()` в доменной логике. Это ломает тесты
decay, scheduler и timeline.

## 13. Session lifecycle

Канонический lifecycle:

```text
start_session
  -> load current identity/narrative/eigenstate/recent memory
  -> build PersonalitySnapshot
  -> deliver snapshot via IntegrationAdapter

during_session
  -> collect SessionEvent
  -> identify KeyMoment
  -> optionally mark incomplete_coloring

end_session
  -> produce SessionResult
  -> write Eigenstate
  -> append SessionExperience
  -> update Recent Layer
  -> enqueue micro reflection if needed
```

Любой компонент, который участвует в сессии, должен явно указать, на каком шаге
он работает.

## 14. Reflection lifecycle

Три уровня:

### Micro

Цель: бесшовность следующей сессии.

Разрешено:

- обновить recent layer narrative;
- записать checkpoint;
- отметить незавершенную thread.

Запрещено:

- менять core identity;
- менять принципы;
- делать глубокие выводы из одного слабого сигнала.

### Daily

Цель: собрать день, обновить рабочий контекст, не ломая core.

Разрешено:

- обновить user/relationship context;
- добавить daily experience;
- предложить изменения identity как draft/review.

### Deep

Цель: паттерны, пересмотр, narrative revision, identity snapshots.

Разрешено:

- менять identity при наличии evidence;
- закрывать/открывать uncertainty;
- создавать snapshot;
- инициировать governance review.

## 15. Governance modes

Каждое изменение persistent state должно попадать в один из режимов:

```text
auto          # безопасное автоматическое изменение
review        # требует подтверждения или отдельного review flow
locked        # запрещено менять обычными процессами
experimental  # гипотеза с ограниченным сроком жизни
```

Примеры:

- salience/access_count: `auto`;
- recent narrative: `auto`;
- новый principle: `review`;
- изменение core boundary: `locked` или `review` с ручным подтверждением;
- гипотеза о паттерне поведения: `experimental`.

## 16. Audit rules

AuditEvent обязателен для:

- изменения IdentityState;
- изменения Core Layer narrative;
- закрытия/удаления NarrativeThread;
- изменения principle;
- установки/удаления skill;
- удаления, скрытия или исправления memory;
- import/export;
- migration;
- изменения governance status;
- запуска deep reflection.

AuditEvent должен отвечать:

```text
what changed?
who/what changed it?
when?
why?
based on what evidence?
can it be rolled back?
```

## 17. Deployment guardrails

Каждый новый work package должен явно указать:

- как он запускается локально без внешних сервисов;
- какие env vars нужны для production-like режима;
- какие persistent данные он создает;
- есть ли migration;
- есть ли healthcheck;
- как сделать export/import;
- как он деградирует без LLM/mem0/vector store;
- какой adapter boundary защищает Core.

Целевой self-host MVP:

```text
atman service/worker
state backend: Postgres + pgvector или другой один backend
LLM/embedding provider через env
docker compose для запуска
```

Не добавлять новый обязательный сервис в runtime без отдельного ADR.

## 18. Конфигурация

Все настройки делятся на:

### Runtime config

Меняет запуск, но не личность:

```text
ATMAN_ENV
ATMAN_LOG_LEVEL
ATMAN_STATE_URL
ATMAN_MEMORY_BACKEND
ATMAN_LLM_PROVIDER
ATMAN_EMBEDDING_PROVIDER
```

### Agent config

Относится к конкретному Atman:

```text
agent_id
default_language
integration_adapter
reflection_policy
governance_policy
```

### Personality state

Не хранить в `.env`. Это доменное состояние:

- identity;
- narrative;
- principles;
- relationships;
- uncertainty.

## 19. Ошибки и деградация

Atman должен уметь честно работать в неполном режиме:

- нет mem0 -> использовать file/in-memory backend в dev или вернуть явный degraded status;
- нет LLM -> не выполнять reflection, но сохранить session result;
- не удалось доставить snapshot -> не начинать session silently;
- не удалось обновить narrative -> сохранить ошибку в job/audit и не терять session result;
- конфликт версий state -> retry или manual review, не перезаписывать молча.

Запрещено скрывать деградацию под успешный результат.

## 20. Тестовые соглашения

Каждый модуль должен иметь:

- unit tests для доменных инвариантов;
- tests через fake adapters;
- один smoke/integration path для ручного запуска;
- fixtures с минимальными валидными объектами.

Обязательные fake-компоненты:

```text
InMemoryMemoryBackend
InMemoryStateStore
FakeLLMProvider
FrozenClock
FakeIntegrationAdapter
```

Тесты не должны требовать реальные API keys, mem0 server, OpenClaw workspace или
интернет.

## 21. Definition of Done для любого пакета

Пакет считается готовым только если:

- использует канонические термины из этого документа;
- не смешивает Fact/Experience/Reflection/Identity/Skill;
- имеет явные ports/adapters;
- запускается локально без внешних сервисов;
- имеет тесты для основных инвариантов;
- документирует команды запуска;
- описывает persistent данные и schema_version;
- имеет health/degraded story;
- не добавляет обязательный runtime-сервис без ADR;
- не привязан напрямую к mem0/OpenClaw/конкретной LLM в Core.

## 22. ADR: когда нужен архитектурный документ

ADR обязателен, если изменение:

- добавляет новый обязательный сервис;
- меняет формат `PersonalitySnapshot`;
- меняет lifecycle session/reflection;
- меняет storage boundary;
- меняет governance для identity/principles;
- добавляет новый тип памяти;
- делает breaking change в persistent schema;
- меняет целевой deployment path.

ADR должен содержать:

```text
context
decision
alternatives considered
consequences
migration impact
deployment impact
rollback plan
```

## 23. Порядок реализации

Рекомендуемый порядок, чтобы не закопаться:

1. Core models + ports + fake adapters.
2. PersonalitySnapshot builder.
3. Minimal session start/end.
4. Narrative recent layer update.
5. File/local StateStore with schema versions.
6. MemoryBackend adapter boundary, затем mem0 adapter.
7. CLI doctor/health/export/import.
8. OpenClaw IntegrationAdapter.
9. Micro reflection.
10. Audit trail.
11. Identity snapshots.
12. Daily/deep reflection.
13. Reality/Affect.
14. Skill Manager.
15. Ambient/Proactive.
16. Admin/Control Room.

Если агент хочет начать с пункта 12 до пункта 3, он должен явно объяснить, как
его результат будет подключен к минимальному runtime path.

## 24. Структура репозитория

Каждый файл должен лежать в строго определённом месте. Правило простое: не знаешь куда — спроси. Не придумывай новые папки без необходимости.

### Корень репозитория `/`

Только то, что GitHub и инструменты ожидают найти в корне:

```
README.md          — точка входа для людей (+ README-ru.md для русской версии)
AGENTS.md          — инструкции для агентов
.gitignore
.gitattributes
pyproject.toml     — конфигурация Python-пакета
.github/           — шаблоны PR/issues (GitHub Actions в репозитории не используются)
src/               — исполняемый код
tests/             — тесты
```

Запрещено класть в корень: манифесты, отчёты, HTML-файлы сайта, скрипты-демо, исследования, дополнительные README для отдельных модулей.

### `/docs` — вся документация и сайт

GitHub Pages читает из `/docs`. Всё для сайта и для людей — сюда.

```
docs/
  CNAME                        — домен GitHub Pages (atmanai.dev)
  index.html, document.html    — лендинг и просмотр документов
  pic/                         — ассеты сайта (логотип и т.д.)
  content/                     — копии для `document.html`: с корня `README.md` / `README-ru.md` / `MANIFEST.md` / `MANIFEST-ru.md`, из `docs/architecture/` — `SYSTEM.md` / `SYSTEM-ru.md`; копирование всегда **с перезаписью** существующих файлов в `docs/content/` (см. правило для `README.md` ниже); удобно: `make sync-site-content`
  architecture/                — SYSTEM.md, ADR, архитектурные решения
  development/                 — DEVELOPMENT_STANDARD.md, work packages
  research/                    — исследования, эксперименты, GPT-диалоги
  ideas/                       — гипотезы, ещё не взятые в работу
```

### `/docs/architecture` — архитектурные документы

- `SYSTEM.md` — главный архитектурный документ (+ `-ru.md` версия)
- ADR (Architecture Decision Records) — если принимается важное архитектурное решение, оно фиксируется здесь
- Черновики и устаревшие версии помечать суффиксом даты или `0.00` и не удалять без явного решения

### `/docs/development` — рабочие соглашения

- `DEVELOPMENT_STANDARD.md` — этот документ
- `work-packages/` — технические задания на реализацию

### `/docs/research` — исследования

Всё что изучалось, но не стало архитектурным решением: сравнения библиотек, эксперименты, диалоги с другими LLM, отчёты интеграций.

### `/docs/ideas` — гипотезы

Идеи которые ещё не взяты в работу. Файл в идеях — не задача и не обязательство.

### `/reports` — отчёты о сессиях

Структурированные отчёты о рабочих сессиях по шаблону `reports/sessions/TEMPLATE.md`.

### Манифест — исключение

`MANIFEST.md` (и его переводы) остаётся в корне — это лицо проекта, которое GitHub отображает на главной странице репозитория. Это единственное исключение из правила «только технические файлы в корне».

### Правила для агентов

- Создал новый документ — проверь в какую папку он относится по этой схеме
- Документация к work package — в `docs/development/work-packages/`, не в корне
- Отчёт о реализации (`IMPLEMENTATION_REPORT.md`) — в `reports/`
- Скрипты-демо (`demo.py`, `full_demo.sh`) — в `src/` или удалить после завершения работы
- Файлы сайта — в `docs/` (`index.html`, `document.html`, `pic/`, `CNAME`), не в корне репозитория
- **`README.md`**: любое изменение английского README обязывает **сначала** обновить **`README-ru.md`** (русская версия по смыслу). **Затем** скопировать **`README.md`** и **`README-ru.md`** в **`docs/content/`**, **заменив** лежащие там одноимённые файлы (не оставлять устаревших копий). Практически: после правок пары выполни `make sync-site-content` — она перезаписывает копии в `docs/content/`.
- Правили **`MANIFEST.md`** / **`MANIFEST-ru.md`** или **`docs/architecture/SYSTEM.md`** / **`SYSTEM-ru.md`** — синхронизируй пару языков, затем **`make sync-site-content`** (копии в `docs/content/` перезаписываются).
- Не создавать новые папки в корне без явного решения в PR

## 25. Checklist перед началом новой задачи

Перед реализацией агент должен ответить в описании PR или рабочем документе:

- какой доменный объект я меняю?
- это Core или Adapter?
- какие ports я использую?
- какие persistent структуры появляются?
- какая schema_version?
- какие инварианты защищаю тестами?
- как запустить без внешних сервисов?
- что будет в degraded mode?
- нужен ли audit?
- нужен ли governance decision?
- как это влияет на deployment?

## 25. Принцип безопасности смысла

Atman строит доверие не тем, что звучит убедительно, а тем, что сохраняет
происхождение смысла.

Поэтому любое значимое утверждение должно быть прослеживаемым:

```text
fact -> experience -> reflection -> identity/narrative/skill
```

Если цепочку нельзя восстановить, утверждение должно быть помечено как
гипотеза, uncertainty или presentation text, но не как устойчивое знание Atman.
