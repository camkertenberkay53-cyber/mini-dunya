# Otonom Belgesel Fabrikası — Hedef Mimari

> Kalıcı referans belgesi. Faz-53A A2 kapanışından sonra (commit `d2435b3`) yazıldı.
> Her bölümde **hedef** (bağlayıcı kural) ve **bugünkü durum** (kodda gerçekten olan) ayrı ayrı yazılıdır.
> Bugünkü durumu hedef gibi göstermek yasaktır; bir aşama ancak ölçümle ve testle doğrulanınca "var" sayılır.

## 0. Değişmez ilkeler

- **0 TL:** Ücretli API, ücretli model ya da ücretli bulut kullanılmaz. Ücretsiz katmanlı servislerin anahtarları depoda
  saklanmaz ve kodda yazılmaz (yalnızca ortam değişkeni ya da CI gizli değişkeni).
- **Tahribatsız gelişim:** Çalışan sistem yeniden yazılmaz. Yeni davranış isteğe bağlı girdi ya da tek anahtarla gelir
  ve tek anahtarla geri alınır. Korunan alanlar şunlar: Shorts planlayıcı, 3D önbellek anahtarları, `kaos/sinema/*`,
  `kurgu.py`, `harita.py`, çalışan render hatları. Bunlar regresyon testleriyle kilitlidir.
- **Test dürüstlüğü:** Test silinmez, eşik düşürülmez, başarısızlık "skip" ile gizlenmez.
- **Render'a göre karar:** Sadece testlerin geçmesi yetmez; karar kare/pano görüntüsüne bakılarak verilir.
- **Konudan bağımsız motor:** `motor/uretim` kodunda konu adı geçmez. Konuya özgü her şey veri ve kural dosyalarındadır.
- **Lisans kapısı:** Yalnızca CC0, PD-Old ve PD-Art serbesttir. CC-BY* ancak `atif` alanıyla kullanılır. Her görselin
  SHA-256 kaydı ve edinim kaydı (`onay`) vardır; otomatik edinim `insan_onayi: false` olarak açıkça işaretlenir.

## 1. Tek girdi, tam otonom akış

**Hedef:** Kullanıcı yalnızca tarihî bir konu başlığı girer. Sistem aşağıdaki hattı insan müdahalesi olmadan yürütür.

```
konu başlığı
  → araştırma (kaynaklı kartlar, iddia→kaynak izi)
  → senaryo (kurallara uygunluk denetimi, geri beslemeli yeniden yazım)
  → seslendirme ölçümü (gerçek süre) → sahne bölücü → ritim planlayıcı (bkz. §4)
  → görsel toplama + lisans kapısı + özne/tür tespiti (bkz. §3)
  → sahne üretimi: 2.5D tarihî görsel | taktik harita | 3D/Godot
  → sinematik bütünlük (renk, atmosfer) + ses tasarımı (bkz. §5)
  → kurgu → kalite kontrol (teknik QC + içerik denetimleri)
  → zamanlanmış YouTube yüklemesi
```

