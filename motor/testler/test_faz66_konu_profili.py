"""Faz-66 — dinamik tarihî konu profili ve üretim hazırlık kapısı (offline).

Fikstür: deneyler/faz66/mohac_havuz.json — Mohaç Meydan Muharebesi için gerçek havuz biçiminde kayıtlar (iddia atomları
iddia_atom ile hesaplanmış; doğrulanmış + tartışmalı + bir belirsiz kayıt; Wikipedia koordinatı).
Gerçek planlayıcı (varlık önbelleği) isteyen testler önbellek yoksa atlanır; diğerleri planlayıcıyı sahte ile yalıtır."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from motor.uretim import konu_profili as kp, sozlesme, veri

KOK = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("otonom_uret_66", KOK / "otonom_uret.py")
ou = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ou)
HAVUZ = json.loads((KOK / "deneyler/faz66/mohac_havuz.json").read_text())
KONU = "Mohaç Meydan Muharebesi"


def _onbellek_var() -> bool:
    try:
        return bool(veri.kitler()) and bool(veri.takimlar())
    except Exception:   # noqa: BLE001
        return False


ONBELLEK = pytest.mark.skipif(not _onbellek_var(), reason="varlık önbelleği yok (gerçek planlayıcı testi)")


def _sahte_oyuncu(n, donem):
    r = (n.get("roller") or [{}])[0]
    ok = r.get("rol") in ("suvari", "piyade", "komutan") and n.get("eylem") in ("yuruyus", "hucum", "komuta_bekleme")
    return ([{"takim": "t", "rol": r.get("rol"), "odak": True}] if ok else []), []


def _sahte_cekim(taslak, donem, oran, gecmis, tohum, **_):
    return {"kamera": {"tur": "x"}}, [], {}


@pytest.fixture
def sahte_planlayici(monkeypatch):
    from motor.uretim import planlayici
    monkeypatch.setattr(planlayici, "oyuncu_sec", _sahte_oyuncu)
    monkeypatch.setattr(planlayici, "cekim_kur", _sahte_cekim)
    monkeypatch.setattr(veri, "takimlar", lambda: {"a": {"rol": "suvari"}, "b": {"rol": "piyade"}, "c": {"rol": "komutan"}})


def _profil(havuz=HAVUZ, konu=KONU):
    return kp.olustur(konu, havuz, oyuncu_sec=_sahte_oyuncu)


def _kayit(i, durum, metin):
    return {"id": f"ark_{i:03d}", "iddia": metin, "durum": durum, "yil": None, "iddia_atomlari": {},
            "bagimsiz_kaynak_sayisi": 1, "kaynaklar": [{"id": "wp", "url": "https://x", "eser": "x", "tur": "ansiklopedi"}]}


# ================================================================== 1) mevcut pilotlar / yeni konu

def test_mevcut_pilot_bulunur_yeni_konu_eksik_tespit_edilir():
    assert ou.sablon_bul("Otlukbeli Savaşı").name == "otlukbeli-1473"
    assert ou.sablon_bul("Roma lejyonunun kartalı").name == "roma-lejyon-kartali"
    with pytest.raises(ou.UretimHatasi) as e:
        ou.sablon_bul(KONU)
    assert e.value.asama == "sablon" and e.value.kod == 2 and "otlukbeli-1473, roma-lejyon-kartali" in str(e.value)


def test_pilot_konularinda_profil_uretici_devreye_girmez_pilot_degismez(tmp_path, monkeypatch):
    oz = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((KOK / "motor/uretim/pilotlar").glob("*/konu.json"))}
    monkeypatch.setattr(kp, "olustur", lambda *a, **k: pytest.fail("pilot konusunda profil üretilmemeli"))
    monkeypatch.setattr(ou, "dinamik_sablon", lambda *a, **k: pytest.fail("pilot konusunda dinamik şablon yok"))
    with pytest.raises(ou.UretimHatasi) as e:   # Gemini yerine anahtar hatası değil: havuzdan sonra görsel kapısı durdurur
        ou.planla("Otlukbeli Savaşı", "shorts", tmp_path / "is", "AIza", havuz_fn=lambda k: {"kayitlar": []},
                  saglayici_fn=lambda: None)
    assert e.value.asama == "arastirma"
    assert not (tmp_path / "is" / "_profil").exists()
    assert oz == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in oz}


# ================================================================== 2) dinamik profil (Mohaç)

def test_mohac_profili_arastirmadan_kurulur():
    k, m, kat = _profil()
    assert sozlesme.konu_denetle(k) == []                                          # konu.schema.json + kit
    assert (k["kimlik"], k["baslik"], k["format"], k["donemler"]) == ("mohac-1526", KONU, "shorts", ["osmanli-15yy"])
    assert m["tarih"] | {} == m["tarih"] and (m["tarih"]["metin"], m["tarih"]["kesinlik"]) == ("29 Ağustos 1526", "kesin")
    tr = {t["anahtar"]: t for t in m["taraflar"]}
    assert set(tr) == {"osmanli-15yy", "macar-16yy"} and set(k["harita"]["taraflar"]) == set(tr)
    assert (tr["osmanli-15yy"]["kit"], tr["osmanli-15yy"]["kit_uygunlugu"], tr["osmanli-15yy"]["kit_farki_yil"]) == \
        ("osmanli-15yy", "yakin", 6)
    assert tr["macar-16yy"]["kit"] is None                                          # kitsiz taraf: yalnız harita
    assert {b["tur"] for b in tr["osmanli-15yy"]["birlikler"]} == {"suvari", "piyade", "top"}
    assert {b["tur"] for b in tr["macar-16yy"]["birlikler"]} == {"suvari", "piyade"}
    assert [x["ad"] for x in m["kisiler"]] == ["Kanuni Sultan Süleyman"]
    assert m["sonuc"]["kesinlik"] == "kesin" and m["sonuc"]["kazanan"] == "osmanli-15yy"
    assert [e["id"] for e in k["harita"]["evreler"]] == ["E1", "E2", "E3"]
    assert k["harita"]["evreler"][0]["baslik"] == "Mohaç · 29 Ağustos 1526"
    assert m["konum"]["enlem"] == 45.993 and m["olay_turu"]["tur"] == "kara"
    assert any("Macar Krallığı için 3D dönem kiti yok" in n for n in k["notlar"])
    assert [x["katalog"] for x in kat] == ["3D-osmanli-suvari", "3D-osmanli-piyade", "3D-osmanli-komutan"]
    assert all(r["donem"] == "osmanli-15yy" for x in kat for r in x["niyet"]["roller"])   # kitsiz tarafa 3D yok


def test_meta_kaynak_kayitlarini_tasir_belirsiz_kayit_girmez():
    k, m, _ = _profil()
    ids = {x["id"] for x in m["kartlar"]}
    assert "ark_012" not in ids and all(x["durum"] in ("dogrulanmis", "tartismali") for x in m["kartlar"])
    assert set(m["tarih"]["kartlar"]) <= ids and set(m["sonuc"]["kartlar"]) <= ids
    assert m["uretici"] == "motor.uretim.konu_profili" and m["surum"] == kp.SURUM
    assert "ark_" in k["harita"]["kaynak"] and "şematik" in k["harita"]["kaynak"]


def test_profil_deterministik():
    a = json.dumps(_profil(), ensure_ascii=False, sort_keys=True)
    b = json.dumps(_profil(copy.deepcopy(HAVUZ)), ensure_ascii=False, sort_keys=True)
    karisik = dict(HAVUZ, kayitlar=list(reversed(HAVUZ["kayitlar"])))
    c = json.dumps(_profil(karisik), ensure_ascii=False, sort_keys=True)
    assert a == b == c
    farkli = copy.deepcopy(HAVUZ)
    farkli["kayitlar"][0]["iddia"] += " Ek."
    assert _profil(farkli)[1]["girdi_ozeti"] != _profil()[1]["girdi_ozeti"]


# ================================================================== 3) tartışmalı bilginin korunması

def test_tarih_yalniz_tartismali_kayitlardaysa_kesinlesmez():
    h = copy.deepcopy(HAVUZ)
    for x in h["kayitlar"]:
        if x["durum"] == "dogrulanmis":
            x["iddia_atomlari"] = {**x["iddia_atomlari"], "yil": []}
            x["yil"] = None
    k, m, kat = _profil(h)
    assert m["tarih"]["kesinlik"] == "tartismali" and m["tarih"]["yil"] == 1526
    assert k["harita"]["evreler"][0]["baslik"].endswith("(tarih tartışmalı)")
    assert any(b["alan"] == "tarih" for b in m["belirsizlikler"])
    r = kp.profil_denetle(k, m, kat, oyuncu_sec=_sahte_oyuncu, cekim_kur=_sahte_cekim)
    assert any(x.startswith("tarih tartışmalı") for x in r["uyarilar"])


def test_tartismali_sonuc_kesin_evreye_donusmez():
    h = copy.deepcopy(HAVUZ)
    for x in h["kayitlar"]:
        if x["id"] in ("ark_002", "ark_005"):
            x["durum"] = "tartismali"
    k, m, _ = _profil(h)
    assert m["sonuc"]["kesinlik"] == "tartismali" and m["sonuc"]["kazanan"] is None and m["sonuc"]["aday"] == "osmanli-15yy"
    assert [e["id"] for e in k["harita"]["evreler"]] == ["E1", "E2"]                 # sonuç evresi çizilmez
    assert not any(b.get("dagildi") for e in k["harita"]["evreler"] for b in e["birlikler"])
    assert any(b["alan"] == "sonuc" for b in m["belirsizlikler"])
    assert any(n.startswith("Tartışmalı (sonuc)") for n in k["notlar"])


def test_karsi_yonde_dogrulanmis_oylar_sonucu_tartismali_yapar():
    h = copy.deepcopy(HAVUZ)
    h["kayitlar"].append(dict(_kayit(20, "dogrulanmis", "Some accounts claim the Hungarians won the first clash in 1526."),
                              yil=1526))
    _, m, _ = _profil(h)
    assert m["sonuc"]["kesinlik"] == "tartismali"


def test_taraf_yalniz_tartismali_kayitlardaysa_isaretlenir():
    h = copy.deepcopy(HAVUZ)
    h["kayitlar"] += [_kayit(30, "tartismali", "Bazı kaynaklara göre Habsburg birlikleri 1526'da yoldaydı."),
                      _kayit(31, "tartismali", "Habsburg yardımının 1526'da geç kaldığı ileri sürülür.")]
    _, m, _ = _profil(h)
    hb = next(t for t in m["taraflar"] if t["sozluk"] == "habsburg")
    assert hb["kesinlik"] == "tartismali" and hb["kit"] is None
    assert any(b["alan"] == f"taraf:{hb['anahtar']}" for b in m["belirsizlikler"])


# ================================================================== 4) hazırlık kapısı: geçerli ve geçersiz

def test_gecerli_mohac_profili_kapidan_gecer(sahte_planlayici):
    k, m, kat = _profil()
    r = kp.profil_denetle(k, m, kat)
    assert r["gecti"] and r["hatalar"] == []
    assert r["uyarilar"] == ["Osmanlı: en yakın kit osmanli-15yy (6 yıl dışarıda; temsilî)"]


@pytest.mark.parametrize("bozma,parca", [
    (lambda k, m, kat: m.update(konum={"enlem": 95.0, "boylam": 18.0}), "koordinat: geçersiz"),
    (lambda k, m, kat: k["harita"]["evreler"][0]["birlikler"][0].update(taraf="bizans-15yy"), "tanımsız taraf"),
    (lambda k, m, kat: k["harita"]["evreler"][1]["birlikler"][1].update(tur="gemi"), "çizemediği tür 'gemi'"),
    (lambda k, m, kat: k["harita"]["evreler"][0]["birlikler"][2].update(konum=[12.0, 3.0]), "konum alan dışında"),
    (lambda k, m, kat: k["harita"]["evreler"][1]["oklar"][0].update(tur="ucus"), "tanımsız tür 'ucus'"),
    (lambda k, m, kat: k["harita"]["evreler"][1]["oklar"][0].update(yol=[[5, 5]]), "yol en az 2 nokta"),
    (lambda k, m, kat: k["harita"]["taraflar"]["macar-16yy"].update(renk=[2, 0, 0]), "renk"),
    (lambda k, m, kat: k["donemler"].append("macar-16yy"), "kit yok"),
    (lambda k, m, kat: m["tarih"].update(yil=1200), "1200 yılına uygun değil"),
    (lambda k, m, kat: m["tarih"].update(yil=None), "geçerli yıl yok"),
    (lambda k, m, kat: m.update(taraflar=m["taraflar"][:1]), "en az 2 taraf"),
    (lambda k, m, kat: m.update(olay_turu={"tur": "deniz"}), "olay türü deniz"),
    (lambda k, m, kat: kat[0]["niyet"]["roller"][0].update(rol="fil_suvarisi"), "olmayan rol 'fil_suvarisi'"),
    (lambda k, m, kat: kat[0]["niyet"].update(eylem="ucus"), "tanımsız eylem 'ucus'"),
    (lambda k, m, kat: kat[0]["niyet"].update(kamera="uydu"), "tanımsız kamera 'uydu'"),
    (lambda k, m, kat: kat[1]["niyet"].update(eylem="savunma_hatti"), "oyuncuya dönüşmüyor"),
    (lambda k, m, kat: kat[0]["niyet"]["roller"][0].update(donem="bizans-15yy"), "konunun kitlerinde yok"),
    (lambda k, m, kat: k.pop("harita"), "profil haritası yok"),
    (lambda k, m, kat: kat.clear(), "Shorts 3D kuralı karşılanamaz"),
])
def test_gecersiz_profil_reddedilir(sahte_planlayici, bozma, parca):
    k, m, kat = _profil()
    bozma(k, m, kat)
    r = kp.profil_denetle(k, m, kat)
    assert not r["gecti"] and any(parca in x for x in r["hatalar"]), r["hatalar"]


def test_cekim_kurulamayan_katalog_reddedilir(sahte_planlayici, monkeypatch):
    k, m, kat = _profil()
    r = kp.profil_denetle(k, m, kat, cekim_kur=lambda *a: ({}, ["kamera bulunamadı"], {}))
    assert any("çekim kurulamadı (kamera bulunamadı)" in x for x in r["hatalar"])


def test_kitsiz_ve_deniz_konulari_kapida_durur(sahte_planlayici):
    kades = {"kayitlar": [
        _kayit(1, "dogrulanmis", "Kadeş Muharebesi MÖ 1274'te Mısır ile Hitit orduları arasında yapıldı."),
        _kayit(2, "dogrulanmis", "Mısır firavunu II. Ramses Hitit kralı Muvattalli ile savaştı."),
        _kayit(3, "dogrulanmis", "Hitit savaş arabaları Mısır ordusuna saldırdı.")]}
    for x in kades["kayitlar"]:
        x["iddia_atomlari"] = {"yil": [-1274]}
    k, m, kat = kp.olustur("Kadeş Muharebesi", kades, oyuncu_sec=_sahte_oyuncu)
    assert k["donemler"] == [] and kat == [] and {t["sozluk"] for t in m["taraflar"]} == {"misir", "hitit"}
    assert k["kimlik"] == "kades-mo1274" and m["taraflar"][0]["anahtar"].endswith("mo13yy")
    r = kp.profil_denetle(k, m, kat)
    assert not r["gecti"] and any("desteklenen 3D dönem kiti yok" in x for x in r["hatalar"])
    preveze = {"kayitlar": [_kayit(i, "dogrulanmis", t) for i, t in enumerate([
        "Preveze Deniz Muharebesi 1538'de Osmanlı donanması ile Venedik ve Haçlı donanması arasında yapıldı.",
        "Barbaros Hayreddin Paşa komutasındaki Osmanlı donanması 1538'de kadırgalarla saldırdı.",
        "The Venetian fleet withdrew in 1538 after the naval battle with the Ottoman fleet.",
        "Osmanlı kadırgaları 1538'de Venedik gemilerini kuşattı."], 1)]}
    for x in preveze["kayitlar"]:
        x["iddia_atomlari"] = {"yil": [1538]}
    k, m, kat = kp.olustur("Preveze Deniz Muharebesi", preveze, oyuncu_sec=_sahte_oyuncu)
    assert m["olay_turu"]["tur"] == "deniz"
    r = kp.profil_denetle(k, m, kat)
    assert any("olay türü deniz" in x for x in r["hatalar"])


def test_yetersiz_arastirma_profil_hatasi():
    with pytest.raises(kp.ProfilHatasi, match="en az 3"):
        kp.olustur(KONU, {"kayitlar": HAVUZ["kayitlar"][:2]})


# ================================================================== 5) üretim hattına bağlama

def test_planla_dinamik_profili_kapidan_gecirip_is_klasorune_yazar(tmp_path, sahte_planlayici, monkeypatch):
    from motor.uretim import anlati, sahne_bolucu
    from motor.varlik import tarihi_gorsel
    monkeypatch.setattr(sozlesme, "senaryo_denetle", lambda s, a: [])
    monkeypatch.setattr(anlati, "shorts_denetle", lambda s, sr: ([], {}))
    monkeypatch.setattr(ou, "EN_AZ_GORSEL", {"shorts": 1, "uzun": 1})
    monkeypatch.setattr(ou, "_shorts_3d_esik", lambda: (0, 0))
    monkeypatch.setattr(ou, "oyuncu_hatalari", lambda s, k, kat=None: [])
    monkeypatch.setattr(sahne_bolucu, "zaman_cizelgesi", lambda s, sr: None)
    monkeypatch.setattr(sahne_bolucu, "cekimlere_bol", lambda s, cz, havuz=None: [])
    monkeypatch.setattr(sahne_bolucu, "toplam_sure", lambda c: 50.0)
    monkeypatch.setattr(tarihi_gorsel, "dogrulanmis_dosya", lambda gid: (tmp_path / gid, {}))
    monkeypatch.setattr(ou, "GORSEL_KOK", tmp_path / "gorsel")
    rol = [{"rol": "suvari", "donem": "osmanli-15yy"}]
    sen = {"cumleler": [
        {"id": "S1", "metin": "a", "kartlar": ["C1"], "niyet": {"tur": "gorsel25d", "aciklama": "p",
                                                                "gorsel25d": {"gorsel_id": "mohac-1526-oto-portre"}}},
        {"id": "S2", "metin": "b", "kartlar": ["C1"], "niyet": {"tur": "harita", "evre": "E1", "metin": "Dizilış"}}]
        + [{"id": f"S{i}", "metin": "c", "kartlar": ["C1"], "niyet": {"tur": "3d", "roller": rol}} for i in (3, 4, 5)]}

    class Sahte:
        def __init__(self):
            self.yanitlar = [json.dumps([{"gorsel_id": "portre", "sorgu": "q", "aciklama": "portre"}]), json.dumps(sen)]
            self.istemler = []

        def tamamla(self, istem, adim, baglam):
            self.istemler.append((adim, istem))
            return self.yanitlar.pop(0)

    def sahte_planla(is_):
        s = json.loads((is_ / "senaryo.json").read_text())
        (is_ / "cekim_plani.json").write_text(json.dumps({"konu": s["konu"], "cekimler": [
            {"id": c["id"], "tur": c["niyet"]["tur"], "sure_sn": 4.0, "cumleler": [c["id"]]} for c in s["cumleler"]]}))
        return {"gecti": True, "hatalar": {}, "toplam_sure_sn": 50.0}

    sg = Sahte()
    r = ou.planla(KONU, "shorts", tmp_path / "is", "AIza", 2, havuz_fn=lambda konu: copy.deepcopy(HAVUZ),
                  saglayici_fn=lambda: sg, topla=lambda q, h: {"lisans_turu": "PD-Art", "eser_adi": "p"},
                  planla_fn=sahte_planla, olc=lambda cs: {})
    d = tmp_path / "is" / "_profil" / "mohac-1526"
    assert r["sablon"] == "mohac-1526" and r["profil"]["dinamik"] and r["profil"]["dizin"] == str(d)
    assert {p.name for p in d.iterdir()} == {"konu.json", "profil_meta.json", "uc_boyut_katalogu.json", "profil_raporu.json"}
    assert json.loads((d / "profil_raporu.json").read_text())["gecti"] is True
    is_ = Path(r["isler"][0]["is"])
    k = json.loads((is_ / "konu.json").read_text())
    assert k["kimlik"] == "mohac-1526-oto" and k["donemler"] == ["osmanli-15yy"] and "harita" in k
    senaryo_istemi = next(i for a, i in sg.istemler if a == "senaryo")
    assert "Mohaç · 29 Ağustos 1526" in senaryo_istemi and "osmanli-15yy" in senaryo_istemi
    assert not (KOK / "motor/uretim/pilotlar/mohac-1526").exists()                 # pilotlara yazılmaz
    assert [x["katalog"] for x in ou._sablon_katalog(d)] == ["3D-osmanli-suvari", "3D-osmanli-piyade", "3D-osmanli-komutan"]


def test_planla_kapidan_gecemeyen_profili_durdurur_ve_raporlar(tmp_path, sahte_planlayici):
    h = copy.deepcopy(HAVUZ)
    h["konum"] = {"enlem": 123.0, "boylam": 18.0}
    with pytest.raises(ou.UretimHatasi) as e:
        ou.planla(KONU, "shorts", tmp_path / "is", "AIza", havuz_fn=lambda konu: h,
                  saglayici_fn=lambda: pytest.fail("kapıdan geçmeyen profilde Gemini çağrılmamalı"))
    assert e.value.asama == "profil" and e.value.kod == 2 and "koordinat: geçersiz" in str(e.value)
    rapor = json.loads((tmp_path / "is/_profil/mohac-1526/profil_raporu.json").read_text())
    assert rapor["gecti"] is False and any("koordinat" in x for x in rapor["hatalar"])
    with pytest.raises(ou.UretimHatasi) as e:
        ou.planla(KONU, "shorts", tmp_path / "is2", "AIza", havuz_fn=lambda konu: {"kayitlar": []})
    assert e.value.asama == "profil" and "en az 3" in str(e.value)


def test_wikipedia_koordinati_ayristirilir():
    from motor.orkestrasyon import kaynak_kesif as kk
    assert kk.koordinat({"coordinates": [{"lat": 45.99, "lon": 18.68, "primary": True, "globe": "earth"}]}) == \
        {"enlem": 45.99, "boylam": 18.68}
    assert kk.koordinat({"coordinates": [{"lat": 1, "lon": 2, "globe": "earth"}, {"lat": 3, "lon": 4, "primary": ""}]}) == \
        {"enlem": 3.0, "boylam": 4.0}
    assert kk.koordinat({"coordinates": [{"lat": 95, "lon": 2}]}) is None
    assert kk.koordinat({"coordinates": [{"lat": 1, "lon": 2, "globe": "moon"}]}) is None
    assert kk.koordinat({}) is None


# ================================================================== 6) gerçek planlayıcı ve harita motoru

@ONBELLEK
def test_gercek_planlayici_mohac_profilini_gecirir():
    from motor.uretim import planlayici
    k, m, kat = kp.olustur(KONU, HAVUZ)
    assert kat and all(planlayici.oyuncu_sec(x["niyet"], "osmanli-15yy")[0] for x in kat)
    r = kp.profil_denetle(k, m, kat)
    assert r["gecti"], r["hatalar"]
    for x in kat:
        c, eks, kayit = planlayici.cekim_kur({"id": "S1", "cumle": "S1", "sure_sn": 4.0, "amac": "olay",
                                              "niyet": x["niyet"]}, "osmanli-15yy", 9 / 16, [], 3)
        assert eks == [] and isinstance(c["kamera"], dict) and c["karakterler"]


@ONBELLEK
def test_gercek_rol_katalogu_mohac_konusunda_dolu():
    k, _, _ = kp.olustur(KONU, HAVUZ)
    kat = ou.rol_katalogu(k)
    assert set(kat) == {"osmanli-15yy"} and {"suvari", "piyade", "komutan"} <= set(kat["osmanli-15yy"])


def test_harita_motoru_profil_evrelerini_cizer():
    from motor.uretim import harita
    k, _, _ = _profil()
    h = harita.Harita(k["harita"], boyut=(180, 320))
    onceki = None
    for ev in k["harita"]["evreler"]:
        im = harita.kare(h, ev, onceki, 0.8, None)
        assert im.size == (180, 320)
        onceki = ev


def test_ornek_profil_bayt_bayt_yeniden_uretilir():
    """deneyler/faz66/ornek_profil (gerçek planlayıcıyla üretildi): aynı girdi → aynı dosyalar (gerileme kontrolü)."""
    k, m, kat = _profil()
    d = KOK / "deneyler/faz66/ornek_profil"
    for ad, v in (("konu.json", k), ("profil_meta.json", m), ("uc_boyut_katalogu.json", kat)):
        assert (d / ad).read_text() == json.dumps(v, ensure_ascii=False, indent=1) + "\n", ad
    assert json.loads((d / "profil_raporu.json").read_text())["gecti"] is True


# ================================================================== çıkarım kuralları (kenar durumları)

def test_daha_az_desteklenen_yil_secilmez_alternatif_kaydedilir():
    h = copy.deepcopy(HAVUZ)
    h["kayitlar"].append(dict(_kayit(40, "dogrulanmis", "Bazı yazarlar hazırlıkların 1525'te başladığını yazar."),
                              iddia_atomlari={"yil": [1525]}))
    t = _profil(h)[1]["tarih"]
    assert t["yil"] == 1526 and {"yil": 1525, "kayit_sayisi": 1} in t["alternatifler"] and t["kesinlik"] == "kesin"


def test_tek_kayitta_gecen_ad_taraf_sayilmaz():
    h = copy.deepcopy(HAVUZ)
    h["kayitlar"].append(_kayit(41, "dogrulanmis", "Venedik elçisi 1526'da gelişmeleri bildirdi."))
    assert "venedik" not in {t["sozluk"] for t in _profil(h)[1]["taraflar"]}


def test_kit_secimi_tam_yakin_yok():
    assert kp.kit_sec(["osmanli-15yy"], 1473) == ("osmanli-15yy", "tam", 0)
    assert kp.kit_sec(["osmanli-15yy"], 1550) == ("osmanli-15yy", "yakin", 30)
    assert kp.kit_sec(["osmanli-15yy"], 1551) == (None, "yok", None)
    assert kp.kit_sec(["osmanli-15yy"], 1071) == (None, "yok", None)
    assert kp.kit_sec(["roma-cumhuriyet"], -53) == ("roma-cumhuriyet", "tam", 0)
    assert kp.kit_sec([], 1526) == (None, "yok", None) and kp.kit_sec(["osmanli-15yy"], None) == (None, "yok", None)


def test_ayni_kisinin_farkli_yazimlari_birlesir():
    ks = [_kayit(1, "dogrulanmis", "Macar ordusunu Kral II. Lajos yönetiyordu."),
          _kayit(2, "dogrulanmis", "Savaştan sonra II. Lajos bir derede boğuldu."),
          _kayit(3, "tartismali", "Kaynaklara göre Lajos genç yaştaydı.")]
    kisiler, _ = kp.adlar_bul(ks, {"macar"})
    assert kisiler == [{"ad": "Kral II. Lajos", "kartlar": ["ark_001", "ark_002", "ark_003"], "kesinlik": "kesin"}]


def test_hem_zafer_hem_yenilgi_tasiyan_kayit_oy_vermez():
    h = copy.deepcopy(HAVUZ)
    h["kayitlar"].append(_kayit(42, "dogrulanmis", "Macar kroniklerindeki zafer anlatısına karşın ordu 1526'da yenildi."))
    s = _profil(h)[1]["sonuc"]
    assert s["kesinlik"] == "kesin" and s["kazanan"] == "osmanli-15yy"
