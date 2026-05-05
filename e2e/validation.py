"""Cross-session checks and corpus-level emotional palette (issue #141)."""

from __future__ import annotations

from collections import defaultdict

from e2e.models import SessionFixtureDocument, SessionSkeletonItem, norm_token


def validate_corpus(fixtures: list[SessionFixtureDocument], count: int) -> None:
    """
    Cross-session coherence: overlapping values, principle follow-ups, palette (for 5-pack).

    Raises ``ValueError`` on failure.
    """
    if len(fixtures) != count:
        raise ValueError(f"expected {count} fixtures, got {len(fixtures)}")
    ordered = sorted(fixtures, key=lambda f: f.metadata.session_number)
    nums = [f.metadata.session_number for f in ordered]
    if nums != list(range(1, count + 1)):
        raise ValueError(f"session_number must be 1..{count} exactly once each, got {nums!r}")
    # Cross-session rules require at least two sessions (e.g. --count-en 1 is valid for smoke tests).
    if count >= 2:
        _check_values_overlap(ordered)
        _check_principle_follow_through(ordered)
    if count == 5:
        _check_emotional_palette_five(ordered)


def _check_values_overlap(fixtures: list[SessionFixtureDocument]) -> None:
    value_sessions: dict[str, set[int]] = defaultdict(set)
    for f in fixtures:
        n = f.metadata.session_number
        for km in f.key_moments:
            for v in km.values_touched:
                value_sessions[v.strip().lower()].add(n)
    if not any(len(sessions) >= 2 for sessions in value_sessions.values()):
        raise ValueError(
            "cross-session values: at least one value in values_touched must appear "
            "in key moments across 2+ sessions"
        )


def _check_principle_follow_through(fixtures: list[SessionFixtureDocument]) -> None:
    """``principles_questioned`` in session *i* must be echoed in some session *j* > *i*."""
    for i, early in enumerate(fixtures):
        later = fixtures[i + 1 :]
        if not later:
            break
        questioned: set[str] = set()
        for km in early.key_moments:
            questioned.update(km.principles_questioned)
        for principle in questioned:
            if not _principle_addressee_in_later(principle, later):
                raise ValueError(
                    f"principle {principle!r} questioned in session "
                    f"{early.metadata.session_number} must be confirmed, questioned again, "
                    "or reflected in narrative/events text of a later session"
                )


def _principle_addressee_in_later(principle: str, later: list[SessionFixtureDocument]) -> bool:
    needle = norm_token(principle)
    if not needle:
        return True
    # Long principles are often paraphrased by LLMs; keep follow-through as soft guidance.
    if len(needle.split()) > 5:
        return True
    for fx in later:
        blob_parts: list[str] = [
            norm_token(fx.metadata.narrative_arc),
            norm_token(fx.metadata.theme),
        ]
        for e in fx.events:
            blob_parts.append(norm_token(e.description))
        for km in fx.key_moments:
            blob_parts.append(norm_token(km.what_happened))
            blob_parts.append(norm_token(km.why_it_matters))
            blob_parts.append(norm_token(km.what_changed))
            for pc in km.principles_confirmed:
                blob_parts.append(norm_token(pc))
            for pq in km.principles_questioned:
                blob_parts.append(norm_token(pq))
        blob = " ".join(blob_parts)
        if _principle_mentioned_in_blob(needle, blob):
            return True
    return False


def _principle_mentioned_in_blob(needle: str, blob: str) -> bool:
    if needle in blob:
        return True
    needle_tokens = [t for t in needle.split() if len(t) >= 3]
    if len(needle_tokens) < 2:
        return False
    matched = sum(1 for token in needle_tokens if token in blob)
    return matched >= 2 and matched >= (len(needle_tokens) + 1) // 2


def _check_emotional_palette_five(fixtures: list[SessionFixtureDocument]) -> None:
    """
    Rough palette: avoid degenerate corpus — need spread across overall tones.

    Maps to issue #141: routine / breakthrough / principle doubt / conflict / integration.
    """
    tones = [f.expected_session_outcome.overall_emotional_tone for f in fixtures]
    if max(tones) - min(tones) < 0.35:
        raise ValueError(
            f"emotional palette too narrow for 5-session corpus: tone range "
            f"{min(tones):.2f}..{max(tones):.2f} (need span >= 0.35)"
        )
    positives = sum(1 for t in tones if t >= 0.2)
    negatives = sum(1 for t in tones if t <= -0.1)
    neutrals = sum(1 for t in tones if -0.15 <= t <= 0.15)
    if positives < 1 or negatives < 1:
        raise ValueError(
            "emotional palette: need at least one session with tone >= 0.2 and "
            "one with tone <= -0.1"
        )
    if neutrals < 1:
        raise ValueError(
            "emotional palette: include at least one roughly neutral session "
            "(overall_emotional_tone between -0.15 and 0.15)"
        )


def skeleton_matches_count(skeleton: list[SessionSkeletonItem], count: int) -> None:
    if len(skeleton) != count:
        raise ValueError(f"skeleton length {len(skeleton)} != --count {count}")
    nums = sorted(s.session_number for s in skeleton)
    if nums != list(range(1, count + 1)):
        raise ValueError(f"skeleton session_number must be 1..{count}, got {nums!r}")
