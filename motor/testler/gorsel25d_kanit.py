"""Faz-53A 2.5D kanıt üretici (sentetik ve gerçek tarihî görsel için ortak; testler ve deneyler/faz53a/a2/kanit.py kullanır).

kanit_uret(gorsel_id, cikti) — kayıttaki (motor/varlik/tarihi_gorsel_kaydi.json + assets/tarihi_gorsel/*.json) görsel için:
  lisans kapısı + SHA-256 (tarihi_gorsel.dogrulanmis_dosya), maske, dolgu, seviye, hareket, render süreleri ve panolar:
  1 kaynak · 2 A1 maskesi · 3 A2 maskesi · 4 A2 dolgu · 5 maske yakın · 6 dolgu yakın · 7-9 hareket başı/ortası/sonu ·
  10 tam/sinirli/kenburns · 11 render süreleri (ozet.json) · 12 maske kalite ölçümleri (ozet.json)
"""
import json
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from kaos.sinema import derinlik
from motor.uretim import gorsel25d as g25
from motor.uretim import render
from motor.varlik import tarihi_gorsel as tg

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def pano(parcalar, baslik, yol, h=420):
    F = ImageFont.truetype(FONT, 24)
    ims = []
    for etiket, a in parcalar:
        a = cv2.cvtColor(a, cv2.COLOR_GRAY2BGR) if a.ndim == 2 else a
        a = cv2.resize(a, (max(1, int(a.shape[1] * h / a.shape[0])), h))
        im = Image.fromarray(cv2.cvtColor(a, cv2.COLOR_BGR2RGB))
        ImageDraw.Draw(im).text((8, 6), etiket, fill=(255, 230, 60), font=F, stroke_width=2, stroke_fill=(0, 0, 0))
        ims.append(im)
    c = Image.new("RGB", (sum(i.width for i in ims) + 6 * (len(ims) - 1), h + 42), (24, 24, 24))
    ImageDraw.Draw(c).text((8, 8), baslik, fill="white", font=F)
    x = 0
    for i in ims:
        c.paste(i, (x, 42))
        x += i.width + 6
    c.save(yol, quality=86)


def kare(video, t, gecici):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", str(gecici)], check=True)
    return cv2.imread(str(gecici))


def _yakin(kutu_px, ih, iw, oran=0.4):
    """Maske sınır kutusunun üst bölgesi (baş, burç, çıkıntı gibi ince ayrıntılar genelde burada)."""
    x0, y0, x1, y1 = kutu_px
    h = max(8, int((y1 - y0) * oran))
    pad = int(0.05 * (x1 - x0))
    return slice(max(0, y0 - pad), min(ih, y0 + h)), slice(max(0, x0 - pad), min(iw, x1 + pad))


