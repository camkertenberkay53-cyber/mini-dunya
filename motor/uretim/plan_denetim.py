"""Çekim planı denetimi: M6 (karakter/dönem), M7 (ortam), M8 (animasyon) ve kamera mesafesi kuralları.
Render katmanı yalnızca bu denetimden HATASIZ geçen planı çeker.

python3 -m motor.uretim.plan_denetim <cekim_plani.json>   -> denetim raporu (stdout, JSON); hata varsa çıkış 1
"""
from __future__ import annotations

import json
import math
import sys

from motor.uretim import animasyon_izni, kadraj, kamera_denetim, ortam_secici, secici, sozlesme, veri

EN_AZ_ARALIK_M = 0.6      # iki karakterin ayak noktaları arası en az uzaklık (iç içe geçmesinler)
MESAFE_SIRA = {"uzak": 0, "orta": 1, "yakin": 2}


def _cevre_mesafesi(cekim: dict, cevre: dict, en_boy: float) -> tuple[str | None, float]:
    """Çevre varlığını kendi yüksekliğiyle kadraj ölçümünden geçirir."""
    boy = veri.glb_yuksekligi(str(veri.ekipman_glb(cevre["id"]))) * cevre.get("olcek", 1.0)
    sahte = {"karakterler": [{"takim": cevre["id"], "konum": cevre["konum"], "yon_derece": 0}],
             "kamera": cekim["kamera"], "sure_sn": cekim["sure_sn"]}
    r = kadraj.olc(sahte, en_boy, boy)[0]
    return r["mesafe"], r["ekran_orani"]


def cekim_denetle(c: dict, donem: str, en_boy: float) -> dict:
    h, u, olcum = [], [], {}
    if c["tur"] != "3d":
        if not c.get("metin"):
            h.append(f"{c['id']}: {c['tur']} çekiminin metni yok")
        return {"hatalar": h, "uyarilar": u, "olcum": olcum}
    for alan in ("ortam", "kamera"):
        if alan not in c:
            h.append(f"{c['id']}: 3D çekimde '{alan}' yok")
    if h:
        return {"hatalar": h, "uyarilar": u, "olcum": olcum}
    o = c["ortam"]
    if not ortam_secici.arazi_var_mi(o["arazi"]):
        h.append(f"{c['id']}: '{o['arazi']}' arazi hazır ayarı yok")
    if not ortam_secici.isik_var_mi(o["isik"]):
        h.append(f"{c['id']}: '{o['isik']}' ışık hazır ayarı yok")
    # kamera mesafesi (ölçülen) ve karakter kuralları
    kad = kadraj.olc(c, en_boy)
    olcum["karakter"] = kad
    olculen_en_yakin = None
    for i, k in enumerate(c.get("karakterler", [])):
        ad = k["takim"]
        if ad not in veri.takimlar():
            h.append(f"{c['id']}: '{ad}' derlenmiş karakter değil")
            continue
        m = kad[i]
        mesafe = m["mesafe"] or "uzak"
        if m["gorunur"] and (olculen_en_yakin is None or MESAFE_SIRA[mesafe] > MESAFE_SIRA[olculen_en_yakin]):
            olculen_en_yakin = mesafe
        ok, n = secici.karakter_uygun_mu(ad, donem, mesafe)
        h += [f"{c['id']}: {x}" + ("" if m["gorunur"] else " (kadraj dışı)") for x in n]
        ok, n = animasyon_izni.izinli(ad, k["animasyon"], {"binek": False, "nesneler": []}, k.get("hiz_m_sn"), k.get("olcek", 1.0))
        h += [f"{c['id']}: {x}" for x in n]
        for e in veri.takimlar()[ad]["takilanlar"]:
            g = (veri.parca(e["id"]) or {}).get("tarih", {}).get("guven")
            if g in ortam_secici.TEMSILI_GEREKEN and m["gorunur"]:
                u.append(f"{c['id']}: {ad} '{e['id']}' taşıyor (tarih güveni {g}): görüntüde temsilî; anlatıda kesin bilgi gibi sunulamaz")
    # karakterler iç içe mi (başta ve sonda)
    ks = c.get("karakterler", [])
    for zaman in (0.0, c["sure_sn"]):
        for i in range(len(ks)):
            for j in range(i + 1, len(ks)):
                a, b = kadraj.karakter_konumu(ks[i], zaman), kadraj.karakter_konumu(ks[j], zaman)
                if math.dist(a, b) < EN_AZ_ARALIK_M:
                    h.append(f"{c['id']}: {ks[i]['takim']}#{i} ile {ks[j]['takim']}#{j} {zaman:.1f}. sn'de iç içe ({math.dist(a, b):.2f} m)")
    for i, cv in enumerate(o.get("cevre", [])):
        if veri.parca(cv["id"]) is not None and veri.ekipman_glb(cv["id"]).exists():
            yaricap = veri.glb_yayilimi(str(veri.ekipman_glb(cv["id"]))) * cv.get("olcek", 1.0)
            for j, k in enumerate(ks):
                for zaman in (0.0, c["sure_sn"] / 2, c["sure_sn"]):
                    p = kadraj.karakter_konumu(k, zaman)
                    if math.dist((p[0], p[2]), cv["konum"]) < yaricap + 0.3:
                        h.append(f"{c['id']}: {k['takim']}#{j} {zaman:.1f}. sn'de {cv['id']} çevre varlığıyla çakışıyor")
                        break
        mes, oran = _cevre_mesafesi(c, cv, en_boy)
        olcum.setdefault("cevre", {})[f"{i}:{cv['id']}"] = {"mesafe": mes, "ekran_orani": oran}
        ok, n = ortam_secici.cevre_uygun_mu(cv["id"], donem, mes or "uzak", cv.get("temsili", False))
        h += [f"{c['id']}: {x}" for x in n]
    plan = c["kamera"]["plan"]
    if olculen_en_yakin and plan != olculen_en_yakin:
        h.append(f"{c['id']}: kamera planı '{plan}' yazılmış ama ölçülen en yakın karakter '{olculen_en_yakin}' planda")
    if olculen_en_yakin == "yakin":
        h.append(f"{c['id']}: yakın plan kullanılamaz (A sınıfı karakter yok; yönetim kararı)")
    if not any(m["gorunur"] for m in kad.values()) and c.get("karakterler"):
        u.append(f"{c['id']}: hiçbir karakter kadrajda değil")
    for i, m in kad.items():
        if not m["gorunur"]:
            u.append(f"{c['id']}: {m['takim']}#{i} çekim boyunca hiç görünmüyor (render maliyeti var, katkısı yok)")
    # Faz 5.3 kamera QC: planlayıcının kurduğu çekimlerde (odak kaydı olan) kalan kadraj/çarpışma kusuru hatadır
    odak_i = c.get("meta", {}).get("odak_indeks")
    if odak_i is not None and c.get("karakterler"):
        kusur = kamera_denetim.denetle(c, odak_i, en_boy)
        olcum["kamera_kusur"] = kusur
        h += [f"{c['id']}: kamera kusuru: {x}" for x in kusur]
    olcum["kamera_plani_olculen"] = olculen_en_yakin
    return {"hatalar": h, "uyarilar": u, "olcum": olcum}


