# Playbook Audit: Atman → agent-playbook

**Date:** 2026-05-07  
**Author:** Cursor Cloud Agent  
**Purpose:** Identify generalizable patterns from Atman implementation for agent-playbook enrichment  

---

## Section A: What Already Exists in agent-playbook

Current version: **0.1.0** (2026-04-30). 5 core patterns + 2 guides + 7 templates. All patterns focus on **process management of AI-agent workflows** — how to organize work, assign tasks, review results, isolate environments, and transfer context.

### Core Patterns (5)

| # | Title | Category | Problem Solved |
|---|-------|----------|----------------|
| 01 | Agent Rules Structure | Foundation | How to organize documentation so agents work consistently |
| 02 | Issue-to-PR Workflow | Process | Async task assignment and review via GitHub without direct access |
| 03 | Strategic Review | Governance | Maintaining architectural coherence across parallel agent contributions |
| 04 | Environment Isolation | Infrastructure | Preventing interference between parallel agents (Docker/worktrees) |
| 05 | Context Handoff | Coordination | Transferring knowledge between agents or across agent sessions |

### Supporting Guides (2)

- **Definition of Done for Agents** — completing criteria, type-specific DoD (features/bugs/refactoring/docs)
- **Common Agent Failure Modes** — context loss, over-engineering, test theater, boundary violations

### Templates (7)

AGENTS.md, DEVELOPMENT_STANDARD.md, PR template, Feature Request, Bug Report, Work Package, issue templates directory

### Gap Analysis

The playbook covers **process patterns only** — how humans manage agents. It has **no technical design patterns** — how to architect systems that agents build. All patterns would apply to any software project; none are specific to the domain of building autonomous systems or LLM-powered components.

---

## Section B: What is in Atman, Valuable for the Playbook, Not Covered by Existing Patterns

The following patterns were identified from Atman's implementation. Each is stated in project-neutral terms and passes the **substitution test** (description makes sense without Atman-specific words).

### B-01: Idempotent Long-Running Operations via Deterministic Run Keys

**Source:** `docs/features/reflection-engine/README.md` — Operational Contracts; `src/atman/core/services/reflection/`

**Description:** Compute a deterministic `run_key` from the operation's input parameters (date, scope, identity snapshot id). Before executing side effects, check whether a terminal success event with this key already exists in the event store. If yes — return the existing result; if no — execute and persist the success event atomically. The operation becomes safe to retry, replay, and schedule redundantly.

**Why generalizable:** Any long-running job (batch processing, scheduled LLM calls, nightly aggregations, webhook processing) needs this. Exception-based "just catch and retry" loses context; mutable "update a flag" creates race conditions. Deterministic keys solve both.

---

### B-02: Append-Only Records with Annotation Layers

**Source:** `docs/features/experience-store/README.md` — Key Principles §2; `docs/features/reflection-engine/README.md` — Design Decision §2

**Description:** Original records are immutable after creation (no update methods on the core model). Derived perspectives — corrections, reframings, commentary — accumulate in a separate append-only list (`reframing_notes`). Callers always see both the original and all annotations; they can choose which view to use.

**Why generalizable:** Any domain where original records have audit or authenticity value: medical records, financial ledgers, legal documents, content moderation decisions, ML training labels. Mutation loses the "what actually happened" layer. This pattern keeps both.

---

### B-03: Port + Deterministic Mock Adapter for LLM-Dependent Logic

**Source:** `docs/features/reflection-engine/README.md` — Design Decision §1; `src/atman/adapters/reflection/mock_reflection_model.py`

**Description:** Define an abstract port (`ReflectionModel`) that the service depends on. Provide a `MockReflectionModel` that returns template-based, fully deterministic responses based on input content. The mock is not a spy or a stub — it produces semantically meaningful output without any network calls or stochastic behavior. All business logic, including LLM output parsing, error paths, and result routing, is tested against the mock.

**Why generalizable:** Any feature that calls an LLM, embedding model, or other probabilistic service. Without deterministic mocks, tests either skip the integration entirely (low confidence) or hit real APIs (slow, expensive, flaky). This pattern provides a third path: full integration test coverage at unit test speed.

---

### B-04: First-Hand vs Retrospective Data Capture

**Source:** `docs/features/session-manager/README.md` — Key Design Principles §1; `docs/architecture/SYSTEM.md` — Critical change 28.04.2026

