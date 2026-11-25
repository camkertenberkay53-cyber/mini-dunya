"""M6 + M9 — Çekim planlayıcı: bir görsel niyeti (rol, eylem, mesafe, ortam) çekilebilir bir 3D çekime çevirir.

1. Oyuncu seçimi: her rol için secici.sec (dönem, kalite/mesafe, animasyon izni, nesne). Tek bir nesneyi (sancak)
   taşıyan karakterler, o nesne açıkça istenmedikçe kalabalığa katılmaz (bir birlikte iki ana sancak olmasın).
2. Diziliş: kurallar/dizilis.yaml (kol, sıra, dağınık, tek). Odak karakter önde.
3. Kamera (Faz 5.3): kurallar/kamera.yaml kataloğundan tercih sırası anlatı amacına, eyleme, odağın rolüne ve
   kalabalığa göre kurulur (amac_kamera, eylem_kamera, rol_kamera, kalabalik_kamera); çeşitlilik kuralları (ardışık
   aynı hareket yasak, tekrar cezası) korunur. Tür başına lens ve hedef ekran oranı; uzaklık kadraj ÖLÇÜMÜYLE
   doğrulanıp düzeltilir. Her aday kamera_denetim ile denetlenir; kusurlu aday reddedilir, sıradakine geçilir
   ve gerekçe çekimin meta kaydına yazılır.
4. Çevre varlıkları: istenen dönem varlıkları kameranın baktığı yönde, sahnenin arkasına yerleştirilir.

Hiçbir şey uydurulmaz: rol, eylem ya da nesne için uygun karakter yoksa çekim "eksik" kaydıyla döner.
"""
from __future__ import annotations

import json
import math

import numpy as np

from motor.uretim import animasyon_izni, kadraj, kamera_denetim, secici, veri

ALTIN = 0.6180339887


def _sancakli(ad: str) -> bool:
    return any(e["kategori"] == "sancak" for e in veri.takimlar()[ad]["takilanlar"])


def oyuncu_sec(niyet: dict, donem: str) -> tuple[list[dict], list[str]]:
    """Dönüş: ([{takim, animasyon, rol, odak}], eksikler)"""
    eylem = niyet.get("eylem")
    mesafe = niyet.get("mesafe", "orta")
    secilen, eksik, kullanilan = [], [], set()
    for r in niyet.get("roller", []):
        rd = r.get("donem") or donem   # çok taraflı konular: rol kendi dönemini (tarafını) taşıyabilir
        s = secici.sec(r["rol"], rd, mesafe, eylem, r.get("nesne"), {"binek": False, "nesneler": []})
        uygun = [(a, an) for a, an in s["uygun"] if r.get("nesne") or not _sancakli(a)]
        if not uygun:
            eksik.append(s["eksik"] or f"{rd}: '{r['rol']}' rolü için sancaksız uygun karakter yok")
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


def kamera_tercihleri(amac: str | None, eylem: str | None, odak_rol: str | None, hareketli: bool, kalabalik: int,
                      niyet_kamera: str | None = None) -> tuple[list[str], set, list[str]]:
    """Anlatı grameri: (tercih sırası, yasak türler, gerekçe). Senaryo niyetindeki tür her zaman önce gelir."""
    k = veri.kural("kamera")
    g, yasak, liste = [], set(), []
    if niyet_kamera:
        liste.append(niyet_kamera)
        g.append(f"senaryo niyeti: {niyet_kamera}")
    e = k.get("eylem_kamera", {}).get(eylem or "")
    if e:
        liste += e.get("once", [])
        yasak |= set(e.get("yasak", []))
        g.append(f"eylem '{eylem}': {e.get('once', [])} önce" + (f", yasak {sorted(yasak)}" if yasak else ""))
    r = k.get("rol_kamera", {}).get(odak_rol or "")
    if r and not (r.get("yalniz_yerinde") and hareketli) and amac not in r.get("amaclar_haric", []):
        liste += r["once"]
        g.append(f"rol '{odak_rol}' (yerinde): {r['once']}")
    a = list(k.get("amac_kamera", {}).get(amac or "", []))
    kk = k.get("kalabalik_kamera")
    if kk and kalabalik >= kk["en_az"] and amac in ("baglam", "olay", "final", "gerilim"):
        a = a[:1] + [t for t in kk["once"] if t not in a[:1]] + [t for t in a[1:] if t not in kk["once"]]
        g.append(f"kalabalık ({kalabalik} karakter): {kk['once']} öne alındı")
    liste += a
    g.append(f"amaç '{amac}': {a}")
    sira = []
    for t in liste:
        if t not in sira and t not in yasak and t in k["cekimler"]:
            sira.append(t)
    return sira, yasak, g


