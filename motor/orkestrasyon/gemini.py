"""Gerçek LLM sağlayıcısı: Google Gemini (ücretsiz katman, 0 TL). Sessiz mock fallback YOKTUR.

- Anahtar varsayılan olarak `GEMINI_API_KEY` ortam değişkeninden okunur. Canlı dry-run, kendi seçtiği anahtarı
  `anahtar=` ile verir (bkz. canli_dry_run.dryrun_anahtari_sec). URL'ye değil `x-goog-api-key` başlığına konur.
  Hiçbir dosyaya, loga, rapora ya da hata mesajına yazılmaz; hata metinlerinde geçerse `***` ile maskelenir.
- Anahtar yoksa ya da API başarısız olursa `GercekUretimHatasi` fırlatılır. Planlayıcı bu durumda durur ve raporlar;
  MockLLMProvider'a GEÇMEZ.
- Mock yalnızca açık test/offline kipinde kullanılır (`saglayici_sec("test")`).
- Model sırası `GEMINI_MODELLER` ile değiştirilebilir. Modeli değiştirmek mock fallback sayılmaz; hepsi aynı gerçek
  sağlayıcıdır.
- Hata sınıfları ve davranışlar:
  - `model_bulunamadi` (404): tekrar yok, sıradaki modele geçilir.
  - `kota` (429): tekrar YOK, diğer modeller denenmez; `GeminiKotaHatasi` ile kontrollü durulur.
  - `yetki` (401/403): durulur.
  - `asiri_yuk` (503): `Retry-After` başlığı varsa ona uyulur, yoksa 15 sn, sonra 30 sn beklenip AYNI model yeniden
    denenir. Bekleme sırası `beklemeler_503` ile verilir. Bekleme süre bütçesini aşacaksa beklenmez, durulur.
  - Faz-57 tek atışlık 503 yedeği: birincil model 503 bütçesini (15 → 30 sn) tükettiğinde, YAPILANDIRILMIŞ model
    sırasında (`MODELLER` / `GEMINI_MODELLER`) ondan sonra gelen, ondan farklı ve 404 vermemiş ilk Flash modele BİR KEZ
    geçilir (yeni model adı uydurulmaz). Yedeğin 503 bütçesi `beklemeler_503_yedek` (varsayılan tek tekrar: 15 sn).
    Yedek de 503 / 404 / başka hata verirse başka model ARANMAZ, kontrollü durulur. Geçiş hakkı sağlayıcı ömründe
    birdir; yedek bir kez kullanıldıysa sonraki çağrılarda yeni geçiş olmaz. 429 hangi modelde gelirse gelsin anında
    durulur. Toplam istek üst sınırı (503 yolu): 1 + len(beklemeler_503) + 1 + len(beklemeler_503_yedek).
  - `zaman_asimi`, `ag` ve `sunucu` (diğer 5xx): sınırlı tekrar, sonra sıradaki model.
  - Faz-58 aşırı yük bağlamı: bir model 503 verdiğinde o model için AŞIRI YÜK BAĞLAMI açılır ve sağlayıcı ömrü boyunca
    korunur (`asiri_yuk_goruldu`, `_yuk_modeller`). Bağlam açıkken:
      · o modele (ve yedek modele) giden isteklerin zaman aşımı kısa tutulur (`zaman_asimi_yuk`, 30–45 sn; vars. 40);
      · o modelde gelen zaman aşımı `zaman_asimi` sınıfıyla kaydedilir (503 sayılmaz; `hatalar[*].asiri_yuk_baglami`
        ayrı işaretlenir) ama genel tekrar hakkını değil, 503 tekrar hakkını (`beklemeler_503`) tüketir; ek bekleme
        yapılmaz (zaman aşımının kendisi bekleme sayılır);
      · süre bütçesinin `yedek_rezerv_sn` kadarı (vars. min(60, bütçe × 0,4)) yedek model için AYRILIR: birincil model
        bu payı kullanamaz; payı biterse ya da bekleme payı aşacaksa doğrudan yedeğe geçilir.
    503 bağlamı olmayan zaman aşımı, genel 5xx, ağ hatası ve 429 davranışı değişmez.
    Deterministik üst sınır (aşırı yük yolu): birincil 1 + len(beklemeler_503), yedek 1 + len(beklemeler_503_yedek)
    istek; her istek en çok `zaman_asimi_yuk` sn (bağlam açılmadan önceki ilk istek hariç).
- Tekrar güvenliği: generateContent durumsuzdur. 503 yanıtında üretilmiş bir metin yoktur; zaman aşımında sunucu
  yanıt üretmiş olsa bile bize ulaşmadığı için kullanılmaz. Her `tamamla` çağrısı tam olarak BİR yanıt döndürür, yani
  çift üretim çıktıya giremez.
  - `istek_gecersiz` (diğer 4xx) ve `yanit_bicimi`: sıradaki model.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

from motor.orkestrasyon.llm import LLMHatasi, LLMProvider, MockLLMProvider

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# Varsayılan: ücretsiz katmanda yüksek RPM/TPM'li hızlı model. Kullanımdan kalkmışsa (404) sıradaki denenir;
# sıra GEMINI_MODELLER="m1,m2" ortam değişkeniyle değiştirilebilir. Model değiştirmek mock fallback DEĞİLDİR.
# (gemini-2.5-flash bu hesap için 404 "no longer available to new users"; sonda yedek olarak kalır)
MODELLER = ("gemini-flash-latest", "gemini-3.7-flash", "gemini-2.5-flash")


def modeller() -> tuple[str, ...]:
    e = os.environ.get("GEMINI_MODELLER", "").strip()
    return tuple(m.strip() for m in e.split(",") if m.strip()) or MODELLER


class GercekUretimHatasi(LLMHatasi):
    """Gerçek üretim yapılamadı. Mesaj anahtar içermez. Çağıran sessizce mock'a geçmemelidir.
    sinif: anahtar_yok | kota | yetki | model_bulunamadi | zaman_asimi | ag | sunucu | istek_gecersiz | yanit_bicimi |
    sure_butcesi. hatalar: [{model, sinif, http}] (anahtar içermez)."""

    def __init__(self, mesaj: str, sinif: str = "bilinmiyor", hatalar: list | None = None,
                 asiri_yuk_baglami: bool = False):
        super().__init__(mesaj)
        self.sinif = sinif
        self.hatalar = list(hatalar or [])
        # sınıftan BAĞIMSIZ: başarısızlık 503 aşırı yük bağlamında mı oldu (ör. 503 sonrası zaman aşımı / süre bütçesi)
        self.asiri_yuk_baglami = bool(asiri_yuk_baglami)


class GeminiKotaHatasi(GercekUretimHatasi):
    """HTTP 429: ücretsiz kota ya da dakika başı sınır aşıldı. Agresif tekrar yapılmaz; üretim kontrollü durur."""


def hata_sinifi(kod: int | None, istisna: BaseException | None = None) -> str:
    if istisna is not None:
        return "zaman_asimi" if isinstance(istisna, TimeoutError) or "timed out" in str(istisna).lower() else "ag"
    if kod == 404:
        return "model_bulunamadi"
    if kod == 429:
        return "kota"
    if kod in (401, 403):
        return "yetki"
    if kod == 503:
        return "asiri_yuk"
    if kod is not None and kod >= 500:
        return "sunucu"
    return "istek_gecersiz"


def _urllib_tasiyici(url: str, govde: bytes, basliklar: dict, zaman: float) -> tuple[int, str, dict]:
    istek = urllib.request.Request(url, data=govde, headers=basliklar, method="POST")
    try:
        with urllib.request.urlopen(istek, timeout=zaman) as y:
            return (y.status, y.read(8 * 1024 * 1024).decode("utf-8", errors="replace"),
                    {k.lower(): v for k, v in y.headers.items()})
    except urllib.error.HTTPError as e:
        return (e.code, e.read(64 * 1024).decode("utf-8", errors="replace"),
                {k.lower(): v for k, v in (e.headers.items() if e.headers else [])})


BEKLEMELER_503 = (15.0, 30.0)
BEKLEMELER_503_YEDEK = (15.0,)
ZAMAN_ASIMI_YUK = 40.0          # 503 bağlamındaki istekler için kısa zaman aşımı (30–45 sn arasında olmalı)
YEDEK_REZERV_SN = 60.0          # süre bütçesinden yedek modele ayrılan pay (bütçenin %40'ını aşmaz)
RETRY_AFTER_TAVANI = 120.0


def retry_after_sn(basliklar: dict | None, simdi: float | None = None) -> float | None:
    """Retry-After: saniye ya da HTTP tarihi. Geçersizse None. Negatif/aşırı değerler kırpılır."""
    v = (basliklar or {}).get("retry-after")
    if v is None:
        return None
    v = str(v).strip()
    try:
        sn = float(v)
    except ValueError:
        try:
            from email.utils import parsedate_to_datetime
            sn = parsedate_to_datetime(v).timestamp() - (simdi if simdi is not None else time.time())
        except (TypeError, ValueError, OverflowError):
            return None
    return max(0.0, min(RETRY_AFTER_TAVANI, sn))


class GeminiLLMProvider(LLMProvider):
    ad = "gemini"
    sentetik = False

    def __init__(self, modeller=None, tasiyici=None, zaman_asimi: float = 90.0, uyku=time.sleep, en_cok_tekrar: int = 2,
                 dusunme_butcesi: int | None = 1024, sure_butcesi: float | None = None, ilerleme=None, saat=time.monotonic,
                 en_az_aralik: float = 0.0, anahtar: str | None = None, anahtar_kaynagi: str = "GEMINI_API_KEY",
                 beklemeler_503: tuple = BEKLEMELER_503, yedek_503: bool = True,
                 beklemeler_503_yedek: tuple = BEKLEMELER_503_YEDEK, zaman_asimi_yuk: float = ZAMAN_ASIMI_YUK,
                 yedek_rezerv_sn: float | None = None):
        """zaman_asimi: istek başına en çok bekleme (sn). dusunme_butcesi: thinking token sınırı (None → gönderilmez;
        model desteklemiyorsa 400 sonrası o model için kendiliğinden kapatılır). sure_butcesi: bu sağlayıcının bütün
        çağrıları için toplam duvar saati sınırı (aşılırsa GercekUretimHatasi; asılı kalma yok). en_az_aralik: iki istek
        başlangıcı arasında en az bekleme (sn) — ücretsiz katman dakika başı istek sınırını (429) korur."""
        anahtar = anahtar if anahtar is not None else os.environ.get("GEMINI_API_KEY")
        if not anahtar or not anahtar.strip():
            raise GercekUretimHatasi(f"{anahtar_kaynagi} tanımlı değil: gerçek üretim yapılamaz (mock'a geçilmez)", "anahtar_yok")
        self.__anahtar = anahtar.strip()
        self.anahtar_kaynagi = anahtar_kaynagi   # yalnızca AD (değer değil) raporlanabilir
        self.hatalar: list[dict] = []
        self.kota_doldu = False   # ilk 429'dan sonra (paralel parçalar dahil) yeni istek GÖNDERİLMEZ
        self.beklemeler_503 = tuple(float(x) for x in beklemeler_503)   # testte (0, 0) verilebilir
        self.tekrar_kaydi: list[dict] = []   # 503 tekrarları: {etiket, model, tekrar, bekleme_sn, kaynak}
        self.yedek_503 = bool(yedek_503)
        self.beklemeler_503_yedek = tuple(float(x) for x in beklemeler_503_yedek)
        self.yedek_gecisi: dict | None = None   # {etiket, kimden, kime}: en çok BİR kez dolar
        self._bulunamayan: set[str] = set()     # 404 veren modeller (yedek seçilmez)
        self.asiri_yuk_doldu = False            # 503 ile kontrollü durulduysa yeni istek GÖNDERİLMEZ (çift çağrı yok)
        if not 30.0 <= float(zaman_asimi_yuk) <= 45.0:
            raise ValueError("zaman_asimi_yuk 30–45 sn aralığında olmalı")
        self.zaman_asimi_yuk = float(zaman_asimi_yuk)
        self.asiri_yuk_goruldu = False          # bu sağlayıcıda en az bir 503 görüldü mü (Shorts kısa devresi için)
        self._yuk_modeller: set[str] = set()    # 503 vermiş modeller: aşırı yük bağlamı model başına korunur
        self.son_basarisizlik: dict | None = None   # {sinif, asiri_yuk_baglami}: son kontrollü duruş
        self.modeller = tuple(modeller) if modeller else globals()["modeller"]()
        self.tasiyici = tasiyici or _urllib_tasiyici
        self.zaman_asimi, self.uyku, self.en_cok_tekrar = zaman_asimi, uyku, en_cok_tekrar
        self.kullanilan_model: str | None = None
        self.cagri_sayisi = 0
        self.dusunme_butcesi, self.sure_butcesi, self.ilerleme, self.saat = dusunme_butcesi, sure_butcesi, ilerleme, saat
        self._baslangic = saat()
        self.yedek_rezerv_sn = (0.0 if sure_butcesi is None else
                                float(yedek_rezerv_sn) if yedek_rezerv_sn is not None else
                                min(YEDEK_REZERV_SN, 0.4 * float(sure_butcesi)))
        self._dusunmesiz: set[str] = set()
        self._semasiz: set[str] = set()          # Faz-63: responseJsonSchema'yı 400 ile reddeden modeller
        self.sema_dusurulen: list[dict] = []     # {etiket, model}: şemasız tekrar edilen istekler (raporlanır)
        self.en_az_aralik = float(en_az_aralik)
        self._son_istek: float | None = None
        import threading
        self._kilit = threading.Lock()

    def __repr__(self) -> str:   # anahtar hiçbir temsilde görünmez
        return f"GeminiLLMProvider(modeller={self.modeller!r})"

    def _maskele(self, metin: str) -> str:
        return (metin or "").replace(self.__anahtar, "***")

    def _log(self, mesaj: str) -> None:
        if self.ilerleme:
            self.ilerleme("gemini_cagri", mesaj)

    def _kalan(self) -> float | None:
        return None if self.sure_butcesi is None else self.sure_butcesi - (self.saat() - self._baslangic)

    def _govde(self, istem: str, model: str, sema: dict | None = None) -> bytes:
        cfg = {"temperature": 0.2, "responseMimeType": "application/json"}
        if sema is not None and model not in self._semasiz:
            # Faz-63: yapılandırılmış çıktı — REST GenerationConfig.responseJsonSchema (responseMimeType ile birlikte
            # zorunlu; responseSchema ile birlikte gönderilmez). İstemdeki JSON talimatı korunur; güvence şemadan gelir.
            cfg["responseJsonSchema"] = sema
        if self.dusunme_butcesi is not None and model not in self._dusunmesiz:
            cfg["thinkingConfig"] = {"thinkingBudget": int(self.dusunme_butcesi)}
        return json.dumps({"contents": [{"role": "user", "parts": [{"text": istem}]}], "generationConfig": cfg}).encode()

    def _hata(self, model, sinif, http=None, asiri_yuk_baglami=False):
        with self._kilit:
            h = {"model": model, "sinif": sinif, "http": http}
            if asiri_yuk_baglami:
                h["asiri_yuk_baglami"] = True
            self.hatalar.append(h)

    def _rezerv(self, model: str) -> float:
        """Birincil modelin kullanamayacağı, yedeğe ayrılmış süre (yalnız aşırı yük bağlamında ve yedek varken)."""
        if self.sure_butcesi is None or model not in self._yuk_modeller or self._yedek_sec(model) is None:
            return 0.0
        return self.yedek_rezerv_sn

    def _dur(self, mesaj: str, sinif: str, yuk: bool, tip=None):
        """Kontrollü duruş: sınıf korunur, aşırı yük bağlamı ayrıca taşınır; bağlamdaysa yeni istek engellenir."""
        if yuk:
            self.asiri_yuk_doldu = True
        self.son_basarisizlik = {"sinif": sinif, "asiri_yuk_baglami": bool(yuk)}
        raise (tip or GercekUretimHatasi)(self._maskele(mesaj), sinif, self.hatalar, asiri_yuk_baglami=yuk)

    def _yedek_sec(self, model: str) -> str | None:
        """503 bütçesi biten `model` için yapılandırmadan tek yedek: sırada ondan SONRA gelen, ondan farklı, adında
        'flash' geçen ve 404 vermemiş ilk model. Geçiş daha önce yapıldıysa ya da kapalıysa None (sonsuz zincir yok)."""
        if not self.yedek_503 or self.yedek_gecisi is not None or model not in self.modeller:
            return None
        sonra = self.modeller[self.modeller.index(model) + 1:]
        return next((m for m in sonra if m != model and "flash" in m.lower() and m not in self._bulunamayan), None)

    def _kota_kontrol(self, etiket: str) -> None:
        if self.asiri_yuk_doldu:
            raise GercekUretimHatasi(f"Gemini 503 aşırı yük bütçesi bu sağlayıcıda daha önce tükendi; {etiket} için istek "
                                     f"gönderilmedi (mock'a geçilmez)", "asiri_yuk", self.hatalar,
                                     asiri_yuk_baglami=True)
        if self.kota_doldu:
            raise GeminiKotaHatasi(f"Gemini kotası bu koşuda daha önce aşıldı (HTTP 429); {etiket} için istek gönderilmedi "
                                   f"(mock'a geçilmez)", "kota", self.hatalar)

    def tamamla(self, istem: str, adim: str, baglam: dict) -> str:
        basliklar = {"Content-Type": "application/json", "x-goog-api-key": self.__anahtar}
        sorunlar, son_sinif = [], "bilinmiyor"
        etiket = adim + (f"/{baglam['bolum']}" if baglam.get("bolum") else "")
        sema = baglam.get("yanit_semasi")   # Faz-63: isteğe bağlı JSON Schema (yapılandırılmış çıktı)
        if self.yedek_gecisi is not None:   # yedeğe geçildiyse yalnız yedek: birincile geri dönüş / yeni zincir yok
            sira = [self.yedek_gecisi["kime"]]
        else:
            sira = ([self.kullanilan_model] if self.kullanilan_model else []) + [m for m in self.modeller if m != self.kullanilan_model]
        self._kota_kontrol(etiket)
        kuyruk = list(sira)
        while kuyruk:
            model = kuyruk.pop(0)
            yedek_mi = self.yedek_gecisi is not None and model == self.yedek_gecisi["kime"]
            beklemeler = self.beklemeler_503_yedek if yedek_mi else self.beklemeler_503
            tekrar, yuk_tekrar = 0, 0
            gecis = None   # aşırı yük bütçesi bitince yedek model adı

            def _yuk_bitti(neden: str):
                """Bu modelin aşırı yük bütçesi bitti: tek atışlık yedek varsa onu döndür, yoksa kontrollü dur."""
                yedek = None if yedek_mi else self._yedek_sec(model)
                if yedek:
                    with self._kilit:
                        self.yedek_gecisi = {"etiket": etiket, "kimden": model, "kime": yedek}
                    self._log(f"⇄ {etiket} model={model} aşırı yük bütçesi bitti ({neden}): tek atışlık yedek modele "
                              f"geçiliyor → {yedek} (en çok {1 + len(self.beklemeler_503_yedek)} istek, "
                              f"rezerv {self._kalan_metin()})")
                    return yedek
                self._log(f"■ {etiket} model={model} aşırı yük sürüyor ({neden}){' (yedek model)' if yedek_mi else ''}: "
                          f"durduruluyor")
                ek = (f"; yedek geçişi {self.yedek_gecisi['kimden']} → {self.yedek_gecisi['kime']} de başarısız"
                      if yedek_mi else "")
                self._dur(f"Gemini aşırı yük (model={model}; {neden}){ek}, üretim durduruldu (mock'a geçilmez): "
                          + " | ".join(sorunlar[-4:]), "asiri_yuk", True)

            while tekrar <= self.en_cok_tekrar:
                kalan = self._kalan()
                rez = self._rezerv(model)
                yuk = model in self._yuk_modeller
                if kalan is not None and kalan - rez <= 1:
                    if rez:   # birincilin payı bitti; rezerv yedeğe ait
                        gecis = _yuk_bitti(f"birincil süre payı bitti, {rez:.0f} sn yedeğe ayrılmıştı")
                        break
                    self._dur(f"Gemini süre bütçesi ({self.sure_butcesi:.0f} sn) doldu; üretim durduruldu (mock'a "
                              f"geçilmez): " + " | ".join(sorunlar), "sure_butcesi", self.asiri_yuk_goruldu)
                zaman = self.zaman_asimi
                if yuk or yedek_mi:
                    zaman = min(zaman, self.zaman_asimi_yuk)   # aşırı yük bağlamında kısa zaman aşımı
                if kalan is not None:   # rezerv varken birincil isteği yedeğin payına taşamaz
                    zaman = min(zaman, kalan - rez) if rez else max(5.0, min(zaman, kalan))
                with self._kilit:   # istek aralığı: paralel çağrılar da sıraya girer
                    if self.en_az_aralik and self._son_istek is not None:
                        bekle = self.en_az_aralik - (self.saat() - self._son_istek)
                        if bekle > 0:
                            self.uyku(bekle)
                    self._kota_kontrol(etiket)   # beklerken başka parça 429 almış olabilir
                    self._son_istek = self.saat()
                    self.cagri_sayisi += 1
                t0 = self.saat()
                self._log(f"→ {etiket} model={model}{' (yedek)' if yedek_mi else ''} deneme={tekrar + 1} "
                          f"503_tekrar={yuk_tekrar}/{len(beklemeler)} zaman_asimi={zaman:.0f}s"
                          f"{' [aşırı yük bağlamı]' if yuk or yedek_mi else ''} istem={len(istem)} kr")
                try:
                    yanit_ham = self.tasiyici(API.format(model=model), self._govde(istem, model, sema), basliklar, zaman)
                    kod, metin = yanit_ham[0], yanit_ham[1]
                    yanit_basliklari = yanit_ham[2] if len(yanit_ham) > 2 else {}
                except Exception as e:   # zaman aşımı / ağ hatası: mesaj maskelenir
                    son_sinif = hata_sinifi(None, e)
                    yuk_bag = son_sinif == "zaman_asimi" and (yuk or yedek_mi)
                    self._hata(model, son_sinif, asiri_yuk_baglami=yuk_bag)
                    sorunlar.append(f"{model}: {son_sinif}{' (aşırı yük bağlamında)' if yuk_bag else ''} "
                                    f"{type(e).__name__}: {self._maskele(str(e))[:300]}")
                    self._log(f"✗ {etiket} model={model} {son_sinif}{' [aşırı yük bağlamı]' if yuk_bag else ''} "
                              f"{type(e).__name__} ({self.saat() - t0:.1f}s)")
                    if yuk_bag:   # 503 sonrası zaman aşımı: 503 tekrar hakkını tüketir, ek bekleme yok
                        if yuk_tekrar >= len(beklemeler):
                            gecis = _yuk_bitti(f"503 sonrası zaman aşımı, {yuk_tekrar} tekrardan sonra sürüyor")
                            break
                        yuk_tekrar += 1
                        with self._kilit:
                            self.tekrar_kaydi.append({"etiket": etiket, "model": model, "tekrar": yuk_tekrar,
                                                      "bekleme_sn": 0.0, "kaynak": "zaman_asimi"})
                        continue
                    if tekrar < self.en_cok_tekrar:
                        self.uyku(2 ** tekrar)
                        tekrar += 1
                        continue
                    break
                self._log(f"← {etiket} model={model} HTTP {kod} ({self.saat() - t0:.1f}s, {len(metin)} kr)")
                if kod == 400 and "thinking" in metin.lower() and model not in self._dusunmesiz:
                    self._dusunmesiz.add(model)   # bu model thinking yapılandırmasını desteklemiyor: onsuz tekrar
                    continue
                if (kod == 400 and sema is not None and model not in self._semasiz
                        and re.search(r"schema", metin, re.I)):
                    # Faz-63: model şemayı reddetti → bu model için şemasız TEK tekrar (istem JSON talimatı + yerel
                    # normalizasyon ve doğrulama yine çalışır); raporlanır, sessiz değil
                    with self._kilit:
                        self._semasiz.add(model)
                        self.sema_dusurulen.append({"etiket": etiket, "model": model})
                    self._log(f"⚠ {etiket} model={model} responseJsonSchema reddedildi (HTTP 400): şemasız tekrar")
                    continue
                if kod == 200:
                    try:
                        d = json.loads(metin)
                        parcalar = d["candidates"][0]["content"]["parts"]
                        yanit = "".join(p.get("text", "") for p in parcalar)
                    except (KeyError, IndexError, json.JSONDecodeError, TypeError):
                        son_sinif = "yanit_bicimi"
                        self._hata(model, son_sinif, 200)
                        sorunlar.append(f"{model}: yanit_bicimi")
                        break
                    with self._kilit:
                        self.kullanilan_model = model
                    return yanit
                son_sinif = hata_sinifi(kod)
                self._hata(model, son_sinif, kod)
                if son_sinif == "model_bulunamadi":
                    self._bulunamayan.add(model)
                ozet = self._maskele(re.sub(r"\s+", " ", metin))[:400]
                sorunlar.append(f"{model}: {son_sinif} HTTP {kod} {ozet}")
                if son_sinif == "kota":   # agresif tekrar YOK; diğer modelleri de zorlamadan kontrollü dur
                    self.kota_doldu = True
                    self._log(f"■ {etiket} model={model} KOTA (429): üretim durduruluyor, tekrar denenmeyecek")
                    self._dur(f"Gemini kotası aşıldı (HTTP 429, model={model}); tekrar denenmedi, üretim durduruldu "
                              f"(mock'a geçilmez): {ozet}", "kota", False, GeminiKotaHatasi)
                if son_sinif == "yetki":
                    self._dur(f"Gemini yetki hatası (HTTP {kod}, anahtar={self.anahtar_kaynagi}); üretim durduruldu: "
                              f"{ozet}", "yetki", False)
                if son_sinif == "asiri_yuk":   # 503: Retry-After ya da 15 → 30 sn; sınırlı; tek yedek; sonra dur
                    with self._kilit:
                        self._yuk_modeller.add(model)
                        self.asiri_yuk_goruldu = True
                    if yuk_tekrar >= len(beklemeler):
                        gecis = _yuk_bitti(f"HTTP 503 {yuk_tekrar} tekrardan sonra sürüyor")
                        break
                    ra = retry_after_sn(yanit_basliklari)
                    bekle = ra if ra is not None else beklemeler[yuk_tekrar]
                    kalan = self._kalan()
                    rez = self._rezerv(model)
                    if kalan is not None and bekle >= kalan - rez - 1:
                        if rez:
                            gecis = _yuk_bitti(f"{bekle:.0f} sn bekleme birincil süre payını aşıyor")
                            break
                        self._log(f"■ {etiket} model={model} 503: {bekle:.0f} sn bekleme süre bütçesini "
                                  f"({kalan:.0f} sn) aşıyor")
                        self._dur(f"Gemini aşırı yük (HTTP 503); gereken {bekle:.0f} sn bekleme süre bütçesini aşıyor, "
                                  f"üretim durduruldu (mock'a geçilmez): {ozet}", "asiri_yuk", True)
                    yuk_tekrar += 1
                    with self._kilit:
                        self.tekrar_kaydi.append({"etiket": etiket, "model": model, "tekrar": yuk_tekrar,
                                                  "bekleme_sn": bekle, "kaynak": "retry-after" if ra is not None else "plan"})
                    self._log(f"↻ {etiket} model={model} 503 aşırı yük: {bekle:.0f} sn bekleniyor "
                              f"({'Retry-After' if ra is not None else 'plan'}), tekrar {yuk_tekrar}/{len(beklemeler)}")
                    self.uyku(bekle)
                    continue
                if son_sinif == "sunucu" and tekrar < self.en_cok_tekrar:
                    self.uyku(min(30, 5 * (tekrar + 1)))
                    tekrar += 1
                    continue
                break   # model_bulunamadi / istek_gecersiz / tekrarı biten sunucu: sıradaki model
            if gecis:
                kuyruk = [gecis]   # yalnız yedek; sıradaki diğer modellere geçilmez (zincir yok). Yedek başka bir
                #                    hatayla biterse kuyruk zaten boştur: yeni model aranmaz.
        yuk_son = self.asiri_yuk_goruldu and son_sinif in ("asiri_yuk", "zaman_asimi")
        self._dur("Gemini çağrısı başarısız (mock'a geçilmez): " + " | ".join(sorunlar), son_sinif, yuk_son)

    def _kalan_metin(self) -> str:
        k = self._kalan()
        return "sınırsız" if k is None else f"kalan {k:.0f} sn"

def saglayici_sec(kip: str) -> LLMProvider:
    """'gercek' → GeminiLLMProvider (anahtar yoksa hata). 'test' / 'offline' → MockLLMProvider. Başka yol yok."""
    if kip == "gercek":
        return GeminiLLMProvider()
    if kip in ("test", "offline"):
        return MockLLMProvider()
    raise ValueError("kip 'gercek', 'test' ya da 'offline' olmalı")
