"""M5 — Sahne bölücü: senaryo cümlelerini ÖLÇÜLEN seslendirme sürelerine göre zaman çizelgesine ve çekimlere böler.

Her cümle en az bir çekimle gösterilir; uzun cümle (kurallar/shorts.yaml cekim.en_cok_sure_sn) iki çekime bölünür.
Çekim süresi = cümlenin seslendirme süresi + ardından gelen duraklama.
Faz-62c: senaryo biçimi 'uzun' ise kurallar/uzun.yaml (bölüm arası duraklama, uzun cümle → eşit parçalar) kullanılır;
Shorts yolu değişmez."""
from __future__ import annotations

from motor.uretim import veri


def zaman_cizelgesi(senaryo: dict, sureler: dict) -> list[dict]:
    if senaryo.get("format") == "uzun":
        return _uzun_cizelge(senaryo, sureler)
    d = veri.kural("shorts")["duraklama_sn"]
    cs = senaryo["cumleler"]
    t = d["baslangic"]
    satirlar = []
    for i, c in enumerate(cs):
        s = sureler[c["id"]]["sure_sn"]
        if c.get("amac") == "kanca":
            ara = d["kanca_sonrasi"]
        elif i == len(cs) - 1:
            ara = d["kapanis"]
        elif cs[i + 1].get("amac") == "final":
            ara = d["final_oncesi"]
        else:
            ara = d["cumle_arasi"]
        bas = 0.0 if i == 0 else t
        ses_bas = t
        t += s + ara
        satirlar.append({"cumle": c["id"], "ses_bas_sn": round(ses_bas, 3), "ses_sure_sn": s,
                         "goruntu_bas_sn": round(bas, 3), "goruntu_son_sn": round(t, 3)})
    return satirlar


def cekimlere_bol(senaryo: dict, cizelge: list[dict]) -> list[dict]:
    if senaryo.get("format") == "uzun":
        return _uzun_bol(senaryo, cizelge)
    k = veri.kural("shorts")["cekim"]
    niyet = {c["id"]: c for c in senaryo["cumleler"]}
    cekimler = []
    for z in cizelge:
        sure = z["goruntu_son_sn"] - z["goruntu_bas_sn"]
        parca = 2 if sure > k["en_cok_sure_sn"] and sure / 2 >= k["en_az_sure_sn"] else 1
        for j in range(parca):
            c = niyet[z["cumle"]]
            cekimler.append({"id": f"{z['cumle']}{'' if parca == 1 else 'abc'[j]}", "cumle": z["cumle"],
                             "parca": j, "parca_sayisi": parca, "sure_sn": round(sure / parca, 3),
                             "bas_sn": round(z["goruntu_bas_sn"] + j * sure / parca, 3), "niyet": c["niyet"], "amac": c.get("amac")})
    return cekimler


def toplam_sure(cizelge: list[dict]) -> float:
    return round(cizelge[-1]["goruntu_son_sn"], 2) if cizelge else 0.0


def _uzun_cizelge(senaryo: dict, sureler: dict) -> list[dict]:
    d = veri.kural("uzun")["duraklama_sn"]
    cs = senaryo["cumleler"]
    t = d["baslangic"]
    satirlar = []
    for i, c in enumerate(cs):
        s = sureler[c["id"]]["sure_sn"]
        if i == len(cs) - 1:
            ara = d["kapanis"]
        elif i == 0:
            ara = d["kanca_sonrasi"]
        elif cs[i + 1].get("bolum") != c.get("bolum"):
            ara = d["bolum_arasi"]
        else:
            ara = d["cumle_arasi"]
        bas = 0.0 if i == 0 else t
        ses_bas = t
        t += s + ara
        satirlar.append({"cumle": c["id"], "ses_bas_sn": round(ses_bas, 3), "ses_sure_sn": s,
                         "goruntu_bas_sn": round(bas, 3), "goruntu_son_sn": round(t, 3)})
    return satirlar


def _uzun_bol(senaryo: dict, cizelge: list[dict]) -> list[dict]:
    import math
    k = veri.kural("uzun")["cekim"]
    niyet = {c["id"]: c for c in senaryo["cumleler"]}
    cekimler = []
    for z in cizelge:
        sure = z["goruntu_son_sn"] - z["goruntu_bas_sn"]
        c = niyet[z["cumle"]]
        # yalnızca 3D cümle bölünür (kamera çeşitliliği); harita / 2.5D tek, kesintisiz kamera hareketi olarak kalır
        parca = 1 if c["niyet"]["tur"] != "3d" else \
            max(1, min(math.ceil(sure / k["en_cok_sure_sn"]), int(sure // k["en_az_sure_sn"]) or 1, 26))
        for j in range(parca):
            cekimler.append({"id": f"{z['cumle']}{'' if parca == 1 else 'abcdefghijklmnopqrstuvwxyz'[j]}", "cumle": z["cumle"],
                             "parca": j, "parca_sayisi": parca, "sure_sn": round(sure / parca, 3),
                             "bas_sn": round(z["goruntu_bas_sn"] + j * sure / parca, 3), "niyet": c["niyet"], "amac": c.get("amac")})
    return cekimler
