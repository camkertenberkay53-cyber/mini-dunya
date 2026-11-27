"""Faz-56 — araştırma motoru güvenilirlik düzeltmeleri (ağsız, deterministik).

Run 45956710301 bulguları:
  (a) PDF metni satır satır pencerelere bölündü; TDV PDF'leri hiçbir iddiayı doğrulayamadı.
  (b) %50 kelime örtüşmesi, yalnızca savaşı anan kaynakları "doğrulayıcı" saydı.
  (c) Kaynak bazında başarısızlık nedeni görünmüyordu.
  (d) Dosya paylaşım barındırıcıları (Discord CDN) getirilmeye çalışıldı.
"""
from __future__ import annotations

import json
import unicodedata

import pytest

from motor.orkestrasyon import iddia_atom as ia
from motor.orkestrasyon import kaynak_dogrulayici as kd
from motor.orkestrasyon import kaynak_kesif as kk
from motor.orkestrasyon.pdf_normal import normalize_sayfalar
from motor.testler.test_kaynak_dogrulama import GENEL_IP, SahteAg, _pdf

IDDIA = {"metin": "Anadolu'nun birliğinin sağlanmasında bir dönüm noktası olan Örnekova Savaşı, 11 Ağustos 1501 "
                  "tarihinde Demir Han ile Taş Bey arasında vuku buldu.", "olay_terimleri": ["Örnekova", "Savaşı"]}


# ------------------------------------------------------------------ 1–4: PDF normalizasyonu

SAYFA1 = """ÖRNEKOVA SAVAŞI
Demir Han ile Taş Bey arasında 11 Ağus-
tos 1501 tarihinde Örnekova mevkiinde yapılan ve
Demir Han'ın Taş Bey karşısında ka-
zandığı zaferle sonuçlanan meydan muharebesi. Ak-
Koyunlu hükümdarının ordusu savaşta dağıldı ve
bölge tarihinde bu zafer büyük önem taşıdı.
Savaşın arka planı uzun bir rekabete dayanır.
1 Bk. Âşıkpaşazâde, Târih, s. 120.
214"""
SAYFA2 = """ÖRNEKOVA SAVAŞI
Taş Bey yenilgiden sonra doğuya çekildi ve
tarihinde ilk kez barış istedi; bu tarih
inde yeni bir dönem başladı.
Bu gelişme bölgede yeni bir dönem başlattı.
215"""


def test_1_pdf_satir_sonlari_paragrafta_birlesir_ve_dogrulama_gecer():
    n = normalize_sayfalar([SAYFA1])
    assert n["paragraflar"][1] == "ÖRNEKOVA SAVAŞI"            # tek sayfa: başlık silinmez ama ayrı paragraf
    govde = n["paragraflar"][2]
    assert "\n" not in govde and govde.startswith("Demir Han ile Taş Bey arasında 11 Ağustos 1501 tarihinde Örnekova")
    ham_satirli = SAYFA1   # eski davranış: her satır ayrı pencere
    eski = kd.icerik_dogrula(ham_satirli, {"metin": "Örnekova muharebesi 11 Ağustos 1501 tarihinde Demir Han ile Taş Bey "
                                                    "arasında yapıldı.", "olay_terimleri": ["Örnekova"]})
    yeni = kd.icerik_dogrula(n["metin"], {"metin": "Örnekova muharebesi 11 Ağustos 1501 tarihinde Demir Han ile Taş Bey "
                                                   "arasında yapıldı.", "olay_terimleri": ["Örnekova"]})
    assert eski["verification_status"] == "content_mismatch" and yeni["verification_status"] == "verified"


def test_2_tire_ile_bolunmus_kelimeler_ve_bilesik_ad():
    m = normalize_sayfalar([SAYFA1])["metin"]
    assert "Ağustos" in m and "Ağus-" not in m and "kazandığı" in m and "ka-" not in m
    assert "Ak-Koyunlu" in m                                   # büyük harfle süren satır: bileşik ad tiresi korunur
    yumusak = normalize_sayfalar(["Bu mu­\nharebe bölgede yapıldı ve uzun sürdü.\nİkinci satır burada."])["metin"]
    assert "muharebe" in yumusak


def test_2b_tiresiz_bolunme_yalniz_belgede_kanit_varsa_birlesir():
    m = normalize_sayfalar([SAYFA2])["metin"]
    assert "bu tarihinde" in m                                  # "tarihinde" belgede geçiyor → "tarih"+"inde" birleşti
    m2 = normalize_sayfalar(["Kale kuşatması uzun sür\nmüş ve şehir zor günler yaşamış; halk dağılmış.\nSon satır."])["metin"]
    assert "sür müş" in m2                                      # kanıt yok → kelime uydurulmaz, boşlukla ayrılır


