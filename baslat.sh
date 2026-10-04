#!/bin/bash
# =========================================================
# ASTRA — Güvenli Başlatma Betiği v44 (screen + log + auto-restart)
# Kullanım: ./baslat.sh
#
# YENİ v44:
#  - Loglar KALICI dosyaya yazılır (logs/astra.log) — bot çökse bile
#    [WATCHDOG TEŞHİS] dahil her şey kaydolur.
#  - Bot çökerse OTOMATİK yeniden başlar (10s sonra).
#  - PuTTY'den bağımsız (screen).
# =========================================================

BOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCREEN_AD="astra"
LOG_DIR="$BOT_DIR/logs"
LOG_FILE="$LOG_DIR/astra.log"

mkdir -p "$LOG_DIR"

# v50: Log rotasyonu — logs/ sınırsız büyümesin (denetim bulgusu M-5).
# 50MB'ı aşarsa arşivle, en fazla 5 arşiv tut.
if [ -f "$LOG_FILE" ]; then
    BOYUT=$(stat -c%s "$LOG_FILE" 2>/dev/null || echo 0)
    if [ "$BOYUT" -gt 52428800 ]; then
        mv "$LOG_FILE" "$LOG_FILE.$(date +%Y%m%d-%H%M%S)"
        ls -1t "$LOG_DIR"/astra.log.* 2>/dev/null | tail -n +6 | xargs -r rm -f
        echo "  → Log arşivlendi (50MB aşıldı), eski arşivler temizlendi"
    fi
fi

echo "════════════════════════════════════════════"
echo "  ASTRA — Güvenli Başlatma v44"
echo "════════════════════════════════════════════"

# 1. Sunucu saati kontrolü (-1021 önleme)
echo ""
echo "▶ Sunucu saati kontrol ediliyor..."
if command -v timedatectl &> /dev/null; then
    SENKRON=$(timedatectl 2>/dev/null | grep -i "synchronized" | grep -i "yes")
    if [ -z "$SENKRON" ]; then
        echo "  ⚠ Saat senkronize değil! Düzeltiliyor..."
        timedatectl set-ntp true 2>/dev/null
        systemctl restart systemd-timesyncd 2>/dev/null
        echo "  → NTP açıldı"
    else
        echo "  ✓ Saat senkron"
    fi
fi

# 2. screen kurulu mu?
if ! command -v screen &> /dev/null; then
    echo "  ⚠ screen kuruluyor..."
    apt install -y screen 2>/dev/null
fi

# 3. Zaten çalışıyor mu?
if screen -list 2>/dev/null | grep -q "$SCREEN_AD"; then
    echo ""
    echo "  ⚠ Zaten çalışan bir ASTRA oturumu var!"
    read -p "  Durdurup yeniden başlatayım mı? (e/h): " yanit
    if [ "$yanit" = "e" ]; then
        screen -X -S "$SCREEN_AD" quit 2>/dev/null
        sleep 1
    else
        echo "  İptal. Bağlanmak için: screen -r $SCREEN_AD"
        exit 0
    fi
fi

# 4. venv kontrolü
if [ ! -d "$BOT_DIR/venv" ]; then
    echo "  ❌ venv yok! Önce: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# 5. Otomatik-restart döngüsü içeren çalıştırıcı betik
RUNNER="$BOT_DIR/.astra_runner.sh"
cat > "$RUNNER" << RUNNEREOF
#!/bin/bash
cd "$BOT_DIR"
source venv/bin/activate
while true; do
    echo "════════════════════════════════════════════"
    echo "[\$(date '+%Y-%m-%d %H:%M:%S')] ASTRA başlatılıyor..."
    echo "════════════════════════════════════════════"
    # Hem ekrana hem log dosyasına yaz (tee), stderr dahil
    python main.py bot 2>&1 | tee -a "$LOG_FILE"
    KOD=\${PIPESTATUS[0]}
    echo "[\$(date '+%Y-%m-%d %H:%M:%S')] Bot durdu (çıkış kodu: \$KOD). 10s sonra yeniden başlıyor..." | tee -a "$LOG_FILE"
    sleep 10
done
RUNNEREOF
chmod +x "$RUNNER"

# 6. screen içinde otomatik-restart döngüsünü başlat
echo ""
echo "▶ Bot başlatılıyor (otomatik-restart + log dosyası)..."
screen -dmS "$SCREEN_AD" bash "$RUNNER"
sleep 3

# 7. Kontrol
if screen -list 2>/dev/null | grep -q "$SCREEN_AD"; then
    echo ""
    echo "════════════════════════════════════════════"
    echo "  ✅ ASTRA BAŞLATILDI"
    echo "════════════════════════════════════════════"
    echo ""
    echo "  • PuTTY'i KAPATABİLİRSİNİZ — bot çalışmaya devam eder."
    echo "  • Bot çökerse 10s içinde OTOMATİK yeniden başlar."
    echo "  • Loglar kalıcı: $LOG_FILE"
    echo ""
    echo "  Faydalı komutlar:"
    echo "    Canlı ekran    : screen -r $SCREEN_AD"
    echo "    Ayrıl          : Ctrl+A sonra D"
    echo "    Logu izle      : tail -f $LOG_FILE"
    echo "    WATCHDOG ara   : grep 'WATCHDOG TEŞHİS' $LOG_FILE"
    echo "    Tamamen durdur : screen -X -S $SCREEN_AD quit"
    echo ""
else
    echo "  ❌ Başlatılamadı. Manuel: cd $BOT_DIR && source venv/bin/activate && python main.py bot"
    exit 1
fi
