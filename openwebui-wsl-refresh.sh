#!/bin/bash
# OpenWebUI Port Forward Refresh — обновление при изменении IP WSL
# Добавьте в ~/.bashrc: ~/openwebui/refresh-port-forward.sh

PORT=3000
WSL_IP=$(hostname -I | awk '{print $1}')

if [ -z "$WSL_IP" ]; then
    echo "[ERROR] Не удалось получить IP WSL"
    exit 1
fi

echo "[OpenWebUI] Обновление проброса порта..."
echo "            WSL IP: $WSL_IP"

# Проверяем доступность powershell
if ! command -v powershell.exe &>/dev/null; then
    echo "[ERROR] powershell.exe недоступен"
    exit 1
fi

# Удаляем старое правило и создаем новое
powershell.exe -Command "
    # Удалить старое правило если есть
    netsh interface portproxy delete v4tov4 listenport=$PORT listenaddress=0.0.0.0 2>\$null
    
    # Создать новое
    netsh interface portproxy add v4tov4 listenport=$PORT listenaddress=0.0.0.0 connectport=$PORT connectaddress=$WSL_IP
    
    # Показать результат
    Write-Host '[OK] Проброс обновлен: 0.0.0.0:$PORT -> $WSL_IP:$PORT' -ForegroundColor Green
    netsh interface portproxy show all | Select-String -Pattern '$PORT'
" 2>/dev/null

# Перезапускаем OpenWebUI если нужно
cd "$HOME/openwebui" 2>/dev/null && docker compose ps 2>/dev/null | grep -q "Up" || {
    echo "[OpenWebUI] Перезапуск контейнера..."
    cd "$HOME/openwebui" && docker compose up -d 2>/dev/null
}

echo "[OpenWebUI] Готово! http://localhost:$PORT"
