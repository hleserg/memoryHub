#!/bin/bash
# =============================================================================
# Open WebUI + Ollama setup on WSL2 — with LAN access
# =============================================================================
# Использование:
#   chmod +x setup-openwebui.sh
#   ./setup-openwebui.sh
#
# Что делает:
#   1. Проверяет/устанавливает Docker
#   2. Разворачивает Open WebUI (подключается к локальному Ollama на WSL)
#   3. Настраивает проброс порта из Windows -> WSL (через netsh)
#   4. Открывает порт 3000 в Windows Firewall
#   5. Выводит инструкцию по доступу с других машин в сети
# =============================================================================

set -e

OPENWEBUI_PORT=3000
OLLAMA_HOST="host.docker.internal"
OLLAMA_PORT=11434
DATA_DIR="$HOME/openwebui-data"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()    { echo -e "${GREEN}[+]${NC} $1"; }
warn()   { echo -e "${YELLOW}[!]${NC} $1"; }
error()  { echo -e "${RED}[x]${NC} $1"; exit 1; }
info()   { echo -e "${BLUE}[i]${NC} $1"; }

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║     Open WebUI WSL2 Setup Script         ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# -----------------------------------------------------------------------------
# 1. Проверка окружения
# -----------------------------------------------------------------------------
log "Проверяем окружение..."

if ! grep -qi microsoft /proc/version 2>/dev/null; then
    warn "Скрипт не обнаружил WSL-окружение. Продолжаем, но LAN-проброс порта работает только в WSL2."
fi

# -----------------------------------------------------------------------------
# 2. Docker
# -----------------------------------------------------------------------------
if ! command -v docker &>/dev/null; then
    log "Docker не найден — устанавливаем..."
    sudo apt-get update -qq
    sudo apt-get install -y ca-certificates curl gnupg lsb-release

    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg

    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
      https://download.docker.com/linux/ubuntu \
      $(lsb_release -cs) stable" \
      | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

    sudo apt-get update -qq
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    sudo usermod -aG docker "$USER"
    warn "Docker установлен. После скрипта перелогинься или выполни: newgrp docker"
else
    log "Docker уже установлен: $(docker --version)"
fi

# Запускаем демон если не запущен
if ! sudo docker info &>/dev/null 2>&1; then
    log "Запускаем Docker daemon..."
    sudo service docker start
    sleep 3
fi

# -----------------------------------------------------------------------------
# 3. Проверяем Ollama
# -----------------------------------------------------------------------------
log "Проверяем доступность Ollama на localhost:${OLLAMA_PORT}..."

if curl -s --connect-timeout 3 "http://localhost:${OLLAMA_PORT}/api/tags" > /dev/null 2>&1; then
    log "Ollama отвечает ✓"
    MODELS=$(curl -s "http://localhost:${OLLAMA_PORT}/api/tags" | python3 -c \
        "import sys,json; tags=json.load(sys.stdin).get('models',[]); \
         print(', '.join(m['name'] for m in tags)) if tags else print('(нет загруженных моделей)')" 2>/dev/null || echo "(не удалось получить список)")
    info "Загруженные модели: $MODELS"
else
    warn "Ollama не отвечает на localhost:${OLLAMA_PORT}"
    warn "Убедись что ollama запущен: 'ollama serve' или через systemd"
    warn "Продолжаем деплой — Open WebUI запустится, Ollama можно добавить позже"
fi

# -----------------------------------------------------------------------------
# 4. Создаём директорию для данных
# -----------------------------------------------------------------------------
log "Создаём директорию для данных: $DATA_DIR"
mkdir -p "$DATA_DIR"

# -----------------------------------------------------------------------------
# 5. docker-compose.yml
# -----------------------------------------------------------------------------
log "Генерируем docker-compose.yml..."

COMPOSE_FILE="$HOME/openwebui/docker-compose.yml"
mkdir -p "$HOME/openwebui"

cat > "$COMPOSE_FILE" << EOF
version: "3.8"

