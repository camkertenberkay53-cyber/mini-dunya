"""Faz-58 — 503 + zaman aşımı aşırı yük bağlamı, yedek süre rezervi, Shorts kısa devresi ve sayı çelişkisi.

Run 45984647430: birincil model 503 → 15 sn → 90 sn ZAMAN AŞIMI → 503 → 30 sn → 70 sn ZAMAN AŞIMI → süre bütçesi
(210 sn) doldu. Zaman aşımları aşırı yük bağlamını taşımadığı için yedek modele hiç geçilmedi, son sınıf
`sure_butcesi` olduğundan Shorts kısa devresi de çalışmadı (3 istek daha). Sayı tarafında ark_029 / ark_032
(5.000 Uzun Hasan kuvveti / 60.000 ona saldıran kanatlar, ikisi de EN Wikipedia) yanlışlıkla çelişki sayıldı.

Bütün testler sahte saatle deterministiktir: zaman aşımı, istekte verilen süre kadar saati ilerletir; uyku da öyle.
"""
from __future__ import annotations

import json

import pytest

from motor.orkestrasyon import canli_dry_run as cdr
from motor.orkestrasyon import gemini as gm
from motor.orkestrasyon import iddia_atom as ia
from motor.orkestrasyon import kaynak_kesif as kk

ANAHTAR = "AIzaTEST-faz58-0123456789"
P, Y, U = gm.MODELLER[0], gm.MODELLER[1], gm.MODELLER[2]
T = "ZAMAN_ASIMI"


def _y200(metin="ok"):
    return 200, json.dumps({"candidates": [{"content": {"parts": [{"text": metin}]}}]})


def _saglayici(davranis, saat=None, **kw):
    """davranis(model, n) → (kod, metin[, başlıklar]) ya da T. Dönüş: (sağlayıcı, istekler[(model, zaman, t)], uykular)."""
    saat = saat if saat is not None else [0.0]
    istek, uyku = [], []

    def t(url, govde, bas, zaman):
        model = url.split("/models/")[1].split(":")[0]
        istek.append((model, zaman, saat[0]))
        r = davranis(model, len(istek))
        if r == T:
            saat[0] += zaman
            raise TimeoutError("The read operation timed out")
        saat[0] += 1.0
        return r

    def u(s):
        uyku.append(s)
        saat[0] += s
    kw.setdefault("en_cok_tekrar", 1)
    g = gm.GeminiLLMProvider(tasiyici=t, uyku=u, saat=lambda: saat[0], anahtar=ANAHTAR, **kw)
    return g, istek, uyku


def _dizi(*adimlar):
    """Model başına sıralı yanıt listesi; liste biterse son yanıt tekrarlanır."""
    sayac: dict[str, int] = {}

    def d(model, n):
        sira = dict(adimlar)[model] if model in dict(adimlar) else [(404, "not found")]
        i = sayac.get(model, 0)
        sayac[model] = i + 1
        return sira[min(i, len(sira) - 1)]
    return d


# ================================================================== 1. aşırı yük bağlamı ve kısa zaman aşımı

def test_503_retry_timeout_asiri_yuk_baglamini_korur_ve_yedege_gecer():
    """Koşu 45984647430'un deseni: 503 → bekle → zaman aşımı → 503. Artık yedeğe geçilir ve yedek başarır."""
    g, istek, uyku = _saglayici(_dizi((P, [(503, "x"), T, (503, "x")]), (Y, [_y200("yedek")])), sure_butcesi=210.0)
    assert g.tamamla("x", "anlati", {}) == "yedek"
    assert [m for m, _, _ in istek] == [P, P, P, Y]
    assert g.yedek_gecisi == {"etiket": "anlati", "kimden": P, "kime": Y}
    # zaman aşımı 503 olarak KAYDEDİLMEZ; aşırı yük bağlamı ayrı işaretlenir
    assert [(h["sinif"], h.get("asiri_yuk_baglami", False)) for h in g.hatalar] == [
        ("asiri_yuk", False), ("zaman_asimi", True), ("asiri_yuk", False)]
    assert g.asiri_yuk_goruldu is True
    assert uyku == [15.0]                                           # zaman aşımından sonra ek bekleme yok