def test_3_turkce_karakterler_nfc_ve_bagli_harfler():
    ayrik = unicodedata.normalize("NFD", "İĞŞÇÖÜ ığşçöü Âşıkpaşazâde")
    m = normalize_sayfalar([ayrik + " ﬁ ﬂ\nikinci satır metni burada."])["metin"]
    assert "İĞŞÇÖÜ ığşçöü Âşıkpaşazâde" in m and "fi fl" in m
    assert unicodedata.is_normalized("NFC", m)


def test_4_sayfa_sinirlari_baslik_altbilgi_dipnot_ve_ham_metin():
    n = normalize_sayfalar([SAYFA1, SAYFA2])
    p = n["paragraflar"]
    assert p[0] == "[s. 214]" and "[s. 215]" in p                # basılı sayfa numarası korunur
    assert not any(x == "ÖRNEKOVA SAVAŞI" for x in p)           # tekrar eden başlık ana metinde yok …
    assert {"sayfa": 1, "satir": "ÖRNEKOVA SAVAŞI"} in n["kaldirilan"]   # … ama kayıtlı
    assert n["dipnotlar"] == [{"sayfa": 1, "metin": "1 Bk. Âşıkpaşazâde, Târih, s. 120."}]
    assert any(x.startswith("[dipnot s. 214]") for x in p)
    i215 = p.index("[s. 215]")
    assert not any("Taş Bey yenilgiden" in x for x in p[:i215])  # sayfalar arası birleştirme yok
    pdf = _pdf(["Birinci sayfa Örnekova metni burada yer alır ve uzun bir cümle olarak devam eder.".encode("latin-1", "replace").decode("latin-1")])
    d = kd.pdf_cikar(pdf)
    assert d["ham"] and d["metin"] and d["neden_kodu"] == "pdf_metni" and d["metin"].startswith("[pdf s. 1]")


def test_4b_tek_sayfalik_kisa_metinde_kenar_ayiklamasi_yok():
    n = normalize_sayfalar(["Kısa ama gerçek içerik."])
    assert n["kaldirilan"] == [] and "Kısa ama gerçek içerik." in n["metin"]


# ------------------------------------------------------------------ 5–7: atomik doğrulama

@pytest.mark.parametrize("ad,pencere,beklenen", [
    ("5_yalniz_ad", "Örnekova gibi büyük savaşlar dönemin siyasetini belirledi.", "mention"),
    ("5_ad_ve_yil_listesi", "Dandanakan (1040), Kösedağ (1243), Örnekova (1501) gibi savaşlar dönemi belirledi.", "partial"),
    ("6_yalniz_yil", "Demir Han 1501 yılında Örnekova Savaşı ile Taş Bey'i yenilgiye uğrattı.", "partial"),
    ("7_tam", "Anadolu'nun birliğinin sağlanmasında bir dönüm noktası olan Örnekova Savaşı, 11 Ağustos 1501 tarihinde "
              "Demir Han ile Taş Bey arasında vuku bulmuştur.", "supported"),
    ("7_yorumsuz_tam_tarih", "Örnekova Savaşı 11 Ağustos 1501 tarihinde Demir Han ile Taş Bey arasında yapıldı.", "partial"),
    ("cel_gun", "Örnekova Savaşı 1 Ağustos 1501 tarihinde Demir Han ile Taş Bey arasında yapıldı; dönüm noktası oldu.",
     "contradicts"),
    ("cel_yil", "Örnekova Savaşı 1499 yılında Demir Han ile Taş Bey arasında yapıldı.", "contradicts"),
    ("iliski_celiski_degil", "Örnekova Savaşı'nın ardından 1502 yılında Demir Han ile Taş Bey barış yaptı.", "partial"),
    ("ilgisiz", "Kale on sekizinci yüzyılda onarıldı ve garnizon yeniden düzenlendi.", "no_evidence"),
])
def test_5_6_7_destek_siniflari_etiketli_vaka_seti(ad, pencere, beklenen):
    """Eşikler (ICERIK_ESIGI, VARLIK_ESIGI) bu etiketli setle belirlendi; tek bir örtüşme oranı ölçüt değildir."""
    r = ia.degerlendir([pencere], IDDIA)
    assert r["destek_sinifi"] == beklenen, (ad, r["atomlar"], r["icerik_orani"], r["celiski"])


