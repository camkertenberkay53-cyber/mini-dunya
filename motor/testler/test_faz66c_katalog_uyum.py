"""Faz-66c — rol kataloğunda animasyon uyumu ve en az 3 ayrı 3D cümle / kamera açısı çeşitliliği (offline).

Gerçek koşu (Mohaç): senaryo kapısı geçti, çekim planı kapısı durdu:
  uyum:       S7: S7a/S7b eylem 'kilic_saldirisi' — odak animasyonu ual2/Idle_Shield_Loop
  cesitlilik: farklı aci_kovasi sayısı 2; en az 3
Kök neden: katalog ve senaryo kapısı yalnız planlayici.oyuncu_sec'e bakıyordu; çekimi kuran koreografi tek başına
saldıran odağı rakip yokken bekleme animasyonuna çevirir ve uyum.py eylem kuralı düşer. Ayrıca tek 3D cümlenin iki
çekime bölünmesi (S7a/S7b) açı kovası çeşitliliğine yetmez. Korunan uyum/plan_denetim/cesitlilik kuralları DEĞİŞMEDİ."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from motor.uretim import veri

KOK = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("otonom_uret_66c", KOK / "otonom_uret.py")
ou = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ou)
PILOT = KOK / "motor/uretim/pilotlar/otlukbeli-1473"
MOHAC = json.loads((KOK / "deneyler/faz66/ornek_profil/konu.json").read_text())
GERCEK_HATALAR = {"uyum": ["S7: S7a eylem 'kilic_saldirisi' — odak animasyonu ual2/Idle_Shield_Loop",
                           "S7: S7b eylem 'kilic_saldirisi' — odak animasyonu ual2/Idle_Shield_Loop"],
                  "cesitlilik": ["farklı aci_kovasi sayısı 2; en az 3"]}


def _onbellek_var() -> bool:
    try:
        return bool(veri.kitler()) and bool(veri.takimlar())
    except Exception:   # noqa: BLE001
        return False


ONBELLEK = pytest.mark.skipif(not _onbellek_var(), reason="varlık önbelleği yok (gerçek planlayıcı testi)")


# ------------------------------------------------------------------ sahte planlayıcı: koreografi tek saldıranı beklemeye çevirir
ANIM = {"kilic_saldirisi": {"Sword_Attack"}, "yuruyus": {"Walk"}, "bekleme": {"Idle"}, "kilicla_bekleme": {"Sword_Idle"}}


@pytest.fixture
def sahte(monkeypatch):
    from motor.uretim import planlayici, secici
    cagri = {"cekim": 0}

    def oyuncu_sec(n, d):
        ok = n["roller"][0].get("rol") in ("piyade", "komutan") and n.get("eylem") in ("kilic_saldirisi", "yuruyus", "savas")
        return ([{"takim": "t", "rol": n["roller"][0]["rol"], "odak": True}] if ok else []), ([] if ok else ["yok"])

    def cekim_kur(taslak, donem, oran, gecmis, tohum, **k):
        cagri["cekim"] += 1
        e, m = taslak["niyet"].get("eylem"), taslak["niyet"].get("mesafe")
        anim = {"kilic_saldirisi": "Idle_Shield_Loop", "yuruyus": "Walk", "savas": "Sword_Idle"}.get(e, "Idle")
        if e == "savas" and m == "orta":
            anim = "Nope"   # 'savas' yalnız uzakta uyumlu
        # odak 0; yan karakter (son) her zaman saldırı animasyonunda — uyum yalnız ODAĞA bakmalı
        return {"karakterler": [{"takim": "t", "animasyon": anim}, {"takim": "y", "animasyon": "Sword_Attack"}],
                "meta": {"odak_indeks": 0}, "kamera": {}}, [], {}

    monkeypatch.setattr(planlayici, "oyuncu_sec", oyuncu_sec)
    monkeypatch.setattr(planlayici, "cekim_kur", cekim_kur)
    monkeypatch.setattr(secici, "eylem_animasyonlari", lambda e: ANIM.get(e, set()))
    monkeypatch.setattr(veri, "takimlar", lambda: {"a": {"rol": "piyade"}, "b": {"rol": "komutan"}})
    monkeypatch.setattr(ou, "_eylemler", lambda: ["kilic_saldirisi", "savas", "yuruyus"])
    monkeypatch.setattr(ou, "_UYUM_ONBELLEK", {})
    return cagri


def _n(eylem, rol="piyade", mesafe="orta"):
    return {"tur": "3d", "eylem": eylem, "mesafe": mesafe, "roller": [{"rol": rol, "donem": "osmanli-15yy"}]}


# ================================================================== 1) animasyon uyumu

def test_odak_uyumu_kurulan_cekimin_animasyonuna_bakar(sahte):
    assert ou._odak_uyumu(_n("kilic_saldirisi"), "osmanli-15yy") == (False, "Idle_Shield_Loop")
    assert ou._odak_uyumu(_n("yuruyus"), "osmanli-15yy") == (True, "Walk")
    # 'savas' eyleminin yedeği 'kilicla_bekleme' (kurallar/animasyon.yaml): uyum.py ile aynı kabul
    assert "kilicla_bekleme" in veri.kural("animasyon")["eylem_yedekleri"]["savas"]
    assert ou._odak_uyumu(_n("savas", mesafe="uzak"), "osmanli-15yy") == (True, "Sword_Idle")
    assert ou._odak_uyumu(_n("savas"), "osmanli-15yy") == (False, "Nope")
    assert ou._odak_uyumu({"tur": "3d", "roller": []}, "osmanli-15yy") == (True, "")   # eylemsiz niyet


def test_odak_uyumu_onbellekli_ve_planlayici_degisince_yeniden_olculur(sahte, monkeypatch):
    from motor.uretim import planlayici
    ou._odak_uyumu(_n("yuruyus"), "osmanli-15yy")
    ou._odak_uyumu(_n("yuruyus"), "osmanli-15yy")
    assert sahte["cekim"] == 1
    monkeypatch.setattr(planlayici, "cekim_kur", lambda *a, **k: ({"karakterler": [{"animasyon": "Idle"}], "meta": {}}, [], {}))
    assert ou._odak_uyumu(_n("yuruyus"), "osmanli-15yy") == (False, "Idle")


def test_cekim_kurulamazsa_uyumsuz(sahte, monkeypatch):
    from motor.uretim import planlayici
    monkeypatch.setattr(planlayici, "cekim_kur", lambda *a, **k: ({}, ["S: kamera yok"], {}))
    assert ou._odak_uyumu(_n("yuruyus"), "osmanli-15yy") == (False, "S: kamera yok")


def test_katalog_uyumsuz_eylemi_cikarir(sahte):
    kat = ou.rol_katalogu({"donemler": ["osmanli-15yy"]})
    assert kat == {"osmanli-15yy": {"komutan": ["savas", "yuruyus"], "piyade": ["savas", "yuruyus"]}}
    assert "kilic_saldirisi" not in ou.rol_katalogu_kurali(kat)


def test_senaryo_kapisi_uyumsuz_eylemi_yerel_duzeltme_yonuyle_raporlar(sahte):
    s = {"cumleler": [{"id": "S7", "niyet": _n("kilic_saldirisi")}, {"id": "S8", "niyet": _n("yuruyus", mesafe="uzak")}]}
    h = ou.oyuncu_hatalari(s, {"donemler": ["osmanli-15yy"]})
    assert h == [f"S7: 3D eylem 'kilic_saldirisi' kuruluyor ama odak animasyonu 'Idle_Shield_Loop' bu eyleme uymuyor "
                 f"(çekim planı uyum kuralı); 'osmanli-15yy' / 'piyade' için 'orta' mesafede uyumlu eylemler: "
                 f"yuruyus{ou.YEREL_DUZELTME}"]


def test_rol_hatasi_varsa_uyum_ayrica_raporlanmaz(sahte):
    s = {"cumleler": [{"id": "S7", "niyet": _n("kilic_saldirisi", rol="suvari")}]}
    h = ou.oyuncu_hatalari(s, {"donemler": ["osmanli-15yy"]})
    assert len(h) == 1 and "oyuncuya dönüşmüyor" in h[0] and "odak animasyonu" not in h[0]


# ================================================================== 2) en az 3 ayrı 3D cümle ve açı kovası

def _c(i, tur="3d", **n):
    if tur == "3d":
        n.setdefault("roller", [{"rol": "suvari", "donem": "osmanli-15yy"}])
    return {"id": f"S{i}", "metin": f"cümle {i}", "amac": "olay", "kartlar": ["C1"], "niyet": {"tur": tur, **n}}


@pytest.fixture
def kapilar(monkeypatch):
    from motor.uretim import anlati, sozlesme
    monkeypatch.setattr(sozlesme, "senaryo_denetle", lambda s, a: [])
    monkeypatch.setattr(anlati, "shorts_denetle", lambda s, sr: ([], {}))
    monkeypatch.setattr(ou, "EN_AZ_GORSEL", {"shorts": 0, "uzun": 0})
    monkeypatch.setattr(ou, "oyuncu_hatalari", lambda s, k, kat=None: [])
    return dict(ou.konu_kur(PILOT, "Otlukbeli Savaşı", "shorts"), hedef_sure_sn=[1, 100])


def _olc(cs):
    return {c["id"]: {"sure_sn": 6.0, "harf_sn": 14, "motor": "s", "wav": "x"} for c in cs}


def test_tek_bolunmus_3d_cumle_ve_iki_3d_cumle_kapida_durur(kapilar):
    assert ou.EN_AZ_3D_CUMLE == 3
    iki = {"format": "shorts", "cumleler": [_c(1, "harita", evre="E1", metin="a"), _c(2, mesafe="orta"),
                                            _c(3, mesafe="uzak")]}
    h = ou.senaryo_denetle(iki, {}, kapilar, [], lambda cs: pytest.fail("3D cümle sayısı TTS'ten önce denetlenmeli"))
    m = next(x for x in h if "ayrı 3D cümle" in x)
    assert m.startswith("2 ayrı 3D cümle; Shorts en az 3 ayrı 3D cümle ister (bir cümlenin çekimlere bölünmesi "
                        "sayılmaz") and m.endswith(ou.SILME_YASAGI)
    uc = copy.deepcopy(iki)
    uc["cumleler"].append(_c(4, mesafe="orta"))
    assert not any("ayrı 3D cümle" in x for x in ou.senaryo_denetle(uc, {}, kapilar, [], _olc))


def test_ilk_tur_istemi_3_ayri_cumle_ve_aci_kovasi_ister():
    p = ou.gorsel_kurallari(ou.konu_kur(PILOT, "Otlukbeli Savaşı", "shorts"), [])
    assert "en az 3 AYRI '3d' cümle yaz — bir cümlenin iki çekime bölünmesi ayrı cümle sayılmaz" in p
    assert ou.aci_kovasi_kurali() in p


def test_aci_kovasi_kurali_kamera_kurallarindan_ve_esikten():
    from motor.uretim import planlayici
    k = ou.aci_kovasi_kurali()
    esik = veri.kural("cesitlilik")["en_az_farkli_aci_kovasi"]
    assert esik == 3 and k.startswith(f"KAMERA AÇISI (zorunlu çeşitlilik): 3D çekimler en az {esik} farklı açı kovasından")
    for ad, x in veri.kural("kamera")["cekimler"].items():
        assert len(__import__("re").findall(rf"(?<![a-z_]){ad} \(", k)) == 1, ad
        kova = planlayici._aci_kovasi(float(x["aci_derece"]))
        grup = dict(g.split(": ", 1) for g in k.split("(parantezde desteklenen mesafeler): ", 1)[1].split("; "))
        assert f"{ad} ({'/'.join(x['mesafeler'])})" in grup[kova].split(", ")
    assert len({planlayici._aci_kovasi(float(x["aci_derece"])) for x in veri.kural("kamera")["cekimler"].values()}) >= esik


def test_geri_besleme_3_ayri_cumle_ve_aci_kovasini_korur():
    g = ou.geri_besleme_kurali(["S7: x"], None)
    assert "en az 3 AYRI 3D cümle ve en az 3 farklı kamera açısı kovası (KAMERA AÇISI listesi)." in g
    assert "en az biri 'orta', en az biri 'uzak'" in g and "YASAKTIR" in g


# ================================================================== 3) çekim planı hatasının geri beslemesi

def test_plan_geri_beslemesi_gercek_hatalara_yon_ekler():
    p = ou.plan_geri_beslemesi(GERCEK_HATALAR)
    assert p[:3] == ["ÇEKİM PLANI KAPISI (uyum): " + GERCEK_HATALAR["uyum"][0],
                     "ÇEKİM PLANI KAPISI (uyum): " + GERCEK_HATALAR["uyum"][1],
                     "ÇEKİM PLANI KAPISI (cesitlilik): farklı aci_kovasi sayısı 2; en az 3"]
    assert any(x.startswith("ÇEKİM PLANI YÖNÜ (cesitlilik): 3D cümle silme; en az 3 AYRI 3D cümle") for x in p)
    assert ("ÇEKİM PLANI YÖNÜ (uyum): S7 cümlesinin eylemi planlanan odak animasyonuyla uyuşmuyor; 3D ROL KATALOĞU'ndaki "
            "uyumlu bir eylemle değiştir (sahneyi silme)") in p
    assert ou.hatali_cumleler(p) == ["S7"]


def test_plan_geri_beslemesi_ilgisiz_hatada_yon_eklemez_ve_sinir_korunur():
    assert ou.plan_geri_beslemesi({"plan_denetimi": ["S2: süre"]}) == ["ÇEKİM PLANI KAPISI (plan_denetimi): S2: süre"]
    cok = ou.plan_geri_beslemesi({"cesitlilik": [f"farklı aci_kovasi sayısı {i}; en az 3" for i in range(20)]})
    assert len(cok) == 13 and cok[-1].startswith("ÇEKİM PLANI YÖNÜ (cesitlilik)")       # 12 hata + yön her zaman


def test_plan_hatasi_turunda_onceki_senaryo_ve_koruma_kurallari_aktarilir(kapilar):
    onceki = {"cumleler": [_c(1, "harita", evre="E1", metin="a"), _c(7, eylem="kilic_saldirisi", mesafe="orta"),
                           _c(8, mesafe="uzak"), _c(9, mesafe="orta")]}
    sonra = copy.deepcopy(onceki)
    sonra["cumleler"][1]["niyet"]["eylem"] = "yuruyus"

    class Sahte:
        def __init__(self):
            self.istemler = []

        def tamamla(self, istem, adim, baglam):
            self.istemler.append(istem)
            return json.dumps(sonra)

    sg = Sahte()
    s, _ = ou.senaryo_uret(sg, kapilar, {"kartlar": []}, [], olc=_olc, ilk_hatalar=ou.plan_geri_beslemesi(GERCEK_HATALAR),
                           onceki=onceki)
    ilk = sg.istemler[0]
    for parca in ("GERİ BESLEME KURALLARI (zorunlu):", "DÜZELTİLECEK cümleler: S7.", "KORUNACAK cümleler (aynen): S1, S8, S9.",
                  "Önceki turda 3 3D cümle vardı", "ÖNCEKİ SENARYO", '"eylem": "kilic_saldirisi"', "ÇEKİM PLANI YÖNÜ (uyum)",
                  "KAMERA AÇISI (zorunlu çeşitlilik)", "en az 3 AYRI 3D cümle"):
        assert parca in ilk, parca
    assert ou._uc_d_sayisi(s) == 3


def test_planla_plan_hatasinda_yonlu_geri_besleme_ve_onceki_senaryo_verir(tmp_path, monkeypatch):
    cagri = []

    def sahte_senaryo_uret(g, k, ara, gorseller, olc=None, ilk_hatalar=None, onceki=None):
        cagri.append({"ilk_hatalar": list(ilk_hatalar or []), "onceki": onceki})
        return {"cumleler": [_c(7, eylem="kilic_saldirisi")], "konu": k["kimlik"], "surum": 1}, []

    tur = {"n": 0}

    def sahte_planla(is_):
        tur["n"] += 1
        (is_ / "cekim_plani.json").write_text(json.dumps({"konu": "t", "cekimler": []}))
        return ({"gecti": False, "hatalar": GERCEK_HATALAR} if tur["n"] == 1 else
                {"gecti": True, "hatalar": {}, "toplam_sure_sn": 50.0})

    class G:
        def tamamla(self, istem, adim, baglam):
            return "[]"

    monkeypatch.setattr(ou, "senaryo_uret", sahte_senaryo_uret)
    monkeypatch.setattr(ou, "gorsel_kapisi", lambda *a, **k: [])
    havuz = {"kayitlar": [{"id": "ark_001", "iddia": "x" * 50, "durum": "dogrulanmis", "bagimsiz_kaynak_sayisi": 2,
                           "kaynaklar": [{"id": "a", "url": "https://a", "eser": "a", "tur": "ansiklopedi"},
                                         {"id": "b", "url": "https://b", "eser": "b", "tur": "ansiklopedi"}]}]}
    ou.planla("Otlukbeli Savaşı", "shorts", tmp_path / "is", "AIza", havuz_fn=lambda k: havuz, saglayici_fn=G,
              topla=lambda q, h: {}, planla_fn=sahte_planla)
    assert len(cagri) == 2 and cagri[1]["onceki"]["cumleler"][0]["niyet"]["eylem"] == "kilic_saldirisi"
    assert cagri[1]["ilk_hatalar"] == ou.plan_geri_beslemesi(GERCEK_HATALAR)


# ================================================================== 4) gerçek planlayıcı

@ONBELLEK
def test_gercek_katalogda_kilic_saldirisi_yok_her_eylem_uyumlu():
    kat = ou.rol_katalogu(MOHAC)
    assert kat and all("kilic_saldirisi" not in ey for r in kat.values() for ey in r.values())
    karsi = list(MOHAC["donemler"])
    for d, roller in kat.items():
        for r, ey in roller.items():
            for e in ey:
                assert any(ou._kurulur({"tur": "3d", "eylem": e, "mesafe": m, "roller": [{"rol": r, "donem": d}]}, d, karsi)
                           for m in ou.KATALOG_MESAFELERI), (d, r, e)


@ONBELLEK
def test_gercek_kapi_tek_saldiran_kilic_saldirisini_yakalar():
    from motor.uretim import planlayici
    n = {"tur": "3d", "eylem": "kilic_saldirisi", "mesafe": "orta", "roller": [{"rol": "piyade", "donem": "osmanli-15yy"}]}
    assert planlayici.oyuncu_sec(n, "osmanli-15yy")[0]                                     # eski kontrol geçiriyordu
    h = ou.oyuncu_hatalari({"cumleler": [{"id": "S7", "niyet": n}]}, MOHAC)
    assert len(h) == 1 and h[0].startswith("S7: 3D eylem 'kilic_saldirisi' kuruluyor ama odak animasyonu")
    assert "uyumlu eylemler:" in h[0] and "kilic_saldirisi," not in h[0].split("uyumlu eylemler:")[1]