def test_503_sonrasi_kisa_zaman_asimi_uygulanir():
    g, istek, _ = _saglayici(_dizi((P, [(503, "x"), T, T]), (Y, [_y200()])), sure_butcesi=None)
    g.tamamla("x", "anlati", {})
    zamanlar = [z for _, z, _ in istek]
    assert zamanlar[0] == 90.0                                      # bağlam yokken normal zaman aşımı
    assert all(30.0 <= z <= 45.0 for z in zamanlar[1:]) and set(zamanlar[1:]) == {40.0}


@pytest.mark.parametrize("deger", [29.0, 46.0, 90.0])
def test_kisa_zaman_asimi_30_45_araligi_disinda_reddedilir(deger):
    with pytest.raises(ValueError):
        gm.GeminiLLMProvider(anahtar=ANAHTAR, zaman_asimi_yuk=deger)


def test_birincil_zaman_butcesini_tuketmeden_yedek_calisir():
    """Birincil 503 + iki zaman aşımı; yedeğe geçildiğinde süre bütçesinde en az rezerv kadar zaman kalmıştır."""
    g, istek, _ = _saglayici(_dizi((P, [(503, "x"), T, T]), (Y, [_y200("y")])), sure_butcesi=210.0)
    assert g.tamamla("x", "anlati", {}) == "y"
    t_yedek = next(t for m, _, t in istek if m == Y)
    assert 210.0 - t_yedek >= g.yedek_rezerv_sn == 60.0
    assert t_yedek == 96.0                                          # 1 + 15 + 40 + 40 (eskiden 90 + 70 harcanırdı)


def test_retry_after_birincil_payini_asarsa_yedek_rezervine_dokunmadan_gecis():
    g, istek, uyku = _saglayici(_dizi((P, [(503, "x", {"retry-after": "100"})]), (Y, [_y200("y")])),
                                sure_butcesi=210.0)
    assert g.tamamla("x", "anlati", {}) == "y"
    assert [m for m, _, _ in istek] == [P, P, Y] and uyku == [100.0]
    t_yedek = next(t for m, _, t in istek if m == Y)
    assert 210.0 - t_yedek >= 60.0
    assert all(z <= 210.0 - t - 60.0 for m, z, t in istek if m == P and t > 0)   # birincil rezerve taşmadı


def test_yedek_basarili_yanit_ve_sonraki_parca_yedekte_kalir():
    g, istek, _ = _saglayici(_dizi((P, [(503, "x")]), (Y, [_y200("p1"), _y200("p2")])), sure_butcesi=210.0)
    assert g.tamamla("a", "anlati", {"bolum": "1"}) == "p1" and g.tamamla("b", "anlati", {"bolum": "2"}) == "p2"
    assert [m for m, _, _ in istek] == [P, P, P, Y, Y] and g.kullanilan_model == Y


def test_yedek_503_ve_zaman_asimi_ile_basarisiz_olur_zincir_yok():
    g, istek, uyku = _saglayici(_dizi((P, [(503, "x"), T, (503, "x")]), (Y, [T, (503, "x")])), sure_butcesi=210.0)
    with pytest.raises(gm.GercekUretimHatasi) as e:
        g.tamamla("x", "anlati", {})
    assert e.value.sinif == "asiri_yuk" and e.value.asiri_yuk_baglami is True and ANAHTAR not in str(e.value)
    assert [m for m, _, _ in istek] == [P, P, P, Y, Y] and U not in [m for m, _, _ in istek]
    assert g.son_basarisizlik == {"sinif": "asiri_yuk", "asiri_yuk_baglami": True}
    with pytest.raises(gm.GercekUretimHatasi):                     # çift çağrı yok: yeni istek gönderilmez
        g.tamamla("y", "plan", {})
    assert len(istek) == 5


