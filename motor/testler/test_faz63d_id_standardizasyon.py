"""Faz-63d — Gemini cümle kimliği standardizasyonu (normalize_senaryo): c1/C1/s1/"12"/12 → S<n>; geçerli S<n>
öncelikli ve dokunulmaz; çakışanlar ve eksikler çakışmasız S<n>; bozuk biçimler dönüştürülmez; metin değişmez."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from motor.uretim import anlati, sozlesme, veri

KOK = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("otonom_uret_63d", KOK / "otonom_uret.py")
ou = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ou)
ARA = json.loads((KOK / "motor/uretim/pilotlar/otlukbeli-1473/arastirma.json").read_text())
EKSIK = object()


def _cs(ids):
    return [{"metin": f"Cümle {k}: Otlukbeli’de “ağır” toplar — {k}.", "kartlar": ["C1"],
             "niyet": {"tur": "3d", "aciklama": "x"}, **({} if i is EKSIK else {"id": i})} for k, i in enumerate(ids)]


def _ids(ids, **kw):
    return [c.get("id") for c in ou.normalize_senaryo({"cumleler": _cs(ids)}, **kw)["cumleler"]]


def _shorts(ids, **ek):
    return {"surum": 1, "konu": "k", "format": "shorts", "baslik": "B", "kanca": "x", "final": "y",
            "ana_fikir": "Toplar savaşın kaderini belirledi.", "cumleler": _cs(ids), **ek}


# ================================================================== dönüşümler

@pytest.mark.parametrize("girdi, beklenen", [
    ("s1", "S1"), ("c1", "S1"), ("c8", "S8"), ("C1", "S1"), ("C12", "S12"), ("s12", "S12"),
    ("12", "S12"), (12, "S12"), ("1", "S1"), (8, "S8"), (0, "S0"), ("c08", "S08"),
])
def test_tekil_donusum(girdi, beklenen):
    assert _ids([girdi]) == [beklenen]


def test_gercek_kosu_hatasi_c1_c8():
    """Gerçek koşudaki hata: cumleler/0/id: 'c1' does not match '^S[0-9]+$' (c1..c8)."""
    s = _shorts([f"c{i}" for i in range(1, 9)])
    assert any("'c1' does not match" in h for h in sozlesme.senaryo_denetle(s, ARA))
    n = ou.normalize_senaryo(s)
    assert [c["id"] for c in n["cumleler"]] == [f"S{i}" for i in range(1, 9)]
    assert (n["kanca"], n["final"]) == ("S1", "S8") and sozlesme.senaryo_denetle(n, ARA) == []


@pytest.mark.parametrize("girdi, beklenen", [
    (["S1", "S2", "S3"], ["S1", "S2", "S3"]),                    # aynen korunur
    (["s1", "s2"], ["S1", "S2"]), (["c1", "c2", "c8"], ["S1", "S2", "S8"]), (["C1", "C2"], ["S1", "S2"]),
    ([1, 2, 8], ["S1", "S2", "S8"]), (["1", "2", "8"], ["S1", "S2", "S8"]),
    (["c1", "S2", "s3", "4", 5, "C6"], ["S1", "S2", "S3", "S4", "S5", "S6"]),   # karışık büyük/küçük harf ve tür
])
def test_desteklenen_bicimler(girdi, beklenen):
    assert _ids(girdi) == beklenen


def test_gecerli_s_kimligi_hic_degismez():
    assert _ids(["S1", "S01", "S007", "S99"]) == ["S1", "S01", "S007", "S99"]


@pytest.mark.parametrize("bozuk", ["abc", "S-1", "", " s3", "s3 ", "s1a", "x7", "cc1", "S", "c", "Ş1", "c-1", "s 1",
                                   "-1", "+1", 1.5, -1, True, False, ["S1"], {"id": "S1"}, "１"])
def test_bozuk_kimlik_gelisiguzel_donusturulmez(bozuk):
    n = ou.normalize_senaryo({"cumleler": _cs([bozuk, "c2"])})
    assert n["cumleler"][0]["id"] == bozuk and n["cumleler"][1]["id"] == "S2"
    assert ou.id_adayi(bozuk) is None


def test_bozuk_kimlik_dogrulayicida_acik_hata():
    n = ou.normalize_senaryo(_shorts(["S-1", "c2"]))
    assert any("'S-1' does not match" in h for h in sozlesme.senaryo_denetle(n, ARA))


# ================================================================== çakışma yönetimi

@pytest.mark.parametrize("girdi, beklenen", [
    (["c1", "S1"], ["S2", "S1"]),                                # geçerli S1 sonra gelse de öncelikli
    (["c1", "s1", "C1", "1", 1], ["S1", "S2", "S3", "S4", "S5"]),  # aynı hedefe dönüşenler: ilki kazanır, sonrakiler boş
    (["S1", "s1", "S2", "c2"], ["S1", "S3", "S2", "S4"]),
    (["c3", "S3", "c1"], ["S2", "S3", "S1"]),                    # c1 → S1 serbest; c3 çakışır → en küçük boş S2
])
def test_ayni_kimlige_donusenler_cakismasiz_cozulur(girdi, beklenen):
    r = _ids(girdi)
    assert r == beklenen and len(set(r)) == len(r)


def test_eksik_kimlikler_mevcut_ve_donusen_kimliklerle_cakismaz():
    r = _ids([EKSIK, "c1", None, "S2", EKSIK, "c2"])
    # geçerli S2 ayrılır; c1→S1; c2 hedefi dolu → atanacak; eksikler + c2 liste sırasıyla en küçük boş: S3, S4, S5, S6
    assert r == ["S3", "S1", "S4", "S2", "S5", "S6"] and len(set(r)) == 6


def test_eksik_atama_mantigi_korunur_onceki_fazlarla_ayni():
    assert _ids([EKSIK, "S2", EKSIK, "S4", EKSIK]) == ["S1", "S2", "S3", "S4", "S5"]   # Faz-63 davranışı
    assert _ids([EKSIK, "s1"]) == ["S2", "S1"]                                          # Faz-63c davranışı


def test_belirlenimci_her_calismada_ayni():
    girdi = ["c3", EKSIK, "s1", "S1", "7", 7, "abc", None, "C2"]
    sonuc = {tuple(_ids(girdi)) for _ in range(20)}
    assert len(sonuc) == 1


# ================================================================== uyumluluk

@pytest.mark.parametrize("ids", [
    ["c1", "c2", "c8"], ["S1", "s1", "c1", EKSIK, "abc"], [1, "1", "c1"], ["S-1", "c1"], [EKSIK, EKSIK], ["S5"],
])
@pytest.mark.parametrize("kanca_final", [True, False])
def test_idempotent(ids, kanca_final):
    bir = ou.normalize_senaryo({"senaryo": _shorts(ids)}, kanca_final=kanca_final)
    assert ou.normalize_senaryo(copy.deepcopy(bir), kanca_final=kanca_final) == bir


def test_cumle_metinleri_ve_sirasi_degismez_bilinmeyen_alanlar_kalir():
    g = _shorts(["c2", "S1", EKSIK, "abc", 3], gemini_notu={"x": 1})
    for c in g["cumleler"]:
        c["ozel_alan"] = [1, 2]
    kopya = copy.deepcopy(g)
    n = ou.normalize_senaryo(g)
    assert g == kopya                                                            # girdi değişmez
    assert [c["metin"] for c in n["cumleler"]] == [c["metin"] for c in kopya["cumleler"]]
    assert [c["niyet"] for c in n["cumleler"]] == [c["niyet"] for c in kopya["cumleler"]]
    assert n["gemini_notu"] == {"x": 1} and all(c["ozel_alan"] == [1, 2] for c in n["cumleler"])


def test_kanca_final_normalize_kimliklerle_uyumlu():
    n = ou.normalize_senaryo(_shorts(["c1", "c2", "c3"], kanca="c1", final="Zafer metni"))
    assert (n["kanca"], n["final"]) == ("S1", "S3")
    n = ou.normalize_senaryo(_shorts(["c2", "S2"]))
    assert n["kanca"] == n["cumleler"][0]["id"] == "S1" and n["final"] == "S2"


def test_bozuk_ogede_kimlik_donusumu_yapilmaz():
    s = _shorts(["c1", "c2"])
    s["cumleler"].append({"id": "c3"})                                           # metin eksik
    n = ou.normalize_senaryo(s)
    assert [c.get("id") for c in n["cumleler"]] == ["c1", "c2", "c3"] and n["kanca"] == "x"


def test_shorts_ve_uzun_uyumlulugu():
    sh = ou.normalize_senaryo({"senaryo": _shorts(["c1", "c2", EKSIK])})
    assert sozlesme.senaryo_denetle(sh, ARA) == []
    roller = veri.kural("uzun")["bolum"]["roller"]
    bolumler = [{"id": f"B{i + 1}", "baslik": f"b{i}", "roller": [r]} for i, r in enumerate(roller[:7])]
    bolumler[-1]["roller"] = ["etkiler", "kapanis"]
    cs = [{"id": f"c{i + 1}", "metin": f"Belge {i} anlatımı " + " ".join(f"k{i}x{j}" for j in range(8)),
           "kartlar": ["C1"], "bolum": f"B{i // 6 + 1}", "niyet": {"tur": "3d", "aciklama": "x"}} for i in range(42)]
    cs[0]["metin"] = "Yalnızca 1 gün süren savaş neyi değiştirdi?"
    uz = ou.normalize_senaryo({"surum": 1, "konu": "k", "format": "uzun", "baslik": "U", "bolumler": bolumler,
                               "cumleler": cs, "kanca": "c1", "final": "c42"})
    assert [c["id"] for c in uz["cumleler"]] == [f"S{i}" for i in range(1, 43)]
    assert sozlesme.senaryo_denetle(uz, ARA) == []
    h, _ = anlati.uzun_denetle(uz, {f"S{i}": {"sure_sn": 5.0} for i in range(1, 43)})
    assert not [x for x in h if "kanca ilk" in x or "final son" in x]
    bolum = ou.normalize_senaryo({"cumleler": _cs(["c1", EKSIK])}, kanca_final=False)    # uzun bölüm parçası
    assert [c["id"] for c in bolum["cumleler"]] == ["S1", "S2"] and "kanca" not in bolum


def test_otonom_shorts_akisi_c_kimlikleriyle_ilk_denemede_gecer(monkeypatch):
    monkeypatch.setattr(ou, "senaryo_denetle", lambda s, ara, *a, **k: sozlesme.senaryo_denetle(s, ara))

    class Sahte:
        cagri_sayisi = 0

        def tamamla(self, istem, adim, baglam):
            self.cagri_sayisi += 1
            return json.dumps(_shorts([f"c{i}" for i in range(1, 9)]), ensure_ascii=False)
    s = Sahte()
    pilot = KOK / "motor/uretim/pilotlar/otlukbeli-1473"
    sen, gecmis = ou.senaryo_uret(s, ou.konu_kur(pilot, "Otlukbeli Savaşı", "shorts"), ARA, [])
    assert s.cagri_sayisi == 1 and gecmis[0]["hatalar"] == [] and sen["cumleler"][7]["id"] == "S8"
