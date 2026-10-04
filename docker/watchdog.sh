#!/bin/bash
# =========================================================
# ASTRA v9.0 — Systemd Watchdog Script
# systemd ile kullan, yoksa bu script'i cronjob'a ekle:
# */5 * * * * /opt/astra/docker/watchdog.sh
# =========================================================

ASTRA_DIR="/opt/astra"
LOG_FILE="$ASTRA_DIR/logs/watchdog.log"
HEARTBEAT_FILE="$ASTRA_DIR/logs/.heartbeat"
MAX_SILENT=300   # 5 dakika

MAX_LOG_BYTES=10485760   # 10 MB
MAX_ARSIV=5

timestamp() { date '+%Y-%m-%d %H:%M:%S'; }

# v55: Log rotasyonu EKLENDİ. Bu script cron ile 5 dakikada bir çalışıyor ve
# her çalışmada watchdog.log'a satır ekliyordu — hiçbir rotasyon yoktu, yani
# 7/24 çalışan bir kurulumda dosya sınırsız büyüyordu.
# (baslat.sh astra.log için zaten rotasyon yapıyor; bu dosya atlanmıştı.)
rotate_log() {
    [ -f "$LOG_FILE" ] || return 0
    local boyut
    boyut=$(stat -c %s "$LOG_FILE" 2>/dev/null || echo 0)
    [ "$boyut" -lt "$MAX_LOG_BYTES" ] && return 0
    local i=$MAX_ARSIV
    while [ "$i" -gt 1 ]; do
        [ -f "${LOG_FILE}.$((i-1))" ] && mv -f "${LOG_FILE}.$((i-1))" "${LOG_FILE}.${i}"
        i=$((i-1))
    done
    mv -f "$LOG_FILE" "${LOG_FILE}.1"
    : > "$LOG_FILE"
}

log() {
    mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null
    rotate_log
    echo "[$(timestamp)] $1" >> "$LOG_FILE"
}

# Process çalışıyor mu?
if ! pgrep -f "python.*main.py" > /dev/null; then
    log "KRITIK: Bot çalışmıyor! systemd restart tetikleniyor..."
    systemctl restart astra 2>/dev/null || \
        (cd "$ASTRA_DIR" && source venv/bin/activate && \
         nohup python main.py futures >> logs/astra.log 2>&1 &)
    log "Restart komutu gönderildi"
    exit 1
fi

# Heartbeat kontrolü (main.py logs/astra.log'a yazıyor)
if [ -f "$ASTRA_DIR/logs/astra.log" ]; then
    SON_YAZIM=$(stat -c %Y "$ASTRA_DIR/logs/astra.log" 2>/dev/null || echo 0)
    SIMDI=$(date +%s)
    FARK=$((SIMDI - SON_YAZIM))
    if [ "$FARK" -gt "$MAX_SILENT" ]; then
        log "UYARI: Log ${FARK}s'dir güncellenmedi — restart"
        systemctl restart astra 2>/dev/null
    fi
fi

log "OK: Bot çalışıyor"
