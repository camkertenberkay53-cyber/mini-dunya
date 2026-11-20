# LOJİSTİK KAOS 🚛

Limanda konuşan tırlar, konteynerler, gemiler ve evraklar. Lojistik dünyasının animasyon sitcom'u.
Bu depo, YouTube kanalı için her gün kendi kendine bölüm **yazan, seslendiren, çizen ve yükleyen** bottur.

- **Her gün 3 Shorts:** 08:30 ana hikâye, 13:30 bağımsız skeç, 19:30 ana hikâye
- **Haftada 2 uzun video:** Çarşamba ve pazar 18:00, 6–7 dakika, yatay
- **Senaryo:** Google Gemini (ücretsiz katman). Evren kitabı, sezon planı ve hikâye hafızasıyla yazılır, kalite kontrolünden geçer.
- **Ses:** Gemini TTS. Kota biterse Microsoft Edge seslerine, o da olmazsa yerel Piper seslerine geçer.
- **Animasyon:** Tamamen kodla çizilir (`kaos/engine`). Dış görsel servisi gerekmez.
- **Maliyet:** 0 TL. GitHub Actions, Gemini ücretsiz katmanı ve YouTube API ücretsiz.

## Klasörler
| Klasör | İçerik |
|---|---|
| `evren/evren.md` | Karakterler, kişilikler, sabit laflar, mekânlar, sektör olay havuzu. **Bot her bölümde bunu okur.** |
| `evren/sezonNN.yaml` | 14 günlük sezon planı. Sezon bitince bot yenisini kendisi yazar. |
| `state/hafiza.json` | Hikâye hafızası: yayınlanan bölümler, açık meseleler, izlenme verileri |
| `episodes/` | Yayınlanan her bölümün senaryosu |
| `config.yaml` | Yayın, gizlilik ve karakter sesi ayarları |

## Kurulum (bir kez)

### 1) Gemini anahtarı
**Settings → Secrets and variables → Actions → New repository secret**
- Name: `GEMINI_API_KEY`
- Secret: Google AI Studio'dan aldığın anahtar

### 2) İlk test
**Actions → Lojistik Kaos Bot → Run workflow → görev: `test` → Run workflow**
Birkaç dakika sonra çalışmanın sayfasının en altında **Artifacts** bölümünde video çıkar, indirip izle.
Bu test YouTube'a yüklemez.

### 3) Ses kataloğu
**Run workflow → görev: `katalog`** ile her karakterin aday seslerini dinle. Beğendiğin harfleri söyle, `config.yaml` güncellensin.

### 4) YouTube bağlantısı
1. https://console.cloud.google.com adresinde üstten **lojistik-kaos** projesini seç.
2. **APIs & Services → Library** bölümünde **YouTube Data API v3**'ü bul ve **Enable** de.
3. **Google Auth Platform (OAuth consent screen)** bölümünde:
   - User type: **External**, uygulama adı: `Lojistik Kaos Bot`, e-postan
   - **Audience** sayfasında **Publish app** ile durumu **In production** yap. Test modunda kalırsa bağlantı 7 günde bir kopar.
4. **Clients (Credentials) → Create client → Web application**
   - Authorized redirect URI: `https://developers.google.com/oauthplayground`
   - Çıkan **Client ID** ve **Client secret**'ı kaydet.
5. https://developers.google.com/oauthplayground adresinde:
   - Sağ üstteki ⚙️ simgesinden **Use your own OAuth credentials** seç, Client ID ve secret'ı yapıştır.
   - Sol kutuya şunu yaz: `https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly` → **Authorize APIs**
   - Kanalın olduğu Google hesabını seç. "Doğrulanmamış uygulama" uyarısında **Gelişmiş → devam et** de.
   - **Exchange authorization code for tokens** de ve çıkan **Refresh token**'ı kopyala.
6. GitHub Secrets'a şu üçünü ekle: `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`

Bundan sonra bot her gün kendiliğinden çalışır.

## Elle çalıştırma
**Actions → Run workflow** ile istediğin zaman `sabah`, `oglen`, `aksam` ya da `uzun` bölümü üretebilirsin.

## Ayarlar
- `config.yaml → yayin.gizlilik`: `public` (hemen yayın), `private` (gizli yükle, sen açarsın)
- `config.yaml → voices`: karakter sesleri
- `evren/evren.md`: karakterleri ve dünyayı değiştirmek için burayı düzenle; bot bir sonraki bölümde yeni hâliyle yazar.

## Yerelde çalıştırma
```
pip install -r requirements.txt
GEMINI_API_KEY=... python -m kaos.main --slot sabah --no-upload
python -m kaos.main --json episodes/0001_x.json --no-upload   # hazır senaryodan
```

Yazı tipi: Baloo 2 (SIL Open Font License, `assets/fonts/OFL.txt`).
