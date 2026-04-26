#!/usr/bin/env bash
# scripts/backup.sh
# memoryHub Disaster Recovery — backup script.
# Creates encrypted backup and uploads to cloud storage.
# See ARCHITECTURE.md §4.9 Disaster Recovery
#
# Usage:
#   ./scripts/backup.sh [--type incremental|daily|weekly|monthly]
#
# Scheduled via systemd timer or cron:
#   Incremental: every 6 hours  (0 */6 * * *)
#   Daily:       03:00          (0 3 * * *)
#   Weekly:      Sunday 04:00   (0 4 * * 0)
#   Monthly:     1st 05:00      (0 5 1 * *)
#
# Requirements:
#   - sqlite3
#   - openssl (for encryption)
#   - aws CLI or rclone (for cloud upload)
#   - ENV: MEMORYHUB_DR_ENCRYPTION_KEY, MEMORYHUB_DR_ACCESS_KEY, MEMORYHUB_DR_SECRET_KEY

set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────
BACKUP_TYPE="${BACKUP_TYPE:-incremental}"
DATA_DIR="${DATA_DIR:-./data}"
BACKUP_DIR="${DATA_DIR}/backups/${BACKUP_TYPE}"
DB_FILE="${DATA_DIR}/memoryhub.sqlite"
KUZU_DIR="${DATA_DIR}/kuzu"
TIMESTAMP=$(date -u +"%Y%m%dT%H%M%SZ")
BACKUP_NAME="memoryhub-${BACKUP_TYPE}-${TIMESTAMP}"
BACKUP_FILE="${BACKUP_DIR}/${BACKUP_NAME}.tar.gz.enc"

# Cloud config (from ENV — see docker/.env.example)
CLOUD_PROVIDER="${CLOUD_PROVIDER:-backblaze_b2}"  # backblaze_b2 | aws_s3
CLOUD_BUCKET="${CLOUD_BUCKET:-memoryhub-dr}"
DR_ENCRYPTION_KEY="${MEMORYHUB_DR_ENCRYPTION_KEY:-}"

# ─────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────
LOG_FILE="${DATA_DIR}/logs/backup.log"
log() { echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] $*" | tee -a "${LOG_FILE}"; }
fail() { log "ERROR: $*" >&2; exit 1; }

log "=== Backup started: type=${BACKUP_TYPE}, timestamp=${TIMESTAMP} ==="

# ─────────────────────────────────────────────────────────────────────────
# Parse arguments
# ─────────────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --type) BACKUP_TYPE="$2"; shift 2 ;;
        --data-dir) DATA_DIR="$2"; shift 2 ;;
        *) log "Unknown argument: $1"; shift ;;
    esac
done

# ─────────────────────────────────────────────────────────────────────────
# Pre-flight checks
# ─────────────────────────────────────────────────────────────────────────
[[ -f "${DB_FILE}" ]] || fail "Database not found: ${DB_FILE}"
[[ -n "${DR_ENCRYPTION_KEY}" ]] || fail "MEMORYHUB_DR_ENCRYPTION_KEY not set"

mkdir -p "${BACKUP_DIR}"

# ─────────────────────────────────────────────────────────────────────────
# Step 1: Create SQLite backup (safe online backup)
# Using SQLite .backup command — safe for WAL mode
# ─────────────────────────────────────────────────────────────────────────
TEMP_DIR=$(mktemp -d)
trap "rm -rf ${TEMP_DIR}" EXIT

log "Step 1: Creating SQLite backup..."
sqlite3 "${DB_FILE}" ".backup '${TEMP_DIR}/memoryhub.sqlite'"
log "SQLite backup: $(du -sh "${TEMP_DIR}/memoryhub.sqlite" | cut -f1)"

# ─────────────────────────────────────────────────────────────────────────
# Step 2: Copy KuzuDB data
# ─────────────────────────────────────────────────────────────────────────
log "Step 2: Copying KuzuDB data..."
if [[ -d "${KUZU_DIR}" ]]; then
    cp -r "${KUZU_DIR}" "${TEMP_DIR}/kuzu"
    log "KuzuDB: $(du -sh "${TEMP_DIR}/kuzu" | cut -f1)"
else
    log "KuzuDB directory not found — skipping"
fi

