"""Faz 3 karakter sistemi: dönem kitlerindeki karakter tanımlarını doğrular, gövdeleri derler, takım dosyalarını yazar.

python3 -m motor.karakter.takim            -> bütün kitler
python3 -m motor.karakter.takim --zorla

Karakter = gövde + giysiler (gövdeyle birlikte derlenir) + takılanlar (ayrı GLB, çalışma anında yuvaya takılır).
Aynı (gövde, saç, giysi) birleşimini kullanan karakterler TEK derlenmiş gövdeyi paylaşır; ekipman dosyaları
bütün karakterlerde ortaktır. Rastgele birleşime izin verilmez: dönem, yuva ve çakışma kuralları derlemeden
önce denetlenir; kuralı bozan karakter derlenmez.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import yaml

from motor import ayar
from motor.varlik import katalog
from motor.varlik import ekipman as ekipman_mod

KITLER = Path(__file__).resolve().parent.parent / "kit" / "faz3"
BETIK = Path(__file__).resolve().parent.parent / "varlik" / "blender"
GOVDE_CIKTI = ayar.ONBELLEK / "karakter3"
TAKIM_CIKTI = ayar.ONBELLEK / "takim"
OZET = Path(__file__).resolve().parent / "derlenmis3.json"
UAL = "ual1/UAL1_Standard.fbx"
ANIMASYONLAR = ["Idle_Loop", "Walk_Loop", "Walk_Formal_Loop", "Jog_Fwd_Loop", "Sprint_Loop", "Sword_Idle", "Sword_Attack",
                "Death01", "Hit_Chest", "Driving_Loop", "Idle_Torch_Loop", "Push_Loop", "Interact", "Fixing_Kneeling"]
GOVDELER = {
    "erkek": "quaternius-stage/UniversalBaseCharacters/SK_SuperheroMaleFullBody.usda",
    "kadin": "quaternius-stage/UniversalBaseCharacters/SK_SuperheroFemaleFullBody.usda",
}
SAC = {
    "kisa": "quaternius-stage/UniversalBaseCharacters/SK_HairBuzzedFBX(Unity).usda",
    "sakal": "quaternius-stage/UniversalBaseCharacters/SK_HairBeardFBX(Unity).usda",
    "kas": "quaternius-stage/UniversalBaseCharacters/SK_EyebrowsRegularFBX(Unity).usda",
}
YUVALAR = {"bas", "sag_el", "sag_el_dik", "sol_el", "sol_kol", "sirt", "bel_sol", "bel_sag"}
# Aynı anda dolu olamayacak yuvalar (fiziksel çakışma)
CAKISMALAR = [("sag_el", "sag_el_dik"), ("sol_el", "sol_kol")]
ZORUNLU_KATEGORILER = ["baslik", "kiyafet", "zirh", "kalkan", "silah", "sancak", "aksesuar", "cevre"]


def kitleri_yukle() -> dict[str, dict]:
    return {p.stem: yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted(KITLER.glob("*.yaml"))}


def karakterler(kit: dict):
    for rol, liste in (kit.get("karakterler") or {}).items():
        for k in liste:
            yield rol, k


def kural_denetle(kit: dict, k: dict, katalog_: dict) -> list[str]:
    """Bir karakter tanımının dönem, yuva ve çakışma kurallarına uyup uymadığı. Boş liste = uygun."""
    h = []
    kabul = set(kit["kabul_edilen_donemler"])
    G, P = katalog_["giysiler"], katalog_["parcalar"]
    for g in k.get("giysiler", []):
        if g not in G:
            h.append(f"{k['ad']}: bilinmeyen giysi {g}")
        elif not set(G[g]["donem"]) & kabul:
            h.append(f"{k['ad']}: DÖNEM UYUMSUZ giysi {g} ({','.join(G[g]['donem'])})")
    for yuva, pid in (k.get("takilanlar") or {}).items():
        if yuva not in YUVALAR:
            h.append(f"{k['ad']}: bilinmeyen yuva {yuva}")
        if pid not in P:
            h.append(f"{k['ad']}: bilinmeyen parça {pid}")
            continue
        if P[pid]["yuva"] != yuva:
            h.append(f"{k['ad']}: {pid} '{P[pid]['yuva']}' yuvasına aittir, '{yuva}' yuvasına takılamaz")
        if not set(P[pid]["donem"]) & kabul:
            h.append(f"{k['ad']}: DÖNEM UYUMSUZ parça {pid} ({','.join(P[pid]['donem'])})")
    ty = set((k.get("takilanlar") or {}).keys())
    for a, b in CAKISMALAR:
        if a in ty and b in ty:
            h.append(f"{k['ad']}: {a} ile {b} aynı anda dolu olamaz")
    if k.get("govde") not in GOVDELER:
        h.append(f"{k['ad']}: bilinmeyen gövde {k.get('govde')}")
    return h


def kit_kategori_denetle(kit: dict, katalog_: dict) -> list[str]:
    h = []
    kabul = set(kit["kabul_edilen_donemler"])
    havuz = {**katalog_["giysiler"], **katalog_["parcalar"]}
    for kat in ZORUNLU_KATEGORILER:
        liste = (kit.get("kategoriler") or {}).get(kat) or []
        if not liste:
            h.append(f"EKSİK KATEGORİ: {kat}")
        for pid in liste:
            if pid not in havuz:
                h.append(f"{kat}: bilinmeyen {pid}")
            elif not set(havuz[pid]["donem"]) & kabul:
                h.append(f"{kat}: DÖNEM UYUMSUZ {pid}")
    return h


def govde_kimligi(k: dict) -> str:
    anahtar = json.dumps([k["govde"], sorted(k.get("sac", [])), k.get("giysiler", [])])
    return f"{k['govde']}_" + hashlib.sha256(anahtar.encode()).hexdigest()[:10]


def _betik_ozeti() -> str:
    h = hashlib.sha256()
    for b in ("karakter_kur.py", "giysi.py", "ortak.py", "doku.py", "olc.py"):
        h.update((BETIK / b).read_bytes())
    return h.hexdigest()[:16]


def derle(zorla: bool = False) -> dict:
    GOVDE_CIKTI.mkdir(parents=True, exist_ok=True)
    TAKIM_CIKTI.mkdir(parents=True, exist_ok=True)
    kat = ekipman_mod.katalog()
    kayit = katalog.yukle()
    ekip_kaydi = ekipman_mod.uret()
    kitler = kitleri_yukle()
    ozet = json.loads(OZET.read_text()) if OZET.exists() else {"govdeler": {}, "takimlar": {}}
    reddedilen = {}
    gerekli = {}
    for kad, kit in kitler.items():
        for rol, k in karakterler(kit):
            h = kural_denetle(kit, k, kat)
            if h:
                reddedilen[k["ad"]] = h
                continue
            gerekli.setdefault(govde_kimligi(k), k)
    betik = _betik_ozeti()
    for gid, k in gerekli.items():
        parcalar, malz = [], {}
        for g in k.get("giysiler", []):
            for p in kat["giysiler"][g]["parcalar"]:
                parcalar.append(p)
                malz[p["malzeme"]] = kat["malzemeler"][p["malzeme"]]
        kullanilan = [katalog.bul(kayit, GOVDELER[k["govde"]]), katalog.bul(kayit, UAL)] + [katalog.bul(kayit, SAC[s]) for s in sorted(set(k.get("sac", [])) | {"kas"})]
        anahtar = hashlib.sha256(json.dumps([parcalar, malz, [v["sha256"] for v in kullanilan], betik, ANIMASYONLAR], sort_keys=True).encode()).hexdigest()[:16]
        glb = GOVDE_CIKTI / f"{gid}.glb"
        if not zorla and ozet["govdeler"].get(gid, {}).get("anahtar") == anahtar and glb.exists():
            continue
        tarif = {
            "kiyafet": str(katalog.dosya_yolu(kullanilan[0])), "govde": None,
            "ekler": [str(katalog.dosya_yolu(v)) for v in kullanilan[2:]],
            "animasyon_fbx": str(katalog.dosya_yolu(kullanilan[1])), "animasyonlar": ANIMASYONLAR,
            "giysiler": parcalar, "malzemeler": malz, "doku_siniri": 1024, "cikti": str(glb),
        }
        tj = GOVDE_CIKTI / f"{gid}.tarif.json"
        tj.write_text(json.dumps(tarif, ensure_ascii=False, indent=1))
        p = subprocess.run([sys.executable, str(BETIK / "karakter_kur.py"), str(tj)], capture_output=True, text=True, timeout=1800)
        if p.returncode != 0 or not glb.exists():
            print(p.stdout[-2000:], p.stderr[-3000:])
            raise SystemExit(f"GÖVDE DERLEME HATASI: {gid}")
        olc = glb.with_suffix(".olc.json")
        p = subprocess.run([sys.executable, str(BETIK / "olc.py"), str(glb), str(olc), str(BETIK.parent / "evrensel_iskelet.json")],
                           capture_output=True, text=True, timeout=600)
        if p.returncode != 0:
            print(p.stderr[-2000:])
            raise SystemExit(f"ÖLÇÜM HATASI: {gid}")
        ozet["govdeler"][gid] = {
            "anahtar": anahtar, "govde": k["govde"], "sac": k.get("sac", []), "giysiler": k.get("giysiler", []),
            "glb_sha256": hashlib.sha256(glb.read_bytes()).hexdigest(), "bayt": glb.stat().st_size,
            "kaynaklar": [v["id"] for v in kullanilan], "lisanslar": sorted({v["lisans"] for v in kullanilan} | {"kendi-uretim"}),
            "olcum": json.loads(olc.read_text()), "yuvalar": json.loads(glb.with_suffix(".yuva.json").read_text()),
        }
        print("GÖVDE DERLENDİ", gid, "+".join(k.get("giysiler", [])), f"{glb.stat().st_size / 1e6:.1f} MB")
    ozet["takimlar"] = {}
    for kad, kit in kitler.items():
        for rol, k in karakterler(kit):
            if k["ad"] in reddedilen:
                continue
            gid = govde_kimligi(k)
            takim = {
                "ad": k["ad"], "kit": kad, "rol": rol, "govde_id": gid, "glb": str(GOVDE_CIKTI / f"{gid}.glb"),
                "binek": k.get("binek"),
                "takilanlar": [{"yuva": y, "id": pid, "glb": str(ekipman_mod.CIKTI / f"{pid}.glb"),
                                "kategori": kat["parcalar"][pid]["kategori"]} for y, pid in (k.get("takilanlar") or {}).items()],
            }
            (TAKIM_CIKTI / f"{k['ad']}.json").write_text(json.dumps(takim, ensure_ascii=False, indent=1))
            ozet["takimlar"][k["ad"]] = {"kit": kad, "rol": rol, "govde_id": gid, "takilanlar": k.get("takilanlar") or {},
                                         "giysiler": k.get("giysiler", []), "binek": k.get("binek")}
    ozet["reddedilen"] = reddedilen
    OZET.write_text(json.dumps(ozet, ensure_ascii=False, indent=1))
    return ozet


if __name__ == "__main__":
    o = derle("--zorla" in sys.argv)
    print("gövde:", len(o["govdeler"]), "takım:", len(o["takimlar"]), "reddedilen:", len(o["reddedilen"]))
    for a, h in o["reddedilen"].items():
        print("  RED", a, h)