def test_6_yalniz_yili_dogrulayan_kaynak_gun_ayi_dogrulamaz():
    r = ia.degerlendir(["Demir Han 1501 yılında Örnekova Savaşı ile Taş Bey'i yendi."], IDDIA)
    assert r["atomlar"]["yil"] is True and r["atomlar"]["gun_ay"] is False and r["destek_sinifi"] != "supported"
    v = kd.icerik_dogrula("Demir Han 1501 yılında Örnekova Savaşı ile Taş Bey'i yendi.", IDDIA)
    assert v["verification_status"] == "content_mismatch" and v["destek_sinifi"] == "partial"


def test_7_kismi_destek_partial_ve_sayi_celiskisi():
    i = {"metin": "Muharebede Taş Bey 3.000 kayıp verdi ve geri çekildi.", "olay_terimleri": ["Örnekova"]}
    assert ia.degerlendir(["Muharebede Taş Bey 3.000 kayıp verdi."], i)["destek_sinifi"] == "partial"
    assert ia.degerlendir(["Muharebede Taş Bey 3.000 kayıp verdi ve ardından geri çekildi."], i)["destek_sinifi"] == "supported"
    j = {"metin": "Demir Han ordusu 40.000 askerden oluşuyordu.", "olay_terimleri": ["Örnekova"]}
    assert ia.degerlendir(["Demir Han ordusu 60.000 askerden oluşuyordu."], j)["destek_sinifi"] == "contradicts"


def _havuz(kaynaklar):
    ag = SahteAg(dns={})
    return kk.havuz_olustur("Örnekova Savaşı", kaynaklar, kd.KaynakDogrulayici(ag.istemci()), ["Örnekova", "Savaşı"])


def _api(kid, yay, metin):
    return {"id": kid, "url": f"https://doi.org/10.1/{kid}", "baslik": kid, "yayinci": yay, "tur": "akademik",
            "metin": metin, "api_metni": True, "aday": True}


def test_havuz_yalniz_anan_kaynaklar_bagimsiz_destek_sayilmaz_yorum_tek_kaynak():
    ana = _api("A", "dergi-a", IDDIA["metin"])
    ana["aday"] = False   # iddianın çıktığı kaynak
    anan = [_api(f"M{i}", f"dergi-{i}", f"Örnekova Savaşı (1501) sonrası bölgede {x} değişti.")
            for i, x in enumerate(["vergi düzeni", "ticaret yolları", "kale garnizonları"])]
    h = _havuz([ana] + anan)
    k = next(k for k in h["kayitlar"] if "dönüm noktası" in k["iddia"])
    assert k["bagimsiz_kaynak_sayisi"] == 1                     # 3 anan kaynak tam destek sayılmadı
    assert k["tarih_teyit_kume_sayisi"] == 1                    # gün-ay yalnız kendi kaynağında
    assert k["durum"] == "tartismali" and k["tek_kaynak_uyarisi"]
    assert not any(x["id"].startswith("M") for x in k["kaynaklar"])   # yalnız anan kaynak hiçbir teyit olarak girmez


def test_8_ayni_yayinci_ailesi_bagimsiz_degil():
    k = kk.bagimsizlik_kumeleri([
        {"id": "tr", "yayinci": kk.yayinci("https://tr.wikipedia.org/wiki/X")},
        {"id": "en", "yayinci": kk.yayinci("https://en.wikipedia.org/wiki/Y")},
        {"id": "tdv", "yayinci": kk.yayinci("https://cdn.islamansiklopedisi.org.tr/dosya/34/C1.pdf")},
        {"id": "tdv_arsiv", "yayinci": kk.yayinci("https://web.archive.org/web/2019/https://cdn2.islamansiklopedisi.org.tr/C2.pdf")},
        {"id": "oa1", "yayinci": "openalex:Belleten"}, {"id": "oa2", "yayinci": "openalex:Belleten"},
        {"id": "oa3", "yayinci": "openalex:OTAM"}])
    assert k["tr"] == k["en"] and k["tdv"] == k["tdv_arsiv"] and k["oa1"] == k["oa2"]
    assert len({k["tr"], k["tdv"], k["oa1"], k["oa3"]}) == 4