# ─────────────────────────────────────────────────────────────────────────
# Step 3: Create metadata file
# See ARCHITECTURE.md §4.9 "Что бэкапится" — metadata.json
# ─────────────────────────────────────────────────────────────────────────
log "Step 3: Creating metadata..."
RECORD_COUNT=$(sqlite3 "${DB_FILE}" "SELECT COUNT(*) FROM memories WHERE status='shared';" 2>/dev/null || echo "N/A")
cat > "${TEMP_DIR}/metadata.json" <<EOF
{
  "backup_type": "${BACKUP_TYPE}",
  "timestamp": "${TIMESTAMP}",
  "hostname": "$(hostname)",
  "db_file": "${DB_FILE}",
  "record_count_shared": ${RECORD_COUNT},
  "memoryhub_version": "TODO: read from binary"
}
EOF

# ─────────────────────────────────────────────────────────────────────────
# Step 4: Archive and encrypt
# See ARCHITECTURE.md §4.9 encryption.algorithm: "AES-256-GCM"
# ─────────────────────────────────────────────────────────────────────────
log "Step 4: Archiving and encrypting..."
TEMP_ARCHIVE=$(mktemp /tmp/memoryhub-backup-XXXXXX.tar.gz)
tar -czf "${TEMP_ARCHIVE}" -C "${TEMP_DIR}" .

# TODO: Use AES-256-GCM (openssl enc -aes-256-gcm not available in all versions)
# Fallback: AES-256-CBC with PBKDF2
openssl enc -aes-256-cbc -pbkdf2 -iter 100000 \
    -in "${TEMP_ARCHIVE}" \
    -out "${BACKUP_FILE}" \
    -pass env:MEMORYHUB_DR_ENCRYPTION_KEY

rm -f "${TEMP_ARCHIVE}"
log "Encrypted backup: $(du -sh "${BACKUP_FILE}" | cut -f1)"

# ─────────────────────────────────────────────────────────────────────────
# Step 5: Checksum for integrity verification
# See ARCHITECTURE.md §4.9 Restore Verification
# ─────────────────────────────────────────────────────────────────────────
log "Step 5: Computing checksum..."
shasum -a 256 "${BACKUP_FILE}" > "${BACKUP_FILE}.sha256"
log "Checksum: $(cat "${BACKUP_FILE}.sha256" | cut -d' ' -f1)"

# ─────────────────────────────────────────────────────────────────────────
# Step 6: Upload to cloud storage
# TODO: Implement actual cloud upload
# See ARCHITECTURE.md §4.9 cloud.provider
# ─────────────────────────────────────────────────────────────────────────
log "Step 6: Uploading to ${CLOUD_PROVIDER}..."

case "${CLOUD_PROVIDER}" in
    backblaze_b2)
        # TODO: Use rclone or b2 CLI
        # rclone copy "${BACKUP_FILE}" "b2:${CLOUD_BUCKET}/backups/${BACKUP_TYPE}/"
        log "TODO: Implement Backblaze B2 upload"
        ;;
    aws_s3)
        # TODO: aws s3 cp "${BACKUP_FILE}" "s3://${CLOUD_BUCKET}/backups/${BACKUP_TYPE}/"
        log "TODO: Implement AWS S3 upload"
        ;;
    *)
        log "Unknown cloud provider: ${CLOUD_PROVIDER} — local backup only"
        ;;
esac

# ─────────────────────────────────────────────────────────────────────────
# Step 7: Cleanup old local backups
# ─────────────────────────────────────────────────────────────────────────
log "Step 7: Cleaning old local backups..."
case "${BACKUP_TYPE}" in
    incremental) RETENTION_DAYS=7 ;;
    daily)       RETENTION_DAYS=30 ;;
    weekly)      RETENTION_DAYS=365 ;;
    monthly)     RETENTION_DAYS=-1 ;;  # Forever
esac

if [[ ${RETENTION_DAYS} -gt 0 ]]; then
    find "${BACKUP_DIR}" -name "*.enc" -mtime "+${RETENTION_DAYS}" -delete 2>/dev/null || true
    log "Cleaned backups older than ${RETENTION_DAYS} days"
fi

# ─────────────────────────────────────────────────────────────────────────
# Done
# ─────────────────────────────────────────────────────────────────────────
log "=== Backup completed: ${BACKUP_FILE} ==="
log "RTO: 15min | RPO: 6h — See ARCHITECTURE.md §4.9"
