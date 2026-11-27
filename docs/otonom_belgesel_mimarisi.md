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

## 8. Operasyon notları (Faz-55)

- **Canlı dry-run yalnızca elle:** Her push'ta ücretsiz Gemini kotası harcanmasın diye canlı dry-run otomatik
  çalışmaz. Başlatmak için: Actions → "Faz53a gerçek görsel kanıtı" → Run workflow → `canli_dry_run = true`.
  Zorunlu ağsız testler her push'ta çalışmaya devam eder.
- **Gemini kotası paylaşılıyor:** `bot.yml` saat başı (`37 * * * *`) aynı `secrets.GEMINI_API_KEY` ile çalışır ve
  aynı ücretsiz günlük kotayı kullanır. Dry-run'da 429 görülürse kota bot tarafından tüketilmiş olabilir. Dry-run'ı
  bot'un yoğun olmadığı bir saatte tetikleyin ya da ayrı bir ücretsiz anahtar kullanın.
- **Model (Faz-55B):**
  - Varsayılan sıra: `gemini-flash-latest`, sonra `gemini-3.7-flash`, sonra `gemini-2.5-flash`. Bu hesapta
    `gemini-2.5-flash` 404 veriyor ("no longer available to new users"). Sıra `GEMINI_MODELLER="m1,m2"` ile
    değiştirilebilir.
  - Hata sınıfları ve davranışlar:
    - 404 `model_bulunamadi`: tekrar yok, sıradaki modele geçilir.
    - 429 `kota`: tekrar YOK. Diğer modeller ve paralel parçalar için de yeni istek gönderilmez; koşu kontrollü durur.
    - 401/403 `yetki`: durulur.
    - `zaman_asimi`, `ag` ve 5xx `sunucu`: sınırlı tekrar, sonra sıradaki model.
    - Diğer 4xx `istek_gecersiz`: sıradaki model.
  - Uzun mod 3 parçada üretilir: anlatı 3 istek, plan 3 istek. İstek başlangıçları arasında en az 3 sn bekleme var.
    İstek başına en çok 90 sn beklenir. Süre bütçesi uzun mod için 150 sn, Shorts için 75 sn.
- **Dry-run anahtarı (yalnızca canlı dry-run adımında):**
  - Önce `secrets.GEMINI_DRYRUN_KEY` kullanılır; bu anahtar bot.yml kotasından ayrıdır. Tanımlı değilse
    `secrets.GEMINI_API_KEY` kullanılır. Hiçbiri yoksa Gemini adımı atlanır; mock'a geçilmez.
  - Raporda yalnızca anahtarın KAYNAK ADI görünür. Log satırları ve çıktı dosyaları, ortamdaki bütün anahtar
    değerlerine karşı ayrıca maskelenir.
  - bot.yml ve diğer otomasyonlar değiştirilmedi.
- **OpenAlex** (bağımsız akademik küme):
  - Şubat 2026'dan beri API anahtarı gerektiriyor. Anahtar ücretsizdir (openalex.org/settings/api), bu yüzden
    0 TL kuralına uyar.
  - İsteğe bağlı `secrets.OPENALEX_API_KEY` tanımlanabilir. Anahtar yoksa anahtarsız denenir; bu durumda günlük
    bütçe çok küçüktür.
  - Anahtar yalnızca ortamdan okunur; loglara ve kaynak URL'lerine yazılmaz.
- **Wikidata** Wikimedia'ya aittir, yani Wikipedia ile aynı yayıncıdır. Bağımsız küme sayılmaz, o yüzden kaynak
  kanalı olarak kullanılmadı.
- **PDF:** Açık erişimli PDF'ler (en çok 3 MB, ilk 10 sayfa) `pypdf` ile yalıtılmış bir alt süreçte okunur. Bu
  süreç bellek, CPU ve süre sınırıyla çalışır. Okunamayan PDF `unverified` sayılır; içeriği yanlış sayılmaz.
