"""M6 + M9 — Çekim planlayıcı: bir görsel niyeti (rol, eylem, mesafe, ortam) çekilebilir bir 3D çekime çevirir.

1. Oyuncu seçimi: her rol için secici.sec (dönem, kalite/mesafe, animasyon izni, nesne). Tek bir nesneyi (sancak)
   taşıyan karakterler, o nesne açıkça istenmedikçe kalabalığa katılmaz (bir birlikte iki ana sancak olmasın).
2. Diziliş: kurallar/dizilis.yaml (kol, sıra, dağınık, tek). Odak karakter önde.
3. Kamera: kurallar/kamera.yaml kataloğundan, önceki çekimlerle çeşitlilik kurallarına uyan tür seçilir; uzaklık
   hedef ekran oranından hesaplanır, kadraj ÖLÇÜMÜYLE doğrulanıp düzeltilir.
4. Çevre varlıkları: istenen dönem varlıkları kameranın baktığı yönde, sahnenin arkasına yerleştirilir.

Hiçbir şey uydurulmaz: rol, eylem ya da nesne için uygun karakter yoksa çekim "eksik" kaydıyla döner.
"""
from __future__ import annotations

import json
import math

import numpy as np

from motor.uretim import animasyon_izni, kadraj, secici, veri

ALTIN = 0.6180339887


def _sancakli(ad: str) -> bool:
    return any(e["kategori"] == "sancak" for e in veri.takimlar()[ad]["takilanlar"])


def oyuncu_sec(niyet: dict, donem: str) -> tuple[list[dict], list[str]]:
    """Dönüş: ([{takim, animasyon, rol, odak}], eksikler)"""
    eylem = niyet.get("eylem")
    mesafe = niyet.get("mesafe", "orta")
    secilen, eksik, kullanilan = [], [], set()
    for r in niyet.get("roller", []):
        s = secici.sec(r["rol"], donem, mesafe, eylem, r.get("nesne"), {"binek": False, "nesneler": []})
        uygun = [(a, an) for a, an in s["uygun"] if r.get("nesne") or not _sancakli(a)]
        if not uygun:
            eksik.append(s["eksik"] or f"{donem}: '{r['rol']}' rolü için sancaksız uygun karakter yok")
            continue
        adet = r.get("adet", 1)
        # aynı karakterin yan yana tekrarını azaltmak için uygun listede sırayla dolaş; odak/nesne istenen ilk uygunu alır
        tazeler = [x for x in uygun if x[0] not in kullanilan] or uygun
        for i in range(adet):
            ad, an = tazeler[i % len(tazeler)]
            secilen.append({"takim": ad, "animasyon": an, "rol": r["rol"], "odak": bool(r.get("odak")) and i == 0})
            kullanilan.add(ad)
    if secilen and not any(x["odak"] for x in secilen):
        secilen[0]["odak"] = True
    return secilen, eksik


