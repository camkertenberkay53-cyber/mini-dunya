"""Faz-53A A2 görsel kanıt panelleri (sentetik görseller). python3 deneyler/faz53a/a2/kanit.py <olc_klasoru> <cikti>"""
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from kaos.sinema import derinlik, motor  # noqa: E402
from motor.uretim import gorsel25d as g25  # noqa: E402
from motor.uretim import render  # noqa: E402
from motor.varlik import tarihi_gorsel as tg  # noqa: E402

O, C = Path(sys.argv[1]), Path(sys.argv[2])
C.mkdir(parents=True, exist_ok=True)
F = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 26)


def pano(parcalar, baslik, yol, h=420):
    ims = []
    for etiket, a in parcalar:
        a = cv2.cvtColor(a, cv2.COLOR_GRAY2BGR) if a.ndim == 2 else a
        a = cv2.resize(a, (int(a.shape[1] * h / a.shape[0]), h))
        im = Image.fromarray(cv2.cvtColor(a, cv2.COLOR_BGR2RGB))
        ImageDraw.Draw(im).text((8, 6), etiket, fill=(255, 230, 60), font=F, stroke_width=2, stroke_fill=(0, 0, 0))
        ims.append(im)
    w = sum(i.width for i in ims) + 6 * (len(ims) - 1)
    c = Image.new("RGB", (w, h + 44), (24, 24, 24))
    ImageDraw.Draw(c).text((8, 8), baslik, fill="white", font=F)
    x = 0
    for i in ims:
        c.paste(i, (x, 44))
        x += i.width + 6
    c.save(yol, quality=88)


def kare(video, t):
    yol = C / "_k.png"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", str(t), "-i", video, "-frames:v", "1", str(yol)], check=True)
    return cv2.imread(str(yol))


olc = json.loads((O / "olcum.json").read_text())
img = motor._yukle(str(O / "sentetik_kale.png"), 1920, 1080)[..., :3]
ih, iw = img.shape[:2]
kutu = [0.35, 0.27, 0.67, 0.84]
eski = (np.clip((derinlik.ozne_maskesi(img, kutu) - 0.25) * 2.2, 0, 1) * 255).astype(np.uint8)
alfa, puan = g25.maske(img, kutu)
yeni = (alfa * 255).astype(np.uint8)
arka, _ = g25.dolgu(img, alfa, 7)
arka0, _ = g25.dolgu(img, alfa, 7, dict(g25.ayarlar(), doku_doldurma={"acik": False}))
x0, y0, x1, y1 = int(0.30 * iw), int(0.22 * ih), int(0.72 * iw), int(0.88 * ih)
kr = (slice(y0, y1), slice(x0, x1))
pano([("kaynak", img[kr]), ("A1 maske (480 px)", eski[kr]), ("A2 maske", yeni[kr]), ("A2 dolgu (doku açık)", arka[kr]),
      ("A2 dolgu (doku kapalı)", arka0[kr])], "1) Özne maskesi ve dolgulu arka plan (bölge kırpımı)", C / "a2_1_maske_dolgu.jpg")
# burç dişleri yakın
bx0, by0 = int(0.36 * iw), int(0.27 * ih)
bk = (slice(by0, by0 + 160), slice(bx0, bx0 + 420))
pano([("kaynak", img[bk]), ("A1 maske", eski[bk]), ("A2 maske", yeni[bk]), ("A2 dolgu", arka[bk])],
     "2) Burç dişleri: A1 boşlukları özne sayıyor, A2 ayırıyor", C / "a2_2_burc_yakin.jpg", h=300)
# hareket sonu yakın kırpım: A1 ve A2 videoları (benchmark çıktıları)
a1 = next(x["video"] for x in olc if x["yol"] == "A1")
a2 = next(x["video"] for x in olc if x["yol"] == "A2")
k1, k2 = kare(a1, 5.8), kare(a2, 5.8)
yk = (slice(120, 620), slice(560, 1360))
pano([("A1 son kare (kayma ~82 px)", k1[yk]), ("A2 son kare (kayma ≤20 px)", k2[yk])],
     "3) push-in sonu yakın kırpım (1920x1080, t=5,8 sn)", C / "a2_3_son_kare_yakin.jpg", h=480)
