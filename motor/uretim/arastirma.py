"""Kaynaklı araştırma kartları ve iddia → kaynak takibi.

Kartlar ister bir araştırma ajanınca (bu pilotta Claude, web araması ile) ister ileride Gemini ile üretilsin,
aynı denetimden geçer. Bu modül kartları ÜRETMEZ; kaynak kurallarını uygular ve senaryodaki her cümlenin hangi
iddiaya, o iddianın hangi kaynağa dayandığını gösteren izi çıkarır.
"""
from __future__ import annotations

from motor.uretim import sozlesme, veri


def kart_denetle(a: dict) -> list[str]:
    h = sozlesme.arastirma_denetle(a)
    if h:
        return h
    k = veri.kural("arastirma")
    kaynak = {x["id"]: x for x in a["kaynaklar"]}
    for x in a["kaynaklar"]:
        if x["tur"] in k["url_zorunlu_turler"] and not x.get("url"):
            h.append(f"kaynak {x['id']}: {x['tur']} kaynakta bağlantı (url) zorunlu")
    for c in a["kartlar"]:
        if c["guven"] != "kesin":
            continue
        turler = [kaynak[i]["tur"] for i in c["kaynaklar"] if i in kaynak]
        yeterli = len(set(c["kaynaklar"])) >= k["kesin_icin"]["en_az_kaynak"]
        if not yeterli:
            h.append(f"kart {c['id']}: 'kesin' için en az {k['kesin_icin']['en_az_kaynak']} kaynak gerekir ({len(turler)} var)")
    return h


def kaynak_izi(senaryo: dict, a: dict) -> list[dict]:
    """Her cümle: metin, amaç, dayandığı kartlar (iddia + güven), kartların kaynakları (başlık + bağlantı)."""
    kart = {c["id"]: c for c in a["kartlar"]}
    kaynak = {x["id"]: x for x in a["kaynaklar"]}
    iz = []
    for c in senaryo["cumleler"]:
        kartlar = []
        for kid in c["kartlar"]:
            k = kart.get(kid)
            if k is None:
                kartlar.append({"id": kid, "hata": "tanımsız kart"})
                continue
            kartlar.append({"id": kid, "iddia": k["iddia"], "guven": k["guven"],
                            "kaynaklar": [{"id": i, "baslik": kaynak[i]["baslik"], "tur": kaynak[i]["tur"], "url": kaynak[i].get("url")}
                                          for i in k["kaynaklar"] if i in kaynak]})
        en_zayif = min((x.get("guven", "kesin") for x in kartlar), key=["tartismali", "belirsiz", "makul", "kesin"].index) if kartlar else None
        iz.append({"cumle": c["id"], "metin": c["metin"], "amac": c.get("amac"), "olgusal": c.get("olgusal", True),
                   "kartlar": kartlar, "en_zayif_guven": en_zayif})
    return iz


def kullanilmayan_kartlar(senaryo: dict, a: dict) -> list[str]:
    kullanilan = {k for c in senaryo["cumleler"] for k in c["kartlar"]}
    return [c["id"] for c in a["kartlar"] if c["id"] not in kullanilan]