def dizilis_kur(oyuncular: list[dict], eylem: str | None, tohum: int, dizilis: str | None = None,
                sure: float | None = None) -> tuple[list[dict], str, int]:
    """Konumları ve yönleri atar. Odak (0, odak_onde) konumunda; +Z'ye bakar. Dönüş: (karakterler, diziliş, odak indeksi)."""
    k = veri.kural("dizilis")
    ad = dizilis or (k["eylem_dizilisi"].get(eylem, "kol") if len(oyuncular) > 1 else "tek")
    d = k["dizilisler"][ad]
    odak = [o for o in oyuncular if o["odak"]]
    digerleri = [o for o in oyuncular if not o["odak"]]
    rng = np.random.default_rng(tohum)
    yer = []
    if ad == "tek":
        yer = [(odak[0] if odak else oyuncular[0], (0.0, 0.0), 0.0)]
    elif ad == "kol":
        yer.append((odak[0], (0.0, d["odak_onde"]), 0.0)) if odak else None
        for i, o in enumerate(digerleri):
            sira, yan = divmod(i, d["yan"])
            yer.append((o, ((yan - (d["yan"] - 1) / 2) * d["yan_aralik"], -sira * d["sira_aralik"]), 0.0))
    elif ad == "sira":
        yer.append((odak[0], (0.0, d["odak_onde"]), 0.0)) if odak else None
        for i, o in enumerate(digerleri):
            sira, yan = divmod(i, d["en_cok_yan"])
            n = min(d["en_cok_yan"], len(digerleri) - sira * d["en_cok_yan"])
            yer.append((o, ((yan - (n - 1) / 2) * d["yan_aralik"], -sira * d["sira_aralik"]), 0.0))
    elif ad == "dagin":
        noktalar = []
        for o in oyuncular:
            for _ in range(200):
                p = rng.uniform(-d["yaricap"], d["yaricap"], 2)
                if all(math.dist(p, q) >= d["en_az_aralik"] for q in noktalar):
                    break
            noktalar.append(p)
            yer.append((o, (float(p[0]), float(p[1])), float(rng.uniform(-40, 40))))
    yayilim = k["faz_yayilimi_sn"]
    cs = k["cesitlilik"]
    odak_i = next((i for i, (o, _, _) in enumerate(yer) if o["odak"]), 0)
    sonuc = []
    for i, (o, (x, z), yon) in enumerate(yer):
        kural = veri.kural("animasyon")["animasyonlar"][o["animasyon"]]
        r = np.random.default_rng(tohum * 1000 + i)
        olcek = 1.0 if i == odak_i else float(r.uniform(*cs["olcek"]))
        if i != odak_i and ad != "dagin":
            x += float(r.uniform(-1, 1)) * cs["konum_sapmasi_m"]
            z += float(r.uniform(-1, 1)) * cs["konum_sapmasi_m"]
            if kural["tur"] != "yer_degistiren":
                yon += float(r.uniform(-1, 1)) * cs["yon_sapmasi_derece"]
        hiz = animasyon_izni.zemin_hizi(o["animasyon"]) * olcek if kural["tur"] == "yer_degistiren" else 0.0
        faz = 0.0 if kural["tur"] == "tek_sefer" else round((i * ALTIN) % 1.0 * yayilim, 3)
        c = {"takim": o["takim"], "rol": o["rol"], "konum": [round(x, 2), round(z, 2)], "yon_derece": round(yon, 1),
             "animasyon": o["animasyon"], "faz_sn": faz, "hiz_m_sn": round(hiz, 4)}
        if olcek != 1.0:
            c["olcek"] = round(olcek, 3)
        if kural["tur"] == "tek_sefer" and ad == "dagin" and sure is not None:
            # hepsi aynı anda düşmesin; ama her düşüş çekim bitmeden tamamlansın
            uzunluk = veri.animasyon_olcum()[o["animasyon"]]["sure_sn"]
            bos = max(0.0, sure - k["tek_sefer_bitis_payi_sn"] - uzunluk)
            pay = (i * ALTIN) % 1.0
            if bos >= 0.3:
                c["gecikme_sn"] = round(pay * bos, 2)
            else:   # çekim düşüşten kısa: düşüş ortasından başlar, yine de çekim içinde biter
                gerekli = max(0.0, uzunluk - (sure - k["tek_sefer_bitis_payi_sn"]))
                c["faz_sn"] = round(min(uzunluk * 0.9, gerekli + pay * 0.4), 2)
        sonuc.append(c)
    return sonuc, ad, odak_i


def _yukseklik_sinifi(h: float) -> str:
    s = veri.kural("kamera")["yukseklik_siniflari"]
    return "alcak" if h < s["alcak"] else ("yuksek" if h > s["yuksek"] else "goz")


def _aci_kovasi(a: float) -> str:
    a = abs((a + 180) % 360 - 180)
    for ad, sinir in veri.kural("kamera")["aci_kovalari"].items():
        if a < sinir:
            return ad
    return "arka"


