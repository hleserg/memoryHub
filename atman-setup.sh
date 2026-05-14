#!/usr/bin/env bash
# =============================================================================
# Atman Memory Stack — полный деплой
# Требования: Ubuntu 22.04+ в WSL2, uv установлен, sudo доступ
# Использование: bash atman-setup.sh
# =============================================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

log()    { echo -e "${CYAN}[atman]${NC} $*"; }
ok()     { echo -e "${GREEN}[✓]${NC} $*"; }
warn()   { echo -e "${YELLOW}[!]${NC} $*"; }
error()  { echo -e "${RED}[✗]${NC} $*"; exit 1; }
header() { echo -e "\n${BOLD}${BLUE}━━━ $* ━━━${NC}"; }
info()   { echo -e "    ${BLUE}→${NC} $*"; }

# ── Конфигурация ─────────────────────────────────────────────────────────────
ATMAN_DIR="${HOME}/.atman"
SECRETS_FILE="${ATMAN_DIR}/.secrets"
POSTGRES_VERSION="16"
POSTGRES_DB="atman"
POSTGRES_USER="atman"
POSTGRES_PORT="5432"
QDRANT_PORT="6333"
QDRANT_VERSION="latest"
OLLAMA_LLM_MODEL="qwen3.5:9b"
OLLAMA_EMBED_MODEL="bge-m3"

# NVMe путь — скрипт определит автоматически или использует дефолт
NVME_PATH=""
OLLAMA_MODELS_PATH=""
DOCKER_DATA_PATH=""

# ── Баннер ───────────────────────────────────────────────────────────────────
clear
echo -e "${BOLD}"
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║         Atman Memory Stack Setup             ║"
echo "  ║                                              ║"
echo "  ║  PostgreSQL 16 + pgvector                    ║"
echo "  ║  Qdrant · Ollama · Qwen3.5:9b              ║"
echo "  ║  bge-m3 · Flash Attention                    ║"
echo "  ╚══════════════════════════════════════════════╝"
echo -e "${NC}"
echo -e "  Начало: $(date '+%Y-%m-%d %H:%M:%S')\n"

# ── 1. Проверки окружения ─────────────────────────────────────────────────────
header "Шаг 1 / 10 — Проверка окружения"

# WSL2?
if grep -qi microsoft /proc/version 2>/dev/null; then
    ok "WSL2 обнаружен"
else
    warn "Не похоже на WSL2 — продолжаю как обычный Linux"
fi

# sudo
sudo -n true 2>/dev/null || sudo true
ok "sudo доступен"

# uv
if ! command -v uv &>/dev/null; then
    log "uv не найден — устанавливаю..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="${HOME}/.local/bin:${PATH}"
    ok "uv установлен"
else
    ok "uv $(uv --version | awk '{print $2}')"
fi

# Docker
if ! command -v docker &>/dev/null || ! docker info &>/dev/null || docker --version 2>&1 | grep -q "Windows"; then
    log "Docker не найден или неработоспособен — устанавливаю Docker Engine для WSL2..."
    sudo apt-get update -qq
    sudo apt-get install -y -qq ca-certificates curl gnupg lsb-release
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
        | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update -qq
    sudo apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
    sudo usermod -aG docker "${USER}"
    ok "Docker установлен"
else
    ok "Docker $(docker --version | awk '{print $3}' | tr -d ',')"
fi

# Запуск Docker (адаптация для WSL2)
if grep -qi microsoft /proc/version 2>/dev/null; then
    # WSL2 - запускаем Docker daemon напрямую
    if ! sudo service docker status >/dev/null 2>&1; then
        sudo service docker start > /dev/null 2>&1 || true
        sleep 3
    fi
else
    # Обычный Linux с systemd
    if ! sudo systemctl is-active --quiet docker 2>/dev/null; then
        sudo systemctl enable --now docker > /dev/null 2>&1 || true
        sleep 2
    fi
fi

# Проверяем доступ к Docker без sudo
if ! docker ps &>/dev/null; then
    warn "Docker требует sudo — добавляю в группу docker"
    sudo usermod -aG docker "${USER}" 2>/dev/null || true
    DOCKER_CMD="sudo docker"
else
    DOCKER_CMD="docker"
fi
ok "Docker daemon запущен"

# Базовые утилиты
log "Устанавливаю зависимости..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    curl wget openssl python3 python3-pip \
    util-linux git \
    > /dev/null 2>&1
ok "Базовые утилиты готовы"

# ── 2. Определяем NVMe диск ──────────────────────────────────────────────────
header "Шаг 2 / 10 — Определение хранилища"

log "Сканирую доступные диски..."
echo ""
lsblk -o NAME,SIZE,TYPE,MOUNTPOINT,MODEL 2>/dev/null || lsblk
echo ""

# Ищем NVMe автоматически
if [[ -d "/mnt/nvme" ]]; then
    NVME_PATH="/mnt/nvme"
    NVME_DEVICE=$(lsblk -o NAME,MOUNTPOINT 2>/dev/null | grep "${NVME_PATH}" | head -1 | awk '{print $1}')
    NVME_SIZE=$(lsblk -o NAME,SIZE,MOUNTPOINT 2>/dev/null | grep "${NVME_PATH}" | head -1 | awk '{print $2}')
    ok "NVMe найден: /dev/${NVME_DEVICE} (${NVME_SIZE}) → смонтирован в ${NVME_PATH}"
