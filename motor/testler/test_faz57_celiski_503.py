"""Faz-57 — çelişki yanlış pozitifleri ve sınırlı 503 yedek model geçişi (ağsız, deterministik).

Run 45966548518 bulguları:
  (a) Kaynakça satırındaki yayın yılı ("↑ TSK (1986). Battle of …") ve başka savaşların yılları (1071 Malazgirt,
      1514 Çaldıran) doğru bir 1473 iddiasını "tartışmalı" yaptı.
  (b) Kaynakça sayfa numaraları ("222-223, 272, 311-321") ve alt dize ölçü eşleşmesi ("men") sayı çelişkisi üretti;
      farklı orduların rakamları birbiriyle karşılaştırıldı.
  (c) Birincil model 503 bütçesini bitirince başka model denenmedi; (d) uzun mod 503 ile durduktan sonra Shorts yine
      3 istek gönderdi.
  (e) TDV PDF metin katmanında "1" → "ı" (ı473).
"""
from __future__ import annotations

import json

import pytest

from motor.orkestrasyon import canli_dry_run as cdr
from motor.orkestrasyon import gemini as gm
from motor.orkestrasyon import iddia_atom as ia
from motor.orkestrasyon import kaynak_dogrulayici as kd
from motor.orkestrasyon import kaynak_kesif as kk

ANAHTAR = "AIzaTEST-faz57-0123456789"
BIRINCIL, YEDEK, UCUNCU = gm.MODELLER[0], gm.MODELLER[1], gm.MODELLER[2]


def _y200(metin="{}"):
    return 200, json.dumps({"candidates": [{"content": {"parts": [{"text": metin}]}}]})


def _saglayici(monkeypatch, davranis, **kw):
    """davranis(model, n) → (kod, metin[, basliklar]) ya da istisna. Dönüş: (sağlayıcı, istekler, uykular)."""
    monkeypatch.setenv("GEMINI_API_KEY", ANAHTAR)
    istek, uyku = [], []

    def t(url, govde, bas, zaman):
        model = url.split("/models/")[1].split(":")[0]
        istek.append(model)
        return davranis(model, len(istek))
    g = gm.GeminiLLMProvider(tasiyici=t, uyku=uyku.append, **kw)
    return g, istek, uyku


# ================================================================== 2. 503 yedek model geçişi

def test_birincil_503_tekrarlari_sonra_yedege_gecis_basarir(monkeypatch):
    g, istek, uyku = _saglayici(monkeypatch, lambda m, n: (503, "high demand") if m == BIRINCIL else _y200("yedek-ok"))
    assert g.tamamla("x", "anlati", {}) == "yedek-ok"
    assert istek == [BIRINCIL] * 3 + [YEDEK]                       # 1 + 2 tekrar (15 → 30 sn), sonra TEK yedek
    assert uyku == [15.0, 30.0]
    assert g.yedek_gecisi == {"etiket": "anlati", "kimden": BIRINCIL, "kime": YEDEK}
    assert g.kullanilan_model == YEDEK and g.cagri_sayisi == 4
    assert UCUNCU not in istek


def test_birincil_503_kurtarilirsa_yedege_gecilmez(monkeypatch):
    g, istek, uyku = _saglayici(monkeypatch, lambda m, n: (503, "x") if n <= 2 else _y200("ok"))
    assert g.tamamla("x", "anlati", {}) == "ok" and istek == [BIRINCIL] * 3 and g.yedek_gecisi is None


def test_yedek_de_503_kontrollu_durur_sonsuz_gecis_yok(monkeypatch):
    g, istek, uyku = _saglayici(monkeypatch, lambda m, n: (503, "x"), en_cok_tekrar=5)
    with pytest.raises(gm.GercekUretimHatasi) as e:
        g.tamamla("x", "anlati", {})
    assert e.value.sinif == "asiri_yuk" and "yedek geçişi" in str(e.value) and ANAHTAR not in str(e.value)
    # deterministik: birincil 3 + yedek 2 istek; beklemeler 15 + 30 (birincil) + 15 (yedek); üçüncü model YOK
    assert istek == [BIRINCIL] * 3 + [YEDEK] * 2 and uyku == [15.0, 30.0, 15.0] and g.cagri_sayisi == 5
    assert UCUNCU not in istek and g.asiri_yuk_doldu is True
    with pytest.raises(gm.GercekUretimHatasi) as e2:              # aynı sağlayıcıya yeni çağrı: istek gönderilmez
        g.tamamla("y", "plan", {})
    assert e2.value.sinif == "asiri_yuk" and len(istek) == 5