**Description:** Capture contextual metadata (emotional state, cognitive load, uncertainty level) **at the moment the event occurs**, not by reconstructing it later from logs. If capture is impossible in the moment, mark the record explicitly as `incomplete_coloring=True` — an honest fallback that preserves what was captured. Retrospective reconstruction is prohibited and produces systematically biased data.

**Why generalizable:** Monitoring systems, user feedback, system observability, any domain where subjective or ephemeral context matters. Post-hoc labeling of events is cheap to implement but produces lower-quality signals. Real-time capture + honest incompleteness flag is harder but produces authentic records.

---

### B-05: Outcome-Coded Events as Control Flow Alternative

**Source:** `docs/features/reflection-engine/README.md` — Operational Contracts (example notes values); `src/atman/core/models/reflection.py`

**Description:** Instead of raising exceptions for predictable non-error outcomes (nothing to process, prerequisite not met, already done), persist an event with a structured `outcome` field: `outcome=daily_ok`, `outcome=daily_skipped reason=no_identity`, `outcome=daily_empty reason=no_experiences`. The outcome acts as a terminal state. Callers, schedulers, and monitoring dashboards can query the event store instead of parsing exception logs.

**Why generalizable:** Scheduled jobs, async pipelines, multi-stage workflows. Exceptions are the wrong primitive for "nothing to do today" — they pollute error logs, complicate retry logic, and prevent offline analysis. Outcome-coded events are structured, queryable, and carry semantic meaning.

---

### B-06: Layered Document Volatility (Core / Recent / Threads)

**Source:** `docs/features/identity-store/README.md` — Key Principles §3; `src/atman/core/models/narrative.py`

**Description:** Structure a living document into layers with explicit volatility contracts: (1) a **core layer** that changes rarely and requires deliberate action; (2) a **recent layer** that is replaced completely after each update cycle; (3) **threads** — named storylines with an explicit lifecycle (opened, updated, closed with reason). Each layer has a different write path, different retention, and different reading semantics.

**Why generalizable:** Any system that maintains a "current state" document for an entity that evolves over time: user profile, project status, agent context, onboarding journey. Mixing stable and ephemeral content in a single blob creates staleness and over-growth. Explicit layer contracts prevent both.

---

### B-07: Honest Empty Bootstrap

**Source:** `docs/features/identity-store/README.md` — Key Principles §1; `src/atman/core/services/identity_service.py`

**Description:** When initializing a stateful system for a new entity, start with a **genuinely empty state** and an honest self-description of that emptiness, rather than pre-seeding with plausible-looking but fabricated initial data. Include explicit `open_questions` about what is not yet known. "Empty with honesty" is a valid and preferable initial state.

**Why generalizable:** Personalization systems, recommendation engines, analytics dashboards, agent personas. Pre-seeded defaults look good in demos but pollute the first real data with noise. A system that admits it knows nothing yet is more trustworthy than one that pretends to know.

---

### B-08: Deterministic Experience ID from Session ID

**Source:** `docs/features/session-manager/README.md` — Integration with Experience Store; `src/atman/core/services/session_manager.py`

**Description:** Derive the persisted record's ID deterministically from the triggering event's ID (e.g., `experience_id = uuid5(NAMESPACE, str(session_id))`). On retry or partial persistence failure, the system will attempt to write the same ID, allowing the storage layer to detect and handle idempotent writes explicitly (upsert or detect-duplicate).

**Why generalizable:** Any event-driven system where the same logical event may attempt to create a persistent record multiple times due to retries, at-least-once delivery, or crash recovery. Random UUIDs on each attempt cause phantom duplicates; deterministic IDs allow idempotent writes.

---

### B-09: Replay-Safe Idempotency Keys for Side Effects

**Source:** `docs/features/reflection-engine/README.md` — Operational Contracts ("Reframing is replay-safe"); `src/atman/core/services/reflection/daily.py`

**Description:** When a process generates side effects (appending notes, sending notifications, updating counters), compute a stable `triggered_by` key for each side effect from the operation's run key and the target record's ID: `triggered_by = f"reflection|{run_key}|reframe|{experience_id}"`. The storage layer enforces uniqueness on this key. Replays count `DUPLICATE_TRIGGERED_BY` outcomes instead of producing duplicate side effects.

**Why generalizable:** Any idempotent event processor that generates multiple side effects per run — webhook handlers, change data capture pipelines, fan-out notifications. Without stable side-effect keys, replay protection on the outer operation doesn't prevent inner duplicate side effects.

---

### B-10: Structured Component Documentation (Status / Architecture / Contracts / Testing / Design Decisions)

