@echo off
setlocal
REM =========================================================
REM  ASTRA - ASTRA_OrderBook gorevini GIZLI calistirmaya cevir
REM
REM  KULLANIM: Bu dosyaya SAG TIK -> "Yonetici olarak calistir"
REM            (ya da cift tikla; UAC izni kendisi ister)
REM
REM  NEDEN GEREKLI:
REM   ASTRA_OrderBook gorevi 10 DAKIKADA BIR baslat_orderbook.bat
REM   calistiriyor ve gorev LogonType=Interactive oldugu icin her
REM   seferinde ekranda cmd penceresi acilip kapaniyor.
REM
REM   Kaydedici UZUN OMURLU bir dongu (olculdu: PID tek, saatlerce
REM   ayakta). Yani 10 dakikalik gorev sadece WATCHDOG - her tetiklemede
REM   "zaten calisiyor" deyip cikiyor ve pencereyi BOSUNA aciyor.
REM
REM   Bu betik gorevin EYLEMINI baslat_orderbook_gizli.vbs'e cevirir.
REM   O sarmalayici ayni .bat'i WScript.Shell.Run(...,0,False) ile,
REM   yani pencere HIC gostermeden calistirir.
REM
REM  NE DEGISMEZ: tetikleyiciler (logon + 10dk), calisan kaydedici,
REM   toplanan veri, loglar. Yalnizca pencere gizlenir.
REM
REM  GERI ALMAK ICIN (yonetici PowerShell):
REM   $a = New-ScheduledTaskAction -Execute "C:\Users\<KULLANICI>\Desktop\astra_v55\baslat_orderbook.bat" -WorkingDirectory "C:\Users\<KULLANICI>\Desktop\astra_v55"
REM   Set-ScheduledTask -TaskName ASTRA_OrderBook -Action $a
REM =========================================================

cd /d "%~dp0"

REM --- Yonetici mi? Degilse kendini yukselterek yeniden baslat ---
net session >nul 2>&1
if errorlevel 1 (
    echo [ASTRA] Yonetici yetkisi gerekiyor - izin penceresi aciliyor...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b 0
)

echo.
echo ============================================================
echo   ASTRA_OrderBook gorevi GIZLI calistirmaya ceviriliyor
echo ============================================================
echo.

if not exist "baslat_orderbook_gizli.vbs" (
    echo [HATA] baslat_orderbook_gizli.vbs bulunamadi.
    echo        Bu betik proje kokunden calistirilmali.
    pause
    exit /b 1
)

REM --- 2026-09-21: baslat_orderbook.bat GECICI OLARAK KENARA ALINMISTI ---
REM  Yonetici yetkisi olmadan pencereyi durdurmanin tek yolu, gorevin
REM  cagirdigi dosyayi yerinden almakti (gorev baslatamaz -> pencere yok).
REM  Bu betik dogru cozumu uyguladigi icin asil dosyayi geri koyar;
REM  aksi halde .vbs sarmalayici olmayan bir .bat'i cagirirdi.
if exist "_baslat_orderbook_ASIL.bat" (
    if not exist "baslat_orderbook.bat" (
        echo [ASTRA] baslat_orderbook.bat geri konuyor...
        move /y "_baslat_orderbook_ASIL.bat" "baslat_orderbook.bat" >nul
    )
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$vbs = Join-Path '%~dp0' 'baslat_orderbook_gizli.vbs';" ^
  "$a = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument ('\"' + $vbs + '\"') -WorkingDirectory '%~dp0'.TrimEnd('\');" ^
  "try { Set-ScheduledTask -TaskName ASTRA_OrderBook -Action $a -ErrorAction Stop | Out-Null; Write-Host '[OK] Gorev eylemi degistirildi.' } catch { Write-Host ('[HATA] ' + $_.Exception.Message); exit 1 }"

if errorlevel 1 (
    echo.
    echo [HATA] Degistirilemedi. Yonetici olarak calistirildigindan emin ol.
    pause
    exit /b 1
)

echo.
echo --- DOGRULAMA ---
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$t = Get-ScheduledTask -TaskName ASTRA_OrderBook;" ^
  "Write-Host ('  Durum : ' + $t.State);" ^
  "$t.Actions | ForEach-Object { Write-Host ('  exec  : ' + $_.Execute); Write-Host ('  args  : ' + $_.Arguments) };" ^
  "$t.Triggers | ForEach-Object { Write-Host ('  tetik : ' + $_.CimClass.CimClassName + '  tekrar=' + $_.Repetition.Interval) };" ^
  "$p = @(Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | Where-Object { $_.CommandLine -like '*orderbook_kaydedici*' });" ^
  "Write-Host ('  kaydedici surec: ' + $p.Count)"

echo.
echo ============================================================
echo   TAMAM. Bundan sonra cmd penceresi ACILMAYACAK.
echo   Veri toplama ve otomatik yeniden baslatma DEVAM EDER.
echo ============================================================
echo.
pause
