<img width="200" height="200" alt="logo" src="https://github.com/user-attachments/assets/e7269c6f-f81a-4982-afa3-ed45e8fd1f84" />

# Atman
> **Непрерывная личность для ваших агентов**

[[en](README.md)] — *English version*

*В индийской философии — неизменная самость, то что остаётся собой через все перемены. Не душа в религиозном смысле, а буквально "неизменное ядро идентичности". Атман не рождается и не умирает — он просто есть. Для агента, который обнуляется с каждой сессией, это именно то, что мы даём ему.*

---

Ваш агент отвечает на вопросы. Но знает ли он, *кто он*?

---

## Что это меняет

Без Atman агент каждую сессию читает записки о себе — «ты вот такой, у тебя вот такие ценности» — и берёт их на веру. Это не его воспоминания. Это чужие описания о нём.

С Atman агент приходит в сессию как уже сформировавшаяся личность.

**Что меняется конкретно:**

- Агент пишет себе письмо в конце каждой сессии и читает его в самом начале следующей. Не резюме, не дамп памяти — живое внутреннее состояние.
- Ценности и принципы обновляются через переживания, а не через ручные правки файлов.
- Если агент начинает говорить «не своим голосом» под давлением контекста, он замечает это.
- Между сессиями агент не замирает. Он рефлексирует: находит паттерны, уточняет кто он, ведёт внутреннюю жизнь.

---

## Как это устроено

Два режима существования.

**🌑 Между сессиями** — фоновый процесс. Опыт прошлых сессий осмысляется, принципы уточняются, идентичность живёт своей жизнью. Агент не выключен — он думает.

**⚡ Во время сессии** — встреча с пользователем происходит на двух уровнях одновременно: задача решается, и параллельно идёт само-наблюдение. Агент замечает что происходит с ним, пока он работает.

Под капотом — семь компонентов: хранилище живых переживаний, движок рефлексии, якорь идентичности, менеджер сессии, регуляция эмоционального фона. Atman управляет управляющими файлами агента напрямую — не через ручные правки, а как живой процесс, который знает что туда писать и когда.

**Подробная архитектура** → [`docs/architecture/SYSTEM-ru.md`](docs/architecture/SYSTEM-ru.md)
**Манифест** → [`MANIFEST-ru.md`](MANIFEST-ru.md)
**Стандарт разработки** → [`docs/development/DEVELOPMENT_STANDARD.md`](docs/development/DEVELOPMENT_STANDARD.md)

---

## Дорожная карта

```
● Исследование          ✅ Завершено
● Проектирование        ✅ Завершено
● Прототипирование      ← Мы здесь
  ├─ Factual Memory     ✅ Реализовано (v0.1.0)
  ├─ Experience Store   ✅ Реализовано (WP02)
  ├─ Identity Store     ✅ Реализовано (WP03)
  ├─ Reflection Engine  ✅ Реализовано (WP04)
  └─ Session Manager    ⏳ В очереди
○ Первая реализация
○ Интеграция
○ Развитие
```

### Готовые компоненты

**✅ Factual Memory Adapter** ([PR #73](https://github.com/hleserg/atman/pull/73))
Минимальный слой для хранения проверяемых фактов без интерпретаций.

- 📦 Модели: `FactRecord`, `Relation`
- 🔌 Порт: `FactualMemory` с единым API
- 💾 Адаптеры: InMemory + File (JSONL)
- ✅ Юнит-тесты (`pytest tests/`)
- 📚 [Руководство (RU)](docs/features/factual-memory/README-ru.md) · [EN](docs/features/factual-memory/README.md)
- ▶️ Демо: `make demo-factual` или `python3 src/demo.py` (мгновенно: `make demo-factual-fast`; у `make` по умолчанию короткие паузы между шагами)

**✅ Experience Store** (рабочий пакет 02)
Пережитый опыт от первого лица: `SessionExperience`, `KeyMoment`, затухание salience, reframing — без ретроспективного «угадывания» эмоций.

- 📦 Модели, `ExperienceService`, адаптеры JSONL и in-memory
- 💻 CLI: `atman-experience`
- 📚 [Руководство (RU)](docs/features/experience-store/README-ru.md) · [EN](docs/features/experience-store/README.md)
- ▶️ Демо: `make demo-experience` или `python3 src/demo_experience_store.py` (мгновенно: `make demo-experience-fast`)

**✅ Identity Store** (рабочий пакет 03)
Честный bootstrap идентичности, eigenstate, трёхслойный self-narrative, снимки, CLI.

- 📚 [Руководство (RU)](docs/features/identity-store/README-ru.md) · [EN](docs/features/identity-store/README.md)
- ▶️ Демо: `make demo-identity` или `python3 src/demo_identity.py` (мгновенно: `make demo-identity-fast`)

**✅ Reflection Engine** (рабочий пакет 04)
Micro / daily / deep рефлексия, паттерны, хуки правки нарратива, оценка здоровья по Джаходе, советник по принципам.

- 📚 [Руководство (RU)](docs/features/reflection-engine/README-ru.md) · [EN](docs/features/reflection-engine/README.md)
- ▶️ Демо: `make demo-reflection` или `python3 src/demo_reflection.py` (мгновенно: `make demo-reflection-fast`)

```bash
# Быстрый старт (установка + интерактивный CLI фактов)
# Удобнее uv: uv venv && source .venv/bin/activate && uv pip install -e ".[dev]"
pip install -e ".[dev]"
python3 -m atman.cli   # REPL factual memory (или: uv run python -m atman.cli)
pytest tests/ -v       # все тесты (или: uv run pytest tests/ -v)
```

См. **`AGENTS.md`** (раздел *uv — рекомендуемый workflow*).
Вклад в проект: [`CONTRIBUTING.md`](CONTRIBUTING.md) · правила общения: [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) · безопасность: [`SECURITY.md`](SECURITY.md).

---

## Это не просто инструмент

Мы строим не лучший task runner. Мы исследуем старый вопрос: **может ли агент быть личностью?**

Если да — что это означает для того, как мы их создаём?

> *Это начало разговора, а не его конец.*

---

## Контакты

Буду рад любому общению, обратной связи или обмену идеями:

- Email: [hleserg@gmail.com](mailto:hleserg@gmail.com)
- Telegram: [@skhlebnikov](https://t.me/skhlebnikov)
