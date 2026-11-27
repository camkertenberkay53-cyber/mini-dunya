"""Görsel karşılaştırma raporu.

python3 -m motor.karakter.karsilastir
- Her takım: ön, yan, arka, siluet (ön+yan), yakın çekim, orta mesafe (ONBELLEK/karsilastirma).
- Repoya girenler (motor/karakter/karsilastirma/):
  kit_<kit>.jpg        : kitin bütün karakterleri (ön) + temsilci karakterin 6 görünümü
  donemler_roller.jpg  : satır = rol, sütun = dönem (dört dönem yan yana)
  donemler_orta.jpg / donemler_uzak.jpg / donemler_siluet.jpg : dört dönemin piyadesi aynı sahnede
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from motor import ayar

BURASI = Path(__file__).resolve().parent
CEKIM = ayar.ONBELLEK / "karsilastirma"
RAPOR = BURASI / "karsilastirma"
TAKIM = ayar.ONBELLEK / "takim"
KITLER = ["osmanli_15yy", "akkoyunlu_15yy", "bizans_15yy", "roma_cumhuriyet"]
KIT_AD = {"osmanli_15yy": "Osmanlı 15-16. yy", "akkoyunlu_15yy": "Akkoyunlu / Türkmen", "bizans_15yy": "Bizans 1453",
          "roma_cumhuriyet": "Roma, geç Cumhuriyet"}
ROLLER = ["piyade", "okcu", "suvari", "komutan", "isci_sivil"]
F = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FB = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def godot(args: list[str]) -> None:
    komut = ["xvfb-run", "-a", "-s", "-screen 0 1920x1080x24", ayar.GODOT, "--path", str(ayar.GODOT_PROJE),
             "--rendering-driver", "opengl3", "res://sahneler/karsilastirma.tscn", "--"] + args
    p = subprocess.run(komut, capture_output=True, text=True, timeout=3600)
    if p.returncode != 0:
        print(p.stdout[-2000:], p.stderr[-2000:])
        raise SystemExit("KARŞILAŞTIRMA ÇEKİMİ BAŞARISIZ")


def cek(takimlar: dict[str, dict]) -> None:
    CEKIM.mkdir(parents=True, exist_ok=True)
    adlar = sorted(takimlar)
    for i in range(0, len(adlar), 12):
        godot([str(CEKIM)] + [str(TAKIM / f"{a}.json") for a in adlar[i:i + 12]])
    piyade = [next(a for a in adlar if takimlar[a]["kit"] == k and takimlar[a]["rol"] == "piyade") for k in KITLER]
    godot([str(CEKIM), "--dizi"] + [str(TAKIM / f"{a}.json") for a in piyade])


def _yazi(d, xy, metin, boyut=18, kalin=False, renk=(20, 20, 20)):
    d.text(xy, metin, fill=renk, font=ImageFont.truetype(FB if kalin else F, boyut))


def _kirp(im: Image.Image) -> Image.Image:
    return im.convert("RGB")


def kit_sayfasi(kit: str, takimlar: dict[str, dict]) -> Path:
    uyeler = [a for r in ROLLER for a in sorted(takimlar) if takimlar[a]["kit"] == kit and takimlar[a]["rol"] == r]
    w, h = 200, 400
    sut = 9
    satir = (len(uyeler) + sut - 1) // sut
    temsil = uyeler[0]
    gor = ["on", "yan", "arka", "siluet_on", "siluet_yan", "yakin", "orta"]
    s = Image.new("RGB", (w * sut, 60 + satir * (h + 30) + 40 + h + 30), "white")
    d = ImageDraw.Draw(s)
    _yazi(d, (12, 14), f"{KIT_AD[kit]} — {len(uyeler)} karakter", 26, True)
    for i, a in enumerate(uyeler):
        x, y = (i % sut) * w, 60 + (i // sut) * (h + 30)
        s.paste(_kirp(Image.open(CEKIM / f"{a}_on.png")).resize((w, h)), (x, y + 24))
        _yazi(d, (x + 4, y + 4), f"{takimlar[a]['rol']}: {a.split('_', 1)[1]}"[:28], 13)
    y0 = 60 + satir * (h + 30) + 30
    _yazi(d, (12, y0 - 26), f"Temsilci: {temsil} — ön, yan, arka, siluet, yakın çekim, orta mesafe", 16, True)
    for i, g in enumerate(gor):
        im = _kirp(Image.open(CEKIM / f"{temsil}_{g}.png"))
        s.paste(im.resize((w, h)) if g not in ("yakin", "orta") else im.resize((w, h)), (i * w, y0))
    yol = RAPOR / f"kit_{kit}.jpg"
    s.save(yol, quality=84)
    return yol


def roller_sayfasi(takimlar: dict[str, dict]) -> Path:
    w, h = 220, 440
    s = Image.new("RGB", (120 + w * 4, 50 + h * len(ROLLER)), "white")
    d = ImageDraw.Draw(s)
    for j, k in enumerate(KITLER):
        _yazi(d, (120 + j * w + 8, 14), KIT_AD[k], 16, True)
    for i, r in enumerate(ROLLER):
        _yazi(d, (8, 50 + i * h + h // 2), r, 16, True)
        for j, k in enumerate(KITLER):
            a = next((x for x in sorted(takimlar) if takimlar[x]["kit"] == k and takimlar[x]["rol"] == r), None)
            if a:
                s.paste(_kirp(Image.open(CEKIM / f"{a}_on.png")).resize((w, h)), (120 + j * w, 50 + i * h))
    yol = RAPOR / "donemler_roller.jpg"
    s.save(yol, quality=84)
    return yol


def uret(takimlar: dict[str, dict], cekim: bool = True) -> list[Path]:
    RAPOR.mkdir(parents=True, exist_ok=True)
    if cekim:
        cek(takimlar)
    yollar = [kit_sayfasi(k, takimlar) for k in KITLER] + [roller_sayfasi(takimlar)]
    for g in ("orta", "uzak", "siluet"):
        im = _kirp(Image.open(CEKIM / f"dizi_{g}.png"))
        d = ImageDraw.Draw(im)
        _yazi(d, (16, 12), "Soldan sağa: " + " · ".join(KIT_AD[k] for k in KITLER), 22, True, (10, 10, 10))
        yol = RAPOR / f"donemler_{g}.jpg"
        im.save(yol, quality=86)
        yollar.append(yol)
    return yollar


if __name__ == "__main__":
    oz = json.loads((BURASI / "derlenmis3.json").read_text())
    for y in uret(oz["takimlar"]):
        print("YAZILDI", y)
