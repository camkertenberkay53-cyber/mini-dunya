"""Kamera ve çekim çeşitliliği denetimi + benzer (tekrar eden) çekim tespiti.

Ölçek (plan) olarak planlayıcının niyeti değil, kadraj ölçümüyle bulunan sınıf kullanılır.
Faz-64b: yalnız gerçek render kamera yapılandırması olan 3D çekimler sayılır; kamerası kurulamamış 3D çekim kontrollü
hata üretir (KeyError değil); aynı kamera yapılandırması farklı kimlikle tekrar edilirse çeşitlilik sayılmaz."""
from __future__ import annotations

import json
from collections import Counter

from motor.uretim import veri

BENZERLIK_ALANLARI = ("plan", "hareket", "yukseklik", "aci_kovasi", "dizilis", "odak", "arazi")


def _kamera_kaydi(c: dict, denetim: dict) -> tuple[dict | None, str | None]:
    """Faz-64b: bir 3D çekimin çeşitlilik kaydı YALNIZ gerçek render kamera yapılandırmasından (c['kamera'] — Godot'un
    okuduğu alan) ve onu üreten kamera türünden (meta.tur → kurallar/kamera.yaml). Kamera yoksa/bozuksa varsayılan
    UYDURULMAZ: (None, kontrollü hata). 2.5D ve harita bu fonksiyona hiç gelmez (onların render şemasında 3D kamera yok).
      hareket   = c['kamera']['hareket']
      yukseklik = c['kamera']['bas']['konum'][1] sınıfı (başlangıç kamera yüksekliği)
      aci_kovasi= kamera türünün açısı (aci_derece; başlangıç karesinin geometrik açısı yörünge/kaydırma
                  hareketlerinde nominalden sapar, bu yüzden türün tasarlanan açısı kullanılır)
      plan      = kadraj ölçümü (yoksa c['kamera']['plan'])"""
    from motor.uretim import planlayici
    kam = c.get("kamera")
    if not isinstance(kam, dict) or not kam.get("hareket") or not isinstance(kam.get("bas"), dict) \
            or not isinstance(kam["bas"].get("konum"), list) or len(kam["bas"]["konum"]) != 3:
        return None, (f"{c['id']}: 3D çekimde gerçek kamera yapılandırması yok (planlayıcı kamerayı kuramadı: niyette "
                      f"oyuncuya dönüşen rol ya da uygun kamera türü yok); kamera çeşitliliği ölçülemez")
    kat = veri.kural("kamera")["cekimler"]
    tur = (c.get("meta") or {}).get("tur")
    if tur not in kat:
        return None, f"{c['id']}: 3D çekimin kamera türü bilinmiyor ({tur!r}); kamera çeşitliliği ölçülemez"
    if kat[tur]["hareket"] != kam["hareket"]:
        return None, (f"{c['id']}: render kamerasının hareketi ({kam['hareket']}) kamera türünün hareketiyle "
                      f"({tur}: {kat[tur]['hareket']}) tutarsız")
    m = dict(c.get("meta") or {})
    m["id"] = c["id"]
    m["hareket"] = kam["hareket"]
    m["yukseklik"] = planlayici._yukseklik_sinifi(float(kam["bas"]["konum"][1]))
    m["aci_kovasi"] = planlayici._aci_kovasi(float(kat[tur]["aci_derece"]))
    m["plan"] = denetim["cekimler"].get(c["id"], {}).get("olcum", {}).get("kamera_plani_olculen") or kam.get("plan")
    return m, None


def _ayir(plan: dict, denetim: dict) -> tuple[list[dict], list[str], list[str], list[list[str]]]:
    """(kayıtlar [plan sırasıyla; a/b alt çekimleri dahil], kamerasız/bozuk 3D hataları, kamerasız kimlikler,
    aynı render kamerasını paylaşan kimlik grupları)."""
    ks, hatalar, eksik, imzalar = [], [], [], {}
    for c in plan["cekimler"]:
        if c.get("tur") != "3d":
            continue
        m, hata = _kamera_kaydi(c, denetim)
        if hata:
            hatalar.append(hata)
            eksik.append(c["id"])
            continue
        imzalar.setdefault(json.dumps(c["kamera"], sort_keys=True), []).append(c["id"])
        ks.append(m)
    return ks, hatalar, eksik, [v for v in imzalar.values() if len(v) > 1]