def imza(c: dict) -> str:
    """Tekrar eden çekim tespiti: aynı karakter dizilişi + aynı kamera = aynı çekim."""
    k = sorted((x["takim"], tuple(x["konum"]), x["animasyon"]) for x in c.get("karakterler", []))
    return json.dumps([c["tur"], c.get("ortam"), k, c.get("kamera"), c.get("metin")], sort_keys=True, ensure_ascii=False)


def denetle(plan: dict) -> dict:
    h = sozlesme.sema_hatalari("cekim_plani", plan)
    if h:
        return {"gecti": False, "hatalar": h, "uyarilar": [], "cekimler": {}, "eksikler": plan.get("eksikler", [])}
    gecerli = {x["etiket"] for x in veri.kitler().values()}
    if plan["donem"] not in gecerli:
        h.append(f"plan: '{plan['donem']}' dönemi için kit yok")
    en_boy = plan["cozunurluk"][0] / plan["cozunurluk"][1]
    u, cekimler = [], {}
    h += sozlesme._tekrar([c["id"] for c in plan["cekimler"]], "çekimler")
    gorulen = {}
    for c in plan["cekimler"]:
        r = cekim_denetle(c, plan["donem"], en_boy)
        cekimler[c["id"]] = r
        h += r["hatalar"]
        u += r["uyarilar"]
        s = imza(c)
        if s in gorulen:
            h.append(f"{c['id']}: {gorulen[s]} ile aynı çekim (tekrar)")
        gorulen.setdefault(s, c["id"])
    return {"gecti": not h, "hatalar": h, "uyarilar": u, "cekimler": cekimler, "eksikler": plan["eksikler"]}


if __name__ == "__main__":
    r = denetle(json.loads(open(sys.argv[1]).read()))
    print(json.dumps(r, ensure_ascii=False, indent=1))
    sys.exit(0 if r["gecti"] else 1)
