# Agent Adapter

**Статус:** WIP — только основа (E26, sub-issues #398–#400)
**Назначение:** обёртка на базе Pydantic AI, превращающая сервисы Atman в исполняемого LLM-агента.

[[en](README.md)] — *English version*

---

## Обзор

Agent adapter (`src/atman/adapters/agent/`) — планируемая LLM-ориентированная
поверхность Atman. Когда работа будет завершена, LLM сможет проводить
сессии через `SessionManager`, собирать system prompt из текущего
`Identity` / `NarrativeDocument` и вызывать типизированные инструменты
(запись key moments, логирование опыта, запросы к памяти и т.д.) — при
этом всё выполнение опосредуется существующими core-сервисами и портами.

Этот work-package поставляется поэтапно. **Этот PR (#413) приносит только
основу** — целостного end-to-end демо пока намеренно нет, потому что
runner агента, который связывает `Agent(deps=AtmanDeps,
instructions=…)` и фактически ведёт сессию через LLM-провайдера, —
тема следующего sub-issue. Поставляемые здесь куски юнит-тестируемы
изолированно и покрыты в `tests/test_agent_config.py`,
`tests/test_instructions.py`, `tests/test_tools.py`.

Сервисы, которые этот адаптер оборачивает, уже имеют собственные
запускаемые демо — см. `make demo-session`, `make demo-identity`,
`make demo-reflection`, `make demo-full-corpus`.

---

## Что входит в этот PR

| Модуль | Публичная поверхность | Роль |
|--------|-----------------------|------|
| `adapters/agent/config.py` | `ModelConfig`, `AgentConfig` | Pydantic-валидируемый runtime-конфиг: модель + провайдер, бюджет инструментов, бюджеты обрезания нарратива (E26-R1, E26-R2, E26-R4) |
| `adapters/agent/deps.py` | `AtmanDeps`, `AtmanDeps.from_config(...)` | Замороженный DI-контейнер: `SessionManager` / `IdentityService` / `ExperienceService` / `MicroReflectionService` / `StateStore` + runtime `agent_id` и (опциональный) `session_id`. `from_config(...)` собирает его из провалидированного `AgentConfig`. |
| `adapters/agent/instructions.py` | `build_instructions(deps)` | Загружает текущие `Identity` + `NarrativeDocument` и рендерит динамический system prompt с посекционными бюджетами символов, чтобы не выйти за context window модели. При отсутствии identity использует «bootstrap» prompt. |
| `adapters/agent/tools.py` | `record_key_moment`, `log_experience` | Tool-callback'и Pydantic AI. `record_key_moment` полностью подключён к `SessionManager.record_key_moment`; `log_experience` — заглушка-редирект, направляющая LLM на session-end flow до прихода direct-log пути. |

Два обобщаемых паттерна задокументированы прямо в коде как `PLAYBOOK`-маркеры:

- `error-returning-tool-callbacks` (в `tools.py`) — tool-callback возвращает строку ошибки вместо raise, чтобы LLM мог исправить вызов.
- `dynamic-prompt-from-state-with-truncation` (в `instructions.py`) — рендеринг system prompt из persistent state на каждый запуск с посекционными бюджетами обрезания.

---

## Что отложено (последующие sub-issues)

- **Agent runner.** Связать `pydantic_ai.Agent(model=…, deps_type=AtmanDeps, instructions=lambda ctx: build_instructions(ctx.deps), tools=[record_key_moment, log_experience, …])` с CLI entry-point и таргетом `make demo-agent`. Runner стартует сессию через `SessionManager`, прикрепит `session_id` к свежим `AtmanDeps`, запустит агента и завершит сессию.
- **Direct-log путь для `log_experience`.** Сейчас инструмент возвращает редирект-сообщение; когда runner появится, он должен напрямую вызывать `ExperienceService` для out-of-band опыта.
- **Энфорсмент бюджета инструментов.** `AgentConfig.max_tool_calls` валидируется и переносится в `AtmanDeps`, но пока не энфорсится — runner sub-issue будет ограничивать диспатч инструментов на его основе (митигация E26-R4).
- **Tool'ы запросов identity / experience.** `enable_experience_search` и `get_identity_snapshot`-подобные инструменты запланированы, но не входят в этот PR.
- **Живое демо.** Walkthrough `docs/features/agent-adapter/` и таргет `make demo-agent` будут добавлены вместе с runner'ом.

---

## Тесты

```bash
# Юнит-тесты модулей основы:
pytest tests/test_agent_config.py tests/test_instructions.py tests/test_tools.py -v

# Полный quality-gate проекта:
make check
```

Покрытие новых модулей: `adapters/agent/config.py` 100%, `adapters/agent/tools.py` 100%, `adapters/agent/instructions.py` ~96%, `adapters/agent/deps.py` ~77% (непокрытые строки — блок импортов под `TYPE_CHECKING`).
