"""Poly Haven CC0 varlık testi (deneysel, Faz 5.1 P3). GitHub Actions'ta çalışır.

Kullanım: python3 polyhaven.py <indirme_klasoru> <kayit.json>
Her varlık için: kaynak sayfa, API, dosya adresleri, tür, çözünürlük, boyut, MD5 doğrulaması, yazar, kategori,
lisans (CC0 — Poly Haven tüm varlıklarını CC0 ile yayımlar: https://polyhaven.com/license) ve kullanım amacı kaydedilir.
İndirme ya da MD5 başarısız olursa varlık 'BASARISIZ' kaydedilir; yerine başka varlık zorla konmaz.
Büyük dosya indirilmez: dokular 1K JPG, gökyüzü 2K HDR, model 1K glTF.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

API = "https://api.polyhaven.com"
UA = {"User-Agent": "mini-dunya-faz51-deney (github.com/camkertenberkay53-cyber/mini-dunya)"}
LISANS = {"ad": "CC0 1.0", "kaynak": "https://polyhaven.com/license"}

# (kimlik, tür, amaç) — öncelik: gökyüzü, zemin, kaya, çöl, orman, tarihî çevre
SECIM = [
    ("kloofendal_48d_partly_cloudy", "hdri", "gökyüzü: parçalı bulutlu gündüz, ortam ışığı"),
    ("noga", "hdri", "gökyüzü: gün doğumu/batımı, açık"),
    ("rocks_ground_02", "doku", "zemin: çakıllı toprak (bozkır, yol kenarı)"),
    ("rocky_trail", "doku", "zemin: taşlı patika"),
    ("mud_cracked_dry_03", "doku", "çöl/kurak: çatlak kuru toprak"),
    ("sandstone_cracks", "doku", "çöl/kaya yüzeyi: kumtaşı"),
    ("forest_ground_04", "doku", "orman zemini"),
    ("rock_boulder_dry", "model", "kaya: ön plan kayası (derinlik katmanı)"),
]
TARIHI_KATEGORI = [("brick", "tarihî çevre: tuğla duvar"), ("cobblestone", "tarihî çevre: arnavut kaldırımı"),
                   ("plaster", "tarihî çevre: sıva duvar")]
DOKU_HARITA = {"Diffuse": "diff", "nor_gl": "nor_gl", "Rough": "rough"}


def al(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        return r.read()


def jget(yol: str):
    return json.loads(al(API + yol))


def indir(url: str, md5: str | None, hedef: Path) -> dict:
    t = time.time()
    veri = al(url)
    hedef.parent.mkdir(parents=True, exist_ok=True)
    hedef.write_bytes(veri)
    h = hashlib.md5(veri).hexdigest()
    return {"url": url, "dosya": str(hedef), "bayt": len(veri), "md5_dogru": (md5 is None) or (h == md5),
            "sure_sn": round(time.time() - t, 2)}


def varlik(kimlik: str, tur: str, amac: str, kok: Path) -> dict:
    k = {"kimlik": kimlik, "tur": tur, "amac": amac, "sayfa": f"https://polyhaven.com/a/{kimlik}", "lisans": LISANS,
         "durum": "BASARISIZ", "dosyalar": []}
    try:
        info = jget(f"/info/{kimlik}")
        k.update({"ad": info.get("name"), "yazarlar": info.get("authors"), "kategoriler": info.get("categories"),
                  "indirme_sayisi": info.get("download_count")})
        f = jget(f"/files/{kimlik}")
        if tur == "hdri":
            d = f["hdri"]["2k"]["hdr"]
            k["dosyalar"].append({"harita": "hdri", "cozunurluk": "2k", "bicim": "hdr",
                                  **indir(d["url"], d.get("md5"), kok / kimlik / "hdri.hdr")})
        elif tur == "doku":
            for anahtar, ad in DOKU_HARITA.items():
                d = f[anahtar]["1k"]["jpg"]
                k["dosyalar"].append({"harita": ad, "cozunurluk": "1k", "bicim": "jpg",
                                      **indir(d["url"], d.get("md5"), kok / kimlik / f"{ad}.jpg")})
        elif tur == "model":
            d = f["gltf"]["1k"]["gltf"]
            k["dosyalar"].append({"harita": "gltf", "cozunurluk": "1k", "bicim": "gltf",
                                  **indir(d["url"], d.get("md5"), kok / kimlik / Path(d["url"]).name)})
            for yol, e in (d.get("include") or {}).items():
                k["dosyalar"].append({"harita": "gltf_ek", "cozunurluk": "1k", "bicim": Path(yol).suffix.lstrip("."),
                                      **indir(e["url"], e.get("md5"), kok / kimlik / yol)})
        k["toplam_bayt"] = sum(x["bayt"] for x in k["dosyalar"])
        k["durum"] = "TAMAM" if all(x["md5_dogru"] for x in k["dosyalar"]) else "MD5_HATASI"
    except Exception as e:  # kayda geçer; yerine başka varlık konmaz
        k["hata"] = f"{type(e).__name__}: {e}"
    return k


def main() -> int:
    kok, kayit = Path(sys.argv[1]), Path(sys.argv[2])
    secim = list(SECIM)
    for kat, amac in TARIHI_KATEGORI:
        try:
            liste = jget(f"/assets?t=textures&c={kat}")
            en = max(liste.items(), key=lambda kv: kv[1].get("download_count", 0))[0]
            secim.append((en, "doku", f"{amac} (kategorideki en çok indirilen)"))
        except Exception as e:
            secim.append((f"kategori:{kat}", "doku", f"{amac} — kategori sorgusu başarısız: {e}"))
    sonuc = [varlik(i, t, a, kok) if not i.startswith("kategori:") else
             {"kimlik": i, "tur": t, "amac": a, "durum": "BASARISIZ"} for i, t, a in secim]
    ozet = {"tarih": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "lisans_politikasi": LISANS,
            "kural": "Yalnız CC0; başarısız indirmenin yerine alternatif zorla konmaz.",
            "toplam_mb": round(sum(v.get("toplam_bayt", 0) for v in sonuc) / 1e6, 2),
            "basarili": sum(v["durum"] == "TAMAM" for v in sonuc), "toplam": len(sonuc), "varliklar": sonuc}
    kayit.write_text(json.dumps(ozet, ensure_ascii=False, indent=1))
    for v in sonuc:
        print(v["durum"], v["kimlik"], round(v.get("toplam_bayt", 0) / 1e6, 2), "MB", v.get("hata", ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