def test_8b_ayni_yayinci_iki_kopyasi_tam_destek_sayisini_artirmaz():
    ana = _api("A", "dergi-a", "Örnekova Savaşı 11 Ağustos 1501 tarihinde Demir Han ile Taş Bey arasında yapıldı.")
    ana["aday"] = False
    b1 = _api("B1", "dergi-b", "Örnekova Savaşı 11 Ağustos 1501 tarihinde Demir Han ile Taş Bey arasında yapıldı ve bitti.")
    b2 = _api("B2", "dergi-b", "Demir Han ile Taş Bey 11 Ağustos 1501 tarihinde Örnekova Savaşı'nda karşılaştı ve yapıldı.")
    h = _havuz([ana, b1, b2])
    k = next(k for k in h["kayitlar"] if k["kaynak_kesfi"] == "A")
    assert k["bagimsiz_kaynak_sayisi"] == 2 and k["durum"] == "dogrulanmis"   # A + dergi-b (B1, B2 tek küme)


# ------------------------------------------------------------------ 9: erişim / PDF / içerik nedenleri ayrımı

def _ag(sayfalar):
    return SahteAg(dns={"ornek.org": [GENEL_IP]}, sayfalar={("ornek.org", "/" + k): v for k, v in sayfalar.items()})


def test_9_403_ve_pdf_hatalari_ve_bos_icerik_ayri_kodlanir():
    ag = _ag({"engel": (403, {}, b""), "bozuk": (200, {"Content-Type": "application/pdf"}, b"%PDF-1.4 bozuk"),
              "bos_pdf": (200, {"Content-Type": "application/pdf"}, _pdf([" "])),
              "js": (200, {"Content-Type": "text/html"}, b"<html><body><script>app()</script></body></html>"),
              "resim": (200, {"Content-Type": "image/png"}, b"\x89PNG"), "yok": (404, {}, b""),
              "sunucu": (503, {}, b""), "iyi": (200, {"Content-Type": "application/pdf"},
                                               _pdf(["Ornekova Savasi 11 Agustos 1501 tarihinde Demir Han ile Tas Bey arasinda yapildi."]))})
    ag.hata[("ornek.org", "/yavas")] = kd.AgHatasi("zaman_asimi")
    d = kd.KaynakDogrulayici(ag.istemci(), uyku=lambda s: None)
    beklenen = {"engel": "http_403", "bozuk": "pdf_parse_hatasi", "bos_pdf": "pdf_metin_yok", "js": "bos_icerik",
                "resim": "desteklenmeyen_belge", "yok": "http_404", "sunucu": "http_5xx", "yavas": "timeout", "iyi": "ok"}
    for yol, kod in beklenen.items():
        d.sayfa(f"https://ornek.org/{yol}")
        e = d.erisim[f"https://ornek.org/{yol}"]
        assert e["neden_kodu"] == kod, (yol, e)
    assert d.erisim["https://ornek.org/engel"]["http_status"] == 403 and "belge" not in d.erisim["https://ornek.org/engel"]
    assert d.erisim["https://ornek.org/bozuk"]["http_status"] == 200 and d.erisim["https://ornek.org/bozuk"]["belge"] == "pdf"
    assert d.ham_metin["https://ornek.org/iyi"] and d.erisim["https://ornek.org/iyi"]["pdf"]["sayfa_sayisi"] == 1


def test_9b_kaynak_raporu_kaynak_bazinda_neden_ve_sonuc():
    ag = _ag({"engel": (403, {}, b""), "bozuk": (200, {"Content-Type": "application/pdf"}, b"%PDF-1.4 bozuk"),
              "anan": (200, {"Content-Type": "text/html"}, "<p>Örnekova Savaşı bölge tarihinde sık anılır ve çokça yazılır.</p>".encode())})
    ana = _api("A", "dergi-a", "Örnekova Savaşı 11 Ağustos 1501 tarihinde Demir Han ile Taş Bey arasında yapıldı.")
    ana["aday"] = False
    aday = [{"id": n, "url": f"https://ornek.org/{n}", "baslik": n, "yayinci": f"y-{n}", "tur": "genel_web", "aday": True}
            for n in ("engel", "bozuk", "anan")]
    h = kk.havuz_olustur("Örnekova Savaşı", [ana] + aday, kd.KaynakDogrulayici(ag.istemci()), ["Örnekova", "Savaşı"])
    r = h["kaynak_raporu"]
    assert r["engel"]["dogrulama_sonucu"] == "erisilemedi:http_403" and r["engel"]["erisim"]["http_status"] == 403
    assert r["bozuk"]["dogrulama_sonucu"] == "erisilemedi:pdf_parse_hatasi"    # HTTP başarılı, sorun PDF'te
    assert r["anan"]["dogrulama_sonucu"] == "icerik_uyusmazligi" and r["anan"]["destek"] == {"mention": 1}
    assert r["A"]["dogrulama_sonucu"] == "destekledi" and r["A"]["erisim"]["neden_kodu"] == "api_metni"


