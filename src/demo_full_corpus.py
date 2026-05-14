#!/usr/bin/env python3
"""
Full corpus demo: replay all E2E session fixtures through WP-02..05 wiring
(Factual Memory / WP-01 not on this path).

For each session: SessionManager (experience + eigenstate + narrative touch),
then MicroReflectionService, then DailyReflectionService (one calendar day per
session). After the last session, DeepReflectionService over the whole span.

Output highlights store growth, principle touches, mood (eigenstate / tone),
and a before/after narrative comparison. Uses the deterministic mock reflection
model from ``e2e.full_loop`` (no LLM).

Run: ``make demo-full-corpus`` (sets ``PYTHONPATH=.``) or
``PYTHONPATH=. ATMAN_DEMO_PACE=off python3 src/demo_full_corpus.py --limit 3``.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from uuid import uuid4

from rich.table import Table

import atman.term as term
from atman.adapters.storage.file_state_store import FileStateStore
from atman.adapters.storage.in_memory_reflection_store import (
    InMemoryHealthAssessmentStore,
    InMemoryPatternStore,
    InMemoryReflectionEventStore,
)
from atman.core.clock_impl import FrozenClock
from atman.core.narrative_write_audit import NoOpNarrativeWriteAudit
from atman.core.services import SessionManager
from atman.core.services.narrative_revision import NarrativeRevisionService
from atman.core.services.reflection_service import (
    DailyReflectionService,
    DeepReflectionService,
    MicroReflectionService,
)
from e2e.full_loop import (
    DeterministicReflectionModel,
    StateStoreExperienceAdapter,
    StateStoreIdentityAdapter,
    StateStoreNarrativeAdapter,
    create_bootstrap_identity,
    create_bootstrap_narrative,
    load_all_fixture_sessions_sorted,
    run_session_from_fixture,
    temp_workspace,
)
from e2e.models import SessionFixtureDocument


def _utc_day_start(d: datetime) -> datetime:
    x = d if d.tzinfo else d.replace(tzinfo=UTC)
    return datetime.combine(x.date(), time.min, tzinfo=UTC)


def _utc_day_end(d: datetime) -> datetime:
    x = d if d.tzinfo else d.replace(tzinfo=UTC)
    return datetime.combine(x.date(), time.max, tzinfo=UTC)


def _load_fixture_doc(path: Path) -> SessionFixtureDocument:
    with open(path, encoding="utf-8") as f:
        return SessionFixtureDocument.model_validate(json.load(f))


def _truncate(text: str, max_len: int = 220) -> str:
    t = text.replace("\n", " ").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


@dataclass
class _RunTotals:
    principles_confirmed: int = 0
    principles_questioned: int = 0
    mood_samples: list[float] = field(default_factory=list)


def _reflection_bundle(
    *,
    experience_repo: StateStoreExperienceAdapter,
    identity_repo: StateStoreIdentityAdapter,
    narrative_repo: StateStoreNarrativeAdapter,
    pattern_store: InMemoryPatternStore,
    health_store: InMemoryHealthAssessmentStore,
    event_store: InMemoryReflectionEventStore,
    reflection_model: DeterministicReflectionModel,
    narrative_audit: NoOpNarrativeWriteAudit,
    clock: FrozenClock,
) -> tuple[MicroReflectionService, DailyReflectionService, DeepReflectionService]:
    narrative_revision = NarrativeRevisionService(
        narrative_repo=narrative_repo,
        reflection_model=reflection_model,
        narrative_audit=narrative_audit,
        clock=clock,
    )
    micro = MicroReflectionService(
        experience_repo=experience_repo,
        narrative_revision=narrative_revision,
        event_store=event_store,
        clock=clock,
    )
    daily = DailyReflectionService(
        experience_repo=experience_repo,
        identity_repo=identity_repo,
        pattern_store=pattern_store,
        reflection_model=reflection_model,
        event_store=event_store,
        clock=clock,
    )
    deep = DeepReflectionService(
        experience_repo=experience_repo,
        identity_repo=identity_repo,
        narrative_repo=narrative_repo,
        pattern_store=pattern_store,
        health_store=health_store,
        reflection_model=reflection_model,
        event_store=event_store,
        clock=clock,
    )
    return micro, daily, deep


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay all session JSON fixtures through Session Manager + reflection stack.",
    )
    parser.add_argument(
        "--locale",
        choices=("en", "ru"),
        default="en",
        help="Fixture subdirectory under e2e/fixtures/sessions/",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        metavar="N",
        help="Process only the first N sessions after sort (0 = all).",
    )
    args = parser.parse_args()

    term.print_banner(
        "Full corpus demo",
        "All fixtures → Session Manager → micro → daily → deep summary",
    )
    term.demo_pace()

    paths = load_all_fixture_sessions_sorted(args.locale)
    if args.limit and args.limit > 0:
        paths = paths[: args.limit]

    if not paths:
        term.print_warn(
            f"No fixtures in e2e/fixtures/sessions/{args.locale}/ "
            "(generate with: python -m e2e.generate_fixtures)"
        )
        return 1

    term.print_section("Setup")
    term.print_info(
        f"Locale: {args.locale} — {len(paths)} session(s), deterministic reflection model"
    )
    term.demo_pace()

    # Fixed anchor so multi-day spacing is reproducible.
    anchor = datetime(2026, 1, 6, 10, 0, 0, tzinfo=UTC)
    totals = _RunTotals()

    with temp_workspace() as workspace_path:
        term.print_ok(f"Workspace: {workspace_path}")
        state_store = FileStateStore(workspace=workspace_path)
        agent_id = uuid4()
        identity = create_bootstrap_identity(agent_id)
        state_store.save_identity(identity)
        narrative = create_bootstrap_narrative(agent_id)
        state_store.save_narrative(narrative)

        narrative_repo = StateStoreNarrativeAdapter(state_store)
        initial_narrative = narrative_repo.get_current()
        assert initial_narrative is not None
        baseline_recent = initial_narrative.recent_layer.content

        experience_repo = StateStoreExperienceAdapter(state_store)
        identity_repo = StateStoreIdentityAdapter(state_store)
        event_store = InMemoryReflectionEventStore()
        pattern_store = InMemoryPatternStore()
        health_store = InMemoryHealthAssessmentStore()
        reflection_model = DeterministicReflectionModel()
        narrative_audit = NoOpNarrativeWriteAudit()

        for idx, fixture_path in enumerate(paths):
            doc = _load_fixture_doc(fixture_path)
            day_instant = anchor + timedelta(days=idx)
            fc = FrozenClock(day_instant)
            session_manager = SessionManager(state_store, clock=fc)

            micro, daily, _ = _reflection_bundle(
                experience_repo=experience_repo,
                identity_repo=identity_repo,
                narrative_repo=narrative_repo,
                pattern_store=pattern_store,
                health_store=health_store,
                event_store=event_store,
                reflection_model=reflection_model,
                narrative_audit=narrative_audit,
                clock=fc,
            )

            term.print_section(
                f"Session {doc.metadata.session_number} (step {idx + 1}/{len(paths)}) — "
                f"{doc.metadata.theme}"
            )
            term.print_info(f"[dim]Arc:[/dim] {doc.metadata.narrative_arc}")
            term.demo_pace()

            p_conf = sum(len(km.principles_confirmed) for km in doc.key_moments)
            p_quest = sum(len(km.principles_questioned) for km in doc.key_moments)
            totals.principles_confirmed += p_conf
            totals.principles_questioned += p_quest

            _sid, session_result = run_session_from_fixture(
                fixture_path,
                session_manager,
                agent_id,
                fc,
                verbose=False,
            )

            tone = session_result.overall_emotional_tone
            eigen_tone = (
                session_result.eigenstate.emotional_tone
                if session_result.eigenstate is not None
                else tone
            )
            totals.mood_samples.append(float(eigen_tone))

            term.print_ok(
                f"Finished session — outcome tone {tone:+.2f}, eigenstate {eigen_tone:+.2f} "
                f"(principles +{p_conf} / −{p_quest} in key moments)"
            )

            micro_ev = micro.reflect(_sid)
            term.print_info(f"[dim]Micro reflection:[/dim] {micro_ev.key_insight}")
            daily_ev = daily.reflect(day_instant)
            term.print_info(
                f"[dim]Daily reflection ({day_instant.date()}):[/dim] {daily_ev.key_insight} "
                f"— patterns {len(daily_ev.patterns_detected)}, reframings +{daily_ev.reframing_notes_added}"
            )
            term.demo_pace()

        term.print_section("Deep reflection (full span)")
        last_day = anchor + timedelta(days=len(paths) - 1)
        since = _utc_day_start(anchor)
        until = _utc_day_end(last_day)
        end_clock = FrozenClock(until)
        _m, _d, deep = _reflection_bundle(
            experience_repo=experience_repo,
            identity_repo=identity_repo,
            narrative_repo=narrative_repo,
            pattern_store=pattern_store,
            health_store=health_store,
            event_store=event_store,
            reflection_model=reflection_model,
            narrative_audit=narrative_audit,
            clock=end_clock,
        )
        deep_ev = deep.reflect(since, until)
        term.print_ok(deep_ev.key_insight)
        if deep_ev.identity_changes_proposed:
            term.print_info(
                f"[dim]Identity proposals (event text, not auto-applied):[/dim] {deep_ev.identity_changes_proposed}"
            )
        if deep_ev.narrative_changes_proposed:
            term.print_info(
                f"[dim]Narrative proposals:[/dim] {_truncate(deep_ev.narrative_changes_proposed, 280)}"
            )
        term.demo_pace()

        final_narrative = narrative_repo.get_current()
        assert final_narrative is not None
        final_recent = final_narrative.recent_layer.content

        all_exps = experience_repo.get_all()
        reframing_total = sum(len(x.reframing_notes) for x in all_exps)
        patterns_all = pattern_store.get_all()

        term.print_section(f"Comparison after {len(paths)} session(s) (issue #158)")
        cmp_table = Table(title="Corpus run summary", show_lines=True)
        cmp_table.add_column("Metric", style="bold")
        cmp_table.add_column("Start (bootstrap)", ratio=1)
        cmp_table.add_column("End (after run)", ratio=1)

        cmp_table.add_row(
            "Identity (stored)",
            f"baseline {identity.emotional_baseline:+.2f}; "
            f"values: {', '.join(v.name for v in identity.core_values)}",
            "unchanged (reflection does not persist identity edits in this stack)",
        )
        cmp_table.add_row(
            "Sessions / experiences",
            "0 / 0",
            f"{len(paths)} / {len(all_exps)}",
        )
        cmp_table.add_row(
            "Principle touches (key moments)",
            "—",
            f"confirmed {totals.principles_confirmed}, questioned {totals.principles_questioned}",
        )
        mood_str = ", ".join(f"{x:+.2f}" for x in totals.mood_samples[:8])
        if len(totals.mood_samples) > 8:
            mood_str += ", …"
        cmp_table.add_row(
            "Mood (eigenstate tone, chronological)",
            "—",
            mood_str or "—",
        )
        cmp_table.add_row(
            "Patterns (store)",
            "0",
            str(len(patterns_all)),
        )
        cmp_table.add_row(
            "Reframing notes (on experiences)",
            "0",
            str(reframing_total),
        )
        cmp_table.add_row(
            "Reflection events recorded",
            "0",
            str(len(event_store.get_all())),
        )
        cmp_table.add_row(
            "Narrative recent layer",
            _truncate(baseline_recent, 180),
            _truncate(final_recent, 180),
        )

        term.console.print(cmp_table)
        term.print_info(
            "[dim]Factual Memory (WP-01) is not in this path — only StateStore experiences, "
            "identity, narrative, eigenstates, and reflection side effects.[/dim]"
        )

    term.print_ok("Full corpus demo complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