- **Faz-56 araştırma güvenilirliği:**
  - **PDF normalizasyonu (`pdf_normal.py`):**
    - Satır sonları paragrafa birleştirilir.
    - Tireyle bölünmüş kelimeler birleştirilir; bileşik adlardaki tire korunur.
    - Tiresiz bölünmüş kelimeler yalnızca birleşik hal belgede başka yerde de geçiyorsa birleştirilir.
    - Sayfa işaretleri `[s. N]` biçiminde korunur.
    - Başlık, altbilgi ve dipnotlar ana metinden ayrılır.
    - Ham metin ayrıca saklanır.
  - **Atomik doğrulama (`iddia_atom.py`):**
    - İddia şu parçalara ayrılır: yıl, gün-ay, sayı, kişi/komutan, olay, sonuç, yorum.
    - Kaynak başına destek sınıfı: `supported` / `partial` / `mention` / `contradicts` / `no_evidence`.
    - Yalnızca konuyu anmak ya da yalnızca yılı vermek tam destek sayılmaz.
    - Tek kaynaktaki tarihsel yorum kesinleşmez.
  - **Kaynak raporu:** Her kaynak için erişim nedeni ve doğrulama sonucu yazılır. Erişim nedeni kodları:
    `http_403`, `http_404`, `http_429`, `http_5xx`, `timeout`, `pdf_parse_hatasi`, `pdf_metin_yok`, `bos_icerik`,
    `desteklenmeyen_belge`, `politika_reddi`.
  - **Politika katmanı:** Dosya paylaşım ve korsan kütüphane barındırıcıları ağa hiç çıkılmadan reddedilir. Bu katman
    SSRF korumasına ektir, onun yerine geçmez.
- **Faz-56B Gemini dayanıklılığı:**
  - **503 (aşırı yük):** `Retry-After` başlığı varsa ona uyulur (en çok 120 sn). Yoksa 15 sn, sonra 30 sn beklenip
    aynı model yeniden denenir. İki tekrardan sonra hâlâ 503 ise ya da bekleme süre bütçesini aşacaksa kontrollü
    durulur; sonsuz tekrar yoktur.
  - **Diğer hatalar:** 429'da anında durulur. Diğer 5xx hataları ve zaman aşımı eski davranışını korur.
  - **Sıralı üretim:** Uzun belgeselin 3 parçası sırayla üretilir. Bir parça başarısız olursa sonrakiler istenmez.
    Başarılı parçalar aynı adımın sonraki denemesinde yeniden istenmez; böylece çift üretim olmaz. Her parça,
    önceki parçanın son birimlerini ve sahnelerini bağlam olarak alır.
  - **Shorts:** Değişmedi.
  - **Dry-run süre bütçeleri:** Uzun 210 sn, Shorts 90 sn. CI adımı en çok 6 dakika sürer.
- **Faz-57: çelişki yanlış pozitifleri ve sınırlı 503 yedeği** (Run 45966548518 bulguları):
  - **Kaynakça / dipnot dışlama:** "↑ Yazar (1986).", ISBN, "222-223, 272" sayfa listesi, `[dipnot …]` ve
    BİBLİYOGRAFYA başlığı altındaki paragraflar yıl, gün-ay ve sayı çelişkisi üretmez. Destek sınıflaması etkilenmez.
  - **Genel olay sözcükleri:** "savaş, muharebe, battle, war…" tek başına olay bağlamı kurmaz ve yıl çelişkisi
    tetiklemez. Yıl, yalnızca konuya özgü olay adına bağlıysa olayın yılıdır. "<Başka ad> Savaşı (1514)" kalıbında
    yıl o başka olaya bağlanır.
  - **Sayı çelişkisi:** değer + ölçü türü (kelime sınırıyla) + taraf (aynı yan cümledeki en yakın özel ad, olay adı
    hariç) + olay (yan cümlede iddiada olmayan yıl yok) birlikte eşleşmelidir. Taraf belirsizse karşılaştırma yapılmaz.
    Kümeler arası sayı çelişkisi de aynı ölçü + taraf + olay grubunda aranır.
  - **OCR rakam onarımı:** yalnız doğrulama kopyasında, güçlü bağlamda `ı → 1` ("ı473", "ı ı Ağustos"). Özgün metin
    değişmez; alıntı özgün metinden verilir. OCR onarımlı pencere çelişki üretmez. OCR'a bağlı destek, iddianın
    OCR'sız bir desteği yoksa sayılmaz (`sayilmadi`).
  - **503 yedeği:** birincil model 503 bütçesini (15 → 30 sn) bitirirse yapılandırılmış sırada ondan sonraki ilk
    farklı Flash modele BİR KEZ geçilir; yedeğin bütçesi tek tekrar (15 sn). Yedek de başarısızsa başka model
    aranmaz, birincile dönülmez. 429 her modelde anında durdurur. 503 yolunda en çok 5 istek, 60 sn bekleme.
  - **Shorts kısa devresi:** uzun mod 503 bütçesini tüketerek durursa Shorts için Gemini çağrılmaz
    (`atlandi_asiri_yuk`, koşu durumu `gemini_asiri_yuk`, çıkış 1). Zaman aşımı, genel 5xx ve ağ hatalarında
    davranış değişmedi.