def kanit_uret(gorsel_id: str, cikti: Path, W: int = 1920, H: int = 1080, sure: float = 3.0,
               hareket: str = "push_in", seviyeler: bool = True) -> dict:
    cikti = Path(cikti)
    (cikti / "is").mkdir(parents=True, exist_ok=True)
    yol, kayit = tg.dogrulanmis_dosya(gorsel_id)          # lisans + SHA-256 kapısı (geçmezse LisansHatasi)
    t0 = time.time()
    ek, rap = g25.hazirla(yol, kayit, {"hareket": hareket}, W, H, cikti / "is", 1)
    hazirlik = time.time() - t0
    img = cv2.imread(ek["gorsel"])
    ih, iw = img.shape[:2]
    kutu = rap.get("kutu")
    ozet = {"gorsel_id": gorsel_id, "lisans_turu": kayit["lisans_turu"], "lisans_kisa_adi": kayit.get("lisans_kisa_adi"),
            "atif": kayit.get("atif"), "onay": kayit.get("onay"), "insan_onayi": tg.insan_onayli(kayit),
            "sha256": kayit["sha256"], "cozunurluk_cikti": [W, H],
            "kalite": rap, "hazirlik_sn": round(hazirlik, 2)}
    parcalar = [("1 kaynak", img)]
    if kutu:
        a1 = (np.clip((derinlik.ozne_maskesi(img, kutu) - 0.25) * 2.2, 0, 1) * 255).astype(np.uint8)
        parcalar.append(("2 A1 maske", a1))
    if "ozne_maskesi" in ek:
        a2 = (cv2.imread(ek["ozne_maskesi"], cv2.IMREAD_UNCHANGED) / 257).astype(np.uint8)
        arka = cv2.imread(ek["arka_plan_dolgu"])
        parcalar += [("3 A2 maske", a2), ("4 A2 dolgu", arka)]
        ys, xs = np.nonzero(a2 > 127)
        yk = _yakin((xs.min(), ys.min(), xs.max(), ys.max()), ih, iw)
        pano([("kaynak", img[yk]), ("5 A2 maske yakın", a2[yk]), ("6 A2 dolgu yakın", arka[yk])] +
             ([("A1 maske yakın", a1[yk])] if kutu else []), f"{gorsel_id}: yakın kırpımlar", cikti / "2_yakin.jpg", h=360)
    pano(parcalar, f"{gorsel_id}: seviye {rap['seviye']} · puan {rap['puan']}", cikti / "1_maske_dolgu.jpg", h=380)
    # render (doğal seviye) + başlangıç/orta/bitiş
    eski_kok = render.KOK
    render.KOK = cikti / "is" / "uretim"
    try:
        c = {"id": "K", "cumleler": ["C1"], "sure_sn": sure, "tur": "gorsel25d", "metin": "kanıt",
             "gorsel25d": {"gorsel_id": gorsel_id, "hareket": hareket}}
        plan = {"surum": 1, "konu": "faz53a-kanit", "donem": "osmanli-15yy", "donemler": ["osmanli-15yy"], "fps": 30,
                "cozunurluk": [W, H], "tohum": 1, "cekimler": [c], "eksikler": [], "ses": {"motor": "piper", "cizelge": [], "toplam_sn": sure}}
        pp = cikti / "is" / "plan.json"
        pp.write_text(json.dumps(plan))
        r = render.render(str(pp), "K", onbellek=False)
        ozet["render"] = r["olculen"]
        gk = cikti / "is" / "_k.png"
        pano([(f"7 başlangıç", kare(r["video"], 0.03, gk)), (f"8 orta", kare(r["video"], sure / 2, gk)),
              (f"9 bitiş", kare(r["video"], sure - 0.1, gk))], f"{gorsel_id}: hareket ({rap['seviye']})", cikti / "3_hareket.jpg", h=360)
        if seviyeler:
            gercek = g25.seviye
            sv, olc = [], {}
            try:
                for s_ in ("tam", "sinirli", "kenburns"):
                    g25.seviye = lambda p, a=None, _s=s_: _s
                    rr = render.render(str(pp), "K", onbellek=False)
                    olc[s_] = {"kayma_px": rr["kalite"]["kayma_px"], "sinema_sn": rr["olculen"]["sinema_sn"],
                               "render_sn": rr["olculen"]["render_sn"]}
                    sv.append((f"{s_} bitiş (kayma {rr['kalite']['kayma_px']} px)", kare(rr["video"], sure - 0.1, gk)))
            finally:
                g25.seviye = gercek
            pano(sv, f"{gorsel_id}: 10 tam / sinirli / kenburns", cikti / "4_seviyeler.jpg", h=330)
            ozet["seviye_karsilastirma"] = olc
    finally:
        render.KOK = eski_kok
    (cikti / "ozet.json").write_text(json.dumps(ozet, ensure_ascii=False, indent=1, default=str))
    return ozet


def gercek_gorseller() -> tuple[list[dict], list[str]]:
    """(diskte olan ve kapıdan geçen kayıtlar, sorun listesi). Dosyası diskte olmayan kayıtlar sorun sayılmaz ama
    raporlanır; dosyası olup kapıdan geçemeyen kayıtlar 'kapı' sorunudur."""
    gecen, notlar = [], []
    for k in tg.kayit()["gorseller"]:
        y = tg.dosya_yolu(k)
        if y is None or not y.is_file():
            notlar.append(f"{k.get('gorsel_id')}: dosya diskte yok ({y})")
            continue
        h = tg.denetle(k)
        if h:
            notlar.append(f"KAPI {k.get('gorsel_id')}: " + "; ".join(h))
        else:
            gecen.append(k)
    return gecen, notlar
