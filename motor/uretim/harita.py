"""Taktik harita anlatımı (konudan bağımsız; kendi yazımımız). Konu verisindeki 'harita' bloğundan (arazi, birlikler,
evreler) senaryonun 'harita' niyetli cümlesine animasyonlu harita çekimi üretir.

- Görünüm: eski el yazması harita dokusu (prosedürel kâğıt, tepe gölgelemesi, dere/yol çizgileri, yer adları).
- Birlikler: askerî harita simgeleri (piyade ×, süvari ⟋, top ●), taraf rengiyle; önceki evredeki yerinden bu evredeki
  yerine kayar; 'durum: dagildi' birlik solar ve üstü çizilir.
- Oklar: saldırı (dolu), geri çekilme/kaçış (kesikli); çekim boyunca uçtan uca çizilerek ilerler.
- Kamera: evrenin odak noktasına yavaş yaklaşma (çekim sonunda sinematik sahneye geçişe hazır).
- Ölçek temsilîdir (km ızgarası şematik): kaynakta verilen diziliş ve hareket yönleri gösterilir, uydurulmaz.

Çıktı: plan çözünürlüğünde (1080x1920, 30 fps) H.264 mp4. CPU; ~0,1 sn/kare.
"""
from __future__ import annotations

import math
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
FONT_I = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf"
FONT_N = "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"
S = 2   # iç çizim çarpanı (kenar yumuşatma için 2x çizilip küçültülür)


def _goruntu(a: np.ndarray) -> Image.Image:
    """uint8 dizisinden PIL görüntüsü (gri ya da RGB)."""
    a = np.ascontiguousarray(a)
    return Image.frombytes("L" if a.ndim == 2 else "RGB", (a.shape[1], a.shape[0]), a.tobytes())