def test_yedekte_429_aninda_durur(monkeypatch):
    g, istek, uyku = _saglayici(monkeypatch, lambda m, n: (503, "x") if m == BIRINCIL else (429, "quota"))
    with pytest.raises(gm.GeminiKotaHatasi):
        g.tamamla("x", "anlati", {})
    assert istek == [BIRINCIL] * 3 + [YEDEK] and uyku == [15.0, 30.0] and g.kota_doldu   # 429'da bekleme/tekrar yok
    with pytest.raises(gm.GeminiKotaHatasi):
        g.tamamla("y", "anlati", {})
    assert len(istek) == 4


def test_birincilde_429_yedege_gecilmez(monkeypatch):
    g, istek, uyku = _saglayici(monkeypatch, lambda m, n: (429, "quota"))
    with pytest.raises(gm.GeminiKotaHatasi):
        g.tamamla("x", "anlati", {})
    assert istek == [BIRINCIL] and uyku == [] and g.yedek_gecisi is None


def test_yedek_404_ise_baska_model_aranmaz(monkeypatch):
    g, istek, uyku = _saglayici(monkeypatch, lambda m, n: (503, "x") if m == BIRINCIL else (404, "not found"))
    with pytest.raises(gm.GercekUretimHatasi):
        g.tamamla("x", "anlati", {})
    assert istek == [BIRINCIL] * 3 + [YEDEK] and UCUNCU not in istek


def test_yedek_birincille_ayni_olamaz_ve_flash_olmayan_secilmez(monkeypatch):
    g, istek, _ = _saglayici(monkeypatch, lambda m, n: (503, "x"), modeller=("m-flash", "m-flash"))
    with pytest.raises(gm.GercekUretimHatasi):
        g.tamamla("x", "anlati", {})
    assert istek == ["m-flash"] * 3 and g.yedek_gecisi is None
    g2, istek2, _ = _saglayici(monkeypatch, lambda m, n: (503, "x"), modeller=("m-flash", "m-pro"))
    with pytest.raises(gm.GercekUretimHatasi):
        g2.tamamla("x", "anlati", {})
    assert istek2 == ["m-flash"] * 3                                # model adı uydurulmaz; yapılandırmada yedek yok
    g3, istek3, _ = _saglayici(monkeypatch, lambda m, n: (503, "x"), modeller=("tek-flash",))
    with pytest.raises(gm.GercekUretimHatasi):
        g3.tamamla("x", "anlati", {})
    assert istek3 == ["tek-flash"] * 3


def test_yedek_tek_atislik_sonraki_parcada_yeni_gecis_ve_geri_donus_yok(monkeypatch):
    sayac = {"yedek": 0}

    def d(m, n):
        if m == BIRINCIL:
            return 503, "x"
        sayac["yedek"] += 1
        return _y200("p1") if sayac["yedek"] == 1 else (503, "x")
    g, istek, uyku = _saglayici(monkeypatch, d)
    assert g.tamamla("x", "anlati", {"bolum": "1"}) == "p1"
    with pytest.raises(gm.GercekUretimHatasi) as e:
        g.tamamla("y", "anlati", {"bolum": "2"})
    assert e.value.sinif == "asiri_yuk"
    assert istek == [BIRINCIL] * 3 + [YEDEK] + [YEDEK] * 2          # 2. parçada birincile dönülmez, 3. model yok
    assert uyku == [15.0, 30.0, 15.0]


def test_yedek_kapatilabilir(monkeypatch):
    g, istek, _ = _saglayici(monkeypatch, lambda m, n: (503, "x"), yedek_503=False)
    with pytest.raises(gm.GercekUretimHatasi):
        g.tamamla("x", "anlati", {})
    assert istek == [BIRINCIL] * 3


