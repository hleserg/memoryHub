#!/usr/bin/env bash
# =============================================================================
# Генерация секретов — вызывается из setup.sh
# Аргументы: <output_file> <pg_user> <pg_db> <pg_port> <qdrant_port> <llm> <embed>
# =============================================================================
set -euo pipefail

OUTPUT="$1"
PG_USER="$2"
PG_DB="$3"
PG_PORT="$4"
QD_PORT="$5"
LLM_MODEL="$6"
EMBED_MODEL="$7"

PG_PASS=$(openssl rand -base64 32 | tr -d '/+=' | head -c 32)
ATMAN_APP_PASS=$(openssl rand -base64 32 | tr -d '/+=' | head -c 32)
QD_KEY=$(openssl rand -base64 32 | tr -d '/+=' | head -c 32)

mkdir -p "$(dirname "${OUTPUT}")"
chmod 700 "$(dirname "${OUTPUT}")"

cat > "${OUTPUT}" << EOF
# Atman secrets — НЕ коммитить в git!
# Сгенерировано: $(date -u +"%Y-%m-%dT%H:%M:%SZ")

# PostgreSQL — суперпользователь (только для миграций)
POSTGRES_USER=${PG_USER}
POSTGRES_DB=${PG_DB}
POSTGRES_HOST=localhost
POSTGRES_PORT=${PG_PORT}
POSTGRES_PASSWORD=${PG_PASS}

# PostgreSQL — роль приложения (не суперпользователь, RLS применяется)
# Приложение подключается через DATABASE_URL. Суперпользователь — через ATMAN_ADMIN_DATABASE_URL.
ATMAN_APP_PASSWORD=${ATMAN_APP_PASS}
DATABASE_URL=postgresql://atman_app:${ATMAN_APP_PASS}@localhost:${PG_PORT}/${PG_DB}
ATMAN_ADMIN_DATABASE_URL=postgresql://${PG_USER}:${PG_PASS}@localhost:${PG_PORT}/${PG_DB}

QDRANT_URL=http://localhost:${QD_PORT}
QDRANT_API_KEY=${QD_KEY}

OLLAMA_URL=http://localhost:11434
ATMAN_OLLAMA_MODEL=${LLM_MODEL}
ATMAN_EMBED_MODEL=${EMBED_MODEL}
EMBEDDING_MODEL=${EMBED_MODEL}
OLLAMA_EMBED_MODEL=${EMBED_MODEL}
EOF

chmod 600 "${OUTPUT}"