def cekim_turu_adaylari(mesafe: str, hareketli: bool, gecmis: list[dict], indeks: int, tercih: str | None = None,
                        ayrilmis: set | None = None) -> list[str]:
    """Çeşitlilik sırasına dizilmiş uygun türler: kullanılmamış türler önce; önceki çekimle aynı hareket, yükseklik ve
    açı kovası cezalandırılır. Niyetin tercih ettiği tür, önceki çekimle aynı hareket değilse başa alınır."""
    kat = veri.kural("kamera")["cekimler"]
    adaylar = [ad for ad, x in kat.items() if mesafe in x["mesafeler"] and (x.get("gerekli") != "hareketli" or hareketli)]
    if not adaylar:
        return ""
    onceki = gecmis[-1] if gecmis else None
    sayac = {}
    for g in gecmis:
        sayac[g["tur"]] = sayac.get(g["tur"], 0) + 1
    def puan(ad):
        x = kat[ad]
        p = sayac.get(ad, 0) * 10
        if onceki:
            p += 6 * (x["hareket"] == onceki["hareket"]) + 3 * (_yukseklik_sinifi(x["yukseklik_m"]) == onceki["yukseklik"])
            p += 2 * (_aci_kovasi(x["aci_derece"]) == onceki["aci_kovasi"])
        return (p, (adaylar.index(ad) - indeks) % len(adaylar))
    ayrilmis = (ayrilmis or set()) - {tercih}
    sirali = sorted(adaylar, key=lambda ad: (ad in ayrilmis,) + puan(ad))   # başka cümlenin tercih ettiği tür sona
    if tercih in sirali and not (onceki and kat[tercih]["hareket"] == onceki["hareket"]):
        sirali.remove(tercih)
        sirali.insert(0, tercih)
    return sirali


def _yon(a_derece: float) -> np.ndarray:
    a = math.radians(a_derece)
    return np.array([math.sin(a), 0.0, math.cos(a)])


def kamera_kur(tur: str, odak: dict, sure: float, oran: float, tepe: float | None = None) -> dict:
    x = veri.kural("kamera")["cekimler"][tur]
    fov = float(veri.kural("kamera")["fov"])
    boy = veri.kural("mesafe")["karakter_boyu_m"]
    d = boy / (2 * oran * math.tan(math.radians(fov) / 2))
    s0, s1 = kadraj.karakter_konumu(odak, 0.0), kadraj.karakter_konumu(odak, sure)
    sm = (s0 + s1) / 2
    yon = _yon(odak.get("yon_derece", 0.0) + x["aci_derece"])
    h, hy = x["yukseklik_m"], x["hedef_y_m"]
    if veri.kural("animasyon")["animasyonlar"].get(odak.get("animasyon"), {}).get("son_poz") == "yerde":
        hy = min(hy, 0.5)   # çekim sonunda karakterler yerde: bakış yere iner
    if tepe and tepe > boy:
        hy += (tepe - boy) * 0.35   # odak uzun bir nesne (sancak, standart) taşıyorsa bakış noktası biraz yükselir
    yuk = np.array([0, 1.0, 0])

    def an(merkez, uzaklik, yukseklik, yon_v, hedef_kayma=np.zeros(3)):
        return {"konum": [round(float(v), 3) for v in merkez + yon_v * uzaklik + yuk * yukseklik],
                "hedef": [round(float(v), 3) for v in merkez + yuk * hy + hedef_kayma], "fov": fov}

    hr = x["hareket"]
    if hr in ("takip", "geri_takip"):
        bas, son = an(s0, d, h, yon), an(s1, d, h, yon)
    elif hr == "yaklasma":
        bas, son = an(s0, d * 1.15, h, yon), an(s1, d * 0.92, h, yon)
    elif hr == "yukselme":
        bas, son = an(sm, d * 0.9, h, yon), an(sm, d * 1.05, h + 4.5, yon)
    elif hr == "yorunge":
        bas, son = an(s0, d, h, _yon(odak.get("yon_derece", 0.0) + x["aci_derece"] - 15)), an(s1, d, h, _yon(odak.get("yon_derece", 0.0) + x["aci_derece"] + 20))
    elif hr == "yanal_kayma":
        yan = np.cross(yon, yuk)
        bas = an(sm, d, h, yon, -yan * 0.0)
        bas["konum"] = [round(float(v), 3) for v in np.array(bas["konum"]) - yan * d * 0.18]
        son = an(sm, d, h, yon)
        son["konum"] = [round(float(v), 3) for v in np.array(son["konum"]) + yan * d * 0.18]
    elif hr == "sabit_suzulme":
        bas = an(sm, d, h, yon)
        son = an(sm, d * 1.04, h + 0.4, yon)
    else:  # sabit
        bas = son = an(sm, d, h, yon)
    return {"plan": None, "hareket": hr, "bas": bas, "son": son, "yumusatma": "giris_cikis" if hr != "takip" else "dogrusal"}