| Aşama | Modül | Bugünkü durum |
|---|---|---|
| Araştırma | `motor/uretim/arastirma.py`, `motor/orkestrasyon/senaryo_planlayici.py` | Shorts kart denetimi var. Orkestrasyon (Faz-55'ten itibaren gerçek kipte araştırma = dış kaynak keşfi + canlı doğrulama; LLM hafızası kabul edilmez): araştırma → bilgi havuzu (doğrulanmış/tartışmalı/belirsiz, kronoloji, çelişki) → anlatı → sahne planı → Validation Gate (en çok 3 deneme, hedefli onarım, fail-safe). **Yalnızca `MockLLMProvider` ile çalışır**; gerçek (ücretsiz) LLM sağlayıcısı bağlı değil. |
| Senaryo | `motor/uretim/senaryo_uretici.py` | Shorts için var (ücretsiz Gemini, `GEMINI_API_KEY` gerekir, yoksa açıkça durur). Uzun format yok. |
| Seslendirme ölçümü | `motor/uretim/seslendirme.py` | Var (Piper yerel; yayın sırası Gemini→Edge→Piper). |
| Sahne bölücü / plan | `sahne_bolucu.py`, `planlayici.py`, `uretim_hatti.py` | Shorts için var; uzun format ritim planlayıcısı yok. |
| Görsel toplama | `motor/varlik/commons_toplayici.py`, `tarihi_gorsel.py` | Var (Commons, ≥2000 px, lisans kaydı, SHA-1/256). Özne tespiti el ile; `ozne_tespit.py` Faz-53B'de. |
| 2.5D | `motor/uretim/gorsel25d.py` + `kaos/sinema` | Var (Faz-53A A2: maske, dolgu, tam/sınırlı/kenburns, tuval). |
| Harita | `motor/uretim/harita.py` | Var. |
| 3D | `motor/uretim/render.py` (Godot) | Var; 3D sınırları Faz-52 kapanışında kayıtlı. |
| Kurgu | `motor/uretim/kurgu.py` | Shorts için var; uzun format ve ses tasarımı katmanları yok. |
| QC | `kaos/qc.py` | Teknik QC var (FFmpeg + OpenCV). |
| Yükleme | `kaos/youtube.py` | YouTube Data API v3 yüklemesi var; yeni hatta bağlı değil. |

## 2. Aşamalı üretim kapasitesi

1. **Aşama 1 — Uçtan uca doğrulama:** Tek bir konu başlığından tek bir **15 dakikalık** belgesel üretilir. Hat şudur:
   araştırma → senaryo → 15 dk sahne planı → otomatik görsel toplama → 2.5D/3D/harita → seslendirme/kurgu → kalite kontrol.
   Hiçbir adımda insan müdahalesi olmaz. Hedef çıktı "kusursuz"dur; bu da ölçülebilir kapılarla tanımlanır:
   - Teknik QC'de kritik hata sıfır.
   - Senaryonun her cümlesinin kaynak izi tam.
   - Her görselin lisans kaydı tam.
   - Fallback'e düşen sahneler raporlanmış.
   - Son izleme insan gözüyle onaylanır; bu bir doğrulama adımıdır, üretim adımı değildir.
2. **Aşama 2 — Seri üretim:** Aşama 1 başarılı olduktan sonra başlar. Tempo haftada 2 adet 15–20 dk belgesel ve her gün
   1 adet 50–60 sn Shorts. Aşama 1 doğrulanmadan Aşama 2'ye geçilmez.

## 3. Otonom arşiv ve güven skorlu özne tespiti

- `commons_toplayici.py` açık kaynak API'lerden (ilk kaynak Wikimedia Commons) ≥2000 px eserleri indirir. Lisans,
  SHA-256 ve edinim kaydını oluşturur; görsel ikili dosyaları depoya girmez.
- `ozne_tespit.py` iki **bağımsız** soruyu yanıtlar:
  1. **Görsel türü:** portre, mimari, minyatür, harita, belirsiz.
  2. **Özne kutusu:** Çok figürlü kompozisyonlar tek bir dar kutuya sıkıştırılmaz.
- **Güven skoru gerçek ölçümden gelir:** yüz algılama tutarlılığı, kontur/kompozisyon ölçüleri, kenar yoğunluğu. Sabit
  değer yazılmaz.
- **Semantik sınır:** OpenCV bir figürün kim olduğunu ya da sahnenin ana karakterinin hangisi olduğunu bilemez. Bu yüzden
  `tespit_durumu` alanı tahmini tahmin olarak etiketler: `kesin_yuz`, `geometrik_tahmin`, `belirsiz_fallback`.
- **Güvenli fallback:** Düşük güvende kutu, tam görseli kapsayan tam kadrajdır ve önerilen seviye `kenburns`'tür. Tespit
  hatası toplama ya da üretim sürecini durdurmaz.

## 4. İzleyici tutma odaklı sahne ritim planlayıcısı

- **Uzun video (15–20 dk):**
  - Sahne süresi **6–12 sn**.
  - Karışım hedefi: stratejik harita ~%40, 2.5D tarihî görsel ~%40, 3D/Godot ~%20. Bu oranlar dinamiktir; içerik ve
    kullanılabilir varlık izin verdiği kadar uygulanır ve sapma raporlanır.
  - Aynı türden sahneler uzun süre art arda gelmez.
- **Günlük Shorts (50–60 sn):** İlk **3 sn** durağan harita olamaz. Hareketli bir 2.5D karakter ya da aksiyon sahnesi ve
  güçlü bir görsel kanca ile açılır.
- **Bugünkü durum:** Mevcut Shorts planı korunur. Ritim planlayıcısı yeni, ayrı ve anahtarlı bir katman olarak eklenir;
  mevcut planlarda byte düzeyinde değişiklik olmaz.

## 5. Sinematik bütünlük ve ses tasarımı

- Tüm kaynaklar (2.5D, harita, 3D) ortak renk tonlamasından ve atmosferik efektlerden geçer (`kaos/sinema`, Faz-52 renk
  profilleri ve ışık ön ayarları).
- Kurgu hattında düz TTS yerine şunlar kullanılır:
  - bölüm geçişlerinde vuruş (boom),
  - sahne türüne uygun düşük seviyeli ambiyans katmanları (rüzgâr, meydan/kuşatma atmosferi),
  - vurgulu anlatım.
- Ses varlıkları da görsellerle aynı lisans kapısından geçer (CC0/PD).
- **Bugünkü durum:** Renk/ışık katmanları var. Ses tasarımı katmanları yok; `kurgu.py` korunarak ayrı bir anahtarla
  eklenir.

## 6. Hata koruması (zero-fail pipeline)

- Bir 3D ya da 2.5D sahnenin render'ı hata verirse video iptal edilmez. Sahne şu sırayla güvenli yedeğe düşer:
  `2.5D tam → sınırlı → kenburns`, `3D → harita ya da kenburns`.
- Her fallback, nedeni ve süresiyle birlikte üretim raporuna yazılır. Yayın takvimi korunur.
- Fallback bir kaliteyi gizleme aracı değildir. Fallback oranı ve nedenleri her üretimde raporlanır ve QC raporunda
  görünür.
- **Açık karar (henüz kural değil):** Bir videoda fallback oranı hangi eşiği aşarsa yayın bekletilir? Eşik, Aşama 1
  ölçümlerinden sonra belirlenecek.

## 7. Yol haritası (öneri, her adım onaya bağlı)

| Faz | Kapsam | Durum |
|---|---|---|
| 53A A1–A2 | Format profilleri, 2.5D motoru, lisans kapısı, Commons toplayıcı, gerçek görsel kalibrasyonu | Kapandı (`d2435b3`) |
| 53B | `ozne_tespit.py`: güven skorlu tür ve özne kutusu tespiti, toplayıcı entegrasyonu; kesin_yuz eşiği 0,80 + yanlış pozitif matrisi | Kodlandı, CI'da doğrulandı |
| 54 | `motor/orkestrasyon`: LLMProvider arayüzü, MockLLMProvider, 6 katmanlı senaryo/sahne planlayıcısı, Validation Gate | Kodlandı (mock); gerçek sağlayıcı bekliyor |
| 55 | Kaynak keşfi (Wikipedia TR/EN), SSRF/DNS korumalı canlı doğrulama, bağımsızlık + sayısal koruma, `GeminiLLMProvider` (sessiz mock fallback yok) | Kodlandı; ağsız testler zorunlu, canlı dry-run CI bilgi adımı |
| Sonraki | Gerçek kaynak doğrulamanın genişletilmesi (akademik API), planın üretim hattına bağlanması, uzun format kurgu, ses tasarımı, zero-fail fallback, yükleme entegrasyonu | Planlanmadı |