- **Faz-58: 503 + zaman aşımı aşırı yük bağlamı ve sayı çelişkisi** (Run 45984647430 bulguları):
  - **Aşırı yük bağlamı:** Bir model 503 verdiğinde o model için bağlam açılır ve sağlayıcı ömrü boyunca korunur.
    - Bağlam açıkken gelen zaman aşımı `zaman_asimi` sınıfıyla kaydedilir, 503 sayılmaz. Hata kaydında
      `asiri_yuk_baglami` ayrıca işaretlenir.
    - Bu zaman aşımı genel tekrar hakkını değil, 503 tekrar hakkını tüketir. Ek bekleme yapılmaz.
  - **Kısa zaman aşımı:** Bağlam açıkken birincil ve yedek modele giden istekler `zaman_asimi_yuk` kullanır
    (30–45 sn arası, varsayılan 40). Bağlam açılmadan önceki ilk istek 90 sn'de kalır.
  - **Yedek rezervi:** Süre bütçesinin `yedek_rezerv_sn` kadarı yedek modele ayrılır (varsayılan: 60 sn ile bütçenin
    %40'ından küçük olanı; uzun mod 60 sn, Shorts 36 sn). Birincil model bu payı kullanamaz.
    - Payı biterse ya da gereken bekleme payını aşacaksa, birincil doğrudan yedeğe geçer.
    - Yedek tek atışlıktır; zincir oluşmaz, birincile geri dönülmez. 429 her modelde anında durdurur.
  - **Deterministik üst sınır:** birincilde 3, yedekte 2 istek; bağlam açıldıktan sonra her istek en çok 40 sn.
  - **Shorts kısa devresi:** Uzun mod şu iki durumda başarısız olursa Shorts için istek gönderilmez:
    - son sınıf `asiri_yuk`,
    - sağlayıcı 503 görmüşken son sınıf `zaman_asimi` ya da `sure_butcesi`.

    503 görülmemiş zaman aşımı, 5xx, ağ hatası ve 429'da davranış değişmedi.
  - **Sayı çelişkisi:**
    - **Özne/nesne:** Sayının sağındaki özel ad yalnızca bitişik nitelemede özne sayılır ("5,000 men of X",
      "100,000-strong X army"). Araya fiil girerse ("60,000 … began to harass X's forces") özne aranmaz.
    - **Olay aşaması:** Öncü, kanat, takip, garnizon, takviye ve pusu işaretleri farklıysa rakamlar karşılaştırılmaz.
    - **Aynı küme:** Aynı küme birden çok değer veriyorsa o küme sayı karşılaştırmasından çıkarılır.
    - **Aynı kaynak:** Kaynağın başka bir penceresi iddianın rakamını veriyorsa sayı çelişkisi düşer. Yıl ve gün-ay
      çelişkisi korunur.
