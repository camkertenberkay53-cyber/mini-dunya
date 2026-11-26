"""Otonom tarihî görsel toplayıcı — Wikimedia Commons (Faz-53A).

Sorgu dosyasındaki her kayıt için Commons MediaWiki API'sinde arar (action=query, generator=search, namespace 6 —
ya da generator=categorymembers), sonuçları süzer ve sıralar, en iyisini indirir:
  assets/tarihi_gorsel/<gorsel_id>.<uzanti>   (görsel; .gitignore kapsamında, depoya girmez)
  assets/tarihi_gorsel/<gorsel_id>.json       (metadata; tarihi_gorsel kaydı bunu okur)

Süzgeç: JPEG/PNG/TIFF, uzun kenar >= EN_AZ_PX; SVG/ikon/küçük resim elenir. Lisans politikası (kullanıcı kararı,
2026-11-26): sıkı beyaz liste YOK — Commons lisans bilgisi (LicenseShortName, UsageTerms, Artist, AttributionRequired)
olduğu gibi kaydedilir; yalnızca açıkça "All rights reserved", "Copyrighted" (lisans adı olarak), "Fair use" ya da
"Non-free" taşıyan dosyalar elenir. Atıf isteyen lisanslarda (CC-BY*) 'atif' alanı (yazar, lisans, kaynak) doldurulur;
yayında açıklamaya yazılması gerekir. Sıralama: başlığın sorguyla örtüşmesi > atıf istemeyen lisans > çözünürlük.
İndirilen dosyanın SHA-1'i Commons'takiyle karşılaştırılır; SHA-256 hesaplanıp kayda yazılır.

python3 -m motor.varlik.commons_toplayici deneyler/faz53a/gercek/sorgular.json [--hedef assets/tarihi_gorsel]
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import cv2
import numpy as np

from motor import ayar
from motor.varlik import ozne_tespit

API = "https://commons.wikimedia.org/w/api.php"
KULLANICI_AJANI = "mini-dunya-belgesel/1.0 (https://github.com/camkertenberkay53-cyber/mini-dunya; tarihi gorsel toplayici)"
EN_AZ_PX = 2000
MIME = {"image/jpeg": ".jpg", "image/png": ".png", "image/tiff": ".tif"}
RED_IFADELER = ("all rights reserved", "fair use", "non-free", "nonfree")
META = "LicenseShortName|UsageTerms|License|Artist|DateTimeOriginal|ObjectName|ImageDescription|Credit|AttributionRequired|Copyrighted|Restrictions"
HEDEF = ayar.REPO / "assets" / "tarihi_gorsel"
SAHNE_TURLERI = {"insan_portre": ["komutan_tanitimi", "baglam"], "mimari": ["sehir", "kusatma", "baglam"]}
# ozne_tespit görsel türü → ozne_bilgisi.tur (sorgu "tur" vermediyse)
TESPIT_OZNE_TURU = {"portre": "insan_portre", "mimari": "mimari", "cok_figurlu": "cok_figurlu"}


class ToplayiciHatasi(Exception):
    pass


# ------------------------------------------------------------------ ağ (testlerde taklit edilir)

def _istek_json(params: dict) -> dict:
    url = API + "?" + urllib.parse.urlencode(dict(params, format="json", formatversion="2"))
    req = urllib.request.Request(url, headers={"User-Agent": KULLANICI_AJANI})
    for deneme in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            if deneme == 2:
                raise ToplayiciHatasi(f"Commons API'ye ulaşılamadı: {e}") from e
            time.sleep(2 * (deneme + 1))
    return {}


def _indir(url: str, hedef: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": KULLANICI_AJANI})
    gecici = hedef.with_name(hedef.name + ".indiriliyor")
    with urllib.request.urlopen(req, timeout=300) as r, open(gecici, "wb") as f:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            f.write(b)
    gecici.replace(hedef)


# ------------------------------------------------------------------ arama, süzgeç, sıralama

def _duz(metin: str) -> str:
    """HTML'siz, aksansız, küçük harf (eşleştirme için)."""
    m = re.sub(r"<[^>]+>", " ", html.unescape(metin or ""))
    m = unicodedata.normalize("NFKD", m.replace("ı", "i").replace("İ", "I"))
    return " ".join("".join(c for c in m if not unicodedata.combining(c)).lower().split())


def _meta(ii: dict, ad: str) -> str:
    return re.sub(r"<[^>]+>", "", html.unescape(str((ii.get("extmetadata") or {}).get(ad, {}).get("value", "")))).strip()


