' =========================================================
'  ASTRA - Order book kaydedici GIZLI baslatici (v58)
'
'  NEDEN VAR:
'   Zamanlanmis gorev "ASTRA_OrderBook" 10 DAKIKADA BIR calisiyor
'   (watchdog: kaydedici olmusse yeniden baslatir). Gorev
'   LogonType=Interactive oldugu icin her tetiklemede EKRANDA cmd
'   penceresi acilip kapaniyordu - kullanici bunu bildirdi.
'
'   baslat_orderbook.bat zaten "zaten calisiyor mu" kontrolu yapip
'   hemen cikiyor; yani pencere cogu zaman bos yere aciliyordu.
'
'   Dogru cozum gorevi S4U (etkilesimsiz) yapmakti ama o YONETICI
'   yetkisi istiyor ("Erisim engellendi"). Bu sarmalayici ayni sonucu
'   yetkisiz verir: WScript.Shell.Run'in ikinci parametresi 0 =
'   pencereyi HIC gosterme.
'
'  DAVRANISI DEGISTIRMEZ: ayni .bat, ayni kontroller, ayni loglar.
'  Yalnizca pencere gizlenir.
' =========================================================
Dim kabuk, betikDizini
Set kabuk = CreateObject("WScript.Shell")
betikDizini = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
' 0 = gizli pencere, False = bitmesini bekleme
kabuk.Run """" & betikDizini & "\baslat_orderbook.bat""", 0, False
