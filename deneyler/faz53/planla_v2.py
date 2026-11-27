"""Faz 5.3: pilotun çekim planını kamera v2 ile yeniden kurar (seslendirme ölçümleri ve zaman çizelgesi üretim
planından alınır; yalnız kamera adımı değişir) ve üretimdeki bütün plan denetimlerini çalıştırır.

Kullanım: python3 planla_v2.py <pilot_klasoru> <cikti_klasoru> [tohum]
Çıktı: cekim_plani.json, plan_raporu.json, isler/<cekim>.json (render işleri), kamera_karsilastirma.json (v1/v2)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

BURASI = Path(__file__).resolve().parent
sys.path.insert(0, str(BURASI))
import kamera_v2  # noqa: E402  (veri.kural("kamera") → kamera_v2.yaml)
from motor.uretim import cesitlilik, plan_denetim, render, sahne_bolucu, sozlesme, uyum  # noqa: E402


def planla(klasor: Path, cikti: Path, tohum: int = 7) -> dict:
    sen = json.loads((klasor / "senaryo.json").read_text())
    eski = json.loads((klasor / "cekim_plani.json").read_text())
    taslaklar = sahne_bolucu.cekimlere_bol(sen, eski["ses"]["cizelge"])
    donem = eski["donem"]
    cekimler, eksikler, gecmis = [], [], []
    for i, t in enumerate(taslaklar):
        tercihler = {x["niyet"].get("kamera") for x in taslaklar[i + 1:]} - {None, t["niyet"].get("kamera")}
        c, eks, kayit = kamera_v2.cekim_kur_v2(t, donem, 1080 / 1920, gecmis, tohum + i, tercihler)
        cekimler.append(c)
        if kayit:
            gecmis.append(kayit)
        eksikler += eks
    plan = dict(eski, cekimler=cekimler, eksikler=eski["eksikler"], tohum=tohum)
    rapor = {"hatalar": {}, "uyarilar": [], "kamera_eksik_hata": eksikler}
    den = plan_denetim.denetle(plan)
    rapor["hatalar"]["plan_denetimi"] = den["hatalar"]
    rapor["uyarilar"] += den["uyarilar"]
    rapor["hatalar"]["ortu"] = sozlesme.plan_ortusu(plan, sen)
    rapor["hatalar"]["cesitlilik"], rapor["cesitlilik"] = cesitlilik.denetle(plan, den)
    rapor["hatalar"]["uyum"], rapor["uyum"] = uyum.denetle(sen, plan, den)
    rapor["gecti"] = not any(rapor["hatalar"].values())
    cikti.mkdir(parents=True, exist_ok=True)
    (cikti / "cekim_plani.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1))
    (cikti / "plan_raporu.json").write_text(json.dumps(rapor, ensure_ascii=False, indent=1))
    (cikti / "isler").mkdir(exist_ok=True)
    for c in cekimler:
        if c["tur"] == "3d":
            (cikti / "isler" / f"{c['id']}.json").write_text(json.dumps(render.is_hazirla(plan, c), ensure_ascii=False))
    kar = []
    eskiler = {c["id"]: c for c in eski["cekimler"]}
    for c in cekimler:
        e = eskiler.get(c["id"], {})
        m = c.get("meta", {})
        kar.append({"id": c["id"], "amac": c.get("amac"), "v1": e.get("meta", {}).get("tur"), "v2": m.get("tur"),
                    "v2_lens": m.get("lens_fov"), "gerekce": m.get("secim_gerekcesi"), "reddedilen": m.get("reddedilen_adaylar")})
    (cikti / "kamera_karsilastirma.json").write_text(json.dumps(kar, ensure_ascii=False, indent=1))
    return rapor


if __name__ == "__main__":
    r = planla(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else 7)
    for b, h in r["hatalar"].items():
        for x in h:
            print("HATA", b, x)
    for x in r["kamera_eksik_hata"]:
        print("KAMERA", x)
    print("GEÇTİ" if r["gecti"] else "KALDI")
