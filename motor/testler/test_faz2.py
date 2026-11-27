"""Faz 2 kabul testleri. Çalıştırma: python3 -m pytest motor/testler -q
Önkoşul: kaynak depolar MOTOR_KAYNAK altında, `python3 -m motor.varlik.denetim` çalıştırılmış."""
import json
from pathlib import Path

import pytest

from motor import ayar
from motor.kit import dogrula
from motor.varlik import derle, katalog

KIT = dogrula.KIT_KLASORU


@pytest.fixture(scope="module")
def denetim():
    return json.loads(ayar.DENETIM_RAPOR.read_text())


def test_kayit_tutarli_ve_lisansli():
    k = katalog.yukle()
    assert katalog.dogrula(k) == []
    assert all(v["lisans"] == "CC0-1.0" and len(v["sha256"]) == 64 for v in k["varliklar"])


def test_dislanan_varlik_tarife_giremez():
    k = katalog.yukle()
    dis = next(v for v in k["varliklar"] if v["durum"] == "dislandi")
    with pytest.raises(SystemExit):
        derle.coz("x", {"kiyafet": dis["id"], "animasyonlar": []}, k)


def test_derleme_tekrarlanabilir():
    once = json.loads(derle.OZET.read_text())["koylu_erkek"]["glb_sha256"]
    derle.derle(["koylu_erkek"], zorla=True)
    assert json.loads(derle.OZET.read_text())["koylu_erkek"]["glb_sha256"] == once


def test_gercek_oranli_karakterler_evrensel_iskelette(denetim):
    for ad in ("korucu_erkek", "koylu_erkek", "korucu_kadin", "koylu_kadin"):
        o = denetim[ad]["olcum"]
        assert denetim[ad]["seviye"] in ("A", "B"), ad
        assert o["evrensel_iskelet_eslesen"] == 65
        assert 1.5 <= o["boy_m"] <= 2.05


def test_chibi_ve_stilize_reddedilir(denetim):
    for ad in ("test_chibi_sovalye", "stilize_asker", "stilize_viking", "stilize_sovalye", "stilize_kimono"):
        assert denetim[ad]["seviye"] == "C", ad


def test_renk_kopyasi_kit_ayrismasina_takilir():
    r = dogrula.dogrula([KIT / "test/fantastik_a.yaml", KIT / "test/fantastik_b_renk.yaml"], min_varyant=1, zorunlu=("piyade",))
    assert any("AYRIŞMIYOR" in h for h in r["fantastik_b_renk"]["hatalar"])


def test_renk_kopyasi_ayri_varyant_sayilmaz():
    r = dogrula.dogrula([KIT / "test/fantastik_b_renk.yaml"], min_varyant=2, zorunlu=("piyade",))
    assert any("1 ayrışan varyant" in h for h in r["fantastik_b_renk"]["hatalar"])


def test_yanlis_donem_ve_chibi_kite_giremez():
    r = dogrula.dogrula([KIT / "test/osmanli_yanlis.yaml"], min_varyant=1, zorunlu=("piyade",))["osmanli_yanlis"]
    assert any("DÖNEM DIŞI" in h for h in r["hatalar"])
    assert any("C seviyesi" in h for h in r["hatalar"])
    assert r["durum"] == "KULLANILAMAZ"


def test_bos_kitler_kullanilamaz_raporlanir():
    r = dogrula.dogrula(sorted(KIT.glob("*.yaml")))
    assert len(r) == 4
    assert all(s["durum"] == "KULLANILAMAZ" and any("BOŞ ROL" in h for h in s["hatalar"]) for s in r.values())
