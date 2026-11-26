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
    import subprocess
    gecen, notlar = gercek_gorseller()
    print("\n".join(notlar) or "kayıt notu yok")
    if sys.argv[2] == "hepsi":   # her görsel AYRI süreçte: süre ve tepe bellek birbirine karışmasın
        for k in gecen:
            subprocess.run([sys.executable, __file__, "gercek", k["gorsel_id"], sys.argv[3]], check=True)
    else:
        print(json.dumps(kanit_uret(sys.argv[2], Path(sys.argv[3]) / sys.argv[2]), ensure_ascii=False, default=str)[:400])
    sys.exit(0)

if sys.argv[1] == "_tuval_tek":   # tek varyant, ayrı süreç: <gorsel_id> <olcek_kat> <cikti>
    import resource
    gid, kat, C = sys.argv[2], float(sys.argv[3]), Path(sys.argv[4])
    C.mkdir(parents=True, exist_ok=True)
    gercek_kural = veri.kural

    def kural(ad):
        x = gercek_kural(ad)
        if ad == "gorsel":
            k = dict(x["gorsel25d"]["kalite"])
            k["tuval_hareket"] = dict(k["tuval_hareket"], olcek_kat=kat)
            x = dict(x, gorsel25d=dict(x["gorsel25d"], kalite=k))
        return x
    veri.kural = kural
    render.KOK = C / "uretim"
    c = {"id": "T", "cumleler": ["C1"], "sure_sn": 3.0, "tur": "gorsel25d", "metin": "x", "gorsel25d": {"gorsel_id": gid, "hareket": "push_in"}}
    plan = {"surum": 1, "konu": "faz53a-tuval", "donem": "osmanli-15yy", "donemler": ["osmanli-15yy"], "fps": 30, "cozunurluk": [1920, 1080],
            "tohum": 1, "cekimler": [c], "eksikler": [], "ses": {"motor": "piper", "cizelge": [], "toplam_sn": 3.0}}
    (C / "plan.json").write_text(json.dumps(plan))
    r = render.render(str(C / "plan.json"), "T", onbellek=False)
    for t in (0.03, 1.5, 2.9):
        kare(r["video"], t, C / f"kare_{t:.2f}.png")
    o = r["olculen"]
    (C / "olcum.json").write_text(json.dumps({"olcek_kat": kat, "seviye": r["kalite"]["seviye"], "tuval_boyut": r["kalite"].get("tuval_boyut"),
                                              "hazirlik_sn": o["hazirlik_sn"], "render_sn": o["render_sn"], "sinema_sn": o["sinema_sn"],
                                              "renk_kodlama_sn": o["renk_kodlama_sn"], "kare_basina_sn_acilis_dahil": o["kare_basina_sn_acilis_dahil"],
                                              "tepe_bellek_gb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6, 3),
                                              "kayma_px": r["kalite"].get("kayma_px")}, ensure_ascii=False))
    sys.exit(0)

