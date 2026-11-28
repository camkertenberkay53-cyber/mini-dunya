"""Faz-66b — Shorts senaryo geri beslemesinde 3D sahne koruması ve yerel düzeltme (offline).

Gerçek koşu (Mohaç): 2. denemede 'suvari + uzak + suvari_yuruyus' kurulamadı; 3. denemede Gemini bütün 3D sahneleri
sildi ve 3D mesafe çeşitliliği kapısına takıldı. Kök neden: düzeltme turu önceki senaryoyu görmüyordu (yalnız hata
listesi), 3D silmek yasak değildi ve hata mesajları ("cümle çıkar") silmeye açıktı.
Doğrulayıcı kuralları ve eşikleri DEĞİŞMEDİ; yalnız istem ve geri besleme metni."""
from __future__ import annotations

import copy
import importlib.util
import inspect
import json
from pathlib import Path

import pytest

KOK = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("otonom_uret_66b", KOK / "otonom_uret.py")
ou = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ou)
PILOT = KOK / "motor/uretim/pilotlar/otlukbeli-1473"
ROL = [{"rol": "suvari", "donem": "osmanli-15yy", "adet": 6}]


def _c(i, tur="3d", **n):
    if tur == "3d":
        n.setdefault("roller", copy.deepcopy(ROL))
    return {"id": f"S{i}", "metin": f"cümle {i}", "amac": "olay", "kartlar": ["C1"], "niyet": {"tur": tur, **n}}


def _senaryo(eylem5="yuruyus"):
    return {"format": "shorts", "cumleler": [_c(1, "harita", evre="E1", metin="Dizilış"),
                                             _c(2, eylem="yuruyus", mesafe="orta"),
                                             _c(3, eylem="bekleme", mesafe="uzak"),
                                             _c(4, "harita", evre="E2", metin="Çarpışma"),
                                             _c(5, eylem=eylem5, mesafe="uzak")]}


HATA_S5 = ("S5: 3D roller[0] ('suvari', osmanli-15yy) oyuncuya dönüşmüyor — osmanli-15yy döneminde uzak planda "
           "'suvari' rolü, 'suvari_yuruyus' eylemi için uygun karakter yok")


# ================================================================== istem kuralları

def test_ilk_tur_istemi_degismez_kural_yalniz_duzeltme_turunda():
    assert ou.geri_besleme_kurali([], _senaryo()) == ""


def test_geri_besleme_3d_silmeyi_azaltmayi_donusturmeyi_yasaklar():
    g = ou.geri_besleme_kurali([HATA_S5], None)
    for parca in ("3D cümleleri SİLMEK", "3D cümle sayısını AZALTMAK", "2.5D/harita cümlesine ÇEVİRMEK", "YASAKTIR",
                  "sahne SİLİNMEZ", "UYDURMA", "senaryoyu baştan yazma", "zorunlu sayıları azaltarak çözme"):
        assert parca in g, parca


def test_min_orta_uzak_mesafe_sarti_istem_ve_geri_beslemede_korunur():
    en_az_3d, en_az_mesafe = ou._shorts_3d_esik()
    g = ou.geri_besleme_kurali([HATA_S5], None)
    assert (f"en az {en_az_3d} 3D çekim; 3D cümlelerde en az {en_az_mesafe} farklı 'mesafe' — en az biri 'orta', "
            "en az biri 'uzak'") in g
    p = ou.gorsel_kurallari(ou.konu_kur(PILOT, "Otlukbeli Savaşı", "shorts"), [])
    assert "(en az biri 'orta', biri 'uzak')" in p and "Bu şart her düzeltme turunda da geçerlidir." in p
    assert en_az_mesafe >= 2 and en_az_3d >= 4                                            # eşikler gevşemedi


def test_yerel_duzeltme_sirasi_once_ortaya_cek_sonra_katalog_eylemi():
    g = ou.geri_besleme_kurali([HATA_S5], None)
    i_orta = g.index("önce 'mesafe'yi 'orta' yap")
    i_eylem = g.index("aynı dönem ve rol için 3D ROL KATALOĞU'ndaki")
    assert i_orta < i_eylem and "son 'uzak' 3D cümleyse 'uzak' kalsın" in g
    assert "tarihî anlatı amacını (metin, kartlar, amac) koru" in g


