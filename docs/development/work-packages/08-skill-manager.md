# WP-08: Skill Manager

## Задача для агента

Реализуй слой управления навыками Atman: Skill Library, дистрибутивы навыков, активные/пассивные навыки, версионирование, зависимости, отключение и garbage collection. Пакет должен работать без Session Manager и Reflection Engine.

Источник архитектуры: `docs/architecture/SYSTEM.md`, разделы "Память навыков", "Система управления навыками" и "Skill Garbage Collection".

## Цель

Получить запускаемый менеджер навыков, который:

- хранит описания навыков и их дистрибутивы;
- различает active, passive, core, session-scoped, dormant и disabled состояния;
- умеет планировать установку/обновление/удаление навыков в workspace агента;
- сохраняет disabled state и не восстанавливает отключенные навыки самовольно;
- удаляет session-scoped и давно неиспользуемые навыки по правилам decay.

## Границы

Входит:

- модель `SkillManifest`;
- file-based skill registry;
- dependency resolver;
- installer/uninstaller для workspace directory;
- inventory checker: expected vs installed vs used;
- CLI:
  - `skills list`;
  - `skills install <name>`;
  - `skills disable <name>`;
  - `skills gc`;
  - `skills status`;
- тесты зависимостей, отключения и garbage collection.

Не входит:

- генерация самих навыков LLM;
- Ambient Memory Layer;
- реальное изменение SOUL.md/AGENTS.md вне тестового workspace.

## Минимальные контракты

```python
class SkillKind(str, Enum):
    active = "active"
    passive = "passive"

class SkillState(str, Enum):
    installed = "installed"
    disabled = "disabled"
    dormant = "dormant"
    removed = "removed"

class SkillManifest(BaseModel):
    name: str
    version: str
    kind: SkillKind
    core: bool = False
    session_scoped: bool = False
    dependencies: list[str] = []
    decay_sessions: int = 10
    entry_files: list[str]

class SkillUsage(BaseModel):
    skill_name: str
    last_used_at: datetime | None
    sessions_since_use: int = 0
```

## Реализация

1. **Registry**
   - хранит skill manifests в `skills/<name>/SKILL.toml`;
   - валидирует обязательные поля;
   - умеет искать зависимости рекурсивно.
2. **Workspace inventory**
   - читает `.atman/skills-state.json` в workspace агента;
   - определяет установленные версии;
   - фиксирует disabled skills.
3. **Installer**
   - копирует entry files в workspace;
   - обновляет state;
   - не ставит disabled skills;
   - ставит зависимости перед основным skill.
4. **Garbage collection**
   - удаляет session-scoped skills после завершения сессии;
   - переводит active skill в dormant после N сессий без использования;
   - удаляет dormant после следующего N;
   - никогда не удаляет passive/core skills.
5. **AGENTS/SOUL planning**
   - генерирует patch plan в JSON: что нужно добавить в AGENTS.md и SOUL.md;
   - не обязан применять патчи в реальные файлы.

## Самостоятельная проверка

Команды:

```bash
python -m atman.skills status --workspace ./tmp/workspace
python -m atman.skills install session-wrap-up --workspace ./tmp/workspace
python -m atman.skills gc --workspace ./tmp/workspace
pytest tests/test_skills.py
```

## Приемка

- `install` разворачивает skill и зависимости в тестовый workspace.
- `disable` сохраняет запрет, последующий `install passive` не восстанавливает отключенный skill.
- `gc` удаляет session-scoped skill.
- `gc` не удаляет passive/core skills.
- State-файл читаемый и пригоден для ручной диагностики.

## Независимость

Пакет использует только файловую систему. Он может быть протестирован без памяти, сессий, reflection runner и LLM.