else
    # Ищем большой диск смонтированный не как /
    ALT_MOUNT=$(lsblk -o MOUNTPOINT,SIZE 2>/dev/null | grep -v "^/" | grep -v "MOUNTPOINT" | grep -v "^$" | sort -rh | head -1 | awk '{print $1}')
    if [[ -n "${ALT_MOUNT}" ]]; then
        NVME_PATH="${ALT_MOUNT}"
        warn "NVMe не найден, использую: ${NVME_PATH}"
    else
        NVME_PATH="${HOME}"
        warn "Отдельный диск не найден — использую домашнюю директорию: ${NVME_PATH}"
    fi
fi

# Пути для данных
OLLAMA_MODELS_PATH="${NVME_PATH}/atman/ollama/models"
DOCKER_DATA_PATH="${NVME_PATH}/atman/docker"
ATMAN_DATA_PATH="${NVME_PATH}/atman/data"
PG_BACKUP_PATH="${NVME_PATH}/atman/backups"

log "Создаю директории на ${NVME_PATH}..."
mkdir -p "${OLLAMA_MODELS_PATH}"
mkdir -p "${DOCKER_DATA_PATH}"
mkdir -p "${ATMAN_DATA_PATH}"
mkdir -p "${PG_BACKUP_PATH}"
ok "Директории созданы в ${NVME_PATH}/atman/"

