#!/usr/bin/env python3
"""
Reproducible walkthrough of Experience Store using a temporary JSONL file.

Does not write to ~/.atman. See docs/features/experience-store/README.md and `make demo-experience`.

Paced output (optional): ``ATMAN_DEMO_PACE=1`` — pauses between steps; see ``atman.term.demo_pace``.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _ensure_src_on_path() -> Path:
    root = _repo_root()
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    return root


def main() -> None:
    root = _ensure_src_on_path()

    from atman.adapters.storage import JsonlExperienceStore
    from atman.core.models import SessionExperience
    from atman.core.services import ExperienceService
    from atman.term import (
        demo_pace,
        print_banner,
        print_err,
        print_experience_record,
        print_info,
        print_ok,
        print_salience_table,
        print_section,
    )

    fixture = root / "fixtures" / "experience1_competence_challenge.json"
    if not fixture.is_file():
        print_err(f"Missing fixture: {fixture}")
        sys.exit(1)

    print_banner(
        "Atman Experience Store",
        "Runnable demo · temporary JSONL (your ~/.atman is not modified)",
    )
    demo_pace()

    with NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".jsonl", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        store = JsonlExperienceStore(tmp_path)
        service = ExperienceService(store)

        print_section("Step 1: Load fixture and create experience")
        demo_pace()
        with open(fixture, encoding="utf-8") as f:
            raw = json.load(f)
        experience = SessionExperience.model_validate(raw)
        record = service.create_experience(experience)
        print_experience_record(record)
        demo_pace()
        eid = record.experience.id

        print_section("Step 2: Add reframing note (append-only)")
        demo_pace()
        updated = service.add_reframing_note(
            experience_id=eid,
            reflection="In retrospect, admitting uncertainty was appropriate for the task.",
            reflection_type="growth",
        )
        if updated is None:
            print_err("Expected experience after reframing")
            sys.exit(1)
        print_info(f"Reframing notes: {len(updated.experience.reframing_notes)}")
        demo_pace()

        print_section("Step 3: Search by values touched (competence, honesty)")
        demo_pace()
        matches = service.search_by_values(["competence", "honesty"], limit=5)
        print_ok(f"Matches: {len(matches)}")
        demo_pace()

        print_section("Step 4: Salience decay preview (does not mutate stored salience)")
        demo_pace()
        current_time = datetime.now(UTC)
        exp = updated.experience
        rows: list[tuple[int, float]] = []
        for days in (0, 7, 30):
            t = current_time + timedelta(days=days)
            sal = exp.calculate_current_salience(current_time=t)
            rows.append((days, sal))
        print_salience_table(rows, title="Days vs salience")
        demo_pace()

        print_ok("Demo completed successfully.")
    finally:
        tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
