#!/bin/bash
# Environment verification script for Atman Cloud Agents
# This script checks if the environment is properly configured

set -e

echo "🔍 Verifying Atman Cloud Agent Environment"
echo "=========================================="
echo ""

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

success() {
    echo -e "${GREEN}✅ $1${NC}"
}

warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

error() {
    echo -e "${RED}❌ $1${NC}"
}

# Check Python version
echo "1. Checking Python version..."
PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d'.' -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d'.' -f2)

if [ "$PYTHON_MAJOR" -ge 3 ] && [ "$PYTHON_MINOR" -ge 12 ]; then
    success "Python $PYTHON_VERSION (>= 3.12 required)"
else
    error "Python $PYTHON_VERSION (>= 3.12 required)"
    exit 1
fi

# Check pip
echo "2. Checking pip..."
if command -v pip &> /dev/null; then
    PIP_VERSION=$(pip --version | cut -d' ' -f2)
    success "pip $PIP_VERSION"
else
    error "pip not found"
    exit 1
fi

# Check pytest
echo "3. Checking pytest..."
if command -v pytest &> /dev/null; then
    PYTEST_VERSION=$(pytest --version | cut -d' ' -f2)
    success "pytest $PYTEST_VERSION"
else
    error "pytest not found"
    exit 1
fi

# Check git
echo "4. Checking git..."
if command -v git &> /dev/null; then
    GIT_VERSION=$(git --version | cut -d' ' -f3)
    success "git $GIT_VERSION"
else
    error "git not found"
    exit 1
fi

# Check uv (recommended, not required)
echo "5. Checking uv package manager..."
if command -v uv &> /dev/null; then
    UV_VERSION=$(uv --version | cut -d' ' -f2)
    success "uv $UV_VERSION (recommended for future work)"
else
    warning "uv not found (recommended for future work packages)"
    echo "   Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
fi

echo ""
echo "6. Installing project dependencies..."
if pip install -e . --quiet 2>&1; then
    success "Project installed in editable mode"
else
    error "Failed to install project"
    exit 1
fi

echo "7. Verifying project imports..."
if python3 -c "from atman.adapters.memory import InMemoryBackend, FileBackend; from atman.core.models import FactRecord" 2>/dev/null; then
    success "Core imports working"
else
    error "Failed to import core modules"
    exit 1
fi

echo "8. Running test suite..."
if pytest tests/ -q 2>&1 | tail -1 | grep -q "passed"; then
    TEST_RESULT=$(pytest tests/ -q 2>&1 | tail -1)
    success "Test suite passed: $TEST_RESULT"
else
    error "Test suite failed"
    pytest tests/ -v
    exit 1
fi

echo "9. Checking CLI..."
if python3 -c "import atman.cli; print('CLI module OK')" 2>/dev/null; then
    success "CLI module accessible"
else
    warning "CLI check failed"
fi

echo ""
echo "=========================================="
echo -e "${GREEN}🎉 Environment verification complete!${NC}"
echo ""
echo "Summary:"
echo "  - Python 3.12+ ✅"
echo "  - Core dependencies ✅"
echo "  - All tests passing ✅"
echo "  - Ready for development ✅"
echo ""

if ! command -v uv &> /dev/null; then
    echo "Recommendation:"
    echo "  Install uv for future work: curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo ""
fi