def test_yedek_yalniz_zaman_asimi_verirse_sinirli_istekten_sonra_durur():
    g, istek, _ = _saglayici(_dizi((P, [(503, "x")]), (Y, [T])), sure_butcesi=None)
    with pytest.raises(gm.GercekUretimHatasi) as e:
        g.tamamla("x", "anlati", {})
    assert e.value.sinif == "asiri_yuk" and e.value.asiri_yuk_baglami
    assert [m for m, _, _ in istek] == [P, P, P, Y, Y]              # yedek: 1 + len(beklemeler_503_yedek)
    assert [z for m, z, _ in istek if m == Y] == [40.0, 40.0]


def test_yedekte_429_aninda_durur():
    g, istek, uyku = _saglayici(_dizi((P, [(503, "x"), T, (503, "x")]), (Y, [(429, "quota")])), sure_butcesi=210.0)
    with pytest.raises(gm.GeminiKotaHatasi) as e:
        g.tamamla("x", "anlati", {})
    assert e.value.sinif == "kota" and g.kota_doldu and [m for m, _, _ in istek] == [P, P, P, Y]
    with pytest.raises(gm.GeminiKotaHatasi):
        g.tamamla("y", "anlati", {})
    assert len(istek) == 4


def test_birincilde_429_503_sonrasinda_da_aninda_durur():
    g, istek, uyku = _saglayici(_dizi((P, [(503, "x"), (429, "quota")])), sure_butcesi=210.0)
    with pytest.raises(gm.GeminiKotaHatasi):
        g.tamamla("x", "anlati", {})
    assert [m for m, _, _ in istek] == [P, P] and uyku == [15.0] and g.yedek_gecisi is None


def test_sonsuz_yedek_zinciri_yok_ucuncu_model_hic_istenmez():
    g, istek, _ = _saglayici(lambda m, n: (503, "x") if n % 2 else T, sure_butcesi=None, en_cok_tekrar=5)
    with pytest.raises(gm.GercekUretimHatasi):
        g.tamamla("x", "anlati", {})
    modeller = [m for m, _, _ in istek]
    assert U not in modeller and modeller.count(Y) <= 2 and len(modeller) <= 5


def test_bekleme_ve_zaman_asimi_butceleri_deterministik():
    """Aşırı yük yolunun tam dökümü: istek sayısı, her isteğin zaman aşımı, beklemeler ve toplam süre sabit."""
    sonuclar = []
    for _ in range(3):
        saat = [0.0]
        g, istek, uyku = _saglayici(_dizi((P, [(503, "x"), T, (503, "x")]), (Y, [T, (503, "x")])),
                                    saat=saat, sure_butcesi=210.0)
        with pytest.raises(gm.GercekUretimHatasi):
            g.tamamla("x", "anlati", {})
        sonuclar.append(([(m, z) for m, z, _ in istek], uyku, saat[0], g.cagri_sayisi))
    assert sonuclar[0] == sonuclar[1] == sonuclar[2]
    istekler, uyku, toplam, cagri = sonuclar[0]
    assert istekler == [(P, 90.0), (P, 40.0), (P, 40.0), (Y, 40.0), (Y, 40.0)]
    assert uyku == [15.0] and cagri == 5
    assert toplam == 1 + 15 + 40 + 1 + 40 + 1 == 98.0             # eski davranışta 210 sn bütçenin tamamı yanıyordu
    assert toplam <= 210.0


# ================================================================== 1b. 503 görülmeyen hatalarda davranış korunur

