"""Lazy dependency check for atman.eval.

Imported once on `import atman.eval`. Raises a friendly ImportError if
required eval dependencies are missing.
"""

import importlib.util

# Canary deps — if any of these is missing, the user installed bare `atman`
# instead of `atman[eval]`. We don't check every eval dep, just one obvious
# canary that uniquely belongs to the eval extra; full dep set is in
# pyproject.toml under ``[project.optional-dependencies] eval``.
#
# As of E0 the eval extra contains alembic / psycopg / sqlalchemy / click
# (needed for migrations only); larger model/dataset deps will be added by
# E-1.2 (#211) and E5+ work packages. Update this canary set when the eval
# extra surface grows.
_REQUIRED_CANARIES = (("alembic", "alembic"),)


def _check_eval_deps_installed() -> None:
    missing = [
        pip_name
        for module_name, pip_name in _REQUIRED_CANARIES
        if importlib.util.find_spec(module_name) is None
    ]
    if missing:
        raise ImportError(
            "atman.eval requires extra dependencies (currently missing: "
            + ", ".join(missing)
            + "). Install with:\n\n    pip install 'atman[eval]'\n\n"
            "or with uv:\n\n    uv sync --extra eval\n"
        )
