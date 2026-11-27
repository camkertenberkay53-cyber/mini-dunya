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

    def __init__(self, mesaj: str, sinif: str = "bilinmiyor", hatalar: list | None = None):
        super().__init__(mesaj)
        self.sinif = sinif
        self.hatalar = list(hatalar or [])


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
                 beklemeler_503_yedek: tuple = BEKLEMELER_503_YEDEK):
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
        self.modeller = tuple(modeller) if modeller else globals()["modeller"]()
        self.tasiyici = tasiyici or _urllib_tasiyici
        self.zaman_asimi, self.uyku, self.en_cok_tekrar = zaman_asimi, uyku, en_cok_tekrar
        self.kullanilan_model: str | None = None
        self.cagri_sayisi = 0
        self.dusunme_butcesi, self.sure_butcesi, self.ilerleme, self.saat = dusunme_butcesi, sure_butcesi, ilerleme, saat
        self._baslangic = saat()
        self._dusunmesiz: set[str] = set()
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

    def _govde(self, istem: str, model: str) -> bytes:
        cfg = {"temperature": 0.2, "responseMimeType": "application/json"}
        if self.dusunme_butcesi is not None and model not in self._dusunmesiz:
            cfg["thinkingConfig"] = {"thinkingBudget": int(self.dusunme_butcesi)}
        return json.dumps({"contents": [{"role": "user", "parts": [{"text": istem}]}], "generationConfig": cfg}).encode()

    def _hata(self, model, sinif, http=None):
        with self._kilit:
            self.hatalar.append({"model": model, "sinif": sinif, "http": http})

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
                                     f"gönderilmedi (mock'a geçilmez)", "asiri_yuk", self.hatalar)
        if self.kota_doldu:
            raise GeminiKotaHatasi(f"Gemini kotası bu koşuda daha önce aşıldı (HTTP 429); {etiket} için istek gönderilmedi "
                                   f"(mock'a geçilmez)", "kota", self.hatalar)

    def tamamla(self, istem: str, adim: str, baglam: dict) -> str:
        basliklar = {"Content-Type": "application/json", "x-goog-api-key": self.__anahtar}
        sorunlar, son_sinif = [], "bilinmiyor"
        etiket = adim + (f"/{baglam['bolum']}" if baglam.get("bolum") else "")
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
            while tekrar <= self.en_cok_tekrar:
                kalan = self._kalan()
                if kalan is not None and kalan <= 1:
                    raise GercekUretimHatasi(self._maskele(f"Gemini süre bütçesi ({self.sure_butcesi:.0f} sn) doldu; "
                                                           f"üretim durduruldu (mock'a geçilmez): " + " | ".join(sorunlar)),
                                             "sure_butcesi", self.hatalar)
                zaman = self.zaman_asimi if kalan is None else max(5.0, min(self.zaman_asimi, kalan))
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
                          f"503_tekrar={yuk_tekrar}/{len(beklemeler)} "
                          f"zaman_asimi={zaman:.0f}s istem={len(istem)} kr")
                try:
                    yanit_ham = self.tasiyici(API.format(model=model), self._govde(istem, model), basliklar, zaman)
                    kod, metin = yanit_ham[0], yanit_ham[1]
                    yanit_basliklari = yanit_ham[2] if len(yanit_ham) > 2 else {}
                except Exception as e:   # zaman aşımı / ağ hatası: mesaj maskelenir
                    son_sinif = hata_sinifi(None, e)
                    self._hata(model, son_sinif)
                    sorunlar.append(f"{model}: {son_sinif} {type(e).__name__}: {self._maskele(str(e))[:300]}")
                    self._log(f"✗ {etiket} model={model} {son_sinif} {type(e).__name__} ({self.saat() - t0:.1f}s)")
                    if tekrar < self.en_cok_tekrar:
                        self.uyku(2 ** tekrar)
                        tekrar += 1
                        continue
                    break
                self._log(f"← {etiket} model={model} HTTP {kod} ({self.saat() - t0:.1f}s, {len(metin)} kr)")
                if kod == 400 and "thinking" in metin.lower() and model not in self._dusunmesiz:
                    self._dusunmesiz.add(model)   # bu model thinking yapılandırmasını desteklemiyor: onsuz tekrar
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
                    raise GeminiKotaHatasi(self._maskele(
                        f"Gemini kotası aşıldı (HTTP 429, model={model}); tekrar denenmedi, üretim durduruldu "
                        f"(mock'a geçilmez): {ozet}"), "kota", self.hatalar)
                if son_sinif == "yetki":
                    raise GercekUretimHatasi(self._maskele(
                        f"Gemini yetki hatası (HTTP {kod}, anahtar={self.anahtar_kaynagi}); üretim durduruldu: {ozet}"),
                        "yetki", self.hatalar)
                if son_sinif == "asiri_yuk":   # 503: Retry-After ya da 15 → 30 sn; sınırlı; tek yedek; sonra dur
                    if yuk_tekrar >= len(beklemeler):
                        yedek = None if yedek_mi else self._yedek_sec(model)
                        if yedek:
                            with self._kilit:
                                self.yedek_gecisi = {"etiket": etiket, "kimden": model, "kime": yedek}
                            self._log(f"⇄ {etiket} model={model} 503 bütçesi bitti ({yuk_tekrar} tekrar): tek atışlık "
                                      f"yedek modele geçiliyor → {yedek} (en çok {1 + len(self.beklemeler_503_yedek)} istek)")
                            kuyruk = [yedek]
                            break
                        self._log(f"■ {etiket} model={model} 503 aşırı yük {yuk_tekrar} tekrardan sonra sürüyor"
                                  f"{' (yedek model)' if yedek_mi else ''}: durduruluyor")
                        self.asiri_yuk_doldu = True
                        gecis = (f"; yedek geçişi {self.yedek_gecisi['kimden']} → {self.yedek_gecisi['kime']} de "
                                 f"başarısız" if yedek_mi else "")
                        raise GercekUretimHatasi(self._maskele(
                            f"Gemini aşırı yük (HTTP 503, model={model}); {yuk_tekrar} tekrardan sonra sürüyor{gecis}, "
                            f"üretim durduruldu (mock'a geçilmez): {ozet}"), "asiri_yuk", self.hatalar)
                    ra = retry_after_sn(yanit_basliklari)
                    bekle = ra if ra is not None else beklemeler[yuk_tekrar]
                    kalan = self._kalan()
                    if kalan is not None and bekle >= kalan - 1:
                        self.asiri_yuk_doldu = True
                        self._log(f"■ {etiket} model={model} 503: {bekle:.0f} sn bekleme süre bütçesini ({kalan:.0f} sn) aşıyor")
                        raise GercekUretimHatasi(self._maskele(
                            f"Gemini aşırı yük (HTTP 503); gereken {bekle:.0f} sn bekleme süre bütçesini aşıyor, üretim "
                            f"durduruldu (mock'a geçilmez): {ozet}"), "asiri_yuk", self.hatalar)
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
        raise GercekUretimHatasi(self._maskele("Gemini çağrısı başarısız (mock'a geçilmez): " + " | ".join(sorunlar)),
                                 son_sinif, self.hatalar)


def saglayici_sec(kip: str) -> LLMProvider:
    """'gercek' → GeminiLLMProvider (anahtar yoksa hata). 'test' / 'offline' → MockLLMProvider. Başka yol yok."""
    if kip == "gercek":
        return GeminiLLMProvider()
    if kip in ("test", "offline"):
        return MockLLMProvider()
    raise ValueError("kip 'gercek', 'test' ya da 'offline' olmalı")