def test_yedek_beklemesi_sure_butcesini_asarsa_beklemeden_durur(monkeypatch):
    saat = [0.0]

    def d(m, n):
        if m == BIRINCIL:
            return 503, "x"
        saat[0] = 95.0
        return 503, "x", {"retry-after": "60"}
    g, istek, uyku = _saglayici(monkeypatch, d, sure_butcesi=100.0, saat=lambda: saat[0])
    with pytest.raises(gm.GercekUretimHatasi) as e:
        g.tamamla("x", "anlati", {})
    assert e.value.sinif == "asiri_yuk" and "süre bütçesini aşıyor" in str(e.value)
    assert istek == [BIRINCIL] * 3 + [YEDEK] and uyku == [15.0, 30.0]


# ================================================================== 2b. uzun 503 → Shorts kısa devresi

def _dry_run(monkeypatch, davranis):
    """Gerçek GeminiLLMProvider + sahte taşıyıcı; gerçek-kip araştırma havuzu. Dönüş: (rapor, mod→istek sayısı)."""
    from motor.testler.test_kaynak_dogrulama import _havuz as gercek_havuz
    sayac: dict[str, int] = {}

    def fabrika(m, anahtar, kaynak, log_fn):
        def t(url, govde, bas, zaman):
            sayac[m] = sayac.get(m, 0) + 1
            return davranis(m, sayac[m])
        return gm.GeminiLLMProvider(tasiyici=t, uyku=lambda s: None, en_cok_tekrar=1, anahtar=anahtar,
                                    anahtar_kaynagi=kaynak, ilerleme=log_fn)
    monkeypatch.setattr(cdr, "_gemini", fabrika)
    r = {"asamalar": {}, "planlar": {}}
    durumlar = cdr._gemini_asamasi(r, "Örnekova Muharebesi", ["uzun", "shorts"], gercek_havuz(), ANAHTAR, "GEMINI_DRYRUN_KEY")
    return r, sayac, durumlar


def test_uzun_503_bitince_shorts_cagrilmaz(monkeypatch):
    r, sayac, durumlar = _dry_run(monkeypatch, lambda m, n: (503, "high demand"))
    assert sayac == {"uzun": 5}                                     # birincil 3 + yedek 2; Shorts: 0 istek
    assert r["asamalar"]["3_gemini_shorts"]["durum"] == "atlandi_asiri_yuk"
    assert r["asamalar"]["3_gemini_shorts"]["gemini_cagri"] == 0
    assert r["asamalar"]["3_gemini_uzun"]["durum"] == "gemini_asiri_yuk" and r["planlar"] == {}
    assert durumlar == ["gemini_asiri_yuk", "gemini_asiri_yuk"]


def test_uzun_429_bitince_shorts_kota_ile_atlanir_davranis_korunur(monkeypatch):
    r, sayac, _ = _dry_run(monkeypatch, lambda m, n: (429, "quota"))
    assert sayac == {"uzun": 1} and r["asamalar"]["3_gemini_shorts"]["durum"] == "atlandi_kota"


def _zaman(m, n):
    raise TimeoutError("timed out")


def _ag(m, n):
    raise ConnectionResetError("reset")


@pytest.mark.parametrize("ad,davranis", [("zaman_asimi", _zaman), ("ag", _ag), ("sunucu_500", lambda m, n: (500, "err"))])
def test_uzun_503_disi_hatalarda_shorts_eskisi_gibi_denenir(monkeypatch, ad, davranis):
    r, sayac, _ = _dry_run(monkeypatch, davranis)
    assert sayac.get("uzun", 0) > 0 and sayac.get("shorts", 0) > 0, (ad, sayac)   # kısa devre YALNIZ 503 için
    assert not r["asamalar"]["3_gemini_shorts"]["durum"].startswith("atlandi"), ad
    assert r["asamalar"]["3_gemini_uzun"]["durum"] != "gemini_asiri_yuk"


