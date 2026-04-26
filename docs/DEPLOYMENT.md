# memoryHub — Deployment Guide

> See ARCHITECTURE.md §9 Deployment Diagram for full architecture context.

---

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Go          | 1.22+   | CGO required (for go-sqlite3) |
| Docker      | 24+     | For containerized deployment |
| Docker Compose | 2.20+ | Multi-service orchestration |
| SQLite dev headers | 3.40+ | `libsqlite3-dev` on Ubuntu, `sqlite` on Alpine |
| Make        | 3.81+   | Build automation |
| Git         | 2.40+   | For GitHub Snapshots |

Optional (recommended for production):

| Tool | Purpose |
|------|---------|
| `air` | Hot-reload in development |
| `golangci-lint` | Code linting (`make lint`) |
| `redis` 7.2+ | Distributed rate limiting |

---

## Quick Start (Local Development)

```bash
# 1. Clone repository
git clone https://github.com/YOUR_ORG/memoryhub
cd memoryhub

# 2. Run setup (creates dirs, copies config, runs migrations)
make setup

# 3. Start dependencies (Redis)
make docker-up

# 4. Run in development mode
make dev
# → API Hub:   http://localhost:3000
# → MCP Server: http://localhost:3100
# → Dashboard:  http://localhost:3200

# 5. Verify
curl http://localhost:3000/v1/health
```

---

## Configuration

All configuration lives in a single file: `config/memoryhub.config.yaml`  
See ARCHITECTURE.md §10 Единый конфиг for complete parameter reference.

```bash
# Copy template
cp config/memoryhub.config.yaml /etc/memoryhub/memoryhub.config.yaml

# Edit to match your environment
vim /etc/memoryhub/memoryhub.config.yaml
```

**Key settings to configure first:**

1. `system.environment` → `production`
2. `system.data_dir` → persistent data path (e.g. `/data/memoryhub`)
3. `api_hub.port` → default `3000`
4. `storage.embeddings.provider` → `local` (no API key) or `openai`
5. `disaster_recovery.cloud.*` → S3/B2 credentials
6. `integrations.telegram.*` → Bot token and chat ID for alerts

Environment variables override config file values. See `docker/.env.example` for full list.

---

## Docker Deployment (Recommended)

### Single-node production

```bash
# 1. Clone and configure
git clone https://github.com/YOUR_ORG/memoryhub
cd memoryhub

# 2. Configure environment
cp docker/.env.example docker/.env
vim docker/.env  # Fill in real secrets

# 3. Configure system
cp config/memoryhub.config.yaml /etc/memoryhub/memoryhub.config.yaml
vim /etc/memoryhub/memoryhub.config.yaml

# 4. Start services
make docker-up

# 5. Initialize database and create admin key
docker exec memoryhub_api /usr/local/bin/memoryhub-setup.sh

# 6. Check health
curl http://localhost:3000/v1/health
```

### Managing services

```bash
make docker-up      # Start
make docker-down    # Stop
make docker-logs    # Tail logs
make docker-build   # Rebuild image
```

---

## Native Deployment (systemd)

For deployment directly on macOS or Linux without Docker:

```bash
# 1. Build binary
make build
sudo cp build/memoryhub /usr/local/bin/

# 2. Create service user
sudo useradd -r -s /bin/false memoryhub

# 3. Create data directories (ARCHITECTURE.md §9)
sudo mkdir -p /data/memoryhub/kuzu /data/memoryhub/backups /data/memoryhub/logs
sudo mkdir -p /etc/memoryhub
sudo chown -R memoryhub:memoryhub /data/memoryhub /etc/memoryhub

# 4. Configure
sudo cp config/memoryhub.config.yaml /etc/memoryhub/
sudo vim /etc/memoryhub/memoryhub.config.yaml

# 5. Initialize database
sudo -u memoryhub memoryhub init --config /etc/memoryhub/memoryhub.config.yaml

# 6. Install systemd services (ARCHITECTURE.md §9)
sudo cp deploy/memoryhub.service /etc/systemd/system/
sudo cp deploy/memoryhub-dr.timer /etc/systemd/system/
sudo cp deploy/memoryhub-gh.timer /etc/systemd/system/
sudo systemctl daemon-reload

# 7. Enable and start
sudo systemctl enable --now memoryhub
sudo systemctl enable --now memoryhub-dr.timer
sudo systemctl enable --now memoryhub-gh.timer

# 8. Check status
sudo systemctl status memoryhub
curl http://localhost:3000/v1/health
```

---

## First-Run Initialization

After deployment, initialize the system:

```bash
# Create initial admin API key (shown ONCE — save it!)
memoryhub keys create \
  --name "admin" \
  --tier trusted \
  --permissions all

# Create an agent key for Alfred
memoryhub keys create \
  --name "alfred" \
  --tier trusted \
  --permissions read,write,verify

# Verify
curl http://localhost:3000/v1/status \
  -H "Authorization: Bearer mhub_prod_admin_..."
```

---

## Database Migrations

Migrations are applied automatically on startup. To run manually:

