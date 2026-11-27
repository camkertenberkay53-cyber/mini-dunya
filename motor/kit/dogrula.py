"""Dönem kiti doğrulayıcı.

python3 -m motor.kit.dogrula [kit.yaml ...]      (varsayılan: motor/kit/*.yaml)

Bir kit ancak şu durumda KULLANILABİLİR:
1. Her zorunlu rolde en az MIN_VARYANT ayrışan karakter var (renk kopyaları tek varyant sayılır).
2. Hiçbir karakter C seviyesi değil (stilize/chibi/düşük poligon/iskelet uyumsuz).
3. Her karakterin kıyafet dönemi kitin kabul ettiği dönemlerden biri.
4. Kitin piyadesi, diğer her kitin piyadesinden siluet olarak ayrışıyor (renkten bağımsız test).
Eksik olan her şey adıyla raporlanır; kit sessizce başka varlıkla doldurulmaz.
"""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import numpy as np
import yaml

from motor import ayar

KIT_KLASORU = Path(__file__).resolve().parent
MASKE = ayar.ONBELLEK / "denetim"
ZORUNLU_ROLLER = ("piyade", "okcu", "suvari", "komutan", "isci_sivil")
MIN_VARYANT = 3
# Siluet benzerliği (önden ve yandan kesişim/birleşim ortalaması). Ölçülen dayanak noktaları (Faz 2):
#   renk kopyası 1,00 | aynı gövdede korucu-köylü kıyafeti ~0,84 | gerçek oranlı - chibi ~0,32
# Aynı gövdede kıyafet değiştirmek bile 0,80'i aşıyor; dönemler arası fark bundan büyük olmalı.
# Faz 3'te gerçek dönem kitleriyle yeniden ayarlanacak (geçici eşik).
AYRISMA_ESIGI = 0.80
VARYANT_KOPYA_ESIGI = 0.97


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    return float((a & b).sum() / max(1, (a | b).sum()))


def benzerlik(x: str, y: str) -> float:
    return round(np.mean([_iou(np.load(MASKE / f"{x}_maske_{d}.npy"), np.load(MASKE / f"{y}_maske_{d}.npy")) for d in (0, 90)]), 3)


def _ayrisan(liste: list[str]) -> list[str]:
    """Birbirinin siluet kopyası olmayan varyantlar (renk değişimi ya da aynı tarif tek sayılır)."""
    secilen: list[str] = []
    for k in liste:
        if all(k != s and benzerlik(k, s) < VARYANT_KOPYA_ESIGI for s in secilen):
            secilen.append(k)
    return secilen


def kit_denetle(kit: dict, denetim: dict, zorunlu=ZORUNLU_ROLLER, min_varyant=MIN_VARYANT) -> dict:
    hatalar, uyarilar = [], []
    roller = kit.get("roller", {}) or {}
    for rol in zorunlu:
        if rol not in roller or not roller[rol]:
            hatalar.append(f"BOŞ ROL: {rol} için uygun varlık yok")
    for rol, liste in roller.items():
        gecerli = []
        for k in liste or []:
            d = denetim.get(k)
            if d is None:
                hatalar.append(f"{rol}/{k}: denetlenmemiş varlık")
                continue
            if d["seviye"] == "C":
                hatalar.append(f"{rol}/{k}: C seviyesi ({'; '.join(d['gerekce'])[:90]})")
                continue
            if not set(d["donem"]) & set(kit["kabul_edilen_donemler"]):
                hatalar.append(f"{rol}/{k}: DÖNEM DIŞI (kıyafet {','.join(d['donem'])}; kit {','.join(kit['kabul_edilen_donemler'])})")
                continue
            gecerli.append(k)
        kit.setdefault("_gecerli", {})[rol] = gecerli
        ayr = _ayrisan(gecerli)
        if liste and len(ayr) < min_varyant:
            hatalar.append(f"{rol}: {len(ayr)} ayrışan varyant (en az {min_varyant}); renk kopyaları tek sayılır")
    return {"ad": kit["ad"], "etiket": kit["etiket"], "hatalar": hatalar, "uyarilar": uyarilar}


def kitler_arasi(kitler: dict[str, dict]) -> list[str]:
    """Her kit çiftinin piyadelerini siluet olarak karşılaştırır."""
    hatalar = []
    for (a, ka), (b, kb) in itertools.combinations(kitler.items(), 2):
        # yalnızca denetimden geçmiş üyeler karşılaştırılır
        pa = ka.get("_gecerli", {}).get("piyade") or []
        pb = kb.get("_gecerli", {}).get("piyade") or []
        if not pa or not pb:
            continue
        en = max(benzerlik(x, y) for x in pa for y in pb)
        if en >= AYRISMA_ESIGI:
            hatalar.append(f"AYRIŞMIYOR: {a} ile {b} piyadeleri siluet olarak {en:.2f} benzer (eşik {AYRISMA_ESIGI})")
    return hatalar


def dogrula(yollar: list[Path], min_varyant=MIN_VARYANT, zorunlu=ZORUNLU_ROLLER) -> dict:
    denetim = json.loads(ayar.DENETIM_RAPOR.read_text())
    kitler = {p.stem: yaml.safe_load(p.read_text(encoding="utf-8")) for p in yollar}
    sonuc = {ad: kit_denetle(k, denetim, zorunlu, min_varyant) for ad, k in kitler.items()}
    for h in kitler_arasi(kitler):
        for ad in kitler:
            if f" {ad} " in f" {h} ":
                sonuc[ad]["hatalar"].append(h)
    for s in sonuc.values():
        s["durum"] = "KULLANILABİLİR" if not s["hatalar"] else "KULLANILAMAZ"
    return sonuc


if __name__ == "__main__":
    yollar = [Path(a) for a in sys.argv[1:]] or sorted(KIT_KLASORU.glob("*.yaml"))
    for ad, s in dogrula(yollar).items():
        print(f"{s['durum']:15s} {ad}")
        for h in s["hatalar"]:
            print("   -", h)
