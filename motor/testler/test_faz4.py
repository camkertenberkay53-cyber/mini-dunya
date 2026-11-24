"""Faz 4 (kontrol noktası 1) kabul testleri: sözleşmeler, plan denetçileri (M6, M7, M8), kadraj ölçümü,
ayak kayması ve uçtan uca küçük bir render. Faz 3b'nin kabul edilmiş çıktılarının değişmediği de burada denetlenir."""
from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest

from motor import ayar
from motor.karakter import montaj
from motor.uretim import animasyon_izni, ayak_kaymasi, kadraj, plan_denetim, render, secici, sozlesme, veri

ORNEK = Path(__file__).resolve().parents[1] / "uretim" / "ornekler"
TEST_PLANI = ORNEK / "test_cekimi.json"


@pytest.fixture()
def plan():
    return json.loads(TEST_PLANI.read_text())


def _hatalar(p):
    return plan_denetim.denetle(p)["hatalar"]


def _var(hatalar, parca):
    return any(parca in h for h in hatalar)


# ---------------------------------------------------------------- Faz 3b korunuyor

def test_faz3b_kabul_dosyalari_degismedi():
    """Faz 4 montaj_testi.json, kalite.json ve kit dosyalarına yazmaz: a34d313'teki halleriyle aynı olmalı."""
    for yol in ("motor/karakter/montaj_testi.json", "motor/karakter/kalite.json", "motor/kit/faz3", "motor/varlik/ekipman.yaml"):
        r = subprocess.run(["git", "diff", "--quiet", "a34d313", "--", yol], cwd=ayar.REPO)
        assert r.returncode == 0, f"{yol} Faz 3b kabulünden sonra değişmiş"


def test_ek_animasyon_testi_esikleri_montajla_ayni():
    a = veri.animasyon_testi()
    assert a["esikler"] == montaj.ESIK
    assert a["kare"] == 5
    assert set(a["animasyonlar"]) | set(montaj.ANIMASYONLAR) | set(montaj.ANIMASYON_SUVARI) == set(veri.kural("animasyon")["animasyonlar"])
    assert len(a["takimlar"]) == len(veri.takimlar()) == 52
    for ad, x in a["takimlar"].items():
        for anim, r in x.items():
            assert r["ornek_kare"] == 5, f"{ad} {anim} ölçülmemiş"


# ---------------------------------------------------------------- sözleşmeler

def test_konu_sozlesmesi():
    k = {"surum": 1, "kimlik": "roma-lejyon-kartali", "baslik": "Lejyonun Kartalı", "format": "shorts",
         "hedef_sure_sn": [30, 40], "donemler": ["roma-cumhuriyet"], "dil": "tr", "ozet": "Roma lejyonunun kartalı ve onu taşıyan asker."}
    assert sozlesme.konu_denetle(k) == []
    assert _var(sozlesme.konu_denetle(dict(k, donemler=["viking-10yy"])), "kit yok")
    assert _var(sozlesme.konu_denetle({x: v for x, v in k.items() if x != "ozet"}), "ozet")
    assert _var(sozlesme.konu_denetle(dict(k, hedef_sure_sn=[40, 30])), "sırasında")


ARASTIRMA = {"surum": 1, "konu": "x", "kaynaklar": [{"id": "K1", "baslik": "Kaynak", "tur": "ikincil"}],
             "kartlar": [{"id": "C1", "iddia": "Kesin bir olgu.", "guven": "kesin", "kaynaklar": ["K1"]},
                         {"id": "C2", "iddia": "Belirsiz bir olgu.", "guven": "belirsiz", "kaynaklar": ["K1"]}]}


def _senaryo(metin="Lejyon yürüyordu.", kartlar=("C1",)):
    return {"surum": 1, "konu": "x", "format": "shorts", "baslik": "B", "kanca": "S1", "final": "S1",
            "cumleler": [{"id": "S1", "metin": metin, "kartlar": list(kartlar),
                          "niyet": {"tur": "3d", "roller": [{"rol": "piyade"}], "eylem": "yuruyus", "mesafe": "orta"}}]}