def cekim_turu_adaylari(mesafe: str, hareketli: bool, gecmis: list[dict], indeks: int, tercih: str | None = None,
                        ayrilmis: set | None = None, tercih_sirasi: list[str] | None = None,
                        yasak: set | None = None) -> list[str]:
    """Uygun türler, sıralı: (1) başka cümlenin ayırdığı tür sona, (2) önceki çekimle aynı hareket sona (çeşitlilik
    kuralı), (3) anlatı tercih sırası, (4) tekrar / aynı yükseklik / aynı açı cezası."""
    kat = veri.kural("kamera")["cekimler"]
    tercih_sirasi = list(tercih_sirasi or ([tercih] if tercih else []))
    adaylar = [ad for ad, x in kat.items() if mesafe in x["mesafeler"] and (x.get("gerekli") != "hareketli" or hareketli)
               and ad not in (yasak or set())]
    if not adaylar:
        return []
    onceki = gecmis[-1] if gecmis else None
    sayac: dict = {}
    for g in gecmis:
        sayac[g["tur"]] = sayac.get(g["tur"], 0) + 1
    ayrilmis = (ayrilmis or set()) - set(tercih_sirasi[:1])

    def anahtar(ad):
        x = kat[ad]
        ayni_hareket = bool(onceki and x["hareket"] == onceki["hareket"])
        sira = tercih_sirasi.index(ad) if ad in tercih_sirasi else len(tercih_sirasi) + 2
        p = sayac.get(ad, 0) * 5
        if onceki:
            p += 3 * (_yukseklik_sinifi(x["yukseklik_m"]) == onceki["yukseklik"])
            p += 2 * (_aci_kovasi(x["aci_derece"]) == onceki["aci_kovasi"])
        return (ad in ayrilmis, ayni_hareket, sira * 4 + p, (adaylar.index(ad) - indeks) % len(adaylar))
    return sorted(adaylar, key=anahtar)


def _yon(a_derece: float) -> np.ndarray:
    a = math.radians(a_derece)
    return np.array([math.sin(a), 0.0, math.cos(a)])


