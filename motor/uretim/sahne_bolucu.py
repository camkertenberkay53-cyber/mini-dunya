"""M5 — Sahne bölücü: senaryo cümlelerini ÖLÇÜLEN seslendirme sürelerine göre zaman çizelgesine ve çekimlere böler.

Her cümle en az bir çekimle gösterilir; uzun cümle (kurallar/shorts.yaml cekim.en_cok_sure_sn) yalnızca ikinci çekim
gerçekten farklı bir görüntü olacaksa (Faz-64) iki çekime bölünür.
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


# Faz-64: 2.5D ikinci çekimde ilk çekimden FARKLI gerçek kamera hareketi (kaos/sinema/kamera.HAREKETLER adları)
G25_HAREKET_SIRASI = ("zoom_in", "pan_sag", "pull_back", "pan_sol", "push_in", "zoom_out", "capraz", "pan_yukari")


def _kokler(metin: str) -> set[str]:
    """İçerik kelimesi kökleri (≥5 harf → ilk 5 harf): Türkçe eklerden bağımsız kaba eşleşme ('Hasan'ın' ~ 'Hasan')."""
    import re
    return {w[:5] for w in re.findall(r"\w+", (metin or "").replace("I", "ı").replace("İ", "i").lower()) if len(w) >= 5}


def ilgili_gorsel(havuz: list[dict], cumle: dict, kullanilan: set[str]) -> dict | None:
    """Faz-64: cümlenin ikinci çekimi için havuzdan kullanılmamış ve İLGİLİ ilk görsel (havuz sırası; belirlenimci).
    İlgi: ilk görselle aynı 'sahne' etiketi ya da cümle metniyle ortak içerik kelimesi kökü. Yoksa None (bölünmez)."""
    ilk = (cumle["niyet"].get("gorsel25d") or {}).get("gorsel_id")
    ilk_sahne = next((g.get("sahne") for g in havuz if g.get("gorsel_id") == ilk), None)
    kok = _kokler(cumle.get("metin", ""))
    for g in havuz:
        if g.get("gorsel_id") in kullanilan or not g.get("aciklama"):
            continue
        if (ilk_sahne and g.get("sahne") == ilk_sahne) or kok & _kokler(g["aciklama"]):
            return g
    return None


def cekimlere_bol(senaryo: dict, cizelge: list[dict], havuz: list[dict] | None = None) -> list[dict]:
    """Faz-64: uzun cümle yalnızca ikinci çekim GERÇEKTEN farklı bir görüntü olacaksa bölünür:
    3D → iki çekim (planlayıcı kamera türünü geçmişe göre değiştirir); harita → bölünmez (aynı evre iki kez aynı
    kareleri üretir); 2.5D → havuzda kullanılmamış ilgili bir görsel varsa ikinci çekim o görselle ve farklı kamera
    hareketiyle, yoksa tek çekim. Kısa cümleler ve 3D için davranış Faz 5.x ile aynı."""
    if senaryo.get("format") == "uzun":
        return _uzun_bol(senaryo, cizelge)
    k = veri.kural("shorts")["cekim"]
    niyet = {c["id"]: c for c in senaryo["cumleler"]}
    kullanilan = {(c["niyet"].get("gorsel25d") or {}).get("gorsel_id") for c in senaryo["cumleler"]
                  if c["niyet"].get("tur") == "gorsel25d"}
    cekimler = []
    for z in cizelge:
        sure = z["goruntu_son_sn"] - z["goruntu_bas_sn"]
        c = niyet[z["cumle"]]
        uzun = sure > k["en_cok_sure_sn"] and sure / 2 >= k["en_az_sure_sn"]
        tur = c["niyet"].get("tur")
        niyetler = [c["niyet"]]
        if uzun and tur == "3d":
            niyetler = [c["niyet"], c["niyet"]]
        elif uzun and tur == "gorsel25d" and havuz:
            alt = ilgili_gorsel(havuz, c, kullanilan)
            if alt:
                kullanilan.add(alt["gorsel_id"])
                ilk_h = (c["niyet"].get("gorsel25d") or {}).get("hareket", "zoom_in")
                ilk_h = ilk_h if isinstance(ilk_h, str) else None
                h2 = next(h for h in G25_HAREKET_SIRASI if h != ilk_h)
                niyetler = [c["niyet"], {"tur": "gorsel25d", "gorsel25d": {"gorsel_id": alt["gorsel_id"], "hareket": h2},
                                         "aciklama": alt["aciklama"]}]
        parca = len(niyetler)
        for j, n in enumerate(niyetler):
            cekimler.append({"id": f"{z['cumle']}{'' if parca == 1 else 'abc'[j]}", "cumle": z["cumle"],
                             "parca": j, "parca_sayisi": parca, "sure_sn": round(sure / parca, 3),
                             "bas_sn": round(z["goruntu_bas_sn"] + j * sure / parca, 3), "niyet": n, "amac": c.get("amac")})
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