def test_shorts_ve_uzun_kendi_saglayicisinda_basarili_uretim_yolu_degismez(monkeypatch):
    """503 yolunun dışında sıralı parça yapısı korunur: uzun modda ilk istekte yalnız 1. parça istenir."""
    from motor.orkestrasyon import senaryo_planlayici as sp
    istemler = []

    def d(m, n):
        return 503, "x"
    from motor.testler.test_kaynak_dogrulama import _havuz as gercek_havuz
    monkeypatch.setenv("GEMINI_API_KEY", ANAHTAR)

    def t(url, govde, bas, zaman):
        istemler.append(json.loads(govde)["contents"][0]["parts"][0]["text"])
        return 503, "x"
    g = gm.GeminiLLMProvider(tasiyici=t, uyku=lambda s: None)
    r = sp.plan_uret("Örnekova Muharebesi", "uzun", g, arastirma=gercek_havuz(), parcali=True)
    ilk = "YALNIZCA şu bölüm(ler)i yaz, bu sırayla: " + ", ".join(sp.PARCA_GRUPLARI[0])
    assert len(istemler) == 5 and all(ilk in x for x in istemler)   # yedek de aynı (1.) parçayı ister
    assert r["durum"] == "durduruldu" and r["render_baslatildi"] is False


# ================================================================== 1d. OCR rakam normalizasyonu

@pytest.mark.parametrize("ham,beklenen", [
    ("ı473", "1473"),
    ("ı ı Ağustos ı473", "11 Ağustos 1473"),
    ("Ağustos ı473", "Ağustos 1473"),
    ("ıı Ağustos ı473", "11 Ağustos 1473"),
    ("ı5 Mayıs ı474'te", "15 Mayıs 1474'te"),
    ("ı473-ı474 yılları", "1473-1474 yılları"),
])
def test_ocr_rakam_normalize(ham, beklenen):
    kopya, duz = ia.ocr_rakam_normalize(ham)
    assert " ".join(kopya.split()) == beklenen and duz
    assert len(kopya) == len(ham)                                   # uzunluk korunur → konum eşlemesi


@pytest.mark.parametrize("metin", [
    "ılık bir sabah ısı yükseldi; kırk atlı ılgın ağaçlarının altında bekledi.",
    "Sığınakta ı harfi tek başına yazıldı ve ıı diye uzatıldı.",
    "Kılıç Arslan ile Iğdır yöresi; Akıncılar sınırda.",
    "Sayfa ı47 bozuk ama yıl sayılmaz",                              # 3 hane ve geçerli yıl değil → dokunulmaz
])
def test_ocr_normal_turkce_i_korunur(metin):
    kopya, duz = ia.ocr_rakam_normalize(metin)
    assert kopya == metin and duz == []


def test_ocr_ozgun_metin_degismez_alinti_ozgun_metinden_ve_ocr_bagimli_isaretlenir():
    ozgun = ("ÖRNEKOVA SAVAŞI\nDemir Han ile Taş Bey arasında ı ı Ağustos ı501 tarihinde Örnekova mevkiinde yapılan "
             "savaş Demir Han'ın zaferiyle sonuçlandı.\n")
    kopya_oncesi = str(ozgun)
    i = {"metin": "Örnekova Savaşı 11 Ağustos 1501 tarihinde Demir Han ile Taş Bey arasında yapıldı ve Demir Han'ın "
                  "zaferiyle sonuçlandı.", "olay_terimleri": ["Örnekova", "Savaşı"]}
    r = kd.icerik_dogrula(ozgun, i)
    assert ozgun == kopya_oncesi                                    # özgün metin değişmedi
    assert r["destek_sinifi"] == "supported" and r["ocr_duzeltmeli"] and r["ocr_bagimli"]
    assert "ı ı Ağustos ı501" in r["supporting_excerpt"]            # alıntı özgün (onarılmamış) metinden
    assert "ocr_onarimina_bagli" in r["neden"]
    w, duz = kd.dogrulama_pencereleri(ozgun)
    assert w[0].orijinal and "ı501" in w[0].orijinal and "1501" in w[0]


def _api(kid, yay, metin):
    return {"id": kid, "url": f"https://doi.org/10.1/{kid}", "baslik": kid, "yayinci": yay, "tur": "akademik",
            "metin": metin, "api_metni": True, "aday": True}


def _havuz(kaynaklar):
    from motor.testler.test_kaynak_dogrulama import SahteAg
    return kk.havuz_olustur("Örnekova Savaşı", kaynaklar, kd.KaynakDogrulayici(SahteAg(dns={}).istemci()),
                            ["Örnekova", "Savaşı"])


