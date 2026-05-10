"""Atman evaluation subsystem.

Optional namespace — not part of the production install.
Install with: pip install 'atman[eval]'

This module is intentionally isolated from the production code in
src/atman/{factual_memory,identity_store,...}. Production code MUST NOT
import from atman.eval; this is enforced by import-linter (.importlinter)
and verified by `make verify-prod-isolation`.
"""

from atman.eval._deps_check import _check_eval_deps_installed

_check_eval_deps_installed()

# Public API is filled in by epics E1-E20:
#   from atman.eval.runner import BenchmarkRunner, RunContext
#   from atman.eval.judge import OllamaJudge, OpenAIJudge
#   ...

