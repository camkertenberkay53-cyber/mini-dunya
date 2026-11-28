"""Faz-64e — 3D niyetinde geçerli oyuncu rolü kataloğu.

Planlayıcı oyuncuyu planlayici.oyuncu_sec → secici.sec(rol, dönem, mesafe, eylem, nesne) ile kurar: rol derlenmiş
takımların 'rol' alanıyla, dönem takımın kit dönemiyle eşleşmeli; eylemin animasyonu o karaktere izinli, kalite sınıfı
o mesafede kullanılabilir olmalı. Rol adı dolu ama bu koşullardan biri tutmuyorsa çekim kamerasız/ortamsız kalıyordu
(gerçek koşu: 'S5: 3D çekim kuruldu — kamera/ortam yok').

- Katalog (prompt) ve kapı AYNI fonksiyonu (planlayici.oyuncu_sec) çağırır; kapı plan ile aynı varsayılan dönemi kullanır.
- Yalnız harf/aksan/büyük-küçük farkı olan adlar eşlenir; eş anlamlı uydurulmaz ('sipahi' → 'suvari' yapılmaz).
Gerçek planlayıcı testleri varlık önbelleği yoksa atlanır."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from motor.uretim import planlayici, veri

KOK = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("otonom_uret_64e", KOK / "otonom_uret.py")
ou = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ou)
PILOTLAR = KOK / "motor/uretim/pilotlar"
PILOT = PILOTLAR / "otlukbeli-1473"


def _onbellek_var() -> bool:
    try:
        return bool(veri.kitler()) and bool(veri.takimlar())
    except Exception:   # noqa: BLE001
        return False


ONBELLEK = pytest.mark.skipif(not _onbellek_var(), reason="varlık önbelleği yok (gerçek planlayıcı testi)")


def _konu():
    return ou.konu_kur(PILOT, "Otlukbeli Savaşı", "shorts")   # donemler: osmanli-15yy, akkoyunlu-15yy


def _c(i, roller, eylem="yuruyus", mesafe="orta", tur="3d", **n):
    return {"id": f"S{i}", "metin": "m", "kartlar": ["C1"],
            "niyet": {"tur": tur, "eylem": eylem, "mesafe": mesafe, "roller": roller, **n}}


# ------------------------------------------------------------------ sahte planlayıcı (önbelleksiz birim testleri)
SAHTE = {("osmanli-15yy", "suvari"): {"yuruyus", "bekleme"}, ("osmanli-15yy", "okcu"): {"yuruyus"},
         ("akkoyunlu-15yy", "suvari"): {"suvari_hucum", "yuruyus"}, ("bizans-15yy", "piyade"): {"yuruyus"}}


@pytest.fixture
def sahte_planlayici(monkeypatch):
    monkeypatch.setattr(ou, "_odak_uyumu", lambda n, d, k=None: (True, ""))   # Faz-66c: gerçek uyum test_faz66c'de
    monkeypatch.setattr(ou, "EN_AZ_3D_CUMLE", 0)   # Faz-66c: en az 3 ayrı 3D cümle kuralı test_faz66c'de
    cagrilar = []

    def oyuncu_sec(niyet, donem):
        cagrilar.append((niyet, donem))
        r = niyet["roller"][0]
        rd = r.get("donem") or donem
        if niyet.get("eylem") in SAHTE.get((rd, r["rol"]), set()):
            return [{"takim": f"{rd}_{r['rol']}", "animasyon": "a", "rol": r["rol"], "odak": True}], []
        return [], [f"{rd} döneminde {niyet.get('mesafe')} planda '{r['rol']}' rolü, '{niyet.get('eylem')}' eylemi için "
                    "uygun karakter yok"]

    monkeypatch.setattr(planlayici, "oyuncu_sec", oyuncu_sec)
    monkeypatch.setattr(veri, "takimlar", lambda: {f"t{i}": {"rol": r} for i, r in enumerate(["suvari", "okcu", "piyade"])})
    monkeypatch.setattr(ou, "_eylemler", lambda: ["bekleme", "suvari_hucum", "yuruyus"])
    return cagrilar


# ================================================================== katalog ve prompt

def test_katalog_planlayicidan_olculur_yalniz_konu_donemleri(sahte_planlayici):
    kat = ou.rol_katalogu(_konu())
    assert kat == {"osmanli-15yy": {"okcu": ["yuruyus"], "suvari": ["bekleme", "yuruyus"]},
                   "akkoyunlu-15yy": {"suvari": ["suvari_hucum", "yuruyus"]}}            # bizans: konuda yok; piyade: kurulamıyor
    assert {m for n, _ in sahte_planlayici for m in [n["mesafe"]]} == set(ou.KATALOG_MESAFELERI)


def test_katalog_kurali_tam_liste_ve_bos_katalog(sahte_planlayici):
    k = ou.rol_katalogu_kurali(ou.rol_katalogu(_konu()))
    assert k.startswith("3D ROL KATALOĞU (TAM LİSTE; yalnız bunlar oyuncuya dönüşür")
    assert "- donem 'osmanli-15yy', rol 'suvari': eylem ∈ {bekleme, yuruyus}" in k
    assert "- donem 'osmanli-15yy', rol 'okcu': eylem ∈ {yuruyus}" in k
    assert "- donem 'akkoyunlu-15yy', rol 'suvari': eylem ∈ {suvari_hucum, yuruyus}" in k
    assert "piyade" not in k and len(k.splitlines()) == 4
    assert "listede olmayan rol, dönem ya da rol-eylem eşleşmesi YAZMA" in k and "dönem kimliğini aynen yaz" in k
    assert "'3d' niyeti KULLANMA" in ou.rol_katalogu_kurali({})


def test_shorts_promptu_katalogu_tasir(sahte_planlayici):
    p = ou.gorsel_kurallari(_konu(), [])
    assert ou.rol_katalogu_kurali(ou.rol_katalogu(_konu())) in p and ou.ROL_KURALI in p


# ================================================================== kapı: her rol öğesi oyuncuya dönüşmeli

def test_gecerli_roller_gecer_planlayiciya_plan_ile_ayni_donem_verilir(sahte_planlayici):
    s = {"cumleler": [_c(1, [{"rol": "suvari"}, {"rol": "suvari", "donem": "akkoyunlu-15yy"}]),
                      _c(2, [{"rol": "okcu"}], tur="harita"), _c(3, [], tur="3d")]}
    assert ou.oyuncu_hatalari(s, _konu()) == []                     # boş roller rol_hatalari'nın işi
    assert [(n["roller"], d) for n, d in sahte_planlayici] == [([{"rol": "suvari"}], "osmanli-15yy"),
                                                               ([{"rol": "suvari", "donem": "akkoyunlu-15yy"}],
                                                                "osmanli-15yy")]


def test_tanimsiz_rol_donem_ve_eylem_ayri_ipucuyla_raporlanir(sahte_planlayici):
    s = {"cumleler": [_c(4, [{"rol": "sipahi"}]),
                      _c(5, [{"rol": "suvari", "donem": "osmanli-15yy"}], eylem="suvari_hucum"),
                      _c(6, [{"rol": "suvari", "donem": "osmanli"}]),
                      _c(7, [{"rol": "suvari"}, {"rol": "piyade", "donem": "akkoyunlu-15yy"}])]}
    h = ou.oyuncu_hatalari(s, _konu())
    assert len(h) == 4
    assert h[0].startswith("S4: 3D roller[0] ('sipahi', osmanli-15yy) oyuncuya dönüşmüyor")
    assert "'osmanli-15yy' döneminde geçerli roller: ['okcu', 'suvari']" in h[0]
    assert h[1].startswith("S5: 3D roller[0] ('suvari', osmanli-15yy)") and "'suvari_hucum' eylemi" in h[1]
    assert "'osmanli-15yy' / 'suvari' için geçerli eylemler: bekleme, yuruyus" in h[1]
    assert "geçerli dönemler: ['akkoyunlu-15yy', 'osmanli-15yy']" in h[2]
    assert h[3].startswith("S7: 3D roller[1] ('piyade', akkoyunlu-15yy)")   # geçerli öğe raporlanmaz


def test_kapi_tanimsiz_rolu_tts_den_once_reddeder(sahte_planlayici, monkeypatch):
    from motor.uretim import anlati, sozlesme
    monkeypatch.setattr(sozlesme, "senaryo_denetle", lambda s, a: [])
    monkeypatch.setattr(anlati, "shorts_denetle", lambda s, sr: ([], {}))
    monkeypatch.setattr(ou, "EN_AZ_GORSEL", {"shorts": 0, "uzun": 0})
    k = dict(_konu(), hedef_sure_sn=[1, 100])
    s = {"format": "shorts", "cumleler": [_c(1, [{"rol": "suvari"}], mesafe="orta"),
                                          _c(2, [{"rol": "sipahi"}], mesafe="uzak"), _c(3, None, tur="harita", evre="E1")]}
    h = ou.senaryo_denetle(s, {}, k, [], lambda cs: pytest.fail("rol hatasında TTS ölçülmemeli"))
    assert any(x.startswith("S2: 3D roller[0] ('sipahi'") for x in h)


def test_tanimsiz_rol_geri_beslenir_sonraki_denemede_gecer(sahte_planlayici, monkeypatch):
    from motor.uretim import anlati, sozlesme
    monkeypatch.setattr(sozlesme, "senaryo_denetle", lambda s, a: [])
    monkeypatch.setattr(anlati, "shorts_denetle", lambda s, sr: ([], {}))
    monkeypatch.setattr(ou, "EN_AZ_GORSEL", {"shorts": 0, "uzun": 0})
    monkeypatch.setattr(ou, "_shorts_3d_esik", lambda: (0, 2))
    k = dict(_konu(), hedef_sure_sn=[1, 100])

    def sen(rol):
        return {"cumleler": [_c(1, [{"rol": rol}], mesafe="orta"), _c(2, [{"rol": "okcu"}], mesafe="uzak")]}

    class Sahte:
        def __init__(self):
            self.yanitlar, self.istemler = [json.dumps(sen("sipahi")), json.dumps(sen("suvari"))], []

        def tamamla(self, istem, adim, baglam):
            self.istemler.append(istem)
            return self.yanitlar.pop(0)

    sg = Sahte()
    olc = lambda cs: {c["id"]: {"sure_sn": 6.0, "harf_sn": 14, "motor": "s", "wav": "x"} for c in cs}
    s, gecmis = ou.senaryo_uret(sg, k, {"kartlar": []}, [], olc=olc)
    assert len(gecmis) == 2 and "S1: 3D roller[0] ('sipahi'" in sg.istemler[1] and s["cumleler"][0]["niyet"]["roller"][0]["rol"] == "suvari"


# ================================================================== güvenli ad eşleme (uydurma yok)

def test_aksanli_rol_adi_senaryo_uretiminde_eslenir_ilk_denemede_gecer(sahte_planlayici, monkeypatch):
    from motor.uretim import anlati, sozlesme
    monkeypatch.setattr(sozlesme, "senaryo_denetle", lambda s, a: [])
    monkeypatch.setattr(anlati, "shorts_denetle", lambda s, sr: ([], {}))
    monkeypatch.setattr(ou, "EN_AZ_GORSEL", {"shorts": 0, "uzun": 0})
    monkeypatch.setattr(ou, "_shorts_3d_esik", lambda: (0, 2))
    sen = {"cumleler": [_c(1, [{"rol": "Süvari", "donem": "Osmanlı-15yy"}], mesafe="orta"),
                        _c(2, [{"rol": "Okçu"}], mesafe="uzak")]}

    class Sahte:
        def tamamla(self, istem, adim, baglam):
            return json.dumps(sen)

    olc = lambda cs: {c["id"]: {"sure_sn": 6.0, "harf_sn": 14, "motor": "s", "wav": "x"} for c in cs}
    s, gecmis = ou.senaryo_uret(Sahte(), dict(_konu(), hedef_sure_sn=[1, 100]), {"kartlar": []}, [], olc=olc)
    assert len(gecmis) == 1 and gecmis[0]["hatalar"] == []
    assert [c["niyet"]["roller"] for c in s["cumleler"]] == [[{"rol": "suvari", "donem": "osmanli-15yy"}], [{"rol": "okcu"}]]


def test_yalniz_harf_aksan_farki_eslenir(sahte_planlayici):
    s = {"cumleler": [_c(1, [{"rol": "Süvari", "donem": "Osmanlı-15yy"}, {"rol": "OKÇU"}, {"rol": "sipahi"},
                             {"rol": "suvari", "donem": "osmanli"}]),
                      _c(2, [{"rol": "Süvari"}], tur="harita")]}
    yapilan = ou.rol_adlarini_esle(s, _konu())
    r = s["cumleler"][0]["niyet"]["roller"]
    assert r == [{"rol": "suvari", "donem": "osmanli-15yy"}, {"rol": "okcu"}, {"rol": "sipahi"},
                 {"rol": "suvari", "donem": "osmanli"}]                        # sipahi/osmanli uydurulmadı
    assert s["cumleler"][1]["niyet"]["roller"] == [{"rol": "Süvari"}]         # 3D dışı dokunulmaz
    assert yapilan == ["S1: rol 'Süvari' → 'suvari'", "S1: donem 'Osmanlı-15yy' → 'osmanli-15yy'",
                       "S1: rol 'OKÇU' → 'okcu'"]
    assert ou.rol_adlarini_esle(s, _konu()) == []                             # idempotent


def test_katla():
    assert [ou._katla(x) for x in ("Süvari", "OKÇU", "İşçi Sivil", "Osmanlı-15yy", "ışık")] == \
        ["suvari", "okcu", "isci_sivil", "osmanli-15yy", "isik"]


# ================================================================== gerçek planlayıcı (önbellek gerekir)

@ONBELLEK
def test_gercek_kosudaki_hata_kapida_yakalanir():
    """Rol adı geçerli ama bu dönemde atlı hücum animasyonu kurulamıyor: plan değil senaryo kapısı yakalar."""
    k = _konu()
    s = {"cumleler": [_c(5, [{"rol": "suvari", "donem": "osmanli-15yy"}], eylem="suvari_hucum")]}
    assert planlayici.oyuncu_sec(s["cumleler"][0]["niyet"], "osmanli-15yy")[0] == []
    h = ou.oyuncu_hatalari(s, k)
    assert len(h) == 1 and h[0].startswith("S5: 3D roller[0] ('suvari', osmanli-15yy) oyuncuya dönüşmüyor")
    assert "'osmanli-15yy' / 'suvari' için geçerli eylemler:" in h[0]
    akk = {"cumleler": [_c(5, [{"rol": "suvari", "donem": "akkoyunlu-15yy"}], eylem="suvari_hucum")]}
    assert ou.oyuncu_hatalari(akk, k) == []


@ONBELLEK
def test_katalog_ile_planlayici_birebir_uyumlu():
    k = _konu()
    kat = ou.rol_katalogu(k)
    roller = sorted({t["rol"] for t in veri.takimlar().values()})
    assert set(kat) == set(k["donemler"])
    for d in k["donemler"]:
        for r in roller:
            for e in ou._eylemler():
                for m in ou.KATALOG_MESAFELERI:
                    n = {"tur": "3d", "eylem": e, "mesafe": m, "roller": [{"rol": r, "donem": d}]}
                    kurulur = bool(planlayici.oyuncu_sec(n, d)[0])
                    assert (ou.oyuncu_hatalari({"cumleler": [{"id": "S1", "niyet": n}]}, k, kat) == []) is kurulur
                    if kurulur:
                        assert e in kat[d][r]


@ONBELLEK
def test_bilinmeyen_rol_gercek_katalogla_raporlanir():
    h = ou.oyuncu_hatalari({"cumleler": [_c(3, [{"rol": "sipahi"}])]}, _konu())
    assert len(h) == 1 and "'osmanli-15yy' döneminde geçerli roller:" in h[0] and "'suvari'" in h[0]


@ONBELLEK
@pytest.mark.parametrize("pilot", sorted(p.name for p in PILOTLAR.iterdir()))
def test_pilot_ve_uzun_katalog_niyetleri_oyuncuya_donusur(pilot):
    """Uzun biçimde Gemini rol yazmaz, 3D niyeti pilot kataloğundan aynen gelir: o niyetler de kapıyı geçer."""
    k = ou.konu_kur(PILOTLAR / pilot, "x", "shorts")
    s = json.loads((PILOTLAR / pilot / "senaryo.json").read_text())
    assert ou.oyuncu_hatalari(s, k) == []
    kat = ou._sablon_katalog(PILOTLAR / pilot)
    assert kat and ou.oyuncu_hatalari({"cumleler": [{"id": x["katalog"], "niyet": x["niyet"]} for x in kat]}, k) == []
