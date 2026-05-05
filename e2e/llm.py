"""Anthropic API: skeleton pass + per-session fixture pass with tool_use."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from e2e.models import (
    SessionFixtureDocument,
    SessionSkeletonItem,
    SkeletonPassOutput,
    validate_fixture_document,
)
from e2e.prompts import SESSION_SYSTEM, SKELETON_SYSTEM, session_user_prompt, skeleton_user_prompt
from e2e.validation import skeleton_matches_count, validate_corpus


def _tool_schema(model: type[BaseModel]) -> dict[str, Any]:
    """JSON Schema for Anthropic ``input_schema``."""
    return model.model_json_schema()


def _extract_tool_input(message: Any, tool_name: str) -> dict[str, Any]:
    for block in message.content:
        btype = getattr(block, "type", None)
        if btype == "tool_use" and getattr(block, "name", None) == tool_name:
            inp = getattr(block, "input", None)
            if isinstance(inp, dict):
                return inp
            raise RuntimeError(f"tool {tool_name} input is not a dict")
    raise RuntimeError(f"No tool_use block named {tool_name!r} in assistant message")


def run_skeleton_pass(client: Any, model: str, count: int) -> list[SessionSkeletonItem]:
    """Call Anthropic once; return ordered skeleton rows."""
    input_schema = SkeletonPassOutput.model_json_schema()
    msg = client.messages.create(
        model=model,
        max_tokens=4096,
        system=SKELETON_SYSTEM,
        tools=[
            {
                "name": "submit_session_skeleton",
                "description": "Planned metadata for each session in the corpus",
                "input_schema": input_schema,
            }
        ],
        messages=[
            {
                "role": "user",
                "content": skeleton_user_prompt(count),
            }
        ],
    )
    raw = _extract_tool_input(msg, "submit_session_skeleton")
    parsed = SkeletonPassOutput.model_validate(raw)
    rows = sorted(parsed.sessions, key=lambda s: s.session_number)
    skeleton_matches_count(rows, count)
    return rows


def fixture_summary(doc: SessionFixtureDocument) -> dict[str, Any]:
    """Compact context for subsequent session prompts."""
    return {
        "session_number": doc.metadata.session_number,
        "theme": doc.metadata.theme,
        "narrative_arc": doc.metadata.narrative_arc,
        "event_types": [e.event_type for e in doc.events],
        "key_moment_titles": [m.what_happened[:120] for m in doc.key_moments],
        "overall_tone": doc.expected_session_outcome.overall_emotional_tone,
        "values": sorted({v.lower() for m in doc.key_moments for v in m.values_touched}),
        "principles_questioned": sorted(
            {p for m in doc.key_moments for p in m.principles_questioned}
        ),
    }


def run_session_pass(
    client: Any,
    model: str,
    skeleton: SessionSkeletonItem,
    prior_documents: list[SessionFixtureDocument],
    validation_error_hint: str | None,
) -> SessionFixtureDocument:
    """Generate one session fixture; optional hint retries after validation failure."""
    schema = SessionFixtureDocument.model_json_schema()
    prior_summary = [fixture_summary(d) for d in prior_documents]
    user_text = session_user_prompt(skeleton, prior_summary)
    if validation_error_hint:
        user_text = (
            f"The previous attempt was rejected:\n{validation_error_hint}\n\n"
            f"Fix the JSON to satisfy constraints and call the tool again.\n\n{user_text}"
        )
    msg = client.messages.create(
        model=model,
        max_tokens=16384,
        system=SESSION_SYSTEM,
        tools=[
            {
                "name": "submit_session_fixture",
                "description": "Complete single-session JSON fixture",
                "input_schema": schema,
            }
        ],
        messages=[{"role": "user", "content": user_text}],
    )
    raw = _extract_tool_input(msg, "submit_session_fixture")
    return SessionFixtureDocument.model_validate(raw)


def anthropic_client() -> Any:
    """Construct Anthropic client (import deferred for optional dependency)."""
    try:
        from anthropic import Anthropic
    except ImportError as e:
        raise ImportError(
            "The e2e extra is required: pip install 'atman[e2e]' or pip install anthropic"
        ) from e
    return Anthropic()


def generate_corpus_with_retries(
    client: Any, model: str, count: int
) -> list[SessionFixtureDocument]:
    """
    Full two-phase generation with up to 3 attempts per session (1 + 2 retries).

    Raises the last ``ValidationError`` or ``ValueError`` if all attempts fail.
    """
    skeleton = run_skeleton_pass(client, model, count)
    out: list[SessionFixtureDocument] = []
    for row in skeleton:
        last_err: str | None = None
        doc: SessionFixtureDocument | None = None
        for attempt in range(3):
            hint = last_err if attempt else None
            try:
                doc = run_session_pass(client, model, row, out, hint)
                if doc.metadata.session_number != row.session_number:
                    raise ValueError(
                        f"session_number {doc.metadata.session_number} != skeleton "
                        f"{row.session_number}"
                    )
                validate_fixture_document(doc)
                break
            except (ValidationError, ValueError) as e:
                last_err = str(e)
                if attempt == 2:
                    raise
        assert doc is not None
        out.append(doc)

    validate_corpus(out, count)
    return out


def write_fixture_files(fixtures: list[SessionFixtureDocument], output_dir: Path) -> list[Path]:
    """Write ``session_NN_<slug>.json`` files; return written paths."""
    from e2e.models import theme_to_slug

    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for doc in sorted(fixtures, key=lambda d: d.metadata.session_number):
        slug = theme_to_slug(doc.metadata.theme)
        nn = doc.metadata.session_number
        path = output_dir / f"session_{nn:02d}_{slug}.json"
        payload = json.loads(doc.model_dump_json(indent=2))
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        paths.append(path)
    return paths


def print_summary(fixtures: list[SessionFixtureDocument]) -> None:
    """Stdout summary for human review."""
    print("=== Session fixture corpus summary ===")
    for doc in sorted(fixtures, key=lambda d: d.metadata.session_number):
        n = doc.metadata.session_number
        tone = doc.expected_session_outcome.overall_emotional_tone
        vals = sorted({v for m in doc.key_moments for v in m.values_touched})
        print(f"  session {n}: theme={doc.metadata.theme!r} tone={tone:+.2f} values={vals}")
    all_vals: set[str] = set()
    for doc in fixtures:
        for m in doc.key_moments:
            all_vals.update(x.lower() for x in m.values_touched)
    print(f"  distinct values (lower): {sorted(all_vals)}")
    pq_all: set[str] = set()
    for doc in fixtures:
        for m in doc.key_moments:
            pq_all.update(m.principles_questioned)
    print(f"  principles questioned (all sessions): {sorted(pq_all)}")
    print("=== Review files before commit (LLM output is not deterministic). ===")
