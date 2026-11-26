"""Çarpışma koreografisi (konudan bağımsız). Bir çekimde kılıç dövüşü eylemi varsa askerleri boşluğa savuran tek tip
bir hat yerine düello çiftleri kurar: konunun karşı tarafından (konu.json 'donemler') teknik izni olan rakipler eklenir,
her çift karşı karşıya durur, her asker izinli vuruş/savunma animasyonlarından birini oynar, zamanlamalar animasyonun
tamamına dağılır; geri kalanlar ikinci safta bekler. Karşı taraf yoksa ya da izinli rakip yoksa uydurulmaz: yalnız
çeşitlilik (farklı vuruş, dağılmış zamanlama, yön) uygulanır ve meta'ya yazılır.

Kurallar: kurallar/koreografi.yaml. Teknik izin: animasyon_izni.izinli (montaj + animasyon testi beyaz listesi)."""
from __future__ import annotations

import json
import math
import struct
from functools import lru_cache

import numpy as np

from motor import ayar
from motor.uretim import animasyon_izni, secici, veri


@lru_cache(None)
def _kutuphane_sureleri(yol: str) -> dict[str, float]:
    b = open(yol, "rb").read()
    n = struct.unpack("<I", b[12:16])[0]
    j = json.loads(b[20:20 + n])
    out = {}
    for a in j.get("animations", []):
        out[a["name"]] = max(float(j["accessors"][s["input"]]["max"][0]) for s in a["samplers"])
    return out


def sure(anim: str) -> float:
    """Animasyon uzunluğu (sn): temel animasyonlar ölçümden, kütüphane animasyonları kendi GLB'sinden."""
    if "/" in anim:
        kut, ad = anim.split("/", 1)
        yol = ayar.MOTOR / veri.kural("animasyon")["kutuphaneler"][kut]
        return _kutuphane_sureleri(str(yol)).get(ad, 1.0)
    return float(veri.animasyon_olcum().get(anim, {}).get("sure_sn", 1.0))


def _izinli_secenekler(takim: str, adaylar: list[str]) -> list[str]:
    return [a for a in adaylar if a in veri.kural("animasyon")["animasyonlar"] and animasyon_izni.izinli(takim, a)[0]]


def _rakip_takimlari(karsi: str, mesafe: str, k: dict) -> list[tuple[str, list[str]]]:
    """Karşı dönemden, savunma/vuruş animasyonlarından en az birine teknik izni olan kılıçlı takımlar."""
    out, gor = [], set()
    for rol in k["rakip_rolleri"]:
        for e in k["rakip_eylemleri"]:
            for ad, _ in secici.sec(rol, karsi, mesafe, e, None, {"binek": False, "nesneler": []})["uygun"]:
                if ad in gor or veri.takimlar()[ad].get("binek"):
                    continue
                sec = _izinli_secenekler(ad, k["savunma"])
                if sec:
                    out.append((ad, sec))
                    gor.add(ad)
    return out


