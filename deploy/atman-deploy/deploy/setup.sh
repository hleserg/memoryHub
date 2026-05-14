#!/usr/bin/env bash
# =============================================================================
# Atman — полный деплой
#
# Использование:
#   bash setup.sh                  # авто-определение всего
#   bash setup.sh --data-path /mnt/nvme/atman   # указать путь для данных
#   bash setup.sh --skip-models    # не скачивать модели (позже вручную)
#   bash setup.sh --help
#
# Требования: Ubuntu 22.04+, sudo, curl
# Опционально: uv (установится автоматически)
# =============================================================================

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ── Цвета ────────────────────────────────────────────────────────────────────
R='\033[0;31m' G='\033[0;32m' Y='\033[1;33m'
B='\033[0;34m' C='\033[0;36m' W='\033[1m' N='\033[0m'

log()    { echo -e "${C}[atman]${N} $*"; }
ok()     { echo -e "${G}[✓]${N} $*"; }
warn()   { echo -e "${Y}[!]${N} $*"; }
err()    { echo -e "${R}[✗]${N} $*"; exit 1; }
header() { echo -e "\n${W}${B}━━━ $* ━━━${N}"; }

# ── Аргументы ────────────────────────────────────────────────────────────────
DATA_PATH=""
SKIP_MODELS=false
SKIP_PYTHON=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --data-path)   DATA_PATH="$2"; shift 2 ;;
        --skip-models) SKIP_MODELS=true; shift ;;
        --skip-python) SKIP_PYTHON=true; shift ;;
        --help|-h)
            echo "Использование: bash setup.sh [опции]"
            echo "  --data-path PATH   путь для данных (модели, БД, бэкапы)"
            echo "  --skip-models      не скачивать LLM модели"
            echo "  --skip-python      не устанавливать Python зависимости"
            exit 0 ;;
        *) warn "Неизвестный аргумент: $1"; shift ;;
    esac
done

# ── Загрузка конфига ─────────────────────────────────────────────────────────
CONFIG_FILE="${SCRIPT_DIR}/config.env"
[[ -f "${CONFIG_FILE}" ]] || err "Не найден ${CONFIG_FILE}"
# shellcheck disable=SC1090
source "${CONFIG_FILE}"

# ── Определение пути для данных ───────────────────────────────────────────────
if [[ -z "${DATA_PATH}" ]]; then
    # Ищем NVMe или большой диск
    NVME=$(lsblk -d -o NAME,TYPE,ROTA 2>/dev/null | awk '$2=="disk" && $3=="0" {print $1}' | head -1)
    if [[ -n "${NVME}" ]]; then
        # Ищем смонтированный раздел
        NVME_MNT=$(lsblk -o NAME,MOUNTPOINT 2>/dev/null \
            | grep "${NVME}" | awk '$2!="" && $2!="/" {print $2}' | head -1)
        if [[ -n "${NVME_MNT}" ]]; then
            DATA_PATH="${NVME_MNT}/atman"
        fi
    fi
    # Фоллбек на домашнюю директорию
    DATA_PATH="${DATA_PATH:-${HOME}/.atman/data}"
fi

SECRETS_FILE="${HOME}/.atman/.secrets"
OLLAMA_MODELS_PATH="${DATA_PATH}/ollama/models"
PG_BACKUP_PATH="${DATA_PATH}/backups"

# ── Баннер ───────────────────────────────────────────────────────────────────
clear
echo -e "${W}"
echo "  ╔═══════════════════════════════════════╗"
echo "  ║         Atman — деплой                ║"
echo "  ╚═══════════════════════════════════════╝"
echo -e "${N}"
echo "  Данные:  ${DATA_PATH}"
echo "  Проект:  ${PROJECT_ROOT}"
echo "  Старт:   $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# ── Шаг 1: Базовые утилиты ───────────────────────────────────────────────────
header "1 / 9 — Окружение"

sudo -n true 2>/dev/null || sudo true

sudo apt-get update -qq
sudo apt-get install -y -qq curl wget openssl python3 git lsblk > /dev/null 2>&1
ok "Базовые утилиты"

# uv
if ! command -v uv &>/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="${HOME}/.local/bin:${PATH}"
    # shellcheck disable=SC2016
    echo 'export PATH="${HOME}/.local/bin:${PATH}"' >> ~/.bashrc
fi
ok "uv $(uv --version 2>/dev/null | awk '{print $2}')"

# Docker
if ! command -v docker &>/dev/null; then
    log "Устанавливаю Docker..."
    bash "${SCRIPT_DIR}/install-docker.sh"
fi
ok "Docker $(docker --version 2>/dev/null | awk '{print $3}' | tr -d ',')"

# Docker без sudo
if ! docker ps &>/dev/null; then
    sudo usermod -aG docker "${USER}"
    DOCKER="sudo docker"
