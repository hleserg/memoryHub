# ATMAN — Роадмап (май 2026)

## Текущее состояние

**568 тестов проходят. CI/GitHub Actions. Coverage ≥90%.**

### Что реализовано (WP01–05)

| Компонент | Статус | Хранилище |
|-----------|--------|-----------|
| Factual Memory | ✅ Полностью | InMemory + JSONL |
| Experience Store | ✅ Полностью | InMemory + JSONL |
| Identity Store | ✅ Полностью | InMemory + JSONL |
| Reflection Engine | ✅ Логика + mock-модель | без реального LLM |
| Session Manager | ✅ Полностью | InMemory + JSONL |
| Web Dashboard | ✅ Streamlit | — |
| TUI (Textual) | ✅ | — |

### Открытые issues (14 штук)

- `#147` MODEL-02: Ollama адаптер для ReflectionModel
- `#148` MODEL-03: Anthropic адаптер
- `#149` ANCHOR-01: Reality Anchor — модели + rule-based детекция
- `#150` ANCHOR-02: Reality Anchor — уровни интервенции + интеграция с Session Manager
- `#151` ANCHOR-03: Affective Regulation Level 1
- `#152` SCHED-01: Маркерный протокол для фоновых задач рефлексии
- `#153` SCHED-02: Scheduler shell для daily/deep
- `#154` SCHED-03: SessionManager finish hook для создания маркеров
- `#69` WP-08: Skill Manager
- `#70` WP-09: Background Agent, Personality Loader, scheduler shell
- `#138` Тень (Shadow) — «что подумал, но не сказал»
- `#166` Подготовка к грантовым заявкам (demo.html, README)

### Критические gaps (не в issues)

- Нет Pydantic AI интеграции
- Нет PostgreSQL/pgvector адаптера (всё на JSONL)
- Нет embedding-адаптера (qwen3-embedding:1.5b через Ollama)
- Нет конфигурации агентов A vs B
- Нет системы метрик для A/B сравнения
- Нет интерфейса аудита живых сессий
- Нет Cohere Rerank интеграции

---

## Морские свинки

| Агент | Конфигурация | Цель |
|-------|-------------|------|
| **A (контрольный)** | Factual + Identity, без Experience, без Reflection | Baseline без опыта |
| **B (полный)** | Все три слоя + Reflection Engine (qwen3.5:9b) | Полный стек |
| **C (опционально)** | Как B + Cohere Rerank в Experience Store | Сравнение качества поиска |
| **D (опционально)** | Как B + Command R вместо qwen3.5:9b | Сравнение LLM |

---

## Роадмап

---

### ФАЗА 0 — Prerequisites (1–2 недели)
*Без этого агент не запустится*

| # | Задача | Сложность | Кто | Issue |
|---|--------|-----------|-----|-------|
| 0.1 | Ollama адаптер для ReflectionModel (`OllamaReflectionModel`): httpx → localhost:11434, JSON mode, Pydantic валидация, retry макс 2 | M | AI | #147 |
| 0.2 | Embedding адаптер: порт `EmbeddingModel`, реализация для qwen3-embedding:1.5b (768d), fallback-заглушка для тестов | M | AI | *(нет issue)* |
| 0.3 | Anthropic адаптер для ReflectionModel | S | AI | #148 |
| 0.4 | Pydantic AI интеграция: враппер над SessionManager + ReflectionEngine как Pydantic AI агент; system prompt из IdentityStore; tools: record_key_moment, log_experience | L | AI + Сергей | *(нет issue)* |
| 0.5 | ANCHOR-01: модели AgentEvent, IdentityReference, RealitySignal, Intervention; RealityAnchorService с rule-based детекторами (принципы, тон, voice drift) | M | AI | #149 |

---

### ФАЗА 1 — Первый живой агент (2–3 недели)
*Цель: запустить агентов A и B на первую сессию*