def test_ocr_bagimli_destek_ocrsiz_destek_varken_sayilir():
    iddia = "Örnekova Savaşı 11 Ağustos 1501 tarihinde Demir Han ile Taş Bey arasında yapıldı."
    ana = dict(_api("A", "dergi-a", iddia), aday=False)
    ocr = _api("B", "dergi-b", "Örnekova Savaşı ı ı Ağustos ı501 tarihinde Demir Han ile Taş Bey arasında yapıldı.")
    h = _havuz([ana, ocr])
    k = next(x for x in h["kayitlar"] if x["iddia"] == iddia)
    b = next(x for x in k["kaynaklar"] if x["id"] == "B")
    assert b["dogrulama"]["ocr_bagimli"] is True and not b.get("sayilmadi")
    assert "ı ı Ağustos ı501" in b["dogrulama"]["supporting_excerpt"]   # alıntı özgün metinden
    assert k["bagimsiz_kaynak_sayisi"] == 2


def test_yalniz_ocr_bagimli_destek_tek_basina_kanit_sayilmaz():
    destek = [{"id": "B", "kume": 1, "teyit_turu": "icerik", "dogrulama": {"ocr_bagimli": True}},
              {"id": "C", "kume": 2, "teyit_turu": "icerik", "dogrulama": {"ocr_bagimli": True}}]
    kk.ocr_tek_basina_isaretle(destek)
    assert all(x["sayilmadi"] == "ocr_onarimina_bagli_tek_basina" for x in destek)
    karisik = [{"id": "A", "kume": 0, "teyit_turu": "icerik", "dogrulama": {"ocr_bagimli": False}},
               {"id": "B", "kume": 1, "teyit_turu": "icerik", "dogrulama": {"ocr_bagimli": True}}]
    assert not any(x.get("sayilmadi") for x in kk.ocr_tek_basina_isaretle(karisik))
    k = {"id": "x", "iddia": "x", "yil": 1501, "olay_id": "olay_1501", "karsi_kume_sayisi": 0, "kaynaklar": destek,
         "sayilar": [], "bagimsiz_kaynak_sayisi": 0, "tarih_teyit_kume_sayisi": 0, "sayi_teyit_kume_sayisi": 0,
         "iddia_atomlari": {}}
    kk.sayisal_koruma([k])
    assert k["durum"] == "belirsiz"                                 # yalnız OCR'a bağlı destek → doğrulanmış değil


# ================================================================== 1a. kaynakça / dipnot dışlama

OTLUK = {"metin": "Osmanlı Devleti 1473'te Otlukbeli Savaşı ile Akkoyunlu Devleti'ni yendi.",
         "olay_terimleri": ["Otlukbeli", "Savaşı"]}


@pytest.mark.parametrize("satir", [
    "↑ TSK (1986). Battle of Otlukbeli (PDF). Ankara: Genelkurmay Basımevi.",
    "^ TSK (1986). Otlukbeli Savaşı (PDF).",
    "[dipnot 3] Bk. Otlukbeli Savaşı, Ankara 1986, s. 44-45.",
    "BİBLİYOGRAFYA: Otlukbeli Savaşı, Ankara 1986; Setton, The Papacy and the Levant, II, 222-223, 272, 311-321.",
    "Woods, The Aqquyunlu, Minneapolis 1976, ISBN 0-88297-000-0, Otlukbeli 1986.",
])
def test_kaynakca_satiri_yil_celiskisi_uretmez(satir):
    assert ia.kaynakca_mi(satir)
    r = kd.icerik_dogrula(satir, OTLUK)
    assert r["destek_sinifi"] != "contradicts" and r["celiski"] == [], (satir, r["celiski"])


def test_kaynakca_basligindan_sonraki_paragraflar_kaynakca_sayilir():
    m = ("Otlukbeli Savaşı 1473 yılında yapıldı ve Osmanlı Devleti Akkoyunlu Devleti'ni yendi.\nBİBLİYOGRAFYA\n"
         "Otlukbeli Seferi Raporu, Genelkurmay Harp Tarihi Başkanlığı, Ankara 1986, toplam 120 sayfa.\n")
    w = kd._pencereler(m)
    assert [x.kaynakca for x in w] == [False, True]


