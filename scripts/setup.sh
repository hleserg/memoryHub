#!/usr/bin/env bash
# scripts/setup.sh — memoryHub first-run initialization
# Creates required directories, applies DB migrations, validates config.
# See ARCHITECTURE.md §9 Deployment Diagram, Appendix A Quick Start
#
# Usage:
#   bash scripts/setup.sh                        # Default data dir from env/config
#   MEMORYHUB_DATA_DIR=/custom/path bash scripts/setup.sh

set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────
DATA_DIR="${MEMORYHUB_DATA_DIR:-./data}"
CONFIG_FILE="${MEMORYHUB_CONFIG:-config/memoryhub.config.yaml}"
DB_FILE="${DATA_DIR}/memoryhub.sqlite"
MIGRATIONS_DIR="db/migrations"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

info()    { echo -e "${GREEN}→${NC} $*"; }
warn()    { echo -e "${YELLOW}⚠${NC}  $*"; }
error()   { echo -e "${RED}✗${NC} $*" >&2; }
success() { echo -e "${GREEN}✓${NC} $*"; }

echo ""
echo "memoryHub — Setup Script"
echo "━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ─────────────────────────────────────────────────────────────────────────
# Check dependencies
# ─────────────────────────────────────────────────────────────────────────
info "Checking dependencies..."

if ! command -v sqlite3 &>/dev/null; then
    error "sqlite3 not found. Install it first:"
    error "  macOS:  brew install sqlite"
    error "  Ubuntu: sudo apt-get install sqlite3"
    exit 1
fi

if ! command -v go &>/dev/null; then
    warn "go not found — skipping Go compilation check"
fi

success "Dependencies OK"

# ─────────────────────────────────────────────────────────────────────────
# Create directory structure
# See ARCHITECTURE.md §9 /data/memoryhub/ layout
# ─────────────────────────────────────────────────────────────────────────
info "Creating directory structure at ${DATA_DIR}..."

mkdir -p \
    "${DATA_DIR}/kuzu" \
    "${DATA_DIR}/backups" \
    "${DATA_DIR}/logs" \
    "${DATA_DIR}/keys"

success "Directories created"

# ─────────────────────────────────────────────────────────────────────────
# Validate config file
# ─────────────────────────────────────────────────────────────────────────
info "Checking config file..."

if [ ! -f "${CONFIG_FILE}" ]; then
    warn "Config file not found at ${CONFIG_FILE}"
    warn "Creating from template..."
    cp config/memoryhub.config.yaml "${CONFIG_FILE}" 2>/dev/null || {
        warn "Template not found either. Please create ${CONFIG_FILE} manually."
        warn "Reference: ARCHITECTURE.md §10 Единый конфиг"
    }
else
    success "Config found: ${CONFIG_FILE}"
fi

# ─────────────────────────────────────────────────────────────────────────
# Run DB migrations
# See db/migrations/ — applied in numerical order
# ─────────────────────────────────────────────────────────────────────────
info "Running database migrations on ${DB_FILE}..."

if [ ! -d "${MIGRATIONS_DIR}" ]; then
    error "Migrations directory not found: ${MIGRATIONS_DIR}"
    exit 1
fi

MIGRATION_COUNT=0
for migration in "${MIGRATIONS_DIR}"/*.sql; do
    if [ -f "${migration}" ]; then
        MIGRATION_NAME=$(basename "${migration}")
        echo "  Applying ${MIGRATION_NAME}..."
        sqlite3 "${DB_FILE}" < "${migration}" || {
            error "Migration failed: ${MIGRATION_NAME}"
            exit 1
        }
        MIGRATION_COUNT=$((MIGRATION_COUNT + 1))
    fi
done

if [ "${MIGRATION_COUNT}" -eq 0 ]; then
    warn "No migration files found in ${MIGRATIONS_DIR}"
else
    success "Applied ${MIGRATION_COUNT} migration(s)"
fi

# ─────────────────────────────────────────────────────────────────────────
# Verify database schema
# ─────────────────────────────────────────────────────────────────────────
info "Verifying database schema..."

TABLES=$(sqlite3 "${DB_FILE}" ".tables" 2>/dev/null || echo "")

REQUIRED_TABLES=(memories agents audit_log pending_review quarantine agent_metrics system_state)
ALL_OK=true

for table in "${REQUIRED_TABLES[@]}"; do
    if echo "${TABLES}" | grep -qw "${table}"; then
        echo "  ✓ ${table}"
    else
        error "  ✗ Missing table: ${table}"
        ALL_OK=false
    fi
done

if [ "${ALL_OK}" = false ]; then
    error "Schema verification failed. Check migration files."
    exit 1
fi

success "Schema verified"

# ─────────────────────────────────────────────────────────────────────────
# Check for .env file
# ─────────────────────────────────────────────────────────────────────────
info "Checking environment configuration..."

if [ ! -f "docker/.env" ]; then
    warn "docker/.env not found"
    warn "Copy the template and fill in real values:"
    warn "  cp docker/.env.example docker/.env"
    warn "  vim docker/.env"
else
    success "docker/.env found"

    # Warn about placeholder values
    if grep -q "REPLACE_WITH" docker/.env 2>/dev/null; then
        warn "Some values in docker/.env still contain placeholders (REPLACE_WITH_...)"
        warn "Update them before running in production!"
    fi
fi

# ─────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
success "Setup complete!"
echo ""
echo "  Data directory: ${DATA_DIR}"
echo "  Database:       ${DB_FILE}"
echo "  Config:         ${CONFIG_FILE}"
echo ""
echo "Next steps:"
echo "  1. Edit config: vim ${CONFIG_FILE}"
echo "  2. Fill in secrets: vim docker/.env"
echo "  3. Start the server: make dev"
echo "  4. Create admin key: memoryhub keys create --name admin --tier trusted --permissions all"
echo "  5. Verify: curl http://localhost:3000/v1/health"
echo ""
echo "See ARCHITECTURE.md Appendix A for full Quick Start guide."
echo ""