def _fbm(w: int, h: int, tohum: int, oktav: int = 5) -> np.ndarray:
    g = np.random.default_rng(tohum)
    out = np.zeros((h, w), np.float32)
    a = 1.0
    for o in range(oktav):
        n = 4 * 2 ** o
        k = g.random((n + 1, n + 1)).astype(np.float32)
        img = _goruntu((k * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
        out += a * (np.asarray(img, np.float32) / 255.0)
        a *= 0.5
    return out / (2 - 2 ** (1 - oktav))


class Harita:
    def __init__(self, veri: dict, boyut=(1080, 1920)):
        self.v = veri
        self.W, self.H = boyut[0] * S, boyut[1] * S
        self.alan = veri.get("alan_km", [10.0, 10.0])
        # Tam kadraj harita: genişlik alana oturur, dikeyde alanın üstü/altı da arazi olarak sürer (9:16)
        olcek = self.W / (self.alan[0] * 1.08)
        self.olcek = olcek
        self.x0 = (self.W - self.alan[0] * olcek) / 2
        self.y0 = (self.H - self.alan[1] * olcek) / 2 + self.H * 0.02
        self.taban = self._taban()

    def p(self, xy) -> tuple[float, float]:
        """km (x doğu, y kuzey) → piksel (2x)."""
        return self.x0 + xy[0] * self.olcek, self.y0 + (self.alan[1] - xy[1]) * self.olcek

    def _yukseklik(self, w, h) -> np.ndarray:
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        z = np.zeros((h, w), np.float32)
        for t in self.v.get("arazi", {}).get("tepeler", []):
            cx, cy = self.p(t["merkez"])
            r = t["yaricap_km"] * self.olcek
            z += t.get("yukseklik", 1.0) * np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * (r * 0.6) ** 2)))
        return z + 0.03 * _fbm(w, h, 11, 4)

    def _taban(self) -> Image.Image:
        w, h = self.W, self.H
        kagit = _fbm(w // 4, h // 4, 3, 6)
        kagit = np.asarray(_goruntu((kagit * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC), np.float32) / 255.0
        renk = np.array([226, 211, 176], np.float32)[None, None, :] * (0.9 + 0.16 * kagit[..., None])
        # tepe gölgelemesi (kuzeybatıdan ışık) ve eş yükselti çizgileri
        z = self._yukseklik(w // 2, h // 2)
        gy, gx = np.gradient(z)
        isik = np.clip(0.5 - (gx * -1 + gy * -1) * 55.0, 0, 1)
        isik = np.asarray(_goruntu((isik * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC), np.float32) / 255.0
        zb = np.asarray(_goruntu((np.clip(z / max(z.max(), 1e-3), 0, 1) * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC), np.float32) / 255.0
        renk *= (0.82 + 0.3 * isik[..., None]) * (1 - 0.08 * zb[..., None])
        es = (np.abs(np.sin(zb * 34.0)) < 0.05) & (zb > 0.22)
        renk[es] *= 0.86
        # kenar kararması (eski kâğıt)
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        kk = np.minimum(np.minimum(xx, w - xx) / w, np.minimum(yy, h - yy) / h)
        renk *= np.clip(0.72 + kk[..., None] * 3.2, 0, 1)
        im = _goruntu(np.clip(renk, 0, 255).astype(np.uint8))
        d = ImageDraw.Draw(im, "RGBA")
        # dereler / nehirler, yollar
        for s in self.v.get("arazi", {}).get("dereler", []):
            pts = [self.p(q) for q in s["noktalar"]]
            d.line(pts, fill=(78, 104, 128, 230), width=int(s.get("genislik", 5) * S), joint="curve")
            if s.get("ad"):
                self._yazi(d, pts[len(pts) // 2], s["ad"], 30, (60, 82, 104, 255), FONT_I, ofset=(0, -28 * S))
        for s in self.v.get("arazi", {}).get("yollar", []):
            pts = [self.p(q) for q in s["noktalar"]]
            for i in range(len(pts) - 1):
                self._kesikli(d, pts[i], pts[i + 1], (120, 92, 60, 200), 3 * S, 14 * S)
        for t in self.v.get("arazi", {}).get("tepeler", []):
            if t.get("ad"):
                self._yazi(d, self.p(t["merkez"]), t["ad"], 28, (92, 68, 44, 255), FONT_I, ofset=(0, -t["yaricap_km"] * self.olcek * 0.35))
        for y in self.v.get("arazi", {}).get("yerler", []):
            px, py = self.p(y["konum"])
            d.ellipse([px - 7 * S, py - 7 * S, px + 7 * S, py + 7 * S], fill=(70, 50, 34, 255))
            self._yazi(d, (px, py), y["ad"], 30, (60, 42, 28, 255), FONT, ofset=(0, 26 * S))
        # şematik km ızgarası (tüm tuval)
        for i in range(-3, int(self.alan[0]) + 4):
            x, _ = self.p((i, 0))
            d.line([(x, 0), (x, self.H)], fill=(120, 96, 66, 24), width=S)
        for j in range(-8, int(self.alan[1]) + 9):
            _, y = self.p((0, j))
            d.line([(0, y), (self.W, y)], fill=(120, 96, 66, 24), width=S)
        # kuzey oku
        nx, ny = self.W - 80 * S, self.H * 0.2
        d.polygon([(nx, ny - 40 * S), (nx - 16 * S, ny + 14 * S), (nx, ny + 4 * S), (nx + 16 * S, ny + 14 * S)], fill=(70, 50, 34, 230))
        self._yazi(d, (nx, ny + 34 * S), "K", 30, (70, 50, 34, 255), FONT)
        return im

    # ---------------------------------------------------------------- çizim yardımcıları
    def _yazi(self, d, xy, metin, boy, renk, font=FONT, ofset=(0, 0), golge=True):
        f = ImageFont.truetype(font, int(boy * S))
        x, y = xy[0] + ofset[0], xy[1] + ofset[1]
        if golge:
            d.text((x, y), metin, font=f, fill=(240, 230, 205, 170), anchor="mm", stroke_width=3 * S, stroke_fill=(240, 230, 205, 150))
        d.text((x, y), metin, font=f, fill=renk, anchor="mm")

    def _kesikli(self, d, a, b, renk, gen, adim):
        L = math.dist(a, b)
        n = max(1, int(L / adim))
        for i in range(0, n, 2):
            t0, t1 = i / n, min(1, (i + 1) / n)
            d.line([(a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0), (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1)],
                   fill=renk, width=gen)

    def _renk(self, taraf, a=255):
        r = self.v["taraflar"][taraf]["renk"]
        return (int(r[0] * 255), int(r[1] * 255), int(r[2] * 255), a)

    def birlik(self, d, b, konum, gorunur=1.0):
        px, py = self.p(konum)
        w, h = 104 * S * b.get("buyukluk", 1.0), 56 * S * b.get("buyukluk", 1.0)
        a = int(255 * gorunur)
        dolgu = self._renk(b["taraf"], int(215 * gorunur))
        kenar = (40, 28, 20, a)
        yon = math.radians(b.get("yon_derece", 0))
        # birlik yönü: ön kenarda kalın çizgi (cephe)
        d.rectangle([px - w / 2, py - h / 2, px + w / 2, py + h / 2], fill=dolgu, outline=kenar, width=3 * S)
        tur = b.get("tur", "piyade")
        if tur == "piyade":
            d.line([(px - w / 2, py - h / 2), (px + w / 2, py + h / 2)], fill=kenar, width=3 * S)
            d.line([(px - w / 2, py + h / 2), (px + w / 2, py - h / 2)], fill=kenar, width=3 * S)
        elif tur == "suvari":
            d.line([(px - w / 2, py + h / 2), (px + w / 2, py - h / 2)], fill=kenar, width=3 * S)
        elif tur == "top":
            d.ellipse([px - 10 * S, py - 10 * S, px + 10 * S, py + 10 * S], fill=kenar)
        elif tur == "karargah":
            d.line([(px - w / 2, py), (px + w / 2, py)], fill=kenar, width=3 * S)
            d.line([(px - w / 2 + 6 * S, py - h / 2 - 22 * S), (px - w / 2 + 6 * S, py - h / 2)], fill=kenar, width=3 * S)
            d.polygon([(px - w / 2 + 6 * S, py - h / 2 - 22 * S), (px - w / 2 + 34 * S, py - h / 2 - 15 * S), (px - w / 2 + 6 * S, py - h / 2 - 8 * S)],
                      fill=self._renk(b["taraf"], a))
        cx, cy = px + math.sin(yon) * h * 0.62, py - math.cos(yon) * h * 0.62
        d.ellipse([cx - 6 * S, cy - 6 * S, cx + 6 * S, cy + 6 * S], fill=kenar)
        if b.get("dagildi") and gorunur < 1.0:
            d.line([(px - w * 0.7, py - h * 0.9), (px + w * 0.7, py + h * 0.9)], fill=(140, 20, 16, int(255 * (1 - gorunur) + 120)), width=6 * S)
        if b.get("ad"):
            self._yazi(d, (px, py + h / 2 + 24 * S), b["ad"], 24, (40, 28, 20, a), FONT)

    def ok(self, d, o, ilerleme):
        pts = [self.p(q) for q in o["yol"]]
        egri = _catmull(pts, 24)
        n = max(2, int(len(egri) * ilerleme))
        egri = egri[:n]
        if len(egri) < 2:
            return
        renk = self._renk(o["taraf"], 215)
        koyu = (40, 28, 20, 220)
        gen = 22 * S if o.get("tur", "saldiri") == "saldiri" else 12 * S
        kesik = o.get("tur") in ("geri_cekilme", "kacis")
        for i in range(len(egri) - 1):
            if kesik and (i // 3) % 2:
                continue
            t = i / max(1, len(egri) - 1)
            g = gen * (0.55 + 0.45 * t)   # uca doğru kalınlaşan gövde
            d.line([egri[i], egri[i + 1]], fill=koyu, width=int(g + 6 * S))
        for i in range(len(egri) - 1):
            if kesik and (i // 3) % 2:
                continue
            t = i / max(1, len(egri) - 1)
            d.line([egri[i], egri[i + 1]], fill=renk, width=int(gen * (0.55 + 0.45 * t)))
        (x1, y1), (x0, y0) = egri[-1], egri[max(0, len(egri) - 4)]
        a = math.atan2(y1 - y0, x1 - x0)
        L, B = gen * 2.6, gen * 1.6
        uc = [(x1 + math.cos(a) * L * 0.5, y1 + math.sin(a) * L * 0.5),
              (x1 - math.cos(a) * L * 0.5 + math.cos(a + math.pi / 2) * B, y1 - math.sin(a) * L * 0.5 + math.sin(a + math.pi / 2) * B),
              (x1 - math.cos(a) * L * 0.5 - math.cos(a + math.pi / 2) * B, y1 - math.sin(a) * L * 0.5 - math.sin(a + math.pi / 2) * B)]
        d.polygon(uc, fill=renk, outline=koyu, width=3 * S)

    def ust_bilgi(self, im: Image.Image, ust: str, alt: str | None, gorunur: float) -> None:
        """Başlık bandı ve lejant (çıktı çözünürlüğünde; harita yakınlaşmasından etkilenmez)."""
        W, H = im.size
        kat = Image.new("RGBA", im.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(kat)
        a = int(255 * gorunur)
        for y in range(int(H * 0.17)):   # üstte kâğıt rengi yumuşak bant
            d.line([(0, y), (W, y)], fill=(232, 219, 186, int(225 * (1 - y / (H * 0.17)) ** 0.7 * gorunur)))
        f = ImageFont.truetype(FONT, 50)
        d.text((W / 2, H * 0.06), ust, font=f, fill=(48, 32, 20, a), anchor="mm")
        if alt:
            d.text((W / 2, H * 0.105), alt, font=ImageFont.truetype(FONT_I, 31), fill=(80, 58, 36, a), anchor="mm")
        for y in range(int(H * 0.86), H):
            d.line([(0, y), (W, y)], fill=(232, 219, 186, int(210 * max(0.0, (y - H * 0.86) / (H * 0.14)) ** 0.8)))
        x, y0 = W * 0.08, H * 0.915
        for i, (ad, t) in enumerate(self.v["taraflar"].items()):
            yy = y0 + i * 46
            d.rectangle([x, yy - 14, x + 46, yy + 14], fill=self._renk(ad, 230), outline=(40, 28, 20, 255), width=2)
            d.text((x + 62, yy), t["ad"], font=ImageFont.truetype(FONT_N, 28), fill=(40, 28, 20, 255), anchor="lm")
        d.text((W * 0.92, H * 0.95), "temsilî ölçek", font=ImageFont.truetype(FONT_I, 22), fill=(90, 70, 50, 255), anchor="rm")
        im.alpha_composite(kat)


def _catmull(p: list, adim: int) -> list:
    if len(p) == 2:
        return [(p[0][0] + (p[1][0] - p[0][0]) * t / adim, p[0][1] + (p[1][1] - p[0][1]) * t / adim) for t in range(adim + 1)]
    q = [p[0]] + p + [p[-1]]
    out = []
    for i in range(1, len(q) - 2):
        p0, p1, p2, p3 = (np.array(x) for x in q[i - 1: i + 3])
        for t in np.linspace(0, 1, adim, endpoint=False):
            out.append(tuple(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3)))
    out.append(tuple(p[-1]))
    return out


def _yumusak(u: float) -> float:
    u = min(1.0, max(0.0, u))
    return u * u * (3 - 2 * u)


def evre_bul(veri: dict, evre: str) -> tuple[dict, dict | None]:
    ev = veri["evreler"]
    i = next(i for i, e in enumerate(ev) if e["id"] == evre)
    return ev[i], (ev[i - 1] if i > 0 else None)


def kare(h: Harita, evre: dict, onceki: dict | None, u: float, baslik: str | None) -> Image.Image:
    """u ∈ [0,1]: çekim içindeki ilerleme."""
    im = h.taban.copy()
    d = ImageDraw.Draw(im, "RGBA")
    eski = {b["id"]: b for b in (onceki or {}).get("birlikler", [])}
    hareket = _yumusak((u - 0.05) / 0.55)
    for b in evre["birlikler"]:
        e = eski.get(b["id"])
        k0 = e["konum"] if e else b["konum"]
        konum = [k0[0] + (b["konum"][0] - k0[0]) * hareket, k0[1] + (b["konum"][1] - k0[1]) * hareket]
        gor = 1.0
        if b.get("dagildi"):
            gor = 1.0 - 0.65 * _yumusak((u - 0.45) / 0.4)
        elif not e and onceki is not None:
            gor = _yumusak(u / 0.25)
        h.birlik(d, b, konum, gor)
    for i, o in enumerate(evre.get("oklar", [])):
        bas = 0.12 + 0.1 * i
        h.ok(d, o, _yumusak((u - bas) / 0.55))
    # kamera: evre odağına yavaş yaklaşma
    z = 1.0 + 0.10 * _yumusak(u)
    odak = h.p(evre.get("odak_km", [h.alan[0] / 2, h.alan[1] / 2]))
    cx = h.W / 2 + (odak[0] - h.W / 2) * 0.35 * _yumusak(u)
    cy = h.H / 2 + (odak[1] - h.H / 2) * 0.35 * _yumusak(u)
    w, hh = h.W / z, h.H / z
    x0 = min(max(cx - w / 2, 0), h.W - w)
    y0 = min(max(cy - hh / 2, 0), h.H - hh)
    cikis = im.crop((int(x0), int(y0), int(x0 + w), int(y0 + hh))).resize((h.W // S, h.H // S), Image.LANCZOS).convert("RGBA")
    h.ust_bilgi(cikis, baslik or evre.get("baslik", ""), evre.get("alt_baslik"), _yumusak(u / 0.15))
    return cikis


def render(veri: dict, evre_id: str, sure_sn: float, cikti: Path, fps: int = 30, boyut=(1080, 1920),
           baslik: str | None = None, vf: str = "") -> dict:
    h = Harita(veri, boyut)
    evre, onceki = evre_bul(veri, evre_id)
    n = round(sure_sn * fps)
    p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{boyut[0]}x{boyut[1]}",
                          "-r", str(fps), "-i", "-", *(["-vf", vf] if vf else []), "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
                          "-an", str(cikti)], stdin=subprocess.PIPE)
    for i in range(n):
        im = kare(h, evre, onceki, i / max(1, n - 1), baslik)
        p.stdin.write(np.asarray(im.convert("RGB")).tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("harita kodlama hatası")
    return {"kare": n, "evre": evre_id}