def test_503_gorulmeyen_zaman_asimi_eski_davranis():
    g, istek, uyku = _saglayici(lambda m, n: T, sure_butcesi=None)
    with pytest.raises(gm.GercekUretimHatasi) as e:
        g.tamamla("x", "anlati", {})
    assert e.value.sinif == "zaman_asimi" and e.value.asiri_yuk_baglami is False
    assert {z for _, z, _ in istek} == {90.0}                      # kısa zaman aşımı YOK
    assert [m for m, _, _ in istek] == [P, P, Y, Y, U, U]          # sınırlı tekrar, sonra sıradaki model (eskisi gibi)
    assert g.asiri_yuk_goruldu is False and g.yedek_gecisi is None and g.asiri_yuk_doldu is False
    assert all("asiri_yuk_baglami" not in h for h in g.hatalar)


def test_503_gorulmeyen_sure_butcesi_asiri_yuk_baglami_tasimaz():
    g, istek, _ = _saglayici(lambda m, n: T, sure_butcesi=100.0)
    with pytest.raises(gm.GercekUretimHatasi) as e:
        g.tamamla("x", "anlati", {})
    assert e.value.sinif == "sure_butcesi" and e.value.asiri_yuk_baglami is False and g.yedek_rezerv_sn == 40.0


@pytest.mark.parametrize("davranis,sinif", [(lambda m, n: (500, "err"), "sunucu"),
                                            (lambda m, n: (_ for _ in ()).throw(ConnectionResetError("reset")), "ag")])
def test_genel_5xx_ve_ag_hatasi_regresyonu(davranis, sinif):
    istek, uyku = [], []

    def t(url, govde, bas, zaman):
        istek.append((url.split("/models/")[1].split(":")[0], zaman))
        return davranis(None, len(istek))
    g = gm.GeminiLLMProvider(tasiyici=t, uyku=uyku.append, anahtar=ANAHTAR, en_cok_tekrar=1)
    with pytest.raises(gm.GercekUretimHatasi) as e:
        g.tamamla("x", "anlati", {})
    assert e.value.sinif == sinif and e.value.asiri_yuk_baglami is False
    assert [m for m, _ in istek] == [P, P, Y, Y, U, U] and {z for _, z in istek} == {90.0}
    assert g.yedek_gecisi is None and g.asiri_yuk_goruldu is False


# ================================================================== 2. Shorts kısa devresi

def _dry_run(monkeypatch, davranis_uzun, davranis_shorts=None, sure=None):
    from motor.testler.test_kaynak_dogrulama import _havuz as gercek_havuz
    sayac: dict[str, int] = {}
    saglayicilar = {}

    def fabrika(m, anahtar, kaynak, log_fn):
        saat = [0.0]
        d = davranis_uzun if m == "uzun" else (davranis_shorts or davranis_uzun)

        def t(url, govde, bas, zaman):
            sayac[m] = sayac.get(m, 0) + 1
            model = url.split("/models/")[1].split(":")[0]
            r = d(model, sayac[m])
            if r == T:
                saat[0] += zaman
                raise TimeoutError("timed out")
            saat[0] += 1.0
            return r

        def u(s):
            saat[0] += s
        g = gm.GeminiLLMProvider(tasiyici=t, uyku=u, saat=lambda: saat[0], en_cok_tekrar=1, anahtar=anahtar,
                                 anahtar_kaynagi=kaynak, ilerleme=log_fn,
                                 sure_butcesi=(sure or cdr.SURE_BUTCESI)[m] if sure is not False else None)
        saglayicilar[m] = g
        return g
    monkeypatch.setattr(cdr, "_gemini", fabrika)
    r = {"asamalar": {}, "planlar": {}}
    durumlar = cdr._gemini_asamasi(r, "Örnekova Muharebesi", ["uzun", "shorts"], gercek_havuz(), ANAHTAR,
                                   "GEMINI_DRYRUN_KEY")
    return r, sayac, durumlar, saglayicilar


