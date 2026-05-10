# Playbook Candidates Awaiting Markers

These are generalizable patterns identified during the initial audit
(see `reports/playbook-audit-2026-05-07.md`, Section B) but not yet
bootstrapped with PLAYBOOK markers.

**When working on a listed component:** check if the pattern still applies
and add a marker at the implementation site using the syntax in
`docs/development/PLAYBOOK_MARKERS.md`.

Suggested marker text is provided for each candidate to make it easy to
add the marker when you encounter the code.

---

## Component: Experience Store

- [ ] **Salience decay via exponential function**
  - Location: `src/atman/core/services/experience_service.py`
  - Candidate id: `salience-decay-relevance`
  - Suggested title: Salience Decay for Time-Aware Relevance Without Deletion
  - Category: `design-patterns`
  - Body: "Calculate record relevance as `base_salience * exp(-lambda * days_since_access)` with the decay rate modulated by record depth/intensity. Store the initial salience; compute current salience on read. Do NOT modify the stored record. Why: hard deletion loses data; static scores go stale; decay-on-read gives time-aware relevance with zero destructive writes."

- [ ] **Incomplete coloring flag as honest fallback**
  - Location: `src/atman/core/models/experience.py` — `KeyMoment.incomplete_coloring`
  - Candidate id: `incomplete-data-honest-flag`
  - Suggested title: Explicit Incompleteness Flag as Honest Data Quality Fallback
  - Category: `design-patterns`
  - Body: "When contextual metadata cannot be captured in the moment (emotional state, cognitive load, sensor reading), mark the record with an explicit `incomplete_coloring=True` flag rather than guessing or omitting. A record that admits incompleteness is more trustworthy than a fabricated value. Why: post-hoc reconstruction is biased by later context; honest flags preserve signal quality."

---

## Component: Session Manager

- [ ] **First-hand vs retrospective data capture**
  - Location: `src/atman/core/services/session_manager.py`
  - Candidate id: `first-hand-data-capture`
  - Suggested title: First-Hand Data Capture at Event Time vs Retrospective Reconstruction
  - Category: `design-patterns`
  - Body: "Capture contextual metadata (emotional state, cognitive load, relevance signal) at the moment the event occurs, not by reconstructing it later from logs. If in-the-moment capture fails, mark the record explicitly as incomplete rather than guessing. Why: monitoring systems, labeling pipelines, and observability stacks all produce lower-quality signals when context is reconstructed after the fact."

- [ ] **Deterministic experience ID from session ID**
  - Location: `src/atman/core/services/session_manager.py` — `finish_session`
  - Candidate id: `deterministic-id-from-triggering-event`
  - Suggested title: Deterministic Record ID Derived from Triggering Event ID
  - Category: `design-patterns`
  - Body: "Derive the persisted record's ID deterministically from the triggering event's ID (e.g., UUID v5 namespace + session_id). On retry after partial persistence failure, the same ID is produced, allowing the storage layer to detect duplicate writes. Why: random IDs on each attempt create phantom duplicates in at-least-once delivery systems."

---

## Component: Reflection Engine

- [ ] **Outcome-coded events instead of exceptions**
  - Location: `src/atman/core/services/reflection/daily.py` and `deep.py`
  - Candidate id: `outcome-coded-events`
  - Suggested title: Outcome-Coded Events for Structured Control Flow
  - Category: `design-patterns`
  - Body: "Instead of raising exceptions for predictable non-error outcomes (nothing to process, prerequisite not met, already done), persist a structured event with an `outcome` field: `outcome=daily_ok`, `outcome=daily_skipped reason=no_identity`. The outcome is a terminal state, queryable offline. Why: exceptions are the wrong primitive for 'nothing to do today' — they pollute error logs, complicate retry logic, and prevent structured analysis."

- [ ] **Replay-safe side effect keys**
  - Location: `src/atman/core/services/reflection/daily.py` — reframing logic
  - Candidate id: `replay-safe-side-effect-keys`
  - Suggested title: Stable Idempotency Keys for Side Effects Within Idempotent Operations
  - Category: `design-patterns`
  - Body: "When an idempotent operation generates multiple side effects (appended notes, notifications, counter increments), compute a stable `triggered_by` key for each side effect: `triggered_by = f'{operation_run_key}|{side_effect_type}|{target_id}'`. The storage layer enforces uniqueness on this key; replays count `DUPLICATE_TRIGGERED_BY` outcomes. Why: outer-operation idempotency without inner-side-effect keys causes duplicate side effects on replay."

- [ ] **Optimistic concurrency for text layer updates**
  - Location: `src/atman/core/services/session_manager.py` — narrative recent layer update
  - Candidate id: `optimistic-concurrency-text-documents`
  - Suggested title: Optimistic Concurrency for Async Text-Layer Updates
  - Category: `design-patterns`
  - Body: "Pass a `last_seen_updated_at` token with text document write requests. On write, compare token to current state; on mismatch, return a structured conflict outcome rather than silently overwriting. Caller decides retry or merge. Why: locking long-lived async text edits creates serialization stalls; optimistic concurrency requires no distributed lock infrastructure."

---

## Component: Identity Store

- [ ] **Honest empty bootstrap**
  - Location: `src/atman/core/services/identity_service.py` — `bootstrap_identity`
  - Candidate id: `honest-empty-bootstrap`
  - Suggested title: Honest Empty Bootstrap for Stateful Entities
  - Category: `design-patterns`
  - Body: "Initialize a stateful entity with a genuinely empty state and an explicit honest self-description of that emptiness, rather than pre-seeding with plausible-looking defaults. Include explicit `open_questions` as first-class fields. Why: pre-seeded defaults produce phantom data that pollutes early real observations; a system that admits it knows nothing is more trustworthy."

- [ ] **Three-layer document volatility**
  - Location: `src/atman/core/models/narrative.py` — `NarrativeDocument`
  - Candidate id: `layered-document-volatility`
  - Suggested title: Layered Document Volatility (Stable Core / Ephemeral Recent / Named Threads)
  - Category: `design-patterns`
  - Body: "Structure living documents into layers with explicit volatility contracts: (1) a core layer that changes rarely and requires deliberate action; (2) a recent layer replaced completely each cycle; (3) named threads with explicit lifecycle (opened → updated → closed with reason). Each layer has a different write path and retention contract. Why: mixing stable identity with ephemeral session data in one blob causes stale context or unbounded growth."

---

## Architecture-level candidates

- [ ] **Component README structure (Status/Architecture/Contracts/Design Decisions)**
  - Location: `docs/features/reflection-engine/README.md` — template for all feature READMEs
  - Candidate id: `component-readme-structure`
  - Suggested title: Structured Component Documentation Template
  - Category: `templates`
  - Body: "Every non-trivial component has a README with these sections: Status, Architecture (models/services/ports/adapters), Running the Demo, CLI Usage, Key Contracts (reads/writes), Operational Contracts (invariants/idempotency/degraded behaviors), Critical Rule, Testing, Design Decisions (each with 'Why'), Integration Points, Future Work. Why: documentation missing the 'why' forces future readers to reverse-engineer intent; operational contracts section is almost always missing and almost always valuable."

---

*Generated from audit: `reports/playbook-audit-2026-05-07.md`*  
*Last updated: 2026-05-07*
