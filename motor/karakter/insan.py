"""Gerçekçi insan çeşitliliği (kurallar/insan.yaml): her gövde birleşimi için N farklı kişi üretir ve giydirir.

Kişi = MPFB2/MakeHuman CC0 gövdesi (yaş, beden, yüz, ten, saç/sakal; tohumdan) → aynı Faz 3b giysi hattı
(giysi.py, karakter_kur.py) → <gövde_kimliği>_k<i>.glb. Eski UBC gövdesi geri dönüş için ayrıca derlenir.
Hiçbir değer elle seçilmez; bütün çeşitlilik kitin dönem aralıklarından belirlenimci tohumla gelir.
"""
from __future__ import annotations

import hashlib
import json
import random
import subprocess
import sys
from pathlib import Path

from motor import ayar
from motor.uretim import veri

BETIK = Path(__file__).resolve().parent.parent / "varlik" / "blender"
MH = Path(__file__).resolve().parent.parent / "varlik" / "makehuman" / "system_assets"
CIKTI = ayar.ONBELLEK / "insan"


def kural() -> dict:
    return veri.kural("insan")


def acik() -> bool:
    return bool(kural().get("acik"))


def _yas_makro(yil: float) -> float:
    return 0.5 + (yil - 25) / 65 * 0.5 if yil >= 25 else (yil - 1) / 24 * 0.5


def _sec(r: random.Random, olas: dict) -> str:
    x, t = r.random() * sum(olas.values()), 0.0
    for k, v in olas.items():
        t += v
        if x <= t:
            return k
    return list(olas)[-1]


def _karis(a, b, t):
    return [round(x + (y - x) * t, 4) for x, y in zip(a, b)]


def _varliklar(r: random.Random) -> dict:
    """MakeHuman CC0 varlıkları (indirildiyse): göz, kaş, kirpik. Yoksa insan_uret kendi yedeklerini kurar."""
    v = {}
    for tur, klasor in (("gozler", "eyes"), ("kaslar", "eyebrows"), ("kirpikler", "eyelashes")):
        adaylar = sorted(p for p in MH.rglob(f"{klasor}/**/*.mhclo"))
        if tur == "gozler":
            adaylar = [p for p in adaylar if "low" in p.name.lower()] or adaylar
        if adaylar:
            v[tur] = str(adaylar[r.randrange(len(adaylar))])
    return v


def _ten_dokusu(yil: float, koken: dict) -> str | None:
    yas = "young" if yil < 32 else ("middleage" if yil < 50 else "old")
    irk = max(koken, key=koken.get)
    for p in sorted(MH.rglob("skins/**/*.png")):
        n = p.name.lower()
        if yas in n and {"caucasian": "light", "asian": "light", "african": "dark"}.get(irk, "light") in n and "female" not in n \
                and "diffuse" in n:
            return str(p)
    return None


def kisi(kit_adi: str, gid: str, i: int, sac: list[str]) -> dict:
    k = kural()
    kt = k["kitler"].get(kit_adi) or next(iter(k["kitler"].values()))
    tohum = int(hashlib.sha256(f"{gid}:{i}".encode()).hexdigest()[:8], 16)
    r = random.Random(tohum)
    # yaş: kişiler aralığa yayılır (aynı takımda hep aynı yaş olmasın), içinde rastgele
    lo, hi = k["yas_yil"]
    n = int(k["kisi_sayisi"])
    yil = lo + (hi - lo) * ((i + r.random()) / n)
    makro = {"gender": 1.0, "age": round(_yas_makro(yil), 4)}
    for ad, (a, b) in k["beden"].items():
        makro[ad] = round(r.uniform(a, b), 4)
    if yil > 40:   # orta yaşta kilo/göbek eğilimi
        makro["weight"] = round(min(0.85, makro["weight"] + (yil - 40) * 0.006), 4)
    koken = {ad: r.uniform(a, b) for ad, (a, b) in kt["koken"].items()}
    t = sum(koken.values())
    makro.update({ad: round(x / t, 4) for ad, x in koken.items()})
    ten = _karis(kt["ten"][0], kt["ten"][1], r.random())
    sac_renk = list(r.choice(kt["sac"]))
    if yil > k["yasli_gri"]:
        sac_renk = _karis(sac_renk, [0.42, 0.40, 0.38], min(0.85, (yil - k["yasli_gri"]) / 14 * r.uniform(0.5, 1.0)))
    sakal = _sec(r, kt["sakal"] if "sakal" in sac else kt["sakalsiz"])
    doku = _ten_dokusu(yil, koken)
    p = {
        "tohum": tohum % 100000, "yas_yil": round(yil, 1), "makro": makro, "boy_m": k.get("referans_boy_m", 1.81),
        "yuz": {"guc": k["yuz"]["guc"], "bolgeler": k["yuz"]["bolgeler"]},
        "ten": {"doku": doku, "carpan": _karis([1, 1, 1], [x / max(ten) for x in ten], 0.35)} if doku else {"renk": ten},
        "sakal": {"tur": sakal, "renk": sac_renk, "uzunluk_carpan": round(r.uniform(0.8, 1.25), 3)},
        "sac_kabuk": {"acik": "kisa" in sac, "renk": sac_renk, "uzunluk_m": round(r.uniform(0.004, 0.009), 4)},
        "kas": {"acik": True, "yogunluk": round(r.uniform(0.9, 1.4), 3)},
        "sac_renk": sac_renk, "goz_renk": list(r.choice(kt["goz"])),
        "varliklar": _varliklar(r),
    }
    return p


