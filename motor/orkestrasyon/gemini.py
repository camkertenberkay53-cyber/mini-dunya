"""Gerçek LLM sağlayıcısı: Google Gemini (ücretsiz katman, 0 TL). Sessiz mock fallback YOKTUR.

- Anahtar yalnızca `GEMINI_API_KEY` ortam değişkeninden okunur. URL'ye değil `x-goog-api-key` başlığına konur.
  Hiçbir dosyaya, loga, rapora ya da hata mesajına yazılmaz; hata metinlerinde geçerse `***` ile maskelenir.
- Anahtar yoksa ya da API başarısız olursa `GercekUretimHatasi` fırlatılır. Planlayıcı bu durumda durur ve raporlar;
  MockLLMProvider'a GEÇMEZ.
- Mock yalnızca açık test/offline kipinde kullanılır (`saglayici_sec("test")`).
- Model sırası depodaki mevcut Gemini kullanımıyla aynıdır. Modeli değiştirmek fallback sayılmaz; hepsi aynı gerçek
  sağlayıcıdır.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from motor.orkestrasyon.llm import LLMHatasi, LLMProvider, MockLLMProvider

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# Varsayılan: ücretsiz katmanda yüksek RPM/TPM'li hızlı model. Kullanımdan kalkmışsa (404) sıradaki denenir;
# sıra GEMINI_MODELLER="m1,m2" ortam değişkeniyle değiştirilebilir. Model değiştirmek mock fallback DEĞİLDİR.
MODELLER = ("gemini-2.5-flash", "gemini-flash-latest", "gemini-3.7-flash")


def modeller() -> tuple[str, ...]:
    e = os.environ.get("GEMINI_MODELLER", "").strip()
    return tuple(m.strip() for m in e.split(",") if m.strip()) or MODELLER


class GercekUretimHatasi(LLMHatasi):
    """Gerçek üretim yapılamadı. Mesaj anahtar içermez. Çağıran sessizce mock'a geçmemelidir."""


def _urllib_tasiyici(url: str, govde: bytes, basliklar: dict, zaman: float) -> tuple[int, str]:
    istek = urllib.request.Request(url, data=govde, headers=basliklar, method="POST")
    try:
        with urllib.request.urlopen(istek, timeout=zaman) as y:
            return y.status, y.read(8 * 1024 * 1024).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(64 * 1024).decode("utf-8", errors="replace")


class GeminiLLMProvider(LLMProvider):
    ad = "gemini"
    sentetik = False

    def __init__(self, modeller=None, tasiyici=None, zaman_asimi: float = 90.0, uyku=time.sleep, en_cok_tekrar: int = 2,
                 dusunme_butcesi: int | None = 1024, sure_butcesi: float | None = None, ilerleme=None, saat=time.monotonic,
                 en_az_aralik: float = 0.0):
        """zaman_asimi: istek başına en çok bekleme (sn). dusunme_butcesi: thinking token sınırı (None → gönderilmez;
        model desteklemiyorsa 400 sonrası o model için kendiliğinden kapatılır). sure_butcesi: bu sağlayıcının bütün
        çağrıları için toplam duvar saati sınırı (aşılırsa GercekUretimHatasi; asılı kalma yok). en_az_aralik: iki istek
        başlangıcı arasında en az bekleme (sn) — ücretsiz katman dakika başı istek sınırını (429) korur."""
        anahtar = os.environ.get("GEMINI_API_KEY")
        if not anahtar or not anahtar.strip():
            raise GercekUretimHatasi("GEMINI_API_KEY tanımlı değil: gerçek üretim yapılamaz (mock'a geçilmez)")
        self.__anahtar = anahtar.strip()
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

    def tamamla(self, istem: str, adim: str, baglam: dict) -> str:
        basliklar = {"Content-Type": "application/json", "x-goog-api-key": self.__anahtar}
        sorunlar = []
        etiket = adim + (f"/{baglam['bolum']}" if baglam.get("bolum") else "")
        for model in ([self.kullanilan_model] if self.kullanilan_model else []) + [m for m in self.modeller if m != self.kullanilan_model]:
            tekrar = 0
            while tekrar <= self.en_cok_tekrar:
                kalan = self._kalan()
                if kalan is not None and kalan <= 1:
                    raise GercekUretimHatasi(self._maskele(f"Gemini süre bütçesi ({self.sure_butcesi:.0f} sn) doldu; "
                                                           f"üretim durduruldu (mock'a geçilmez): " + " | ".join(sorunlar)))
                zaman = self.zaman_asimi if kalan is None else max(5.0, min(self.zaman_asimi, kalan))
                with self._kilit:   # istek aralığı: paralel çağrılar da sıraya girer
                    if self.en_az_aralik and self._son_istek is not None:
                        bekle = self.en_az_aralik - (self.saat() - self._son_istek)
                        if bekle > 0:
                            self.uyku(bekle)
                    self._son_istek = self.saat()
                    self.cagri_sayisi += 1
                t0 = self.saat()
                self._log(f"→ {etiket} model={model} deneme={tekrar + 1} zaman_asimi={zaman:.0f}s istem={len(istem)} kr")
                try:
                    kod, metin = self.tasiyici(API.format(model=model), self._govde(istem, model), basliklar, zaman)
                except Exception as e:   # ağ hatası / zaman aşımı: mesaj maskelenir
                    sorunlar.append(f"{model}: ag_hatasi {type(e).__name__}: {self._maskele(str(e))[:160]}")
                    self._log(f"✗ {etiket} model={model} {type(e).__name__} ({self.saat() - t0:.1f}s)")
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
                        sorunlar.append(f"{model}: yanit_bicimi")
                        break
                    with self._kilit:
                        self.kullanilan_model = model
                    return yanit
                if kod in (429, 500, 502, 503, 504) and tekrar < self.en_cok_tekrar:
                    self.uyku(min(30, 5 * (tekrar + 1)))
                    tekrar += 1
                    continue
                sorunlar.append(f"{model}: HTTP {kod} {self._maskele(metin)[:160]}")
                break
        raise GercekUretimHatasi(self._maskele("Gemini çağrısı başarısız (mock'a geçilmez): " + " | ".join(sorunlar)))


def saglayici_sec(kip: str) -> LLMProvider:
    """'gercek' → GeminiLLMProvider (anahtar yoksa hata). 'test' / 'offline' → MockLLMProvider. Başka yol yok."""
    if kip == "gercek":
        return GeminiLLMProvider()
    if kip in ("test", "offline"):
        return MockLLMProvider()
    raise ValueError("kip 'gercek', 'test' ya da 'offline' olmalı")
