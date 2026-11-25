"""Faz 5.3 deney: anlatı amacına bağlı kamera seçimi, tür başına lens, kadraj/çarpışma denetimi ve otomatik alternatif.

motor/ DEĞİŞMEZ. Üretim planlayıcısının (motor/uretim/planlayici.py) kamera adımı bu modülde genişletilir:
- kamera_kur_v2: üretimdeki kamera_kur + tür başına fov/fov_son + 'itme' ve 'genis_suzulme' hareketleri
- kamera_ayarla_v2: üretimdeki kadraj ölçümüyle düzeltme + tür başına hedef ekran oranı
- adaylar_v2: amaç/eylem/rol/kalabalık gramerine göre sıralama + mevcut çeşitlilik cezaları
- denetle: çarpışma (karakter gövdesi, zemin), objektife yakınlık, odak kesilmesi, dönüş ve hareket hızı
- cekim_kur_v2: üretimdeki cekim_kur ile aynı akış; kusurlu aday reddedilip sıradakine geçilir (gerekçe kaydedilir)
Kural dosyası: deneyler/faz53/kamera_v2.yaml (veri.kural("kamera") bu dosyaya yönlendirilir).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import yaml

BURASI = Path(__file__).resolve().parent
REPO = BURASI.parents[1]
sys.path.insert(0, str(REPO))

from motor.uretim import kadraj, planlayici, veri  # noqa: E402

_KURAL = yaml.safe_load((BURASI / "kamera_v2.yaml").read_text())
_orijinal_kural = veri.kural


def _kural(ad: str) -> dict:
    return _KURAL if ad == "kamera" else _orijinal_kural(ad)


veri.kural = _kural   # yalnız bu süreçte; dosyalar değişmez


def kamera_kur_v2(tur: str, odak: dict, sure: float, oran: float, tepe: float | None = None) -> dict:
    x = _KURAL["cekimler"][tur]
    fov = float(x.get("fov", _KURAL["fov"]))
    fov_son = float(x.get("fov_son", fov))
    boy = veri.kural("mesafe")["karakter_boyu_m"]
    d = boy / (2 * oran * math.tan(math.radians(fov) / 2))
    s0, s1 = kadraj.karakter_konumu(odak, 0.0), kadraj.karakter_konumu(odak, sure)
    sm = (s0 + s1) / 2
    yon = planlayici._yon(odak.get("yon_derece", 0.0) + x["aci_derece"])
    h, hy = x["yukseklik_m"], x["hedef_y_m"]
    if veri.kural("animasyon")["animasyonlar"].get(odak.get("animasyon"), {}).get("son_poz") == "yerde":
        hy = min(hy, 0.5)
    if tepe and tepe > boy:
        hy += (tepe - boy) * 0.35
    yuk = np.array([0, 1.0, 0])

    def an(merkez, uzaklik, yukseklik, yon_v, f=fov):
        return {"konum": [round(float(v), 3) for v in merkez + yon_v * uzaklik + yuk * yukseklik],
                "hedef": [round(float(v), 3) for v in merkez + yuk * hy], "fov": f}

    def kaydir(a, v):
        a["konum"] = [round(float(q), 3) for q in np.array(a["konum"]) + v]
        a["hedef"] = [round(float(q), 3) for q in np.array(a["hedef"]) + v * 0.35]
        return a

    hr = x["hareket"]
    yan = np.cross(yon, yuk)
    if hr in ("takip", "geri_takip"):
        bas, son = an(s0, d, h, yon), an(s1, d, h, yon)
    elif hr == "yaklasma":
        bas, son = an(s0, d * 1.15, h, yon), an(s1, d * 0.92, h, yon)
    elif hr == "itme":   # dramatik yaklaşma: dolly + daralan lens; ekran oranı d'de hedefe ulaşır
        bas, son = an(s0, d * 1.45, h, yon, fov), an(s1, d * 1.0 * math.tan(math.radians(fov) / 2) / math.tan(math.radians(fov_son) / 2) * 0.82, h, yon, fov_son)
    elif hr == "yukselme":
        bas, son = an(sm, d * 0.9, h, yon), an(sm, d * 1.05, h + 4.5, yon)
    elif hr == "yorunge":
        a0 = odak.get("yon_derece", 0.0) + x["aci_derece"]
        bas, son = an(s0, d, h, planlayici._yon(a0 - 15)), an(s1, d, h, planlayici._yon(a0 + 20))
    elif hr == "yanal_kayma":
        bas = kaydir(an(sm, d, h, yon), -yan * d * 0.18)
        son = kaydir(an(sm, d, h, yon), yan * d * 0.18)
        bas["hedef"] = son["hedef"] = an(sm, d, h, yon)["hedef"]
    elif hr == "genis_suzulme":   # establishing: yanal süzülme + hafif yükselme, hedef sabit
        bas = an(sm, d, h, yon)
        son = an(sm, d, h + 1.0, yon)
        bas["konum"] = [round(float(q), 3) for q in np.array(bas["konum"]) - yan * d * 0.10]
        son["konum"] = [round(float(q), 3) for q in np.array(son["konum"]) + yan * d * 0.10]
    elif hr == "sabit_suzulme":
        bas = an(sm, d, h, yon)
        son = an(sm, d * 1.04, h + 0.4, yon)
    else:
        bas = son = an(sm, d, h, yon)
    yum = "dogrusal" if hr == "takip" else ("giris" if hr == "itme" else "giris_cikis")
    return {"plan": None, "hareket": hr, "bas": bas, "son": son, "yumusatma": yum}


def kamera_ayarla_v2(cekim: dict, odak_i: int, mesafe: str, en_boy: float, tur: str, tepe: float | None = None) -> dict:
    """Üretimdeki kamera_ayarla ile aynı döngü; hedef oran türün 'oran' alanından (yoksa mesafe sınıfından)."""
    m = veri.kural("mesafe")["sinirlar"]
    x = _KURAL["cekimler"][tur]
    hedef = float(x.get(f"oran_{mesafe}", x.get("oran", _KURAL["hedef_oran"][mesafe])))
    oran = hedef
    for _ in range(6):
        cekim["kamera"] = kamera_kur_v2(tur, cekim["karakterler"][odak_i], cekim["sure_sn"], oran, tepe)
        cekim["kamera"]["plan"] = mesafe
        olc = kadraj.olc(cekim, en_boy)
        en = max((x["ekran_orani"] for x in olc.values() if x["gorunur"]), default=0.0)
        if mesafe == "orta" and m["uzak"] <= en <= m["yakin"] * 0.92:
            break
        if mesafe == "uzak" and 0 < en < m["uzak"] * 0.95:
            break
        if en == 0:
            oran *= 0.8
            continue
        ust = m["yakin"] * 0.85 if mesafe == "orta" else m["uzak"] * 0.85
        oran *= min(1.6, max(0.5, (ust if en > ust else hedef) / en))
    return cekim


def tercih_listesi(amac: str | None, eylem: str | None, roller: list[dict], odak_rol: str | None,
                   hareketli: bool, kalabalik: int, niyet_kamera: str | None) -> tuple[list[str], set, list[str]]:
    """(tercih sırası, yasak türler, gerekçe satırları)."""
    g, yasak, liste = [], set(), []
    if niyet_kamera:
        liste.append(niyet_kamera)
        g.append(f"senaryo niyeti: {niyet_kamera}")
    e = _KURAL["eylem_kamera"].get(eylem or "")
    if e:
        liste += e.get("once", [])
        yasak |= set(e.get("yasak", []))
        g.append(f"eylem '{eylem}': {e.get('once', [])} önce" + (f", yasak {sorted(yasak)}" if yasak else ""))
    r = _KURAL["rol_kamera"].get(odak_rol or "")
    if r and not (r.get("yalniz_yerinde") and hareketli) and amac not in r.get("amaclar_haric", []):
        liste += r["once"]
        g.append(f"rol '{odak_rol}' (yerinde): {r['once']}")
    a = list(_KURAL["amac_kamera"].get(amac or "", []))
    k = _KURAL["kalabalik_kamera"]
    if kalabalik >= k["en_az"] and amac in ("baglam", "olay", "final", "gerilim"):
        a = a[:1] + [t for t in k["once"] if t not in a[:1]] + [t for t in a[1:] if t not in k["once"]]
        g.append(f"kalabalık ({kalabalik} karakter): {k['once']} öne alındı")
    liste += a
    g.append(f"amaç '{amac}': {a}")
    sira = []
    for t in liste:
        if t not in sira and t not in yasak:
            sira.append(t)
    return sira, yasak, g


def adaylar_v2(mesafe: str, hareketli: bool, gecmis: list[dict], tercih: list[str], yasak: set,
               ayrilmis: set | None) -> list[str]:
    kat = _KURAL["cekimler"]
    uygun = [ad for ad, x in kat.items() if mesafe in x["mesafeler"] and (x.get("gerekli") != "hareketli" or hareketli)
             and ad not in yasak]
    onceki = gecmis[-1] if gecmis else None
    sayac: dict = {}
    for x in gecmis:
        sayac[x["tur"]] = sayac.get(x["tur"], 0) + 1

    def anahtar(ad):
        x = kat[ad]
        ayni_hareket = bool(onceki and x["hareket"] == onceki["hareket"])   # çeşitlilik kuralı: kesin
        sira = tercih.index(ad) if ad in tercih else len(tercih) + 2
        p = sayac.get(ad, 0) * 5
        if onceki:
            p += 3 * (planlayici._yukseklik_sinifi(x["yukseklik_m"]) == onceki["yukseklik"])
            p += 2 * (planlayici._aci_kovasi(x["aci_derece"]) == onceki["aci_kovasi"])
        return (ad in (ayrilmis or set()) and ad not in tercih[:1], ayni_hareket, sira * 4 + p, ad)
    return sorted(uygun, key=anahtar)


def denetle(c: dict, odak_i: int, en_boy: float) -> list[str]:
    """Kamera hareketi boyunca kusur listesi (boş = temiz)."""
    d = _KURAL["denetim"]
    boy0 = veri.kural("mesafe")["karakter_boyu_m"]
    kam, sure, ks = c["kamera"], c["sure_sn"], c["karakterler"]
    n = d["ornek"]
    kusur: set = set()
    onceki = None
    for j in range(n):
        t = j / (n - 1)
        k, h, fov = kadraj.kamera_ani(kam, t)
        if k[1] < d["zemin_en_az_m"]:
            kusur.add(f"kamera zemine çok yakın ({k[1]:.2f} m)")
        for i, ch in enumerate(ks):
            p = kadraj.karakter_konumu(ch, t * sure)
            boy = boy0 * ch.get("olcek", 1.0)
            yatay = math.dist((k[0], k[2]), (p[0], p[2]))
            if yatay < d["govde_yaricap_m"] and k[1] < boy + 0.3:
                kusur.add(f"kamera {ch['takim']}#{i} gövdesinin içinden geçiyor")
                continue
            orta = p + np.array([0, boy * 0.6, 0])
            e = kadraj.ekran(k, h, fov, orta, en_boy)
            if e and abs(e[0]) < 1.1 and abs(e[1]) < 1.1 and e[2] < d["objektif_en_az_m"]:
                kusur.add(f"{ch['takim']}#{i} objektife {e[2]:.2f} m (kesik/bulanık ön plan)")
        f = ks[odak_i]
        p = kadraj.karakter_konumu(f, t * sure)
        boy = boy0 * f.get("olcek", 1.0)
        # Baş asla kesilmez; yanlardan taşma yok. Orta planda ayakların alt kenardan çıkması normal kadrajdır
        # (diz üstü/bel üstü plan); uzak planda bütün beden kadrajda kalmalı.
        tam_beden = c["kamera"].get("plan") == "uzak"
        for ad, nokta in (("ayağı", p), ("başı", p + np.array([0, boy, 0]))):
            e = kadraj.ekran(k, h, fov, nokta, en_boy)
            if e is None or abs(e[0]) > d["odak_kenar"] or e[1] > d["odak_kenar"] or (e[1] < -d["odak_kenar"] and (ad == "başı" or tam_beden)):
                kusur.add(f"odak karakterin {ad} kadraj dışına taşıyor")
        if onceki is not None:
            dt = sure / (n - 1)
            v0, v1 = onceki[1] - onceki[0], h - k
            a0, a1 = math.atan2(v0[0], v0[2]), math.atan2(v1[0], v1[2])
            don = abs((math.degrees(a1 - a0) + 180) % 360 - 180) / dt
            hiz = float(np.linalg.norm(k - onceki[0])) / dt
            if don > d["en_cok_donus_der_sn"]:
                kusur.add(f"bakış dönüşü çok hızlı ({don:.0f}°/sn)")
            if hiz > d["en_cok_hiz_m_sn"]:
                kusur.add(f"kamera çok hızlı ({hiz:.1f} m/sn)")
        onceki = (k, h)
    return sorted(kusur)


def cekim_kur_v2(taslak: dict, donem: str, en_boy: float, gecmis: list[dict], tohum: int,
                 ayrilmis: set | None = None, zorla_tur: str | None = None) -> tuple[dict, list[str], dict]:
    """Üretimdeki planlayici.cekim_kur akışı; kamera adımı amaç grameri + denetim + otomatik alternatif.
    zorla_tur: test için tek bir türü dener (denetim yine çalışır, kusur kaydedilir)."""
    n = taslak["niyet"]
    c = {"id": taslak["id"], "cumleler": [taslak["cumle"]], "sure_sn": taslak["sure_sn"], "tur": n["tur"], "amac": taslak.get("amac")}
    if n.get("metin_katmani"):
        c["metin_katmani"] = n["metin_katmani"]
    if n["tur"] != "3d":
        c["metin"] = n.get("metin") or n.get("aciklama", "")
        return c, [f"{taslak['id']}: '{n['tur']}' görseli üretecek 2D kart/harita motoru yok"], {}
    oyuncular, eksik = planlayici.oyuncu_sec(n, donem)
    if not oyuncular:
        return c, [f"{taslak['id']}: {e}" for e in eksik] or [f"{taslak['id']}: niyette rol yok"], {}
    karakterler, dizilis, odak_i = planlayici.dizilis_kur(oyuncular, n.get("eylem"), tohum, n.get("dizilis"), taslak["sure_sn"])
    o = n.get("ortam") or {}
    c["ortam"] = {"arazi": o.get("arazi", "ova_cimen"), "isik": o.get("isik", "aksam_ustu")}
    c["karakterler"] = karakterler
    hareketli = karakterler[odak_i]["hiz_m_sn"] > 0
    mesafe = n.get("mesafe", "orta")
    odak_rol = veri.takimlar()[karakterler[odak_i]["takim"]]["rol"]
    tercih, yasak, gerekce = tercih_listesi(taslak.get("amac"), n.get("eylem"), n.get("roller", []), odak_rol, hareketli,
                                            len(karakterler), n.get("kamera"))
    adaylar = [zorla_tur] if zorla_tur else adaylar_v2(mesafe, hareketli, gecmis, tercih, yasak, ayrilmis)
    from motor.uretim import uyum
    nesne = next((r["nesne"] for r in n.get("roller", []) if r.get("nesne")), None)
    tepe = uyum.nesne_tepesi(karakterler[odak_i]["takim"], nesne) if nesne else None
    if not adaylar:
        return c, eksik + [f"{taslak['id']}: '{mesafe}' mesafesi için çekim türü yok"], {}
    esik = _KURAL["en_az_gorunur_oran"]
    en_iyi, reddedilen = None, []
    for tur in adaylar:
        kamera_ayarla_v2(c, odak_i, mesafe, en_boy, tur, tepe)
        olc = kadraj.olc(c, en_boy)
        nesne_ok = tepe is None or kadraj.nokta_gorunurlugu(c, c["karakterler"][odak_i], tepe, en_boy) >= 0.8
        oran = sum(x["gorunur"] for x in olc.values()) / len(olc)
        en_buyuk = max((x["ekran_orani"] for x in olc.values() if x["gorunur"]), default=0.0)
        sinif = olc[odak_i]["gorunur"] and (0.3 <= en_buyuk <= 1.0 if mesafe == "orta" else en_buyuk < 0.3)
        kusur = denetle(c, odak_i, en_boy)
        if not sinif:
            kusur.append(f"ölçek sınıfı tutmadı (en büyük oran {en_buyuk:.2f})")
        if not nesne_ok:
            kusur.append("taşınan nesne kadrajda kalmıyor")
        puan = (not kusur, sinif and nesne_ok, oran >= esik, -len(kusur), oran)
        if en_iyi is None or puan > en_iyi[0]:
            en_iyi = (puan, tur, json.loads(json.dumps(c["kamera"])), kusur)
        if not kusur:
            break
        reddedilen.append({"tur": tur, "neden": kusur})
    _, tur, c["kamera"], kalan_kusur = en_iyi
    olc = kadraj.olc(c, en_boy)
    budanan = [c["karakterler"][i]["takim"] for i, x in olc.items() if not x["gorunur"] and i != odak_i]
    if budanan:
        odak_ad = id(c["karakterler"][odak_i])
        c["karakterler"] = [k for i, k in enumerate(c["karakterler"]) if olc[i]["gorunur"] or i == odak_i]
        odak_i = next(i for i, k in enumerate(c["karakterler"]) if id(k) == odak_ad)
    cevre, ce = planlayici.cevre_yerlestir(o.get("cevre", []), c, donem)
    c["ortam"]["cevre"] = cevre
    x = _KURAL["cekimler"][tur]
    kayit = {"tur": tur, "hareket": x["hareket"], "yukseklik": planlayici._yukseklik_sinifi(x["yukseklik_m"]),
             "aci_kovasi": planlayici._aci_kovasi(x["aci_derece"]), "dizilis": dizilis, "odak": karakterler[odak_i]["takim"],
             "arazi": c["ortam"]["arazi"]}
    c["meta"] = dict(kayit, aciklama=x["aciklama"], odak_indeks=odak_i, budanan_gorunmeyen=budanan,
                     lens_fov=[x.get("fov", _KURAL["fov"]), x.get("fov_son", x.get("fov", _KURAL["fov"]))],
                     secim_gerekcesi=gerekce, tercih_sirasi=tercih, reddedilen_adaylar=reddedilen,
                     kalan_kusur=kalan_kusur if en_iyi[0][0] is False else [])
    c["kamera"]["hareket"] = x["hareket"]
    hata = [f"{taslak['id']}: kamera kusuru giderilemedi: {'; '.join(kalan_kusur)}"] if not en_iyi[0][0] else []
    return c, [f"{taslak['id']}: {e}" for e in eksik + ce] + hata, kayit