**Source:** `docs/features/reflection-engine/README.md` and all feature READMEs in `docs/features/`

**Description:** Every implemented component has a README with these mandatory sections: Status, Architecture (models + services + ports + adapters), Running the Demo, CLI Usage, Key Contracts (what it reads / what it writes), Operational Contracts (invariants, idempotency guarantees, degraded behaviors), Critical Rule, Testing, Design Decisions (each with explicit "Why"), Integration Points, Future Work.

**Why generalizable:** Documentation that is missing the "why" of design decisions forces future agents (or developers) to reverse-engineer intent. The operational contracts section (especially degraded behaviors and edge cases) is almost always missing and almost always valuable. This structure works for any non-trivial component.

---

### B-11: Optimistic Concurrency for Text-Layer Updates

**Source:** `docs/features/session-manager/README.md` — Integration with Narrative Store; `src/atman/core/services/session_manager.py`

**Description:** When updating a document that multiple processes might write concurrently, pass a `last_seen_revision` token (e.g., `updated_at` timestamp) with the write request. On the storage layer, compare token to current state before committing; on mismatch, return a structured conflict outcome. The caller decides whether to retry, merge, or record a conflict event. No distributed locks, no serialization stalls.

**Why generalizable:** Any async pipeline where multiple processes might update the same text resource: narrative documents, configuration files, shared notes, summarized context. Locking is brittle under async reflection pipelines; optimistic concurrency + explicit conflict handling is more robust.

---

### B-12: Salience Decay for Relevance Without Deletion

**Source:** `docs/features/experience-store/README.md` — Key Principles §3; `src/atman/core/services/experience_service.py`

**Description:** Represent the "current importance" of a stored record as a calculated value that decays exponentially with time since last access: `salience = base_salience * exp(-lambda * days_since_access)`, with the decay rate modulated by record properties (e.g., depth of a memory). Importantly: **calculating salience does NOT modify the stored record**. The stored `salience` is the initial value; current salience is computed on read.

**Why generalizable:** Search result ranking, recommendation systems, cache eviction policies, notification prioritization. Hard deletion loses data; fixed weights go stale. Decay-on-read gives time-aware relevance without destructive updates.

---

## Section C: What in the Playbook Could Be Updated (Without Replacing)

### Pattern 01: Agent Rules Structure
Atman's feature READMEs demonstrate a **structured component documentation template** (Status / Architecture / Key Contracts / Operational Contracts / Design Decisions) that goes beyond generic "add documentation" advice. Pattern 01 could be extended with a subsection: "Layer 3.5: Component Contract Documents — what they should include and why". This supplements, not replaces, the existing DEVELOPMENT_STANDARD.md guidance.

### Pattern 05: Context Handoff
Atman's `docs/architecture/SYSTEM_MAP.md` is a maintained inventory of all modules, integrations, user scenarios, edge cases, and known regressions — updated in the same PR as the code that changes it. This is a concrete implementation of "Layer 4: Current State" from Pattern 05, with a specific structure that has proven useful. Could be added as a named sub-pattern: "System Map as Living Current-State Document".

---

## Section D: Proposed New Patterns

The following 10 patterns are proposed for `agent-playbook/patterns/`. Each is universal — describable without Atman-specific terminology.

### 06: Idempotent Long-Running Operations
**Summary:** Make batch jobs, scheduled workers, and async pipelines safe to retry by computing a deterministic run key from input parameters and persisting a terminal success event before returning.  
**Key insight:** Idempotency via deterministic keys is fundamentally different from "just retry and ignore errors" — it gives callers a queryable history of what happened.

### 07: Append-Only Records with Annotation Layers
**Summary:** Keep original records immutable; accumulate derived perspectives in a separate append-only annotations list. Callers get both raw data and all interpretations.  
**Key insight:** The "what actually happened" layer has fundamentally different integrity requirements from the "what we think it means" layer.

### 08: Port + Deterministic Mock Adapter for External Dependencies
**Summary:** Abstract probabilistic external dependencies (LLMs, APIs, sensors) behind ports; provide a deterministic mock that returns semantically meaningful output for testing. Not a stub — a real integration test path without network calls.  
**Key insight:** Most LLM-powered features have untested business logic because tests skip the LLM entirely. Deterministic mocks remove this tradeoff.

