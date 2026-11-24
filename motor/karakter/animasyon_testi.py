"""Ek animasyon testi (Faz 4): montaj testinin ölçmediği animasyonları, AYNI ölçüm betiği ve AYNI eşiklerle,
her animasyonu ayrı bir çalıştırmada (ölçümler animasyon başına kalsın diye) ölçer.

python3 -m motor.karakter.animasyon_testi            -> motor/karakter/animasyon_testi.json
python3 -m motor.karakter.animasyon_testi --hizli    -> her animasyonda 3 kare

Faz 3b'nin kabul edilmiş montaj_testi.json dosyasına dokunmaz. Bir ek animasyonda eşik aşılırsa karakter RED olmaz;
o animasyon o karakter için yasaklanır (temel animasyon dışındaki her başarısızlıkta olduğu gibi).
Animasyon izni beyaz listedir: burada ya da montaj testinde ölçülmemiş animasyon hiçbir karakterde kullanılamaz.
"""
from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from motor.karakter import montaj

BURASI = Path(__file__).resolve().parent
SONUC = BURASI / "animasyon_testi.json"
EK_ANIMASYONLAR = ["Death01", "Fixing_Kneeling", "Hit_Chest", "Idle_Torch_Loop", "Interact",
                   "Push_Loop", "Sprint_Loop", "Sword_Idle", "Walk_Formal_Loop"]
IS_KLASORU = montaj.ayar.ONBELLEK / "animasyon_testi"


def isler_hazirla(takimlar: list[dict], animasyonlar: list[str], hizli: bool) -> list[Path]:
    IS_KLASORU.mkdir(parents=True, exist_ok=True)
    gorulen, kl = set(), []
    for t in takimlar:
        k = {"ad": t["ad"], "govde_glb": t["glb"], "takilanlar": t["takilanlar"]}
        k["_giysi"] = t["govde_id"] not in gorulen
        gorulen.add(t["govde_id"])
        kl.append(k)
    yollar = []
    for a in animasyonlar:
        for giysi in (True, False):
            grup = [k for k in kl if k["_giysi"] == giysi]
            for j in range(2):  # iki paralel parça
                parca = grup[j::2]
                if not parca:
                    continue
                yol = IS_KLASORU / f"is_{a}_{int(giysi)}_{j}.json"
                yol.write_text(json.dumps({"karakterler": parca, "animasyonlar": [a], "kare": 3 if hizli else 5,
                                           "giysi_testi": giysi, "cikti": str(yol.with_suffix(".sonuc.json"))},
                                          ensure_ascii=False))
                yollar.append(yol)
    return yollar


def animasyon_karari(r: dict, anim: str) -> list[str]:
    """Montaj testinin kararı + giysi eşiğinin bu animasyona uygulanması (eşikler aynı)."""
    h = montaj.karar(r)
    if not r.get("ornek_kare"):
        h.append(f"{anim}: gövdede bulunamadı ya da hiç kare ölçülmedi")  # ölçülmeyen animasyon geçmiş sayılmaz
    for g, x in r.get("giysi", {}).items():
        oran = (x.get("animasyon") or {}).get(anim)
        if oran is not None and oran > montaj.ESIK["giysi_tasma_orani"] and anim not in montaj.TEMEL_ANIMASYON:
            h.append(f"{g}: {anim} sırasında alt katman dışarı taşıyor (%{oran * 100:.1f})")
    return h


def test_et(animasyonlar: list[str] = EK_ANIMASYONLAR, hizli: bool = False) -> dict:
    takimlar = [json.loads(p.read_text()) for p in sorted(montaj.TAKIM.glob("*.json"))]
    gid = {t["ad"]: t["govde_id"] for t in takimlar}
    yollar = isler_hazirla(takimlar, animasyonlar, hizli)
    t0 = time.time()
    with ThreadPoolExecutor(2) as ex:
        ham = list(ex.map(lambda y: (json.loads(y.read_text())["animasyonlar"][0], montaj.calistir(y)), yollar))
    sure = round(time.time() - t0, 1)
    cikti: dict[str, dict] = {}
    for anim in animasyonlar:
        sonuclar = [r for a, liste in ham if a == anim for r in liste]
        govde_giysi = {gid[r["ad"]]: r["giysi"] for r in sonuclar if r.get("katman") is not None}
        for r in sonuclar:
            r["giysi"] = govde_giysi.get(gid[r["ad"]], r["giysi"])
            h = animasyon_karari(r, anim)
            cikti.setdefault(r["ad"], {})[anim] = {"gecti": not h, "hatalar": h, "uyarilar": montaj.uyarilar(r),
                                                   "ornek_kare": r.get("ornek_kare")}
    return {"esikler": montaj.ESIK, "animasyonlar": animasyonlar, "kare": 3 if hizli else 5,
            "sure_sn": sure, "takimlar": cikti}


if __name__ == "__main__":
    c = test_et(hizli="--hizli" in sys.argv)
    SONUC.write_text(json.dumps(c, ensure_ascii=False, indent=1))
    print(f"ANİMASYON TESTİ: {len(c['takimlar'])} karakter, {len(c['animasyonlar'])} animasyon, {c['sure_sn']} sn")
    for a in c["animasyonlar"]:
        g = sum(1 for x in c["takimlar"].values() if x.get(a, {}).get("gecti"))
        print(f"  {a}: {g}/{len(c['takimlar'])} geçti")