else
    DOCKER="docker"
fi

if ! sudo systemctl is-active --quiet docker 2>/dev/null; then
    sudo systemctl enable --now docker
fi

# ── Шаг 2: Директории и секреты ─────────────────────────────────────────────
header "2 / 9 — Секреты"

mkdir -p "${HOME}/.atman" "${OLLAMA_MODELS_PATH}" "${PG_BACKUP_PATH}"
chmod 700 "${HOME}/.atman"

if [[ ! -f "${SECRETS_FILE}" ]]; then
    bash "${SCRIPT_DIR}/gen-secrets.sh" \
        "${SECRETS_FILE}" \
        "${POSTGRES_USER}" \
        "${POSTGRES_DB}" \
        "${POSTGRES_PORT}" \
        "${QDRANT_PORT}" \
        "${OLLAMA_LLM_MODEL}" \
        "${OLLAMA_EMBED_MODEL}"
    ok "Секреты сгенерированы → ${SECRETS_FILE}"
else
    warn "Секреты уже существуют"
fi

# shellcheck disable=SC1090
source "${SECRETS_FILE}"

# .env в проект
cp "${SECRETS_FILE}" "${PROJECT_ROOT}/.env"
chmod 600 "${PROJECT_ROOT}/.env"
ok ".env → ${PROJECT_ROOT}/.env"

# ── Шаг 3: Ollama ────────────────────────────────────────────────────────────
header "3 / 9 — Ollama"

if ! command -v ollama &>/dev/null; then
    curl -fsSL https://ollama.com/install.sh | sh > /dev/null 2>&1
fi
ok "Ollama $(ollama --version 2>/dev/null | awk '{print $2}')"

# Systemd override
sudo mkdir -p /etc/systemd/system/ollama.service.d/
envsubst < "${SCRIPT_DIR}/ollama-override.conf.tpl" \
    | sudo tee /etc/systemd/system/ollama.service.d/override.conf > /dev/null
sudo systemctl daemon-reload

# Запуск
if sudo systemctl is-active --quiet ollama 2>/dev/null; then
    sudo systemctl restart ollama
else
    sudo systemctl enable --now ollama 2>/dev/null || {
        pkill ollama 2>/dev/null || true; sleep 1
        OLLAMA_MODELS="${OLLAMA_MODELS_PATH}" OLLAMA_FLASH_ATTENTION=1 \
            nohup ollama serve > "${HOME}/.atman/ollama.log" 2>&1 &
    }
fi

log "Жду Ollama..."
until curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; do sleep 2; done
ok "Ollama запущена"

# ── Шаг 4: Модели ────────────────────────────────────────────────────────────
header "4 / 9 — Модели Ollama"

if [[ "${SKIP_MODELS}" == "true" ]]; then
    warn "Пропускаю загрузку моделей (--skip-models)"
else
    log "Embedding: ${OLLAMA_EMBED_MODEL}"
    ollama pull "${OLLAMA_EMBED_MODEL}"
    ok "${OLLAMA_EMBED_MODEL}"

    log "LLM: ${OLLAMA_LLM_MODEL} (~9 GB)"
    ollama pull "${OLLAMA_LLM_MODEL}"
    ok "${OLLAMA_LLM_MODEL}"
fi

# ── Шаг 5: PostgreSQL ────────────────────────────────────────────────────────
header "5 / 9 — PostgreSQL + pgvector"

PG_CONTAINER="atman-postgres"

if ! ${DOCKER} ps -a --format '{{.Names}}' | grep -q "^${PG_CONTAINER}$"; then
    ${DOCKER} run -d \
        --name "${PG_CONTAINER}" \
        --restart unless-stopped \
        -e POSTGRES_USER="${POSTGRES_USER}" \
        -e POSTGRES_PASSWORD="${POSTGRES_PASSWORD}" \
        -e POSTGRES_DB="${POSTGRES_DB}" \
        -e POSTGRES_INITDB_ARGS="--encoding=UTF-8 --lc-collate=C --lc-ctype=C" \
        -p "127.0.0.1:${POSTGRES_PORT}:5432" \
        -v atman-postgres-data:/var/lib/postgresql/data \
        -v "${PG_BACKUP_PATH}:/backups" \
        "pgvector/pgvector:pg${POSTGRES_VERSION}" > /dev/null
else
    ${DOCKER} start "${PG_CONTAINER}" > /dev/null 2>&1 || true
fi

log "Жду PostgreSQL..."
until ${DOCKER} exec "${PG_CONTAINER}" pg_isready -U "${POSTGRES_USER}" > /dev/null 2>&1
do sleep 1; done
ok "PostgreSQL готов"

# ── Шаг 6: Схема БД ──────────────────────────────────────────────────────────
header "6 / 9 — Схема БД"

