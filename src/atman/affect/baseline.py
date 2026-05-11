"""Rolling z-score baseline persisted as JSONL under the workspace."""

from __future__ import annotations

import json
import math
from collections import deque
from pathlib import Path
from typing import Any

METRIC_KEYS = (
    "nrc_valence",
    "hedge_density",
    "length_z",
    "question_tail_density",
    "self_reference_density",
    "disclaimer_density",
    "negation_adjusted_valence",
    "emotion_lexical_energy",
)


class RollingBaseline:
    """FIFO window of metric vectors with JSONL persistence."""

    def __init__(self, path: Path, window: int = 200) -> None:
        self.path = path
        self.window = window
        self._history: deque[dict[str, float]] = deque(maxlen=window)
        self._chars: deque[int] = deque(maxlen=window)
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        rows: list[dict[str, float]] = []
        chars: list[int] = []
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj: dict[str, Any] = json.loads(line)
                except json.JSONDecodeError:
                    continue
                vec = obj.get("metrics")
                if isinstance(vec, dict):
                    rows.append({k: float(vec[k]) for k in METRIC_KEYS if k in vec})
                cc = obj.get("char_count")
                if isinstance(cc, int | float):
                    chars.append(int(cc))
        for row in rows[-self.window :]:
            self._history.append(row)
        for c in chars[-self.window :]:
            self._chars.append(c)

    def _persist_row(self, row: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def char_mean_std(self) -> tuple[float, float]:
        """Mean and std of observed character counts (degenerate-safe)."""
        if not self._chars:
            return 0.0, 1.0
        if len(self._chars) == 1:
            return float(self._chars[0]), 1.0
        mean = sum(self._chars) / len(self._chars)
        var = sum((c - mean) ** 2 for c in self._chars) / max(1, (len(self._chars) - 1))
        std = math.sqrt(var)
        return mean, max(std, 1e-9)

    def update(
        self,
        metrics: dict[str, float],
        char_count: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Append metrics to memory and JSONL."""
        row = {k: float(metrics[k]) for k in METRIC_KEYS}
        self._history.append(row.copy())
        if char_count is not None:
            self._chars.append(int(char_count))
        payload: dict[str, Any] = {"metrics": row}
        if char_count is not None:
            payload["char_count"] = int(char_count)
        if extra:
            payload.update(extra)
        self._persist_row(payload)

    def z_scores(self, metrics: dict[str, float]) -> dict[str, float]:
        """Population z-scores vs rolling history (current row not yet in history)."""
        if len(self._history) < 2:
            return {k: 0.0 for k in METRIC_KEYS}
        out: dict[str, float] = {}
        for key in METRIC_KEYS:
            vals = [h[key] for h in self._history if key in h]
            if len(vals) < 2:
                out[key] = 0.0
                continue
            mean = sum(vals) / len(vals)
            var = sum((v - mean) ** 2 for v in vals) / max(1, (len(vals) - 1))
            std = math.sqrt(var)
            if std <= 1e-9:
                out[key] = 0.0
            else:
                out[key] = (float(metrics[key]) - mean) / std
        return out