def ara(sorgu: str | None = None, kategori: str | None = None, adet: int = 30, dosya: str | None = None) -> list[dict]:
    """Commons dosya adayları: [{baslik, url, aciklama_url, gen, yuk, mime, sha1, meta}]. 'dosya' verilirse yalnız o
    dosya başlığı sorgulanır (tekrarlanabilir seçim; yine aynı süzgeçten geçer)."""
    p = {"action": "query", "prop": "imageinfo", "iiprop": "url|size|mime|sha1|extmetadata", "iiextmetadatafilter": META}
    if dosya:
        p["titles"] = dosya if dosya.startswith("File:") else f"File:{dosya}"
    elif kategori:
        p.update({"generator": "categorymembers", "gcmtitle": kategori if kategori.startswith("Category:") else f"Category:{kategori}",
                  "gcmtype": "file", "gcmlimit": adet})
    else:
        p.update({"generator": "search", "gsrsearch": sorgu, "gsrnamespace": 6, "gsrlimit": adet})
    v = _istek_json(p)
    out = []
    for pg in (v.get("query") or {}).get("pages", []) or []:
        for ii in pg.get("imageinfo", [])[:1]:
            out.append({"baslik": pg.get("title", ""), "url": ii.get("url"), "aciklama_url": ii.get("descriptionurl"),
                        "gen": int(ii.get("width", 0)), "yuk": int(ii.get("height", 0)), "mime": ii.get("mime", ""),
                        "sha1": ii.get("sha1"), "meta": {k: _meta(ii, k) for k in META.split("|")}})
    return out


def lisans_kategorisi(meta: dict) -> tuple[str, bool]:
    """(lisans_turu, atif_gerekli). Commons 'License' / 'LicenseShortName' alanlarından."""
    kisa, kod = _duz(meta.get("LicenseShortName", "")), _duz(meta.get("License", ""))
    if kod.startswith("cc0") or "cc0" in kisa:
        return "CC0-1.0", False
    if kod.startswith("pd") or "public domain" in kisa or kisa.startswith("pd"):
        return ("PD-Art" if ("pd-art" in kisa or "pd-art" in kod or "art" in kod) else "PD-Old"), False
    m = re.match(r"(cc[- ]by(?:[- ]sa)?)[- ]?([\d.]+)?", kod or kisa)
    if m:
        ad = m.group(1).upper().replace(" ", "-")
        return (f"{ad}-{m.group(2)}" if m.group(2) else ad), True
    gerekli = _duz(meta.get("AttributionRequired", "")) == "true"
    return (meta.get("LicenseShortName") or "bilinmiyor"), gerekli


def elenme_nedeni(a: dict, en_az: int = EN_AZ_PX) -> str | None:
    if a.get("mime") not in MIME:
        return f"biçim {a.get('mime')}"
    if max(a.get("gen", 0), a.get("yuk", 0)) < en_az:
        return f"çözünürlük {a.get('gen')}x{a.get('yuk')} < {en_az}"
    m = a.get("meta", {})
    metin = _duz(" ".join([m.get("LicenseShortName", ""), m.get("UsageTerms", ""), m.get("Restrictions", "")]))
    if any(r in metin for r in RED_IFADELER) or _duz(m.get("LicenseShortName", "")) == "copyrighted":
        return f"telifli: {m.get('LicenseShortName') or m.get('UsageTerms')}"
    return None


def puan(a: dict, sorgu: str, tercih: str | None = None) -> tuple:
    kelime = [k for k in _duz(sorgu).split() if len(k) > 2]
    baslik = _duz(a["baslik"].replace("_", " "))
    ortusme = sum(k in baslik for k in kelime) / max(1, len(kelime))
    serbest = lisans_kategorisi(a.get("meta", {}))[1] is False
    on = 1 if (tercih and _duz(tercih).replace("_", " ") in baslik) else 0
    return (on, round(ortusme, 3), serbest, a.get("gen", 0) * a.get("yuk", 0))


def sec(adaylar: list[dict], sorgu: str, tercih: str | None = None, en_az: int = EN_AZ_PX) -> tuple[dict | None, list]:
    elenen = [(a["baslik"], n) for a in adaylar if (n := elenme_nedeni(a, en_az))]
    kalan = [a for a in adaylar if not elenme_nedeni(a, en_az)]
    if not kalan:
        return None, elenen
    return max(kalan, key=lambda a: puan(a, sorgu, tercih)), elenen


# ------------------------------------------------------------------ özne kutusu

