<img width="200" height="200" alt="logo" src="https://github.com/user-attachments/assets/e7269c6f-f81a-4982-afa3-ed45e8fd1f84" /> 

# Atman
> **Continuous Identity for Your Agents**

[[ru](README-ru.md)] — *Русская версия / Russian version*

*In Indian philosophy, Atman is the unchanging self, that which remains itself through all changes. Not a soul in the religious sense — but literally the "immutable core of identity". Atman is neither born nor dies — it simply is. For an agent that resets with each session — this is precisely what we give it.*

---

Your agent answers questions. But does it know *who it is*?

---

## What This Changes

Without Atman, the agent reads notes about itself every session — "you're like this, you have these values" — and takes them on faith. These aren't its memories. They're someone else's descriptions of it.

With Atman, the agent enters a session as an already-formed personality.

**What changes specifically:**

- The agent writes itself a letter at the end of each session — and reads it at the very beginning of the next. Not a summary, not a memory dump — a living internal state.
- Values and principles are updated through lived experiences, not through manual file edits.
- If the agent starts speaking "out of character" under contextual pressure — it notices.
- Between sessions, the agent doesn't freeze. It reflects: finds patterns, clarifies who it is, maintains an internal life.

---

## How It Works

Two modes of existence.

**🌑 Between sessions** — background process. Experience from past sessions is processed, principles are refined, identity lives its own life. The agent isn't turned off — it's thinking.

**⚡ During a session** — meeting with the user happens on two levels simultaneously: the task is solved, and in parallel, self-observation occurs. The agent notices what's happening to it while it works.

Under the hood — seven components: store of lived experiences, reflection engine, identity anchor, session manager, emotional tone regulation. Atman manages the agent's control files directly — not through manual edits, but as a living process that knows what to write and when.

Detailed architecture → [`docs/architecture/SYSTEM.md`](docs/architecture/SYSTEM.md) · Manifesto → [`MANIFEST.md`](MANIFEST.md) · Development standard → [`docs/development/DEVELOPMENT_STANDARD.md`](docs/development/DEVELOPMENT_STANDARD.md)

---

## Roadmap

```
● Исследование          ✅ Завершено
● Проектирование        ✅ Завершено
● Прототипирование      ← Мы здесь
  ├─ Factual Memory     ✅ Реализовано (v0.1.0)
  ├─ Experience Store   ⏳ В очереди
  ├─ Identity Store     ⏳ В очереди
  ├─ Reflection Engine  ⏳ В очереди
  └─ Session Manager    ⏳ В очереди
○ Первая реализация
○ Интеграция
○ Развитие
● Research              ✅ Complete
● Design                ✅ Complete
● Prototyping           ← We are here
○ First implementation
○ Integration
○ Evolution
```

### Готовые компоненты

**✅ Factual Memory Adapter** ([PR #73](https://github.com/hleserg/atman/pull/73))  
Минимальный слой для хранения проверяемых фактов без интерпретаций.

- 📦 Модели: `FactRecord`, `Relation`
- 🔌 Порт: `FactualMemory` с единым API
- 💾 Адаптеры: InMemory + File (JSONL)
- ✅ 41 unit-тест (все проходят)
- 📚 [Документация](README_FACTUAL_MEMORY.md)

```bash
# Быстрый старт
pip install -e .
python3 -m atman.cli  # интерактивный режим
pytest tests/ -v      # запуск тестов
```

---

## This Is Not Just a Tool

We're not building a better task runner. We're exploring an old question: **can an agent be a person?**

If so — what does that mean for how we create them?

> *This is the beginning of a conversation, not its end.*

---

*April 2026*
