@echo off
REM =========================================================
REM  ASTRA v57 - Windows bot baslatici
REM
REM  Zamanlanmis gorev "ASTRA_Bot" tarafindan oturum acilisinda
REM  calistirilir. Elle de calistirilabilir.
REM
REM  NEDEN VAR:
REM   Bot yeniden baslatmadan sag cikmiyordu. 2026-08-20'de baslatilan
REM   surec makine kapaninca oldu ve ~14 saat veri kaybi olustu.
REM   100 kapanmis paper islem hedefi (CANLI_GECIS_PROTOKOLU.md Asama 1)
REM   botun surekli calismasini gerektiriyor.
REM
REM  CIFT CALISTIRMA KORUMASI:
REM   Ayni DB'ye iki bot yazarsa paper sayaci ve bakiye bozulur.
REM   Python tarafinda tek-instance kilidi YOK, o yuzden burada kontrol
REM   ediliyor. Zaten calisan bir "main.py bot" varsa bu betik cikar.
REM =========================================================

cd /d "%~dp0"

REM --- Zaten calisiyor mu? (PowerShell: wmic Win11'de guvenilmez) ---
REM  Calisan bir "main.py bot" varsa exit 1 doner.
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Get-CimInstance Win32_Process -Filter \"name='python.exe'\" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*main.py bot*' }) { exit 1 } else { exit 0 }"
if errorlevel 1 (
    echo [ASTRA] Zaten calisan bir bot var - yeni instance baslatilmadi.
    exit /b 0
)

REM --- Log dizini ---
if not exist "logs" mkdir "logs"

REM --- UTF-8 zorla (Windows/Turkce locale cp1254 sorunu icin) ---
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

echo [ASTRA] Bot baslatiliyor: %DATE% %TIME%
echo [ASTRA] BASLADI %DATE% %TIME% >> "logs\bot_yasam_dongusu.log"

python -X utf8 main.py bot >> "logs\bot_autostart.log" 2>&1

REM v57: CIKIS KODUNU KAYDET.
REM  2026-08-26 04:27'de bot SESSIZCE oldu: log sustu, traceback yok, Windows
REM  cokme kaydi yok, watchdog hic konusmadi. Sebep TESPIT EDILEMEDI cunku
REM  surecin nasil sonlandigina dair hicbir iz yoktu. Zaman cizelgesi:
REM    04:27:54  son log satiri (Optuna XGB sirasinda sustu)
REM    04:37:10  gorev tetiklendi, YENI BOT BASLATMADI -> surec hala ayaktaydi
REM    04:47:10  gorev tetiklendi, bot yoktu -> yeniden baslatti
REM  Yani cokmedi, ASILDI; sonra 04:37-04:47 arasinda oldu.
REM
REM  Cikis kodu bunu ayirt eder:
REM    0           = temiz cikis
REM    1           = Python istisnasi
REM    -1073741819 = 0xC0000005 access violation -> C uzantisinda cokme
REM    -1073741510 = 0xC000013A harici sonlandirma / Ctrl+C
REM    143 veya 15 = SIGTERM (watchdog kendini oldurmus olabilir)
echo [ASTRA] BITTI  %DATE% %TIME% cikis_kodu=%ERRORLEVEL% >> "logs\bot_yasam_dongusu.log"