def kamera_ayarla(cekim: dict, odak_i: int, mesafe: str, en_boy: float, tur: str, tepe: float | None = None) -> dict:
    """Kadraj ölçümüyle doğrulama: odak karakterin ölçülen en büyük oranı hedef sınıfın içine düşene kadar
    uzaklığı ölçekler (en çok 6 deneme). Sınıf tutmazsa çekim olduğu gibi döner; plan denetimi reddeder."""
    m = veri.kural("mesafe")["sinirlar"]
    hedef = veri.kural("kamera")["hedef_oran"][mesafe]
    oran = hedef
    for _ in range(6):
        cekim["kamera"] = kamera_kur(tur, cekim["karakterler"][odak_i], cekim["sure_sn"], oran, tepe)
        cekim["kamera"]["plan"] = mesafe
        olc = kadraj.olc(cekim, en_boy)
        sinif_en = max((x["ekran_orani"] for x in olc.values() if x["gorunur"]), default=0.0)
        if mesafe == "orta" and m["uzak"] <= sinif_en <= m["yakin"] * 0.92:
            break
        if mesafe == "uzak" and 0 < sinif_en < m["uzak"] * 0.95:
            break
        if sinif_en == 0:
            oran *= 0.8
            continue
        hedef_ust = m["yakin"] * 0.85 if mesafe == "orta" else m["uzak"] * 0.85
        oran *= min(1.6, max(0.5, (hedef_ust if sinif_en > hedef_ust else hedef) / sinif_en))
    return cekim


def cevre_yerlestir(istenen: list[str], cekim: dict, donem: str) -> tuple[list[dict], list[str]]:
    """İstenen çevre varlıkları sahnenin arkasına (kameranın bakış yönünde) yerleştirilir. Döneme uymayan ya da
    kayıtlı olmayan varlık uydurulmaz: eksik olarak döner."""
    from motor.uretim import ortam_secici
    yer, eksik = [], []
    if not istenen:
        return yer, eksik
    k = cekim["kamera"]["bas"]
    ileri = np.array(k["hedef"]) - np.array(k["konum"])
    ileri[1] = 0
    ileri /= np.linalg.norm(ileri) + 1e-9
    yan = np.cross(ileri, [0, 1, 0])
    merkez = np.array(k["hedef"])
    for i, pid in enumerate(istenen):
        if pid not in ortam_secici.donem_cevreleri(donem):
            eksik.append(f"'{pid}' {donem} döneminin çevre varlıklarında yok")
            continue
        p = merkez + ileri * (24 + 7 * i) + yan * ((-1) ** i) * (6 + 3 * i)
        yer.append({"id": pid, "konum": [round(float(p[0]), 2), round(float(p[2]), 2)], "yon_derece": round(37.0 * i % 90, 1)})
    return yer, eksik