def test_onceki_senaryo_temel_alinir_hatali_cumle_ve_korunacaklar_ayrilir():
    g = ou.geri_besleme_kurali([HATA_S5], _senaryo("suvari_yuruyus"))
    assert "Önceki turda 3 3D cümle vardı (S2: orta, S3: uzak, S5: uzak); bu tur en az 3 3D cümle kalır." in g
    assert "DÜZELTİLECEK cümleler: S5. KORUNACAK cümleler (aynen): S1, S2, S3, S4." in g
    js = json.loads(g.split("ÖNCEKİ SENARYO (temel al; yalnız düzeltilecek cümleleri değiştir):\n", 1)[1])
    assert [c["id"] for c in js["cumleler"]] == ["S1", "S2", "S3", "S4", "S5"]
    assert js["cumleler"][4]["niyet"]["eylem"] == "suvari_yuruyus" and js["cumleler"][1]["niyet"]["mesafe"] == "orta"


@pytest.mark.parametrize("hata,beklenen", [
    (HATA_S5, ["S5"]),
    ("ÇEKİM PLANI KAPISI (uyum): S3a 3D çekim kuruldu — kamera/ortam yok", ["S3"]),
    ("S10: x; S2: y", ["S2", "S10"]),
    ("3D cümlelerde 0 farklı mesafe (-)", []),
    ("Sultan S kelimesi, SS12 değil", []),
])
def test_hatali_cumleler(hata, beklenen):
    assert ou.hatali_cumleler([hata]) == beklenen


# ================================================================== hata mesajları silmeye değil düzeltmeye yönlendirir

@pytest.fixture
def kapilar(monkeypatch):
    monkeypatch.setattr(ou, "EN_AZ_3D_CUMLE", 0)   # Faz-66c: en az 3 ayrı 3D cümle kuralı test_faz66c'de
    from motor.uretim import anlati, sozlesme
    monkeypatch.setattr(sozlesme, "senaryo_denetle", lambda s, a: [])
    monkeypatch.setattr(anlati, "shorts_denetle", lambda s, sr: ([], {}))
    monkeypatch.setattr(ou, "EN_AZ_GORSEL", {"shorts": 0, "uzun": 0})
    monkeypatch.setattr(ou, "oyuncu_hatalari", lambda s, k, kat=None: [
        f"{c['id']}: 3D roller[0] ('suvari', osmanli-15yy) oyuncuya dönüşmüyor{ou.YEREL_DUZELTME}"
        for c in s["cumleler"] if c["niyet"].get("eylem") == "suvari_yuruyus"])
    return dict(ou.konu_kur(PILOT, "Otlukbeli Savaşı", "shorts"), hedef_sure_sn=[1, 100])


def _olc(cs):
    return {c["id"]: {"sure_sn": 6.0 if c["niyet"]["tur"] == "3d" else 4.0, "harf_sn": 14, "motor": "s", "wav": "x"}
            for c in cs}


def test_mesafe_cesitliligi_hatasi_silme_yasagini_tasir(kapilar):
    s = _senaryo()
    for c in s["cumleler"]:
        if c["niyet"]["tur"] == "3d":
            c["niyet"] = {"tur": "harita", "evre": "E3", "metin": c["id"]}
    h = ou.senaryo_denetle(s, {}, kapilar, [], _olc)
    m = next(x for x in h if "farklı mesafe" in x)
    assert m.startswith("3D cümlelerde 0 farklı mesafe (-); çeşitlilik için en az 2 (en az biri 'orta', biri 'uzak')")
    assert m.endswith(ou.SILME_YASAGI) and "3D cümleleri silme" in m


def test_sure_fazlaysa_3d_cumle_silinmesi_onerilmez(kapilar):
    h = ou.senaryo_denetle(_senaryo(), {}, dict(kapilar, hedef_sure_sn=[1, 5]), [], _olc)
    assert h and "3D olmayan bir cümle çıkar (3D cümleleri silme)" in h[0]


def test_az_3d_cekim_hatasi_silme_yasagini_tasir(kapilar, monkeypatch):
    from motor.uretim import sahne_bolucu
    monkeypatch.setattr(sahne_bolucu, "cekimlere_bol", lambda s, cz, havuz=None: [{"niyet": {"tur": "3d"}}])
    h = ou.senaryo_denetle(_senaryo(), {}, kapilar, [], _olc)
    assert h[0].startswith("1 3D çekim") and h[0].endswith(ou.SILME_YASAGI)


