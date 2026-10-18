# =========================================================
# ASTRA — Windows zamanlanmış görevini kurar
#
# Kullanım (depo kökünde, NORMAL PowerShell — yönetici GEREKMEZ):
#     powershell -ExecutionPolicy Bypass -File .\gorev_kur.ps1
#
# NEDEN VAR (2026-10-18):
#   Bilgisayar sıfırlanırsa kod GitHub'dan geri gelir ama Windows
#   zamanlanmış görevi GELMEZ. Botu 7/24 ayakta tutan tek mekanizma bu
#   görev: oturum açılışında başlatır ve 10 dakikada bir "hâlâ çalışıyor
#   mu?" diye bakar (baslat_bot.bat çift çalıştırmayı kendisi engeller).
#
#   DEVAM_NOTLARI bu görev hakkında defalarca uyarıyordu ("Enable
#   unutma" — 2026-08-21'de 14 saat veri kaybı) ama nasıl OLUŞTURULACAĞI
#   hiçbir yerde yazılı değildi. ASTRA_OrderBook'un komutu §-notlarda
#   vardı, ASTRA_Bot'unki yoktu.
#
#   Aşağıdaki tanım, çalışan makinedeki görevin dökümünden BİREBİR
#   alındı (Get-ScheduledTask, 2026-10-18):
#       eylem   : cmd.exe /c "<kök>\baslat_bot.bat"
#       tetik   : oturum açılışı + 10 dakikada bir tekrar
#       ayar    : pilde de çalış, süre sınırı yok, çakışırsa yenisini YOKSAY
#       yetki   : Interactive, Limited  (yönetici DEĞİL — bu yüzden
#                 Disable-ScheduledTask yönetici istemeden çalışır;
#                 ASTRA_OrderBook yönetici olarak kurulduğu için
#                 kapatılırken "Erişim engellendi" vermişti, §0.52)
#
# ⚠️ ÖNCE .env'i KUR. Görev 2 dakika içinde botu başlatır.
#   .env yoksa bot yine GÜVENLİ başlar (K-106: varsayılan testnet,
#   LIVE_TRADING=false) ama Telegram ve borsa erişimi olmaz.
#
# Parametreler:
#   -DevreDisi   görevi KAPALI oluşturur (başlatmaz). Önce kurup sonra
#                bilinçli olarak açmak istersen:
#                    Enable-ScheduledTask -TaskName ASTRA_Bot
#   -Ad          görev adı (varsayılan ASTRA_Bot; test için değiştirilir)
# =========================================================
param(
    [switch]$DevreDisi,
    [string]$Ad = "ASTRA_Bot"
)

$ErrorActionPreference = "Stop"
$kok = $PSScriptRoot
$bat = Join-Path $kok "baslat_bot.bat"

if (-not (Test-Path $bat)) {
    Write-Host "  [HATA] baslat_bot.bat bulunamadi: $bat" -ForegroundColor Red
    Write-Host "         Bu betigi depo KOKUNDE calistir." -ForegroundColor Red
    exit 1
}

$mevcut = Get-ScheduledTask -TaskName $Ad -ErrorAction SilentlyContinue
if ($mevcut) {
    Write-Host ("  [UYARI] '{0}' zaten var (durum: {1}) — uzerine yazilacak." -f $Ad, $mevcut.State) -ForegroundColor Yellow
}

$eylem = New-ScheduledTaskAction -Execute "cmd.exe" `
            -Argument ('/c "' + $bat + '"') -WorkingDirectory $kok

$t_oturum = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$t_tekrar = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
              -RepetitionInterval (New-TimeSpan -Minutes 10)

$ayar_arg = @{
    AllowStartIfOnBatteries    = $true
    DontStopIfGoingOnBatteries = $true
    ExecutionTimeLimit         = [TimeSpan]::Zero
    StartWhenAvailable         = $true
    MultipleInstances          = "IgnoreNew"
}
if ($DevreDisi) { $ayar_arg["Disable"] = $true }
$ayar = New-ScheduledTaskSettingsSet @ayar_arg

$kim = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $Ad -Action $eylem -Trigger $t_oturum, $t_tekrar `
    -Settings $ayar -Principal $kim -Force | Out-Null

# ── Doğrula: yazılanı değil, KAYITLI olanı oku ──
$g = Get-ScheduledTask -TaskName $Ad
Write-Host ""
Write-Host "  ============================================================"
Write-Host ("  Gorev kuruldu : {0}" -f $Ad)
Write-Host ("  Durum         : {0}" -f $g.State)
Write-Host ("  Eylem         : {0} {1}" -f $g.Actions[0].Execute, $g.Actions[0].Arguments)
Write-Host ("  Calisma dizini: {0}" -f $g.Actions[0].WorkingDirectory)
$g.Triggers | ForEach-Object {
    Write-Host ("  Tetik         : {0}  tekrar={1}" -f $_.CimClass.CimClassName, $_.Repetition.Interval)
}
Write-Host ("  Yetki         : {0} / {1}" -f $g.Principal.LogonType, $g.Principal.RunLevel)
Write-Host "  ============================================================"
if ($g.State -eq "Disabled") {
    Write-Host "  Gorev KAPALI. Baslatmak icin:"
    Write-Host ("      Enable-ScheduledTask -TaskName {0}" -f $Ad)
} else {
    Write-Host "  Gorev ACIK — bot en gec 2 dakika icinde baslar."
    Write-Host "  Durdurmak icin (SIRA ONEMLI — once Disable, yoksa 10 dk'da geri gelir):"
    Write-Host ("      Disable-ScheduledTask -TaskName {0}" -f $Ad)
    Write-Host ("      Stop-ScheduledTask    -TaskName {0}" -f $Ad)
}
Write-Host ""