```bash
# Via Makefile (applies all migrations in order)
make migrate

# Directly
sqlite3 /data/memoryhub/memoryhub.sqlite < db/migrations/001_init.sql
sqlite3 /data/memoryhub/memoryhub.sqlite < db/migrations/002_trust.sql
sqlite3 /data/memoryhub/memoryhub.sqlite < db/migrations/003_graph.sql
```

Migration files are in `db/migrations/` and are numbered sequentially.

---

## Health Monitoring

Dashboard (when implemented, Week 8): `http://localhost:3200`

Quick health checks via CLI (see ARCHITECTURE.md Appendix B):

```bash
# System status
curl http://localhost:3000/v1/status | jq '.overall_health'

# Trust Pipeline queue
curl http://localhost:3000/v1/review/queue | jq '.total'

# Quarantine
curl http://localhost:3000/v1/quarantine | jq '.total'

# Last backup
curl http://localhost:3000/v1/dr/status | jq '.last_backup'

# Conflicts
curl http://localhost:3000/v1/graph/conflicts?resolved=false | jq '.total'
```

---

## Disaster Recovery

See ARCHITECTURE.md §4.9 for full DR documentation.

```bash
# List available recovery points
memoryhub dr list-snapshots

# Restore to specific point in time
memoryhub dr restore --snapshot 2026-04-25T03:00:00Z

# Dry-run restore (for verification)
memoryhub dr restore --snapshot 2026-04-25T03:00:00Z --dry-run --target /tmp/restore-test

# Verify restored data
memoryhub dr verify --path /tmp/restore-test
```

**Recovery objectives** (ARCHITECTURE.md §4.9):
- RTO: < 15 minutes
- RPO: < 6 hours
- MTTR: < 10 minutes (with available snapshot)

---

## GitHub Snapshots

Automated daily exports to a private GitHub repository.  
See ARCHITECTURE.md §4.10 GitHub Snapshots.

```bash
# Configure
export MEMORYHUB_GITHUB_TOKEN=ghp_...
export MEMORYHUB_GITHUB_REPO_OWNER=your-username
export MEMORYHUB_GITHUB_REPO_NAME=memoryhub-snapshots

# Manual snapshot
memoryhub snapshot push

# Audit memory history
git clone https://github.com/your-username/memoryhub-snapshots
cd memoryhub-snapshots
git log --oneline --since="7 days ago"
git diff v2026.16 v2026.17 -- latest/memories.json
```

---

## Upgrading

```bash
# 1. Pull latest code
git pull origin main

# 2. Build new binary
make build

# 3. Stop service
sudo systemctl stop memoryhub

# 4. Replace binary
sudo cp build/memoryhub /usr/local/bin/

# 5. Apply any new migrations
make migrate

# 6. Restart
sudo systemctl start memoryhub

# 7. Verify
curl http://localhost:3000/v1/health
```

---

## Troubleshooting

### Service won't start

```bash
# Check logs
journalctl -u memoryhub -n 50
# or Docker:
docker logs memoryhub_api

# Validate config
memoryhub config validate --config /etc/memoryhub/memoryhub.config.yaml

# Check data dir permissions
ls -la /data/memoryhub/
```

### Trust Pipeline full (>100 items)

```bash
# See ARCHITECTURE.md Appendix B Operational Runbook
curl http://localhost:3000/v1/review/queue?limit=10

# Bulk approve trusted agent
curl -X POST http://localhost:3000/v1/review/bulk-approve \
  -H "Authorization: Bearer <ADMIN_KEY>" \
  -d '{"agent_id": "alfred", "since": "2026-04-25T00:00:00Z"}'
```

### Disk space

```bash
# Check usage
df -h /data/memoryhub/

# Cleanup archived records (older than 90 days)
memoryhub maintenance cleanup --older-than 90d --status archived

# Force DR upload + local cleanup
memoryhub dr force-upload && memoryhub dr local-cleanup
```

### Integrity violation

```bash
# Get details
curl http://localhost:3000/v1/quarantine?reason=integrity_violation \
  -H "Authorization: Bearer <ADMIN_KEY>"

# Run manual rescan
curl -X POST http://localhost:3000/v1/admin/rescan \
  -H "Authorization: Bearer <ADMIN_KEY>" \
  -d '{"scope": "recent", "hours": 24}'
```

---

## Security Checklist

Before going to production:

- [ ] Admin API key rotated from default
- [ ] TLS enabled (`api_hub.tls.enabled: true`)
- [ ] `docker/.env` not committed to git (check `.gitignore`)
- [ ] DR encryption key set (`MEMORYHUB_DR_ENCRYPTION_KEY`)
- [ ] Signing key set (`MEMORYHUB_SIGNING_KEY`)
- [ ] Integrity checksums enabled (`corruption_protection.checksums.enabled: true`)
- [ ] Rate limiting tuned per agent tier
- [ ] Telegram alerts configured and tested
- [ ] DR restore tested (dry-run at minimum)
- [ ] Audit log retention configured

See ARCHITECTURE.md §14 Security — Threat Model for complete security guidance.
