"""Faz-53A A2 mikro düzeltme: öncesi (yakin_parca + tuval_hareket kapalı = A2) / sonrası benchmark ve kanıt panoları.
python3 deneyler/faz53a/a2_mikro/olc_kanit.py <gecici_klasor> <kanit_klasoru>
python3 deneyler/faz53a/a2_mikro/olc_kanit.py gercek <gorsel_id|hepsi> <kanit_klasoru>   # gerçek tarihî görsel kanıtı"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from motor.testler import test_faz53a_a2 as T  # noqa: E402
from motor.testler.gorsel25d_kanit import gercek_gorseller, kanit_uret, kare, pano  # noqa: E402
from motor.uretim import gorsel25d as g25  # noqa: E402
from motor.uretim import render, veri  # noqa: E402
from motor.varlik import tarihi_gorsel as tg  # noqa: E402

if sys.argv[1] == "gercek":
    gecen, notlar = gercek_gorseller()
    print("\n".join(notlar) or "kayıt notu yok")
    for k in gecen:
        if sys.argv[2] in ("hepsi", k["gorsel_id"]):
            print(json.dumps(kanit_uret(k["gorsel_id"], Path(sys.argv[3]) / k["gorsel_id"]), ensure_ascii=False, default=str)[:400])
    sys.exit(0)

G, C = Path(sys.argv[1]), Path(sys.argv[2])
G.mkdir(parents=True, exist_ok=True)
C.mkdir(parents=True, exist_ok=True)
gercek_kural = veri.kural


def mikro(acik: bool):
    def kural(ad):
        x = gercek_kural(ad)
        if ad == "gorsel":
            k = dict(x["gorsel25d"]["kalite"])
            k["yakin_parca"] = dict(k["yakin_parca"], acik=acik)
            k["tuval_hareket"] = dict(k["tuval_hareket"], acik=acik)
            x = dict(x, gorsel25d=dict(x["gorsel25d"], kalite=k))
        return x
    veri.kural = kural


img, *_ = T.kale()
pk = G / "kale.png"
cv2.imwrite(str(pk), img)
pp_ = T._portre(G)
kayitlar = [T._kayit(G, pk, gorsel_id="kale"),
            T._kayit(G, pp_, gorsel_id="portre", ozne_bilgisi={"kutu": [0.15, 0.08, 0.85, 1.0], "tur": "insan_portre"}, derinlik_uygunlugu="dusuk")]
for k in kayitlar:
    k["onay"] = {"onaylayan": "DENEME KAYDI (üretim değil)", "tarih": "2026-11-26"}
(G / "kayit.json").write_text(json.dumps({"gorseller": kayitlar}))
tg.KAYIT = G / "kayit.json"
render.KOK = G / "uretim"


def cek(gid, sure, efekt=True):
    g = {"gorsel_id": gid, "hareket": "push_in"}
    if efekt:
        g.update({"odak": [0.5, 0.5], "ufuk": 0.45, "efektler": [{"tip": "toz", "guc": 0.6}, {"tip": "sis", "guc": 0.5}], "ton": "sicak"})
    return {"id": gid, "cumleler": ["C1"], "sure_sn": sure, "tur": "gorsel25d", "metin": "x", "gorsel25d": g}


def rend(c, coz=(1920, 1080)):
    plan = {"surum": 1, "konu": "faz53a-mikro", "donem": "osmanli-15yy", "donemler": ["osmanli-15yy"], "fps": 30, "cozunurluk": list(coz),
            "tohum": 1, "cekimler": [c], "eksikler": [], "ses": {"motor": "piper", "cizelge": [], "toplam_sn": c["sure_sn"]}}
    pp = G / "plan.json"
    pp.write_text(json.dumps(plan))
    return render.render(str(pp), c["id"], onbellek=False)


olc = []
videolar = {}
for tekrar in (1, 2):
    for ad, acik in (("A2", False), ("mikro", True)):
        mikro(acik)
        r = rend(cek("kale", 6.0))
        o, kq = r["olculen"], r["kalite"]
        videolar[ad] = r["video"]
        olc.append({"yol": ad, "tekrar": tekrar, "toplam_sn": o["render_sn"], "maske_sn": kq["maske_sn"], "dolgu_sn": kq["dolgu_sn"],
                    "hazirlik_sn": o["hazirlik_sn"], "sinema_sn": o["sinema_sn"], "kare_dongusu_sn_kare": round(o["sinema_sn"] / o["kare"], 4),
                    "renk_kodlama_sn": o["renk_kodlama_sn"], "kare_basina_acilis_dahil": o["kare_basina_sn_acilis_dahil"],
                    "tepe_bellek_gb": o["render_tepe_bellek_gb"], "seviye": kq["seviye"], "kayma_px": kq["kayma_px"], "puan": kq["puan"]})
        print(json.dumps(olc[-1], ensure_ascii=False), flush=True)
        if tekrar == 1:
            gk = G / "_k.png"
            videolar[ad + "_son"] = kare(r["video"], 5.8, gk)
(C / "benchmark.json").write_text(json.dumps(olc, ensure_ascii=False, indent=1))
yk = (slice(120, 520), slice(560, 1360))
pano([("A2 son kare", videolar["A2_son"][yk]), ("mikro düzeltme son kare", videolar["mikro_son"][yk])],
     "1) push-in sonu, burç dişleri (1920x1080, t=5,8 sn)", C / "m1_burc_son_kare.jpg", h=420)
# maske karşılaştırması
yi = T._yukle_gibi(img, 1920, 1080)
ih, iw = yi.shape[:2]
a = dict(g25.ayarlar()["kalite"])
a0 = dict(a, yakin_parca=dict(a["yakin_parca"], acik=False))
al0, _ = g25.maske(yi, [0.35, 0.27, 0.67, 0.84], a0)
al1, p1 = g25.maske(yi, [0.35, 0.27, 0.67, 0.84], a)
mk = (slice(int(0.27 * ih), int(0.27 * ih) + 170), slice(int(0.36 * iw), int(0.36 * iw) + 560))
pano([("kaynak", yi[mk]), ("A2 maske", (al0 * 255).astype(np.uint8)[mk]), ("mikro maske", (al1 * 255).astype(np.uint8)[mk])],
     "2) Kopuk burç dişleri: A2'de arka planda, mikro düzeltmede özne", C / "m2_maske_yakin.jpg", h=300)
# portre tuval: başlangıç / orta / bitiş, öncesi ve sonrası
satirlar = {}
for ad, acik in (("A2", False), ("mikro", True)):
    mikro(acik)
    r = rend(cek("portre", 3.0, efekt=False))
    gk = G / "_k.png"
    satirlar[ad] = (r, [kare(r["video"], t, gk) for t in (0.03, 1.5, 2.9)])
    print(ad, "tuval", r["kalite"]["tuval"], r["kalite"]["hareket"], r["kalite"].get("tuval_zoom_tavani"), flush=True)
for ad in ("A2", "mikro"):
    r, ks = satirlar[ad]
    hz = r["kalite"]["hareket"]
    pano([(f"{ad} başlangıç", ks[0]), (f"{ad} orta", ks[1]), (f"{ad} bitiş", ks[2])],
         f"3) Dikey görsel 16:9 tuval — {ad}: zoom {hz['bas'][2]:.3f}→{hz['son'][2]:.3f}, cy {hz['bas'][1]:.3f}→{hz['son'][1]:.3f}",
         C / f"m3_tuval_{ad}.jpg", h=300)
mikro(True)
(C / "ozet.json").write_text(json.dumps({"benchmark": olc, "maske_puani_mikro": p1,
                                         "tuval": {ad: satirlar[ad][0]["kalite"]["hareket"] for ad in satirlar}}, ensure_ascii=False, indent=1))
