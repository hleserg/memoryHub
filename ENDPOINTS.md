# Atman Memory Stack — Endpoints Reference

**Создано:** $(date '+%Y-%m-%d %H:%M:%S')  
**Хост:** WSL2 (172.31.192.143) / Windows (localhost)

---

## 🧠 Core Services

### PostgreSQL + pgvector
| Параметр | Значение |
|----------|----------|
| Host | `localhost` |
| Port | `5432` |
| Database | `atman` |
| User | `atman` |
| Password | `${POSTGRES_PASSWORD}` (в `.env`) |
| Connection String | `postgresql://atman:${POSTGRES_PASSWORD}@localhost:5432/atman` |

**Docker:**
```bash
docker exec -it atman-postgres psql -U atman -d atman
```

---

### Qdrant (Vector Database)
| Параметр | Значение |
|----------|----------|
| HTTP API | `http://localhost:6333` |
| gRPC API | `http://localhost:6334` |
| API Key | `${QDRANT_API_KEY}` (в `.env`) |

**Collections:**
- `atman_facts` — фактическая память
- `atman_experiences` — опыт/сессии

**Health Check:**
```bash
curl -H "api-key: ${QDRANT_API_KEY}" http://localhost:6333/collections/atman_facts
```

---

### Ollama (LLM API)
| Параметр | Значение |
|----------|----------|
| Base URL | `http://localhost:11434` |
| API Docs | https://github.com/ollama/ollama/blob/main/docs/api.md |

**Models:**
| Model | Size | Purpose | VRAM |
|-------|------|---------|------|
| `qwen3.5:9b` | 6.6 GB | LLM (chat/reasoning) | ~8 GB |
| `qwen3-embedding:4b` | 2.5 GB | Embeddings | ~3 GB |

**Quick Test:**
```bash
# Chat
curl http://localhost:11434/api/generate -d '{
  "model": "qwen3.5:9b",
  "prompt": "Привет! Как дела?",
  "stream": false
}'

# List models
curl http://localhost:11434/api/tags

# Embeddings
curl http://localhost:11434/api/embed -d '{
  "model": "qwen3-embedding:4b",
  "input": "Текст для эмбеддинга"
}'
```

---

## 🌐 Web UI

### OpenWebUI (Chat Interface)
| Параметр | Значение |
|----------|----------|
| WSL URL | `http://172.31.192.143:3000` |
| Windows URL | `http://localhost:3000` (после проброса) |
| LAN URL | `http://<Windows_IP>:3000` |

**Настройка Ollama в UI:**
- Base URL: `http://host.docker.internal:11434` (уже настроено)

**First Login:**
- Первый зарегистрированный пользователь = Admin

---

## 🔌 Connection Strings для Atman Code

### Python (psycopg2 / asyncpg)
```python
import os
from dotenv import load_dotenv

load_dotenv()

# PostgreSQL
PG_URL = f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}@localhost:5432/{os.getenv('POSTGRES_DB')}"

# Qdrant
QDRANT_URL = "http://localhost:6333"
QDRANT_API_KEY = os.getenv('QDRANT_API_KEY')

# Ollama
OLLAMA_URL = "http://localhost:11434"
```

### Docker Compose (внутри сети)
```yaml
# Для сервисов внутри docker-compose:
environment:
  - POSTGRES_URL=postgresql://atman:${POSTGRES_PASSWORD}@atman-postgres:5432/atman
  - QDRANT_URL=http://atman-qdrant:6333
  - OLLAMA_URL=http://host.docker.internal:11434  # для WSL2
```

---

## 🛠️ Management Commands

### Запуск / Остановка
```bash
# Все сервисы Atman
cd /mnt/nvme/atman/atman
docker compose up -d          # Запуск
docker compose stop           # Остановка
docker compose down           # Удаление

# OpenWebUI (отдельно)
cd ~/openwebui
docker compose up -d
docker compose stop

# Ollama
ollama serve                  # Запуск сервера
ollama list                   # Список моделей
ollama ps                     # Загруженные модели
ollama pull <model>           # Скачать модель
ollama rm <model>             # Удалить модель
```

### Логи
```bash
# PostgreSQL
docker logs atman-postgres -f

# Qdrant
docker logs atman-qdrant -f

# OpenWebUI
docker logs open-webui -f

# Ollama
tail -f ~/.atman/ollama.log
```

### Health Checks
```bash
# PostgreSQL
docker exec atman-postgres pg_isready -U atman

# Qdrant
curl -H "api-key: $(grep QDRANT_API_KEY .env | cut -d= -f2)" http://localhost:6333/healthz

# Ollama
curl http://localhost:11434/api/tags

# OpenWebUI
curl http://localhost:3000/health
```

---

## 🌐 Windows Port Forward (LAN Access)

### Настройка доступа из локальной сети
**PowerShell (Admin):**
```powershell
# Проброс порта WSL -> Windows
netsh interface portproxy add v4tov4 listenport=3000 listenaddress=0.0.0.0 connectport=3000 connectaddress=172.31.192.143

# Firewall правило
New-NetFirewallRule -DisplayName "Open WebUI WSL2" -Direction Inbound -Protocol TCP -LocalPort 3000 -Action Allow
```

### Обновление после перезапуска WSL
```bash
~/openwebui/refresh-port-forward.sh
```

---

## 📁 Файлы конфигурации

| Файл | Назначение |
|------|------------|
| `/mnt/nvme/atman/atman/.env` | Environment variables |
| `/mnt/nvme/atman/atman/.secrets` | Secrets (passwords, keys) |
| `/mnt/nvme/atman/atman/docker-compose.yml` | Atman infrastructure |
| `~/openwebui/docker-compose.yml` | OpenWebUI |
| `~/.atman/ollama.log` | Ollama logs |
| `/mnt/nvme/atman/backups/` | PostgreSQL backups |

---

## 🔒 Secrets

**Никогда не коммитьте эти файлы!**
- `.env`
- `.secrets`
- `*.key`, `*.pem`

**Получить значение:**
```bash
grep POSTGRES_PASSWORD /mnt/nvme/atman/atman/.env
grep QDRANT_API_KEY /mnt/nvme/atman/atman/.env
```

---

## 📝 Quick Reference Card

```
┌─────────────────────────────────────────────────────────────────┐
│  ATMAN MEMORY STACK ENDPOINTS                                    │
├─────────────────────────────────────────────────────────────────┤
│  PostgreSQL     localhost:5432      user: atman                  │
│  Qdrant HTTP    localhost:6333      api-key required             │
│  Qdrant gRPC    localhost:6334                                   │
│  Ollama         localhost:11434     qwen3.5:9b, qwen3-embed:4b   │
│  OpenWebUI      localhost:3000      http://172.31.192.143:3000   │
├─────────────────────────────────────────────────────────────────┤
│  DOCKER                                                          │
│  atman-postgres  Up   5432->5432/tcp                             │
│  atman-qdrant    Up   6333->6333, 6334->6334/tcp                 │
│  open-webui      Up   3000->8080/tcp                             │
└─────────────────────────────────────────────────────────────────┘
```

---

**Последнее обновление:** $(date '+%Y-%m-%d %H:%M:%S')
