#!/usr/bin/env python3
"""Gemini Health Check (minimal ping) — birincil ve yedek modelin ANLIK erişilebilirliği.

Tamamen bağımsızdır: hiçbir üretim modülünü import etmez, dosya/sahne/plan üretmez. Yalnızca standart kütüphane.

- Modeller: `GEMINI_MODELLER` (virgülle; ilk ikisi) ya da varsayılan sıranın ilk ikisi
  (`gemini-flash-latest` birincil, `gemini-3.7-flash` yedek). Her modele AYRI AYRI tek bir kısa istek gider.
- Sıfır tekrar: hata ya da zaman aşımında yeniden denenmez; model başına EN ÇOK 1 istek.
- Katı zaman aşımı: varsayılan 25 sn (20–30 sn aralığı dışı reddedilir). Soket zaman aşımına ek olarak duvar saati
  sınırı da uygulanır; yanıt 25 sn içinde gelmezse `timeout` sayılır (yavaş akan yanıt da süreyi uzatamaz).
- Sınıflar: `OK` | `503_overload` | `429_quota` | `timeout` | `auth_or_other_error` (401/403/404/400/diğer 5xx/ağ
  hatası/anahtar yok). Bir model başarısız olsa da diğeri MUTLAKA denenir.
- Anahtar: `GEMINI_DRYRUN_KEY`, yoksa `GEMINI_API_KEY`. URL'ye değil `x-goog-api-key` başlığına konur; hiçbir çıktıya,
  loga, özete ya da hata metnine yazılmaz (geçerse `***` ile maskelenir). Raporda yalnızca değişkenin ADI görünür.
- Çıktı: Markdown tablo (stdout) ve `GITHUB_STEP_SUMMARY` tanımlıysa oraya; `--json` ile makine okunur özet.
- Çıkış kodu: 0 = bütün modeller OK; 1 = en az bir model OK değil; 2 = anahtar yok (hiç istek gönderilmez);
  3 = geçersiz argüman (ör. zaman aşımı 20–30 sn dışı; hiç istek gönderilmez).

Kullanım:  python3 araclar/gemini_ping.py [--zaman-asimi 25] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
VARSAYILAN_MODELLER = ("gemini-flash-latest", "gemini-3.7-flash")   # üretim sırasının ilk ikisi (testte eşlenir)
ISTEM = "Respond with OK only."
ZAMAN_ASIMI = 25.0
SINIFLAR = ("OK", "503_overload", "429_quota", "timeout", "auth_or_other_error")


class ZamanAsimi(Exception):
    """Duvar saati sınırı aşıldı."""


def modeller(ortam=None) -> tuple[str, str]:
    """(birincil, yedek). GEMINI_MODELLER verilmişse ilk ikisi; tek model verilmişse yedek varsayılandan gelir."""
    ortam = os.environ if ortam is None else ortam
    e = [m.strip() for m in (ortam.get("GEMINI_MODELLER") or "").split(",") if m.strip()]
    birincil = e[0] if e else VARSAYILAN_MODELLER[0]
    yedek = e[1] if len(e) > 1 else next(m for m in VARSAYILAN_MODELLER if m != birincil)
    return birincil, yedek


def anahtar_sec(ortam=None) -> tuple[str | None, str | None]:
    """(anahtar, kaynak_adı). Değer hiçbir yerde raporlanmaz; yalnızca kaynak ADI raporlanır."""
    ortam = os.environ if ortam is None else ortam
    for ad in ("GEMINI_DRYRUN_KEY", "GEMINI_API_KEY"):
        v = (ortam.get(ad) or "").strip()
        if v:
            return v, ad
    return None, None


def _govde() -> bytes:
    # thinkingConfig gönderilmez (desteklemeyen modelde 400 → yanlış negatif olmasın); kısa çıktı sınırı
    return json.dumps({"contents": [{"role": "user", "parts": [{"text": ISTEM}]}],
                       "generationConfig": {"temperature": 0.0, "maxOutputTokens": 64}}).encode()


def urllib_tasiyici(url: str, govde: bytes, basliklar: dict, zaman: float) -> tuple[int, str]:
    istek = urllib.request.Request(url, data=govde, headers=basliklar, method="POST")
    try:
        with urllib.request.urlopen(istek, timeout=zaman) as y:
            return y.status, y.read(256 * 1024).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(16 * 1024).decode("utf-8", errors="replace")


def _kati_sure(fn, zaman: float):
    """fn()'i en çok `zaman` sn bekler; aşılırsa ZamanAsimi. İş parçacığı daemon'dur (süreç çıkışını bekletmez)."""
    sonuc: dict = {}

    def calis():
        try:
            sonuc["deger"] = fn()
        except BaseException as e:   # noqa: BLE001 — sınıflandırma çağırana bırakılır
            sonuc["hata"] = e
    t = threading.Thread(target=calis, daemon=True)
    t.start()
    t.join(zaman)
    if t.is_alive():
        raise ZamanAsimi(f"{zaman:.0f} sn içinde yanıt yok")
    if "hata" in sonuc:
        raise sonuc["hata"]
    return sonuc["deger"]


def _zaman_asimi_mi(e: BaseException) -> bool:
    if isinstance(e, (ZamanAsimi, TimeoutError, socket.timeout)):
        return True
    if isinstance(e, urllib.error.URLError) and isinstance(getattr(e, "reason", None), (TimeoutError, socket.timeout)):
        return True
    return "timed out" in str(e).lower()


def sinifla(kod: int | None) -> str:
    if kod == 200:
        return "OK"
    if kod == 503:
        return "503_overload"
    if kod == 429:
        return "429_quota"
    return "auth_or_other_error"


def ping(model: str, anahtar: str, tasiyici=urllib_tasiyici, zaman: float = ZAMAN_ASIMI, saat=time.monotonic) -> dict:
    """Tek model, TEK istek, sıfır tekrar. Dönüş: {model, durum, sure_sn, http, ayrinti} (anahtar içermez)."""
    basliklar = {"Content-Type": "application/json", "x-goog-api-key": anahtar}

    def maskele(m: str) -> str:
        return (m or "").replace(anahtar, "***")
    t0 = saat()
    try:
        kod, metin = _kati_sure(lambda: tasiyici(API.format(model=model), _govde(), basliklar, zaman), zaman)
    except BaseException as e:   # noqa: BLE001
        sure = round(saat() - t0, 2)
        if _zaman_asimi_mi(e):
            return {"model": model, "durum": "timeout", "sure_sn": sure, "http": None,
                    "ayrinti": f"{zaman:.0f} sn sınırı aşıldı"}
        return {"model": model, "durum": "auth_or_other_error", "sure_sn": sure, "http": None,
                "ayrinti": maskele(f"ag_hatasi {type(e).__name__}: {e}")[:160]}
    sure = round(saat() - t0, 2)
    durum = sinifla(kod)
    if durum == "OK":
        try:
            d = json.loads(metin)
            yanit = "".join(p.get("text", "") for p in d["candidates"][0]["content"].get("parts", []))
            ayrinti = f"yanıt: {yanit.strip()[:20]!r}" if yanit.strip() else "yanıt boş (HTTP 200)"
        except (KeyError, IndexError, json.JSONDecodeError, TypeError, AttributeError):
            ayrinti = "HTTP 200, yanıt biçimi beklenmedik"
    else:
        try:
            ayrinti = json.loads(metin)["error"].get("status") or ""
        except (KeyError, json.JSONDecodeError, TypeError, AttributeError):
            ayrinti = ""
        ayrinti = maskele(f"HTTP {kod} {ayrinti}".strip())[:160]
    return {"model": model, "durum": durum, "sure_sn": sure, "http": kod, "ayrinti": maskele(ayrinti)}


def calistir(ortam=None, tasiyici=None, zaman: float = ZAMAN_ASIMI, saat=time.monotonic) -> dict:
    tasiyici = tasiyici or urllib_tasiyici
    if not 20.0 <= float(zaman) <= 30.0:
        raise ValueError("zaman aşımı 20–30 sn aralığında olmalı")
    anahtar, kaynak = anahtar_sec(ortam)
    birincil, yedek = modeller(ortam)
    roller = (("birincil", birincil), ("yedek", yedek))
    if not anahtar:
        sonuclar = [{"rol": r, "model": m, "durum": "auth_or_other_error", "sure_sn": None, "http": None,
                     "ayrinti": "anahtar_yok: GEMINI_DRYRUN_KEY / GEMINI_API_KEY tanımlı değil; istek gönderilmedi"}
                    for r, m in roller]
        return {"anahtar_kaynagi": None, "zaman_asimi_sn": zaman, "sonuclar": sonuclar, "cikis": 2}
    sonuclar = []
    for rol, model in roller:   # sırayla; biri başarısız olsa da diğeri MUTLAKA denenir
        sonuclar.append(dict(ping(model, anahtar, tasiyici, zaman, saat), rol=rol))
    cikis = 0 if all(s["durum"] == "OK" for s in sonuclar) else 1
    return {"anahtar_kaynagi": kaynak, "zaman_asimi_sn": zaman, "sonuclar": sonuclar, "cikis": cikis}


def markdown(rapor: dict) -> str:
    def sure(s):
        return "—" if s is None else f"{s * 1000:.0f} ms" if s < 1 else f"{s:.2f} sn"
    satirlar = ["## Gemini Health Check (minimal ping)", "",
                f"Anahtar kaynağı: `{rapor['anahtar_kaynagi'] or 'yok'}` · istek başına zaman aşımı: "
                f"{rapor['zaman_asimi_sn']:.0f} sn · tekrar: 0", "",
                "| Rol | Model | Durum | Süre | Hata sınıfı / ayrıntı |", "|---|---|---|---|---|"]
    for s in rapor["sonuclar"]:
        isaret = "✅" if s["durum"] == "OK" else "⚠️" if s["durum"] in ("503_overload", "timeout") else "❌"
        hata = "—" if s["durum"] == "OK" else s["durum"]
        ayrinti = (s.get("ayrinti") or "").replace("|", "/")
        satirlar.append(f"| {s['rol']} | `{s['model']}` | {isaret} {s['durum']} | {sure(s['sure_sn'])} | "
                        f"{hata}{' — ' + ayrinti if ayrinti else ''} |")
    return "\n".join(satirlar) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--zaman-asimi", type=float, default=ZAMAN_ASIMI)
    ap.add_argument("--json", action="store_true", help="tabloya ek olarak JSON özeti yaz")
    a = ap.parse_args(argv)
    try:
        rapor = calistir(zaman=a.zaman_asimi)
    except ValueError as e:
        print(f"geçersiz argüman: {e}", file=sys.stderr)
        return 3
    md = markdown(rapor)
    print(md)
    if a.json:
        print(json.dumps(rapor, ensure_ascii=False, indent=1))
    ozet = os.environ.get("GITHUB_STEP_SUMMARY")
    if ozet:
        with open(ozet, "a", encoding="utf-8") as f:
            f.write(md)
    return rapor["cikis"]


if __name__ == "__main__":
    sys.exit(main())