def test_duzyazi_kaynakca_sanilmaz():
    for p in ["Osmanlı ordusu 11 Ağustos 1473 günü Otlukbeli ovasında Akkoyunlu kuvvetleriyle karşılaştı.",
              "Otlukbeli Savaşı (1473), Doğu Anadolu'da Osmanlı hâkimiyetinin yolunu açtı."]:
        assert not ia.kaynakca_mi(p), p


def test_kaynakca_sayfa_numaralari_sayi_celiskisi_uretmez():
    i = {"metin": "Mehmed II's Ottoman army numbered 70,000 men at Otlukbeli.", "olay_terimleri": ["Otlukbeli", "Battle"]}
    w = "Setton, The Papacy and the Levant: Mehmed II, Ottoman army at Otlukbeli, II, 222-223, 272, 311-321 men."
    r = kd.icerik_dogrula(w, i)
    assert r["destek_sinifi"] != "contradicts" and "sayi" not in r["celiski"]


def test_gercek_yil_celiskisi_hala_yakalanir():
    r = kd.icerik_dogrula("Otlukbeli Savaşı 1474 yılında Osmanlı Devleti ile Akkoyunlu Devleti arasında yapıldı.", OTLUK)
    assert r["destek_sinifi"] == "contradicts" and "yil" in r["celiski"]


# ================================================================== 1b. genel olay kelimeleri

@pytest.mark.parametrize("pencere", [
    "1071 Malazgirt Savaşı ile başlayan süreç Osmanlı Devleti ve Akkoyunlu Devleti dönemine uzandı; Otlukbeli de anılır.",
    "Osmanlı Devleti ile Safevîler arasındaki Çaldıran Savaşı (1514), Otlukbeli ve Akkoyunlu Devleti sonrası dönemi kapattı.",
    "Sürgünler (1453-1514). Savaşların ardından Osmanlı Devleti Akkoyunlu Devleti topraklarına yerleşimciler gönderdi.",
    "The Battle of Chaldiran (1514) followed decades after Otlukbeli; the Ottoman state and Akkoyunlu realm declined.",
])
def test_baska_savaslarin_yillari_otlukbeli_1473_ile_celismez(pencere):
    r = ia.degerlendir([pencere], OTLUK)
    assert r["destek_sinifi"] != "contradicts" and r["celiski"] == [], (pencere, r["celiski"])


def test_yalniz_genel_olay_sozcugu_yil_baglamaz_ve_olay_baglami_kurmaz():
    tok = ia._tokenler("Savaşı 1514 yılında yapıldı")
    assert ia._olay_yili_bagli(tok, ["savas"]) == []
    assert ia._olay_yili_bagli(ia._tokenler("Otlukbeli Savaşı (1473) ve Çaldıran Savaşı (1514)"), ["otluk", "savas"]) == [1473]
    a = ia.atomlar(OTLUK)
    r = ia.pencere_degerlendir("Bu savaş 1514 yılında yapıldı.", dict(a, _olay_yili=[1473], _sayi_baglam=[]))
    assert r["atomlar"]["olay"] is False and r["celiski"] == []


# ================================================================== 1c. sayı + ölçü + özne/birlik + olay

def test_farkli_ordu_sayilari_celiski_sayilmaz():
    w = "Otlukbeli'de Osmanlı ordusu 70.000 askerden oluşuyordu, Akkoyunlu ordusu ise 40.000 kişiydi."
    for metin in ("Otlukbeli'de Osmanlı ordusu 70.000 askerden oluşuyordu.", "Otlukbeli'de Akkoyunlu ordusu 40.000 kişiydi."):
        r = ia.degerlendir([w], {"metin": metin, "olay_terimleri": ["Otlukbeli"]})
        assert r["destek_sinifi"] != "contradicts", (metin, r)
    r = ia.degerlendir(["Otlukbeli'de Akkoyunlu ordusu 100.000 kişiydi."],
                       {"metin": "Otlukbeli'de Osmanlı ordusu 70.000 askerden oluşuyordu.", "olay_terimleri": ["Otlukbeli"]})
    assert r["destek_sinifi"] != "contradicts"