# seviye karşılaştırması: aynı sahne, seviye zorlanarak
tg.KAYIT = O / "kayit.json"
render.KOK = C / "uretim"
gercek = g25.seviye
cek = {"id": "S", "cumleler": ["C1"], "sure_sn": 3.0, "tur": "gorsel25d", "metin": "x",
       "gorsel25d": {"gorsel_id": "a2_kale", "hareket": "push_in", "odak": [0.5, 0.5], "ozne": kutu, "ufuk": 0.45, "ton": "sicak"}}
plan = {"surum": 1, "konu": "faz53a-a2-seviye", "donem": "osmanli-15yy", "donemler": ["osmanli-15yy"], "fps": 30,
        "cozunurluk": [1920, 1080], "tohum": 1, "cekimler": [cek], "eksikler": [], "ses": {"motor": "piper", "cizelge": [], "toplam_sn": 3.0}}
pp = C / "plan.json"
pp.write_text(json.dumps(plan))
parcalar, rap = [], {}
for sev in ("tam", "sinirli", "kenburns"):
    g25.seviye = lambda p, a=None, _s=sev: _s
    r = render.render(str(pp), "S", onbellek=False)
    rap[sev] = {"kayma_px": r["kalite"]["kayma_px"], "zemin_par": r["kalite"].get("zemin_par"), "sinema_sn": r["olculen"]["sinema_sn"]}
    parcalar.append((f"{sev}  t=0", kare(r["video"], 0.05)))
    parcalar.append((f"{sev}  t=2,9 (kayma {r['kalite']['kayma_px']} px)", kare(r["video"], 2.9)))
g25.seviye = gercek
satir1, satir2 = parcalar[:2] + parcalar[2:4], parcalar[4:]
pano(parcalar[:4], "4a) Seviye: tam ve sınırlı (aynı sahne)", C / "a2_4a_seviye_tam_sinirli.jpg", h=300)
pano(parcalar[4:], "4b) Seviye: kenburns (parallax yok)", C / "a2_4b_seviye_kenburns.jpg", h=300)
# dikey görsel → 16:9 tuval
H, W = 2400, 1500
p = np.full((H, W, 3), (170, 190, 205), np.uint8)
p[:, :] = (np.linspace(150, 210, H)[:, None, None] * np.array([1.0, 1.05, 1.1])).astype(np.uint8)
cv2.ellipse(p, (750, 1500), (430, 900), 0, 0, 360, (45, 50, 60), -1)
cv2.circle(p, (750, 600), 230, (60, 80, 120), -1)
pyol = C / "portre.png"
cv2.imwrite(str(pyol), p)
k = dict(json.loads((O / "kayit.json").read_text())["gorseller"][0], gorsel_id="a2_portre", yerel_yol=str(pyol),
         sha256=tg._sha(pyol), ozne_bilgisi={"kutu": [0.15, 0.12, 0.85, 1.0], "tur": "insan_portre"}, derinlik_uygunlugu="dusuk")
(C / "kayit2.json").write_text(json.dumps({"gorseller": [k]}))
tg.KAYIT = C / "kayit2.json"
cek2 = dict(cek, id="P", gorsel25d={"gorsel_id": "a2_portre", "hareket": "push_in"})
pp.write_text(json.dumps(dict(plan, cekimler=[cek2])))
r = render.render(str(pp), "P", onbellek=False)
pano([("kaynak (dikey)", p), ("16:9 t=0", kare(r["video"], 0.05)), ("16:9 t=2,9", kare(r["video"], 2.9))],
     f"5) Dikey görsel → 16:9 tuval (kırpılmaz; yanlar maskede yok) — seviye {r['kalite']['seviye']}, nefes {r['kalite']['nefes']}",
     C / "a2_5_tuval.jpg", h=360)
rap["portre"] = {k_: r["kalite"][k_] for k_ in ("seviye", "tuval", "nefes", "zemin_derinlik", "kayma_px", "puan")}
rap["maske_puani_kale"] = puan
(C / "kanit_ozet.json").write_text(json.dumps(rap, ensure_ascii=False, indent=1))
print(json.dumps(rap, ensure_ascii=False))