services:
  open-webui:
    image: ghcr.io/open-webui/open-webui:main
    container_name: open-webui
    restart: unless-stopped

    # Слушаем на всех интерфейсах WSL — нужно для проброса в Windows
    ports:
      - "0.0.0.0:${OPENWEBUI_PORT}:8080"

    volumes:
      - ${DATA_DIR}:/app/backend/data

    environment:
      # Ollama внутри Docker недоступен через localhost — используем host.docker.internal
      - OLLAMA_BASE_URL=http://${OLLAMA_HOST}:${OLLAMA_PORT}

      # Если хочешь подключить OpenAI/Anthropic API — раскомментируй:
      # - OPENAI_API_KEY=sk-...
      # - OPENAI_API_BASE_URL=https://api.openai.com/v1

      # Безопасность: первый зарегистрированный пользователь станет admin
      # Для внутренней сети можно отключить регистрацию после первого входа
      - WEBUI_AUTH=true

      # Название в интерфейсе
      - WEBUI_NAME=Alfred WebUI

    # Для доступа к Ollama на хосте через host.docker.internal
    extra_hosts:
      - "host.docker.internal:host-gateway"

    # Health check
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s
EOF

log "docker-compose.yml создан: $COMPOSE_FILE"

# -----------------------------------------------------------------------------
# 6. Запускаем Open WebUI
# -----------------------------------------------------------------------------
log "Запускаем Open WebUI..."
cd "$HOME/openwebui"
sudo docker compose pull
sudo docker compose up -d

log "Контейнер запущен ✓"

# -----------------------------------------------------------------------------
# 7. Получаем IP WSL
# -----------------------------------------------------------------------------
WSL_IP=$(hostname -I | awk '{print $1}')
log "IP WSL2: $WSL_IP"

# -----------------------------------------------------------------------------
# 8. Windows netsh — проброс порта WSL -> Windows
# -----------------------------------------------------------------------------
log "Создаём скрипт для проброса порта через Windows netsh..."

# Путь к Windows tmp (работает в WSL2)
WIN_TEMP=$(wslpath "$(cmd.exe /c 'echo %TEMP%' 2>/dev/null | tr -d '\r')" 2>/dev/null || echo "/tmp")

PORT_FORWARD_SCRIPT="$HOME/openwebui/windows-port-forward.ps1"

cat > "$PORT_FORWARD_SCRIPT" << PSEOF
# ============================================================
# Запусти этот скрипт в PowerShell от имени Администратора!
# ============================================================
# Автоматически пробрасывает порт из Windows в WSL2
# и открывает его в Windows Firewall

param(
    [string]\$WslIp = "${WSL_IP}",
    [int]\$Port = ${OPENWEBUI_PORT}
)

Write-Host "=== Open WebUI Port Forward Setup ===" -ForegroundColor Cyan

# Получаем актуальный IP WSL (может меняться при перезапуске)
\$wslIpActual = (wsl hostname -I).Trim().Split(' ')[0]
if (\$wslIpActual) {
    Write-Host "WSL IP detected: \$wslIpActual" -ForegroundColor Green
    \$WslIp = \$wslIpActual
} else {
    Write-Host "Using provided WSL IP: \$WslIp" -ForegroundColor Yellow
}

# Удаляем старое правило если есть
netsh interface portproxy delete v4tov4 listenport=\$Port listenaddress=0.0.0.0 2>\$null

# Добавляем проброс
netsh interface portproxy add v4tov4 `
    listenport=\$Port `
    listenaddress=0.0.0.0 `
    connectport=\$Port `
    connectaddress=\$WslIp

Write-Host "Port proxy added: 0.0.0.0:\$Port -> \$WslIp:\$Port" -ForegroundColor Green

# Добавляем правило firewall (если нет)
\$ruleName = "Open WebUI WSL2"
\$existingRule = Get-NetFirewallRule -DisplayName \$ruleName -ErrorAction SilentlyContinue

if (-not \$existingRule) {
    New-NetFirewallRule `
        -DisplayName \$ruleName `
        -Direction Inbound `
        -Protocol TCP `
        -LocalPort \$Port `
        -Action Allow `
        -Profile Any | Out-Null
    Write-Host "Firewall rule created: '\$ruleName'" -ForegroundColor Green
} else {
    Write-Host "Firewall rule already exists: '\$ruleName'" -ForegroundColor Yellow
}

# Показываем текущий IP Windows
\$windowsIp = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { \$_.InterfaceAlias -notmatch 'Loopback' -and \$_.InterfaceAlias -notmatch 'WSL' } | Select-Object -First 1).IPAddress
Write-Host ""
Write-Host "=== Готово! ===" -ForegroundColor Cyan
Write-Host "Открой в браузере с любого устройства в сети:" -ForegroundColor White
Write-Host "  http://\$windowsIp:\$Port" -ForegroundColor Yellow
Write-Host ""
Write-Host "Для проверки проброса:" -ForegroundColor White
Write-Host "  netsh interface portproxy show all" -ForegroundColor Gray
PSEOF

