"""Kamera ve çekim çeşitliliği denetimi + benzer (tekrar eden) çekim tespiti.

Ölçek (plan) olarak planlayıcının niyeti değil, kadraj ölçümüyle bulunan sınıf kullanılır."""
from __future__ import annotations

from collections import Counter

from motor.uretim import veri

BENZERLIK_ALANLARI = ("plan", "hareket", "yukseklik", "aci_kovasi", "dizilis", "odak", "arazi")


def kayitlar(plan: dict, denetim: dict) -> list[dict]:
    r = []
    for c in plan["cekimler"]:
        if c["tur"] != "3d":
            continue
        m = dict(c.get("meta", {}))
        m["id"] = c["id"]
        m["plan"] = denetim["cekimler"].get(c["id"], {}).get("olcum", {}).get("kamera_plani_olculen") or c["kamera"]["plan"]
        r.append(m)
    return r


def denetle(plan: dict, denetim: dict) -> tuple[list[str], dict]:
    k = veri.kural("cesitlilik")
    ks = kayitlar(plan, denetim)
    h = []
    for a, b in zip(ks, ks[1:]):
        if k["ardisik_ayni_plan_ve_hareket"] == "yasak" and (a["plan"], a["hareket"]) == (b["plan"], b["hareket"]):
            h.append(f"{a['id']} ve {b['id']}: ardışık aynı ölçek ve kamera hareketi ({a['plan']}, {a['hareket']})")
        elif k["ardisik_ayni_hareket"] == "yasak" and a["hareket"] == b["hareket"]:
            h.append(f"{a['id']} ve {b['id']}: ardışık aynı kamera hareketi ({a['hareket']})")
    say = {alan: Counter(x[alan] for x in ks) for alan in ("plan", "hareket", "yukseklik", "aci_kovasi", "tur")}
    for alan, kural in (("hareket", "en_az_farkli_hareket"), ("plan", "en_az_farkli_plan_olcegi"),
                        ("yukseklik", "en_az_farkli_yukseklik_sinifi"), ("aci_kovasi", "en_az_farkli_aci_kovasi")):
        if len(say[alan]) < k[kural]:
            h.append(f"farklı {alan} sayısı {len(say[alan])}; en az {k[kural]}")
    if ks:
        en, adet = say["hareket"].most_common(1)[0]
        if adet / len(ks) > k["bir_hareketin_en_cok_payi"]:
            h.append(f"'{en}' hareketi çekimlerin %{100 * adet / len(ks):.0f}'inde; en çok %{100 * k['bir_hareketin_en_cok_payi']:.0f}")
    benzer = {}
    for x in ks:
        imza = tuple(x.get(a) for a in BENZERLIK_ALANLARI)
        benzer.setdefault(imza, []).append(x["id"])
    tekrarlar = [v for v in benzer.values() if len(v) > 1]
    if k["benzer_cekim"] == "yasak":
        h += [f"benzer çekim: {', '.join(v)} (aynı ölçek, hareket, yükseklik, açı, diziliş, odak ve arazi)" for v in tekrarlar]
    rapor = {"cekim_sayisi": len(ks), "dagilim": {a: dict(v) for a, v in say.items()}, "sira": ks, "benzer_gruplar": tekrarlar}
    return h, rapor