def derle(gid: str, kit_adi: str, sac: list[str], tarif: dict, ubc_usda: str, anahtar: str, onceki: dict | None) -> list[dict]:
    """gid için N kişi: gövde üret → giydir → ölç. Dönüş: [{glb, kisi, sha256, ...}]. Önbellek anahtarı eşleşirse atlanır."""
    CIKTI.mkdir(parents=True, exist_ok=True)
    k = kural()
    betik = hashlib.sha256(b"".join((BETIK / b).read_bytes() for b in ("insan_uret.py", "karakter_kur.py", "giysi.py"))).hexdigest()[:12]
    sonuc = []
    for i in range(int(k["kisi_sayisi"])):
        par = kisi(kit_adi, gid, i, sac)
        ank = hashlib.sha256(json.dumps([anahtar, par, betik], sort_keys=True).encode()).hexdigest()[:16]
        glb = CIKTI / f"{gid}_k{i}.glb"
        eski = next((x for x in (onceki or {}).get("kisiler", []) if x.get("glb") == str(glb)), None)
        if eski and eski.get("anahtar") == ank and glb.exists():
            sonuc.append(eski)
            continue
        pj = CIKTI / f"{gid}_k{i}.kisi.json"
        govde = CIKTI / f"{gid}_k{i}.govde.blend"
        pj.write_text(json.dumps(dict(par, doku_dizini=str(CIKTI / "doku")), ensure_ascii=False, indent=1))
        p = subprocess.run([sys.executable, str(BETIK / "insan_uret.py"), ubc_usda, str(govde), str(pj)],
                           capture_output=True, text=True, timeout=900)
        if p.returncode != 0 or not govde.exists():
            print(p.stdout[-1500:], p.stderr[-2500:])
            raise SystemExit(f"İNSAN ÜRETİM HATASI: {gid} k{i}")
        t = dict(tarif, kiyafet=str(govde), ekler=[], cikti=str(glb))
        tj = CIKTI / f"{gid}_k{i}.tarif.json"
        tj.write_text(json.dumps(t, ensure_ascii=False, indent=1))
        p = subprocess.run([sys.executable, str(BETIK / "karakter_kur.py"), str(tj)], capture_output=True, text=True, timeout=1800)
        if p.returncode != 0 or not glb.exists():
            print(p.stdout[-1500:], p.stderr[-2500:])
            raise SystemExit(f"İNSAN GİYDİRME HATASI: {gid} k{i}")
        olc = glb.with_suffix(".olc.json")
        p = subprocess.run([sys.executable, str(BETIK / "olc.py"), str(glb), str(olc), str(BETIK.parent / "evrensel_iskelet.json")],
                           capture_output=True, text=True, timeout=600)
        if p.returncode != 0:
            print(p.stderr[-2000:])
            raise SystemExit(f"İNSAN ÖLÇÜM HATASI: {gid} k{i}")
        govde.unlink(missing_ok=True)
        sonuc.append({"glb": str(glb), "anahtar": ank, "kisi": par, "sha256": hashlib.sha256(glb.read_bytes()).hexdigest(),
                      "bayt": glb.stat().st_size, "olcum": json.loads(olc.read_text()),
                      "yuvalar": json.loads(glb.with_suffix(".yuva.json").read_text())})
        print("KİŞİ DERLENDİ", gid, i, f"{par['yas_yil']} yaş", par["sakal"]["tur"], f"{glb.stat().st_size / 1e6:.1f} MB")
    return sonuc


SONUC = Path(__file__).resolve().parent / "insan_testi.json"


def montaj_testi(hizli: bool = False) -> dict:
    """Faz 3b montaj testi (aynı eşikler, montaj.ESIK) her gerçekçi kişi + takım birleşimine uygulanır.
    Geçemeyen kişi o takımın 'kisiler' listesine girmez (takim.py derlemesinde 'red' işaretiyle elenir)."""
    from motor.karakter import montaj
    ek = []
    for p in sorted(montaj.TAKIM.glob("*.json")):
        t = json.loads(p.read_text())
        for i, g in enumerate(t.get("kisiler", [])):
            ek.append(dict(t, ad=f"{t['ad']}#k{i}", glb=g, govde_id=f"{t['govde_id']}_k{i}"))
    c = montaj.test_et(adlar=["__yalniz_kisiler__"], hizli=hizli, ek=ek)
    SONUC.write_text(json.dumps({"esikler": montaj.ESIK, "hizli": hizli, "kisiler": c}, ensure_ascii=False, indent=1))
    return c


def reddedilenler() -> set[str]:
    """Montaj testinden geçemeyen kişi glb'leri (takım bazında)."""
    if not SONUC.exists():
        return set()
    return {f"{a.split('#')[0]}#{a.split('#')[1]}" for a, x in json.loads(SONUC.read_text())["kisiler"].items() if not x["gecti"]}


if __name__ == "__main__":
    c = montaj_testi("--hizli" in sys.argv)
    gecen = sum(1 for x in c.values() if x["gecti"])
    print(f"İNSAN MONTAJ: {gecen}/{len(c)} geçti")
    for a, x in c.items():
        for h in x["hatalar"]:
            print("  KALDI", a, h)
