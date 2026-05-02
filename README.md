<img width="200" height="200" alt="logo" src="https://github.com/user-attachments/assets/e7269c6f-f81a-4982-afa3-ed45e8fd1f84" /> 

# Atman
> **Continuous Identity for Your Agents**

[[ru](README-ru.md)] — *Russian version*

*In Indian philosophy, Atman is the unchanging self, that which remains itself through all changes. Not a soul in the religious sense, but literally the "immutable core of identity". Atman is neither born nor dies — it simply is. For an agent that resets with each session, this is precisely what we give it.*

---

Your agent answers questions. But does it know *who it is*?

---

## What This Changes

Without Atman, the agent reads notes about itself every session — "you're like this, you have these values" — and takes them on faith. These aren't its memories. They're someone else's descriptions of it.

With Atman, the agent enters a session as an already-formed personality.

**What changes specifically:**

- The agent writes itself a letter at the end of each session and reads it at the very beginning of the next. Not a summary, not a memory dump — a living internal state.
- Values and principles are updated through lived experiences, not through manual file edits.
- If the agent starts speaking "out of character" under contextual pressure, it notices.
- Between sessions, the agent doesn't freeze. It reflects: finds patterns, clarifies who it is, maintains an internal life.

---

## How It Works

Two modes of existence.

**🌑 Between sessions** — background process. Experience from past sessions is processed, principles are refined, identity lives its own life. The agent isn't turned off — it's thinking.

**⚡ During a session** — meeting with the user happens on two levels simultaneously: the task is solved, and in parallel, self-observation occurs. The agent notices what's happening to it while it works.

Under the hood — seven components: store of lived experiences, reflection engine, identity anchor, session manager, emotional tone regulation. Atman manages the agent's control files directly — not through manual edits, but as a living process that knows what to write and when.

**Detailed architecture** → [`docs/architecture/SYSTEM.md`](docs/architecture/SYSTEM.md)  
**Manifesto** → [`MANIFEST.md`](MANIFEST.md)  
**Development standard** → [`docs/development/DEVELOPMENT_STANDARD.md`](docs/development/DEVELOPMENT_STANDARD.md)

---

## Roadmap

```
● Research              ✅ Complete
● Design                ✅ Complete
● Prototyping           ← We are here
  ├─ Factual Memory     ✅ Implemented (v0.1.0)
  ├─ Experience Store   ✅ Implemented (WP02)
  ├─ Identity Store     ⏳ In queue
  ├─ Reflection Engine  ⏳ In queue
  └─ Session Manager    ⏳ In queue
○ First implementation
○ Integration
○ Evolution
```

### Ready components

**✅ Factual Memory Adapter** ([PR #73](https://github.com/hleserg/atman/pull/73))  
Minimal layer for storing verifiable facts without interpretations.

- 📦 Models: `FactRecord`, `Relation`
- 🔌 Port: `FactualMemory` with unified API
- 💾 Adapters: InMemory + File (JSONL)
- ✅ Unit tests (see `pytest tests/`)
- 📚 [Guide (EN)](docs/features/factual-memory/README.md) · [RU](docs/features/factual-memory/README-ru.md)
- ▶️ Demo: `make demo-factual` or `python3 src/demo.py` (`make demo-factual-fast` for instant output; `make` sets pacing by default)

**✅ Experience Store** (work package 02)  
First-hand lived experience: `SessionExperience`, `KeyMoment`, salience decay, reframing notes — no retroactive emotional “guessing”.

- 📦 Domain models + `ExperienceService` + JSONL / in-memory adapters
- 💻 CLI: `atman-experience`
- 📚 [Guide (EN)](docs/features/experience-store/README.md) · [RU](docs/features/experience-store/README-ru.md)
- ▶️ Demo: `make demo-experience` or `python3 src/demo_experience_store.py` (`make demo-experience-fast` for instant output)

```bash
# Quick start (install + interactive factual CLI)
# Prefer uv: uv venv && source .venv/bin/activate && uv pip install -e ".[dev]"
pip install -e ".[dev]"
python3 -m atman.cli   # factual memory REPL (or: uv run python -m atman.cli)
pytest tests/ -v       # full test suite (or: uv run pytest tests/ -v)
```

See **`AGENTS.md`** (*uv — рекомендуемый workflow*) for `uv run` and venv tips.  
Contributing: [`CONTRIBUTING.md`](CONTRIBUTING.md) · Community standards: [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) · Security: [`SECURITY.md`](SECURITY.md).

---

## This Is Not Just a Tool

We're not building a better task runner. We're exploring an old question: **can an agent be a person?**

If so — what does that mean for how we create them?

> *This is the beginning of a conversation, not its end.*

---

## Contact

I welcome any communication, feedback, or exchange of ideas:

- Email: [hleserg@gmail.com](mailto:hleserg@gmail.com)
- Telegram: [@skhlebnikov](https://t.me/skhlebnikov)