# ------------------------------------------------------------------ 10: güvenlik ve kaynak politikası

@pytest.mark.parametrize("url", [
    "https://cdn.discordapp.com/attachments/1/2/kitap.pdf", "https://media.discordapp.net/x.pdf",
    "https://web.archive.org/web/20231225195151/https://cdn.discordapp.com/attachments/1/kitap.pdf",
    "https://z-lib.io/book/1", "https://singlelogin.re.z-library.sk/x", "https://libgen.is/book", "https://annas-archive.org/md5/1",
    "https://sci-hub.se/10.1/x", "https://www.scribd.com/document/1", "https://mega.nz/file/x"])
def test_10_dosya_paylasim_barindiricilari_aga_cikmadan_reddedilir(url):
    ag = SahteAg(dns={})
    d = kd.KaynakDogrulayici(ag.istemci())
    r = d.dogrula(url, IDDIA)
    assert r["verification_status"] == "unverified" and r["neden"].startswith("politika_reddi")
    assert d.erisim[url]["neden_kodu"] == "politika_reddi" and ag.baglantilar == []


def test_10b_politika_ssrfyi_gevsetmez_ve_mesru_kaynaklari_engellemez():
    for u in ("https://dergipark.org.tr/x", "https://tr.wikipedia.org/wiki/X", "https://archive.org/details/kitap",
              "https://cdn.islamansiklopedisi.org.tr/dosya/1.pdf", "https://web.archive.org/web/2019/https://dergipark.org.tr/x"):
        assert kd.kaynak_politikasi(u) == (True, ""), u
    ag = SahteAg(dns={"ic.ornek.org": ["10.0.0.5"]})
    d = kd.KaynakDogrulayici(ag.istemci(), politika=lambda u: (True, ""))   # politika her şeye izin verse bile …
    r = d.dogrula("https://ic.ornek.org/x", IDDIA)
    assert r["neden"].startswith("guvenlik_reddi") and ag.baglantilar == []  # … SSRF katmanı özel IP'yi reddeder
    for url in ("http://127.0.0.1/", "http://169.254.169.254/latest/meta-data", "file:///etc/passwd"):
        assert kd.KaynakDogrulayici(SahteAg(dns={}).istemci(), politika=lambda u: (True, "")).dogrula(url, IDDIA)[
            "neden"].startswith("guvenlik_reddi")


def test_10c_sinirlar_degismedi():
    assert kd.EN_COK_BAYT == 2 * 1024 * 1024 and kd.PDF_EN_COK_BAYT == 3 * 1024 * 1024
    assert kd.PDF_EN_COK_SAYFA == 10 and kd.EN_COK_YONLENDIRME == 3 and kd.ZAMAN_ASIMI <= 12.0
    json.dumps(kd.REDDEDILEN_HOSTLAR)


def test_yorum_tek_kaynakta_ise_tarih_iki_kumede_teyitli_olsa_da_tartismali():
    ana = _api("A", "dergi-a", IDDIA["metin"])
    ana["aday"] = False
    tarih = _api("T", "dergi-t", "Örnekova Savaşı 11 Ağustos 1501 tarihinde Demir Han ile Taş Bey arasında vuku buldu.")
    h = _havuz([ana, tarih])
    k = next(k for k in h["kayitlar"] if "dönüm noktası" in k["iddia"])
    assert k["tarih_teyit_kume_sayisi"] == 2 and k["bagimsiz_kaynak_sayisi"] == 1   # tarih 2 kümede; yorum yalnız A'da
    assert k["durum"] == "tartismali" and k["tek_kaynak_uyarisi"] and "yorum" in k["celiski_notu"]
    ikinci = _api("Y", "dergi-y", "Anadolu'nun birliğinin sağlanmasında dönüm noktası olan Örnekova Savaşı 11 Ağustos 1501 "
                                  "tarihinde Demir Han ile Taş Bey arasında vuku bulmuştur.")
    h2 = _havuz([ana, tarih, ikinci])
    k2 = next(k for k in h2["kayitlar"] if k["kaynak_kesfi"] == "A")
    assert k2["bagimsiz_kaynak_sayisi"] == 2 and k2["durum"] == "dogrulanmis"