def cekim_kur(taslak: dict, donem: str, en_boy: float, gecmis: list[dict], tohum: int,
              ayrilmis: set | None = None) -> tuple[dict, list[str], dict]:
    """taslak: sahne_bolucu.cekimlere_bol çıktısı. Dönüş: (plan çekimi, eksikler, çeşitlilik kaydı)."""
    n = taslak["niyet"]
    c = {"id": taslak["id"], "cumleler": [taslak["cumle"]], "sure_sn": taslak["sure_sn"], "tur": n["tur"], "amac": taslak.get("amac")}
    if n.get("metin_katmani"):
        c["metin_katmani"] = n["metin_katmani"]
    if n["tur"] != "3d":
        c["metin"] = n.get("metin") or n.get("aciklama", "")
        return c, [f"{taslak['id']}: '{n['tur']}' görseli üretecek 2D kart/harita motoru yok"], {}
    oyuncular, eksik = oyuncu_sec(n, donem)
    if not oyuncular:
        return c, [f"{taslak['id']}: {e}" for e in eksik] or [f"{taslak['id']}: niyette rol yok"], {}
    karakterler, dizilis, odak_i = dizilis_kur(oyuncular, n.get("eylem"), tohum, n.get("dizilis"), taslak["sure_sn"])
    o = n.get("ortam") or {}
    c["ortam"] = {"arazi": o.get("arazi", "ova_cimen"), "isik": o.get("isik", "aksam_ustu")}
    c["karakterler"] = karakterler
    hareketli = karakterler[odak_i]["hiz_m_sn"] > 0
    adaylar = cekim_turu_adaylari(n.get("mesafe", "orta"), hareketli, gecmis, len(gecmis), n.get("kamera"), ayrilmis)
    from motor.uretim import uyum
    nesne = next((r["nesne"] for r in n.get("roller", []) if r.get("nesne")), None)
    tepe = uyum.nesne_tepesi(karakterler[odak_i]["takim"], nesne) if nesne else None
    if not adaylar:
        return c, eksik + [f"{taslak['id']}: '{n.get('mesafe')}' mesafesi için çekim türü yok"], {}
    esik = veri.kural("kamera")["en_az_gorunur_oran"]
    en_iyi = None
    for tur in adaylar:   # çeşitlilik sırasıyla dene; görünürlük ve ölçek sınıfı tutan ilk tür seçilir
        kamera_ayarla(c, odak_i, n.get("mesafe", "orta"), en_boy, tur, tepe)
        olc = kadraj.olc(c, en_boy)
        nesne_ok = tepe is None or kadraj.nokta_gorunurlugu(c, c["karakterler"][odak_i], tepe, en_boy) >= 0.8
        oran = sum(x["gorunur"] for x in olc.values()) / len(olc)
        en_buyuk = max((x["ekran_orani"] for x in olc.values() if x["gorunur"]), default=0.0)
        sinif_tutuyor = olc[odak_i]["gorunur"] and (0.3 <= en_buyuk <= 1.0 if n.get("mesafe", "orta") == "orta" else en_buyuk < 0.3)
        puan = (sinif_tutuyor and nesne_ok, oran >= esik, oran)
        if en_iyi is None or puan > en_iyi[0]:
            en_iyi = (puan, tur, json.loads(json.dumps(c["kamera"])))
        if sinif_tutuyor and nesne_ok and oran >= esik:
            break
    _, tur, c["kamera"] = en_iyi
    # hiç görünmeyen yan karakterler budanır: render maliyeti var, anlatıya katkısı yok (odak asla budanmaz)
    olc = kadraj.olc(c, en_boy)
    budanan = [c["karakterler"][i]["takim"] for i, x in olc.items() if not x["gorunur"] and i != odak_i]
    if budanan:
        odak_ad = id(c["karakterler"][odak_i])
        c["karakterler"] = [k for i, k in enumerate(c["karakterler"]) if olc[i]["gorunur"] or i == odak_i]
        odak_i = next(i for i, k in enumerate(c["karakterler"]) if id(k) == odak_ad)
    cevre, ce = cevre_yerlestir(o.get("cevre", []), c, donem)
    c["ortam"]["cevre"] = cevre
    x = veri.kural("kamera")["cekimler"][tur]
    kayit = {"tur": tur, "hareket": x["hareket"], "yukseklik": _yukseklik_sinifi(x["yukseklik_m"]),
             "aci_kovasi": _aci_kovasi(x["aci_derece"]), "dizilis": dizilis, "odak": karakterler[odak_i]["takim"],
             "arazi": c["ortam"]["arazi"]}
    c["meta"] = dict(kayit, aciklama=x["aciklama"], odak_indeks=odak_i, budanan_gorunmeyen=budanan)
    c["kamera"]["hareket"] = x["hareket"]
    return c, [f"{taslak['id']}: {e}" for e in eksik + ce], kayit
