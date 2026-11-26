"""Üretim hattı (kontrol noktası 2 kapsamı): konu + araştırma + senaryo -> ölçülmüş zaman çizelgesi -> çekim planı
-> bütün denetimler -> rapor. Render YAPMAZ.

python3 -m motor.uretim.uretim_hatti <klasor>    (klasörde konu.json, arastirma.json, senaryo.json)
Çıktı: <klasor>/cekim_plani.json, <klasor>/plan_raporu.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from motor.uretim import (anlati, arastirma, cesitlilik, plan_denetim, planlayici, sahne_bolucu, seslendirme,
                          sozlesme, uyum)


def _eksik_turu(metin: str) -> str:
    for anahtar, tur in (("animasyon", "animasyon"), ("binek", "binek"), ("çevre", "ortam"), ("arazi", "ortam"),
                         ("karakter", "karakter"), ("rol", "karakter"), ("nesne", "ekipman"), ("taşı", "ekipman")):
        if anahtar in metin:
            return tur
    return "diger"


def planla(klasor: Path, tohum: int = 7) -> dict:
    t0 = time.time()
    konu = json.loads((klasor / "konu.json").read_text())
    ara = json.loads((klasor / "arastirma.json").read_text())
    sen = json.loads((klasor / "senaryo.json").read_text())
    rapor: dict = {"konu": konu["kimlik"], "hatalar": {}, "uyarilar": []}
    rapor["hatalar"]["konu"] = sozlesme.konu_denetle(konu)
    rapor["hatalar"]["arastirma"] = arastirma.kart_denetle(ara)
    rapor["hatalar"]["senaryo"] = sozlesme.senaryo_denetle(sen, ara)
    if any(rapor["hatalar"].values()):
        rapor["gecti"] = False
        return rapor
    sureler = seslendirme.olc(sen["cumleler"])
    rapor["seslendirme"] = {k: {"sure_sn": v["sure_sn"], "harf_sn": v["harf_sn"], "motor": v["motor"], "okunus": v["metin"]}
                            for k, v in sureler.items()}
    rapor["hatalar"]["anlati"], rapor["anlati_olcum"] = anlati.shorts_denetle(sen, sureler)
    cizelge = sahne_bolucu.zaman_cizelgesi(sen, sureler)
    toplam = sahne_bolucu.toplam_sure(cizelge)
    rapor["toplam_sure_sn"] = toplam
    a, b = konu["hedef_sure_sn"]
    rapor["hatalar"]["sure"] = [] if a <= toplam <= b else [f"toplam süre {toplam} sn; hedef {a}-{b} sn"]
    taslaklar = sahne_bolucu.cekimlere_bol(sen, cizelge)
    donem = konu["donemler"][0]
    cekimler, eksikler, gecmis = [], [], []
    for i, t in enumerate(taslaklar):
        # yalnızca SONRAKİ cümlelerin tercih ettiği kamera türleri saklı tutulur
        tercihler = {x["niyet"].get("kamera") for x in taslaklar[i + 1:]} - {None, t["niyet"].get("kamera")}
        c, eks, kayit = planlayici.cekim_kur(t, donem, 1080 / 1920, gecmis, tohum + i, tercihler, list(konu["donemler"]))
        cekimler.append(c)
        if kayit:
            gecmis.append(kayit)
        eksikler += [{"tur": _eksik_turu(e), "ne": e.split(": ", 1)[-1], "nerede": t["id"]} for e in eks]
    plan = {"surum": 1, "konu": konu["kimlik"], "donem": donem, "donemler": list(konu["donemler"]), "fps": 30, "cozunurluk": [1080, 1920], "tohum": tohum,
            "cekimler": cekimler, "eksikler": eksikler,
            "ses": {"motor": next(iter(sureler.values()))["motor"], "cizelge": cizelge, "toplam_sn": toplam}}
    den = plan_denetim.denetle(plan)
    rapor["hatalar"]["plan_denetimi"] = den["hatalar"]
    rapor["uyarilar"] += den["uyarilar"]
    rapor["hatalar"]["ortu"] = sozlesme.plan_ortusu(plan, sen)
    rapor["hatalar"]["cesitlilik"], rapor["cesitlilik"] = cesitlilik.denetle(plan, den)
    rapor["hatalar"]["uyum"], rapor["uyum"] = uyum.denetle(sen, plan, den)
    rapor["kaynak_izi"] = arastirma.kaynak_izi(sen, ara)
    rapor["kullanilmayan_kartlar"] = arastirma.kullanilmayan_kartlar(sen, ara)
    rapor["eksikler"] = eksikler
    rapor["olcum"] = {k: v["olcum"] for k, v in den["cekimler"].items()}
    rapor["planlama_sn"] = round(time.time() - t0, 2)
    rapor["gecti"] = not any(rapor["hatalar"].values())
    (klasor / "cekim_plani.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1))
    (klasor / "plan_raporu.json").write_text(json.dumps(rapor, ensure_ascii=False, indent=1))
    return rapor


if __name__ == "__main__":
    r = planla(Path(sys.argv[1]))
    for bolum, h in r["hatalar"].items():
        for x in h:
            print("HATA", bolum, x)
    for u in r.get("uyarilar", []):
        print("UYARI", u)
    print("GEÇTİ" if r["gecti"] else "KALDI", r.get("toplam_sure_sn"), "sn")