if sys.argv[1] == "tuval_karsilastir":   # <gorsel_id> <cikti>: eski (kaynak çözünürlük) / 1,1 / 1,25 aynı sahne
    import subprocess
    gid, C = sys.argv[2], Path(sys.argv[3])
    C.mkdir(parents=True, exist_ok=True)
    varyant = {"eski": 0.0, "1.1": 1.1, "1.25": 1.25}
    olc = {}
    for ad, kat in varyant.items():
        subprocess.run([sys.executable, __file__, "_tuval_tek", gid, str(kat), str(C / ad)], check=True)
        olc[ad] = json.loads((C / ad / "olcum.json").read_text())

    def ssim(a, b):
        a, b = [cv2.cvtColor(x, cv2.COLOR_BGR2GRAY).astype(np.float64) for x in (a, b)]
        c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
        mu_a, mu_b = cv2.GaussianBlur(a, (11, 11), 1.5), cv2.GaussianBlur(b, (11, 11), 1.5)
        saa = cv2.GaussianBlur(a * a, (11, 11), 1.5) - mu_a ** 2
        sbb = cv2.GaussianBlur(b * b, (11, 11), 1.5) - mu_b ** 2
        sab = cv2.GaussianBlur(a * b, (11, 11), 1.5) - mu_a * mu_b
        return float((((2 * mu_a * mu_b + c1) * (2 * sab + c2)) / ((mu_a ** 2 + mu_b ** 2 + c1) * (saa + sbb + c2))).mean())

    def keskinlik(a):
        return float(cv2.Laplacian(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())
    # bölgeler (1920x1080 çıktı karesinde, dikey portrenin tuvalde ortalandığı düzen için)
    bolge = {"sarik_bas": (0.38, 0.06, 0.62, 0.42), "yuz": (0.40, 0.22, 0.56, 0.55), "omuz": (0.30, 0.55, 0.70, 0.95),
             "yan_dolgu": (0.02, 0.20, 0.22, 0.80)}
    sonuc = {"olcum": olc, "karsilastirma": {}}
    for ad in ("1.1", "1.25"):
        kk = {}
        for t in ("0.03", "1.50", "2.90"):
            e, y = cv2.imread(str(C / "eski" / f"kare_{t}.png")), cv2.imread(str(C / ad / f"kare_{t}.png"))
            H_, W_ = e.shape[:2]
            kb = {"tam_kare": {"ssim": round(ssim(e, y), 4), "psnr": round(float(cv2.PSNR(e, y)), 2)}}
            for b, (x0, y0, x1, y1) in bolge.items():
                sl = (slice(int(y0 * H_), int(y1 * H_)), slice(int(x0 * W_), int(x1 * W_)))
                ey, yy_ = e[sl], y[sl]
                # ½ çözünürlük: eski yoldaki örtüşme (aliasing) desenini eler, gerçek detay kaybını gösterir
                ey2 = cv2.resize(ey, (ey.shape[1] // 2, ey.shape[0] // 2), interpolation=cv2.INTER_AREA)
                yy2 = cv2.resize(yy_, (yy_.shape[1] // 2, yy_.shape[0] // 2), interpolation=cv2.INTER_AREA)
                kb[b] = {"ssim": round(ssim(ey, yy_), 4), "keskinlik_orani": round(keskinlik(yy_) / max(1e-6, keskinlik(ey)), 3),
                         "ssim_yarim": round(ssim(ey2, yy2), 4), "keskinlik_orani_yarim": round(keskinlik(yy2) / max(1e-6, keskinlik(ey2)), 3)}
            kk[t] = kb
        sonuc["karsilastirma"][ad] = kk
    # kalite kapısı (½ çözünürlükte): yüz/sarık/omuz SSIM >= 0,97 ve keskinlik oranı >= 0,90, her karede.
    # Tam çözünürlük değerleri de ozet.json'da (eski yolun örtüşmesi orada fark olarak görünür; kapı değildir).
    for ad in ("1.1", "1.25"):
        kk = sonuc["karsilastirma"][ad]
        en_kotu = {b: {"ssim_yarim": min(kk[t][b]["ssim_yarim"] for t in kk), "keskinlik_yarim": min(kk[t][b]["keskinlik_orani_yarim"] for t in kk),
                       "ssim_tam": min(kk[t][b]["ssim"] for t in kk), "keskinlik_tam": min(kk[t][b]["keskinlik_orani"] for t in kk)} for b in bolge}
        sonuc.setdefault("kapi", {})[ad] = {"en_kotu": en_kotu, "gecti": all(v["ssim_yarim"] >= 0.97 and v["keskinlik_yarim"] >= 0.90
                                                                              for b, v in en_kotu.items() if b != "yan_dolgu")}
    (C / "ozet.json").write_text(json.dumps(sonuc, ensure_ascii=False, indent=1))
    # yan yana panolar: tam kare ve 2x yakın kırpımlar (t = 1,5 sn)
    for t in ("0.03", "2.90"):
        pano([(f"eski (kaynak çöz.) t={t}", cv2.imread(str(C / "eski" / f"kare_{t}.png"))),
              (f"yeni 1,1x t={t}", cv2.imread(str(C / "1.1" / f"kare_{t}.png")))], f"{gid}: tuval eski / 1,1x (1920x1080)", C / f"tam_kare_{t}.jpg", h=420)
    for b, (x0, y0, x1, y1) in bolge.items():
        parcalar = []
        for ad in ("eski", "1.1", "1.25"):
            k_ = cv2.imread(str(C / ad / "kare_1.50.png"))
            H_, W_ = k_.shape[:2]
            parcalar.append((ad, k_[int(y0 * H_):int(y1 * H_), int(x0 * W_):int(x1 * W_)]))
        pano(parcalar, f"{gid}: {b} yakın (t=1,5 sn, 1920x1080 kareden)", C / f"yakin_{b}.jpg", h=420)
    print(json.dumps({"olcum": olc, "kapi": sonuc["kapi"]}, ensure_ascii=False))
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
