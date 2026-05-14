# E1 Evaluation Runner Framework

## Назначение

E1 добавляет минимальный, но рабочий слой оркестрации бенчмарков в `src/atman/eval/`, сохраняя изоляцию от production runtime.

Ключевые цели:

- запуск бенчмарков через module-only CLI (`python -m atman.eval.benchmark_runner`)
- простой реестр бенчмарков (`registry.py` + decorator, без entry points)
- использование существующей eval-схемы БД (`eval.benchmark_runs`, `eval.run_items`) и хранение дополнительного контекста в `metadata` JSONB
- воспроизводимый локальный результат (JSONL reporter + demo script)

## Карта модулей

- `benchmark_runner.py` - Click CLI с командами `list` / `run`
- `runner_core.py` - lifecycle запуска и детерминированная app-level идемпотентность при наличии `git_sha`
- `run_context.py` - типизированный контекст запуска + `to_db_metadata()`
- `registry.py` - register/get/list бенчмарков
- `reporters/base.py` - протокол reporter'а
- `reporters/db_reporter.py` - запись в `eval.benchmark_runs` и `eval.run_items`
- `reporters/jsonl_reporter.py` - JSONL sink для локальных артефактов
- `seed_manager.py` - разрешение seed и применение глобального seed
- `hardware.py` - сбор CPU/memory/GPU с graceful fallback при отсутствии `psutil`/`pynvml` или NVML
- `benchmarks/noop.py` - smoke-бенчмарк для demo и CLI-проверок

## Использование CLI

Список бенчмарков:

```bash
python -m atman.eval.benchmark_runner list
```

Запуск бенчмарка:

```bash
python -m atman.eval.benchmark_runner run noop --git-sha "$(git rev-parse --short HEAD)" --jsonl-output /tmp/atman-eval.jsonl
```

Опциональная запись в БД (существующая eval-схема):

```bash
python -m atman.eval.benchmark_runner run noop --db-dsn "$POSTGRES_URL"
```

## Алиасы Makefile

- `make eval-list`
- `make eval-run`
- `make demo-eval-runner`
- `make demo-eval-runner-fast`

## Демонстрация

`src/demo_eval_runner.py` показывает:

1. обнаружение бенчмарков через registry
2. один запуск noop с JSONL-репортером
3. повторный запуск с тем же `git_sha`, возвращающий идемпотентный `skipped` outcome

Запуск:

```bash
make demo-eval-runner
```

## Примечания по безопасности/изоляции

- для eval runner не добавляются production entry points
- `atman.eval` остается optional и защищен dependency check
- `make lint-boundary` и `make verify-prod-isolation` остаются обязательными gate-проверками