def test_uzun_503_timeout_karisik_asiri_yukte_shorts_cagrilmaz(monkeypatch):
    """Koşu 45984647430 deseni (503 / zaman aşımı dönüşümlü, yedek de aynı): Shorts'a 0 istek."""
    r, sayac, durumlar, g = _dry_run(monkeypatch, lambda m, n: (503, "x") if n % 2 else T)
    assert "shorts" not in sayac and r["asamalar"]["3_gemini_shorts"]["durum"] == "atlandi_asiri_yuk"
    assert r["asamalar"]["3_gemini_uzun"]["durum"] == "gemini_asiri_yuk"
    assert g["uzun"].yedek_gecisi is not None                       # yedek bu kez gerçekten denendi
    assert sayac["uzun"] <= 5 and durumlar == ["gemini_asiri_yuk", "gemini_asiri_yuk"]


def test_uzun_503_sonrasi_sure_butcesi_bitse_de_shorts_cagrilmaz(monkeypatch):
    """Aşırı yük bağlamında süre bütçesi biterse sınıf 'sure_butcesi' kalır ama kısa devre uygulanır."""
    r, sayac, _, g = _dry_run(monkeypatch, _dizi((P, [(503, "x", {"retry-after": "100"})]), (Y, [T])),
                              sure={"uzun": 150.0, "shorts": 90.0})
    assert g["uzun"].son_basarisizlik["asiri_yuk_baglami"] is True
    assert "shorts" not in sayac and r["asamalar"]["3_gemini_shorts"]["durum"] == "atlandi_asiri_yuk"


def test_uzun_503_gorulmeyen_zaman_asiminda_shorts_eskisi_gibi_denenir(monkeypatch):
    r, sayac, _, _ = _dry_run(monkeypatch, lambda m, n: T)
    assert sayac.get("shorts", 0) > 0 and not r["asamalar"]["3_gemini_shorts"]["durum"].startswith("atlandi")
    assert r["asamalar"]["3_gemini_uzun"]["durum"] != "gemini_asiri_yuk"


@pytest.mark.parametrize("davranis", [lambda m, n: (500, "err"),
                                      lambda m, n: (_ for _ in ()).throw(ConnectionResetError("reset"))])
def test_uzun_5xx_ve_ag_hatasinda_shorts_denenir(monkeypatch, davranis):
    r, sayac, _, _ = _dry_run(monkeypatch, davranis, sure=False)
    assert sayac.get("shorts", 0) > 0 and not r["asamalar"]["3_gemini_shorts"]["durum"].startswith("atlandi")


def test_uzun_429_shorts_kota_ile_atlanir(monkeypatch):
    r, sayac, _, _ = _dry_run(monkeypatch, lambda m, n: (429, "quota"))
    assert sayac == {"uzun": 1} and r["asamalar"]["3_gemini_shorts"]["durum"] == "atlandi_kota"


def test_basarisizlik_siniflandirmasi():
    f = cdr._asiri_yuk_basarisizligi
    assert f("asiri_yuk", False) and f("zaman_asimi", True) and f("sure_butcesi", True)
    assert not f("zaman_asimi", False) and not f("sure_butcesi", False)
    assert not f("sunucu", True) and not f("ag", True) and not f("kota", True)


# ================================================================== 3. sayı çelişkisi

ARK_029 = "Here Uzun Hasan's force of 5,000 men was encountered."
ARK_032 = "On the right and left wings, 60,000 people began to harass Uzun Hasan's forces with all their efforts."


def test_nesne_konumundaki_ordu_ozne_sayilmaz():
    b = ia.sayi_baglamlari(ARK_032)
    assert [(x["deger"], x["taraf"]) for x in b] == [(60000, set())]
    assert ia.sayi_baglamlari(ARK_029)[0]["taraf"] == {"hasan", "uzunh"}
    assert ia.sayi_baglamlari("Uzun Hasan attacked the 100,000-strong Ottoman army.")[0]["taraf"] == {"ottom"}
    sag = ia.sayi_baglamlari("an army of 5,000 men of Uzun Hasan")[0]["taraf"]   # sağda bitişik niteleme
    assert sag & ia.sayi_baglamlari(ARK_029)[0]["taraf"] == {"uzunh"}


