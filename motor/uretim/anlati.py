"""Shorts anlatı yapısı denetimi: güçlü açılış (ölçülen süre), amaç sırası, sadelik.

Uzun video ayrı kurallarla denetlenecek (kurallar/uzun.yaml; henüz yok)."""
from __future__ import annotations

import re

from motor.uretim import veri


def kanca_merak_isareti(metin: str) -> list[str]:
    k = veri.kural("shorts")["kanca"]["merak_isaretleri"]
    bulunan = []
    if k.get("rakam") and re.search(r"\d", metin):
        bulunan.append("rakam")
    if k.get("soru") and "?" in metin:
        bulunan.append("soru")
    kelimeler = set(re.findall(r"\w+", metin.lower()))
    bulunan += [f"'{w}'" for w in k.get("kelimeler", []) if w in kelimeler]
    return bulunan


def shorts_denetle(senaryo: dict, sureler: dict) -> tuple[list[str], dict]:
    """sureler: seslendirme.olc() çıktısı. Dönüş: (hatalar, ölçümler)."""
    k = veri.kural("shorts")
    h, o = [], {}
    if senaryo["format"] != "shorts":
        return [f"senaryo biçimi '{senaryo['format']}': Shorts denetimi uygulanamaz"], o
    if not senaryo.get("ana_fikir"):
        h.append("Shorts senaryosunun tek bir 'ana_fikir' cümlesi olmalı")
    cs = senaryo["cumleler"]
    if len(cs) > k["cumle"]["en_cok"]:
        h.append(f"{len(cs)} cümle; Shorts için en çok {k['cumle']['en_cok']}")
    sira = k["amac_sirasi"]
    onceki = -1
    for c in cs:
        if "amac" not in c:
            h.append(f"{c['id']}: anlatı amacı (amac) yok")
            continue
        i = sira.index(c["amac"])
        if i < onceki:
            h.append(f"{c['id']}: '{c['amac']}' amacı anlatı sırasını bozuyor")
        onceki = max(onceki, i)
        n = len(re.findall(r"\w+", c["metin"]))
        if n > k["cumle"]["en_cok_kelime"]:
            h.append(f"{c['id']}: {n} kelime; en çok {k['cumle']['en_cok_kelime']}")
    if cs[0]["id"] != senaryo["kanca"] or cs[0].get("amac") != "kanca":
        h.append("kanca ilk cümle olmalı ve amacı 'kanca' olmalı")
    if cs[-1]["id"] != senaryo["final"] or cs[-1].get("amac") != "final":
        h.append("final son cümle olmalı ve amacı 'final' olmalı")
    kanca = cs[0]
    ks = sureler[kanca["id"]]["sure_sn"]
    o["kanca_sure_sn"] = ks
    o["kanca_merak_isaretleri"] = kanca_merak_isareti(kanca["metin"])
    if ks > k["kanca"]["en_cok_sure_sn"]:
        h.append(f"kanca seslendirmesi {ks:.2f} sn sürüyor (ölçülen); en çok {k['kanca']['en_cok_sure_sn']} sn")
    if not o["kanca_merak_isaretleri"]:
        h.append("kancada merak işareti yok (sayı, soru ya da sıradışılık bildiren kelime)")
    return h, o
