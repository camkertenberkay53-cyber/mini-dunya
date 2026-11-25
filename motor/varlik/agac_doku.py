"""Ağaç kartı dokuları: CC0 fotoğraf kaynaklarından (ambientCG Leaf001, Poly Haven fir_sapling_medium) türetilmiş
alfalı yaprak salkımı ve iğne dalı kartları. Tohumlu, belirlenimci; kendi kodumuz (PIL + numpy).

python3 -m motor.varlik.agac_doku <cikti_klasoru>
Çıktı: yaprak_salkim.png (1024², RGBA), igne_dal.png (1024x512, RGBA), kaynak.json (kaynak dosyalar ve sha256)."""
from __future__ import annotations

import hashlib
import json
import math
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

CC0 = Path(__file__).resolve().parent / "cc0"
LEAF = CC0 / "ambientcg" / "Leaf001"
FIR = CC0 / "polyhaven" / "fir_sapling_medium" / "textures" / "fir_sapling_medium_twigs_diff_1k.jpg"


def _parcalar(rgba: Image.Image, en_az: int = 400) -> list[Image.Image]:
    """Alfa maskesindeki bağlı bölgeler (yaprak/dal sprite'ları) → ayrı RGBA parçalar."""
    a = np.array(rgba.split()[3]) > 40
    from collections import deque
    gor = np.zeros_like(a)
    out = []
    h, w = a.shape
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            if a[y, x] and not gor[y, x]:
                q = deque([(y, x)])
                gor[y, x] = True
                ys, xs = [y], [x]
                while q:
                    cy, cx = q.popleft()
                    for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                        if 0 <= ny < h and 0 <= nx < w and a[ny, nx] and not gor[ny, nx]:
                            gor[ny, nx] = True
                            q.append((ny, nx))
                            ys.append(ny)
                            xs.append(nx)
                if len(ys) >= en_az:
                    out.append(rgba.crop((min(xs), min(ys), max(xs) + 1, max(ys) + 1)))
    return out


def yaprak_salkim(cikti: Path, tohum: int = 7) -> None:
    r = random.Random(tohum)
    renk = Image.open(LEAF / "diff.jpg").convert("RGB")
    rgba = renk.copy()
    rgba.putalpha(Image.open(LEAF / "opak.jpg").convert("L"))
    yapraklar = _parcalar(rgba.resize((512, 512), Image.LANCZOS), 300)
    S = 1024
    kart = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(kart)
    # ince dallar (yaprakların altında)
    for _ in range(7):
        x0, y0 = S * 0.5 + r.uniform(-60, 60), S * 0.98
        x, y = x0, y0
        aci = math.radians(r.uniform(-120, -60))
        for _ in range(9):
            nx, ny = x + math.cos(aci) * r.uniform(50, 90), y + math.sin(aci) * r.uniform(50, 90)
            d.line((x, y, nx, ny), fill=(70, 55, 40, 255), width=r.choice([3, 4, 5]))
            x, y = nx, ny
            aci += math.radians(r.uniform(-25, 25))
    # yapraklar: elips içinde, merkeze yoğun; ton ve parlaklık değişkenliği (güneş/gölge yaprakları)
    for i in range(520):
        while True:
            u, v = r.uniform(-1, 1), r.uniform(-1, 1)
            if u * u + v * v <= 1 and r.random() < 1.15 - (u * u + v * v) * 0.6:
                break
        cx, cy = S * 0.5 + u * S * 0.42, S * 0.47 + v * S * 0.42
        y_ = r.choice(yapraklar)
        k = r.uniform(0.07, 0.12) * S / max(y_.size)
        p = y_.resize((max(4, int(y_.width * k)), max(4, int(y_.height * k))), Image.LANCZOS).rotate(r.uniform(0, 360), Image.BICUBIC, expand=True)
        arr = np.array(p).astype(np.float32)
        ton = r.uniform(0.42, 0.95)   # gölgedeki iç yapraklar koyu, dıştakiler açık
        arr[..., 0] *= ton * r.uniform(0.72, 0.9)
        arr[..., 1] *= ton * 0.92
        arr[..., 2] *= ton * r.uniform(0.6, 0.85)
        p = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGBA")
        kart.alpha_composite(p, (int(cx - p.width / 2), int(cy - p.height / 2)))
    _kenar_tasir(kart).save(cikti / "yaprak_salkim.png")