def test_ark_029_ve_ark_032_celiski_sayilmaz():
    r = ia.degerlendir([ARK_032], {"metin": ARK_029, "olay_terimleri": ["Otlukbeli"]})
    assert r["destek_sinifi"] != "contradicts" and "sayi" not in r["celiski"]
    k = [_kayit("ark_029", ARK_029, [0, 4]), _kayit("ark_032", ARK_032, [0])]
    kk.sayisal_koruma(k)
    assert all("celiski" not in x for x in k)


def _kayit(kid, metin, kumeler, olay="olay_genel"):
    return {"id": kid, "iddia": metin, "yil": None, "olay_id": olay, "karsi_kume_sayisi": 0,
            "kaynaklar": [{"kume": c, "teyit_turu": "icerik"} for c in kumeler],
            "sayilar": kk._sayilar(metin), "bagimsiz_kaynak_sayisi": len(kumeler), "tarih_teyit_kume_sayisi": 2,
            "sayi_teyit_kume_sayisi": len(kumeler), "iddia_atomlari": {}}


def test_ayni_ordu_ayni_olay_farkli_rakam_yakalanir():
    a = "At Otlukbeli Uzun Hasan's army numbered 5,000 men."
    b = "At Otlukbeli Uzun Hasan's army numbered 60,000 men."
    r = ia.degerlendir([b], {"metin": a, "olay_terimleri": ["Otlukbeli"]})
    assert r["destek_sinifi"] == "contradicts" and "sayi" in r["celiski"]
    k = [_kayit("a", a, [0]), _kayit("b", b, [1])]
    kk.sayisal_koruma(k)
    assert all(x["durum"] == "tartismali" and "celiski" in x for x in k)
    assert {d["deger"] for d in k[0]["celiski"]["degerler"]} == {5000, 60000}


def test_farkli_birlik_ve_olay_asamasi_celiski_sayilmaz():
    i = {"metin": "At Otlukbeli Uzun Hasan's vanguard of 5,000 men was routed.", "olay_terimleri": ["Otlukbeli"]}
    r = ia.degerlendir(["At Otlukbeli Uzun Hasan's army of 60,000 men stood on the hills."], i)
    assert r["destek_sinifi"] != "contradicts"
    r2 = ia.degerlendir(["Otlukbeli'de Uzun Hasan'ın 60.000 kişilik ordusu takip sırasında dağıldı."],
                        {"metin": "Otlukbeli'de Uzun Hasan'ın 5.000 kişilik ordusu tepelerde bekledi.",
                         "olay_terimleri": ["Otlukbeli"]})
    assert r2["destek_sinifi"] != "contradicts"
    k = [_kayit("a", "At Otlukbeli Uzun Hasan's vanguard of 5,000 men was routed.", [0]),
         _kayit("b", "At Otlukbeli Uzun Hasan's army of 60,000 men stood on the hills.", [1])]
    kk.sayisal_koruma(k)
    assert all("celiski" not in x for x in k)


def test_ayni_kaynaktaki_farkli_baglam_rakamlari_otomatik_celiski_degil():
    i = {"metin": "At Otlukbeli Uzun Hasan's army numbered 5,000 men.", "olay_terimleri": ["Otlukbeli"]}
    ayni_kaynak = ["At Otlukbeli Uzun Hasan's army numbered 60,000 men before the desertions began.",
                   "Later at Otlukbeli Uzun Hasan's army numbered 5,000 men on the ridge."]
    r = ia.degerlendir(ayni_kaynak, i)
    assert r["destek_sinifi"] != "contradicts" and "sayi" not in r["celiski"]
    # havuz: aynı küme (0) her iki değeri veriyor → o küme karşılaştırmadan çıkar
    k = [_kayit("a", "At Otlukbeli Uzun Hasan's army numbered 5,000 men.", [0, 4]),
         _kayit("b", "At Otlukbeli Uzun Hasan's army numbered 60,000 men.", [0])]
    kk.sayisal_koruma(k)
    assert all("celiski" not in x for x in k)