def test_ayni_ordu_farkli_rakam_yakalanir():
    i = {"metin": "Otlukbeli'de Osmanlı ordusu 70.000 askerden oluşuyordu.", "olay_terimleri": ["Otlukbeli"]}
    r = ia.degerlendir(["Otlukbeli'de Osmanlı ordusu 100.000 askerden oluşuyordu."], i)
    assert r["destek_sinifi"] == "contradicts" and "sayi" in r["celiski"]
    i2 = {"metin": "At Otlukbeli the Ottoman army numbered 70,000 men.", "olay_terimleri": ["Otlukbeli"]}
    r2 = ia.degerlendir(["At Otlukbeli the Ottoman army numbered 100 thousand soldiers."], i2)
    assert r2["destek_sinifi"] == "contradicts"


def test_olcu_kelime_siniri_men_substring_degil():
    assert ia._olcu_kelime("men") == "ordu" and ia._olcu_kelime("document") is None
    assert ia._olcu_kelime("comments") is None and ia._olcu_kelime("women") is None
    i = {"metin": "At Otlukbeli the Ottoman army numbered 70,000 men.", "olay_terimleri": ["Otlukbeli"]}
    r = ia.degerlendir(["At Otlukbeli the Ottoman archive document 120 comments survived."], i)
    assert r["destek_sinifi"] != "contradicts"


def test_baska_olayin_rakami_celiski_sayilmaz():
    i = {"metin": "Otlukbeli'de Osmanlı ordusu 70.000 askerden oluşuyordu.", "olay_terimleri": ["Otlukbeli"]}
    r = ia.degerlendir(["Otlukbeli'den sonra 1514'te Osmanlı ordusu 120.000 askerle doğuya yürüdü."], i)
    assert r["destek_sinifi"] != "contradicts"


def test_ozne_belirsiz_rakam_celiski_sayilmaz():
    i = {"metin": "Otlukbeli'de ordu 70.000 askerden oluşuyordu.", "olay_terimleri": ["Otlukbeli"]}
    r = ia.degerlendir(["Otlukbeli'de ordu 100.000 askerden oluşuyordu."], i)
    assert r["destek_sinifi"] != "contradicts"


def test_iddia_sayilari_taraf_tasir():
    s = kk._sayilar("Osmanlı ordusu 70.000 askerden oluşuyordu, Akkoyunlu ordusu ise 40.000 kişiydi.")
    assert [(x["deger"], x["olcu_turu"], x["taraf"]) for x in s] == [(70000, "ordu", ["osman"]), (40000, "ordu", ["akkoy"])]
    assert kk._sayilar("Belge 120 yorum içeriyor, documents and comments 300.")[0]["olcu_turu"] == "diger"


def _kayit(kid, deger, taraf, kume, olay="olay_1473"):
    return {"id": kid, "iddia": kid, "yil": None, "olay_id": olay, "karsi_kume_sayisi": 0,
            "kaynaklar": [{"kume": kume, "teyit_turu": "icerik"}],
            "sayilar": [{"deger": deger, "olcu_turu": "ordu", "taraf": taraf}],
            "bagimsiz_kaynak_sayisi": 2, "tarih_teyit_kume_sayisi": 2, "sayi_teyit_kume_sayisi": 2, "iddia_atomlari": {}}


def test_havuz_kumeler_arasi_farkli_ordu_rakamlari_celiski_degil_ayni_ordu_celiski():
    k = [_kayit("osm", 70000, ["osman"], 0), _kayit("akk", 40000, ["akkoy"], 1)]
    kk.sayisal_koruma(k)
    assert all("celiski" not in x for x in k) and [x["durum"] for x in k] == ["dogrulanmis", "dogrulanmis"]
    k2 = [_kayit("osm1", 70000, ["osman"], 0), _kayit("osm2", 100000, ["osman"], 1)]
    kk.sayisal_koruma(k2)
    assert all(x["durum"] == "tartismali" and x["celiski"]["taraf"] == ["osman"] for x in k2)
    assert {d["deger"] for d in k2[0]["celiski"]["degerler"]} == {70000, 100000}   # ortalama yok, ayrı değerler
    k3 = [_kayit("osm1", 70000, ["osman"], 0, "olay_1473"), _kayit("osm2", 120000, ["osman"], 1, "olay_1514")]
    kk.sayisal_koruma(k3)
    assert all("celiski" not in x for x in k3)                     # farklı olay
    k4 = [_kayit("a", 70000, [], 0), _kayit("b", 100000, [], 1)]
    kk.sayisal_koruma(k4)
    assert all("celiski" not in x for x in k4)                     # özne belirsiz → karşılaştırılmaz


