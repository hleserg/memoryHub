# WP-03: Identity Store, Eigenstate и Self-Narrative

## Цель

Сделать самостоятельный модуль живого самоописания Atman: структурированная идентичность, eigenstate последней сессии, открытые вопросы и `NARRATIVE.md` как first-person письмо для следующего запуска.

## Архитектурная опора

- `Identity Store` из `SYSTEM.md`.
- `Bootstrap - откуда берется первая идентичность`.
- `Self-Narrative`, `Eigenstate`, `Uncertainty Store` из архитектурных решений внутри `SYSTEM.md`.

## Независимость

Не ждать реализации Experience Store или Reflection Engine. Для входных данных использовать:

- JSON-файлы с identity/eigenstate/uncertainty;
- моковый список недавних переживаний;
- file workspace adapter для чтения/записи `NARRATIVE.md`, `SOUL.md`, `USER.md`.

## Что реализовать

1. Модели:
   - `Identity`;
   - `CoreValue`;
   - `Habit`;
   - `Principle`;
   - `Goal`;
   - `OpenQuestion`;
   - `IdentitySnapshot`;
   - `Eigenstate`;
   - `NarrativeDocument`.
2. Identity Store:
   - создать пустую bootstrap-identity без навязанных seed-принципов;
   - обновлять ценности, привычки, принципы, цели и вопросы;
   - делать snapshot при значимом изменении;
   - читать актуальную версию.
3. Narrative manager:
   - хранить трехслойную структуру: `CORE LAYER`, `RECENT LAYER`, `THREADS`;
   - генерировать/обновлять `NARRATIVE.md` из identity + eigenstate + active uncertainties;
   - архивировать старый нарратив перед заменой;
   - валидировать first-person стиль базовыми правилами.
4. CLI:
   - `identity init`;
   - `identity show`;
   - `identity snapshot`;
   - `narrative render`;
   - `narrative validate`.

## Запускаемый результат

Минимальный demo:

```bash
identity init --workspace ./demo-workspace
narrative render --workspace ./demo-workspace --eigenstate fixtures/eigenstate.json
narrative validate ./demo-workspace/NARRATIVE.md
```

После запуска в demo workspace должны появиться:

- `identity.json`;
- `NARRATIVE.md`;
- архив предыдущих нарративов после повторного render.

## Тесты

- Bootstrap создает честную пустую identity: есть self-description о недостатке данных, нет фальшивых принципов.
- Snapshot сохраняет прошлую версию и не мутирует ее.
- Narrative содержит обязательные секции.
- Narrative написан от первого лица и не содержит формулировок вида "агент сделал".
- Recent layer заменяется, core layer сохраняется без явного флага.
- Threads не удаляются молча: закрытие должно быть явным.

## Критерии приемки

- Модуль работает без LLM и внешних сервисов.
- `NARRATIVE.md` можно читать первым при старте агента как самостоятельный управляющий файл.
- Identity и Narrative имеют явные схемы и тесты миграционно-опасных полей.
- В README модуля описано, как в будущем подключить Experience Store и Reflection Engine.

## Не делать в этом пакете

- Не реализовывать deep reflection.
- Не строить полноценный relation memory.
- Не генерировать "красивую личность" из воздуха при bootstrap.

