"""Registered product features for the developer UI."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DemoCommand:
    """One runnable demo (argv after ``uv run`` / ``python -m`` prefix)."""

    label: str
    argv: tuple[str, ...]
    env: dict[str, str]


@dataclass(frozen=True)
class FeatureInfo:
    slug: str
    title: str
    summary: str
    doc_dir: str  # relative to repo root, e.g. docs/features/foo
    related_paths: tuple[str, ...]
    demos: tuple[DemoCommand, ...]
    test_globs: tuple[str, ...]


FEATURES: tuple[FeatureInfo, ...] = (
    FeatureInfo(
        slug="factual-memory",
        title="Factual Memory Adapter",
        summary="Verifiable facts storage, search, and file-backed adapter with CLI demo.",
        doc_dir="docs/features/factual-memory",
        related_paths=(
            "src/atman/adapters/memory/",
            "src/atman/core/models/fact.py",
            "src/atman/core/ports/memory_backend.py",
            "src/demo.py",
            "src/atman/cli.py",
        ),
        demos=(
            DemoCommand(
                "Demo (paced)",
                ("src/demo.py",),
                {"ATMAN_DEMO_PACE": "1"},
            ),
            DemoCommand(
                "Demo (fast)",
                ("src/demo.py",),
                {"ATMAN_DEMO_PACE": "off"},
            ),
        ),
        test_globs=(
            "tests/test_*backend*.py",
            "tests/test_models.py",
            "tests/test_file_backend.py",
        ),
    ),
    FeatureInfo(
        slug="experience-store",
        title="Experience Store",
        summary="Session experience records, salience, JSONL persistence, and service API.",
        doc_dir="docs/features/experience-store",
        related_paths=(
            "src/atman/adapters/storage/",
            "src/atman/core/models/experience.py",
            "src/atman/core/services/experience_service.py",
            "src/demo_experience_store.py",
            "src/atman/cli_experience.py",
        ),
        demos=(
            DemoCommand(
                "Demo (paced)",
                ("src/demo_experience_store.py",),
                {"ATMAN_DEMO_PACE": "1"},
            ),
            DemoCommand(
                "Demo (fast)",
                ("src/demo_experience_store.py",),
                {"ATMAN_DEMO_PACE": "off"},
            ),
        ),
        test_globs=(
            "tests/test_experience_*.py",
            "tests/test_experience_service.py",
        ),
    ),
)


def get_feature(slug: str) -> FeatureInfo | None:
    for f in FEATURES:
        if f.slug == slug:
            return f
    return None