# ================================================================== senaryo üretimi: yerel düzeltme ve 3D koruma

class Sahte:
    def __init__(self, yanitlar):
        self.yanitlar, self.istemler = [json.dumps(y) for y in yanitlar], []

    def tamamla(self, istem, adim, baglam):
        self.istemler.append(istem)
        return self.yanitlar.pop(0)


def test_duzeltme_turu_onceki_senaryoyu_ve_hatali_cumleyi_verir(kapilar):
    sg = Sahte([_senaryo("suvari_yuruyus"), _senaryo("yuruyus")])
    s, gecmis = ou.senaryo_uret(sg, kapilar, {"kartlar": []}, [], olc=_olc)
    assert len(gecmis) == 2 and gecmis[1]["hatalar"] == []
    assert "GERİ BESLEME KURALLARI" not in sg.istemler[0]                                  # ilk istem aynı kaldı
    ikinci = sg.istemler[1]
    assert "GERİ BESLEME KURALLARI (zorunlu):" in ikinci and "DÜZELTİLECEK cümleler: S5." in ikinci
    assert '"eylem": "suvari_yuruyus"' in ikinci and "Önceki turda 3 3D cümle vardı" in ikinci
    assert ou._uc_d_sayisi(s) == 3


def test_3d_silen_tur_referans_olmaz_sonraki_tur_zengin_senaryoyu_gorur(kapilar):
    silinmis = _senaryo()
    silinmis["cumleler"] = [c for c in silinmis["cumleler"] if c["niyet"]["tur"] != "3d"]
    sg = Sahte([_senaryo("suvari_yuruyus"), silinmis, _senaryo("yuruyus")])
    s, gecmis = ou.senaryo_uret(sg, kapilar, {"kartlar": []}, [], olc=_olc)
    assert len(gecmis) == 3 and any("farklı mesafe" in x for x in gecmis[1]["hatalar"])
    ucuncu = sg.istemler[2]
    assert "Önceki turda 3 3D cümle vardı (S2: orta, S3: uzak, S5: uzak); bu tur en az 3 3D cümle kalır." in ucuncu
    assert ou.SILME_YASAGI in ucuncu                                                        # hata metni geri beslendi


def test_plan_kapisi_geri_beslemesinde_onceki_senaryo_verilir(tmp_path, monkeypatch):
    cagri = []

    def sahte_senaryo_uret(g, k, ara, gorseller, olc=None, ilk_hatalar=None, onceki=None):
        cagri.append({"ilk_hatalar": list(ilk_hatalar or []), "onceki": onceki})
        return dict(_senaryo(), konu=k["kimlik"], surum=1), [{"deneme": 1, "hatalar": []}]

    tur = {"n": 0}

    def sahte_planla(is_):
        tur["n"] += 1
        (is_ / "cekim_plani.json").write_text(json.dumps({"konu": "t", "cekimler": [
            {"id": "S2", "tur": "3d", "sure_sn": 4.0, "cumleler": ["S2"]}]}))
        if tur["n"] == 1:
            return {"gecti": False, "hatalar": {"uyum": ["S5 3D çekim kuruldu — kamera/ortam yok"]}}
        return {"gecti": True, "hatalar": {}, "toplam_sure_sn": 50.0}

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
    assert len(cagri) == 2 and cagri[0]["onceki"] is None and cagri[0]["ilk_hatalar"] == []
    assert cagri[1]["onceki"]["cumleler"] == _senaryo()["cumleler"]
    assert cagri[1]["ilk_hatalar"] == ["ÇEKİM PLANI KAPISI (uyum): S5 3D çekim kuruldu — kamera/ortam yok"]


# ================================================================== mesafeye özgü katalog ve ipucu