def kamera_kur(tur: str, odak: dict, sure: float, oran: float, tepe: float | None = None) -> dict:
    x = veri.kural("kamera")["cekimler"][tur]
    fov = float(x.get("fov", veri.kural("kamera")["fov"]))
    fov_son = float(x.get("fov_son", fov))
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

    def an(merkez, uzaklik, yukseklik, yon_v, f=fov):
        return {"konum": [round(float(v), 3) for v in merkez + yon_v * uzaklik + yuk * yukseklik],
                "hedef": [round(float(v), 3) for v in merkez + yuk * hy], "fov": f}

    hr = x["hareket"]
    yan = np.cross(yon, yuk)
    if hr in ("takip", "geri_takip"):
        bas, son = an(s0, d, h, yon), an(s1, d, h, yon)
    elif hr == "yaklasma":
        bas, son = an(s0, d * 1.15, h, yon), an(s1, d * 0.92, h, yon)
    elif hr == "itme":   # dramatik yaklaşma: dolly + daralan lens
        d_son = d * math.tan(math.radians(fov) / 2) / math.tan(math.radians(fov_son) / 2) * 0.82
        bas, son = an(s0, d * 1.45, h, yon, fov), an(s1, d_son, h, yon, fov_son)
    elif hr == "yukselme":
        bas, son = an(sm, d * 0.9, h, yon), an(sm, d * 1.05, h + 4.5, yon)
    elif hr == "yorunge":
        a0 = odak.get("yon_derece", 0.0) + x["aci_derece"]
        bas, son = an(s0, d, h, _yon(a0 - 15)), an(s1, d, h, _yon(a0 + 20))
    elif hr == "yanal_kayma":
        bas, son = an(sm, d, h, yon), an(sm, d, h, yon)
        bas["konum"] = [round(float(v), 3) for v in np.array(bas["konum"]) - yan * d * 0.18]
        son["konum"] = [round(float(v), 3) for v in np.array(son["konum"]) + yan * d * 0.18]
    elif hr == "genis_suzulme":   # mekân tanıtımı: yanal süzülme + hafif yükselme, hedef sabit
        bas, son = an(sm, d, h, yon), an(sm, d, h + 1.0, yon)
        bas["konum"] = [round(float(v), 3) for v in np.array(bas["konum"]) - yan * d * 0.10]
        son["konum"] = [round(float(v), 3) for v in np.array(son["konum"]) + yan * d * 0.10]
    elif hr == "sabit_suzulme":
        bas = an(sm, d, h, yon)
        son = an(sm, d * 1.04, h + 0.4, yon)
    else:  # sabit
        bas = son = an(sm, d, h, yon)
    yum = "dogrusal" if hr == "takip" else ("giris" if hr == "itme" else "giris_cikis")
    return {"plan": None, "hareket": hr, "bas": bas, "son": son, "yumusatma": yum}


