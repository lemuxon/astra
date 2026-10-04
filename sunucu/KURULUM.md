# ASTRA — Contabo Sunucu Kurulumu

> Hedef: paper veri toplamayı 7/24 çalıştırmak. Yerel laptopta darboğaz
> makine uptime'ıydı (ölçüm: ortalama 1.8 saat/gün). Sunucuda bu sorun kalkar.
>
> **Bu belgede hiçbir gizli değer YOK ve olmamalı.** API anahtarı, parola,
> token gibi değerleri sunucuda **siz** girersiniz.

---

> **PuTTY kullanıyorsanız:** Windows tarafındaki adımlar (anahtar üretimi,
> dosya transferi, tünel) için önce **`PUTTY_ADIMLARI.md`** okuyun.
> Bu belgedeki *sunucu* komutları PuTTY ile de aynen geçerlidir.

---

## 0. ÖNCE GÜVENLİK (atlanmaz)

### 0.1 Root parolasını değiştirin
Parola sohbete yapıştırıldıysa **yanmış sayılır** (`DEVAM_NOTLARI` §4.4).
Ayrıca public IP + root + parola ile SSH, internetteki en çok saldırılan
kombinasyondur.

```bash
ssh root@<SUNUCU_IP>
passwd
```

### 0.2 Anahtar tabanlı girişe geçin
Yerel makinede:
```bash
ssh-keygen -t ed25519 -C "astra-deploy" -f "$HOME/.ssh/id_ed25519"
ssh root@<SUNUCU_IP> "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys" < "$HOME/.ssh/id_ed25519.pub"
```

Anahtarla girebildiğinizi **doğrulayın**, sonra parolayı kapatın:
```bash
ssh root@<SUNUCU_IP> "sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/; s/^#*PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config && systemctl restart sshd"
```

⚠️ Sırayı bozmayın — anahtar çalışmadan parolayı kapatırsanız kilitlenirsiniz.

### 0.3 Güvenlik duvarı — yalnızca SSH
```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw enable
ufw status
```

**Panel portunu (8080) AÇMAYIN.** Sebep §5'te.

---

## 1. Sistem hazırlığı

```bash
apt update && apt upgrade -y
apt install -y python3 python3-venv python3-pip git build-essential
```

Bot'u kendi kullanıcısıyla çalıştırın (root ile çalıştırmayın):
```bash
adduser --system --group --home /opt/astra astra
```

---

## 2. Kodu taşıma

Yerel makineden (proje kökünde):

```bash
# .env ve veri DIŞARIDA — onlar ayrı ele alınır
tar --exclude='.env' --exclude='__pycache__' --exclude='logs' \
    --exclude='data/*.db*' --exclude='.coverage' \
    -czf astra.tar.gz .

scp astra.tar.gz root@<SUNUCU_IP>:/tmp/
```

Sunucuda:
```bash
mkdir -p /opt/astra && tar -xzf /tmp/astra.tar.gz -C /opt/astra
chown -R astra:astra /opt/astra
rm /tmp/astra.tar.gz
```

---

## 3. Python ortamı

```bash
cd /opt/astra
sudo -u astra python3 -m venv venv
sudo -u astra venv/bin/pip install --upgrade pip
sudo -u astra venv/bin/pip install -r requirements.txt
```

---

## 4. `.env` — gizli değerleri SİZ girin

```bash
cp /opt/astra/.env.example /opt/astra/.env
chmod 600 /opt/astra/.env
chown astra:astra /opt/astra/.env
nano /opt/astra/.env
```

`.env.example` tüm anahtarları açıklamalarıyla içerir. Kritik olanlar:

| Anahtar | Not |
|---|---|
| `BINANCE_API_KEY` / `BINANCE_API_SECRET` | Sunucuya özel YENİ anahtar üretin |
| `BOT_TOKEN` | Telegram bot token |
| `CHAT_ID` | **Boş bırakmayın** — boşsa komut yetkilendirmesi devre dışı kalır (v56 kritik bulgusu) |
| `LIVE_TRADING` | Paper aşamasında **`false`** |
| `PANEL_USER` / `PANEL_PASS` | İkisi de dolu ya da ikisi de boş (yarım yapılandırma botu başlatmaz) |

**Kimlik bilgilerini sohbete yapıştırmayın.**

---

## 5. Panel — dışarı AÇMAYIN