def igne_dal(cikti: Path, tohum: int = 11) -> None:
    r = random.Random(tohum)
    src = Image.open(FIR).convert("RGB")
    a = np.array(src).astype(np.float32)
    lum = a.mean(axis=2)
    alfa = np.clip((lum - 14) * 6, 0, 255).astype(np.uint8)
    alfa[:, : int(src.width * 0.13)] = 0                       # sol kenardaki kabuk şeridi hariç
    alfa[int(src.height * 0.8):, :] = 0                       # alttaki kuru dal çizimi hariç
    rgba = src.copy()
    rgba.putalpha(Image.fromarray(alfa))
    dallar = [p for p in _parcalar(rgba, 2500) if p.height > 60
              and np.array(p)[..., 1][np.array(p)[..., 3] > 40].mean() > np.array(p)[..., 0][np.array(p)[..., 3] > 40].mean() * 1.08]   # yalnız yeşil iğneli parçalar
    W, H = 1024, 512
    kart = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(kart)
    d.line((10, H / 2, W - 20, H / 2 + r.uniform(-8, 8)), fill=(80, 62, 45, 255), width=7)   # ana dal (kart boyunca)
    x = 30.0
    while x < W - 60:
        for yon in (-1, 1):
            p = r.choice(dallar)
            k = r.uniform(0.55, 0.9) * (1.0 - 0.45 * x / W) * (H * 0.55) / p.height
            q = p.resize((max(4, int(p.width * k)), max(4, int(p.height * k))), Image.LANCZOS)
            q = q.rotate(-r.uniform(45, 70), Image.BICUBIC, expand=True)   # dal ucu ana dalın ucuna doğru eğik
            ton = r.uniform(0.8, 1.1)
            arr = np.array(q).astype(np.float32)
            arr[..., :3] *= ton
            q = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGBA")
            if yon < 0:
                q = q.transpose(Image.FLIP_TOP_BOTTOM)
            kart.alpha_composite(q, (int(x - q.width * 0.3), int(H / 2 - (q.height * 0.85 if yon < 0 else q.height * 0.15))))
        x += r.uniform(35, 55)
    _kenar_tasir(kart).save(cikti / "igne_dal.png")


def _kenar_tasir(im: Image.Image) -> Image.Image:
    """Saydam piksellerin rengini komşu yaprak rengiyle doldurur (mipmap'te kara hale olmasın); alfa değişmez."""
    rgb = im.convert("RGB")
    a = im.split()[3]
    dolu = rgb.copy()
    for _ in range(6):
        dolu = Image.composite(dolu, dolu.filter(ImageFilter.MaxFilter(5)), a.point(lambda v: 255 if v > 10 else 0))
        a = a.filter(ImageFilter.MaxFilter(5))
    out = dolu.convert("RGBA")
    out.putalpha(im.split()[3])
    return out


def main(cikti: str) -> int:
    c = Path(cikti)
    c.mkdir(parents=True, exist_ok=True)
    yaprak_salkim(c)
    igne_dal(c)
    kay = {str(p.relative_to(CC0)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (LEAF / "diff.jpg", LEAF / "opak.jpg", FIR)}
    (c / "kaynak.json").write_text(json.dumps({"kaynaklar": kay, "lisans": "CC0 1.0 (kaynaklar cc0/lisans.json)",
                                               "uretim": "motor/varlik/agac_doku.py (kendi kodumuz)"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
