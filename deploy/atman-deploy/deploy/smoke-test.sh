#!/usr/bin/env bash
# Smoke test — вызывается из setup.sh в конце
# Аргументы: <pg_user> <pg_db> <qdrant_port> <qdrant_key> <embed_model> <docker_cmd> [expected_dim]
set -euo pipefail

PG_USER="$1"
PG_DB="$2"
QD_PORT="$3"
QD_KEY="$4"
EMBED_MODEL="$5"
DOCKER="${6:-docker}"
EXPECTED_EMBED_DIM="${7:-1024}"

G='\033[0;32m' R='\033[0;31m' N='\033[0m'
ok()  { echo -e "${G}[✓]${N} $*"; }
fail(){ echo -e "${R}[✗]${N} $*"; }

ERRORS=0

# PostgreSQL — количество таблиц
PG_COUNT=$(${DOCKER} exec atman-postgres \
    psql -U "${PG_USER}" -d "${PG_DB}" \
    -t -A -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';" \
    2>/dev/null) && ok "PostgreSQL: ${PG_COUNT} объектов" \
    || { fail "PostgreSQL недоступен"; ERRORS=$((ERRORS+1)); }

# pgvector
PG_VEC=$(${DOCKER} exec atman-postgres \
    psql -U "${PG_USER}" -d "${PG_DB}" \
    -t -A -c "SELECT extversion FROM pg_extension WHERE extname='vector';" \
    2>/dev/null) && ok "pgvector: v${PG_VEC}" \
    || { fail "pgvector не установлен"; ERRORS=$((ERRORS+1)); }

# RLS
RLS_COUNT=$(${DOCKER} exec atman-postgres \
    psql -U "${PG_USER}" -d "${PG_DB}" \
    -t -A -c "SELECT COUNT(*) FROM pg_tables WHERE rowsecurity=true AND schemaname='public';" \
    2>/dev/null) && ok "RLS: ${RLS_COUNT} таблиц защищены" \
    || { fail "RLS не применён"; ERRORS=$((ERRORS+1)); }

# Триггеры иммутабельности
TRIG_COUNT=$(${DOCKER} exec atman-postgres \
    psql -U "${PG_USER}" -d "${PG_DB}" \
    -t -A -c "SELECT COUNT(*) FROM information_schema.triggers WHERE trigger_name LIKE '%immutable%' OR trigger_name LIKE '%append%';" \
    2>/dev/null) && ok "Триггеры иммутабельности: ${TRIG_COUNT}" \
    || { fail "Триггеры не созданы"; ERRORS=$((ERRORS+1)); }

# Qdrant — коллекции
for COL in atman_facts atman_experiences; do
    STATUS=$(curl -sf "http://localhost:${QD_PORT}/collections/${COL}" \
        -H "api-key: ${QD_KEY}" 2>/dev/null \
        | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['status'])" 2>/dev/null \
        || echo "error")
    if [[ "${STATUS}" == "green" ]]; then
        ok "Qdrant [${COL}]: green"
    else
        fail "Qdrant [${COL}]: ${STATUS}"
        ERRORS=$((ERRORS+1))
    fi
done

# Ollama — embedding
EMBED_DIM=$(curl -sf http://localhost:11434/api/embeddings \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"${EMBED_MODEL}\",\"prompt\":\"тест\"}" \
    | python3 -c "import sys,json; print(len(json.load(sys.stdin)['embedding']))" 2>/dev/null \
    || echo "0")

if [[ "${EMBED_DIM}" -eq "${EXPECTED_EMBED_DIM}" ]]; then
    ok "Embedding: ${EMBED_DIM} dims"
else
    fail "Embedding: ожидалось ${EXPECTED_EMBED_DIM}, получено ${EMBED_DIM}"
    ERRORS=$((ERRORS+1))
fi

# Итог
echo ""
if [[ "${ERRORS}" -eq 0 ]]; then
    echo -e "${G}Все проверки пройдены${N}"
else
    echo -e "${R}Ошибок: ${ERRORS}${N}"
    exit 1
fi
