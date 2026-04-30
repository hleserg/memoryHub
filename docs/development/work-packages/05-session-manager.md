# 05 - Session Manager

## Агентское ТЗ

Разработать сессионный runtime, который запускает сессию с личностным контекстом, в процессе принимает события нижнего агента, фиксирует key moments с first-person окраской и завершает сессию передачей опыта в Experience Store.

## Архитектурный источник

- `docs/architecture/SYSTEM.md`: "Менеджер сессий", "Хранилище опыта", "Reality Anchor", "Affective Regulation".

## Границы пакета

Входит:

- `SessionContext` на старте: identity snapshot, narrative, emotional baseline, recent reflections.
- `SessionManager.start_session()`.
- `SessionManager.record_event()` для событий нижнего агента.
- `SessionManager.record_key_moment()` для окрашенных first-person моментов.
- `SessionManager.finish_session()` с созданием `SessionExperience`.
- CLI/демо-сценарий, который прогоняет искусственную сессию и пишет опыт в file storage.

Не входит:

- реальный OpenClaw;
- полноценный Reality Anchor и affect logic;
- фоновая рефлексия.

## Независимый runnable-результат

Должна быть команда, которая:

1. создает тестовую идентичность;
2. стартует сессию;
3. принимает несколько событий;
4. фиксирует минимум два key moments;
5. завершает сессию;
6. сохраняет `SessionExperience` с `recorded_by=session_manager`.

Пример:

```bash
python -m atman.session.demo --workspace /tmp/atman-demo
```

## Минимальные контракты

```python
class SessionManager:
    def start_session(self, user_id: str) -> SessionContext: ...
    def record_event(self, session_id: str, event: SessionEvent) -> None: ...
    def record_key_moment(self, session_id: str, moment: KeyMomentInput) -> None: ...
    def finish_session(self, session_id: str) -> SessionExperience: ...
```

`KeyMomentInput` обязан содержать эмоциональные поля из момента, а не вычислять их позже.

## Тесты

- старт сессии возвращает context с narrative/identity snapshot;
- key moment без emotional valence/intensity/depth отклоняется или помечает `incomplete_coloring`;
- завершение сессии создает `SessionExperience`;
- оригинальные key moments после сохранения не мутируются;
- resource/token warning может быть записан как обычный key moment.

## Критерии приемки

- Сессионный поток полностью работает без внешних сервисов.
- Experience Store получает уже окрашенный опыт, а не сырой лог.
- Неполная окраска явно видна через `incomplete_coloring`.
- Есть README с примером ручного запуска.

## Что проверить вручную

- Запустить demo CLI и открыть сохраненный JSON.
- Убедиться, что события и субъективная окраска различаются.
- Проверить, что завершение сессии можно вызвать повторно безопасно или оно явно запрещено.

