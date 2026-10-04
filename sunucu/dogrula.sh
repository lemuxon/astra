#!/bin/bash
# =========================================================
# ASTRA — Sunucu sağlık doğrulaması
# Kullanım: sudo -u astra bash /opt/astra/sunucu/dogrula.sh
#
# Kurulumdan sonra ve "acaba çalışıyor mu?" dediğiniz her an çalıştırın.
# Hiçbir şeyi DEĞİŞTİRMEZ, yalnızca okur.
# =========================================================
set -uo pipefail

KOK="${ASTRA_KOK:-/opt/astra}"
PY="$KOK/venv/bin/python"
HATA=0

baslik() { echo; echo "=== $1 ==="; }
ok()     { echo "  ✅ $1"; }
uyari()  { echo "  ⚠️  $1"; }
hata()   { echo "  ❌ $1"; HATA=$((HATA+1)); }

cd "$KOK" 2>/dev/null || { echo "❌ $KOK bulunamadı"; exit 1; }

baslik "1. SERVİS"
if systemctl is-active --quiet astra; then
    ok "astra servisi çalışıyor ($(systemctl show -p ActiveEnterTimestamp --value astra))"
else
    hata "astra servisi ÇALIŞMIYOR — systemctl status astra"
fi
yeniden=$(systemctl show -p NRestarts --value astra 2>/dev/null || echo "?")
if [ "$yeniden" != "0" ] && [ "$yeniden" != "?" ]; then
    uyari "servis $yeniden kez yeniden başlamış — journalctl -u astra ile sebebe bakın"
else
    ok "yeniden başlatma yok"
fi

baslik "2. SÜREÇ"
if pgrep -f "main.py bot" >/dev/null; then
    ok "main.py bot süreci ayakta (PID $(pgrep -f 'main.py bot' | tr '\n' ' '))"
else
    hata "main.py bot süreci YOK"
fi

baslik "3. ÇALIŞMA MODU"
if grep -qE '^LIVE_TRADING\s*=\s*false' .env 2>/dev/null; then
    ok "LIVE_TRADING=false (paper — gerçek para riski yok)"
else
    uyari "LIVE_TRADING false DEĞİL — gerçek para modunda olabilirsiniz!"
fi
if grep -qE '^CHAT_ID=.+' .env 2>/dev/null; then
    ok "CHAT_ID dolu (Telegram komut yetkilendirmesi aktif)"
else
    hata "CHAT_ID BOŞ — token'ı bilen herkes komut çalıştırabilir (v56 kritik)"
fi

baslik "4. PANEL GÜVENLİĞİ"
if grep -qE '^PANEL_USER=.+' .env 2>/dev/null && grep -qE '^PANEL_PASS=.+' .env 2>/dev/null; then
    ok "panel kimlik doğrulaması tanımlı"
else
    uyari "panel auth YOK — paneli dışarı açmayın, SSH tüneli kullanın"
fi
if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q "8080"; then
    hata "8080 portu güvenlik duvarında AÇIK — panel auth yoksa çok riskli"
else
    ok "8080 dışarı kapalı görünüyor"
fi

baslik "5. SAYAÇ (canlıya geçiş kriteri)"
"$PY" - <<'PYEOF' 2>/dev/null || echo "  ❌ sayaç okunamadı"
from data.database import win_rate_hesapla, toplam_pnl, acik_tradeler
w = win_rate_hesapla("PAPER")
a = acik_tradeler("PAPER")
print(f"  kapanmış : {w['toplam'] or 0} / 100")
print(f"  win rate : %{w['win_rate']}")
print(f"  PnL      : {toplam_pnl('PAPER'):+.2f} USDT")
print(f"  açık     : {len(a)}")
for t in a:
    print(f"    {t['sembol']} {t['yon']} @ {t['giris_fiyat']:.5f}")
PYEOF

baslik "6. VERİ BÜTÜNLÜĞÜ (test kirliliği var mı)"
sentetik=$("$PY" -c "
import sqlite3
c=sqlite3.connect('data/astra.db')
print(c.execute('SELECT COUNT(*) FROM trades WHERE giris_fiyat IN (63018.9,2000.6,0.50015)').fetchone()[0])
" 2>/dev/null || echo "?")
if [ "$sentetik" = "0" ]; then
    ok "sentetik fikstür fiyatlı işlem yok"
elif [ "$sentetik" = "?" ]; then
    uyari "kontrol edilemedi"
else
    hata "$sentetik adet test artefaktı işlem var — sayaç güvenilmez!"
fi

baslik "7. SON HATALAR (kalıcı teşhis kaydı)"
if [ -f logs/astra_onemli.log ]; then
    n=$(grep -c "CRITICAL" logs/astra_onemli.log 2>/dev/null || echo 0)
    echo "  CRITICAL satır sayısı: $n"
    tail -5 logs/astra_onemli.log 2>/dev/null | sed 's/^/    /' | cut -c1-120
else
    uyari "logs/astra_onemli.log yok — bot v57 öncesi kodla mı çalışıyor?"
fi

baslik "SONUÇ"
if [ "$HATA" -eq 0 ]; then
    echo "  ✅ Kritik sorun yok."
else
    echo "  ❌ $HATA kritik bulgu — yukarıyı inceleyin."
fi
exit "$HATA"