def ozne_kutusu(yol: Path, tur: str | None = None) -> list[float]:
    """Kenar enerjisinin %10–90'ını içeren bölge (5 % pay), güvenli merkez kadrajla birleşik. 0..1 [x0,y0,x1,y1].
    Faz-53B'den beri topla() bunun yerine ozne_tespit.tespit() kullanır; geriye dönük uyumluluk için korunur."""
    img = cv2.imread(str(yol), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ToplayiciHatasi(f"görsel okunamadı: {yol}")
    k = 512 / max(img.shape)
    g = cv2.resize(img, (max(1, int(img.shape[1] * k)), max(1, int(img.shape[0] * k))), interpolation=cv2.INTER_AREA).astype(np.float32)
    e = np.hypot(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))
    h, w = e.shape

    def aralik(profil):
        c = np.cumsum(profil) / max(1e-6, profil.sum())
        return float(np.searchsorted(c, 0.10)) / len(profil), float(np.searchsorted(c, 0.90)) / len(profil)
    x0, x1 = aralik(e.sum(0))
    y0, y1 = aralik(e.sum(1))
    mx, my = (0.12, 0.06) if tur == "insan_portre" else (0.10, 0.10)   # güvenli merkez kadraj
    x0, y0 = min(x0 - 0.05, mx), min(y0 - 0.05, my)
    x1, y1 = max(x1 + 0.05, 1 - mx), max(y1 + 0.05, 1 - my)
    return [round(max(0.0, x0), 3), round(max(0.0, y0), 3), round(min(1.0, x1), 3), round(min(1.0, y1), 3)]


# ------------------------------------------------------------------ toplama

