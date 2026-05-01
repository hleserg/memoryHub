#!/usr/bin/env python3
"""
Reproducible walkthrough of Experience Store using a temporary JSONL file.

Does not write to ~/.atman. See docs/features/experience-store/README.md and `make demo-experience`.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
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
    from atman.cli_experience import print_experience
    from atman.core.models import SessionExperience
    from atman.core.services import ExperienceService

    fixture = root / "fixtures" / "experience1_competence_challenge.json"
    if not fixture.is_file():
        print(f"Missing fixture: {fixture}", file=sys.stderr)
        sys.exit(1)

    print("=" * 60)
    print("Atman Experience Store — runnable demo")
    print("=" * 60)
    print("Using a temporary JSONL file (your ~/.atman is not modified).\n")

    with NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".jsonl", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        store = JsonlExperienceStore(tmp_path)
        service = ExperienceService(store)

        print("Step 1: Load fixture and create experience")
        with open(fixture, encoding="utf-8") as f:
            raw = json.load(f)
        experience = SessionExperience.model_validate(raw)
        record = service.create_experience(experience)
        print_experience(record)
        eid = record.experience.id

        print("\nStep 2: Add reframing note (append-only)")
        updated = service.add_reframing_note(
            experience_id=eid,
            reflection="In retrospect, admitting uncertainty was appropriate for the task.",
            reflection_type="growth",
        )
        if updated is None:
            print("✗ Expected experience after reframing", file=sys.stderr)
            sys.exit(1)
        print(f"  Reframing notes: {len(updated.experience.reframing_notes)}")

        print("\nStep 3: Search by values touched (competence, honesty)")
        matches = service.search_by_values(["competence", "honesty"], limit=5)
        print(f"  Matches: {len(matches)}")

        print("\nStep 4: Salience decay preview (does not mutate stored salience)")
        current_time = datetime.now(timezone.utc)
        print("  Days | Salience")
        print("  -----|----------")
        exp = updated.experience
        for days in (0, 7, 30):
            t = current_time + timedelta(days=days)
            sal = exp.calculate_current_salience(current_time=t)
            print(f"  {days:5d} | {sal:.4f}")

        print("\n✓ Demo completed successfully.")
    finally:
        tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
