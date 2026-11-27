"""Dönem kitlerinin siluet ayrışması (renkten bağımsız).

Her takımın ön ve yan siluetinden (karşılaştırma çekimi) boyu normalize edilmiş maske çıkarılır.
1. Kitler arası: her kit çiftinde, aynı roldeki karakterlerin en yüksek siluet benzerliği (eşik: Faz 2'deki 0,80).
2. Yanlış atama: her karakterin en benzer siluetteki komşusu (kendi gövde kopyası hariç) başka bir kitten ve
   benzerlik çok yüksekse, o karakter "başka döneme karışabilir" diye işaretlenir.
3. Uzaktan tanınma: maske 24 piksel boya küçültülüp (uzak plan) en yakın komşunun kiti kendi kiti mi diye bakılır.
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path

import numpy as np
from PIL import Image

from motor import ayar
from motor.varlik.denetim import maske

CEKIM = ayar.ONBELLEK / "karsilastirma"
AYRISMA_ESIGI = 0.80        # Faz 2'de konan geçici eşik (değiştirilmedi)
KARISMA_ESIGI = 0.90        # bundan benzer başka dönem karakteri: karışabilir
UZAK_BOY = 24


def _kucult(m: np.ndarray, boy: int) -> np.ndarray:
    h, w = m.shape
    return np.asarray(Image.fromarray(m.astype(np.uint8) * 255).resize((max(1, round(w * boy / h)), boy), Image.BILINEAR)) > 96


def maskeler(adlar: list[str]) -> dict[str, list[np.ndarray]]:
    return {a: [maske(CEKIM / f"{a}_siluet_{y}.png") for y in ("on", "yan")] for a in adlar}


def benzer(a: list[np.ndarray], b: list[np.ndarray], boy: int | None = None) -> float:
    s = []
    for x, y in zip(a, b):
        if boy:
            x, y = _kucult(x, boy), _kucult(y, boy)
        s.append((x & y).sum() / max(1, (x | y).sum()))
    return float(np.mean(s))


def analiz(takimlar: dict[str, dict]) -> dict:
    adlar = sorted(takimlar)
    M = maskeler(adlar)
    kitler = sorted({t["kit"] for t in takimlar.values()})
    roller = sorted({t["rol"] for t in takimlar.values()})
    ciftler = {}
    for ka, kb in itertools.combinations(kitler, 2):
        rol_s = {}
        for r in roller:
            A = [a for a in adlar if takimlar[a]["kit"] == ka and takimlar[a]["rol"] == r]
            B = [b for b in adlar if takimlar[b]["kit"] == kb and takimlar[b]["rol"] == r]
            if A and B:
                rol_s[r] = round(max(benzer(M[a], M[b]) for a in A for b in B), 3)
        ciftler[f"{ka}|{kb}"] = rol_s
    yakin, uzak_dogru, karisan = {}, 0, []
    for a in adlar:
        aday = [b for b in adlar if b != a]
        s = {b: benzer(M[a], M[b]) for b in aday}
        en = max(s, key=s.get)
        yakin[a] = {"en_yakin": en, "benzerlik": round(s[en], 3), "ayni_kit": takimlar[en]["kit"] == takimlar[a]["kit"]}
        baska = {b: v for b, v in s.items() if takimlar[b]["kit"] != takimlar[a]["kit"]}
        bb = max(baska, key=baska.get)
        yakin[a]["en_yakin_baska_kit"] = bb
        yakin[a]["baska_kit_benzerlik"] = round(baska[bb], 3)
        if baska[bb] >= KARISMA_ESIGI:
            karisan.append(f"{a} ({takimlar[a]['kit']}) ile {bb} ({takimlar[bb]['kit']}) siluet olarak {baska[bb]:.2f} benzer")
        su = {b: benzer(M[a], M[b], UZAK_BOY) for b in aday}
        enu = max(su, key=su.get)
        yakin[a]["uzak_en_yakin"] = enu
        yakin[a]["uzak_dogru_kit"] = takimlar[enu]["kit"] == takimlar[a]["kit"]
        uzak_dogru += yakin[a]["uzak_dogru_kit"]
    ayrismayan = [f"{c}: {r} {v:.2f}" for c, rs in ciftler.items() for r, v in rs.items() if v >= AYRISMA_ESIGI]
    return {
        "esikler": {"ayrisma": AYRISMA_ESIGI, "karisma": KARISMA_ESIGI, "uzak_boy_px": UZAK_BOY},
        "kit_ciftleri": ciftler,
        "ayrismayan": ayrismayan,
        "karisabilir": karisan,
        "uzak_tanima_orani": round(uzak_dogru / len(adlar), 3),
        "karakterler": yakin,
    }


if __name__ == "__main__":
    oz = json.loads((Path(__file__).resolve().parent / "derlenmis3.json").read_text())
    r = analiz(oz["takimlar"] | {})
    print(json.dumps({k: r[k] for k in ("ayrismayan", "karisabilir", "uzak_tanima_orani")}, ensure_ascii=False, indent=1))
