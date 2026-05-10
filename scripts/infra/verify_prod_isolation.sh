#!/usr/bin/env bash
# Verify that a bare-prod install does not pull eval dependencies
# and that atman.eval is not importable.

set -euo pipefail

TMP=$(mktemp -d)
trap "rm -rf $TMP" EXIT

echo "→ Creating clean venv at $TMP/venv"
python -m venv "$TMP/venv"
# shellcheck source=/dev/null
source "$TMP/venv/bin/activate"

echo "→ Installing bare atman (no extras)"
pip install -e . --quiet --upgrade pip > /dev/null
pip install -e . --quiet

# Forbidden packages in prod
FORBIDDEN=(streamlit huggingface_hub datasets plotly openai)
FAIL=0

echo ""
echo "→ Checking forbidden packages are NOT installed:"
for pkg in "${FORBIDDEN[@]}"; do
    if pip show "$pkg" > /dev/null 2>&1; then
        echo "  ✗ $pkg should NOT be in prod"
        FAIL=1
    else
        echo "  ✓ $pkg absent"
    fi
done

echo ""
echo "→ Checking atman imports:"
if python -c "import atman" 2>/dev/null; then
    echo "  ✓ import atman OK"
else
    echo "  ✗ import atman failed"
    FAIL=1
fi

echo "→ Checking atman.eval is properly gated:"
if python -c "import atman.eval" 2>/dev/null; then
    echo "  ✗ atman.eval imported without [eval] extras — gate broken"
    FAIL=1
else
    echo "  ✓ atman.eval correctly raises ImportError without [eval]"
fi

echo ""
if [[ $FAIL -eq 0 ]]; then
    echo "✅ Production isolation verified."
    exit 0
else
    echo "❌ Production isolation BROKEN. See messages above."
    exit 1
fi

