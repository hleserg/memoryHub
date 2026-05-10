## PLAYBOOK markers

- [ ] I introduced new generalizable patterns and added PLAYBOOK markers
- [ ] I introduced no generalizable patterns (pure refactoring / project-specific changes)
- [ ] I'm uncertain — flagged in the PR description for author review

*See `AGENTS.md` § "PLAYBOOK markers" and `docs/development/PLAYBOOK_MARKERS.md` for criteria.*

---

## Что сделано

Кратко: смысл изменений для ревьюера.

## Как воспроизвести (демонстрация)

Заполните, если PR меняет поведение для пользователя, CLI или добавляет существенную фичу (см. *Definition of Demo* в `docs/development/DEVELOPMENT_STANDARD.md`). Иначе: **N/A** и одна фраза почему.

- **Команда(ы):** (например `make demo-experience`, `make demo-experience-fast` без пауз, `python3 src/demo.py`, `pytest tests/test_….py -q`)
- **Ожидаемый результат:** что должно появиться в выводе / в файлах (кратко)
- **Фикстуры / данные:** пути к `fixtures/` или шаги подготовки
- **Интерактивный CLI:** если демо только через REPL (`atman-experience`), укажите 2–5 строк для копипаста

## Тип изменений

- [ ] Исправление ошибки
- [ ] Новая возможность / документация
- [ ] Рефакторинг (без смены поведения)
- [ ] Прочее:

## Карта системы

См. [`docs/architecture/SYSTEM_MAP.md`](../docs/architecture/SYSTEM_MAP.md) и `DEVELOPMENT_STANDARD.md` §26.

- **Затронутые разделы карты:** (например, «§1.3 — добавлен `…Service`; §2.1 — связка с `…Store`; §3 — новый сценарий H»; иначе **N/A**)
- **Покрытие тестами:** какие тесты закрывают каждый затронутый пункт карты (`tests/test_…py::test_…`)
- **Закрытые GAP'ы из §4.5:** какие edge-case пропуски закрыты (если применимо)
- **Карта обновлена:** [ ] `docs/architecture/SYSTEM_MAP.md` + [ ] `SYSTEM_MAP-ru.md` (или **N/A** с причиной)

## Тесты-страховки агентной разработки

См. `DEVELOPMENT_STANDARD.md` §26.5. Отметьте те, что были обновлены, или
оставьте **N/A** с обоснованием:

- [ ] `tests/test_state_store_contract.py` — изменён порт `StateStore` или добавлен адаптер
- [ ] `tests/test_serialization_roundtrip.py` — изменены поля персистируемых моделей
- [ ] `tests/test_golden_schema.py` — изменена сериализация модели (с описанием миграции)
- [ ] `tests/test_cli_roundtrip.py` — изменён путь/формат файла стораджа
- [ ] `tests/test_cli_all_commands.py` — добавлена/изменена CLI-команда
- [ ] `tests/test_domain_invariants.py` — изменён или добавлен бизнес-инвариант
- [ ] `tests/test_e2e_full_cli.py` — изменён состав/порядок шагов lifecycle §3 A–G

## Чеклист

- [ ] Описание соответствует фактическим изменениям
- [ ] При необходимости обновлены `README` / `docs` / демо-сценарий (отметьте N/A если не нужно)
- [ ] При необходимости обновлены `docs/architecture/SYSTEM_MAP.md` и `SYSTEM_MAP-ru.md` (см. секцию выше; N/A если PR не меняет модули/порты/адаптеры/сервисы/точки входа/сценарии/edge-cases/регрессии)
- [ ] `ruff check src/ tests/` — 0 ошибок (N/A если PR не затрагивает код)
- [ ] `ruff format --check src/ tests/` — 0 ошибок (N/A если PR не затрагивает код)
- [ ] `pyright src/ tests/` — 0 ошибок (N/A если PR не затрагивает код)
- [ ] `bandit -c pyproject.toml -r src/atman/` — 0 ошибок (N/A если PR не затрагивает код)
- [ ] `pytest tests/ -v --cov=atman --cov-fail-under=90` — тесты проходят, покрытие ≥90% (N/A если PR не затрагивает код)
- [ ] GitHub Actions CI зелёный или локальные проверки выше объясняют, почему CI не применим

## Примечания

Риски, обратная совместимость, что проверить вручную — по необходимости.
