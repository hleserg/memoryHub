"""System and user prompts for two-pass fixture generation."""

from __future__ import annotations

import json
from typing import Any

from e2e.models import SessionSkeletonItem

SKELETON_SYSTEM = """You are a careful writer of realistic agent session scenarios for testing.
You output ONLY via the provided tool — no prose outside tool calls.
Sessions form one chronological corpus: later sessions may reference emotional residue from earlier ones.
Use concrete, grounded language; avoid melodrama or grand claims.
Themes and arcs should be plausible work sessions (coding, planning, user dialogue)."""


def skeleton_user_prompt(count: int) -> str:
    palette = ""
    if count == 5:
        palette = """
Required emotional palette across the five sessions (map sessions 1→5 in order):
1) Routine / neutral — low drama, everyday progress.
2) Breakthrough / clearly positive outcome.
3) Doubt about a principle or habit — mixed affect, questioning.
4) Values conflict or setback — overall negative tone allowed.
5) Integration / deep positive insight — coherent closure referencing earlier threads.

"""
    constraints = f"""
Constraints:
- Produce exactly {count} sessions in the tool payload.
- session_number must be 1..{count} exactly once each.
- Each session: theme (short), narrative_arc (one sentence), key_values (≥1), key_principles (may be empty).
- key_values will recur across sessions (same value in multiple sessions in different contexts).
- key_principles lists phrases that may later be questioned; early questions must be revisit-able in later sessions.
{palette}
"""
    return constraints.strip()


SESSION_SYSTEM = """You are writing one JSON session fixture for an AI agent psychology layer.
Output ONLY via the provided tool. Events are raw; key moments are first-hand colored experience.
Each key moment's what_happened must clearly refer to a concrete earlier event (by situation, not by ID).
principles_questioned items MUST appear in wording or paraphrase in an event description BEFORE that moment.
expected_session_outcome.overall_emotional_tone must equal (within 0.1 of) the intensity-weighted mean
of emotional_valence over key_moments, using weights emotional_intensity. Use 3–5 events and 2–3 key moments.
metadata.duration_seconds should be plausible (e.g. 900–7200).
Keep language grounded; avoid purple prose."""


def session_user_prompt(
    skeleton: SessionSkeletonItem,
    prior_fixtures_summary: list[dict[str, Any]],
) -> str:
    prior_json = json.dumps(prior_fixtures_summary, ensure_ascii=False, indent=2)
    sk_json = skeleton.model_dump_json(indent=2)
    return f"""Fixed skeleton for this session (obey theme, arc, values, principles):
{sk_json}

Prior sessions in this corpus (for continuity — you may echo values or revisit questioned principles):
{prior_json}

Fill the tool with the full session: metadata (match session_number and theme from skeleton),
events, key_moments, expected_session_outcome.
metadata.narrative_arc should match or refine the skeleton narrative_arc in one sentence.
""".strip()
