"""Deterministic seed helpers for eval runs."""

from __future__ import annotations

import random
import time


def resolve_seed(seed: int | None) -> int:
    """Return user-provided seed or generate a stable integer."""
    if seed is not None:
        return seed
    return int(time.time_ns() % (2**31 - 1))


def apply_global_seed(seed: int) -> None:
    """Apply seed to stdlib and optional numpy RNG."""
    random.seed(seed)
    try:
        import numpy as np  # type: ignore[import-not-found]
    except ImportError:
        return
    np.random.seed(seed)