@pytest.fixture
def mesafeli_planlayici(monkeypatch):
    """suvari: 'kosu' yalnız ortada, 'yuruyus' iki mesafede kurulur."""
    monkeypatch.setattr(ou, "_odak_uyumu", lambda n, d, k=None: (True, ""))   # Faz-66c: gerçek uyum test_faz66c'de
    from motor.uretim import planlayici, veri

    def sec(n, donem):
        r = n["roller"][0]
        e, m = n.get("eylem"), n.get("mesafe", "orta")
        ok = r.get("rol") == "suvari" and (e == "yuruyus" or (e == "kosu" and m == "orta"))
        return ([{"takim": "t", "rol": "suvari", "odak": True}] if ok else []), ([] if ok else ["uygun karakter yok"])

    monkeypatch.setattr(planlayici, "oyuncu_sec", sec)
    monkeypatch.setattr(veri, "takimlar", lambda: {"t": {"rol": "suvari"}})
    monkeypatch.setattr(ou, "_eylemler", lambda: ["kosu", "yuruyus"])
    return {"donemler": ["osmanli-15yy"]}


def test_katalog_yalniz_bir_mesafede_kurulan_eylemi_isaretler(mesafeli_planlayici):
    kat = ou.rol_katalogu(mesafeli_planlayici)
    kisit = ou.mesafe_kisitlari(mesafeli_planlayici, kat)
    assert kat == {"osmanli-15yy": {"suvari": ["kosu", "yuruyus"]}} and kisit == {("osmanli-15yy", "suvari", "kosu"): "orta"}
    k = ou.rol_katalogu_kurali(kat, kisit)
    assert "eylem ∈ {kosu (yalnız orta), yuruyus}" in k and "YALNIZ o 'mesafe' ile yazılır" in k
    assert "(yalnız orta)" not in ou.rol_katalogu_kurali(kat) and "YALNIZ o" not in ou.rol_katalogu_kurali(kat)


def test_uzakta_kurulamayan_eylem_icin_ortaya_cek_ipucu(mesafeli_planlayici):
    s = {"cumleler": [{"id": "S5", "niyet": {"tur": "3d", "eylem": "kosu", "mesafe": "uzak", "roller": [{"rol": "suvari"}]}}]}
    h = ou.oyuncu_hatalari(s, mesafeli_planlayici)
    assert len(h) == 1 and h[0].startswith("S5: 3D roller[0] ('suvari', osmanli-15yy) oyuncuya dönüşmüyor")
    assert "'kosu' 'uzak' mesafede kurulamıyor ama 'orta'da kuruluyor: SAHNEYİ SİLME — 'mesafe'yi 'orta' yap" in h[0]
    assert "'uzak' mesafede kurulan bir eylem seç: yuruyus" in h[0] and h[0].endswith(ou.YEREL_DUZELTME)


def test_hicbir_mesafede_kurulamayan_eylemde_yerel_duzeltme_yonu(mesafeli_planlayici):
    s = {"cumleler": [{"id": "S5", "niyet": {"tur": "3d", "eylem": "suvari_yuruyus", "mesafe": "uzak",
                                              "roller": [{"rol": "suvari"}]}}]}
    h = ou.oyuncu_hatalari(s, mesafeli_planlayici)
    assert "'osmanli-15yy' / 'suvari' için geçerli eylemler: kosu, yuruyus" in h[0]
    assert "'uzak' mesafede kurulanlar: yuruyus — sahneyi silme, eylemi değiştir" in h[0]
    assert "'orta'da kuruluyor" not in h[0] and h[0].endswith(ou.YEREL_DUZELTME)


# ================================================================== kapsam

def test_uzun_akis_geri_besleme_kuralini_kullanmaz():
    for f in (ou.uzun_senaryo_uret, ou.uzun_taslak_uret, ou.bolum_istemi):
        assert "geri_besleme_kurali" not in inspect.getsource(f)



def test_ilk_tur_istemi_faz66b_oncesi_bilesimle_ayni(kapilar):
    from motor.uretim import senaryo_uretici
    ara = {"kartlar": []}
    sg = Sahte([_senaryo()])
    ou.senaryo_uret(sg, kapilar, ara, [], olc=_olc)
    assert sg.istemler[0] == (senaryo_uretici.istem(kapilar, ara, []) + "\n" + ou.gorsel_kurallari(kapilar, []) + "\n"
                              + ou.kaynak_ihtiyati_kurali(ara, "shorts"))


def test_shorts_istemindeki_katalog_mesafe_kisitini_tasir(mesafeli_planlayici):
    p = ou.gorsel_kurallari(ou.konu_kur(PILOT, "Otlukbeli Savaşı", "shorts"), [])
    assert "- donem 'osmanli-15yy', rol 'suvari': eylem ∈ {kosu (yalnız orta), yuruyus}" in p