def test_arastirma_kaynaksiz_kart_reddedilir():
    assert sozlesme.arastirma_denetle(ARASTIRMA) == []
    a = copy.deepcopy(ARASTIRMA)
    a["kartlar"][0]["kaynaklar"] = ["K9"]
    assert _var(sozlesme.arastirma_denetle(a), "tanımsız kaynak")
    a["kartlar"][0]["kaynaklar"] = []
    assert sozlesme.arastirma_denetle(a)  # şema: en az bir kaynak


def test_senaryo_kartsiz_olgu_ve_kesin_dilli_belirsizlik_reddedilir():
    assert sozlesme.senaryo_denetle(_senaryo(), ARASTIRMA) == []
    assert _var(sozlesme.senaryo_denetle(_senaryo(kartlar=()), ARASTIRMA), "hiçbir araştırma kartına")
    assert _var(sozlesme.senaryo_denetle(_senaryo(kartlar=("C9",)), ARASTIRMA), "tanımsız kart")
    assert _var(sozlesme.senaryo_denetle(_senaryo("Kartal altındandı.", ("C2",)), ARASTIRMA), "kesin dille")
    assert sozlesme.senaryo_denetle(_senaryo("Kartal muhtemelen altındandı.", ("C2",)), ARASTIRMA) == []


def test_plan_her_cumleyi_gostermeli(plan):
    s = _senaryo()
    assert sozlesme.plan_ortusu(plan, s) == []
    s["cumleler"].append(dict(s["cumleler"][0], id="S2"))
    assert _var(sozlesme.plan_ortusu(plan, s), "S2: hiçbir çekimde")
    plan["cekimler"][0]["cumleler"] = []
    assert _var(sozlesme.plan_ortusu(plan, _senaryo()), "metinsiz çekim")


def test_plan_semasi_bozuk_plani_reddeder(plan):
    del plan["cekimler"][0]["sure_sn"]
    assert not plan_denetim.denetle(plan)["gecti"]


# ---------------------------------------------------------------- M6 karakter ve dönem

def test_test_cekimi_denetimden_gecer(plan):
    r = plan_denetim.denetle(plan)
    assert r["gecti"], r["hatalar"]
    assert r["cekimler"]["T1"]["olcum"]["kamera_plani_olculen"] == "orta"


def test_yanlis_donem_karakteri_reddedilir(plan):
    plan["cekimler"][0]["karakterler"][2]["takim"] = "osm_yeniceri_kilic"
    assert _var(_hatalar(plan), "dönemi osmanli-15yy, istenen roma-cumhuriyet")


def test_olmayan_karakter_uydurulmaz(plan):
    plan["cekimler"][0]["karakterler"][2]["takim"] = "rom_lejyoner_atli"
    assert _var(_hatalar(plan), "derlenmiş karakter değil")


def test_secici_kurallara_uyani_bulur_eksigi_raporlar():
    r = secici.sec("piyade", "roma-cumhuriyet", "orta", eylem="yuruyus", nesne="aquila")
    assert [a for a, _ in r["uygun"]] == ["rom_aquilifer"]
    r = secici.sec("suvari", "roma-cumhuriyet", "orta", eylem="binicilik")
    assert not r["uygun"] and "uygun karakter yok" in r["eksik"]
    r = secici.sec("piyade", "roma-cumhuriyet", "yakin", eylem="yuruyus")
    assert not r["uygun"], "A sınıfı karakter yokken yakın plan için karakter seçilmemeli"
    assert secici.sec("piyade", "roma-cumhuriyet", "orta", eylem="ucma")["eksik"]


# ---------------------------------------------------------------- M8 animasyon izni (beyaz liste)

def _yasakli_ornek():
    for ad, m in veri.montaj()["takimlar"].items():
        if "Jog_Fwd_Loop" in m.get("yasak_animasyon", {}):
            return ad
    pytest.skip("yasak animasyonlu karakter yok")


def test_yasak_animasyon_reddedilir():
    ad = _yasakli_ornek()
    ok, n = animasyon_izni.izinli(ad, "Jog_Fwd_Loop", hiz=animasyon_izni.zemin_hizi("Jog_Fwd_Loop"))
    assert not ok and _var(n, "yasak")