def _sha(p: Path, alg: str) -> str:
    h = hashlib.new(alg)
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def topla(s: dict, hedef: Path = HEDEF) -> dict:
    """Tek sorgu kaydı → indirilmiş görsel + metadata .json. Dönüş: metadata (+ '_secim' raporu)."""
    hedef.mkdir(parents=True, exist_ok=True)
    gid = s["gorsel_id"]
    adaylar, sorgu_kullanilan = [], None
    if s.get("dosya"):   # belirli dosya başlığı (kaynak belirtilmiş seçim); süzgeçten geçemezse aramaya düşer
        adaylar, sorgu_kullanilan = ara(dosya=s["dosya"]), s["dosya"]
    for q in ([] if any(not elenme_nedeni(a, s.get("en_az_px", EN_AZ_PX)) for a in adaylar) else
              [s.get("sorgu")] + list(s.get("yedek_sorgular", []))):
        if q:
            adaylar = ara(sorgu=q)
            sorgu_kullanilan = q
            if any(not elenme_nedeni(a, s.get("en_az_px", EN_AZ_PX)) for a in adaylar):
                break
    if s.get("kategori") and not any(not elenme_nedeni(a) for a in adaylar):
        adaylar, sorgu_kullanilan = ara(kategori=s["kategori"]), s["kategori"]
    secilen, elenen = sec(adaylar, sorgu_kullanilan or "", s.get("tercih") or s.get("dosya"), s.get("en_az_px", EN_AZ_PX))
    if secilen is None:
        raise ToplayiciHatasi(f"{gid}: uygun aday yok ({len(adaylar)} aday; elenenler: {elenen[:8]})")
    uz = MIME[secilen["mime"]]
    dosya = hedef / f"{gid}{uz}"
    _indir(secilen["url"], dosya)
    if secilen.get("sha1") and _sha(dosya, "sha1") != secilen["sha1"]:
        dosya.unlink()
        raise ToplayiciHatasi(f"{gid}: indirilen dosyanın SHA-1'i Commons'takiyle uyuşmuyor")
    im = cv2.imread(str(dosya), cv2.IMREAD_UNCHANGED)
    if im is None:
        dosya.unlink()
        raise ToplayiciHatasi(f"{gid}: indirilen dosya görsel olarak okunamadı")
    meta = secilen["meta"]
    lisans, atif_gerekli = lisans_kategorisi(meta)
    # Faz-53B: tür + özne kutusu + güven, gerçek ölçümle (istisna fırlatmaz; başarısızlıkta tam kadraj fallback'i)
    tsp = ozne_tespit.tespit(dosya)
    tur = s.get("tur") or TESPIT_OZNE_TURU.get(tsp["gorsel_turu"], "genel")
    ozne = {"kutu": s.get("kutu") or tsp["ozne_bilgisi"]["kutu"], "tur": tur,
            "kutu_kaynagi": "elle" if s.get("kutu") else "otomatik",
            "figur_sayisi": tsp["ozne_bilgisi"].get("figur_sayisi"), "ana_karakter": tsp["ozne_bilgisi"].get("ana_karakter")}
    if s.get("kutu"):
        ozne["otomatik_kutu"] = tsp["ozne_bilgisi"]["kutu"]
    k = {
        "gorsel_id": gid,
        "kaynak_url": secilen["aciklama_url"], "indirme_kaynagi": secilen["url"], "kaynak_kurum": "Wikimedia Commons",
        "eser_adi": s.get("eser_adi") or meta.get("ObjectName") or secilen["baslik"].replace("File:", ""),
        "tarih": s.get("tarih") or meta.get("DateTimeOriginal") or "bilinmiyor",
        "bolge": s.get("bolge", "bilinmiyor"), "donem": s.get("donem", "bilinmiyor"), "kultur": s.get("kultur", "bilinmiyor"),
        "taraf_faction": s.get("taraf_faction", "bilinmiyor"),
        # sorgu türü verdiyse (elle) o korunur; yoksa ölçülen tür. Ölçülen tür her durumda ozne_tespit'te durur.
        "gorsel_turu": s.get("gorsel_turu") or tsp["gorsel_turu"],
        "gorsel_turu_kaynagi": "sorgu" if s.get("gorsel_turu") else "ozne_tespit",
        "uygun_sahne_turleri": s.get("uygun_sahne_turleri") or SAHNE_TURLERI.get(tur, ["baglam"]),
        "cozunurluk": [int(im.shape[1]), int(im.shape[0])],
        "ozne_bilgisi": ozne,
        "guven_skoru": tsp["guven_skoru"], "tespit_yontemi": tsp["tespit_yontemi"], "tespit_durumu": tsp["tespit_durumu"],
        "fallback_uygulandi": tsp["fallback_uygulandi"], "onerilen_seviye": tsp["onerilen_seviye"],
        "ozne_tespit": {a: tsp[a] for a in ("surum", "gorsel_turu", "tur_guveni", "neden", "olcumler", "uyarilar") if a in tsp}
                       | ({"olasi_kutu": tsp["olasi_kutu"]} if "olasi_kutu" in tsp else {}),
        "derinlik_uygunlugu": s.get("derinlik_uygunlugu", "orta"),
        "lisans_turu": lisans,
        "lisans_kisa_adi": meta.get("LicenseShortName") or "",   # Commons'taki değer AYNEN (yayın açıklaması/atıf için)
        "lisans_commons": {"LicenseShortName": meta.get("LicenseShortName"), "UsageTerms": meta.get("UsageTerms"),
                           "License": meta.get("License"), "AttributionRequired": meta.get("AttributionRequired"),
                           "Copyrighted": meta.get("Copyrighted"), "Credit": meta.get("Credit")},
        "kamu_mali_gerekcesi": f"Commons lisans bilgisi: {meta.get('LicenseShortName') or '-'} — {meta.get('UsageTerms') or '-'}",
        "lisans_dogrulandi": True,   # Commons lisans bilgisinden (aşağıda insan onayı OLMADIĞI açıkça yazılıdır)
        "onay": {"kaynak_edinimi": "otomatik_toplayici", "insan_onayi": False, "tarih": str(date.today())},
        "yerel_yol": str(dosya.relative_to(ayar.REPO)) if dosya.is_relative_to(ayar.REPO) else str(dosya),
        "sha256": _sha(dosya, "sha256"),
        "commons_sha1": secilen.get("sha1"),
        "toplama": {"sorgu": sorgu_kullanilan, "baslik": secilen["baslik"], "aday": len(adaylar), "elenen": len(elenen),
                    "puan": list(puan(secilen, sorgu_kullanilan or "", s.get("tercih")))},
    }
    if atif_gerekli:
        k["atif"] = {"yazar": meta.get("Artist") or "bilinmiyor", "lisans": meta.get("LicenseShortName") or lisans,
                     "kaynak": secilen["aciklama_url"]}
    (hedef / f"{gid}.json").write_text(json.dumps(k, ensure_ascii=False, indent=1) + "\n")
    return k


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    sorgular = json.loads(Path(argv[0]).read_text())
    hedef = Path(argv[argv.index("--hedef") + 1]) if "--hedef" in argv else HEDEF
    hata = 0
    for s in sorgular:
        try:
            k = topla(s, hedef)
            print(f"TOPLANDI {k['gorsel_id']}: {k['toplama']['baslik']} {k['cozunurluk']} lisans={k['lisans_turu']} "
                  f"tur={k['ozne_tespit']['gorsel_turu']} kutu={k['ozne_bilgisi']['kutu']} guven={k['guven_skoru']} "
                  f"durum={k['tespit_durumu']} oneri={k['onerilen_seviye']}")
        except ToplayiciHatasi as e:
            hata += 1
            print(f"HATA {e}")
    return 1 if hata else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