${DOCKER} exec -i "${PG_CONTAINER}" \
    psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
    < "${SCRIPT_DIR}/schema.sql"

# Установить пароль для роли приложения (создаётся schema.sql)
${DOCKER} exec "${PG_CONTAINER}" \
    psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
    -c "ALTER ROLE atman_app PASSWORD '${ATMAN_APP_PASSWORD}';" > /dev/null
ok "Пароль atman_app установлен"

COUNT=$(${DOCKER} exec "${PG_CONTAINER}" \
    psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
    -t -A -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';")
ok "Схема применена: ${COUNT} объектов"

# ── Шаг 7: Qdrant ────────────────────────────────────────────────────────────
header "7 / 9 — Qdrant"

QD_CONTAINER="atman-qdrant"

if ! ${DOCKER} ps -a --format '{{.Names}}' | grep -q "^${QD_CONTAINER}$"; then
    ${DOCKER} run -d \
        --name "${QD_CONTAINER}" \
        --restart unless-stopped \
        -p "127.0.0.1:${QDRANT_PORT}:6333" \
        -p "127.0.0.1:6334:6334" \
        -v atman-qdrant-data:/qdrant/storage \
        -e QDRANT__SERVICE__API_KEY="${QDRANT_API_KEY}" \
        "qdrant/qdrant:${QDRANT_VERSION}" > /dev/null
else
    ${DOCKER} start "${QD_CONTAINER}" > /dev/null 2>&1 || true
fi

log "Жду Qdrant..."
until curl -sf "http://localhost:${QDRANT_PORT}/health" > /dev/null 2>&1; do sleep 1; done
ok "Qdrant готов"

for COL in atman_facts atman_experiences; do
    STATUS=$(curl -sf "http://localhost:${QDRANT_PORT}/collections/${COL}" \
        -H "api-key: ${QDRANT_API_KEY}" 2>/dev/null \
        | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['status'])" 2>/dev/null \
        || echo "")
    if [[ "${STATUS}" != "green" ]]; then
        curl -sf -X PUT "http://localhost:${QDRANT_PORT}/collections/${COL}" \
            -H "api-key: ${QDRANT_API_KEY}" \
            -H "Content-Type: application/json" \
            -d "{\"vectors\":{\"size\":${VECTOR_DIM},\"distance\":\"Cosine\"},\"optimizers_config\":{\"default_segment_number\":2}}" \
            > /dev/null
        ok "Коллекция ${COL} создана"
    else
        warn "Коллекция ${COL} уже существует"
    fi
done

# ── Шаг 8: Docker Compose ────────────────────────────────────────────────────
header "8 / 9 — Docker Compose"

envsubst < "${SCRIPT_DIR}/docker-compose.yml.tpl" > "${PROJECT_ROOT}/docker-compose.yml"
ok "docker-compose.yml → ${PROJECT_ROOT}"

# ── Шаг 9: Python ────────────────────────────────────────────────────────────
header "9 / 9 — Python"

if [[ "${SKIP_PYTHON}" == "true" ]]; then
    warn "Пропускаю Python (--skip-python)"
elif [[ -f "${PROJECT_ROOT}/pyproject.toml" ]]; then
    cd "${PROJECT_ROOT}"
    uv venv --python 3.12 > /dev/null 2>&1 || uv venv > /dev/null 2>&1
    uv pip install -e ".[dev,e2e]" \
        asyncpg psycopg2-binary "qdrant-client[fastembed]" \
        pgvector sqlalchemy alembic httpx \
        --quiet
    ok "Python зависимости установлены"
fi

# ── Smoke test ────────────────────────────────────────────────────────────────
header "Smoke test"

bash "${SCRIPT_DIR}/smoke-test.sh" \
    "${POSTGRES_USER}" "${POSTGRES_DB}" "${QDRANT_PORT}" \
    "${QDRANT_API_KEY}" "${OLLAMA_EMBED_MODEL}" "${DOCKER}" "${VECTOR_DIM}"

# ── Итог ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${W}${G}══════════════════════════════════════════${N}"
echo -e "${W}${G}  Atman Memory Stack развёрнут!           ${N}"
echo -e "${W}${G}══════════════════════════════════════════${N}"
echo ""
echo -e "  PostgreSQL  → localhost:${POSTGRES_PORT}"
echo -e "  Qdrant      → localhost:${QDRANT_PORT}"
echo -e "  Ollama      → localhost:11434"
echo ""
echo -e "  Секреты:  ${SECRETS_FILE}"
echo -e "  .env:     ${PROJECT_ROOT}/.env"
echo -e "  Данные:   ${DATA_PATH}"
echo ""
echo -e "  Управление: ${C}docker compose up -d${N}"
echo -e "  Завершено:  $(date '+%Y-%m-%d %H:%M:%S')"
echo ""