log "PowerShell скрипт создан: $PORT_FORWARD_SCRIPT"

# -----------------------------------------------------------------------------
# 9. Пробуем запустить netsh прямо сейчас через cmd.exe
# -----------------------------------------------------------------------------
log "Пробуем автоматически применить проброс порта..."

if command -v cmd.exe &>/dev/null 2>&1; then
    # Пробуем через powershell.exe из WSL
    if command -v powershell.exe &>/dev/null 2>&1; then
        powershell.exe -Command "
            netsh interface portproxy add v4tov4 listenport=${OPENWEBUI_PORT} listenaddress=0.0.0.0 connectport=${OPENWEBUI_PORT} connectaddress=${WSL_IP} 2>&1
            netsh advfirewall firewall add rule name='Open WebUI WSL2' dir=in action=allow protocol=TCP localport=${OPENWEBUI_PORT} 2>&1
        " 2>/dev/null && log "Проброс порта применён автоматически ✓" || warn "Не удалось применить автоматически — нужны права администратора"
    fi
else
    warn "cmd.exe недоступен — запусти PowerShell скрипт вручную (см. ниже)"
fi

# -----------------------------------------------------------------------------
# 10. Скрипт автообновления IP при перезапуске WSL
# -----------------------------------------------------------------------------
REFRESH_SCRIPT="$HOME/openwebui/refresh-port-forward.sh"

cat > "$REFRESH_SCRIPT" << 'RFEOF'
#!/bin/bash
# Запускай этот скрипт после каждого перезапуска WSL
# Обновляет проброс порта с актуальным IP WSL
WSL_IP=$(hostname -I | awk '{print $1}')
PORT=3000
echo "[+] WSL IP: $WSL_IP"
if command -v powershell.exe &>/dev/null 2>&1; then
    powershell.exe -Command "
        netsh interface portproxy delete v4tov4 listenport=${PORT} listenaddress=0.0.0.0 2>&1
        netsh interface portproxy add v4tov4 listenport=${PORT} listenaddress=0.0.0.0 connectport=${PORT} connectaddress=${WSL_IP} 2>&1
    " && echo "[+] Проброс порта обновлён" || echo "[!] Нужны права администратора для netsh"
fi
# Перезапускаем контейнер если нужно
cd "$HOME/openwebui" && sudo docker compose up -d
echo "[+] Open WebUI: http://$WSL_IP:$PORT (WSL) | http://$(hostname -I | awk '{print $1}'):$PORT"
RFEOF

chmod +x "$REFRESH_SCRIPT"

# -----------------------------------------------------------------------------
# 11. Итог
# -----------------------------------------------------------------------------
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║                    ГОТОВО!                               ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo -e "║  Open WebUI в WSL:   ${BLUE}http://${WSL_IP}:${OPENWEBUI_PORT}${NC}"
echo -e "║  (Windows доступ после проброса порта)"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  СЛЕДУЮЩИЕ ШАГИ:                                         ║"
echo "║                                                           ║"
echo "║  1. Запусти PowerShell от Администратора в Windows       ║"
echo "║     и выполни:                                           ║"
echo -e "║     ${YELLOW}powershell -ExecutionPolicy Bypass -File${NC}"
echo -e "║     ${YELLOW}\\\\wsl\$\\Ubuntu\\home\\$USER\\openwebui\\windows-port-forward.ps1${NC}"
echo "║                                                           ║"
echo "║  2. Открой в браузере на ЛЮБОМ устройстве сети:         ║"
echo "║     http://<IP_Windows_машины>:${OPENWEBUI_PORT}                  ║"
echo "║                                                           ║"
echo "║  3. После каждого перезапуска WSL запусти:              ║"
echo "║     ~/openwebui/refresh-port-forward.sh                  ║"
echo "║                                                           ║"
echo "║  Логи контейнера:                                        ║"
echo "║     sudo docker compose -f ~/openwebui/docker-compose.yml logs -f  ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# Ждём готовности и сообщаем
log "Ждём запуска Open WebUI (до 60 сек)..."
for i in $(seq 1 12); do
    if curl -s --connect-timeout 3 "http://localhost:${OPENWEBUI_PORT}" > /dev/null 2>&1; then
        log "Open WebUI готов! ✓"
        break
    fi
    sleep 5
    echo -n "."
done
echo ""