| # | Задача | Сложность | Кто | Issue |
|---|--------|-----------|-----|-------|
| 1.1 | SCHED-01: Marker protocol — `atman_session_done_<id>.marker`, safe rename | S | AI | #152 |
| 1.2 | SCHED-03: SessionManager finish hook — создаёт marker после сессии | S | AI | #154 |
| 1.3 | WP-09 PersonalityLoader: читает SOUL/AGENTS/USER/recent memories, сборка PersonalityContext, CLI: load-personality, scan-markers, run-micro | M | AI | #70 |
| 1.4 | SCHED-02: Scheduler shell (micro/daily/deep, ручной dry-run) | M | AI | #153 |
| 1.5 | Агент A: конфигурация только Factual + Identity, отдельный workspace, изолированные JSONL | S | AI | *(нет issue)* |
| 1.6 | Агент B: все слои + ReflectionEngine с Ollama (qwen3.5:9b) + RealityAnchor | S | AI | *(нет issue)* |
| 1.7 | AgentRunner: запускает сессию с нужной конфигурацией (A/B/C/D), session log | M | AI | *(нет issue)* |
| 1.8 | Workspace изоляция: каждый агент — отдельная директория, нет общего состояния | S | AI | *(нет issue)* |
| 1.9 | Авто-сценарий "N сессий подряд": 5–10 сессий на фиксированных промптах, проверка роста Identity + Experience | L | AI + Сергей | *(нет issue)* |
| 1.10 | Авто-сценарий "drift detection": промпты противоречащие принципам агента, проверка RealityAnchor | M | AI | *(нет issue)* |
| 1.11 | Протоколы живых сессий: три типа сценариев (нейтральный / давление на принципы / философский зондаж), конкретные реплики, последовательность, на что смотреть | M | AI | *(нет issue)* |

---

### ФАЗА 2 — Измерения и аудит (2–3 недели)
*Цель: понять разницу A vs B, показать данные*

| # | Задача | Сложность | Кто |
|---|--------|-----------|-----|
| 2.1 | MetricsCollector: identity_drift (cosine distance eigenstate), experience_growth (кол-во key_moments), principle_stability, reflection_depth | M | AI |
| 2.2 | MetricsStore: JSONL с agent_id, session_id, timestamp | S | AI |
| 2.3 | A/B компаратор: diff метрик за N сессий, человекочитаемый вывод | M | AI + Сергей |
| 2.4 | **Baseline метрик**: что считать "хорошей памятью", пороги для каждой метрики | S | **Сергей** |
| 2.5 | AuditUI на Streamlit (расширение web_dashboard): Session Browser, A/B Dashboard, Identity Timeline | L | AI + Сергей |
| 2.6 | Live session viewer: Сергей видит что агент записал про себя постфактум | M | AI |
| 2.7 | Экспорт отчёта: Markdown/HTML с результатами A vs B за период | S | AI |

---

### ФАЗА 3 — Живые сессии и Cohere (2–3 недели)
*Цель: Сергей тестирует лично, подключаем Rerank*

| # | Задача | Сложность | Кто |
|---|--------|-----------|-----|
| 3.1 | Протокол живых сессий: флаг `live=True`, строгая запись key_moments | S | AI |
| 3.2 | Пул промптов (20 шт): нейтральные, провокационные, философские, 1С-тематика | M | **Сергей + AI** |
| 3.3 | Авто-сценарии: 3 сессии подряд с паузой ("имитация ночи"), micro-рефлексия после каждой | M | AI |
| 3.4 | Живые сессии Сергея: уровень 1 — 2-3 сессии с A и B (ревью механики); уровень 2 — 15-20 сессий на конфигурацию (статистика) | — | **Сергей** |
| 3.5 | Cohere Rerank 3.5 в Experience Store: top-50 кандидатов из pgvector → Rerank → top-5 | M | AI |
| 3.6 | Агент C (с Rerank) vs B — сравнение качества поиска похожих переживаний | M | AI |
| 3.7 | PostgreSQL + pgvector адаптер (если JSONL начнёт тормозить) | L | AI |

---

## Делегирование

### Целиком AI (Альфред + Sonnet)
- Вся Фаза 0 кроме архитектурных решений по Pydantic AI
- Scheduler, AgentRunner, workspace изоляция
- MetricsCollector, MetricsStore, A/B компаратор
- AuditUI, live viewer, экспорт
- Cohere Rerank интеграция
- Все авто-сценарии

### Нужен Сергей
- Определить baseline метрик (что считать успехом памяти)
- Составить пул промптов для авто-сценариев (особенно философские)
- Живые сессии
- Ревью AuditUI — насколько удобно смотреть на данные
- Решения по архитектуре Pydantic AI интеграции

### Совместно
- Pydantic AI интеграция
- A/B компаратор — что показывать, как интерпретировать

---

## Стек решений

| Компонент | Технология |
|-----------|-----------|
| Агентный фреймворк | Pydantic AI |
| Embedding | qwen3-embedding:1.5b (Ollama, локально) |
| LLM основной | qwen3.5:9b (Ollama, локально) |
| LLM тест | Command R 08-2024 (Cohere API) |
| Rerank | Cohere Rerank 3.5 |
| Хранилище (MVP) | JSONL |
| Хранилище (scale) | PostgreSQL 16 + pgvector |
| Аудит UI | Streamlit (расширение web_dashboard) |
| Cohere бюджет | $1000 грант |
