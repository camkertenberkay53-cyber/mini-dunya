"""Varlık kalite sınıflandırması: A (yakın çekim) / B (orta mesafe) / C (uzak, arka plan) / RED (kullanılamaz).

python3 -m motor.karakter.kalite   -> motor/karakter/kalite.json

Sınıf yalnızca poligon ya da dosya boyutuna bakmaz. Bir karakterin sınıfı, şunların EN DÜŞÜĞÜDÜR:
- dönem uygunluğu (kural ihlali = RED)
- montaj ve animasyon testi (kalan = RED)
- gövde oranı ve iskelet (Faz 2 denetimi; stilize/chibi = RED)
- model bütünlüğü ve dosya boyutu (bozuk ya da bütçe aşımı = RED)
- lisans kaydı (eksik = RED)
- siluet: başka döneme karışabiliyorsa en fazla C
- tarihsel güven: belirsiz parça taşıyan karakter yakın çekime (A) çıkamaz
- geometri ve doku ayrıntısı (ekipman üçgen sayısı, doku çözünürlüğü)
- görsel inceleme kaydı (gorsel_inceleme.yaml)
Motor bir karakteri yalnızca sınıfının izin verdiği mesafede kullanır: A yakın+orta+uzak, B orta+uzak, C uzak.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from motor import ayar
from motor.karakter import siluet
from motor.varlik import ekipman as ekipman_mod

BURASI = Path(__file__).resolve().parent
SIRA = {"RED": 0, "C": 1, "B": 2, "A": 3}
KULLANIM = {"A": ["yakin", "orta", "uzak"], "B": ["orta", "uzak"], "C": ["uzak"], "RED": []}
IZINLI_LISANS = {"CC0-1.0", "kendi-uretim"}
GOVDE_MAKS_BAYT = 6_000_000
EKIPMAN_MAKS_BAYT = 400_000
# kategori -> (en kısa, en uzun) boyut (m): ekipmanın gerçekçi ölçüde olup olmadığı
OLCU = {"baslik": (0.15, 0.80), "kalkan": (0.30, 1.30), "silah": (0.25, 3.60), "sancak": (1.5, 4.5), "sirt": (0.3, 1.0),
        "aksesuar": (0.05, 0.6), "cevre": (1.5, 25.0)}


def _min(*s):
    return min(s, key=lambda x: SIRA[x])


def ekipman_sinifi(pid: str, k: dict, inceleme: dict) -> dict:
    o = k["olcum"]
    neden = []
    sinif = "A"
    if o.get("bozuk_yuz", 0) or o.get("yalniz_kose", 0):
        sinif, _ = "RED", neden.append("geometri hatası")
    if o["bayt"] > EKIPMAN_MAKS_BAYT:
        sinif, _ = "RED", neden.append(f"dosya {o['bayt'] // 1024} KB > {EKIPMAN_MAKS_BAYT // 1024} KB")
    lo, hi = OLCU.get(k["kategori"], (0.01, 30))
    en_uzun = max(o["boyut_m"])
    if not lo <= en_uzun <= hi:
        sinif, _ = "RED", neden.append(f"ölçü {en_uzun:.2f} m ({k['kategori']} için {lo}-{hi})")
    if k.get("lisans") not in IZINLI_LISANS:
        sinif, _ = "RED", neden.append("lisans kaydı yok")
    if sinif != "RED":
        if o["ucgen"] < 150:
            sinif, _ = _min(sinif, "C"), neden.append(f"{o['ucgen']} üçgen: yalnızca uzak plan")
        elif o["ucgen"] < 600:
            sinif, _ = _min(sinif, "B"), neden.append(f"{o['ucgen']} üçgen: yakın çekim için az")
        if max(o.get("doku") or [0]) < 512:
            sinif, _ = _min(sinif, "B"), neden.append("doku < 512 px")
        if k["tarih"]["guven"] == "belirsiz":
            sinif, _ = _min(sinif, "B"), neden.append("tarihsel güven belirsiz: yakın çekimde öne çıkarılmaz")
        ev = inceleme["ekipman"]["varsayilan"] | (inceleme["ekipman"].get("istisna", {}).get(pid) or {})
        if ev.get("yakin") != "uygun":
            sinif = _min(sinif, "B")
        if ev.get("orta") != "uygun":
            sinif, _ = _min(sinif, "C"), neden.append("görsel inceleme: " + ev.get("not", "orta planda uygun değil"))
    return {"sinif": sinif, "kullanim": KULLANIM[sinif], "neden": neden, "guven": k["tarih"]["guven"], "kategori": k["kategori"]}


def siniflandir() -> dict:
    oz = json.loads((BURASI / "derlenmis3.json").read_text())
    montaj = json.loads((BURASI / "montaj_testi.json").read_text())["takimlar"]
    kat = ekipman_mod.katalog()
    ekip = json.loads(ekipman_mod.KAYIT.read_text())
    inceleme = yaml.safe_load((BURASI / "gorsel_inceleme.yaml").read_text(encoding="utf-8"))
    sil = siluet.analiz(oz["takimlar"])
    karisan = {s.split(" ")[0] for s in sil["karisabilir"]}
    e_sinif = {pid: ekipman_sinifi(pid, k, inceleme) for pid, k in ekip.items()}
    k_sinif = {}
    for ad, t in oz["takimlar"].items():
        g = oz["govdeler"][t["govde_id"]]
        neden, sinif = [], "A"
        if ad in oz["reddedilen"]:
            sinif, _ = "RED", neden.append("dönem kuralı")
        m = montaj.get(ad)
        if m is None or not m["gecti"]:
            sinif, _ = "RED", neden.extend(m["hatalar"] if m else ["montaj testi yapılmadı"])
        o = g["olcum"]
        if o["evrensel_iskelet_eslesen"] < 65 or (o["bas_orani"] or 1) > 0.22 or not 1.5 <= o["boy_m"] <= 2.05:
            sinif, _ = "RED", neden.append("gövde oranı/iskelet")
        if g["bayt"] > GOVDE_MAKS_BAYT:
            sinif, _ = "RED", neden.append(f"gövde dosyası {g['bayt'] / 1e6:.1f} MB")
        if not set(g["lisanslar"]) <= IZINLI_LISANS:
            sinif, _ = "RED", neden.append("lisans")
        if sinif != "RED":
            parca_siniflari = [e_sinif[p]["sinif"] for p in t["takilanlar"].values()]
            gorunur = [e_sinif[p]["sinif"] for p in t["takilanlar"].values() if kat["parcalar"][p]["kategori"] in ("baslik", "kalkan", "silah", "sancak")]
            if gorunur:
                sinif = _min(sinif, min(gorunur, key=lambda x: SIRA[x]))
                if SIRA[min(gorunur, key=lambda x: SIRA[x])] < SIRA["A"]:
                    neden.append("öndeki ekipman yakın çekim sınıfında değil")
            guvenler = [kat["giysiler"][x]["tarih"]["guven"] for x in t["giysiler"]] + [kat["parcalar"][p]["tarih"]["guven"] for p in t["takilanlar"].values()]
            if "belirsiz" in guvenler:
                sinif, _ = _min(sinif, "B"), neden.append("belirsiz tarihsel parça taşıyor")
            if o["ucgen"] < 15000:
                sinif = _min(sinif, "B")
            if m and m["uyarilar"]:
                sinif, _ = _min(sinif, "B"), neden.append("silah bazı karelerde gövdeden geçiyor")
            if ad in karisan:
                sinif, _ = _min(sinif, "C"), neden.append("siluet başka döneme karışabilir")
            ki = inceleme["varsayilan"] | (inceleme.get("karakterler", {}).get(ad) or {})
            if ki.get("yakin") != "uygun":
                sinif = _min(sinif, "B")
            if ki.get("orta") != "uygun":
                sinif, _ = _min(sinif, "C"), neden.append("görsel inceleme: orta planda uygun değil")
            del parca_siniflari
        k_sinif[ad] = {"sinif": sinif, "kullanim": KULLANIM[sinif], "kit": t["kit"], "rol": t["rol"], "neden": sorted(set(neden)),
                       "yasak_animasyon": sorted((m or {}).get("yasak_animasyon", {}).keys())}
    dagilim = lambda d: {s: sum(1 for x in d.values() if x["sinif"] == s) for s in ("A", "B", "C", "RED")}
    return {"karakter": k_sinif, "ekipman": e_sinif, "karakter_dagilimi": dagilim(k_sinif), "ekipman_dagilimi": dagilim(e_sinif),
            "siluet": sil, "inceleme": inceleme["inceleyen"]}


def kullanilabilir_mi(sinif_kaydi: dict, mesafe: str) -> bool:
    """Motorun sahne derleyicisi bunu çağırır: bu karakter bu kamera mesafesinde kullanılabilir mi?"""
    return mesafe in sinif_kaydi["kullanim"]


if __name__ == "__main__":
    r = siniflandir()
    (BURASI / "kalite.json").write_text(json.dumps(r, ensure_ascii=False, indent=1))
    print("karakter:", r["karakter_dagilimi"], "ekipman:", r["ekipman_dagilimi"])
    print("ayrışmayan:", r["siluet"]["ayrismayan"])
    print("karışabilir:", r["siluet"]["karisabilir"])
    print("uzaktan tanıma:", r["siluet"]["uzak_tanima_orani"])