def test_olculmemis_animasyon_beyaz_listede_degil(monkeypatch):
    monkeypatch.setattr(veri, "animasyon_testi", lambda: {"animasyonlar": [], "takimlar": {}})
    ok, n = animasyon_izni.teknik_durum("rom_aquilifer", "Death01")
    assert not ok and _var(n, "hiç test edilmedi")


def test_ek_testten_kalan_animasyon_reddedilir():
    a = veri.animasyon_testi()
    ad, anim = next((t, x) for t, d in a["takimlar"].items() for x, r in d.items() if not r["gecti"])
    ok, n = animasyon_izni.teknik_durum(ad, anim)
    assert not ok and _var(n, "kaldı")


def test_anlamsal_kosullar():
    assert not animasyon_izni.anlamsal_durum("rom_lejyoner_pilum", "Sword_Attack")[0]   # kılıç yok
    assert animasyon_izni.anlamsal_durum("rom_lejyoner_gladius", "Sword_Attack")[0]
    assert not animasyon_izni.anlamsal_durum("rom_suvari", "Driving_Loop")[0]            # binek yok
    assert _var(animasyon_izni.anlamsal_durum("rom_sivil", "Fixing_Kneeling")[1], "işçi aleti")
    assert not animasyon_izni.anlamsal_durum("rom_sivil", "Idle_Torch_Loop")[0]          # meşale yok
    assert not animasyon_izni.anlamsal_durum("rom_sivil", "Push_Loop")[0]                # itilecek nesne yok


def test_planda_yasak_ve_anlamsiz_animasyon_reddedilir(plan):
    k = plan["cekimler"][0]["karakterler"]
    k[2]["animasyon"] = "Sword_Attack"   # pilumlu lejyoner
    k[2]["hiz_m_sn"] = 0.0
    assert _var(_hatalar(plan), "sag_el yuvasında kilic taşımıyor")


def test_ayak_kaymasina_yol_acan_hiz_reddedilir(plan):
    plan["cekimler"][0]["karakterler"][0]["hiz_m_sn"] = 1.25
    assert _var(_hatalar(plan), "ayak kayar")
    plan["cekimler"][0]["karakterler"][0].update(hiz_m_sn=0.5, animasyon="Idle_Loop")
    assert _var(_hatalar(plan), "yerinde animasyon ama")


def test_animasyon_hizi_olculmus_degerden_gelir():
    o = veri.animasyon_olcum()
    assert 0.7 < o["Walk_Loop"]["zemin_hizi_m_sn"] < 0.95
    assert o["Idle_Loop"]["zemin_hizi_m_sn"] < 0.01


def test_godotta_ayak_kaymasi_olculen_hizda_en_az():
    r = ayak_kaymasi.degerlendir("rom_aquilifer", "Walk_Loop")
    assert r["gecti"], r


# ---------------------------------------------------------------- kamera mesafesi ve M7 ortam

def test_yakin_plan_reddedilir(plan):
    c = plan["cekimler"][0]
    c["kamera"]["bas"] = {"konum": [0.0, 1.6, 3.4], "hedef": [0.0, 1.6, 2.0], "fov": 30}
    h = _hatalar(plan)
    assert _var(h, "yakın plan kullanılamaz") and _var(h, "yakin planda kullanılamaz")


def test_yanlis_plan_etiketi_reddedilir(plan):
    plan["cekimler"][0]["kamera"]["plan"] = "uzak"
    assert _var(_hatalar(plan), "ölçülen en yakın karakter 'orta'")


def test_kadraj_olcumu_izdusume_uyar():
    c = {"karakterler": [{"takim": "x", "konum": [0, 0], "yon_derece": 0}], "sure_sn": 1,
         "kamera": {"bas": {"konum": [0, 0.9, 10], "hedef": [0, 0.9, 0], "fov": 40}, "son": {"konum": [0, 0.9, 10], "hedef": [0, 0.9, 0], "fov": 40}}}
    r = kadraj.olc(c, 0.5625)[0]
    import math
    assert abs(r["ekran_orani"] - 1.8 / (2 * 10 * math.tan(math.radians(20)))) < 1e-3
    c["kamera"]["bas"]["hedef"] = c["kamera"]["son"]["hedef"] = [30, 0.9, 10]   # yana bakıyor
    assert not kadraj.olc(c, 0.5625)[0]["gorunur"]


