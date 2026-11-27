"""Gerçekçi mekân varlıklarını üretir, ölçer, sınıflar ve kaydeder (mekân kalite paketi).

python3 -m motor.varlik.mekan_varlik [id ...] [--zorla]

- Katalog: mekan_varliklari.yaml; kaynak: motor/varlik/cc0/<kaynak>/<kimlik>/*.gltf (cc0/lisans.json'da TAMAM, CC0).
- Çıktı: ONBELLEK/mekan/<id>.glb; kayıt: mekan_varlik_kaydi.json (anahtar, sha256, ölçüm, sınıf, lisans, kaynak dosya özetleri).
- Lisans kaydı olmayan / CC0 olmayan kaynak üretime alınmaz (hata). Aynı anahtar yeniden üretilmez.
- Karakter ekipmanı kataloğuna (ekipman.yaml, kalite.json) dokunmaz; ayrı katalog, ayrı kalite sınırı."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import yaml

from motor import ayar

BURASI = Path(__file__).resolve().parent
CC0 = BURASI / "cc0"
KATALOG = BURASI / "mekan_varliklari.yaml"
KAYIT = BURASI / "mekan_varlik_kaydi.json"
BETIK = BURASI / "blender" / "mekan_uret.py"
AGAC_BETIK = BURASI / "blender" / "agac_uret.py"
AGAC_KAYNAK = {"yaprakli": ["ambientcg/Leaf001"], "igne": ["polyhaven/fir_sapling_medium"], "kuru": []}
CIKTI = ayar.ONBELLEK / "mekan"


def katalog() -> dict:
    return yaml.safe_load(KATALOG.read_text(encoding="utf-8"))


def lisans_kaydi(kaynak: str) -> dict:
    """cc0/lisans.json'dan kaynağın kaydı; yoksa, başarısızsa ya da CC0 değilse hata."""
    kay, kim = kaynak.split("/", 1)
    for v in json.loads((CC0 / "lisans.json").read_text())["varliklar"]:
        if v["kaynak"] == kay and v["kimlik"] == kim:
            if v.get("durum") != "TAMAM" or "CC0" not in v["lisans"]["ad"]:
                raise ValueError(f"{kaynak}: lisans/indirme doğrulanmamış ({v.get('durum')})")
            return v
    raise ValueError(f"{kaynak}: cc0/lisans.json'da kayıt yok")


def gltf_yolu(kaynak: str) -> Path:
    g = sorted((CC0 / kaynak).glob("*.gltf"))
    if not g:
        raise FileNotFoundError(f"{kaynak}: glTF yok")
    return g[0]


def kaynaklar(t: dict) -> list[str]:
    """Varlığın dayandığı CC0 kaynakları (lisansı doğrulanır). Prosedürel ağaç: kabuk + yaprak/iğne fotoğrafı."""
    if t.get("uretici") == "agac":
        return [t["kabuk"]] + AGAC_KAYNAK[t["tur"]]
    return [t["kaynak"]]


def anahtar(vid: str, t: dict) -> str:
    h = hashlib.sha256(json.dumps({k: v for k, v in t.items() if k not in ("donem", "tarih", "yerine", "rol")},
                                  sort_keys=True).encode())
    for kay in kaynaklar(t):
        for f in sorted((CC0 / kay).rglob("*")):
            if f.is_file():
                h.update(f.name.encode() + hashlib.sha256(f.read_bytes()).digest())
    if t.get("uretici") == "agac":
        h.update(AGAC_BETIK.read_bytes() + (BURASI / "agac_doku.py").read_bytes())
    else:
        h.update(BETIK.read_bytes())
    return h.hexdigest()[:16]


def _agac_isi(vid: str, t: dict, glb: Path) -> dict:
    kart_kok = CIKTI / "_agac_doku"
    if not (kart_kok / "yaprak_salkim.png").exists() or not (kart_kok / "igne_dal.png").exists():
        from motor.varlik import agac_doku
        agac_doku.main(str(kart_kok))
    k = CC0 / t["kabuk"]
    return {**{a: b for a, b in t.items() if a not in ("donem", "tarih", "yerine", "rol", "uretici")}, "id": vid,
            "kabuk": {"diff": str(k / "diff.jpg"), "nor": str(k / "nor_gl.jpg"), "arm": str(k / "arm.jpg")},
            "kart": str(kart_kok / ("igne_dal.png" if t["tur"] == "igne" else "yaprak_salkim.png")), "cikti": str(glb)}


