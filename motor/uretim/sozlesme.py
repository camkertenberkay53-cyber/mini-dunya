"""Katmanlar arası JSON sözleşmeleri: şema doğrulaması + çapraz başvuru denetimi.

python3 -m motor.uretim.sozlesme <tur> <dosya.json> [arastirma.json] [senaryo.json]
tur: konu | arastirma | senaryo | cekim_plani
"""
from __future__ import annotations

import json
import sys
from functools import lru_cache

import jsonschema

from motor.uretim import veri

TEMKINLI_GUVEN = {"belirsiz", "tartismali"}


@lru_cache(None)
def sema(tur: str) -> dict:
    return json.loads((veri.SEMALAR / f"{tur}.schema.json").read_text())


def sema_hatalari(tur: str, belge: dict) -> list[str]:
    v = jsonschema.Draft202012Validator(sema(tur))
    return [f"{tur}: {'/'.join(str(p) for p in e.absolute_path) or '(kök)'}: {e.message}"
            for e in sorted(v.iter_errors(belge), key=lambda e: list(map(str, e.absolute_path)))]


def _tekrar(ids: list[str], ad: str) -> list[str]:
    gorulen, h = set(), []
    for i in ids:
        if i in gorulen:
            h.append(f"{ad}: '{i}' kimliği birden fazla kez kullanılmış")
        gorulen.add(i)
    return h


def konu_denetle(k: dict) -> list[str]:
    h = sema_hatalari("konu", k)
    if h:
        return h
    gecerli = {x["etiket"] for x in veri.kitler().values()}
    for d in k["donemler"]:
        if d not in gecerli:
            h.append(f"konu: '{d}' dönemi için kit yok (mevcut: {', '.join(sorted(gecerli))})")
    a, b = k["hedef_sure_sn"]
    if a > b:
        h.append("konu: hedef_sure_sn [en az, en çok] sırasında olmalı")
    return h


def arastirma_denetle(a: dict) -> list[str]:
    h = sema_hatalari("arastirma", a)
    if h:
        return h
    kaynaklar = {k["id"] for k in a["kaynaklar"]}
    h += _tekrar([k["id"] for k in a["kaynaklar"]], "araştırma kaynakları")
    h += _tekrar([c["id"] for c in a["kartlar"]], "araştırma kartları")
    for c in a["kartlar"]:
        for kid in c["kaynaklar"]:
            if kid not in kaynaklar:
                h.append(f"kart {c['id']}: tanımsız kaynak {kid}")
    return h


def senaryo_denetle(s: dict, a: dict | None) -> list[str]:
    h = sema_hatalari("senaryo", s)
    if h:
        return h
    ids = [c["id"] for c in s["cumleler"]]
    h += _tekrar(ids, "senaryo cümleleri")
    for k in ("kanca", "final"):
        if s[k] not in ids:
            h.append(f"senaryo: {k} '{s[k]}' cümlelerde yok")
    kartlar = {c["id"]: c for c in (a or {}).get("kartlar", [])}
    temkin = veri.kural("dil_tr")["temkin_ifadeleri"]
    for c in s["cumleler"]:
        if c.get("olgusal", True) and not c["kartlar"]:
            h.append(f"{c['id']}: olgusal cümle hiçbir araştırma kartına dayanmıyor")
        for kid in c["kartlar"]:
            if kid not in kartlar:
                h.append(f"{c['id']}: tanımsız kart {kid}")
            elif kartlar[kid]["guven"] in TEMKINLI_GUVEN and not any(t in c["metin"].lower() for t in temkin):
                h.append(f"{c['id']}: '{kartlar[kid]['guven']}' karta ({kid}) dayanıyor ama kesin dille anlatılmış")
        n = c["niyet"]
        if n["tur"] == "3d" and not n.get("roller") and not (n.get("ortam") or {}).get("cevre") and not n.get("aciklama"):
            h.append(f"{c['id']}: 3D görsel niyetinde ne gösterileceği yok")
        if n["tur"] in ("harita", "bilgi_karti") and not n.get("metin") and not n.get("aciklama") and not n.get("evre"):
            h.append(f"{c['id']}: {n['tur']} niyetinin içeriği yok")
        if n["tur"] == "gorsel25d" and not (n.get("gorsel25d") or {}).get("gorsel_id"):   # Faz-53A
            h.append(f"{c['id']}: 2.5D niyetinde görsel kimliği (gorsel25d.gorsel_id) yok")
    return h


def plan_ortusu(p: dict, s: dict) -> list[str]:
    """Her cümle en az bir çekimle gösterilmeli; her çekim var olan cümlelere bağlı olmalı."""
    h = []
    cumleler = [c["id"] for c in s["cumleler"]]
    ortulen = {i for c in p["cekimler"] for i in c["cumleler"]}
    for i in cumleler:
        if i not in ortulen:
            h.append(f"{i}: hiçbir çekimde gösterilmiyor")
    for c in p["cekimler"]:
        if not c["cumleler"]:
            h.append(f"{c['id']}: hiçbir cümleye bağlı değil (metinsiz çekim)")
        for i in c["cumleler"]:
            if i not in cumleler:
                h.append(f"{c['id']}: tanımsız cümle {i}")
    return h


if __name__ == "__main__":
    tur, yol = sys.argv[1], sys.argv[2]
    belge = json.loads(open(yol).read())
    ek = [json.loads(open(x).read()) for x in sys.argv[3:]]
    if tur == "konu":
        hatalar = konu_denetle(belge)
    elif tur == "arastirma":
        hatalar = arastirma_denetle(belge)
    elif tur == "senaryo":
        hatalar = senaryo_denetle(belge, ek[0] if ek else None)
    else:
        hatalar = sema_hatalari(tur, belge) + (plan_ortusu(belge, ek[1]) if len(ek) > 1 else [])
    print("\n".join(hatalar) if hatalar else f"{tur}: GEÇTİ")
    sys.exit(1 if hatalar else 0)