def uygula(c: dict, odak_i: int, eylem: str | None, donem: str, karsi_donemler: list[str] | None, mesafe: str,
           tohum: int) -> tuple[int, dict | None]:
    """Çekimi yerinde düzenler. Dönüş: (yeni odak indeksi, meta kaydı). Uygulanmazsa çekime dokunmaz."""
    k = veri.kural("koreografi")
    ks = c["karakterler"]
    if not k.get("acik") or eylem not in k["eylemler"] or any(x.get("binek") for x in ks):
        return odak_i, None
    r = np.random.default_rng(tohum * 7 + 3)
    kendi = [i for i, x in enumerate(ks) if _izinli_secenekler(x["takim"], k["saldiri"])]
    if not kendi:
        return odak_i, None
    karsi = next((d for d in (karsi_donemler or []) if d != donem), None)
    rakipler = _rakip_takimlari(karsi, mesafe, k) if karsi else []
    cift = min(len(kendi), int(k["en_cok_cift"])) if rakipler else 0
    sira = [odak_i] + [i for i in kendi if i != odak_i] if odak_i in kendi else kendi
    yan = r.uniform(*k["yan_aralik_m"], size=max(cift, 1))
    xs, sag, sol = [0.0], 0.0, 0.0   # odak çifti ortada; diğerleri iki yana dönüşümlü
    for j in range(1, max(cift, 1)):
        if j % 2:
            sag += float(yan[j]); xs.append(sag)
        else:
            sol -= float(yan[j]); xs.append(sol)
    xs = np.array(xs)
    yeni = []
    for j, i in enumerate(sira):
        x = dict(ks[i])
        secenek = _izinli_secenekler(x["takim"], k["saldiri"])
        x["animasyon"] = secenek[int(r.integers(len(secenek)))]
        x["faz_sn"] = round(float(r.uniform(0, sure(x["animasyon"]))), 3)
        x["hiz_m_sn"] = 0.0
        x.pop("gecikme_sn", None)
        if j < cift:   # ön saf: rakibine bakar
            x["konum"] = [round(float(xs[j] + r.normal(0, 0.15)), 2), round(float(r.normal(0, 0.12)), 2)]
            x["yon_derece"] = round(float(r.uniform(-1, 1) * k["yon_sapmasi_derece"]), 1)
        else:          # arka saf: kılıç elde bekler / sırasını bekler
            arka = j - cift
            x["konum"] = [round(float((arka - (len(sira) - cift - 1) / 2) * k["arka_aralik_m"] + r.normal(0, 0.2)), 2),
                          round(float(-k["arka_derinlik_m"] + r.normal(0, 0.25)), 2)]
            x["yon_derece"] = round(float(r.uniform(-1, 1) * k["yon_sapmasi_derece"] * 1.5), 1)
            bek = _izinli_secenekler(x["takim"], k["bekleme"])
            if bek:
                x["animasyon"] = bek[int(r.integers(len(bek)))]
                x["faz_sn"] = round(float(r.uniform(0, sure(x["animasyon"]))), 3)
        yeni.append(x)
    for j in range(cift):   # karşı taraf: ön saftakinin karşısında, ona bakar
        ad, sec = rakipler[j % len(rakipler)]
        an = sec[int(r.integers(len(sec)))]
        d = float(r.uniform(*k["cift_mesafe_m"]))
        yeni.append({"takim": ad, "rol": "karsi_" + veri.takimlar()[ad]["rol"],
                     "konum": [round(float(xs[j] + r.normal(0, 0.2)), 2), round(d + float(r.normal(0, 0.1)), 2)],
                     "yon_derece": round(180.0 + float(r.uniform(-1, 1) * k["yon_sapmasi_derece"]), 1),
                     "animasyon": an, "faz_sn": round(float(r.uniform(0, sure(an))), 3), "hiz_m_sn": 0.0,
                     **({"olcek": round(float(r.uniform(0.95, 1.05)), 3)})})
    for x in yeni[1:]:   # boy çeşitliliği (şema 0.9-1.1); odak 1.0
        x.setdefault("olcek", round(float(r.uniform(*veri.kural("dizilis")["cesitlilik"]["olcek"])), 3))
    yeni[0].pop("olcek", None)
    c["karakterler"] = yeni
    n_kendi = len(sira)
    ciftler = [[round((yeni[j]["konum"][0] + yeni[n_kendi + j]["konum"][0]) / 2, 2),
                round((yeni[j]["konum"][1] + yeni[n_kendi + j]["konum"][1]) / 2, 2)] for j in range(cift)]
    return 0, {"tur": "duello" if cift else "cesitleme", "cift": cift, "karsi_donem": karsi if cift else None,
               "ciftler": ciftler,
               "rakip_takimlari": sorted({ad for ad, _ in rakipler[:cift]}) if cift else []}