def kamera_ayarla(cekim: dict, odak_i: int, mesafe: str, en_boy: float, tur: str, tepe: float | None = None) -> dict:
    """Kadraj ölçümüyle doğrulama: odak karakterin ölçülen en büyük oranı hedef sınıfın içine düşene kadar
    uzaklığı ölçekler (en çok 6 deneme). Sınıf tutmazsa çekim olduğu gibi döner; plan denetimi reddeder."""
    m = veri.kural("mesafe")["sinirlar"]
    x = veri.kural("kamera")["cekimler"][tur]
    hedef = float(x.get(f"oran_{mesafe}", x.get("oran", veri.kural("kamera")["hedef_oran"][mesafe])))
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
    odak_rol = next((r for r in n.get("roller", []) if r.get("odak")), (n.get("roller") or [{}])[0])
    if odak_rol.get("donem") and odak_rol["donem"] != donem:
        c["donem"] = odak_rol["donem"]   # çekimin dönemi (çevre varlıkları) odak tarafın dönemi
    oyuncular, eksik = oyuncu_sec(n, donem)
    if not oyuncular:
        return c, [f"{taslak['id']}: {e}" for e in eksik] or [f"{taslak['id']}: niyette rol yok"], {}
    karakterler, dizilis, odak_i = dizilis_kur(oyuncular, n.get("eylem"), tohum, n.get("dizilis"), taslak["sure_sn"])
    o = n.get("ortam") or {}
    c["ortam"] = {"arazi": o.get("arazi", "ova_cimen"), "isik": o.get("isik", "aksam_ustu")}
    c["karakterler"] = karakterler
    hareketli = karakterler[odak_i]["hiz_m_sn"] > 0
    mesafe = n.get("mesafe", "orta")
    odak_rol = veri.takimlar()[karakterler[odak_i]["takim"]].get("rol")
    tercih, yasak, gerekce = kamera_tercihleri(taslak.get("amac"), n.get("eylem"), odak_rol, hareketli,
                                               len(karakterler), n.get("kamera"))
    adaylar = cekim_turu_adaylari(mesafe, hareketli, gecmis, len(gecmis), n.get("kamera"), ayrilmis, tercih, yasak)
    from motor.uretim import uyum
    nesne = next((r["nesne"] for r in n.get("roller", []) if r.get("nesne")), None)
    tepe = uyum.nesne_tepesi(karakterler[odak_i]["takim"], nesne) if nesne else None
    if not adaylar:
        return c, eksik + [f"{taslak['id']}: '{mesafe}' mesafesi için çekim türü yok"], {}
    esik = veri.kural("kamera")["en_az_gorunur_oran"]
    en_iyi, reddedilen = None, []
    for tur in adaylar:   # tercih/çeşitlilik sırasıyla dene; kusursuz, ölçek sınıfı ve görünürlük tutan ilk tür seçilir
        kamera_ayarla(c, odak_i, mesafe, en_boy, tur, tepe)
        olc = kadraj.olc(c, en_boy)
        nesne_ok = tepe is None or kadraj.nokta_gorunurlugu(c, c["karakterler"][odak_i], tepe, en_boy) >= 0.8
        oran = sum(x["gorunur"] for x in olc.values()) / len(olc)
        en_buyuk = max((x["ekran_orani"] for x in olc.values() if x["gorunur"]), default=0.0)
        sinif_tutuyor = olc[odak_i]["gorunur"] and (0.3 <= en_buyuk <= 1.0 if mesafe == "orta" else en_buyuk < 0.3)
        kusur = kamera_denetim.denetle(c, odak_i, en_boy)
        if not sinif_tutuyor:
            kusur.append(f"ölçek sınıfı tutmadı (en büyük oran {en_buyuk:.2f})")
        if not nesne_ok:
            kusur.append("taşınan nesne kadrajda kalmıyor")
        puan = (not kusur, sinif_tutuyor and nesne_ok, oran >= esik, -len(kusur), oran)
        if en_iyi is None or puan > en_iyi[0]:
            en_iyi = (puan, tur, json.loads(json.dumps(c["kamera"])), kusur)
        if not kusur:
            break
        reddedilen.append({"tur": tur, "neden": kusur})
    _, tur, c["kamera"], kalan_kusur = en_iyi
    # hiç görünmeyen yan karakterler budanır: render maliyeti var, anlatıya katkısı yok (odak asla budanmaz)
    olc = kadraj.olc(c, en_boy)
    budanan = [c["karakterler"][i]["takim"] for i, x in olc.items() if not x["gorunur"] and i != odak_i]
    if budanan:
        odak_ad = id(c["karakterler"][odak_i])
        c["karakterler"] = [k for i, k in enumerate(c["karakterler"]) if olc[i]["gorunur"] or i == odak_i]
        odak_i = next(i for i, k in enumerate(c["karakterler"]) if id(k) == odak_ad)
    cevre, ce = cevre_yerlestir(o.get("cevre", []), c, c.get("donem", donem))
    c["ortam"]["cevre"] = cevre
    x = veri.kural("kamera")["cekimler"][tur]
    kayit = {"tur": tur, "hareket": x["hareket"], "yukseklik": _yukseklik_sinifi(x["yukseklik_m"]),
             "aci_kovasi": _aci_kovasi(x["aci_derece"]), "dizilis": dizilis, "odak": karakterler[odak_i]["takim"],
             "arazi": c["ortam"]["arazi"]}
    c["meta"] = dict(kayit, aciklama=x["aciklama"], odak_indeks=odak_i, budanan_gorunmeyen=budanan,
                     lens_fov=[x.get("fov", veri.kural("kamera")["fov"]), x.get("fov_son", x.get("fov", veri.kural("kamera")["fov"]))],
                     secim_gerekcesi=gerekce, tercih_sirasi=tercih, reddedilen_adaylar=reddedilen)
    c["kamera"]["hareket"] = x["hareket"]
    return c, [f"{taslak['id']}: {e}" for e in eksik + ce], kayit
