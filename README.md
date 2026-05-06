<img width="200" height="200" alt="logo" src="https://github.com/user-attachments/assets/e7269c6f-f81a-4982-afa3-ed45e8fd1f84" />

# Atman
>
> **Continuous Identity for Your Agents**

[![CI](https://github.com/hleserg/atman/actions/workflows/ci.yml/badge.svg)](https://github.com/hleserg/atman/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

**Tests:** 568 passing (`pytest tests/` on `main`; see CI workflow above).

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
**Side-by-side: Atman vs. a standard agent** → [`docs/research/agent-thinking-comparison.md`](docs/research/agent-thinking-comparison.md)
**Development standard** → [`docs/development/DEVELOPMENT_STANDARD.md`](docs/development/DEVELOPMENT_STANDARD.md)

---

## Roadmap

```text
● Research              ✅ Complete
● Design                ✅ Complete
● Prototyping           ← We are here
  ├─ Factual Memory     ✅ Implemented (v0.1.0)
  ├─ Experience Store   ✅ Implemented (WP02)
  ├─ Identity Store     ✅ Implemented (WP03)
  ├─ Reflection Engine  ✅ Implemented (WP04)
  ├─ Session Manager    ✅ Implemented (WP05)
  └─ CI & test coverage ✅ GitHub Actions on `main`/PRs (`make check`, pytest-cov ≥90%)
○ First implementation
○ Integration
○ Evolution
```

### Ready components

- 🌐 **Site — terminal demos:** [atmanai.dev/demo.html](https://atmanai.dev/demo.html) (RU/EN toggle matches the main landing)

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

**✅ Identity Store** (work package 03)
Honest bootstrap identity, eigenstate, three-layer self-narrative, snapshots, CLI.

- 📚 [Guide (EN)](docs/features/identity-store/README.md) · [RU](docs/features/identity-store/README-ru.md)
- ▶️ Demo: `make demo-identity` or `python3 src/demo_identity.py` (`make demo-identity-fast` for instant output)

**✅ Reflection Engine** (work package 04)
Micro / daily / deep reflection, patterns, narrative revision hooks, Jahoda health assessment, principle advisor.

- 📚 [Guide (EN)](docs/features/reflection-engine/README.md) · [RU](docs/features/reflection-engine/README-ru.md)
- ▶️ Demo: `make demo-reflection` or `python3 src/demo_reflection.py` (`make demo-reflection-fast` for instant output)

**✅ Session Manager** (work package 05)
Real-time session runtime: first-hand experience coloring, key moments with mandatory emotional marking, eigenstate generation, narrative updates.

- 📚 [Guide (EN)](docs/features/session-manager/README.md) · [RU](docs/features/session-manager/README-ru.md)
- ▶️ Demo: `make demo-session` or `python3 src/demo_session_manager.py` (`make demo-session-fast` for instant output)

```bash
# Quick start (install + interactive factual CLI)
# Prefer uv: uv venv && source .venv/bin/activate && uv pip install -e ".[dev]"
pip install -e ".[dev]"
python3 -m atman.cli   # factual memory REPL (or: uv run python -m atman.cli)
pytest tests/ -v       # full test suite (or: uv run pytest tests/ -v)
```

See **`AGENTS.md`** (*uv — рекомендуемый workflow*) for `uv run` and venv tips.
Contributing: [`CONTRIBUTING.md`](CONTRIBUTING.md) · Community standards: [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) · Security: [`SECURITY.md`](SECURITY.md).

## Safety & alignment

For safety reviewers and alignment work: how major Atman building blocks map to drift detection, self-model stability under pressure, honest vs. retrospective experience claims, metacognition, and multi-criterion welfare checks — see [`docs/research/safety-relevance.md`](docs/research/safety-relevance.md).

---

## This Is Not Just a Tool

We're not building a better task runner. We're exploring an old question: **can an agent be a person?**

If so — what does that mean for how we create them?

> *This is the beginning of a conversation, not its end.*

---

## Contact

I welcome any communication, feedback, or exchange of ideas:

- Email: [hello@atmanai.dev](mailto:hello@atmanai.dev)
- Telegram: [@skhlebnikov](https://t.me/skhlebnikov)
