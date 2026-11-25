"""Genel CC0 varlık indirici: Poly Haven (model/doku/hdri) ve ambientCG (malzeme). Actions'ta çalışır (sandbox erişemez).

Kullanım: python3 -m motor.varlik.cc0_indir motor/varlik/cc0/istek.json
istek.json:
  {"katalog": true,                      # isteğe bağlı: iki kaynağın hafif kataloğunu katalog_*.json'a yazar
   "varliklar": [{"kaynak": "polyhaven", "kimlik": "rock_face_03", "tur": "model|doku|hdri",
                  "cozunurluk": "1k", "haritalar": ["diff", "nor_gl", "arm"], "amac": "..."},
                 {"kaynak": "ambientcg", "kimlik": "RoofingTiles006", "cozunurluk": "1K", "amac": "..."}]}
Lisans her varlık için KAYNAĞIN KENDİ API'sinden/sayfasından doğrulanır (Poly Haven: tüm varlıklar CC0,
https://polyhaven.com/license; ambientCG: API 'license' alanı CC0 olmalı). Doğrulanamayan varlık indirilmez.
Dosyalar MD5 (Poly Haven) / SHA-256 kaydıyla motor/varlik/cc0/<kaynak>/<kimlik>/ altına yazılır; lisans.json güncellenir
(önceki kayıtlar korunur, aynı kimlik yeniden indirilirse üzerine yazılır)."""
from __future__ import annotations

import hashlib
import io
import json
import re
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

UA = {"User-Agent": "mini-dunya-varlik (github.com/camkertenberkay53-cyber/mini-dunya)"}
PH_API = "https://api.polyhaven.com"
PH_LISANS = {"ad": "CC0 1.0", "kaynak": "https://polyhaven.com/license"}
ACG_API = "https://ambientcg.com/api/v2/full_json"
ACG_LISANS = {"ad": "CC0 1.0", "kaynak": "https://docs.ambientcg.com/license/"}
PH_HARITA = {"diff": "Diffuse", "nor_gl": "nor_gl", "rough": "Rough", "arm": "arm", "ao": "AO", "disp": "Displacement"}
TUR_KOD = {0: "hdri", 1: "doku", 2: "model"}


def al(url: str) -> bytes:
    for i in range(3):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180).read()
        except Exception:  # noqa: BLE001
            if i == 2:
                raise
            time.sleep(3)
    return b""


def jal(url: str):
    return json.loads(al(url))


def yaz(veri: bytes, hedef: Path, url: str, md5: str | None, kok: Path) -> dict:
    hedef.parent.mkdir(parents=True, exist_ok=True)
    hedef.write_bytes(veri)
    return {"dosya": str(hedef.relative_to(kok)), "url": url, "bayt": len(veri),
            "sha256": hashlib.sha256(veri).hexdigest(),
            "md5_dogru": (md5 is None) or hashlib.md5(veri).hexdigest() == md5}


def polyhaven(it: dict, kok: Path) -> dict:
    kim, coz = it["kimlik"], it.get("cozunurluk", "1k")
    hedef = kok / "polyhaven" / kim
    info = jal(f"{PH_API}/info/{kim}")
    tur = TUR_KOD.get(info.get("type"), "?")
    k = {"kaynak": "polyhaven", "kimlik": kim, "ad": info.get("name"), "tur": tur, "sayfa": f"https://polyhaven.com/a/{kim}",
         "yazarlar": info.get("authors"), "kategoriler": info.get("categories"), "lisans": PH_LISANS,
         "lisans_dogrulama": "Poly Haven tüm varlıklarını CC0 yayımlar (polyhaven.com/license); varlık API'de mevcut.",
         "amac": it.get("amac"), "cozunurluk": coz, "boyut_mm": info.get("dimensions"), "poligon": info.get("polycount"),
         "dosyalar": []}
    f = jal(f"{PH_API}/files/{kim}")
    if tur == "model":
        d = f["gltf"][coz]["gltf"]
        k["dosyalar"].append(yaz(al(d["url"]), hedef / Path(d["url"]).name, d["url"], d.get("md5"), kok))
        for yol, e in (d.get("include") or {}).items():
            k["dosyalar"].append(yaz(al(e["url"]), hedef / yol, e["url"], e.get("md5"), kok))
    elif tur == "doku":
        for h in it.get("haritalar", ["diff", "nor_gl", "arm"]):
            ana = PH_HARITA[h]
            if ana not in f:
                k.setdefault("eksik_harita", []).append(h)
                continue
            d = f[ana][coz]["jpg" if "jpg" in f[ana][coz] else "png"]
            k["dosyalar"].append(yaz(al(d["url"]), hedef / f"{h}.{Path(d['url']).suffix.lstrip('.')}", d["url"], d.get("md5"), kok))
    elif tur == "hdri":
        d = f["hdri"][coz]["hdr"]
        k["dosyalar"].append(yaz(al(d["url"]), hedef / "hdri.hdr", d["url"], d.get("md5"), kok))
    return k


