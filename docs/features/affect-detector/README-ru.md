# Affect Detector (E21)

Поведенческий слой: восемь метрик по тексту (NRC + лексические эвристики), скользящий z-score baseline в JSONL и добавление помеченных `KeyMoment` через `SessionManager.append_key_moment` — единственный write-only путь автоматического affect-capture.

## Область

- **Входит:** `src/atman/affect/*`, опциональная проводка в `SessionManager` (`affect_workspace` + `AffectDetectorConfig`), async-хук после `record_event`, инструмент агента `record_key_moment` → `AffectDetector.submit_self_report`.
- **Не входит:** новые таблицы SQL, LLM-искренность (`use_llm_analysis=True` → `NotImplementedError`), чтение/запросы к `key_moments`.

## Конфигурация

| Поле | По умолчанию | Заметки |
|------|----------------|---------|
| `default_lang` | `"ru"` | Для коротких строк. **Перед продакшеном на английском агенте поставьте `"en"`**. |
| `cold_start_sessions` | `10` | Первые *N* различных `session_id` подавляют триггеры аномалии / random-sample / divergence; baseline всё равно обновляется. |
| `sigma_threshold` / `strong_signal_threshold` | `2.0` / `2` | Считаем метрики с \|z\| > sigma; аномалия при count ≥ порога. |
| `random_sample_every_n` | `5` | Счётчик на каждый `process()`; каждый *n*-й вызов добавляет `affect:random-sample` вне cold start. |
| `divergence_threshold` | `25.0` | \|NRC(сообщение) − NRC(thinking)\|; нужен `SessionEvent.thinking`. |
| `min_text_length` | `12` | Пропуск `process()`, если текст короче, **если** нет `!`. |

Baseline: `{affect_workspace}/affect_baseline.jsonl`.

## Теги на `KeyMoment`

- `affect:anomaly`, `affect:random-sample`, `affect:self-report`, `affect:divergence`

Данные — в `KeyMoment.context_halo`: `description="atman:affect-detector"`, в `metadata` ключи `tags`, `trigger_reason`, `says_writes`, `demonstrates_thinks`, `divergence_score`.

## Session Manager

```python
from pathlib import Path
from atman.affect.detector import AffectDetectorConfig
from atman.core.services import SessionManager

mgr = SessionManager(
    store,
    affect_workspace=Path("/tmp/agent_ws"),
    affect_config=AffectDetectorConfig(),
)
```

`SessionManager.record_key_moment` удалён; при вызове — `AttributeError` с отсылкой к `AffectDetector`. Для тестов и программных сценариев — `append_key_moment_input`.

## CLI-демо

```bash
PYTHONPATH=src python -m atman.affect.detector --demo
```

Берёт `fixtures/affect_demo_responses.txt`, печатает JSON key moments в stdout.

## Тесты

```bash
pytest tests/affect/ -v --tb=short
mypy --strict src/atman/affect/
```

## Ссылки

- Манифест: расхождение self-report vs объективный слой как наблюдаемая аутентичность.
- Лексикон NRC (Mohammad & Turney 2013) в `affect/emolex/`.
