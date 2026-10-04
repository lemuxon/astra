# PuTTY ile Kurulum — Windows Tarafı Adımları

> `KURULUM.md` sunucu tarafını anlatır ve **aynen geçerlidir**.
> Bu belge yalnızca Windows tarafındaki farkları kapsar: PuTTY anahtar
> üretimi, dosya transferi, oturum ayarları.
>
> Sunucuda çalıştıracağınız komutları PuTTY penceresine **sağ tıkla**
> yapıştırabilirsiniz (PuTTY'de Ctrl+V çalışmaz).

---

## Gereken araçlar

PuTTY paketi zaten hepsini içerir:

| Araç | Ne için |
|---|---|
| `putty.exe` | SSH oturumu |
| `puttygen.exe` | Anahtar üretimi |
| `pscp.exe` | Dosya transferi (komut satırı) |
| **WinSCP** (ayrı, isteğe bağlı) | Sürükle-bırak dosya transferi — daha kolay |

---

## 1. ÖNCE: root parolasını değiştirin

PuTTY ile bağlanın (`<SUNUCU_IP>`, port 22, kullanıcı `root`), sonra:

```bash
passwd
```

⚠️ Sohbete yapıştırılan parola **yanmış sayılır**. Yeni parolayı hiçbir
yere yazmayın, kimseyle paylaşmayın.

---

## 2. Anahtar üretimi (PuTTYgen)

1. `puttygen.exe` çalıştırın
2. **Type of key**: `EdDSA` → `Ed25519` seçin (yoksa RSA 4096)
3. **Generate** — fare imlecini pencerede gezdirin
4. **Key passphrase** girin (boş bırakmayın; anahtar çalınırsa tek koruma budur)
5. **Save private key** → `C:\Users\<KULLANICI>\.ssh\astra.ppk`
6. Üstteki **"Public key for pasting into OpenSSH authorized_keys file"**
   kutusundaki metnin TAMAMINI kopyalayın (tek satırdır, `ssh-ed25519 AAAA...`
   diye başlar)

⚠️ "Save public key" düğmesiyle kaydedilen dosya **farklı formattadır** ve
`authorized_keys` için kullanılmaz. Kutudaki metni kopyalayın.

---

## 3. Açık anahtarı sunucuya kurun

PuTTY oturumunda (parola ile girmişken):

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
nano ~/.ssh/authorized_keys
```

Kopyaladığınız satırı **sağ tıkla** yapıştırın → `Ctrl+O`, `Enter`, `Ctrl+X`.

```bash
chmod 600 ~/.ssh/authorized_keys
```

---

## 4. PuTTY oturumunu anahtarla ayarlayın

1. PuTTY → **Session**: Host `<SUNUCU_IP>`, Port `22`
2. **Connection → Data** → Auto-login username: `root`
3. **Connection → SSH → Auth → Credentials** → Private key file: `astra.ppk`
4. **Session**'a dönün → Saved Sessions: `astra` yazın → **Save**

Şimdi **Load → Open** ile parola sormadan (yalnızca anahtar passphrase'i
sorarak) girebilmelisiniz.

---

## 5. Parola girişini kapatın

⚠️ **Yalnızca 4. adım çalıştıysa yapın.** Anahtar çalışmıyorken parolayı
kapatırsanız sunucuya erişimi kaybedersiniz. (Contabo panelinden konsol
erişimi var ama uğraştırır.)

```bash
sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#*PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
sshd -t && systemctl restart ssh && echo "parola girisi KAPATILDI"
```

`sshd -t` yapılandırmayı test eder; hata varsa restart yapılmaz.

**Test:** Mevcut PuTTY penceresini KAPATMADAN yeni bir pencere açıp
girebildiğinizi doğrulayın.

---

## 6. Dosya transferi

Arşiv hazır: **`astra_kurulum.tar.gz`** (0.4 MB, proje kökünde).
İçinde `.env` ve veritabanı **yok** — doğrulandı.

### Seçenek A — WinSCP (kolay)
1. WinSCP'yi açın, PuTTY'de kaydettiğiniz `astra` oturumunu seçin
2. Sol panelde `C:\Users\<KULLANICI>\Desktop\astra_v55` klasörüne gidin
3. `astra_kurulum.tar.gz` dosyasını sağ panelde `/tmp/` içine sürükleyin

### Seçenek B — pscp (komut satırı)
Windows'ta PowerShell veya CMD açın:

```
pscp -i C:\Users\<KULLANICI>\.ssh\astra.ppk C:\Users\<KULLANICI>\Desktop\astra_v55\astra_kurulum.tar.gz root@<SUNUCU_IP>:/tmp/
```

---

## 7. Sunucuda açın

```bash
mkdir -p /opt/astra
tar -xzf /tmp/astra_kurulum.tar.gz -C /opt/astra
rm /tmp/astra_kurulum.tar.gz
ls /opt/astra
```

Buradan sonrası **`KURULUM.md` §1'den itibaren** aynen geçerli:
sistem paketleri, `astra` kullanıcısı, venv, `.env`, systemd, doğrulama.

---

## 8. PuTTY'ye özel iki not

### 8.1 Oturum kapanınca bot ölmez
`systemd` ile kurduğunuz için bot PuTTY oturumundan **bağımsız** çalışır.
PuTTY'yi kapatmak botu etkilemez.

⚠️ Ama botu **elle** başlatırsanız (`python main.py bot`) oturum kapanınca
ölür. Bu yüzden `baslat.sh` `screen` kullanıyordu. **systemd varken elle
başlatmayın:**
```bash
systemctl start astra      # doğru
systemctl status astra
```

### 8.2 Panele erişim — PuTTY tüneli
Panelde kimlik doğrulama **yok** (`PANEL_USER`/`PANEL_PASS` boş), o yüzden
8080 portunu dışarı açmayın. PuTTY ile tünel kurun:

1. PuTTY → **Connection → SSH → Tunnels**
2. Source port: `8080`
3. Destination: `127.0.0.1:8080`
4. **Add** → Session'a dönüp **Save**

Bağlandıktan sonra tarayıcıda: `http://127.0.0.1:8080`

---

## 9. Kurulum bitince

```bash
sudo -u astra bash /opt/astra/sunucu/dogrula.sh
```

Bu betik salt-okunur: servis, süreç, `LIVE_TRADING`, `CHAT_ID`, panel portu,
sayaç ve **test kirliliği** kontrolü yapar. Çıktıyı bana yapıştırırsanız
sorun varsa birlikte bakarız.

---

## 10. Asistan sunucuyu nasıl görecek?

PuTTY sizin aracınız; ben oradan otomatik bir şey göremem. İki yol:

**a) Çıktı yapıştırma (kurulum gerektirmez).** `dogrula.sh` çıktısını veya
log parçalarını bana yapıştırırsınız, ben yorumlarım.

**b) OpenSSH anahtarı (bir kerelik ek adım).** Bu makinede ayrıca OpenSSH
anahtarı kurarsanız, oturumlarımızda sunucuya doğrudan salt-okunur teşhis
komutları çalıştırabilirim:
```bash
ssh-keygen -t ed25519 -C "astra-claude" -f "$HOME/.ssh/id_ed25519"
```
Sonra bu anahtarın `.pub` içeriğini de sunucudaki `~/.ssh/authorized_keys`
dosyasına eklersiniz (PuTTY anahtarınızın yanına, alt satır olarak).

PuTTY'nin `.ppk` formatı OpenSSH ile doğrudan çalışmaz — bu yüzden ayrı
anahtar gerekir. İsterseniz PuTTYgen ile `.ppk`'yı OpenSSH formatına da
dönüştürebilirsiniz: **Conversions → Export OpenSSH key**.

**Her hâlükârda 7/24 izleme Telegram'dadır** — ben oturumlar arasında
sunucuyu izlemem.