# Переносим Docker data-root если не там
CURRENT_DOCKER_ROOT=$(docker info 2>/dev/null | grep "Docker Root Dir" | awk '{print $4}' || echo "/var/lib/docker")
if [[ "${CURRENT_DOCKER_ROOT}" != "${DOCKER_DATA_PATH}" && "${NVME_PATH}" != "${HOME}" ]]; then
    log "Переношу Docker data-root на NVMe..."
    if grep -qi microsoft /proc/version 2>/dev/null; then
        # WSL2 - используем service
        sudo service docker stop 2>/dev/null || true
    else
        # Обычный Linux с systemd
        sudo systemctl stop docker 2>/dev/null || true
    fi
    sudo mkdir -p "${DOCKER_DATA_PATH}"
    if [[ -d "/var/lib/docker" ]]; then
        sudo rsync -a /var/lib/docker/ "${DOCKER_DATA_PATH}/" 2>/dev/null || true
    fi
    sudo tee /etc/docker/daemon.json > /dev/null << EOF
{
  "data-root": "${DOCKER_DATA_PATH}",
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
EOF
    if grep -qi microsoft /proc/version 2>/dev/null; then
        # WSL2 - используем service
        sudo service docker start 2>/dev/null || true
    else
        # Обычный Linux с systemd
        sudo systemctl start docker
    fi
    sleep 3
    ok "Docker data-root → ${DOCKER_DATA_PATH}"
fi

# ── 3. Секреты ────────────────────────────────────────────────────────────────
header "Шаг 3 / 10 — Генерация секретов"

mkdir -p "${ATMAN_DIR}"
chmod 700 "${ATMAN_DIR}"

if [[ ! -f "${SECRETS_FILE}" ]]; then
    POSTGRES_PASSWORD=$(openssl rand -base64 32 | tr -d '/+=' | head -c 32)
    QDRANT_API_KEY=$(openssl rand -base64 32 | tr -d '/+=' | head -c 32)

    cat > "${SECRETS_FILE}" << EOF
# Atman secrets — не коммитить в git!
# Создан: $(date -u +"%Y-%m-%dT%H:%M:%SZ")

POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
POSTGRES_USER=${POSTGRES_USER}
POSTGRES_DB=${POSTGRES_DB}
POSTGRES_HOST=localhost
POSTGRES_PORT=${POSTGRES_PORT}
DATABASE_URL=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:${POSTGRES_PORT}/${POSTGRES_DB}

QDRANT_URL=http://localhost:${QDRANT_PORT}
QDRANT_API_KEY=${QDRANT_API_KEY}

OLLAMA_URL=http://localhost:11434
ATMAN_OLLAMA_MODEL=${OLLAMA_LLM_MODEL}
ATMAN_EMBED_MODEL=${OLLAMA_EMBED_MODEL}
EMBEDDING_MODEL=${OLLAMA_EMBED_MODEL}
OLLAMA_EMBED_MODEL=${OLLAMA_EMBED_MODEL}
OLLAMA_KEEP_ALIVE=5m
OLLAMA_FLASH_ATTENTION=1

NVME_PATH=${NVME_PATH}
OLLAMA_MODELS_PATH=${OLLAMA_MODELS_PATH}
EOF
    chmod 600 "${SECRETS_FILE}"
    ok "Секреты сгенерированы → ${SECRETS_FILE}"
else
    warn "Секреты уже существуют — использую существующие"
fi

source "${SECRETS_FILE}"

# .env в проекте
if [[ -f "pyproject.toml" ]]; then
    cp "${SECRETS_FILE}" "./.env"
    chmod 600 "./.env"
    ok ".env создан в $(pwd)"
fi

# ── 4. Ollama ─────────────────────────────────────────────────────────────────
header "Шаг 4 / 10 — Ollama"

if ! command -v ollama &>/dev/null; then
    log "Устанавливаю Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh > /dev/null 2>&1
    ok "Ollama установлена"
else
    OLLAMA_VER=$(ollama --version 2>/dev/null | awk '{print $2}' || echo "?")
    ok "Ollama ${OLLAMA_VER} уже установлена"
fi

# Настройка systemd override для Ollama
log "Настраиваю Ollama (Flash Attention, NVMe модели, GPU)..."
sudo mkdir -p /etc/systemd/system/ollama.service.d/
sudo tee /etc/systemd/system/ollama.service.d/override.conf > /dev/null << EOF
[Service]
Environment="OLLAMA_MODELS=${OLLAMA_MODELS_PATH}"
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_KEEP_ALIVE=5m"
Environment="OLLAMA_NUM_PARALLEL=1"
Environment="OLLAMA_MAX_LOADED_MODELS=2"
Environment="CUDA_VISIBLE_DEVICES=0"
EOF

if grep -qi microsoft /proc/version 2>/dev/null; then
    # WSL2 - не используем systemd
    true
else
    sudo systemctl daemon-reload
fi

# Запуск Ollama
if grep -qi microsoft /proc/version 2>/dev/null; then
    # WSL2 - запускаем напрямую
    pkill ollama 2>/dev/null || true
    sleep 1
    OLLAMA_MODELS="${OLLAMA_MODELS_PATH}" \
    OLLAMA_FLASH_ATTENTION=1 \
    OLLAMA_KEEP_ALIVE=5m \
    nohup ollama serve > "${ATMAN_DIR}/ollama.log" 2>&1 &
    echo $! > "${ATMAN_DIR}/ollama.pid"
else
    # Обычный Linux с systemd
    if sudo systemctl is-active --quiet ollama 2>/dev/null; then
        sudo systemctl restart ollama
    else
        sudo systemctl enable --now ollama 2>/dev/null || {
            # Если systemd не работает — запускаем напрямую
            pkill ollama 2>/dev/null || true
            sleep 1
            OLLAMA_MODELS="${OLLAMA_MODELS_PATH}" \
            OLLAMA_FLASH_ATTENTION=1 \
            OLLAMA_KEEP_ALIVE=5m \
            nohup ollama serve > "${ATMAN_DIR}/ollama.log" 2>&1 &
            echo $! > "${ATMAN_DIR}/ollama.pid"
        }
    fi
fi

# Ждём Ollama
log "Жду запуска Ollama..."
RETRIES=30
until curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; do
    RETRIES=$((RETRIES - 1))
    [[ $RETRIES -eq 0 ]] && error "Ollama не запустилась"
    sleep 2
done
ok "Ollama запущена"

# Проверка GPU
GPU_INFO=$(OLLAMA_DEBUG=1 ollama run --nowordwrap qwen3:1.7b "hi" 2>&1 | grep "inference compute" | head -1 || true)
if echo "${GPU_INFO}" | grep -qi "cuda\|gpu"; then
    ok "GPU определена: CUDA активна"
elif echo "${GPU_INFO}" | grep -qi "cpu"; then
    warn "GPU не определена — Ollama работает на CPU"
    warn "RTX 5070 Ti / Blackwell: обновите Ollama или попробуйте OLLAMA_VULKAN=1"
    warn "Продолжаю установку — можно исправить позже"
else
    warn "Статус GPU неизвестен — проверьте вручную: ollama run ${OLLAMA_LLM_MODEL}"
fi

# ── 5. Скачиваем модели ───────────────────────────────────────────────────────
header "Шаг 5 / 10 — Загрузка моделей"

info "Embedding модель: ${OLLAMA_EMBED_MODEL} (~1 GB)"
ollama pull "${OLLAMA_EMBED_MODEL}"
ok "${OLLAMA_EMBED_MODEL} готова"

info "LLM: ${OLLAMA_LLM_MODEL} (~9 GB) — займёт время..."
ollama pull "${OLLAMA_LLM_MODEL}"
ok "${OLLAMA_LLM_MODEL} готова"

# Показываем что скачано
echo ""
ollama list
echo ""

# ── 6. PostgreSQL + pgvector ──────────────────────────────────────────────────
header "Шаг 6 / 10 — PostgreSQL 16 + pgvector"

PG_VOLUME="atman-postgres-data"
PG_CONTAINER="atman-postgres"

if ${DOCKER_CMD} ps -a --format '{{.Names}}' | grep -q "^${PG_CONTAINER}$"; then
    warn "Контейнер ${PG_CONTAINER} уже существует"
    ${DOCKER_CMD} start "${PG_CONTAINER}" > /dev/null 2>&1 || true
else
    log "Запускаю PostgreSQL..."
    ${DOCKER_CMD} run -d \
        --name "${PG_CONTAINER}" \
        --restart unless-stopped \
        -e POSTGRES_USER="${POSTGRES_USER}" \
        -e POSTGRES_PASSWORD="${POSTGRES_PASSWORD}" \
        -e POSTGRES_DB="${POSTGRES_DB}" \
        -e POSTGRES_INITDB_ARGS="--encoding=UTF-8 --lc-collate=C --lc-ctype=C" \
        -p "127.0.0.1:${POSTGRES_PORT}:5432" \
        -v "${PG_VOLUME}:/var/lib/postgresql/data" \
        -v "${PG_BACKUP_PATH}:/backups" \
        "pgvector/pgvector:pg${POSTGRES_VERSION}" \
        > /dev/null
    ok "Контейнер создан"
fi

log "Жду готовности PostgreSQL..."
RETRIES=30
until ${DOCKER_CMD} exec "${PG_CONTAINER}" \
    pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" > /dev/null 2>&1; do
    RETRIES=$((RETRIES - 1))
    [[ $RETRIES -eq 0 ]] && error "PostgreSQL не запустился"
    sleep 1
done
ok "PostgreSQL готов"

# ── 7. Схема БД ───────────────────────────────────────────────────────────────
header "Шаг 7 / 10 — Создание схемы БД"

log "Применяю схему..."

${DOCKER_CMD} exec -i "${PG_CONTAINER}" \
    psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" << 'SQL'

-- ═══════════════════════════════════════════════
-- EXTENSIONS
-- ═══════════════════════════════════════════════
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ═══════════════════════════════════════════════
-- REGISTRY
-- ═══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS agents (
    id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    config     JSONB NOT NULL DEFAULT '{}',
    active     BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS agent_snapshots (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id      UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    snapshot_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    identity_hash TEXT,
    metrics       JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_agent_snapshots_agent
    ON agent_snapshots(agent_id, snapshot_at DESC);

-- ═══════════════════════════════════════════════
-- FACTUAL MEMORY
-- ═══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS facts (
    id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id   UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    content    TEXT NOT NULL,
    source     TEXT NOT NULL,
    tags       TEXT[] NOT NULL DEFAULT '{}',
    embedding  halfvec(1024),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata   JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_facts_agent     ON facts(agent_id);
CREATE INDEX IF NOT EXISTS idx_facts_tags      ON facts USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_facts_embedding ON facts USING hnsw(embedding halfvec_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_facts_fts       ON facts USING GIN(to_tsvector('russian', content));

ALTER TABLE facts ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS facts_isolation ON facts;
CREATE POLICY facts_isolation ON facts
    USING (agent_id = NULLIF(current_setting('atman.current_agent', TRUE), '')::UUID);

CREATE TABLE IF NOT EXISTS fact_relations (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id       UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    source_fact_id UUID NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    target_fact_id UUID NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    relation_type  TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT no_self_relation CHECK (source_fact_id != target_fact_id)
);
CREATE INDEX IF NOT EXISTS idx_fact_rel_agent  ON fact_relations(agent_id);
CREATE INDEX IF NOT EXISTS idx_fact_rel_source ON fact_relations(source_fact_id);
CREATE INDEX IF NOT EXISTS idx_fact_rel_target ON fact_relations(target_fact_id);

ALTER TABLE fact_relations ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS fact_relations_isolation ON fact_relations;
CREATE POLICY fact_relations_isolation ON fact_relations
    USING (agent_id = NULLIF(current_setting('atman.current_agent', TRUE), '')::UUID);

CREATE TABLE IF NOT EXISTS fact_sharing (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    from_agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    to_agent_id   UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    fact_id       UUID NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    active        BOOLEAN NOT NULL DEFAULT FALSE,
    shared_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT no_self_sharing CHECK (from_agent_id != to_agent_id)
);

-- ═══════════════════════════════════════════════
-- SESSIONS
-- ═══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS sessions (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id             UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    started_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at             TIMESTAMPTZ,
    status               TEXT NOT NULL DEFAULT 'active'
                         CHECK (status IN ('active','completed','interrupted')),
    identity_snapshot_id UUID
);
CREATE INDEX IF NOT EXISTS idx_sessions_agent ON sessions(agent_id, started_at DESC);

ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS sessions_isolation ON sessions;
CREATE POLICY sessions_isolation ON sessions
    USING (agent_id = NULLIF(current_setting('atman.current_agent', TRUE), '')::UUID);

-- ═══════════════════════════════════════════════
-- EXPERIENCE STORE
-- ═══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS experiences (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id            UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    session_id          UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    importance          FLOAT NOT NULL DEFAULT 0.5 CHECK (importance BETWEEN 0 AND 1),
    salience            FLOAT NOT NULL DEFAULT 1.0 CHECK (salience BETWEEN 0 AND 1),
    last_accessed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    access_count        INT NOT NULL DEFAULT 0,
    incomplete_coloring BOOLEAN NOT NULL DEFAULT FALSE,
    overall_tone        FLOAT CHECK (overall_tone BETWEEN -1 AND 1),
    key_insight         TEXT
);
CREATE INDEX IF NOT EXISTS idx_experiences_agent   ON experiences(agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_experiences_session ON experiences(session_id);

ALTER TABLE experiences ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS experiences_isolation ON experiences;
CREATE POLICY experiences_isolation ON experiences
    USING (agent_id = NULLIF(current_setting('atman.current_agent', TRUE), '')::UUID);

CREATE TABLE IF NOT EXISTS key_moments (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    experience_id        UUID NOT NULL REFERENCES experiences(id) ON DELETE CASCADE,
    agent_id             UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    what_happened        TEXT NOT NULL,
    embedding            halfvec(1024),
    emotional_valence    FLOAT NOT NULL CHECK (emotional_valence BETWEEN -1 AND 1),
    emotional_intensity  FLOAT NOT NULL CHECK (emotional_intensity BETWEEN 0 AND 1),
    depth                TEXT NOT NULL CHECK (depth IN ('surface','meaningful','profound')),
    why_it_matters       TEXT,
    values_touched       TEXT[] NOT NULL DEFAULT '{}',
    principles_confirmed TEXT[] NOT NULL DEFAULT '{}',
    principles_questioned TEXT[] NOT NULL DEFAULT '{}',
    what_changed         TEXT,
    recorded_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_km_experience ON key_moments(experience_id);
CREATE INDEX IF NOT EXISTS idx_km_agent      ON key_moments(agent_id);
CREATE INDEX IF NOT EXISTS idx_km_embedding  ON key_moments USING hnsw(embedding halfvec_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_km_values     ON key_moments USING GIN(values_touched);
CREATE INDEX IF NOT EXISTS idx_km_depth      ON key_moments(agent_id, depth);

ALTER TABLE key_moments ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS key_moments_isolation ON key_moments;
CREATE POLICY key_moments_isolation ON key_moments
    USING (agent_id = NULLIF(current_setting('atman.current_agent', TRUE), '')::UUID);

CREATE OR REPLACE FUNCTION prevent_key_moment_modification()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'key_moments are immutable. Original experience cannot be modified.';
END;
$$;
DROP TRIGGER IF EXISTS key_moments_immutable ON key_moments;
CREATE TRIGGER key_moments_immutable
    BEFORE UPDATE OR DELETE ON key_moments
    FOR EACH ROW EXECUTE FUNCTION prevent_key_moment_modification();

CREATE TABLE IF NOT EXISTS reframing_notes (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    experience_id   UUID NOT NULL REFERENCES experiences(id) ON DELETE CASCADE,
    agent_id        UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    reflection      TEXT NOT NULL,
    reflection_type TEXT NOT NULL
                    CHECK (reflection_type IN ('growth','reinterpretation','closure','insight')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_reframing_experience ON reframing_notes(experience_id);

ALTER TABLE reframing_notes ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS reframing_isolation ON reframing_notes;
CREATE POLICY reframing_isolation ON reframing_notes
    USING (agent_id = NULLIF(current_setting('atman.current_agent', TRUE), '')::UUID);

CREATE OR REPLACE FUNCTION prevent_reframing_modification()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'reframing_notes are append-only.';
END;
$$;
DROP TRIGGER IF EXISTS reframing_notes_append_only ON reframing_notes;
CREATE TRIGGER reframing_notes_append_only
    BEFORE UPDATE OR DELETE ON reframing_notes
    FOR EACH ROW EXECUTE FUNCTION prevent_reframing_modification();

-- ═══════════════════════════════════════════════
-- IDENTITY STORE
-- ═══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS identity (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id           UUID NOT NULL UNIQUE REFERENCES agents(id) ON DELETE CASCADE,
    self_description   TEXT NOT NULL DEFAULT '',
    core_values        JSONB NOT NULL DEFAULT '[]',
    habits             JSONB NOT NULL DEFAULT '[]',
    principles         JSONB NOT NULL DEFAULT '[]',
    goals              JSONB NOT NULL DEFAULT '[]',
    open_questions     JSONB NOT NULL DEFAULT '[]',
    emotional_baseline FLOAT NOT NULL DEFAULT 0.0
                       CHECK (emotional_baseline BETWEEN -1 AND 1),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE identity ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS identity_isolation ON identity;
CREATE POLICY identity_isolation ON identity
    USING (agent_id = NULLIF(current_setting('atman.current_agent', TRUE), '')::UUID);

CREATE TABLE IF NOT EXISTS identity_snapshots (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id    UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    snapshot_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    description TEXT,
    state       JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_id_snapshots_agent
    ON identity_snapshots(agent_id, snapshot_at DESC);

ALTER TABLE identity_snapshots ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS identity_snapshots_isolation ON identity_snapshots;
CREATE POLICY identity_snapshots_isolation ON identity_snapshots
    USING (agent_id = NULLIF(current_setting('atman.current_agent', TRUE), '')::UUID);

CREATE OR REPLACE FUNCTION prevent_snapshot_modification()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'identity_snapshots are immutable.';
END;
$$;
DROP TRIGGER IF EXISTS identity_snapshots_immutable ON identity_snapshots;
CREATE TRIGGER identity_snapshots_immutable
    BEFORE UPDATE OR DELETE ON identity_snapshots
    FOR EACH ROW EXECUTE FUNCTION prevent_snapshot_modification();

CREATE TABLE IF NOT EXISTS narrative (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id     UUID NOT NULL UNIQUE REFERENCES agents(id) ON DELETE CASCADE,
    core_layer   TEXT NOT NULL DEFAULT '',
    recent_layer TEXT NOT NULL DEFAULT '',
    threads      JSONB NOT NULL DEFAULT '[]',
    eigenstate   JSONB NOT NULL DEFAULT '{}',
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE narrative ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS narrative_isolation ON narrative;
CREATE POLICY narrative_isolation ON narrative
    USING (agent_id = NULLIF(current_setting('atman.current_agent', TRUE), '')::UUID);

-- ═══════════════════════════════════════════════
-- OBSERVABILITY
-- ═══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS memory_access_log (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id        UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    session_id      UUID REFERENCES sessions(id) ON DELETE SET NULL,
    accessed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    access_type     TEXT NOT NULL CHECK (access_type IN (
        'fact_search','fact_get','fact_add',
        'experience_search','experience_get','experience_add',
        'identity_read','identity_update',
        'relation_traverse','narrative_read'
    )),
    query_text      TEXT,
    query_embedding halfvec(1024),
    filters         JSONB NOT NULL DEFAULT '{}',
    result_count    INT NOT NULL DEFAULT 0,
    top_score       FLOAT,
    avg_score       FLOAT,
    result_ids      UUID[] NOT NULL DEFAULT '{}',
    caller          TEXT NOT NULL DEFAULT 'unknown',
    latency_ms      INT
);
CREATE INDEX IF NOT EXISTS idx_access_log_agent
    ON memory_access_log(agent_id, accessed_at DESC);
CREATE INDEX IF NOT EXISTS idx_access_log_type
    ON memory_access_log(agent_id, access_type);

CREATE TABLE IF NOT EXISTS quality_alerts (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id    UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    alerted_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    alert_type  TEXT NOT NULL,
    severity    TEXT NOT NULL CHECK (severity IN ('info','warning','critical')),
    details     JSONB NOT NULL DEFAULT '{}',
    resolved_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_alerts_agent
    ON quality_alerts(agent_id, alerted_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_active
    ON quality_alerts(agent_id) WHERE resolved_at IS NULL;

CREATE MATERIALIZED VIEW IF NOT EXISTS memory_quality_metrics AS
SELECT
    a.id                                                     AS agent_id,
    NOW()                                                    AS computed_at,
    COUNT(DISTINCT f.id)                                     AS facts_total,
    COUNT(DISTINCT f.id) FILTER (WHERE f.tags = '{}')       AS facts_without_tags,
    COUNT(DISTINCT f.id) FILTER (WHERE f.embedding IS NULL) AS facts_without_embedding,
    COUNT(DISTINCT e.id)                                     AS experiences_total,
    ROUND(AVG(CASE WHEN e.incomplete_coloring THEN 1.0 ELSE 0.0 END)::NUMERIC, 3)
                                                             AS incomplete_coloring_rate,
    ROUND(AVG(e.salience)::NUMERIC, 3)                      AS avg_salience,
    COUNT(DISTINCT e.id) FILTER (WHERE e.access_count = 0)  AS experiences_never_accessed,
    jsonb_array_length(i.core_values)                        AS values_count,
    jsonb_array_length(i.principles)                         AS principles_count,
    jsonb_array_length(i.open_questions)                     AS open_questions_count,
    i.emotional_baseline                                     AS emotional_baseline,
    n.updated_at                                             AS narrative_last_updated,
    EXTRACT(DAY FROM NOW() - n.updated_at)::INT             AS days_since_narrative_update,
    COUNT(DISTINCT s.id) FILTER (
        WHERE s.started_at > NOW() - INTERVAL '30 days'
    )                                                        AS sessions_last_30_days
FROM agents a
LEFT JOIN facts f       ON f.agent_id = a.id
LEFT JOIN experiences e ON e.agent_id = a.id
LEFT JOIN identity i    ON i.agent_id = a.id
LEFT JOIN narrative n   ON n.agent_id = a.id
LEFT JOIN sessions s    ON s.agent_id = a.id
WHERE a.active = TRUE
GROUP BY a.id, i.core_values, i.principles, i.open_questions,
         i.emotional_baseline, n.updated_at
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS idx_quality_metrics_agent
    ON memory_quality_metrics(agent_id);

CREATE OR REPLACE FUNCTION refresh_quality_metrics()
RETURNS VOID LANGUAGE SQL AS $$
    REFRESH MATERIALIZED VIEW CONCURRENTLY memory_quality_metrics;
$$;

CREATE OR REPLACE FUNCTION check_quality_alerts()
RETURNS INT LANGUAGE plpgsql AS $$
DECLARE
    m   RECORD;
    cnt INT := 0;
BEGIN
    FOR m IN SELECT * FROM memory_quality_metrics LOOP
        IF m.facts_without_tags::FLOAT / GREATEST(m.facts_total, 1) > 0.5 THEN
            INSERT INTO quality_alerts(agent_id,alert_type,severity,details) VALUES
            (m.agent_id,'fact_quality_low','warning',
             jsonb_build_object('without_tags',m.facts_without_tags,'total',m.facts_total));
            cnt := cnt + 1;
        END IF;
        IF m.incomplete_coloring_rate > 0.3 THEN
            INSERT INTO quality_alerts(agent_id,alert_type,severity,details) VALUES
            (m.agent_id,'experience_quality_low','warning',
             jsonb_build_object('rate',m.incomplete_coloring_rate));
            cnt := cnt + 1;
        END IF;
        IF m.days_since_narrative_update > 10 THEN
            INSERT INTO quality_alerts(agent_id,alert_type,severity,details) VALUES
            (m.agent_id,'narrative_stale','info',
             jsonb_build_object('days',m.days_since_narrative_update));
            cnt := cnt + 1;
        END IF;
        IF m.emotional_baseline < -0.5 THEN
            INSERT INTO quality_alerts(agent_id,alert_type,severity,details) VALUES
            (m.agent_id,'agent_distress','critical',
             jsonb_build_object('emotional_baseline',m.emotional_baseline));
            cnt := cnt + 1;
        END IF;
        IF m.open_questions_count > 20 THEN
            INSERT INTO quality_alerts(agent_id,alert_type,severity,details) VALUES
            (m.agent_id,'identity_fragmented','info',
             jsonb_build_object('open_questions',m.open_questions_count));
            cnt := cnt + 1;
        END IF;
    END LOOP;
    RETURN cnt;
END;
$$;

-- ── Application Role ──────────────────────────────────────────────────────────
DO \$\$ BEGIN
    CREATE ROLE atman_app LOGIN NOSUPERUSER NOINHERIT NOCREATEDB NOCREATEROLE NOREPLICATION;
EXCEPTION WHEN duplicate_object THEN NULL;
END \$\$;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.facts              TO atman_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.fact_relations     TO atman_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.sessions           TO atman_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.experiences        TO atman_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.key_moments        TO atman_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.reframing_notes    TO atman_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.reflections        TO atman_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.identity           TO atman_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.identity_snapshots TO atman_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.narrative          TO atman_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.memory_access_log  TO atman_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.quality_alerts     TO atman_app;
GRANT SELECT, INSERT               ON public.agents               TO atman_app;
GRANT SELECT, INSERT               ON public.agent_snapshots      TO atman_app;

SQL

TABLE_COUNT=$(${DOCKER_CMD} exec "${PG_CONTAINER}" \
    psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
    -t -A -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';")
ok "Схема создана: ${TABLE_COUNT} объектов"

# ── 8. Qdrant ─────────────────────────────────────────────────────────────────
header "Шаг 8 / 10 — Qdrant"

QDRANT_CONTAINER="atman-qdrant"

if ${DOCKER_CMD} ps -a --format '{{.Names}}' | grep -q "^${QDRANT_CONTAINER}$"; then
    warn "Контейнер ${QDRANT_CONTAINER} уже существует"
    ${DOCKER_CMD} start "${QDRANT_CONTAINER}" > /dev/null 2>&1 || true
else
    log "Запускаю Qdrant..."
    ${DOCKER_CMD} run -d \
        --name "${QDRANT_CONTAINER}" \
        --restart unless-stopped \
        -p "127.0.0.1:${QDRANT_PORT}:6333" \
        -p "127.0.0.1:6334:6334" \
        -v atman-qdrant-data:/qdrant/storage \
        -e QDRANT__SERVICE__API_KEY="${QDRANT_API_KEY}" \
        "qdrant/qdrant:${QDRANT_VERSION}" \
        > /dev/null
fi

log "Жду готовности Qdrant..."
RETRIES=30
until curl -sf "http://localhost:${QDRANT_PORT}/" | grep -q "qdrant"; do
    RETRIES=$((RETRIES - 1))
    [[ $RETRIES -eq 0 ]] && error "Qdrant не запустился"
    sleep 1
done
ok "Qdrant готов"

# Создаём коллекции
for COLLECTION in atman_facts atman_experiences; do
    STATUS=$(curl -sf "http://localhost:${QDRANT_PORT}/collections/${COLLECTION}" \
        -H "api-key: ${QDRANT_API_KEY}" 2>/dev/null | python3 -c \
        "import sys,json; d=json.load(sys.stdin); print(d['result']['status'])" 2>/dev/null || echo "")

    if [[ "${STATUS}" == "green" ]]; then
        warn "Коллекция ${COLLECTION} уже существует"
    else
        curl -sf -X PUT "http://localhost:${QDRANT_PORT}/collections/${COLLECTION}" \
            -H "api-key: ${QDRANT_API_KEY}" \
            -H "Content-Type: application/json" \
            -d '{"vectors":{"size":1024,"distance":"Cosine"},"optimizers_config":{"default_segment_number":2}}' \
            > /dev/null
        ok "Коллекция ${COLLECTION} создана"
    fi
done

# ── 9. Docker Compose ─────────────────────────────────────────────────────────
header "Шаг 9 / 10 — Docker Compose"

if [[ -f "pyproject.toml" ]]; then
    COMPOSE_DIR="$(pwd)"
else
    COMPOSE_DIR="${ATMAN_DIR}"
fi

cat > "${COMPOSE_DIR}/docker-compose.yml" << EOF
# Atman infrastructure — запуск: docker compose up -d
# Остановка: docker compose stop
# Удаление: docker compose down

version: '3.9'

services:
  postgres:
    image: pgvector/pgvector:pg${POSTGRES_VERSION}
    container_name: atman-postgres
    restart: unless-stopped
    environment:
      POSTGRES_USER: \${POSTGRES_USER}
      POSTGRES_PASSWORD: \${POSTGRES_PASSWORD}
      POSTGRES_DB: \${POSTGRES_DB}
    ports:
      - "127.0.0.1:${POSTGRES_PORT}:5432"
    volumes:
      - atman-postgres-data:/var/lib/postgresql/data
      - ${PG_BACKUP_PATH}:/backups
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U \${POSTGRES_USER}"]
      interval: 10s
      timeout: 5s
      retries: 5

  qdrant:
    image: qdrant/qdrant:${QDRANT_VERSION}
    container_name: atman-qdrant
    restart: unless-stopped
    environment:
      QDRANT__SERVICE__API_KEY: \${QDRANT_API_KEY}
    ports:
      - "127.0.0.1:6333:6333"
      - "127.0.0.1:6334:6334"
    volumes:
      - atman-qdrant-data:/qdrant/storage
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6333/health"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  atman-postgres-data:
  atman-qdrant-data:
EOF

ok "docker-compose.yml создан → ${COMPOSE_DIR}"

# ── 10. Python зависимости ────────────────────────────────────────────────────
header "Шаг 10 / 10 — Python окружение"

if [[ -f "pyproject.toml" ]]; then
    log "Создаю venv (Python 3.12)..."
    uv venv --python 3.12 > /dev/null 2>&1 || uv venv > /dev/null 2>&1
    log "Устанавливаю зависимости..."
    uv pip install -e ".[dev,e2e]" \
        asyncpg \
        "psycopg2-binary" \
        "qdrant-client[fastembed]" \
        pgvector \
        sqlalchemy \
        alembic \
        httpx \
        --quiet
    ok "Python зависимости установлены"
else
    warn "pyproject.toml не найден — пропускаю Python зависимости"
    info "Запусти скрипт из корня репозитория Atman"
fi

# ── Smoke тест ────────────────────────────────────────────────────────────────
header "Smoke test"

# PostgreSQL
PG_TABLES=$(${DOCKER_CMD} exec "${PG_CONTAINER}" \
    psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
    -t -A -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null)
ok "PostgreSQL: ${PG_TABLES} таблиц/объектов"

# pgvector
PG_VEC=$(${DOCKER_CMD} exec "${PG_CONTAINER}" \
    psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
    -t -A -c "SELECT extversion FROM pg_extension WHERE extname='vector';" 2>/dev/null)
ok "pgvector: v${PG_VEC}"

# Qdrant
for COL in atman_facts atman_experiences; do
    COL_STATUS=$(curl -sf "http://localhost:${QDRANT_PORT}/collections/${COL}" \
        -H "api-key: ${QDRANT_API_KEY}" 2>/dev/null \
        | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['status'])" 2>/dev/null)
    ok "Qdrant [${COL}]: ${COL_STATUS}"
done

# Ollama embedding
EMBED_DIM=$(curl -sf http://localhost:11434/api/embeddings \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"${OLLAMA_EMBED_MODEL}\",\"prompt\":\"тест системы\"}" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d['embedding']))" 2>/dev/null)
ok "Embedding: ${EMBED_DIM} dims (ожидается 1024)"

# Ollama модели
LLM_PRESENT=$(ollama list 2>/dev/null | grep -c "qwen3" || echo "0")
ok "Ollama: ${LLM_PRESENT} qwen3 моделей загружено"

# ── Итог ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}══════════════════════════════════════════════${NC}"
echo -e "${BOLD}${GREEN}  Atman Memory Stack успешно развёрнут!       ${NC}"
echo -e "${BOLD}${GREEN}══════════════════════════════════════════════${NC}"
echo ""
echo -e "${BOLD}Сервисы:${NC}"
echo -e "  ${GREEN}●${NC} PostgreSQL + pgvector → localhost:${POSTGRES_PORT}"
echo -e "  ${GREEN}●${NC} Qdrant               → localhost:${QDRANT_PORT}"
echo -e "  ${GREEN}●${NC} Ollama               → localhost:11434"
echo ""
echo -e "${BOLD}Модели:${NC}"
echo -e "  ${GREEN}●${NC} LLM:   ${OLLAMA_LLM_MODEL}"
echo -e "  ${GREEN}●${NC} Embed: ${OLLAMA_EMBED_MODEL}"
echo ""
echo -e "${BOLD}Данные:${NC}"
echo -e "  ${GREEN}●${NC} Секреты:    ${SECRETS_FILE}"
echo -e "  ${GREEN}●${NC} .env:       $(pwd)/.env"
echo -e "  ${GREEN}●${NC} Compose:    ${COMPOSE_DIR}/docker-compose.yml"
echo -e "  ${GREEN}●${NC} Модели:     ${OLLAMA_MODELS_PATH}"
echo -e "  ${GREEN}●${NC} Бэкапы:    ${PG_BACKUP_PATH}"
echo ""
# ── Настройка автозапуска ───────────────────────────────────────────────────
AUTOSTART_MARKER="# Atman Stack Autostart"
if ! grep -q "${AUTOSTART_MARKER}" "${HOME}/.bashrc" 2>/dev/null; then
    echo "" >> "${HOME}/.bashrc"
    echo "${AUTOSTART_MARKER}" >> "${HOME}/.bashrc"
    echo "if [ -f /mnt/nvme/atman/atman/atman-start.sh ]; then" >> "${HOME}/.bashrc"
    echo "    /mnt/nvme/atman/atman/atman-start.sh >/dev/null 2>&1 &" >> "${HOME}/.bashrc"
    echo "fi" >> "${HOME}/.bashrc"
    ok "Автозапуск добавлен в ~/.bashrc"
fi

echo ""
echo -e "${BOLD}Управление:${NC}"
echo -e "  Ручной запуск: ${CYAN}/mnt/nvme/atman/atman/atman-start.sh${NC}"
echo -e "  Остановка:     ${CYAN}docker compose stop${NC}"
echo -e "  Логи:          ${CYAN}docker logs atman-postgres${NC}"
echo -e "  Статус:        ${CYAN}docker ps${NC}"
echo ""
echo -e "${BOLD}Автозапуск:${NC} ${GREEN}настроен${NC} (запускается при входе в WSL)"
echo ""
echo -e "${BOLD}Следующий шаг:${NC} реализовать QdrantFactualAdapter (issue #147)"
echo ""
echo -e "  Завершено: $(date '+%Y-%m-%d %H:%M:%S')"