def test_c_sinifi_cevre_orta_planda_reddedilir(plan):
    plan["cekimler"][0]["ortam"]["cevre"] = [{"id": "roma_cadiri", "konum": [1.5, 6.0]}]
    h = _hatalar(plan)
    assert _var(h, "roma_cadiri: C sınıfı") and _var(h, "planda kullanılamaz")
    assert _var(h, "çevre varlığıyla çakışıyor") or _var(h, "roma_cadiri: C sınıfı")


def test_yanlis_donem_cevresi_ve_olmayan_arazi_reddedilir(plan):
    plan["cekimler"][0]["ortam"]["cevre"] = [{"id": "osmanli_cadiri", "konum": [-14, -20]}]
    plan["cekimler"][0]["ortam"]["arazi"] = "buzul"
    h = _hatalar(plan)
    assert _var(h, "osmanli_cadiri: dönemi") and _var(h, "'buzul' arazi")


def test_belirsiz_parca_temsili_uyarisi(plan):
    p = copy.deepcopy(plan)
    p["donem"] = "bizans-15yy"
    p["cekimler"][0]["ortam"]["cevre"] = []
    for k in p["cekimler"][0]["karakterler"]:
        k["takim"] = "biz_piyade_mizrak"
    p["cekimler"][0]["karakterler"] = [dict(p["cekimler"][0]["karakterler"][0], takim="biz_komutan_sancak")]
    r = plan_denetim.denetle(p)
    assert _var(r["uyarilar"], "temsilî")


def test_cevre_varligi_karakterin_ustune_konamaz(plan):
    plan["cekimler"][0]["ortam"]["cevre"] = [{"id": "roma_cadiri", "konum": [0.0, -1.5]}]
    assert _var(_hatalar(plan), "çevre varlığıyla çakışıyor")


def test_ic_ice_karakter_ve_tekrar_eden_cekim_reddedilir(plan):
    p = copy.deepcopy(plan)
    p["cekimler"][0]["karakterler"][3]["konum"] = list(p["cekimler"][0]["karakterler"][2]["konum"])
    assert _var(_hatalar(p), "iç içe")
    p = copy.deepcopy(plan)
    p["cekimler"].append(dict(copy.deepcopy(p["cekimler"][0]), id="T2"))
    assert _var(_hatalar(p), "T2: T1 ile aynı çekim")


# ---------------------------------------------------------------- M11 render

def test_denetimden_gecmeyen_plan_render_edilmez(tmp_path, plan):
    plan["cekimler"][0]["karakterler"][0]["hiz_m_sn"] = 1.25
    y = tmp_path / "p.json"
    y.write_text(json.dumps(plan))
    r = render.render(str(y), "T1", onbellek=False)
    assert r["durum"] == "REDDEDİLDİ"


def test_is_dosyasi_belirlenimci(plan):
    a = render.is_hazirla(plan, plan["cekimler"][0])
    b = render.is_hazirla(json.loads(TEST_PLANI.read_text()), json.loads(TEST_PLANI.read_text())["cekimler"][0])
    assert render._karma(a) == render._karma(b)


def test_uctan_uca_kucuk_render(tmp_path, plan):
    """Gerçek Godot render'ı (kısa): kare sayısı ve çözünürlük doğrulanır, Godot hatası olmamalı."""
    c = plan["cekimler"][0]
    c["sure_sn"] = 0.2
    c["karakterler"] = c["karakterler"][:2]
    c["ortam"]["cevre"] = []
    y = tmp_path / "kucuk.json"
    plan["konu"] = "test-kucuk-render"
    y.write_text(json.dumps(plan))
    r = render.render(str(y), "T1", onbellek=False)
    assert r["durum"] == "TAMAM", r
    assert r["olculen"]["uretilen_kare"] == 6 and r["olculen"]["cozunurluk"] == "1080x1920"