### 09: First-Hand Data Capture with Explicit Incompleteness Flag
**Summary:** Capture contextual metadata at the moment of the event, not retrospectively. If in-the-moment capture fails, mark the record `incomplete_coloring=True` rather than guessing or omitting.  
**Key insight:** Post-hoc reconstruction is always biased by later context. An honest incompleteness flag is more useful than a plausible-looking but fabricated value.

### 10: Outcome-Coded Events for Structured Control Flow
**Summary:** Represent predictable non-error outcomes as structured events with an `outcome` field and optional `reason`. Schedulers, callers, and dashboards query events instead of parsing exception logs.  
**Key insight:** Exceptions are the wrong primitive for "nothing to process today." Outcome-coded events are observable, structured, and semantically meaningful.

### 11: Layered Document Volatility
**Summary:** Structure living documents into layers with different volatility contracts: stable core (rarely changes), ephemeral recent (replaced each cycle), and named threads (explicit lifecycle). Write paths, retention, and reading semantics differ per layer.  
**Key insight:** Mixing stable identity with ephemeral session data causes either stale context or over-growth. Explicit layer contracts let callers know what to trust.

### 12: Honest Empty Bootstrap
**Summary:** Initialize stateful entities with a genuinely empty state and explicit acknowledgment of what is unknown, rather than pre-seeding with plausible defaults. Include open questions as first-class fields.  
**Key insight:** Pre-seeded defaults produce phantom data that pollutes early real observations. Honest emptiness is a valid — and more trustworthy — starting state.

### 13: Replay-Safe Side Effect Keys
**Summary:** Compute a stable idempotency key for each side effect from the triggering operation's run key and target record ID. The storage layer enforces uniqueness on this key; replays count duplicates instead of re-executing.  
**Key insight:** Outer-operation idempotency without inner-side-effect keys causes duplicate emails, appended notes, incremented counters on replay.

### 14: Salience Decay for Time-Aware Relevance
**Summary:** Calculate relevance as a function of time since last access and record properties, decaying exponentially. Store the initial salience; compute current salience on read. Do not delete records with low salience.  
**Key insight:** Static importance scores go stale; hard deletion loses data. Decay-on-read gives time-aware relevance with zero destructive writes.

### 15: Deterministic ID Derivation for Idempotent Persistence
**Summary:** Derive a persisted record's ID deterministically from the triggering event's ID (UUID v5 or hash). On retry, the same ID is produced, making duplicate-detection at the storage layer trivial.  
**Key insight:** Random IDs on each attempt create phantom duplicates in at-least-once delivery systems. Deterministic IDs collapse retries to a single canonical record.

---

## Section E: Open Questions for the Author

**E-01: Patterns 11 (Layered Document Volatility) vs Pattern 05 (Context Handoff)**  
Pattern 11 is technically generalizable, but its natural home might be as an extension of existing Pattern 05 ("Layer 3.5: Layered Document Structure") rather than a standalone pattern. Should it be a sub-section of 05 or a standalone 11? I lean toward standalone because the write semantics (different paths per layer) are the key insight, which is absent from Pattern 05.

**E-02: Pattern 08 (Deterministic Mock Adapter) — scope**  
The current draft covers LLM mocks specifically. Should it also cover other probabilistic/slow dependencies (embedding APIs, web scrapers, time-based randomness)? The pattern works equally well for all of them. Broadening would make it more universal but less focused.

**E-03: Patterns 13 and 15 — merge or keep separate?**  
Patterns 13 (Replay-Safe Side Effect Keys) and 15 (Deterministic ID Derivation) both address replay safety through deterministic keys, but at different granularities: 15 is about the root record, 13 is about each side effect generated by a process. They could be merged into one "Deterministic Keys for Idempotent Systems" pattern, or kept separate for clarity. Suggest merging unless both need standalone examples.

**E-04: Pattern 12 (Honest Empty Bootstrap) — is it an anti-pattern document rather than a pattern?**  
The substance of Pattern 12 is "don't pre-seed with fake defaults." This might read better as an addition to the Failure Modes guide (`guides/failure-modes.md` — a new section "Phantom Seed Data") rather than a standalone pattern. Your call on whether it deserves pattern-level prominence.

**E-05: Two-tier regulation (acute + homeostatic) and 4-level intervention hierarchy**  
Both are mentioned in `docs/architecture/SYSTEM.md` as planned components but are not yet implemented. Are these patterns mature enough to document now as "planned architecture" patterns, or should we wait for an implementation to validate them first? I've excluded them from Section D for now.

---

*End of audit report. Sections A–E cover the full state of both repositories as of 2026-05-07.*