def ambientcg(it: dict, kok: Path) -> dict:
    kim, coz = it["kimlik"], it.get("cozunurluk", "1K")
    v = jal(f"{ACG_API}?id={kim}&include=downloadData,tagData")["foundAssets"][0]
    lis = str(v.get("license", "")).upper()
    k = {"kaynak": "ambientcg", "kimlik": kim, "ad": v.get("displayName"), "tur": v.get("dataType"),
         "sayfa": f"https://ambientcg.com/view?id={kim}", "lisans": ACG_LISANS, "lisans_api": v.get("license"),
         "amac": it.get("amac"), "cozunurluk": coz, "dosyalar": []}
    if "CC0" not in lis:
        k["durum"] = f"LISANS_RED ({v.get('license')})"
        return k
    indir = [d for c in v["downloadFolders"]["default"]["downloadFiletypeCategories"].values() for d in c["downloads"]
             if d.get("attribute") == f"{coz}-JPG"]
    if not indir:
        k["durum"] = "DOSYA_YOK"
        return k
    url = indir[0]["fullDownloadPath"]
    veri = al(url)
    k["zip"] = {"url": url, "bayt": len(veri), "sha256": hashlib.sha256(veri).hexdigest()}
    desen = re.compile(r"_(Color|NormalGL|Roughness|AmbientOcclusion|Displacement|Opacity|Metalness)\.jpg$", re.I)
    with zipfile.ZipFile(io.BytesIO(veri)) as z:
        for n in z.namelist():
            m = desen.search(n)
            if m:
                ad = {"color": "diff", "normalgl": "nor_gl", "roughness": "rough", "ambientocclusion": "ao",
                      "displacement": "disp", "opacity": "opak", "metalness": "metal"}[m.group(1).lower()]
                k["dosyalar"].append(yaz(z.read(n), kok / "ambientcg" / kim / f"{ad}.jpg", url + "#" + n, None, kok))
    return k


def katalog(kok: Path) -> None:
    ph = {}
    for t in ("models", "textures"):
        for kim, v in jal(f"{PH_API}/assets?t={t}").items():
            ph[kim] = {"tur": TUR_KOD.get(v.get("type")), "ad": v.get("name"), "kat": v.get("categories"),
                       "etiket": v.get("tags"), "poligon": v.get("polycount"), "boyut_mm": v.get("dimensions"),
                       "indirme": v.get("download_count")}
    (kok / "katalog_polyhaven.json").write_text(json.dumps(ph, ensure_ascii=False, separators=(",", ":")))
    acg, ofs = {}, 0
    while True:
        r = jal(f"{ACG_API}?type=Material&limit=250&offset={ofs}&include=tagData")
        for v in r.get("foundAssets", []):
            acg[v["assetId"]] = {"ad": v.get("displayName"), "kat": v.get("displayCategory"), "etiket": v.get("tags"),
                                 "lisans": v.get("license")}
        ofs += 250
        if not r.get("foundAssets") or ofs >= int(r.get("numberOfResults", 0)):
            break
    (kok / "katalog_ambientcg.json").write_text(json.dumps(acg, ensure_ascii=False, separators=(",", ":")))
    print("katalog:", len(ph), "polyhaven,", len(acg), "ambientcg")


def main(istek_yolu: str) -> int:
    istek = json.loads(Path(istek_yolu).read_text())
    kok = Path(istek_yolu).parent
    if istek.get("katalog"):
        try:
            katalog(kok)
        except Exception as e:  # noqa: BLE001
            print("katalog hatası:", repr(e)[:300])
    lyol = kok / "lisans.json"
    eski = {(v["kaynak"], v["kimlik"]): v for v in json.loads(lyol.read_text())["varliklar"]} if lyol.exists() else {}
    for it in istek.get("varliklar", []):
        try:
            k = polyhaven(it, kok) if it["kaynak"] == "polyhaven" else ambientcg(it, kok)
            if "durum" not in k:
                k["durum"] = "TAMAM" if k["dosyalar"] and all(x["md5_dogru"] for x in k["dosyalar"]) else "MD5_HATASI"
            k["toplam_bayt"] = sum(x["bayt"] for x in k["dosyalar"])
        except Exception as e:  # noqa: BLE001
            k = {"kaynak": it["kaynak"], "kimlik": it["kimlik"], "durum": "BASARISIZ", "hata": repr(e)[:300]}
        k["tarih"] = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
        eski[(k["kaynak"], k["kimlik"])] = k
        print(k["durum"], k["kaynak"], k["kimlik"], round(k.get("toplam_bayt", 0) / 1e6, 2), "MB", k.get("hata", ""))
    lyol.write_text(json.dumps({"politika": "Yalnız CC0; lisans kaynağın API'sinden doğrulanır, doğrulanamayan indirilmez.",
                                "varliklar": list(eski.values())}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