def test_ayni_kaynak_yil_celiskisi_sayi_kuralindan_etkilenmez():
    i = {"metin": "Otlukbeli Savaşı 1473 yılında yapıldı ve Uzun Hasan'ın ordusu 5.000 askerden oluşuyordu.",
         "olay_terimleri": ["Otlukbeli", "Savaşı"]}
    r = ia.degerlendir(["Otlukbeli Savaşı 1474 yılında yapıldı; Uzun Hasan'ın ordusu 5.000 askerden oluşuyordu."], i)
    assert r["destek_sinifi"] == "contradicts" and "yil" in r["celiski"]


@pytest.mark.parametrize("pencere", ["At Otlukbeli the women of Uzun Hasan's court numbered 600 in the documents.",
                                     "At Otlukbeli Uzun Hasan's garments: 600 comments in the documents."])
def test_kelime_ici_men_eslesmesi_celiski_uretmez(pencere):
    assert ia._olcu_kelime("women") is None and ia._olcu_kelime("garments") is None
    r = ia.degerlendir([pencere], {"metin": "At Otlukbeli Uzun Hasan's army numbered 5,000 men.",
                                   "olay_terimleri": ["Otlukbeli"]})
    assert r["destek_sinifi"] != "contradicts"


# ================================================================== mutasyon boşluklarını kapatan hedefli testler

def test_birincil_istek_zaman_asimi_yedek_payina_tasmaz():
    """Bütçe 100 sn → rezerv 40 sn. Birincilin 2. isteği yalnız kalan payı (69 − 40 = 29 sn) kullanabilir."""
    g, istek, uyku = _saglayici(_dizi((P, [(503, "x", {"retry-after": "30"}), T]), (Y, [_y200("y")])),
                                sure_butcesi=100.0)
    assert g.yedek_rezerv_sn == 40.0
    assert g.tamamla("x", "anlati", {}) == "y"
    assert [(m, z) for m, z, _ in istek][:2] == [(P, 90.0), (P, 29.0)]
    t_yedek = next(t for m, _, t in istek if m == Y)
    assert 100.0 - t_yedek >= 40.0


def test_asiri_yuk_baglaminda_sure_butcesi_sinifi_korunur_baglam_tasinir(monkeypatch):
    g, istek, _ = _saglayici(_dizi((P, [(503, "x"), T])), sure_butcesi=60.0, yedek_503=False,
                             beklemeler_503=(15.0, 30.0, 30.0, 30.0))
    with pytest.raises(gm.GercekUretimHatasi) as e:
        g.tamamla("x", "anlati", {})
    assert e.value.sinif == "sure_butcesi" and e.value.asiri_yuk_baglami is True   # sınıf korunur, bağlam ayrı
    assert g.son_basarisizlik == {"sinif": "sure_butcesi", "asiri_yuk_baglami": True}
    assert cdr._asiri_yuk_basarisizligi(e.value.sinif, e.value.asiri_yuk_baglami)


def test_ayni_kaynagin_kismi_destekleyen_penceresi_sayi_celiskisini_dusurur():
    i = {"metin": "At Otlukbeli Uzun Hasan's army numbered 5,000 men.", "olay_terimleri": ["Otlukbeli"]}
    celisen = "At Otlukbeli Uzun Hasan's army numbered 60,000 men before the desertions began."
    kismi = "In another account Uzun Hasan's army numbered 5,000 men on the ridge."   # olay adı yok → partial
    assert ia.degerlendir([celisen], i)["destek_sinifi"] == "contradicts"
    r = ia.degerlendir([celisen, kismi], i)
    assert r["destek_sinifi"] != "contradicts" and "sayi" not in r["celiski"]
