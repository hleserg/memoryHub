"""Anthropic API: skeleton pass + per-session fixture pass with tool_use."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from e2e.models import (
    SessionFixtureDocument,
    SessionSkeletonItem,
    SkeletonPassOutput,
    validate_fixture_document,
)
from e2e.prompts import (
    Locale,
    retry_prefix,
    session_system,
    session_user_prompt,
    skeleton_system,
    skeleton_user_prompt,
)
from e2e.validation import skeleton_matches_count, validate_corpus

CorpusPolicy = Literal["strict", "soft"]


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


def run_skeleton_pass(
    client: Any, model: str, count: int, locale: Locale
) -> list[SessionSkeletonItem]:
    """Call Anthropic once; return ordered skeleton rows."""
    input_schema = SkeletonPassOutput.model_json_schema()
    msg = client.messages.create(
        model=model,
        max_tokens=4096,
        system=skeleton_system(locale),
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
                "content": skeleton_user_prompt(count, locale),
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
    locale: Locale,
) -> SessionFixtureDocument:
    """Generate one session fixture; optional hint retries after validation failure."""
    schema = SessionFixtureDocument.model_json_schema()
    prior_summary = [fixture_summary(d) for d in prior_documents]
    user_text = session_user_prompt(skeleton, prior_summary, locale)
    if validation_error_hint:
        user_text = f"{retry_prefix(validation_error_hint, locale)}{user_text}"
    msg = client.messages.create(
        model=model,
        max_tokens=16384,
        system=session_system(locale),
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
    normalized = _normalize_fixture_payload(raw)
    _require_non_null_fixture_fields(normalized)
    return SessionFixtureDocument.model_validate(normalized)


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
    client: Any,
    model: str,
    count: int,
    locale: Locale = "en",
    output_dir: Path | None = None,
    *,
    corpus_policy: CorpusPolicy = "strict",
    max_corpus_regen_sessions: int = 12,
) -> list[SessionFixtureDocument]:
    """
    Full two-phase generation with up to 3 attempts per session (1 + 2 retries).

    ``corpus_policy``:

    - ``strict``: on ``validate_corpus`` failure, drop a tail of sessions and retry (unless
      the tail is longer than ``max_corpus_regen_sessions`` — then keep all files and return
      with a warning; use ``0`` for no limit).
    - ``soft``: never delete on corpus failure; warn and return the on-disk corpus.

    Raises the last ``ValidationError`` or ``ValueError`` if all attempts fail.
    """
    max_corpus_attempts = 8
    skeleton = run_skeleton_pass(client, model, count, locale)
    skeleton_by_num = {item.session_number: item for item in skeleton}
    docs_by_num = _load_existing_docs(output_dir, count)
    if docs_by_num:
        print(
            f"[{locale}] loaded {len(docs_by_num)} existing sessions from disk",
            flush=True,
        )

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    for corpus_attempt in range(1, max_corpus_attempts + 1):
        missing = [n for n in range(1, count + 1) if n not in docs_by_num]
        print(
            f"[{locale}] corpus attempt {corpus_attempt}/{max_corpus_attempts}: "
            f"{len(missing)} missing sessions",
            flush=True,
        )
        for session_number in missing:
            row = skeleton_by_num[session_number]
            prior_docs = [docs_by_num[n] for n in sorted(docs_by_num) if n < session_number]
            last_err: str | None = None
            doc: SessionFixtureDocument | None = None
            for attempt in range(3):
                hint = last_err if attempt else None
                try:
                    doc = run_session_pass(client, model, row, prior_docs, hint, locale)
                    if doc.metadata.session_number != row.session_number:
                        raise ValueError(
                            f"session_number {doc.metadata.session_number} != skeleton "
                            f"{row.session_number}"
                        )
                    validate_fixture_document(doc)
                    docs_by_num[session_number] = doc
                    if output_dir is not None:
                        saved_path = _write_single_fixture(doc, output_dir)
                        print(
                            f"[{locale}] session {session_number}/{count} saved: {saved_path.name}",
                            flush=True,
                        )
                    else:
                        print(f"[{locale}] session {session_number}/{count} ready", flush=True)
                    break
                except (ValidationError, ValueError) as e:
                    last_err = str(e)
                    if attempt == 2:
                        raise
            assert doc is not None

        out = [docs_by_num[n] for n in sorted(docs_by_num)]
        try:
            validate_corpus(out, count)
            return out
        except ValueError as e:
            if corpus_policy == "soft":
                print(
                    f"[{locale}] WARNING: corpus validation failed (soft policy; "
                    f"all files kept): {e}",
                    flush=True,
                )
                return out
            if corpus_attempt == max_corpus_attempts:
                raise
            to_regen = _sessions_to_regenerate(str(e), count)
            if to_regen is None:
                raise ValueError(
                    f"{e}\n\n"
                    "Corpus validation failed on a global rule (no specific session to trim). "
                    "Existing fixture files on disk were not deleted."
                ) from e
            if max_corpus_regen_sessions > 0 and len(to_regen) > max_corpus_regen_sessions:
                print(
                    f"[{locale}] WARNING: corpus validation failed; would re-generate "
                    f"{len(to_regen)} sessions (limit {max_corpus_regen_sessions}). "
                    f"Keeping all saved files. Error: {e}",
                    flush=True,
                )
                return out
            print(
                f"[{locale}] corpus validation failed: {e}. "
                f"Deleting {len(to_regen)} sessions and regenerating...",
                flush=True,
            )
            for n in to_regen:
                docs_by_num.pop(n, None)
                if output_dir is not None:
                    _delete_session_file(output_dir, n)

    raise RuntimeError("unreachable: corpus generation exited without result")


def write_fixture_files(fixtures: list[SessionFixtureDocument], output_dir: Path) -> list[Path]:
    """Write ``session_NN_<slug>.json`` files; return written paths."""
    from e2e.models import theme_to_slug

    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for doc in sorted(fixtures, key=lambda d: d.metadata.session_number):
        slug = theme_to_slug(doc.metadata.theme, doc.metadata.session_number)
        nn = doc.metadata.session_number
        path = output_dir / f"session_{nn:02d}_{slug}.json"
        payload = json.loads(doc.model_dump_json(indent=2))
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        paths.append(path)
    return paths


def _write_single_fixture(doc: SessionFixtureDocument, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    from e2e.models import theme_to_slug

    slug = theme_to_slug(doc.metadata.theme, doc.metadata.session_number)
    path = output_dir / f"session_{doc.metadata.session_number:02d}_{slug}.json"
    payload = json.loads(doc.model_dump_json(indent=2))
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _delete_session_file(output_dir: Path, session_number: int) -> None:
    pattern = f"session_{session_number:02d}_*.json"
    for p in output_dir.glob(pattern):
        p.unlink(missing_ok=True)


def _sessions_to_regenerate(error_text: str, count: int) -> list[int] | None:
    """
    Infer which sessions to discard after a corpus-level validation failure.

    For principle-follow-through errors, regenerate from the referenced session to the end.

    For global invariants (overlap, emotional palette, wrong corpus size) the error text does
    not pin a session number. Returning ``None`` means: do **not** delete any files — abort
    so the operator keeps everything already saved on disk.
    """
    m = re.search(r"session\s+(\d+)", error_text)
    if m:
        start = int(m.group(1))
        if 1 <= start <= count:
            return list(range(start, count + 1))
    return None


def _load_existing_docs(output_dir: Path | None, count: int) -> dict[int, SessionFixtureDocument]:
    """Load already generated session files and keep only valid docs in range 1..count."""
    if output_dir is None or not output_dir.exists():
        return {}
    docs_by_num: dict[int, SessionFixtureDocument] = {}
    for path in sorted(output_dir.glob("session_*.json")):
        try:
            raw = path.read_text(encoding="utf-8")
            doc = SessionFixtureDocument.model_validate_json(raw)
            n = doc.metadata.session_number
            if 1 <= n <= count:
                validate_fixture_document(doc)
                docs_by_num[n] = doc
        except Exception:
            # Malformed partial files are ignored; they will be regenerated.
            continue
    return docs_by_num


def _parse_json_from_string(
    s: str, *, kind: Literal["list", "dict"]
) -> list[Any] | dict[str, Any] | None:
    """Parse JSON list or object from a string; tolerate extra wrapping / bracket slicing."""
    text = s.strip()
    candidates: list[str] = [text]
    lo, hi = ("[", "]") if kind == "list" else ("{", "}")
    start = text.find(lo)
    end = text.rfind(hi)
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for cand in candidates:
        try:
            parsed: Any = json.loads(cand)
            if kind == "list":
                if isinstance(parsed, list):
                    return parsed
                if isinstance(parsed, str):
                    nested = _parse_json_from_string(parsed, kind="list")
                    if nested is not None:
                        return nested
            if kind == "dict" and isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    return None


def _unwrap_json_string_layers(val: Any, *, kind: Literal["list", "dict"]) -> Any:
    """Apply ``_parse_json_from_string`` repeatedly (double-encoded tool payloads)."""
    for _ in range(4):
        if not isinstance(val, str):
            break
        nxt = _parse_json_from_string(val, kind=kind)
        if nxt is None:
            break
        val = nxt
    return val


def _require_non_null_fixture_fields(normalized: dict[str, Any]) -> None:
    """Reject incomplete tool payloads so session retries get an explicit hint."""
    required = ("events", "key_moments", "metadata", "expected_session_outcome")
    bad = [k for k in required if normalized.get(k) is None]
    if bad:
        raise ValueError(
            "Incomplete fixture from model (null or missing): "
            + ", ".join(bad)
            + ". Resubmit with full events, key_moments, metadata, expected_session_outcome."
        )


def _normalize_fixture_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize occasional tool payload quirks where lists/objects come as JSON strings.
    """
    normalized = dict(raw)
    for key in ("events", "key_moments"):
        val = normalized.get(key)
        val = _unwrap_json_string_layers(val, kind="list")
        normalized[key] = val
    for key in ("metadata", "expected_session_outcome"):
        val = normalized.get(key)
        val = _unwrap_json_string_layers(val, kind="dict")
        normalized[key] = val
    return normalized


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
