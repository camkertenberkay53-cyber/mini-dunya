"""Faz-62d — görsel çeşitliliği: (1) bir tarihî görsel dosyası bir videoda en çok bir kez (senaryo, planlayıcı, render
kapısı, Commons seçimi), (2) sahne konularından alt arama terimleri + CC-BY / CC-BY-SA (atıflı) lisans; NC/ND hayır,
(3) en az benzersiz görsel kapısı (Shorts 3, uzun 12) render'dan önce. Çevrimdışı; ağ ve Gemini YOK."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from motor.uretim import plan_denetim
from motor.varlik import commons_toplayici, tarihi_gorsel

KOK = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("otonom_uret_62d", KOK / "otonom_uret.py")
ou = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ou)
PILOT = KOK / "motor/uretim/pilotlar/otlukbeli-1473"
WF = KOK / ".github" / "workflows" / "belgesel_uret.yml"


class Sahte:
    def __init__(self, yanitlar):
        self.yanitlar, self.istemler, self.cagri_sayisi, self.kullanilan_model = list(yanitlar), [], 0, "sahte"

    def tamamla(self, istem, adim, baglam):
        self.istemler.append((adim, istem))
        self.cagri_sayisi += 1
        y = self.yanitlar.pop(0)
        return y if isinstance(y, str) else json.dumps(y, ensure_ascii=False)


def _kayit(i):
    return {"id": f"ark_{i}", "durum": "dogrulanmis", "iddia": f"iddia {i}", "bagimsiz_kaynak_sayisi": 2,
            "kaynaklar": [{"id": f"wp_{i}", "eser": "w", "url": "u", "tur": "ansiklopedi"},
                          {"id": f"tdv_{i}", "eser": "t", "url": "u", "tur": "ansiklopedi"}]}


TASLAK = {"baslik": "Otlukbeli", "bolumler": [
    {"baslik": b, "roller": r, "hedef_sn": 150} for b, r in (("Açılış", ["kanca", "baglam"]), ("Taraflar", ["taraflar"]),
                                                              ("Öncesi", ["savas_oncesi"]), ("Savaş", ["savas"]),
                                                              ("Sonuç", ["sonuc"]), ("Etkiler", ["etkiler"]),
                                                              ("Kapanış", ["kapanis"]))]}


def _metin(i: int, n: int = 16) -> str:
    return f"Belge {i} anlatımı " + " ".join(f"k{i}x{j}" for j in range(n - 3))


def _sorgular(n):
    return [{"gorsel_id": f"g{i}", "sorgu": f"q{i}", "aciklama": f"görsel {i}"} for i in range(n)]


def _topla(lisans="PD-Old", atif=None):
    def f(q, h):
        k = {"lisans_turu": lisans, "eser_adi": "p", "toplama": {"baslik": f"File:{q['gorsel_id']}.jpg"}, "sha256": q["gorsel_id"]}
        if atif:
            k["atif"] = atif
        return k
    return f


@pytest.fixture
def kapi(tmp_path, monkeypatch):
    monkeypatch.setattr(tarihi_gorsel, "dogrulanmis_dosya", lambda gid: (tmp_path / gid, {}))
    monkeypatch.setattr(ou, "GORSEL_KOK", tmp_path / "gorsel")
    return tmp_path


# ================================================================== 1) görsel tekrarı yasağı

def _plan_denetim_yalitik(monkeypatch):
    from motor.uretim import sozlesme, veri
    monkeypatch.setattr(sozlesme, "sema_hatalari", lambda t, b: [])
    monkeypatch.setattr(veri, "kitler", lambda: {"k": {"etiket": "d"}})
    monkeypatch.setattr(plan_denetim, "cekim_denetle", lambda c, d, e, ds: {"hatalar": [], "uyarilar": [], "olcum": {}})


@pytest.mark.parametrize("bicim", ["shorts", "uzun"])
def test_planlayici_ayni_gorseli_ikinci_cekime_atayamaz(monkeypatch, bicim):
    _plan_denetim_yalitik(monkeypatch)
    def c(i, gid):
        return {"id": f"S{i}", "tur": "gorsel25d", "cumleler": [f"S{i}"], "metin": f"farklı {i}", "gorsel25d": {"gorsel_id": gid}}
    plan = {"donem": "d", "donemler": ["d"], "cozunurluk": [1920, 1080] if bicim == "uzun" else [1080, 1920], "eksikler": [],
            "cekimler": [c(1, "a"), c(2, "b"), c(3, "a")], **({"format": "uzun"} if bicim == "uzun" else {})}
    r = plan_denetim.denetle(plan)
    assert not r["gecti"] and any("'a' görseli S1 çekiminde zaten kullanıldı" in h for h in r["hatalar"])
    plan["cekimler"][2] = c(3, "c")
    assert plan_denetim.denetle(plan)["gecti"]


def test_shorts_senaryosu_ayni_gorseli_iki_kez_kullanamaz(monkeypatch):
    from motor.uretim import sozlesme
    monkeypatch.setattr(sozlesme, "senaryo_denetle", lambda s, a: [])
    k = ou.konu_kur(PILOT, "Otlukbeli Savaşı", "shorts")
    g = [{"gorsel_id": f"g{i}", "aciklama": "x"} for i in range(3)]
    def cm(i, gid):
        return {"id": f"S{i}", "metin": "m", "kartlar": ["C1"], "niyet": {"tur": "gorsel25d", "gorsel25d": {"gorsel_id": gid},
                                                                       "aciklama": f"a{i}"}}
    h = ou.senaryo_denetle({"cumleler": [cm(1, "g0"), cm(2, "g1"), cm(3, "g0"), cm(4, "g2")]}, {}, k, g, lambda cs: {})
    assert any("aynı görsel birden fazla cümlede: ['g0']" in x for x in h)


def test_ayni_commons_dosyasi_iki_sorguyla_alinmaz(tmp_path, kapi):
    gorulen_haric = []
    def topla(q, h):
        gorulen_haric.append(list(q["haric"]))
        (h / f"{q['gorsel_id']}.jpg").write_bytes(b"x")
        baslik = "File:Bellini.jpg" if q["gorsel_id"].endswith(("-a", "-b")) else f"File:{q['gorsel_id']}.jpg"
        return {"lisans_turu": "PD-Old", "toplama": {"baslik": baslik}, "sha256": baslik}
    r = ou.gorselleri_topla("k", [{"gorsel_id": x, "sorgu": "q"} for x in "abc"], hedef=tmp_path, topla=topla)
    assert [g["gorsel_id"] for g in r] == ["k-a", "k-c"]
    assert gorulen_haric[1] == ["File:Bellini.jpg"]                                     # sonraki sorgu öncekini hariç tutar
    assert not (tmp_path / "k-b.jpg").exists()                                          # yinelenen dosya silindi


def test_commons_toplayici_haric_basliklari_secmez(monkeypatch):
    aday = [{"baslik": "File:A.jpg", "mime": "image/jpeg", "gen": 3000, "yuk": 3000, "meta": {}},
            {"baslik": "File:B.jpg", "mime": "image/jpeg", "gen": 3000, "yuk": 3000, "meta": {}}]
    yakalanan = []
    monkeypatch.setattr(commons_toplayici, "ara", lambda **k: list(aday))
    monkeypatch.setattr(commons_toplayici, "sec", lambda a, *x, **y: (yakalanan.append([c["baslik"] for c in a]), (None, []))[1])
    with pytest.raises(commons_toplayici.ToplayiciHatasi):
        commons_toplayici.topla({"gorsel_id": "g", "sorgu": "q", "haric": ["File:A.jpg"]}, Path("/tmp/yok"))
    assert yakalanan == [["File:B.jpg"]]


@pytest.mark.parametrize("plan_ids, en_az, beklenen", [
    (["a", "b", "a"], 2, "tekrar eden: ['a']"),
    (["a", "b"], 3, "2 farklı tarihî görsel (en az 3)"),
])
def test_render_kapisi_tekrar_ve_eksik(tmp_path, plan_ids, en_az, beklenen):
    (tmp_path / "gorsel_kapisi.json").write_text(json.dumps({"en_az": en_az}))
    (tmp_path / "cekim_plani.json").write_text(json.dumps({"cekimler": [
        {"id": f"S{i}", "tur": "gorsel25d", "gorsel25d": {"gorsel_id": g}} for i, g in enumerate(plan_ids)]}))
    with pytest.raises(ou.UretimHatasi) as e:
        ou.render_kapisi(tmp_path)
    assert e.value.kod == 5 and beklenen in str(e.value)
    with pytest.raises(ou.UretimHatasi):
        ou.parca_render(tmp_path, 0)                                                    # render işi de başlamaz


def test_render_kapisi_kaydi_yoksa_render_yok_dogrulama_acik_muaf(tmp_path):
    with pytest.raises(ou.UretimHatasi) as e:
        ou.render_kapisi(tmp_path)
    assert "gorsel_kapisi.json yok" in str(e.value)
    (tmp_path / "gorsel_kapisi.json").write_text(json.dumps({"dogrulama": True, "en_az": 12}))
    assert ou.render_kapisi(tmp_path)["dogrulama"] is True
    (tmp_path / "gorsel_kapisi.json").write_text(json.dumps({"en_az": 1}))
    (tmp_path / "cekim_plani.json").write_text(json.dumps({"cekimler": [
        {"id": "S1", "tur": "gorsel25d", "gorsel25d": {"gorsel_id": "a"}}, {"id": "S2", "tur": "harita"}]}))
    assert ou.render_kapisi(tmp_path)["en_az"] == 1


def test_kurgu_once_render_kapisi_sonra_atif_dosyasi(tmp_path, monkeypatch):
    from motor.uretim import kurgu
    is_ = tmp_path / "is"
    is_.mkdir()
    (is_ / "konu.json").write_text(json.dumps({"kimlik": "t"}))
    with pytest.raises(ou.UretimHatasi):
        ou.kurgu_yap(is_, tmp_path / "c")                                               # kapı kaydı yok → kurgu yok
    (is_ / "gorsel_kapisi.json").write_text(json.dumps({"dogrulama": True, "en_az": 3}))
    (is_ / "gorsel_atiflari.json").write_text(json.dumps([
        {"gorsel_id": "g1", "lisans": "CC-BY-SA-4.0", "commons_baslik": "File:Topkapı.jpg", "kaynak_url": "https://c/1",
         "atif": {"yazar": "Ayşe Yılmaz", "lisans": "CC BY-SA 4.0", "kaynak": "https://c/1"}},
        {"gorsel_id": "g2", "lisans": "PD-Old", "commons_baslik": "File:Bellini.jpg", "kaynak_url": "https://c/2"}]))
    monkeypatch.setattr(kurgu, "uret", lambda k: {"durum": "HATA"})
    r = ou.kurgu_yap(is_, tmp_path / "c")
    metin = (tmp_path / "c" / "t_gorsel_atiflari.txt").read_text(encoding="utf-8")
    assert r["gecti"] is False and "Ayşe Yılmaz" in metin and "CC BY-SA 4.0" in metin and "File:Bellini.jpg" in metin


# ================================================================== 2) sorgular ve lisans havuzu

def test_sorgu_istemi_sahne_konularindan_alt_terimler():
    ara = {"kartlar": [{"iddia": "Osmanlı topçusu belirleyici oldu"}]}
    i = ou.gorsel_sorgu_istemi("Otlukbeli Savaşı", ara, 30, ["Savaş: toplar ve yeniçeriler", "Tebriz sarayı"])
    for x in ("Savaş: toplar ve yeniçeriler", "Tebriz sarayı", "Ottoman miniature", "Janissaries", "Mehmed II",
              "15th century battle", "Anatolia historical map", "Tabriz miniature", "Ottoman artillery", "CC-BY-SA"):
        assert x in i, x
    assert 'yalnızca konu/savaş adıyla ("Otlukbeli Savaşı") KURMA' in i and "30 öğe" in i


def test_shorts_sorgulari_kartlardan_sahne_konusu_alir(kapi):
    sen = {"cumleler": [{"id": f"S{i + 1}", "metin": "a", "kartlar": ["C1"], "niyet": {"tur": "gorsel25d",
           "gorsel25d": {"gorsel_id": f"otlukbeli-1473-oto-g{i}"}, "aciklama": f"a{i}"}} for i in range(3)]}
    s = Sahte([_sorgular(4), sen])
    with pytest.raises(ou.UretimHatasi):   # plan sahte değil: yalnız istemleri görmek için kapıda durması yeterli
        ou.planla("Otlukbeli Savaşı", "shorts", kapi / "is", "AIza", havuz_fn=lambda k: {"kayitlar": [_kayit(1)]},
                  saglayici_fn=lambda: s, topla=_topla(), planla_fn=lambda is_: {"gecti": False, "hatalar": {"x": ["y"]}},
                  olc=lambda cs: {})
    assert s.istemler[0][0] == "gorsel_sorgu" and "- iddia 1" in s.istemler[0][1].split("SAHNE KONULARI:")[1]


@pytest.mark.parametrize("lisans, atif, kabul", [
    ("CC0-1.0", None, True), ("PD-Art", None, True), ("PD-Old", None, True),
    ("CC-BY-4.0", {"yazar": "A", "lisans": "CC BY 4.0", "kaynak": "u"}, True),
    ("CC-BY-SA-4.0", {"yazar": "A", "lisans": "CC BY-SA 4.0", "kaynak": "u"}, True),
    ("CC-BY-SA", {"yazar": "A", "lisans": "CC BY-SA", "kaynak": "u"}, True),
    ("CC-BY-SA-4.0", {"yazar": "bilinmiyor", "lisans": "CC BY-SA 4.0", "kaynak": "u"}, False),
    ("CC-BY-4.0", None, False),
    ("CC-BY-NC-4.0", {"yazar": "A", "lisans": "CC BY-NC 4.0", "kaynak": "u"}, False),
    ("CC-BY-ND-2.0", {"yazar": "A", "lisans": "CC BY-ND 2.0", "kaynak": "u"}, False),
    ("CC-BY-NC-SA-3.0", {"yazar": "A", "lisans": "x", "kaynak": "u"}, False),
    ("GFDL", None, False),
])
def test_lisans_havuzu(lisans, atif, kabul):
    assert ou.lisans_uygun({"lisans_turu": lisans, **({"atif": atif} if atif else {})})[0] is kabul


def test_cc_by_sa_atifla_kaydedilir_nc_silinir(tmp_path, kapi):
    atif = {"yazar": "Ayşe", "lisans": "CC BY-SA 4.0", "kaynak": "https://c"}
    r = ou.gorselleri_topla("k", [{"gorsel_id": "a", "sorgu": "q"}], hedef=tmp_path, topla=_topla("CC-BY-SA-4.0", atif))
    assert r[0]["lisans"] == "CC-BY-SA-4.0" and r[0]["atif"] == atif
    (tmp_path / "k-b.jpg").write_bytes(b"x")
    r = ou.gorselleri_topla("k", [{"gorsel_id": "b", "sorgu": "q"}], hedef=tmp_path,
                            topla=_topla("CC-BY-NC-4.0", dict(atif, lisans="CC BY-NC 4.0")))
    assert r == [] and not (tmp_path / "k-b.jpg").exists()


@pytest.mark.parametrize("kisa, kod, beklenen, kisitli", [
    ("CC BY-NC 4.0", "cc-by-nc-4.0", "CC-BY-NC-4.0", True),
    ("CC BY-ND 2.0", "cc-by-nd-2.0", "CC-BY-ND-2.0", True),
    ("CC BY-NC-SA 3.0", "cc-by-nc-sa-3.0", "CC-BY-NC-SA-3.0", True),
    ("CC BY-SA 4.0", "cc-by-sa-4.0", "CC-BY-SA-4.0", False),
    ("CC BY 3.0", "cc-by-3.0", "CC-BY-3.0", False),
])
def test_commons_lisans_siniflamasi_nc_nd_yutmaz(kisa, kod, beklenen, kisitli):
    assert commons_toplayici.lisans_kategorisi({"LicenseShortName": kisa, "License": kod}) == (beklenen, True)
    a = {"mime": "image/jpeg", "gen": 3000, "yuk": 3000, "meta": {"LicenseShortName": kisa, "License": kod}}
    assert (commons_toplayici.elenme_nedeni(a) is not None) is kisitli


def test_lisans_kapisi_nc_nd_atifla_da_gecmez(tmp_path):
    dosya = tmp_path / "g.jpg"
    dosya.write_bytes(b"x")
    taban = {"gorsel_id": "g", "kaynak_url": "u", "kaynak_kurum": "c", "eser_adi": "e", "tarih": "1480", "bolge": "b",
             "donem": "d", "kultur": "k", "yerel_yol": str(dosya), "lisans_dogrulandi": True,
             "onay": {"kaynak_edinimi": "otomatik_toplayici", "insan_onayi": False, "tarih": "2026-11-28"},
             "atif": {"yazar": "A", "lisans": "L", "kaynak": "u"}}
    taban.update({a: taban.get(a) or "x" for a in tarihi_gorsel.ZORUNLU_ALANLAR})
    assert not any("lisans" in h for h in tarihi_gorsel.denetle(dict(taban, lisans_turu="CC-BY-SA-4.0")))
    assert any("izin verilmeyen lisans" in h for h in tarihi_gorsel.denetle(dict(taban, lisans_turu="CC-BY-NC-4.0")))
    assert any("izin verilmeyen lisans" in h for h in tarihi_gorsel.denetle(dict(taban, lisans_turu="CC-BY-ND-2.0")))


# ================================================================== 3) en az benzersiz görsel kapısı

@pytest.mark.parametrize("bicim, indirilen", [("shorts", 2), ("uzun", 11)])
def test_yetersiz_gorselde_senaryo_ve_render_yok(kapi, bicim, indirilen):
    yan = ([TASLAK] if bicim == "uzun" else []) + [_sorgular(indirilen)]
    s = Sahte(yan)
    with pytest.raises(ou.UretimHatasi) as e:
        ou.planla("Otlukbeli Savaşı", bicim, kapi / "is", "AIza", havuz_fn=lambda k: {"kayitlar": [_kayit(1)]},
                  saglayici_fn=lambda: s, topla=_topla(), planla_fn=lambda is_: pytest.fail("plana geçilmemeli"))
    en_az = ou.EN_AZ_GORSEL[bicim]
    assert e.value.kod == 5 and f"{indirilen} benzersiz tarihî görsel indirildi; en az {en_az}" in str(e.value)
    assert [a for a, _ in s.istemler][-1] == "gorsel_sorgu"                             # senaryo çağrısı yapılmadı
    assert ou.EN_AZ_GORSEL == {"shorts": 3, "uzun": 12}


def test_her_ikisi_iki_esigi_de_ister(kapi):
    s = Sahte([TASLAK, _sorgular(5)])
    with pytest.raises(ou.UretimHatasi) as e:
        ou.planla("Otlukbeli Savaşı", "her_ikisi", kapi / "is", "AIza", havuz_fn=lambda k: {"kayitlar": [_kayit(1)]},
                  saglayici_fn=lambda: s, topla=_topla(), planla_fn=lambda is_: pytest.fail("x"))
    assert "uzun: 5 benzersiz" in str(e.value) and "shorts:" not in str(e.value)


def test_shorts_senaryosu_en_az_uc_farkli_gorsel_kullanir(monkeypatch):
    from motor.uretim import sozlesme
    monkeypatch.setattr(sozlesme, "senaryo_denetle", lambda s, a: [])
    k = ou.konu_kur(PILOT, "Otlukbeli Savaşı", "shorts")
    g = [{"gorsel_id": f"g{i}", "aciklama": "x"} for i in range(4)]
    sen = {"cumleler": [{"id": f"S{i}", "metin": "m", "kartlar": ["C1"], "niyet": {"tur": "gorsel25d",
           "gorsel25d": {"gorsel_id": f"g{i}"}, "aciklama": f"a{i}"}} for i in range(2)]}
    assert any("senaryoda 2 farklı tarihî görsel; en az 3" in x for x in ou.senaryo_denetle(sen, {}, k, g, lambda cs: {}))


def test_uzun_bolum_gorsel_kotasi():
    konu = ou.konu_kur(PILOT, "Otlukbeli Savaşı", "uzun")
    g = [{"gorsel_id": f"g{i}", "aciklama": "x"} for i in range(3)]
    ara = {"kartlar": [{"id": "C1", "guven": "kesin", "iddia": "x"}]}
    y = {"cumleler": [{"metin": _metin(400 + j), "kartlar": ["C1"], "niyet":
                       {"tur": "gorsel25d", "gorsel_id": "g0", "aciklama": "a"} if j == 2 else
                       {"tur": "harita", "evre": "E1", "metin": f"m{j}"}} for j in range(10)]}
    _, h = ou.bolum_cumleleri(y, ara, konu, g, [], {}, "B1", 1, [], en_az_yeni=2)
    assert any("1 farklı tarihî görsel kullanıldı; en az 2" in x for x in h)
    _, h = ou.bolum_cumleleri(y, ara, konu, g, [], {}, "B1", 1, [], en_az_yeni=1)
    assert h == []
    istem = ou.bolum_istemi(konu, ara, {"bolumler": []}, {"id": "B1", "baslik": "b", "roller": ["kanca"]}, [], g, [],
                            {"g0": 1}, 100, [], True, False, en_az_yeni=2)
    assert "EN AZ 2 farklı" in istem and "g1 = x" in istem and "g0 = x" not in istem   # kullanılan görsel listelenmez


def test_is_akisi_atif_dosyasi_artifactta():
    assert "${{ env.CIKTI }}/video/*.txt" in WF.read_text()


def test_planla_senaryo_sonrasi_kapi_uretici_atlasa_bile_durdurur(kapi, monkeypatch):
    """Savunma derinliği: senaryo üreticisi (ya da gelecekteki bir değişiklik) kotayı atlasa bile planla, plan ve
    render'dan önce senaryodaki benzersiz görsel sayısını ve tekrarı yeniden denetler."""
    ids = [f"otlukbeli-1473-oto-g{i}" for i in range(12)]
    sen = {"format": "uzun", "cumleler": [{"id": f"S{i}", "niyet": {"tur": "gorsel25d", "gorsel25d": {"gorsel_id": g}}}
                                          for i, g in enumerate(ids[:2] + ids[:1])]}
    monkeypatch.setattr(ou, "uzun_senaryo_uret", lambda *a, **k: (sen, []))
    s = Sahte([TASLAK, _sorgular(12)])
    with pytest.raises(ou.UretimHatasi) as e:
        ou.planla("Otlukbeli Savaşı", "uzun", kapi / "is", "AIza", havuz_fn=lambda k: {"kayitlar": [_kayit(1)]},
                  saglayici_fn=lambda: s, topla=_topla(), planla_fn=lambda is_: pytest.fail("plana geçilmemeli"))
    assert e.value.kod == 5 and "senaryoda 2 farklı" in str(e.value) and "birden fazla cümlede" in str(e.value)
