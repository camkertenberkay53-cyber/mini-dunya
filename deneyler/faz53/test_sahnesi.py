"""Faz 5.3: AYNI test sahnesi (pilot S4: bozkırda ilerleyen lejyon kolu, odak kartal taşıyıcı) her kamera türüyle
planlanır. Uygun olmayan tür (ör. hareketli odak isteyen tür yerinde sahnede) atlanır; her tür için kadraj/çarpışma
denetimi sonucu kaydedilir ve render işi yazılır.

Kullanım: python3 test_sahnesi.py <cikti_klasoru>"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BURASI = Path(__file__).resolve().parent
sys.path.insert(0, str(BURASI))
import kamera_v2  # noqa: E402
from motor.uretim import kadraj, render, sahne_bolucu  # noqa: E402

PILOT = kamera_v2.REPO / "motor/uretim/pilotlar/roma-lejyon-kartali"


def main(cikti: Path) -> None:
    sen = json.loads((PILOT / "senaryo.json").read_text())
    plan = json.loads((PILOT / "cekim_plani.json").read_text())
    taslak = next(t for t in sahne_bolucu.cekimlere_bol(sen, plan["ses"]["cizelge"]) if t["id"].startswith("S4"))
    (cikti / "isler").mkdir(parents=True, exist_ok=True)
    sonuc = []
    for tur, x in kamera_v2._KURAL["cekimler"].items():
        t = json.loads(json.dumps(taslak))
        t["id"], t["sure_sn"] = f"T_{tur}", 4.0
        t["niyet"]["mesafe"] = x["mesafeler"][-1] if "uzak" in x["mesafeler"] else x["mesafeler"][0]
        t["niyet"]["kamera"] = None
        c, hata, _ = kamera_v2.cekim_kur_v2(t, plan["donem"], 1080 / 1920, [], 7, None, zorla_tur=tur)
        if "kamera" in c and c["meta"]["kalan_kusur"] and x.get("gerekli") != "hareketli":
            # aynı sahne, kol durmuş hâli (yerinde türler hareketli odakta kesilme üretir → denetim yakalar)
            ilk = c["meta"]["kalan_kusur"]
            t["id"], t["niyet"]["eylem"] = f"T_{tur}", "bekleme"
            c, hata, _ = kamera_v2.cekim_kur_v2(t, plan["donem"], 1080 / 1920, [], 7, None, zorla_tur=tur)
            c.setdefault("meta", {})["hareketli_kolda_kusur"] = ilk
        if "kamera" not in c:
            sonuc.append({"tur": tur, "durum": "uygulanamadi", "neden": hata})
            continue
        olc = kadraj.olc(c, 1080 / 1920)
        sonuc.append({"tur": tur, "aciklama": x["aciklama"], "mesafe": t["niyet"]["mesafe"], "hareket": x["hareket"],
                      "lens": c["meta"]["lens_fov"], "kusur": c["meta"]["kalan_kusur"],
                      "odak_orani": olc[c["meta"]["odak_indeks"]]["ekran_orani"],
                      "karakter": len(c["karakterler"]), "hareketli_kolda_kusur": c["meta"].get("hareketli_kolda_kusur"), "durum": "temiz" if not c["meta"]["kalan_kusur"] else "kusurlu"})
        (cikti / "isler" / f"{t['id']}.json").write_text(json.dumps(render.is_hazirla(plan, c), ensure_ascii=False))
    (cikti / "test_sahnesi.json").write_text(json.dumps(sonuc, ensure_ascii=False, indent=1))
    for s in sonuc:
        print(s["tur"], s["durum"], s.get("mesafe"), s.get("lens"), s.get("odak_orani"), s.get("karakter"), s.get("kusur") or s.get("neden"))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
