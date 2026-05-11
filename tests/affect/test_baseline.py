"""Rolling baseline tests."""

from __future__ import annotations

from pathlib import Path

from atman.affect.baseline import METRIC_KEYS, RollingBaseline


def test_rolling_baseline_z_scores_degenerate(tmp_path: Path) -> None:
    p = tmp_path / "affect_baseline.jsonl"
    b = RollingBaseline(p, window=50)
    vec = {k: 1.0 for k in METRIC_KEYS}
    z = b.z_scores(vec)
    assert all(v == 0.0 for v in z.values())
    b.update(vec, char_count=10)
    z2 = b.z_scores(vec)
    assert isinstance(z2["nrc_valence"], float)


def test_char_mean_std_single_value(tmp_path: Path) -> None:
    p = tmp_path / "a2.jsonl"
    b = RollingBaseline(p, window=10)
    vec = {k: 0.0 for k in METRIC_KEYS}
    b.update(vec, char_count=42)
    mean, std = b.char_mean_std()
    assert mean == 42.0
    assert std >= 1e-9
