# Issue Backlog (Imported)

This document imports the requested engineering issues into the repository backlog.

## E2E-01: End-to-end integration scenario
Build a minimal end-to-end flow over existing WP-01..05 in `e2e/`.

- One script (~200 lines) that:
  - creates a temporary workspace via `FileStateStore`
  - opens a session via `SessionManager`
  - records 2–3 events and 2 key moments
  - finishes the session
  - runs `MicroReflectionService`
  - simulates 2–3 more sessions during a “day”
  - runs `DailyReflectionService`
  - then runs `DeepReflectionService` for a “week”
- Result: runnable `python -m e2e.full_loop` that demonstrates how five packages connect into one flow.
- Found seams (incompatible contracts, provenance gaps, missing methods) must be logged as separate issues, not fixed in this issue.

## E2E-02: Integration test for full lifecycle
Based on E2E-01, add a `pytest` test in `tests/integration/test_full_lifecycle.py` to verify end-to-end invariants:

- experience becomes immutable after finish
- reframing notes from daily reflection appear on old experiences
- `narrative.recent_layer` updates after micro reflection
- `identity_snapshot_id` propagates correctly through session → experience → reflection

Constraints:

- test uses `FileStateStore` in a temporary directory
- no mocks at storage layer

## MODEL-01: Structured output contracts for `ReflectionModel`
Extend `ReflectionModel` port so all methods return structured Pydantic models instead of free-form text.

Add models in `core/models/reflection.py`:

- `ReframingNoteOutput`
- `PatternDetectionOutput`
- `NarrativeUpdateOutput`
- `HealthCriterionOutput`

Update `MockReflectionModel` for new contracts.

Goal: prepare for real LLM integration while keeping deterministic service logic independent from style/wording quality.

## MODEL-02: Ollama adapter for `ReflectionModel`
Implement `OllamaReflectionModel` in `adapters/reflection/ollama_reflection_model.py`.

Requirements:

- local Ollama API (default `http://localhost:11434`)
- model via env `ATMAN_OLLAMA_MODEL` (default `llama3.1:8b`)
- all methods return structured outputs from MODEL-01
- use Ollama JSON mode + Pydantic validation
- retry on invalid JSON (max 2 attempts)

Tests:

- unit tests with mocked `httpx` client
- integration test marked `@pytest.mark.requires_ollama`, skipped if Ollama is unavailable

## MODEL-03: Anthropic adapter for `ReflectionModel`
Implement `AnthropicReflectionModel` for higher-quality mode.

Requirements:

- use tool_use API for guaranteed valid JSON
- pass output schemas as tool definitions
- API key from env `ANTHROPIC_API_KEY`
- model via env `ATMAN_ANTHROPIC_MODEL` (default `claude-haiku-4-5`)

Tests:

- unit tests with mocks
- integration test marked `@pytest.mark.requires_anthropic_key`

## ANCHOR-01: Reality Anchor — models and rule-based detection
Implement WP-06 detection parts:

- models in `core/models/reality_anchor.py`:
  - `AgentEvent`
  - `IdentityReference`
  - `RealitySignal`
  - `Intervention`
- `RealityAnchorService` in `core/services/` with rule-based detectors:
  - `detect_principle_conflict`
  - `detect_tone_shift` (baseline deviation > threshold)
  - `detect_unsupported_claim` (claim outside `known_limits`)
  - `detect_voice_drift` (via `voice_markers`)
- method `evaluate(event, identity_reference) -> list[RealitySignal]`
- no LLM usage
- thresholds configurable via `RealityAnchorConfig` dataclass

## ANCHOR-02: Reality Anchor — intervention levels and Session Manager integration
Add `InterventionMapper` to aggregate `list[RealitySignal]` into intervention levels 1–4 per `SYSTEM.md`:

- 1: internal flag
- 2: signal to agent
- 3: trigger affect protocol
- 4: recommend pause to user

Rules:

- multiple medium signals can aggregate to higher level
- integrate into `SessionManager`:
  - after each `record_event` and `record_key_moment`, call `RealityAnchorService.evaluate`
  - for level ≥ 3, persist separate `SessionEvent` with type `intervention`
- do not block writing: anchor observes, does not cancel

## ANCHOR-03: Affective Regulation Level 1
Implement `AffectiveRegulationService` with short-term self-regulation protocol.

Behavior:

- when `negative_affect_level > threshold`, return `AffectProtocolResult` with steps:
  - stop
  - pause
  - internal work
  - communication
- include `message_to_user`
- trigger from `InterventionMapper` at level 3
- input: current session emotional state (aggregate from key moments) + config threshold

Add CLI:

- `atman-reality-check --identity examples/identity.json --event examples/drift-event.json`

## SCHED-01: Marker protocol for background reflection tasks
Implement minimal WP-09 part: `MarkerScanner` in `atman/scheduler/markers.py`.

Behavior:

- accepts directory with marker files named `atman_session_done_<timestamp>.marker`
- file contents: session log path or empty
- for each marker: call handler
- on success: rename marker to `.done`
- on error: keep marker in place

Add CLI command:

- `atman-scheduler scan-markers --marker-dir <dir> --handler micro`

No daemon/launchd in this issue.

## SCHED-02: Scheduler shell for daily/deep
Add script `atman-scheduler tick`.

Behavior:

- checks time of last successful daily/deep reflection via `event_store.get_recent` filtered by level
- runs corresponding service if enough time has passed
- config via simple TOML (`scheduler.toml`) with daily/deep intervals
- designed for external cron/launchd invocation
- logs decisions to stdout

No daemon process in this issue.

## SCHED-03: SessionManager finish hook for marker creation
Update `SessionManager.__init__` with optional `marker_dir: Path | None`.

Behavior:

- if provided, after successful `finish_session`, create `atman_session_done_<session_id>.marker`
- marker content: `session_id`

Constraints:

- keep optional to preserve existing behavior
- existing tests must keep passing
