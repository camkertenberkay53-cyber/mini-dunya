"""Faz-64c — 3D niyetinde zorunlu rol ve kanca süresi koruması.

- Rolsüz 3D niyeti (boş/eksik 'roller', boş 'rol') planda oyuncusuz → kamerasız 3D çekime dönüşüyordu; artık Shorts
  senaryo kapısında, TTS ölçümünden ÖNCE yakalanır ve geri beslenir.
- Shorts promptu 3D cümlelerinde rolü açıkça ister; kanca için en fazla 4–5 kelime ve 1.7 sn altı hedef verir.
  Üst sınır (kurallar/shorts.yaml, 2.0 sn) ve korunan anlatı/kurgu/şema kuralları DEĞİŞMEZ."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from motor.uretim import veri

KOK = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("otonom_uret_64c", KOK / "otonom_uret.py")
ou = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ou)
PILOTLAR = KOK / "motor/uretim/pilotlar"
PILOT = PILOTLAR / "otlukbeli-1473"
ROL = [{"rol": "suvari", "donem": "osmanli-15yy", "adet": 4}]


def _c(i, tur="3d", **n):
    return {"id": f"S{i}", "metin": "m", "kartlar": ["C1"], "niyet": {"tur": tur, **n}}


def _olc(cs):
    return {c["id"]: {"sure_sn": 6.0 if c["niyet"]["tur"] == "3d" else 4.0, "harf_sn": 14, "motor": "s", "wav": "x"}
            for c in cs}


@pytest.fixture
def kapilar(monkeypatch):
    """Korunan sozlesme/anlati varlık önbelleği ister; burada geçer kabul edilir (yalnız Faz-64c kuralı sınanır)."""
    from motor.uretim import anlati, sozlesme
    monkeypatch.setattr(sozlesme, "senaryo_denetle", lambda s, a: [])
    monkeypatch.setattr(anlati, "shorts_denetle", lambda s, sr: ([], {}))
    monkeypatch.setattr(ou, "EN_AZ_GORSEL", {"shorts": 0, "uzun": 0})
    return dict(ou.konu_kur(PILOT, "Otlukbeli Savaşı", "shorts"), hedef_sure_sn=[1, 100])


def _gecerli():
    return {"format": "shorts", "cumleler": [_c(1, mesafe="orta", roller=ROL), _c(2, mesafe="uzak", roller=ROL),
                                             _c(3, "harita", evre="E1")]}


# ================================================================== rol_hatalari

@pytest.mark.parametrize("niyet_eki", [{}, {"roller": []}, {"roller": None}, {"roller": "suvari"}])
def test_rolsuz_3d_niyeti_hata(niyet_eki):
    h = ou.rol_hatalari({"cumleler": [_c(7, aciklama="süvari hücumu", **niyet_eki)]})
    assert len(h) == 1 and h[0].startswith("S7:") and "'roller' boş" in h[0] and "rol" in h[0]


@pytest.mark.parametrize("rol", [{"donem": "osmanli-15yy"}, {"rol": ""}, {"rol": "   "}, {"rol": None}, {"rol": 3}, "suvari"])
def test_bos_ya_da_eksik_rol_ogesi_hata(rol):
    h = ou.rol_hatalari({"cumleler": [_c(2, roller=[ROL[0], rol])]})
    assert h == [h[0]] and h[0].startswith("S2:") and "roller[1].rol boş" in h[0]


def test_rollu_3d_ve_rol_gerektirmeyen_turler_gecer():
    s = {"cumleler": [_c(1, roller=ROL), _c(2, roller=[{"rol": "okcu", "donem": "akkoyunlu-15yy"}, {"rol": "komutan"}]),
                      _c(3, "harita", evre="E1"), _c(4, "gorsel25d", gorsel25d={"gorsel_id": "g"}, aciklama="a")]}
    assert ou.rol_hatalari(s) == []


def test_her_rolsuz_3d_cumle_ayri_raporlanir():
    s = {"cumleler": [_c(1), _c(2, roller=ROL), _c(3, roller=[{"rol": ""}])]}
    assert [x.split(":")[0] for x in ou.rol_hatalari(s)] == ["S1", "S3"]


def test_pilot_senaryolari_kurali_saglar():
    """Gerçek pilot senaryolarının bütün 3D niyetleri rol taşır: kural geçerli üretimi reddetmez."""
    for p in sorted(PILOTLAR.iterdir()):
        s = json.loads((p / "senaryo.json").read_text())
        assert any(c["niyet"]["tur"] == "3d" for c in s["cumleler"]), p.name
        assert ou.rol_hatalari(s) == [], p.name


# ================================================================== senaryo kapısı (plan aşamasına rolsüz 3D geçmez)

def test_kapi_rolsuz_3d_yi_tts_den_once_reddeder(kapilar):
    s = _gecerli()
    assert ou.senaryo_denetle(s, {}, kapilar, [], _olc) == []
    s["cumleler"][1]["niyet"].pop("roller")
    h = ou.senaryo_denetle(s, {}, kapilar, [], lambda cs: pytest.fail("rol hatasında TTS ölçülmemeli"))
    assert any(x.startswith("S2: 3D niyetinde 'roller' boş") for x in h)


def test_kapi_bos_rol_dizesini_reddeder(kapilar):
    s = _gecerli()
    s["cumleler"][0]["niyet"]["roller"] = [{"rol": "", "donem": "osmanli-15yy"}]
    assert any("S1: 3D niyetinde roller[0].rol boş" in x for x in ou.senaryo_denetle(s, {}, kapilar, [], _olc))


def test_rolsuz_3d_geri_beslenir_sonraki_denemede_gecer(kapilar):
    kotu, iyi = _gecerli(), _gecerli()
    kotu["cumleler"][0]["niyet"].pop("roller")

    class Sahte:
        def __init__(self):
            self.yanitlar, self.istemler = [json.dumps(kotu), json.dumps(iyi)], []

        def tamamla(self, istem, adim, baglam):
            self.istemler.append(istem)
            return self.yanitlar.pop(0)

    sg = Sahte()
    sen, gecmis = ou.senaryo_uret(sg, kapilar, {"kartlar": []}, [], olc=_olc)
    assert len(gecmis) == 2 and any("'roller' boş" in x for x in gecmis[0]["hatalar"]) and gecmis[1]["hatalar"] == []
    assert "S1: 3D niyetinde 'roller' boş" in sg.istemler[1]           # hata bir sonraki isteme girer
    assert all(ou.ROL_KURALI in i and ou.kanca_kurali() in i for i in sg.istemler)
    assert sen["cumleler"][0]["niyet"]["roller"] == ROL


# ================================================================== prompt kuralları

def test_prompt_3d_rol_kurali_acik_ve_ornekli():
    k = ou.konu_kur(PILOT, "Otlukbeli Savaşı", "shorts")
    p = ou.gorsel_kurallari(k, [])
    assert ou.ROL_KURALI in p
    for parca in ("3D ROL (zorunlu)", "'roller' boş olamaz", "'rol'", "Osmanlı süvarileri", '"rol": "suvari"',
                  '"donem": "osmanli-15yy"', "Akkoyunlu okçuları", '"rol": "okcu"', '"donem": "akkoyunlu-15yy"'):
        assert parca in ou.ROL_KURALI, parca


def test_ornek_roller_pilotun_gercek_rol_ve_donem_sozlugunden():
    pilot = json.loads((PILOT / "senaryo.json").read_text())
    roller = [r for c in pilot["cumleler"] for r in c["niyet"].get("roller") or []]
    assert {"suvari", "okcu"} <= {r["rol"] for r in roller}
    assert {"osmanli-15yy", "akkoyunlu-15yy"} <= {r.get("donem") for r in roller}
    assert ("okcu", "akkoyunlu-15yy") in {(r["rol"], r.get("donem")) for r in roller}


def test_prompt_kanca_kurali_4_5_kelime_ve_1_7_sn():
    ust = float(veri.kural("shorts")["kanca"]["en_cok_sure_sn"])
    assert ust == 2.0 and ou.KANCA_HEDEF_SN == 1.7 < ust                  # korunan üst sınır değişmedi
    kural = ou.kanca_kurali()
    for parca in ("KANCA (ilk cümle)", "EN FAZLA 4–5 kelime", "1.7 saniyenin ALTINDA", "üst sınır 2.0 sn"):
        assert parca in kural, parca
    p = ou.gorsel_kurallari(ou.konu_kur(PILOT, "Otlukbeli Savaşı", "shorts"), [])
    assert kural in p and "4–6 kelime" not in p                           # eski gevşek ipucu kaldırıldı


def test_kanca_hedefi_ust_sinirdan_buyuk_olamaz(monkeypatch):
    gercek = veri.kural

    def sahte(ad):
        k = gercek(ad)
        return dict(k, kanca=dict(k["kanca"], en_cok_sure_sn=1.5)) if ad == "shorts" else k

    monkeypatch.setattr(veri, "kural", sahte)
    assert "1.5 saniyenin ALTINDA" in ou.kanca_kurali() and "üst sınır 1.5 sn" in ou.kanca_kurali()


def test_kanca_suresi_asilinca_somut_kisaltma_yonu_geri_beslenir(kapilar, monkeypatch):
    from motor.uretim import anlati
    msj = "kanca seslendirmesi 2.03 sn sürüyor (ölçülen); en çok 2.0 sn"
    monkeypatch.setattr(anlati, "shorts_denetle", lambda s, sr: ([msj], {}))
    h = ou.senaryo_denetle(_gecerli(), {}, kapilar, [], _olc)
    assert h[0] == msj and any("4–5 kelime" in x and "1.7 sn" in x for x in h[1:])
    monkeypatch.setattr(anlati, "shorts_denetle", lambda s, sr: (["başka anlatı hatası"], {}))
    assert ou.senaryo_denetle(_gecerli(), {}, kapilar, [], _olc) == ["başka anlatı hatası"]


def test_kok_neden_rolsuz_niyet_planlayicida_oyuncu_uretmez():
    """Kapının neden gerektiği: planlayıcı oyuncuyu yalnız 'roller'dan kurar; rolsüz niyet sessizce boş kalır
    (eksik bile raporlanmaz) ve çekim kamera/ortam almaz (Faz-64b'de yakalanan durum)."""
    from motor.uretim import planlayici
    assert planlayici.oyuncu_sec({"tur": "3d", "eylem": "hucum", "aciklama": "süvari hücumu"}, "osmanli-15yy") == ([], [])