def kalite_sinifi(olcum: dict, sinir: dict) -> tuple[str, list]:
    neden = []
    if olcum["bozuk_yuz"] > max(10, olcum["ucgen"] // 200) or olcum["yalniz_kose"] > 0:
        neden.append(f"geometri hatası (bozuk yüz {olcum['bozuk_yuz']}, yalnız köşe {olcum['yalniz_kose']})")
    if olcum["ucgen"] > sinir["ucgen_en_cok"]:
        neden.append(f"üçgen {olcum['ucgen']} > {sinir['ucgen_en_cok']}")
    if olcum["bayt"] > sinir["bayt_en_cok"]:
        neden.append(f"dosya {olcum['bayt'] // 1024} KB > {sinir['bayt_en_cok'] // 1024} KB")
    if olcum["doku"] and max(olcum["doku"]) > sinir["doku_en_cok"]:
        neden.append(f"doku {max(olcum['doku'])} px > {sinir['doku_en_cok']}")
    b = max(olcum["boyut_m"])
    if not sinir["boyut_m"][0] <= b <= sinir["boyut_m"][1]:
        neden.append(f"boyut {b} m sınır dışı")
    if not olcum.get("uv") or not olcum.get("doku"):
        neden.append("UV/doku yok (dokusuz model gerçekçi sayılmaz)")
    return ("RED" if neden else "A"), neden


def kayit_oku() -> dict:
    return json.loads(KAYIT.read_text()) if KAYIT.exists() else {}


def uret(idler: list[str] | None = None, zorla: bool = False) -> dict:
    k = katalog()
    kayit = kayit_oku()
    CIKTI.mkdir(parents=True, exist_ok=True)
    isler = []
    for vid, t in k["varliklar"].items():
        if idler and vid not in idler:
            continue
        for kay in kaynaklar(t):
            lisans_kaydi(kay)   # lisans doğrulanmadan üretim yok
        a = anahtar(vid, t)
        glb = CIKTI / f"{vid}.glb"
        if not zorla and kayit.get(vid, {}).get("anahtar") == a and glb.exists():
            continue
        isler.append((vid, t, a, glb))
    agac = [x for x in isler if x[1].get("uretici") == "agac"]
    isler_gltf = [x for x in isler if x[1].get("uretici") != "agac"]
    if agac:
        is_json = CIKTI / "_agac_is.json"
        is_json.write_text(json.dumps({"parcalar": [_agac_isi(vid, t, glb) for vid, t, a, glb in agac]}))
        p = subprocess.run([sys.executable, str(AGAC_BETIK), str(is_json)], capture_output=True, text=True, timeout=3600)
        if p.returncode != 0:
            print(p.stdout[-3000:], p.stderr[-4000:])
            raise SystemExit("AĞAÇ ÜRETİMİ BAŞARISIZ")
    if isler_gltf:
        isler, tum = isler_gltf, isler
        is_json = CIKTI / "_is.json"
        is_json.write_text(json.dumps({"parcalar": [{"id": vid, "gltf": str(gltf_yolu(t["kaynak"])), "nesneler": t.get("nesneler"),
                                                     "olcek": t.get("olcek", 1.0), "yon_derece": t.get("yon_derece", 0.0),
                                                     "ucgen_hedef": t.get("ucgen_hedef", 0), "doku_max": t.get("doku_max", 1024),
                                                     "cikti": str(glb)} for vid, t, a, glb in isler]}))
        p = subprocess.run([sys.executable, str(BETIK), str(is_json)], capture_output=True, text=True, timeout=3600)
        if p.returncode != 0:
            print(p.stdout[-3000:], p.stderr[-4000:])
            raise SystemExit("MEKÂN VARLIĞI ÜRETİMİ BAŞARISIZ")
        isler = tum
    for vid, t, a, glb in isler:
        olc = json.loads(glb.with_suffix(".olc.json").read_text())
        sinif, neden = kalite_sinifi(olc, k["kalite"])
        lks = [lisans_kaydi(kay) for kay in kaynaklar(t)]
        lk = lks[0]
        kayit[vid] = {"id": vid, "anahtar": a, "sha256": hashlib.sha256(glb.read_bytes()).hexdigest(), "olcum": olc,
                      "sinif": sinif, "neden": neden, "donem": t["donem"], "tarih": t["tarih"], "yerine": t.get("yerine", []),
                      "rol": t.get("rol"), "lisans": lk["lisans"]["ad"], "lisans_kaynak": lk["lisans"]["kaynak"],
                      "yazar": lk.get("yazarlar"), "kaynak": {"sayfa": lk["sayfa"], "kimlik": lk["kimlik"], "nesneler": t.get("nesneler"),
                                                              "dosyalar": [{"dosya": f["dosya"], "sha256": f["sha256"]} for x in lks for f in x["dosyalar"]],
                                                              "tum_kaynaklar": [x["sayfa"] for x in lks]},
                      "not": ("Geometri kendi prosedürel üretimimiz (blender/agac_uret.py); dokular CC0 fotoğraflardan (agac_doku.py)."
                              if t.get("uretici") == "agac" else
                              "Modelin kendi PBR malzemesi/UV'si korunur; yalnız modül seçimi, ölçek/yön, taban, üçgen azaltma, doku sınırı.")}
        print(sinif, vid, olc["ucgen"], "üçgen", round(olc["bayt"] / 1024), "KB", olc["boyut_m"], neden)
    kayit = {v: x for v, x in kayit.items() if v in k["varliklar"]}
    KAYIT.write_text(json.dumps(kayit, ensure_ascii=False, indent=1))
    return kayit


def kullanilabilir(vid: str, donem: str | None) -> Path | None:
    """Üretilmiş, A sınıfı ve döneme uygun varlığın GLB yolu; değilse None."""
    v = kayit_oku().get(vid)
    glb = CIKTI / f"{vid}.glb"
    if not v or v["sinif"] == "RED" or not glb.exists() or (donem and donem not in v["donem"]):
        return None
    return glb


def yerine_gecen(pid: str, donem: str | None) -> list[Path]:
    """Stilize katalog parçası pid'in yerine geçen kullanılabilir gerçekçi varlıklar (katalog sırasıyla)."""
    return [g for vid, t in katalog()["varliklar"].items() if pid in t.get("yerine", []) and (g := kullanilabilir(vid, donem))]


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    uret(a or None, "--zorla" in sys.argv)
