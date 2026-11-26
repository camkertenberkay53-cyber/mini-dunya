"""Faz-53A A2 benchmark: aynı makinede A1 yolu (gorsel25d.kalite kapalı) ile A2 yolu, 1920x1080 6 sn sentetik sahne.
Sentetik görsel testteki üreteçle üretilir; geçici deneme kaydı kullanılır (üretim kaydına girmez).
python3 deneyler/faz53a/a2/olc.py <cikti_klasoru>"""
import json
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from motor.testler.test_faz53a_a2 import kale  # noqa: E402
from motor.uretim import render, veri  # noqa: E402
from motor.varlik import tarihi_gorsel as tg  # noqa: E402

K = Path(sys.argv[1])
K.mkdir(parents=True, exist_ok=True)
img, *_ = kale()
p = K / "sentetik_kale.png"
cv2.imwrite(str(p), img)
kayit = {"gorsel_id": "a2_kale", "kaynak_url": "sentetik", "kaynak_kurum": "-", "eser_adi": "sentetik kale", "tarih": "2026",
         "bolge": "-", "donem": "-", "kultur": "-", "taraf_faction": "-", "gorsel_turu": "gravur_benzeri_sentetik",
         "uygun_sahne_turleri": ["deneme"], "cozunurluk": [3000, 2000], "ozne_bilgisi": {"kutu": [0.35, 0.27, 0.67, 0.84], "tur": "mimari"},
         "derinlik_uygunlugu": "yuksek", "lisans_turu": "CC0-1.0", "kamu_mali_gerekcesi": "kendi üretimimiz",
         "lisans_dogrulandi": True, "onay": {"onaylayan": "DENEME KAYDI (üretim değil)", "tarih": "2026-11-26"},
         "yerel_yol": str(p), "sha256": tg._sha(p)}
(K / "kayit.json").write_text(json.dumps({"gorseller": [kayit]}, ensure_ascii=False))
tg.KAYIT = K / "kayit.json"
render.KOK = K / "uretim"
gercek = veri.kural


def kalite(acik):
    def kural(ad):
        x = gercek(ad)
        if ad == "gorsel":
            x = dict(x, gorsel25d=dict(x["gorsel25d"], kalite=dict(x["gorsel25d"]["kalite"], acik=acik)))
        return x
    veri.kural = kural


cek = {"id": "A2", "cumleler": ["C1"], "sure_sn": 6.0, "tur": "gorsel25d", "metin": "x",
       "gorsel25d": {"gorsel_id": "a2_kale", "hareket": "push_in", "odak": [0.5, 0.5], "ozne": [0.35, 0.27, 0.67, 0.84],
                     "parallax": 1.0, "ufuk": 0.45, "efektler": [{"tip": "toz", "guc": 0.6}, {"tip": "sis", "guc": 0.5}], "ton": "sicak"}}
sonuc = []
for tekrar in (1, 2):
    for ad, acik, coz in (("A1", False, [1920, 1080]), ("A2", True, [1920, 1080])):
        kalite(acik)
        plan = {"surum": 1, "konu": "faz53a-a2", "donem": "osmanli-15yy", "donemler": ["osmanli-15yy"], "fps": 30, "cozunurluk": coz,
                "tohum": 1, "cekimler": [cek], "eksikler": [], "ses": {"motor": "piper", "cizelge": [], "toplam_sn": 6.0}, "format": "uzun"}
        pp = K / "plan.json"
        pp.write_text(json.dumps(plan))
        r = render.render(str(pp), "A2", onbellek=False)
        o = r["olculen"]
        kq = r.get("kalite", {})
        sonuc.append({"yol": ad, "tekrar": tekrar, "cozunurluk": o["cozunurluk"], "toplam_sn": o["render_sn"],
                      "hazirlik_sn": o["hazirlik_sn"], "maske_sn": kq.get("maske_sn"), "dolgu_sn": kq.get("dolgu_sn"),
                      "kalite_hazirlik_sn": kq.get("hazirlik_sn"), "sinema_sn": o["sinema_sn"],
                      "kare_dongusu_sn_kare": round(o["sinema_sn"] / o["kare"], 4), "renk_kodlama_sn": o["renk_kodlama_sn"],
                      "kare_basina_acilis_dahil": o["kare_basina_sn_acilis_dahil"], "tepe_bellek_gb": o["render_tepe_bellek_gb"],
                      "seviye": o.get("seviye"), "kayma_px": kq.get("kayma_px"), "video": r["video"]})
        print(json.dumps(sonuc[-1], ensure_ascii=False), flush=True)
kalite(True)
plan["cozunurluk"] = [1080, 1920]
plan.pop("format")
pp.write_text(json.dumps(plan))
r = render.render(str(pp), "A2", onbellek=False)
o = r["olculen"]
sonuc.append({"yol": "A2_shorts", "tekrar": 1, "cozunurluk": o["cozunurluk"], "toplam_sn": o["render_sn"], "sinema_sn": o["sinema_sn"],
              "kare_basina_acilis_dahil": o["kare_basina_sn_acilis_dahil"], "seviye": o.get("seviye"), "kayma_px": r["kalite"]["kayma_px"],
              "maske_sn": r["kalite"]["maske_sn"], "dolgu_sn": r["kalite"]["dolgu_sn"], "video": r["video"]})
print(json.dumps(sonuc[-1], ensure_ascii=False))
(K / "olcum.json").write_text(json.dumps(sonuc, ensure_ascii=False, indent=1))