# ================================================================== mutasyon boşluklarını kapatan hedefli testler

def test_ocr_onarimli_pencere_celiski_uretmez():
    """OCR onarımı tek başına kanıt değildir: onarım sonrası ortaya çıkan farklı yıl çelişki sayılmaz."""
    ozgun = "Otlukbeli Savaşı ı474 yılında Osmanlı Devleti ile Akkoyunlu Devleti arasında yapıldı ve uzun sürdü."
    r = kd.icerik_dogrula(ozgun, OTLUK)
    assert r["ocr_duzeltmeli"] and r["destek_sinifi"] != "contradicts" and r["celiski"] == []
    onarilmis = ozgun.replace("ı474", "1474")                     # aynı metin OCR'sız: çelişki yakalanır
    assert kd.icerik_dogrula(onarilmis, OTLUK)["destek_sinifi"] == "contradicts"


def test_yedek_secimi_gecisten_sonra_hic_aday_vermez(monkeypatch):
    g, istek, _ = _saglayici(monkeypatch, lambda m, n: (503, "x") if m == BIRINCIL else _y200("ok"))
    assert g._yedek_sec(BIRINCIL) == YEDEK and g._yedek_sec(UCUNCU) is None   # sonda: sonrası yok
    g.tamamla("x", "anlati", {})
    assert g._yedek_sec(BIRINCIL) is None and g._yedek_sec(YEDEK) is None    # tek atış kullanıldı


def test_yedege_gecildikten_sonra_yedek_baska_hata_verirse_birincile_donulmez(monkeypatch):
    sayac = {"yedek": 0}

    def d(m, n):
        if m == BIRINCIL:
            return 503, "x"
        sayac["yedek"] += 1
        return _y200("p1") if sayac["yedek"] == 1 else (500, "err")
    g, istek, _ = _saglayici(monkeypatch, d, en_cok_tekrar=1)
    assert g.tamamla("x", "anlati", {"bolum": "1"}) == "p1"
    with pytest.raises(gm.GercekUretimHatasi) as e:
        g.tamamla("y", "anlati", {"bolum": "2"})
    assert e.value.sinif == "sunucu"
    assert istek == [BIRINCIL] * 3 + [YEDEK] * 3                    # 2. parça: yalnız yedek (500 ×2), birincil/3. yok


@pytest.mark.parametrize("sinif,shorts_cagrilir", [("asiri_yuk", False), ("zaman_asimi", True), ("ag", True),
                                                    ("sunucu", True)])
def test_saglayici_disinda_firlayan_hata_sinifina_gore_kisa_devre(monkeypatch, sinif, shorts_cagrilir):
    from motor.testler.test_kaynak_dogrulama import _havuz as gercek_havuz
    cagrilan = []

    def fabrika(m, anahtar, kaynak, log_fn):
        cagrilan.append(m)
        if m == "uzun":
            raise gm.GercekUretimHatasi(f"sahte {sinif}", sinif)
        return gm.GeminiLLMProvider(tasiyici=lambda *a: (429, "quota"), uyku=lambda s: None, anahtar=anahtar)
    monkeypatch.setattr(cdr, "_gemini", fabrika)
    r = {"asamalar": {}, "planlar": {}}
    cdr._gemini_asamasi(r, "Örnekova Muharebesi", ["uzun", "shorts"], gercek_havuz(), ANAHTAR, "GEMINI_DRYRUN_KEY")
    assert ("shorts" in cagrilan) is shorts_cagrilir
    assert (r["asamalar"]["3_gemini_shorts"]["durum"] == "atlandi_asiri_yuk") is (not shorts_cagrilir)
