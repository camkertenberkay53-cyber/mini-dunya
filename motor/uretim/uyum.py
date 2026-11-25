"""Sahne–anlatım uyumu: her cümlenin görsel niyeti, ona bağlı çekimlerde gerçekten karşılanıyor mu?

Denetlenen (ölçülen) şeyler: istenen roller kadrajda görünüyor mu; istenen nesne (sancak, standart) ve tepesi kadrajda mı;
odak karakterin animasyonu istenen eyleme ait mi; ölçülen kamera mesafesi istenenle aynı mı; ortam (arazi, ışık,
çevre varlıkları) istenen mi; ekran yazısı taşınmış mı. Görselin estetik uyumu bu denetimin konusu değildir."""
from __future__ import annotations

from motor.uretim import kadraj, secici, veri


def nesne_tepesi(ad: str, nesne: str) -> float | None:
    for e in veri.takimlar()[ad]["takilanlar"]:
        if e["id"] == nesne or veri.ekipman_turu(e["id"]) == nesne:
            return max(veri.kural("mesafe")["karakter_boyu_m"], veri.glb_yuksekligi(str(veri.ekipman_glb(e["id"]))))
    return None


def denetle(senaryo: dict, plan: dict, denetim: dict) -> tuple[list[str], list[dict]]:
    en_boy = plan["cozunurluk"][0] / plan["cozunurluk"][1]
    cekimler = {}
    for c in plan["cekimler"]:
        for s in c["cumleler"]:
            cekimler.setdefault(s, []).append(c)
    h, satirlar = [], []
    for s in senaryo["cumleler"]:
        n = s["niyet"]
        cs = cekimler.get(s["id"], [])
        kontrol = []
        def ekle(ad, ok, ayrinti=""):
            kontrol.append({"kontrol": ad, "gecti": ok, "ayrinti": ayrinti})
            if not ok:
                h.append(f"{s['id']}: {ad} — {ayrinti}")
        ekle("çekim var", bool(cs), f"{len(cs)} çekim")
        for c in cs:
            ekle(f"{c['id']} görsel türü", c["tur"] == n["tur"], f"istenen {n['tur']}, planlanan {c['tur']}")
            if n.get("metin_katmani"):
                ekle(f"{c['id']} ekran yazısı", c.get("metin_katmani") == n["metin_katmani"], n["metin_katmani"])
            if c["tur"] != "3d":
                continue
            olc = denetim["cekimler"].get(c["id"], {}).get("olcum", {})
            kad = olc.get("karakter", {})
            gorunen = [c["karakterler"][int(i)] for i, x in kad.items() if x["gorunur"]]
            for r in n.get("roller", []):
                var = [k for k in gorunen if k.get("rol") == r["rol"]]
                ekle(f"{c['id']} '{r['rol']}' görünüyor", bool(var), f"{len(var)} görünür")
                if r.get("nesne"):
                    tasiyan = [k for k in gorunen if nesne_tepesi(k["takim"], r["nesne"]) is not None]
                    if not tasiyan:
                        ekle(f"{c['id']} '{r['nesne']}' görünüyor", False, "taşıyan karakter kadrajda değil")
                    else:
                        k = tasiyan[0]
                        oran = kadraj.nokta_gorunurlugu(c, k, nesne_tepesi(k["takim"], r["nesne"]), en_boy)
                        ekle(f"{c['id']} '{r['nesne']}' tepesi kadrajda", oran >= 0.8, f"anların %{oran * 100:.0f}'inde (tepe yüksekliği yaklaşık)")
            if n.get("eylem"):
                oi = c.get("meta", {}).get("odak_indeks", 0)
                anim = c["karakterler"][oi]["animasyon"] if c.get("karakterler") else None
                # eylem ya da (odak karakter istenen eylemi yapamıyorsa) kurallardaki yedek eylemi (Faz 5.5)
                kabul = {n["eylem"]} | set(veri.kural("animasyon").get("eylem_yedekleri", {}).get(n["eylem"], []))
                tutan = next((e for e in [n["eylem"], *sorted(kabul - {n["eylem"]})] if anim in secici.eylem_animasyonlari(e)), None)
                ekle(f"{c['id']} eylem '{n['eylem']}'", tutan is not None,
                     f"odak animasyonu {anim}" + (f" (yedek eylem '{tutan}')" if tutan and tutan != n["eylem"] else ""))
            if n.get("mesafe"):
                olculen = olc.get("kamera_plani_olculen")
                ekle(f"{c['id']} mesafe '{n['mesafe']}'", olculen == n["mesafe"], f"ölçülen {olculen}")
            o = n.get("ortam") or {}
            for alan in ("arazi", "isik"):
                if o.get(alan):
                    ekle(f"{c['id']} {alan}", c["ortam"][alan] == o[alan], f"istenen {o[alan]}, planlanan {c['ortam'][alan]}")
            for pid in o.get("cevre", []):
                ekle(f"{c['id']} çevre '{pid}'", any(x["id"] == pid for x in c["ortam"].get("cevre", [])), "")
        satirlar.append({"cumle": s["id"], "metin": s["metin"], "cekimler": [c["id"] for c in cs], "kontroller": kontrol,
                         "gecti": all(x["gecti"] for x in kontrol)})
    return h, satirlar