Şu an `PANEL_USER` ve `PANEL_PASS` **boş**, yani panelde kimlik doğrulama
yok. Panel üzerinden pozisyon kapatma gibi işlemler yapılabiliyor
(v56'da tam bu yüzden `0.0.0.0` yerine `127.0.0.1`'e çekilmişti).

Sunucuda panele erişmek isterseniz **SSH tüneli** kullanın — port açmayın:

```bash
# Yerel makinede çalıştırın, sonra tarayıcıda http://127.0.0.1:8080
ssh -L 8080:127.0.0.1:8080 root@<SUNUCU_IP>
```

Paneli gerçekten dışarı açacaksanız **önce** `PANEL_USER`/`PANEL_PASS`
tanımlayın; aksi halde token'ı bilen herkes komut çalıştırabilir.

---

## 6. Servisi kur

```bash
cp /opt/astra/sunucu/astra.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now astra
systemctl status astra --no-pager
```

**Neden systemd önemli:** `engines/watchdog.py` 3 alarmdan sonra kendini
`SIGTERM` ile öldürüyor ve systemd'nin geri getirmesini bekliyor. Windows'ta
systemd olmadığı için zamanlanmış görevle çözüm uydurulmuştu (10 dk'ya kadar
kayıp). Burada 10 saniyede geri gelir.

---

## 7. Doğrulama (kurulumdan sonra ŞART)

```bash
cd /opt/astra
sudo -u astra venv/bin/python testleri_calistir.py
```
Beklenen: `✅ TÜM TESTLER BAŞARILI` (178 test).

Testler üretim verisine **yazmaz** (v57 izolasyonu). Doğrulamak için:
```bash
grep -c '63018\.9' logs/astra.log        # koşu öncesi/sonrası AYNI olmalı
```

Servis sağlığı:
```bash
systemctl status astra --no-pager
journalctl -u astra -n 50 --no-pager
tail -f /opt/astra/logs/astra_onemli.log     # WARNING+ kalıcı kayıt
```

Sayaç:
```bash
cd /opt/astra && sudo -u astra venv/bin/python -c "from data.database import win_rate_hesapla, toplam_pnl; w=win_rate_hesapla('PAPER'); print(w['toplam'] or 0, toplam_pnl('PAPER'))"
```

---

## 8. Veri taşıma (isteğe bağlı)

Yerelde sayaç **0/100 + 1 açık pozisyon**. İki seçenek:

**a) Temiz başla (önerilen):** Hiçbir şey taşımayın. Sunucuda sayaç 0'dan
başlar; yereldeki açık pozisyon zaten sunucuda karşılığı olmayan bir kayıt.

**b) Taşı:** Yerel botu durdurun, sonra:
```bash
scp data/astra.db data/journal.db root@<SUNUCU_IP>:/opt/astra/data/
ssh root@<SUNUCU_IP> "chown astra:astra /opt/astra/data/*.db"
```
Bot yeniden başlarken bakiyeyi DB'den türetir (`_bakiye_hesapla`), yani
açık pozisyon ve PnL korunur.

⚠️ İki bot AYNI ANDA çalışmasın — yereldeki zamanlanmış görevi kaldırın:
```powershell
Unregister-ScheduledTask -TaskName ASTRA_Bot -Confirm:$false
```

---

## 9. Saat dilimi

DB zaten UTC yazıyor. Sunucu saatini UTC'de bırakmak log okumayı kolaylaştırır:
```bash
timedatectl set-timezone UTC
timedatectl
```
Yerel logda saatler TSS (UTC+3) idi; sunucuda UTC olacak. Karşılaştırma
yaparken bunu unutmayın.

---

## 10. Kurulum sonrası — bilinmesi gerekenler

- **Bot artık 7/24 çalışır.** Ölçülen tempo: 12 saatte ~1 pozisyon →
  100 işlem ≈ **50 gün**. Sunucu bunu hızlandırmaz, sadece kesintiyi bitirir.
- **Telegram sizin izleme kanalınız.** Asistan oturumlar arasında sunucuyu
  izlemez; alarmları Telegram taşır.
- **`logs/astra_onemli.log`** teşhis için ilk bakılacak yer — `astra.log`
  4 saatte bir dönüyor.
- Canlıya geçmeden önce `DEVAM_NOTLARI.md` §3'teki iki engel duruyor:
  Binance `-4120` ve 100 paper işlemi.
