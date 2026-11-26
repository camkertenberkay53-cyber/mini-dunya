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
MODELLER = ("gemini-3.8-flash", "gemini-flash-latest", "gemini-3.7-flash")


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

    def __init__(self, modeller=MODELLER, tasiyici=None, zaman_asimi: float = 240.0, uyku=time.sleep, en_cok_tekrar: int = 2):
        anahtar = os.environ.get("GEMINI_API_KEY")
        if not anahtar or not anahtar.strip():
            raise GercekUretimHatasi("GEMINI_API_KEY tanımlı değil: gerçek üretim yapılamaz (mock'a geçilmez)")
        self.__anahtar = anahtar.strip()
        self.modeller = tuple(modeller)
        self.tasiyici = tasiyici or _urllib_tasiyici
        self.zaman_asimi, self.uyku, self.en_cok_tekrar = zaman_asimi, uyku, en_cok_tekrar
        self.kullanilan_model: str | None = None
        self.cagri_sayisi = 0

    def __repr__(self) -> str:   # anahtar hiçbir temsilde görünmez
        return f"GeminiLLMProvider(modeller={self.modeller!r})"

    def _maskele(self, metin: str) -> str:
        return (metin or "").replace(self.__anahtar, "***")

    def tamamla(self, istem: str, adim: str, baglam: dict) -> str:
        govde = json.dumps({"contents": [{"role": "user", "parts": [{"text": istem}]}],
                            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}}).encode()
        basliklar = {"Content-Type": "application/json", "x-goog-api-key": self.__anahtar}
        sorunlar = []
        for model in ([self.kullanilan_model] if self.kullanilan_model else []) + [m for m in self.modeller if m != self.kullanilan_model]:
            for tekrar in range(self.en_cok_tekrar + 1):
                self.cagri_sayisi += 1
                try:
                    kod, metin = self.tasiyici(API.format(model=model), govde, basliklar, self.zaman_asimi)
                except Exception as e:   # ağ hatası: mesaj maskelenir
                    sorunlar.append(f"{model}: ag_hatasi {type(e).__name__}: {self._maskele(str(e))[:160]}")
                    if tekrar < self.en_cok_tekrar:
                        self.uyku(2 ** tekrar)
                        continue
                    break
                if kod == 200:
                    try:
                        d = json.loads(metin)
                        parcalar = d["candidates"][0]["content"]["parts"]
                        yanit = "".join(p.get("text", "") for p in parcalar)
                    except (KeyError, IndexError, json.JSONDecodeError, TypeError):
                        sorunlar.append(f"{model}: yanit_bicimi")
                        break
                    self.kullanilan_model = model
                    return yanit
                if kod in (429, 500, 502, 503, 504) and tekrar < self.en_cok_tekrar:
                    self.uyku(min(30, 5 * (tekrar + 1)))
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