def kayitlar(plan: dict, denetim: dict) -> list[dict]:
    """Gerçek kamera yapılandırması olan 3D çekimlerin kayıtları (plan sırasıyla, a/b alt çekimleri dahil)."""
    return _ayir(plan, denetim)[0]


def esikler(bicim: str | None, uc_d_sayisi: int) -> dict:
    """Biçime göre geçerli çeşitlilik kuralları (Faz-64: planlayıcı da aynı eşikleri hedefler; tek kaynak)."""
    k = veri.kural("cesitlilik")
    if bicim == "uzun":   # Faz-62c: sınırlı 3D — "en az farklı" eşikleri 3D çekim sayısıyla ölçeklenir
        n = (uc_d_sayisi + 1) // 2
        k = dict(k, **{x: min(k[x], n) for x in ("en_az_farkli_hareket", "en_az_farkli_plan_olcegi",
                                                  "en_az_farkli_yukseklik_sinifi", "en_az_farkli_aci_kovasi")})
        if uc_d_sayisi < 3:
            k["bir_hareketin_en_cok_payi"] = 1.0
    return k


def denetle(plan: dict, denetim: dict) -> tuple[list[str], dict]:
    ks, h, kamerasiz, kamera_tekrari = _ayir(plan, denetim)
    # Faz-64b: aynı render kamerası farklı kimlikle tekrarlanırsa çeşitlilik sayımına bir kez girer
    # (dağılım, eşikler ve pay); tekrar ayrıca 'benzer çekim' olarak raporlanır
    tekrar_ids = {i for g in kamera_tekrari for i in g[1:]}
    tekil = [x for x in ks if x["id"] not in tekrar_ids]
    k = esikler(plan.get("format"), len(tekil))
    for a, b in zip(ks, ks[1:]):
        if k["ardisik_ayni_plan_ve_hareket"] == "yasak" and (a["plan"], a["hareket"]) == (b["plan"], b["hareket"]):
            h.append(f"{a['id']} ve {b['id']}: ardışık aynı ölçek ve kamera hareketi ({a['plan']}, {a['hareket']})")
        elif k["ardisik_ayni_hareket"] == "yasak" and a["hareket"] == b["hareket"]:
            h.append(f"{a['id']} ve {b['id']}: ardışık aynı kamera hareketi ({a['hareket']})")
    say = {alan: Counter(x[alan] for x in tekil) for alan in ("plan", "hareket", "yukseklik", "aci_kovasi", "tur")}
    for alan, kural in (("hareket", "en_az_farkli_hareket"), ("plan", "en_az_farkli_plan_olcegi"),
                        ("yukseklik", "en_az_farkli_yukseklik_sinifi"), ("aci_kovasi", "en_az_farkli_aci_kovasi")):
        if len(say[alan]) < k[kural]:
            h.append(f"farklı {alan} sayısı {len(say[alan])}; en az {k[kural]}")
    if tekil:
        en, adet = say["hareket"].most_common(1)[0]
        if adet / len(tekil) > k["bir_hareketin_en_cok_payi"]:
            h.append(f"'{en}' hareketi çekimlerin %{100 * adet / len(tekil):.0f}'inde; en çok %{100 * k['bir_hareketin_en_cok_payi']:.0f}")
    benzer = {}
    for x in ks:
        imza = tuple(x.get(a) for a in BENZERLIK_ALANLARI)
        benzer.setdefault(imza, []).append(x["id"])
    tekrarlar = [v for v in benzer.values() if len(v) > 1]
    if k["benzer_cekim"] == "yasak":
        h += [f"benzer çekim: {', '.join(v)} (aynı ölçek, hareket, yükseklik, açı, diziliş, odak ve arazi)" for v in tekrarlar]
    h += [f"aynı render kamerası: {', '.join(g)} (farklı kimlik, birebir aynı kamera yapılandırması — çeşitlilik sayılmaz)"
          for g in kamera_tekrari]
    rapor = {"cekim_sayisi": len(ks), "dagilim": {a: dict(v) for a, v in say.items()}, "sira": ks, "benzer_gruplar": tekrarlar}
    if kamerasiz:
        rapor["kamerasiz_3d"] = kamerasiz
    if kamera_tekrari:
        rapor["kamera_tekrari"] = kamera_tekrari
    return h, rapor
