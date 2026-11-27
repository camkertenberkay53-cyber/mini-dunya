"""Faz-55 — kaynak keşfi, SSRF/DNS korumalı canlı doğrulayıcı, bağımsızlık, sayısal koruma, GeminiLLMProvider.

Bütün testler AĞSIZ ve deterministiktir: sahte DNS çözücü, sahte (IP'ye sabitli) bağlayıcı, sabit HTML/JSON
fixture'ları ve sahte Gemini taşıyıcısı. Canlı uçtan uca dry-run ayrı ve isteğe bağlıdır (CI bilgi adımı).
"""
from __future__ import annotations

import json
import os
import re
import statistics
import urllib.parse

import pytest

from motor.orkestrasyon import gemini as gm
from motor.orkestrasyon import kaynak_dogrulayici as kd
from motor.orkestrasyon import kaynak_kesif as kk
from motor.orkestrasyon import senaryo_planlayici as sp
from motor.orkestrasyon.llm import MockLLMProvider

GENEL_IP = "93.184.216.34"
GENEL_IP2 = "151.101.1.1"


# ------------------------------------------------------------------ sahte ağ

class SahteAg:
    """host → [ip]; (host, yol) → (durum, başlıklar, gövde); uc_ip_ezme: soketin 'gerçekte' bağlandığı IP."""

    def __init__(self, dns=None, sayfalar=None, uc_ip_ezme=None, hata=None):
        self.dns = dns or {}
        self.sayfalar = sayfalar or {}
        self.uc_ip_ezme = uc_ip_ezme or {}
        self.hata = hata or {}
        self.baglantilar = []

    def cozucu(self, host, port):
        if host not in self.dns:
            raise OSError("NXDOMAIN")
        return list(self.dns[host])

    def baglayici(self, sema, host, port, ip, zaman):
        ag = self

        class B:
            def istek(self, yol, basliklar, en_cok):
                ag.baglantilar.append((sema, host, ip, yol))
                if (host, yol) in ag.hata:
                    raise ag.hata[(host, yol)]
                d = ag.sayfalar.get((host, yol), (404, {}, b"yok"))
                if callable(d):
                    d = d()
                durum, bas, govde = d
                return kd.HamYanit(durum, {k.lower(): v for k, v in bas.items()}, govde[: en_cok + 1],
                                   ag.uc_ip_ezme.get(host, ip))
        return B()

    def istemci(self, **k):
        return kd.GuvenliIstemci(cozucu=self.cozucu, baglayici=self.baglayici, **k)


HTML_UYUMLU = """<html><head><title>x</title><script>document.write('Kale 1999 yılında yıkıldı');</script>
<style>p{color:red}</style></head><body><nav>menü</nav>
<p>Giriş paragrafı, konu dışı bilgiler içerir.</p>
<p>Örnekova Muharebesi 1501 yılında Demir Han ile Taş Bey arasında Örnekova düzlüğünde yapıldı ve
Demir Han'ın zaferiyle sonuçlandı.</p><p>Sonraki yıllarda bölgede ticaret gelişti.</p></body></html>""".encode()
HTML_UYUMSUZ = """<html><body><p>Örnekova düzlüğü verimli tarım alanlarıyla bilinir; 1650 yılında bir
kervansaray inşa edildi.</p><p>Bölge halkı hayvancılıkla geçinir.</p></body></html>""".encode()
IDDIA = {"metin": "Örnekova Muharebesi 1501 yılında Demir Han ile Taş Bey arasında yapıldı.",
         "olay_terimleri": ["Örnekova", "muharebe"]}


def _ag(**sayfa):
    dns = {"ornek.org": [GENEL_IP], "akademi.edu": [GENEL_IP2]}
    s = {("ornek.org", "/" + k): v for k, v in sayfa.items()}
    return SahteAg(dns=dns, sayfalar=s)


def _dog(ag, **k):
    uykular = []
    d = kd.KaynakDogrulayici(ag.istemci(), uyku=uykular.append, **k)
    d.uykular = uykular
    return d


# ------------------------------------------------------------------ HTTP sınıflaması + bağlamsal doğrulama

def test_200_uyumlu_verified_ve_supporting_excerpt():
    ag = _ag(uyumlu=(200, {"Content-Type": "text/html; charset=utf-8"}, HTML_UYUMLU))
    r = _dog(ag).dogrula("https://ornek.org/uyumlu", IDDIA)
    assert r["verification_status"] == "verified" and r["verification_method"] == "structured_and_contextual"
    assert r["year_match"] and r["event_match"] and r["entity_match"] and r["content_match"] and r["http_status"] == 200
    assert "1501" in r["supporting_excerpt"] and "Demir Han" in r["supporting_excerpt"]
    assert "document.write" not in r["supporting_excerpt"] and "1999" not in r["supporting_excerpt"]   # script çalışmaz/okunmaz


def test_200_icerik_uyumsuz_content_mismatch():
    ag = _ag(uyumsuz=(200, {"Content-Type": "text/html"}, HTML_UYUMSUZ))
    r = _dog(ag).dogrula("https://ornek.org/uyumsuz", IDDIA)
    assert r["http_status"] == 200 and r["verification_status"] == "content_mismatch"   # 200 ≠ doğrulandı
    assert r["year_match"] is False and "eksik" in r["neden"] and r["destek_sinifi"] == "mention"


def test_ayni_yil_baska_olay_ayni_paragrafta_degilse_dogrulanmaz():
    html = b"<p>1501 yilinda bir kervansaray yapildi.</p><p>Demir Han ile Tas Bey uzun yillar ticaret yapti.</p>"
    ag = _ag(dag=(200, {"Content-Type": "text/html"}, html))
    assert _dog(ag).dogrula("https://ornek.org/dag", IDDIA)["verification_status"] == "content_mismatch"


def test_403_unverified_olu_sayilmaz():
    ag = _ag(engel=(403, {}, b"Forbidden"))
    r = _dog(ag).dogrula("https://ornek.org/engel", IDDIA)
    assert r["verification_status"] == "unverified" and r["http_status"] == 403 and "sayılmaz" in r["neden"]


@pytest.mark.parametrize("kod", [404, 410])
def test_404_410_unreachable(kod):
    ag = _ag(yok=(kod, {}, b""))
    r = _dog(ag).dogrula("https://ornek.org/yok", IDDIA)
    assert r["verification_status"] == "unreachable" and r["http_status"] == kod


def test_5xx_ve_zaman_asimi_unverified():
    ag = _ag(hata=(503, {}, b""))
    assert _dog(ag).dogrula("https://ornek.org/hata", IDDIA)["verification_status"] == "unverified"
    ag2 = _ag()
    ag2.hata[("ornek.org", "/yavas")] = kd.AgHatasi("zaman_asimi")
    r = _dog(ag2).dogrula("https://ornek.org/yavas", IDDIA)
    assert r["verification_status"] == "unverified" and r["neden"] == "ag_zaman_asimi"


def test_429_kontrollu_bekleme_sinirli_tekrar():
    sira = [(429, {"Retry-After": "3"}, b""), (200, {"Content-Type": "text/html"}, HTML_UYUMLU)]
    ag = _ag(rl=lambda: sira.pop(0))
    d = _dog(ag)
    assert d.dogrula("https://ornek.org/rl", IDDIA)["verification_status"] == "verified" and d.uykular == [3.0]
    ag2 = _ag(rl2=(429, {"Retry-After": "999"}, b""))
    d2 = _dog(ag2)
    r = d2.dogrula("https://ornek.org/rl2", IDDIA)
    assert r["verification_status"] == "unverified" and r["neden"] == "rate_limit_asildi"
    assert len(d2.uykular) == 2 and max(d2.uykular) <= 10.0   # sınırlı ve tavanlı bekleme


def test_boyut_siniri():
    ag = _ag(buyuk=(200, {"Content-Type": "text/html"}, b"<p>" + b"a" * 5000 + b"</p>"))
    r = kd.KaynakDogrulayici(ag.istemci(en_cok_bayt=1000)).dogrula("https://ornek.org/buyuk", IDDIA)
    assert r["verification_status"] == "unverified" and r["neden"] == "ag_cok_buyuk"


def test_hassas_url_parametreleri_loglanmaz():
    ag = _ag(uyumlu=(200, {"Content-Type": "text/html"}, HTML_UYUMLU))
    r = _dog(ag).dogrula("https://ornek.org/uyumlu?api_key=GIZLI123&token=XYZ", IDDIA)
    assert "GIZLI123" not in json.dumps(r) and "XYZ" not in json.dumps(r) and "api_key=***" in r["url"]
    assert kd.url_gizle("https://kul:parola@ornek.org/a?x=1#p") == "https://ornek.org/a?x=***"


# ------------------------------------------------------------------ SSRF ve DNS rebinding

@pytest.mark.parametrize("url", ["http://localhost/a", "http://127.0.0.1/a", "http://[::1]/a", "http://10.0.0.5/a",
                                 "http://172.16.3.4/a", "http://192.168.1.1/a", "http://169.254.169.254/latest/meta-data",
                                 "http://[fe80::1]/a", "http://0.0.0.0/a", "http://[::ffff:127.0.0.1]/a",
                                 "http://ic.local/a", "ftp://ornek.org/a", "file:///etc/passwd", "gopher://ornek.org/"])
def test_ssrf_yasak_hedefler_baglanti_kurulmadan_reddedilir(url):
    ag = _ag()
    with pytest.raises(kd.GuvenlikHatasi):
        ag.istemci().getir(url)
    assert ag.baglantilar == []
    r = _dog(ag).dogrula(url, IDDIA)
    assert r["verification_status"] == "unverified" and r["neden"].startswith("guvenlik_reddi")


@pytest.mark.parametrize("kayitlar", [[GENEL_IP, "10.1.2.3"], ["fd00::1"], [GENEL_IP, "::1"], ["fe80::5"], ["100.64.1.1"]])
def test_dns_butun_a_aaaa_kayitlari_denetlenir(kayitlar):
    ag = SahteAg(dns={"karisik.org": kayitlar})
    with pytest.raises(kd.GuvenlikHatasi):
        ag.istemci().getir("https://karisik.org/")
    assert ag.baglantilar == []


def test_dns_rebinding_baglanilan_ip_dogrulanan_ip_degilse_reddedilir():
    ag = SahteAg(dns={"donek.org": [GENEL_IP]}, sayfalar={("donek.org", "/"): (200, {}, b"ok")},
                 uc_ip_ezme={"donek.org": "127.0.0.1"})
    with pytest.raises(kd.GuvenlikHatasi, match="dns_rebinding"):
        ag.istemci().getir("https://donek.org/")
    ag2 = SahteAg(dns={"donek.org": [GENEL_IP]}, sayfalar={("donek.org", "/"): (200, {}, b"ok")},
                  uc_ip_ezme={"donek.org": GENEL_IP2})   # başka bir genel IP de olsa sabitlenen IP değil
    with pytest.raises(kd.GuvenlikHatasi, match="dns_rebinding"):
        ag2.istemci().getir("https://donek.org/")


def test_yonlendirme_her_adimda_yeniden_denetlenir_ve_sinirli():
    ag = SahteAg(dns={"ornek.org": [GENEL_IP], "kotu.org": ["192.168.0.10"]}, sayfalar={
        ("ornek.org", "/r1"): (302, {"Location": "http://127.0.0.1/admin"}, b""),
        ("ornek.org", "/r2"): (301, {"Location": "https://kotu.org/x"}, b""),
        ("ornek.org", "/r3"): (302, {"Location": "file:///etc/passwd"}, b""),
        ("ornek.org", "/d0"): (302, {"Location": "/d1"}, b""), ("ornek.org", "/d1"): (302, {"Location": "/d2"}, b""),
        ("ornek.org", "/d2"): (302, {"Location": "/d3"}, b""), ("ornek.org", "/d3"): (302, {"Location": "/d4"}, b""),
        ("ornek.org", "/ok0"): (302, {"Location": "/ok1"}, b""), ("ornek.org", "/ok1"): (200, {}, b"tamam")})
    for yol in ("/r1", "/r2", "/r3", "/d0"):
        with pytest.raises(kd.GuvenlikHatasi):
            ag.istemci().getir("https://ornek.org" + yol)
    assert not any(b[1] == "kotu.org" or b[2] == "127.0.0.1" for b in ag.baglantilar)   # özel hedefe bağlanılmadı
    y = ag.istemci().getir("https://ornek.org/ok0")
    assert y.durum == 200 and len(y.zincir) == 2


def test_ip_izinli_tablosu():
    assert kd.ip_izinli(GENEL_IP) and kd.ip_izinli("2606:4700:4700::1111")
    for ip in ("127.0.0.1", "10.0.0.1", "172.31.255.255", "192.168.0.1", "169.254.1.1", "::1", "fe80::1", "fd12::1",
               "0.0.0.0", "224.0.0.1", "240.0.0.1", "::ffff:10.0.0.1", "100.64.0.1", "192.0.2.1"):
        assert not kd.ip_izinli(ip), ip


# ------------------------------------------------------------------ keşif, bağımsızlık, sayısal koruma

TR_METIN = ("Örnekova Muharebesi 1501 yılında Demir Han ile Taş Bey arasında Örnekova düzlüğünde yapıldı. "
            "Demir Han'ın ordusu yaklaşık 40.000 askerden oluşuyordu. "
            "Muharebede Taş Bey 3.000 kayıp verdi ve geri çekildi. "
            "Muharebenin ardından 1502 yılında Demir Han ile Taş Bey arasında barış antlaşması imzalandı. "
            "Muharebe bölgedeki güç dengesini uzun süre değiştirdi ve iki taraf arasındaki sınır hattı yeniden çizildi; "
            "kervan yolları yeni yönetimin denetimine geçti ve çevredeki şehirler bu düzene uyum sağladı.")
EN_METIN = ("The Battle of Ornekova was fought in 1501 between Demir Han and Tas Bey on the Ornekova plain. "
            "Demir Han's army numbered some 40,000 soldiers.")
AKADEMIK_HTML = ("<html><body><p>Örnekova Muharebesi 1501 yılında Demir Han ile Taş Bey arasında yapıldı; Demir Han "
                 "ordusunun 60.000 askerden oluştuğu kaydedilir.</p><p>Muharebede Taş Bey 3.000 kayıp verdi.</p>"
                 "</body></html>").encode()
AYNA_HTML = ("<html><body><p>" + TR_METIN + "</p><p>Kaynak: Vikipedi</p></body></html>").encode()


def _wp_ag():
    def api(dil, metin, pageid, baslik, extlinks, langlinks):
        return {"query": {"pages": [{"pageid": pageid, "title": baslik, "fullurl": f"https://{dil}.wikipedia.org/wiki/{urllib.parse.quote(baslik)}",
                                     "extract": metin, "extlinks": [{"url": u} for u in extlinks],
                                     "langlinks": langlinks}]}}
    sayfalar = {}

    def ekle_api(dil, baslik, metin, pageid, extlinks, langlinks):
        host = f"{dil}.wikipedia.org"

        def yanit():
            return (200, {"Content-Type": "application/json"}, json.dumps(api(dil, metin, pageid, baslik, extlinks, langlinks)).encode())
        return host, yanit

    class Ag(SahteAg):
        def baglayici(self, sema, host, port, ip, zaman):
            ag = self

            class B:
                def istek(self, yol, basliklar, en_cok):
                    ag.baglantilar.append((sema, host, ip, yol))
                    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(yol).query))
                    if host.endswith("wikipedia.org") and yol.startswith("/w/api.php"):
                        dil = host.split(".")[0]
                        if q.get("list") == "search":
                            g = {"query": {"search": [{"title": {"tr": "Örnekova Muharebesi", "en": "Battle of Ornekova"}[dil]}]}}
                        elif dil == "tr":
                            g = api("tr", "== Arka plan ==\n" + TR_METIN, 101, "Örnekova Muharebesi",
                                    ["https://akademi.edu/makale", "https://ayna-site.org/ornekova", "https://olu.org/x"],
                                    [{"lang": "en", "title": "Battle of Ornekova"}])
                        else:
                            g = api("en", EN_METIN, 202, "Battle of Ornekova", [], [])
                        return kd.HamYanit(200, {"content-type": "application/json"}, json.dumps(g).encode(), ip)
                    if "/api/rest_v1/page/summary/" in yol:
                        return kd.HamYanit(200, {"content-type": "application/json"}, json.dumps({"extract": "özet"}).encode(), ip)
                    if host == "tr.wikipedia.org":
                        return kd.HamYanit(200, {"content-type": "text/html"}, ("<p>" + TR_METIN + "</p>").encode(), ip)
                    if host == "en.wikipedia.org":
                        return kd.HamYanit(200, {"content-type": "text/html"}, ("<p>" + EN_METIN + "</p>").encode(), ip)
                    if host == "akademi.edu":
                        return kd.HamYanit(200, {"content-type": "text/html"}, AKADEMIK_HTML, ip)
                    if host == "ayna-site.org":
                        return kd.HamYanit(200, {"content-type": "text/html"}, AYNA_HTML, ip)
                    return kd.HamYanit(404, {}, b"", ip)
            return B()
    return Ag(dns={"tr.wikipedia.org": [GENEL_IP], "en.wikipedia.org": [GENEL_IP], "akademi.edu": [GENEL_IP2],
                   "ayna-site.org": ["185.199.108.153"], "olu.org": ["185.199.109.153"]})


def test_wikipedia_kesif_tr_en_dil_baglantisi_ve_dis_kaynak_adaylari():
    ag = _wp_ag()
    k = kk.WikipediaKesif(ag.istemci()).kesfet("Örnekova Muharebesi")
    ana = {x["id"]: x for x in k if not x["aday"]}
    assert set(ana) == {"wp_tr_101", "wp_en_202"} and ana["wp_tr_101"]["bolumler"] == ["Arka plan"]
    aday = {x["url"]: x for x in k if x["aday"]}
    assert aday["https://akademi.edu/makale"]["tur"] == "akademik" and aday["https://akademi.edu/makale"]["oncelik"] == 3
    assert all(x["tur"] == "ansiklopedi" and x["oncelik"] == 2 and x["yayinci"] == "Wikimedia" for x in ana.values())
    # EN maddesi arama ile değil, TR maddesinin dil bağlantısıyla bulundu
    en_arama = [b for b in ag.baglantilar if b[1] == "en.wikipedia.org" and "list=search" in b[3]]
    assert en_arama == []


def test_bagimsizlik_ayni_yayinci_ve_kopya_site_tek_kume():
    kaynaklar = [{"id": "wp_tr", "yayinci": "Wikimedia", "metin": TR_METIN},
                 {"id": "wp_en", "yayinci": "Wikimedia", "metin": EN_METIN},
                 {"id": "ayna", "yayinci": "ayna-site.org", "metin": kd.html_metin(AYNA_HTML)},
                 {"id": "ayna2", "yayinci": "baska-ayna.net", "metin": "Giriş. " + TR_METIN},
                 {"id": "akademik", "yayinci": "akademi.edu", "metin": kd.html_metin(AKADEMIK_HTML)}]
    k = kk.bagimsizlik_kumeleri(kaynaklar)
    assert k["wp_tr"] == k["wp_en"] == k["ayna"] == k["ayna2"]
    assert k["akademik"] != k["wp_tr"] and len(set(k.values())) == 2


def test_havuz_sayisal_celiski_ortalama_yok_tek_kaynak_uyarisi():
    ag = _wp_ag()
    kaynaklar = kk.WikipediaKesif(ag.istemci()).kesfet("Örnekova Muharebesi")
    for k in kaynaklar:   # kesif aday metni yok: bağımsızlık için doğrulayıcının getirdiği metni ekle
        if k["aday"] and k["url"].startswith("https://ayna"):
            k["metin"] = kd.html_metin(AYNA_HTML)
        if k["aday"] and k["url"].startswith("https://akademi"):
            k["metin"] = kd.html_metin(AKADEMIK_HTML)
    h = kk.havuz_olustur("Örnekova Muharebesi", kaynaklar, kd.KaynakDogrulayici(ag.istemci()))
    kay = {k["iddia"][:30]: k for k in h["kayitlar"]}
    ordu = next(k for k in h["kayitlar"] if "40.000" in k["iddia"])
    assert ordu["durum"] == "tartismali" and ordu["celiski"]
    degerler = sorted(x["deger"] for x in ordu["celiski"]["degerler"])
    assert degerler == [40000, 60000]
    assert statistics.mean(degerler) not in [x["deger"] for x in ordu["celiski"]["degerler"]]   # 50.000 üretilmedi
    assert "50000" not in json.dumps(h) and "50.000" not in json.dumps(h)
    assert ordu["celiski_notu"] == kk.CELISKI_IFADESI
    # kayıp 3.000: akademik + Wikipedia iki bağımsız küme aynı rakam → çelişki yok, doğrulanmış
    kayip = next(k for k in h["kayitlar"] if "3.000" in k["iddia"] and "çekildi" in k["iddia"])
    # Faz-56: akademik kaynak yalnız "3.000 kayıp verdi" diyor; "geri çekildi" kısmını desteklemiyor → partial.
    # Tam destek 1 kümede; rakam 2 bağımsız kümede teyitli → sayısal koruma geçer, iddia doğrulanmış.
    assert kayip["bagimsiz_kaynak_sayisi"] == 1 and kayip["sayi_teyit_kume_sayisi"] == 2
    assert kayip["durum"] == "dogrulanmis" and not kayip["tek_kaynak_uyarisi"]
    akad_k = [x for x in kayip["kaynaklar"] if x["tur"] == "akademik"]
    assert akad_k and akad_k[0]["teyit_turu"] == "yalniz_sayi" and akad_k[0]["dogrulama"]["destek_sinifi"] == "partial"
    # 1502 antlaşma: yalnızca Wikipedia kümesi (TR+EN tek yayıncı) → tek kaynak uyarısı, kesin değil
    barisi = next(k for k in h["kayitlar"] if "1502" in k["iddia"])
    assert barisi["tek_kaynak_uyarisi"] and barisi["durum"] == "tartismali"
    # 404 veren aday kaynak 'ölü' sayıldı ama hiçbir kaydı desteklemiyor
    assert set(h["kaynak_raporu"]["web_" + __import__("hashlib").sha1(b"https://olu.org/x").hexdigest()[:10]]["sonuclar"]) == {"unreachable"}
    # akademik kaynak 40.000'lik iddiayı 'doğrulamaz' (orada 60.000 yazıyor): rakam farkı doğrulama değil çelişki
    akad = [x for x in ordu["kaynaklar"] if x["tur"] == "akademik"]
    assert akad == []
    # havuz planlayıcının gerçek-sağlayıcı araştırma kapısından geçer
    assert sp.arastirma_dogrula(h, sentetik=False) == []
    assert kay


def test_tek_kaynakli_sayi_tek_kaynak_uyarisi():
    kay = [{"id": "a1", "iddia": "x", "yil": None, "sayilar": [{"deger": 20000, "olcu_turu": "ordu"}],
            "kaynaklar": [{"kume": 0, "teyit_turu": "icerik"}], "bagimsiz_kaynak_sayisi": 1, "tarih_teyit_kume_sayisi": 1}]
    kk.sayisal_koruma(kay)
    assert kay[0]["tek_kaynak_uyarisi"] and kay[0]["durum"] == "tartismali"
    kay2 = [{"id": "a2", "iddia": "x", "yil": None, "sayilar": [{"deger": 20000, "olcu_turu": "ordu"}], "kaynaklar": [],
             "bagimsiz_kaynak_sayisi": 0, "tarih_teyit_kume_sayisi": 0}]
    kk.sayisal_koruma(kay2)
    assert kay2[0]["durum"] == "belirsiz"


# ------------------------------------------------------------------ gerçek-sağlayıcı havuzu (fixture) + Gemini

def _havuz():
    def kyn(i, url, kume):
        return {"id": f"src_{i}", "url": url, "eser": f"Kaynak {i}", "yayinci": f"y{kume}", "tur": "akademik", "kume": kume,
                "teyit_turu": "icerik", "dogrulama": {"verification_status": "verified", "supporting_excerpt": "..."}}
    k = [
        {"id": "ark_001", "olay_id": "olay_1501", "tur": "tarih", "yil": 1501, "durum": "dogrulanmis",
         "iddia": "Örnekova Muharebesi 1501 yılında Demir Han ile Taş Bey arasında yapıldı.",
         "kaynaklar": [kyn(1, "https://akademi.edu/a", 0), kyn(2, "https://arsiv.org/b", 1)]},
        {"id": "ark_002", "olay_id": "olay_1501", "tur": "sayi", "yil": None, "durum": "tartismali",
         "iddia": "Demir Han ordusu için kaynaklar 40.000 ve 60.000 rakamlarını verir.",
         "celiski": {"olcu_turleri": ["ordu"], "degerler": [{"deger": 40000, "kume": [0]}, {"deger": 60000, "kume": [1]}]},
         "celiski_notu": kk.CELISKI_IFADESI, "kaynaklar": [kyn(1, "https://akademi.edu/a", 0), kyn(2, "https://arsiv.org/b", 1)]},
        {"id": "ark_003", "olay_id": "olay_1501", "tur": "olay", "yil": None, "durum": "tartismali", "tek_kaynak_uyarisi": True,
         "celiski_notu": "tek bağımsız kaynak", "iddia": "Taş Bey muharebeden sonra doğuya çekildi.",
         "kaynaklar": [kyn(3, "https://akademi.edu/c", 0)]},
        {"id": "ark_004", "olay_id": "olay_1501", "tur": "kisi", "yil": None, "durum": "dogrulanmis",
         "iddia": "Demir Han muharebede ordusunun merkezinde bulundu.", "kaynaklar": [kyn(1, "https://akademi.edu/a", 0)]},
        {"id": "ark_005", "olay_id": "olay_1501", "tur": "yer", "yil": None, "durum": "belirsiz",
         "iddia": "Muharebe alanının tam yeri bilinmiyor.", "kaynaklar": []},
    ]
    return {"konu": "Örnekova Muharebesi", "kayitlar": k}


def _anlati_shorts(havuz):
    bolumler = ["hook"] + ["akis"] * 8 + ["kapanis"] * 3
    sira = ["ark_001", "ark_004", "ark_002", "ark_001", "ark_003", "ark_004", "ark_005", "ark_001", "ark_002", "ark_004",
            "ark_003", "ark_001"]
    kay = {k["id"]: k for k in havuz["kayitlar"]}
    out = []
    for n, (b, i) in enumerate(zip(bolumler, sira)):
        k = kay[i]
        on = ""
        if k.get("celiski"):
            on = "Kaynaklar farklı rakamlar aktarmaktadır: "
        elif k["durum"] != "dogrulanmis":
            on = "Bazı kaynaklara göre "
        out.append({"id": f"b{n}", "bolum": b, "metin": f"{on}{k['iddia']} [{chr(65 + n)}]", "dayanak_ids": [i],
                    "kesinlik": "kesin" if k["durum"] == "dogrulanmis" else "tartismali"})
    return {"mod": "shorts", "birimler": out}


def _plan_shorts(anlati):
    turler = ["gorsel25d", "harita", "gorsel25d", "sahne3d", "harita", "gorsel25d", "harita", "gorsel25d", "sahne3d",
              "gorsel25d", "harita", "gorsel25d"]
    sureler = [3, 5, 4, 5, 4, 5, 4, 5, 5, 6, 5, 5]
    s = []
    for i, (b, t, d) in enumerate(zip(anlati["birimler"], turler, sureler)):
        x = {"id": f"s{i}", "bolum": b["bolum"], "anlatim": b["metin"], "dayanak_ids": b["dayanak_ids"], "kesinlik": b["kesinlik"],
             "sure_sn": d, "ritim": "normal", "gorsel_tur": t, "hareketli": t != "harita", "katki": f"katkı {chr(65 + i)}",
             "ton": "gerilimli", "gecis_efekti": "boom" if i == 0 else "yok", "ambiyans": "kusatma", "hook": i == 0}
        if t == "harita":
            x["cografi_amac"] = "iki ordunun düzlükteki konumu ve çekilme yönü"
        elif t == "gorsel25d":
            x["arama_sorgulari"] = ["Örnekova muharebesi minyatür"]
        else:
            x["uc_boyut_gerekcesi"] = "ordunun merkez dizilişi üç boyutta anlaşılır"
        s.append(x)
    return {"mod": "shorts", "baslik": "Örnekova", "uretim": "ayri", "ana_fikir": "tek muharebe", "ana_olay_id": "olay_1501",
            "sahneler": s}


class SahteGemini:
    """Gemini HTTP yanıtı taklidi. adım istem metninden anlaşılır; yanıtlar sırayla verilir."""

    def __init__(self, yanitlar=None, kod=200, istisna=None):
        self.yanitlar = yanitlar or {}
        self.kod, self.istisna = kod, istisna
        self.istekler = []

    def __call__(self, url, govde, basliklar, zaman):
        istem = json.loads(govde)["contents"][0]["parts"][0]["text"]
        self.istekler.append({"url": url, "basliklar": dict(basliklar), "istem": istem})
        if self.istisna:
            raise self.istisna
        if self.kod != 200:
            return self.kod, '{"error": "x"}'
        adim = "onarim" if istem.startswith(sp.ONARIM_TALIMATI) else "anlati" if "Dramatik anlatı" in istem else "plan"
        y = self.yanitlar[adim]
        veri = y.pop(0) if isinstance(y, list) else y
        metin = veri if isinstance(veri, str) else json.dumps(veri, ensure_ascii=False)
        return 200, json.dumps({"candidates": [{"content": {"parts": [{"text": metin}]}}]})


ANAHTAR = "AIzaTEST-gizli-anahtar-0123456789"


def test_gemini_anahtar_yoksa_hata_mocka_gecmez(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(gm.GercekUretimHatasi, match="mock'a geçilmez"):
        gm.GeminiLLMProvider()
    with pytest.raises(gm.GercekUretimHatasi):
        gm.saglayici_sec("gercek")
    assert isinstance(gm.saglayici_sec("test"), MockLLMProvider)
    with pytest.raises(ValueError):
        gm.saglayici_sec("")


def test_gemini_anahtar_baslikta_url_ve_hatalarda_yok(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", ANAHTAR)
    t = SahteGemini(istisna=OSError(f"bağlantı koptu key={ANAHTAR}"))
    g = gm.GeminiLLMProvider(tasiyici=t, uyku=lambda s: None)
    with pytest.raises(gm.GercekUretimHatasi) as e:
        g.tamamla("istem", "anlati", {})
    assert ANAHTAR not in str(e.value) and "***" in str(e.value) and ANAHTAR not in repr(g)
    assert all(ANAHTAR not in r["url"] and r["basliklar"]["x-goog-api-key"] == ANAHTAR for r in t.istekler)
    assert len(t.istekler) == 3 * len(gm.MODELLER)   # sınırlı tekrar, sonra açık hata


def test_gemini_hatasinda_plan_durur_mock_kullanilmaz_render_yok(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", ANAHTAR)
    g = gm.GeminiLLMProvider(tasiyici=SahteGemini(kod=500), uyku=lambda s: None)
    gonder = []
    r = sp.plan_uret("Örnekova Muharebesi", "shorts", g, arastirma=_havuz(), uretime_gonder=gonder.append)
    assert r["durum"] == "durduruldu" and r["durdugu_katman"] == "3_anlati" and gonder == []
    assert r["hatalar"][0]["kod"] == "saglayici_hatasi" and ANAHTAR not in json.dumps(r)
    assert r["saglayici"] == "gemini" and r["sentetik_mock"] is False


def test_gercek_saglayici_llm_hafizasini_arastirma_kabul_etmez(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", ANAHTAR)
    t = SahteGemini()
    r = sp.plan_uret("Örnekova Muharebesi", "shorts", gm.GeminiLLMProvider(tasiyici=t))
    assert r["durum"] == "durduruldu" and r["hatalar"][0]["kod"] == "llm_hafizasi_arastirma_degil" and t.istekler == []


def test_gemini_uctan_uca_shorts_kapidan_gecer_ve_statuler_istemde(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", ANAHTAR)
    h = _havuz()
    an = _anlati_shorts(h)
    t = SahteGemini({"anlati": an, "plan": _plan_shorts(an)})
    r = sp.plan_uret("Örnekova Muharebesi", "shorts", gm.GeminiLLMProvider(tasiyici=t), arastirma=h)
    assert r["durum"] == "uretime_hazir", r.get("hatalar")
    p = r["plan"]
    assert p["sentetik_mock"] is False and p["yayin_icin_uygun"] is True
    gd = {s["dayanak_ids"][0]: s["guven_durumu"] for s in p["sahneler"]}
    assert gd["ark_001"] == "kaynaklarla_destekleniyor" and gd["ark_002"] == "tartismali_temkinli_anlatim"
    assert gd["ark_005"] == "belirsiz_temkinli_anlatim"
    anlati_istemi = t.istekler[0]["istem"]
    assert "src_1=verified" in anlati_istemi and "tek_kaynak_uyarisi" in anlati_istemi and "CELISKI: 40000, 60000" in anlati_istemi
    assert "UYDURMA" in anlati_istemi and kk.CELISKI_IFADESI in anlati_istemi


@pytest.mark.parametrize("ad,boz,kod", [
    ("sahte_dayanak", lambda p: p["sahneler"][2].update(dayanak_ids=["ark_999"]), "dayanak_yok"),
    ("sahte_kaynak_id", lambda p: p["sahneler"][2].update(kaynak_ids=["src_77"]), "uydurma_kaynak_id"),
    ("sahte_url", lambda p: p["sahneler"][3].update(anlatim=p["sahneler"][3]["anlatim"] + " (bkz. https://uydurma.org/kaynak)"),
     "dogrulanmamis_url"),
    ("celiski_kesin", lambda p: p["sahneler"][2].update(anlatim="Demir Han ordusu 40.000 kişiydi. [C]", kesinlik="kesin"),
     "celiski_ifadesi_yok"),
    ("kanitsiz_sayi", lambda p: p["sahneler"][1].update(anlatim=p["sahneler"][1]["anlatim"] + " 7000 atlı da vardı."),
     "dayanaksiz_sayi"),
    ("tek_kaynak_kesin", lambda p: p["sahneler"][4].update(anlatim="Taş Bey muharebeden sonra doğuya çekildi. [E]", kesinlik="kesin"),
     "temkin_yok"),
])
def test_gemini_uydurma_kilidi_kapida_reddedilir(ad, boz, kod):
    h = sp.bilgi_havuzu(_havuz())
    p = _plan_shorts(_anlati_shorts(_havuz()))
    boz(p)
    e, _, _ = sp.plan_dogrula(p, h, "shorts")
    assert kod in {x["kod"] for x in e}, (ad, e[:3])


def test_gemini_onarim_istemi_baglam_tasir_ve_yalniz_hatali_alani_duzeltir(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", ANAHTAR)
    h = _havuz()
    an = _anlati_shorts(h)
    dogru = _plan_shorts(an)
    bozuk = json.loads(json.dumps(dogru))
    bozuk["sahneler"][3]["anlatim"] += " (bkz. https://uydurma.org/kaynak)"
    yama = {"duzeltmeler": [{"yol": "sahneler[3]", "deger": dogru["sahneler"][3]}]}
    t = SahteGemini({"anlati": an, "plan": [bozuk], "onarim": [yama]})
    r = sp.plan_uret("Örnekova Muharebesi", "shorts", gm.GeminiLLMProvider(tasiyici=t), arastirma=h)
    assert r["durum"] == "uretime_hazir"
    onarim = [x for x in t.istekler if x["istem"].startswith(sp.ONARIM_TALIMATI)]
    assert len(onarim) == 1 and "uydurma.org" in onarim[0]["istem"] and "sahneler[3] (güncel)" in onarim[0]["istem"]
    assert ANAHTAR not in json.dumps(r)


def test_gemini_bozuk_json_ve_kalici_uydurma_fail_safe(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", ANAHTAR)
    h = _havuz()
    an = _anlati_shorts(h)
    bozuk = _plan_shorts(an)
    bozuk["sahneler"][2]["dayanak_ids"] = ["ark_999"]
    ayni = {"duzeltmeler": [{"yol": "sahneler[2].dayanak_ids", "deger": ["ark_998"]}]}   # yine uydurma
    t = SahteGemini({"anlati": an, "plan": ["bu json değil", bozuk], "onarim": [ayni, ayni]})
    gonder = []
    r = sp.plan_uret("Örnekova Muharebesi", "shorts", gm.GeminiLLMProvider(tasiyici=t), arastirma=h, uretime_gonder=gonder.append)
    d = r["katmanlar"]["4_5_sahne_plani_ve_kapi"]["denemeler"]
    assert r["durum"] == "durduruldu" and gonder == [] and len(d) == 3
    assert d[0]["hatalar"][0]["kod"] == "json_parse" and any(x["kod"] == "dayanak_yok" for x in r["hatalar"])


def test_gercek_havuz_kapisi_tek_kaynak_ve_celiski_tekillestirme_reddi():
    h = _havuz()
    h["kayitlar"][2]["durum"] = "dogrulanmis"
    h["kayitlar"][1]["celiski"]["degerler"] = [{"deger": 50000, "kume": [0, 1]}]   # ortalamaya indirgenmiş
    h["kayitlar"][0]["kaynaklar"][0]["dogrulama"]["verification_status"] = "unreachable"
    kodlar = {x["kod"] for x in sp.arastirma_dogrula(h, sentetik=False)}
    assert {"tek_kaynak_kesin", "celiski_tekillestirilmis", "dogrulanmamis_kaynak"} <= kodlar


def test_canli_dry_run_anahtarsiz_gemini_atlar_mocka_gecmez(monkeypatch, capsys):
    from motor.orkestrasyon import canli_dry_run as cdr
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_DRYRUN_KEY", raising=False)
    ag = _wp_ag()
    monkeypatch.setattr(cdr, "_kesif", lambda: kk.WikipediaKesif(ag.istemci()))
    monkeypatch.setattr(cdr, "_dogrulayici", lambda: kd.KaynakDogrulayici(ag.istemci()))
    monkeypatch.setattr(cdr, "_openalex", lambda: kk.OpenAlexKesif(ag.istemci()))   # ağsız: sahte ağda yok → 404
    r = cdr.calistir("Örnekova Muharebesi", ["uzun", "shorts"])
    assert r["durum"] == "gemini_atlandi" and "mock'a geçilmedi" in r["asamalar"]["3_gemini"]["neden"]
    assert r["asamalar"]["2_dogrulama"]["kayit_sayisi"] >= 3 and r["planlar"] == {}
    cikti = capsys.readouterr().out
    for asama in ("kaynak_kesif:", "kaynak_dogrulama:", "gemini_cagri:"):   # zaman damgalı ilerleme satırları
        assert asama in cikti, asama
    assert re.search(r"\[\d\d:\d\d:\d\d \+\s*\d+\.\ds\] kaynak_kesif:", cikti)


def test_ortamda_anahtar_yoksa_dosyalarda_anahtar_izi_yok():
    from pathlib import Path
    kok = Path(sp.__file__).parent
    for f in kok.glob("*.py"):
        t = f.read_text()
        assert "AIza" not in t and "?key=" not in t, f   # anahtar ya da URL'de anahtar kalıbı yok


def test_ayni_baglam_farkli_rakam_dogrulama_degil():
    html = "<p>Örnekova Muharebesi 1501 yılında Demir Han ile Taş Bey arasında yapıldı; Demir Han ordusu 60.000 askerdi.</p>".encode()
    ag = _ag(rakam=(200, {"Content-Type": "text/html"}, html))
    r = _dog(ag).dogrula("https://ornek.org/rakam", {"metin": "Örnekova Muharebesi 1501 yılında Demir Han ordusu 40.000 askerdi.",
                                                     "olay_terimleri": ["Örnekova"]})
    assert r["verification_status"] == "content_mismatch" and r["number_match"] is False and r["year_match"] is True


def test_arsiv_goruntusu_ozgun_yayinciya_gore_siniflanir():
    u = "https://web.archive.org/web/20191025053132/https://islamansiklopedisi.org.tr/x"
    assert kk.ozgun_url(u) == "https://islamansiklopedisi.org.tr/x"
    assert kk.kaynak_turu(u) == "akademik" and kk.yayinci(u) == "islamansiklopedisi.org.tr"
    assert kk.kaynak_turu("https://archive.org/details/kitap") == "birincil_arsiv"


def test_pdf_ve_desteklenmeyen_tur_icerik_yanlis_sayilmaz():
    ag = _ag(pdf=(200, {"Content-Type": "application/pdf"}, b"%PDF-1.7 ..."), resim=(200, {"Content-Type": "image/png"}, b"\x89PNG"))
    d = _dog(ag)
    for yol in ("pdf", "resim"):
        r = d.dogrula(f"https://ornek.org/{yol}", IDDIA)
        assert r["verification_status"] == "unverified" and r["http_status"] == 200, r


def test_olay_terimi_yalnizca_iddiada_geciyorsa_aranir():
    html = "<p>Demir Han 1501 yılında Taş Bey'i yendi ve ordusunu doğuya yöneltti.</p>".encode()
    ag = _ag(p=(200, {"Content-Type": "text/html"}, html))
    r = _dog(ag).dogrula("https://ornek.org/p", {"metin": "Demir Han 1501 yılında Taş Bey'i yendi.", "olay_terimleri": ["Örnekova"]})
    assert r["verification_status"] == "verified" and r["event_match"] is None
    r2 = _dog(ag).dogrula("https://ornek.org/p", {"metin": "Örnekova'da Demir Han 1501 yılında Taş Bey'i yendi.",
                                                  "olay_terimleri": ["Örnekova"]})
    assert r2["verification_status"] == "content_mismatch" and r2["event_match"] is False


def test_kisa_kalip_metin_kopya_sayilmaz_ve_yilsiz_iddia_tarih_degil():
    assert kk.benzerlik("Ana sayfa Giriş Yap Ara", "Ana sayfa Giriş Yap Ara") == 0.0
    ag = _wp_ag()
    h = kk.havuz_olustur("Örnekova Muharebesi", kk.WikipediaKesif(ag.istemci()).kesfet("Örnekova Muharebesi"),
                         kd.KaynakDogrulayici(ag.istemci()))
    assert all(k["yil"] is not None for k in h["kayitlar"] if k["tur"] == "tarih")
    assert sp.arastirma_dogrula(h, sentetik=False) == []


# ------------------------------------------------------------------ süre korumaları ve parçalı üretim

def test_gemini_istek_zaman_asimi_90_ve_dusunme_butcesi(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", ANAHTAR)
    goru = []

    def t(url, govde, bas, zaman):
        goru.append((zaman, json.loads(govde)["generationConfig"]))
        return 200, json.dumps({"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})
    g = gm.GeminiLLMProvider(tasiyici=t)
    g.tamamla("x", "anlati", {})
    assert goru[0][0] == 90.0 and goru[0][1]["thinkingConfig"] == {"thinkingBudget": 1024}


def test_dusunme_yapilandirmasi_desteklenmezse_onsuz_tekrar(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", ANAHTAR)
    goru = []

    def t(url, govde, bas, zaman):
        cfg = json.loads(govde)["generationConfig"]
        goru.append("thinkingConfig" in cfg)
        if "thinkingConfig" in cfg:
            return 400, '{"error": {"message": "thinking is not supported for this model"}}'
        return 200, json.dumps({"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})
    g = gm.GeminiLLMProvider(tasiyici=t)
    assert g.tamamla("x", "anlati", {}) == "{}" and goru == [True, False]
    g.tamamla("y", "anlati", {})
    assert goru[-1] is False   # model hatırlanır


def test_gemini_sure_butcesi_asilinca_acik_hata_asili_kalmaz(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", ANAHTAR)
    saat = [0.0]

    def yavas(url, govde, bas, zaman):
        assert zaman <= 90.0
        saat[0] += zaman   # her istek zaman aşımına kadar sürer
        raise TimeoutError("timed out")
    g = gm.GeminiLLMProvider(tasiyici=yavas, sure_butcesi=150.0, saat=lambda: saat[0], uyku=lambda s: None)
    with pytest.raises(gm.GercekUretimHatasi, match="süre bütçesi"):
        g.tamamla("x", "anlati", {})
    assert saat[0] <= 150.0 + 5.0 and g.cagri_sayisi <= 3


def test_uzun_parcali_uretim_bolum_bolum_ve_kapidan_gecer():
    m = MockLLMProvider()
    log = []
    r = sp.plan_uret("Örnek Kale", "uzun", m, parcali=True, ilerleme=lambda a, b: log.append((a, b)))
    assert r["durum"] == "uretime_hazir" and 900 <= r["ozet"]["toplam_sn"] <= 1200
    adim = [c["adim"] for c in m.cagrilar]
    assert adim.count("anlati") == 3 and adim.count("sahne_plani") == 3   # kota dostu: 5 bölüm 3 istekte
    ids = [s["id"] for s in r["plan"]["sahneler"]]
    assert len(ids) == len(set(ids)) and sum(s["hook"] for s in r["plan"]["sahneler"]) == 1
    assert any(a == "onay_kapisi" and "GEÇTİ" in b for a, b in log)
    # Shorts parçalı üretilmez (tek istek)
    m2 = MockLLMProvider()
    sp.plan_uret("Örnek Kale", "shorts", m2, parcali=True)
    assert [c["adim"] for c in m2.cagrilar].count("sahne_plani") == 1


def test_siniflanamayan_buyuk_rakam_da_tek_kaynakla_kesinlesmez():
    kay = [{"id": "a1", "iddia": "60,000 people harassed the forces.", "yil": None,
            "sayilar": kk._sayilar("On the wings, 60,000 people began to harass the forces."),
            "kaynaklar": [{"kume": 0, "teyit_turu": "icerik"}], "bagimsiz_kaynak_sayisi": 1, "tarih_teyit_kume_sayisi": 1},
           {"id": "a2", "iddia": "x", "yil": None, "sayilar": kk._sayilar("Sultan mobilized the 25,000 janissaries at once."),
            "kaynaklar": [{"kume": 0, "teyit_turu": "icerik"}], "bagimsiz_kaynak_sayisi": 1, "tarih_teyit_kume_sayisi": 1}]
    assert kay[0]["sayilar"][0]["olcu_turu"] == "ordu" and kay[1]["sayilar"][0]["olcu_turu"] == "ordu"
    kk.sayisal_koruma(kay)
    assert all(k["tek_kaynak_uyarisi"] and k["durum"] != "dogrulanmis" for k in kay)
    k3 = [{"id": "a3", "iddia": "x", "yil": None, "sayilar": [{"deger": 340, "olcu_turu": "diger"}],
           "kaynaklar": [{"kume": 0, "teyit_turu": "icerik"}], "bagimsiz_kaynak_sayisi": 1, "tarih_teyit_kume_sayisi": 1}]
    kk.sayisal_koruma(k3)
    assert k3[0]["tek_kaynak_uyarisi"]


# ------------------------------------------------------------------ PDF metin çıkarımı (pypdf)

def _pdf(metinler):
    """Elle kurulmuş geçerli küçük PDF (Helvetica, düz metin akışı)."""
    objs = {1: b"<< /Type /Catalog /Pages 2 0 R >>", 3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"}
    n, kids = 4, []
    for t in metinler:
        satir = [t[i:i + 80] for i in range(0, len(t), 80)]
        akim = ("BT /F1 11 Tf 50 750 Td 14 TL " + " ".join(
            "(%s) '" % x.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for x in satir) + " ET").encode("latin-1")
        objs[n] = b"<< /Length %d >>\nstream\n" % len(akim) + akim + b"\nendstream"
        objs[n + 1] = (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents %d 0 R "
                       b"/Resources << /Font << /F1 3 0 R >> >> >>" % n)
        kids.append(n + 1)
        n += 2
    objs[2] = b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % k for k in kids) + b"] /Count %d >>" % len(kids)
    out, ofs = b"%PDF-1.4\n", {}
    for i in sorted(objs):
        ofs[i] = len(out)
        out += b"%d 0 obj\n" % i + objs[i] + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (max(objs) + 1)
    for i in range(1, max(objs) + 1):
        out += b"%010d 00000 n \n" % ofs[i]
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (max(objs) + 1, x)


PDF_METIN = "Ornekova Muharebesi 1501 yilinda Demir Han ile Tas Bey arasinda Ornekova duzlugunde yapildi."
IDDIA_ASCII = {"metin": "Ornekova Muharebesi 1501 yilinda Demir Han ile Tas Bey arasinda yapildi.", "olay_terimleri": ["Ornekova"]}


def test_pdf_metni_cikarilir_ve_baglamsal_dogrulanir():
    ag = _ag(makale=(200, {"Content-Type": "application/pdf"}, _pdf(["Giris sayfasi.", PDF_METIN])))
    r = _dog(ag).dogrula("https://ornek.org/makale", IDDIA_ASCII)
    assert r["verification_status"] == "verified" and r["http_status"] == 200, r
    assert "1501" in r["supporting_excerpt"] and r["verification_method"] == "structured_and_contextual"


def test_pdf_ilk_10_sayfa_siniri():
    sayfalar = ["Bos sayfa metni burada yer alir ve konu disidir."] * 12 + [PDF_METIN]   # iddia 13. sayfada
    metin, neden = kd.pdf_metin(_pdf(sayfalar))
    assert neden == "pdf_metni" and "1501" not in metin
    ag = _ag(uzun=(200, {"Content-Type": "application/pdf"}, _pdf(sayfalar)))
    assert _dog(ag).dogrula("https://ornek.org/uzun", IDDIA_ASCII)["verification_status"] == "content_mismatch"


def test_pdf_boyut_bozuk_ve_kutuphane_yok_unverified(monkeypatch):
    buyuk = _pdf([PDF_METIN]) + b"%" + b"0" * (3 * 1024 * 1024)
    ag = _ag(buyuk=(200, {"Content-Type": "application/pdf"}, buyuk), bozuk=(200, {"Content-Type": "application/pdf"}, b"%PDF-1.4 x"))
    d = kd.KaynakDogrulayici(ag.istemci(en_cok_bayt=4 * 1024 * 1024))
    r = d.dogrula("https://ornek.org/buyuk", IDDIA_ASCII)
    assert r["verification_status"] == "unverified" and "3 MB" in r["neden"]
    r2 = d.dogrula("https://ornek.org/bozuk", IDDIA_ASCII)
    assert r2["verification_status"] == "unverified" and r2["neden"].startswith("pdf_okunamadi")
    monkeypatch.setattr(kd, "_PDF_BETIGI", kd._PDF_BETIGI.replace("import pypdf", "import pypdf_olmayan_modul"))
    metin, neden = kd.pdf_metin(_pdf([PDF_METIN]))
    assert metin is None and neden.startswith("pdf_kutuphanesi_yok")


def test_html_2mb_siniri_pdf_3mb_istemcisinde_de_korunur():
    ag = _ag(koca=(200, {"Content-Type": "text/html"}, b"<p>" + b"a" * (2 * 1024 * 1024 + 10) + b"</p>"))
    r = kd.KaynakDogrulayici(ag.istemci(en_cok_bayt=3 * 1024 * 1024)).dogrula("https://ornek.org/koca", IDDIA)
    assert r["verification_status"] == "unverified" and "2 MB" in r["neden"]


# ------------------------------------------------------------------ OpenAlex: bağımsız akademik küme

def _oa_yanit(isler):
    return (200, {"Content-Type": "application/json"}, json.dumps({"results": isler}).encode())


def _ters(metin):
    d = {}
    for i, w in enumerate(metin.split()):
        d.setdefault(w, []).append(i)
    return d


OA_ISLER = [
    {"id": "https://openalex.org/W111", "display_name": "The Ornekova campaign of 1501", "publication_year": 2012,
     "doi": "https://doi.org/10.1/abc",
     "abstract_inverted_index": _ters("This article studies the Örnekova Muharebesi fought in 1501 between Demir Han and "
                                      "Taş Bey on the Örnekova plain, based on chronicles."),
     "primary_location": {"source": {"display_name": "Tarih Dergisi"}, "pdf_url": None},
     "open_access": {"oa_url": "https://akademi.edu/acik.pdf"}},
    {"id": "https://openalex.org/W222", "display_name": "Soil chemistry of river deltas", "publication_year": 2020,
     "abstract_inverted_index": _ters("We measure nitrogen in 1501 samples."), "primary_location": {"source": {"display_name": "Soil J"}}},
]


def _oa_ag(isler=OA_ISLER, durum=200):
    ag = _wp_ag()
    ag.dns["api.openalex.org"] = ["104.18.0.1"]
    temel = ag.baglayici

    def baglayici(sema, host, port, ip, zaman):
        if host == "api.openalex.org":
            class B:
                def istek(self, yol, basliklar, en_cok):
                    ag.baglantilar.append((sema, host, ip, yol))
                    if durum != 200:
                        return kd.HamYanit(durum, {}, b"{}", ip)
                    d = _oa_yanit(isler)
                    return kd.HamYanit(d[0], {k.lower(): v for k, v in d[1].items()}, d[2], ip)
            return B()
        return temel(sema, host, port, ip, zaman)
    ag.baglayici = baglayici
    return ag


def test_openalex_ozet_kurulur_ilgisiz_elenir_pdf_aday_eklenir(monkeypatch):
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    ag = _oa_ag()
    k = kk.OpenAlexKesif(ag.istemci()).kesfet("Örnekova Muharebesi", ["Battle of Ornekova"])
    ids = {x["id"] for x in k}
    assert "oa_W111" in ids and "oa_W222" not in ids          # konu dışı yayın elendi
    w = next(x for x in k if x["id"] == "oa_W111")
    assert w["api_metni"] and w["tur"] == "akademik" and w["yayinci"] == "openalex:Tarih Dergisi"
    assert "fought in 1501 between Demir Han" in w["metin"]      # ters indeksten özet
    assert any(x["url"] == "https://akademi.edu/acik.pdf" and x["aday"] for x in k)
    assert all("api_key" not in b[3] for b in ag.baglantilar if b[1] == "api.openalex.org")


def test_openalex_anahtar_ortamdan_url_de_ama_kaynak_ve_logda_yok(monkeypatch):
    monkeypatch.setenv("OPENALEX_API_KEY", "OA-GIZLI-999")
    ag = _oa_ag(durum=403)
    oa = kk.OpenAlexKesif(ag.istemci())
    assert oa.kesfet("Örnekova Muharebesi") == []
    assert any("api_key=OA-GIZLI-999" in b[3] for b in ag.baglantilar)   # istekte var
    assert "OA-GIZLI-999" not in json.dumps(oa.log) and "HTTP 403" in oa.log[0] and "anahtar" in oa.log[0]


def test_openalex_bagimsiz_kume_tarih_iddiasini_dogrular(monkeypatch):
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    ag = _oa_ag()
    wp = kk.WikipediaKesif(ag.istemci()).kesfet("Örnekova Muharebesi")
    sadece_wp = kk.havuz_olustur("Örnekova Muharebesi", [k for k in wp if not k["aday"]], kd.KaynakDogrulayici(ag.istemci()))
    ilk = next(k for k in sadece_wp["kayitlar"] if "1501" in k["iddia"] and "yapıldı" in k["iddia"])
    assert ilk["durum"] == "tartismali" and ilk["tek_kaynak_uyarisi"]          # yalnız Wikipedia: tek küme
    oa = kk.OpenAlexKesif(ag.istemci()).kesfet("Örnekova Muharebesi", ["Battle of Ornekova"])
    h = kk.havuz_olustur("Örnekova Muharebesi", [k for k in wp if not k["aday"]] + [x for x in oa if x["id"] == "oa_W111"],
                         kd.KaynakDogrulayici(ag.istemci()))
    k = next(k for k in h["kayitlar"] if "1501" in k["iddia"] and "yapıldı" in k["iddia"])
    assert k["tarih_teyit_kume_sayisi"] == 2 and k["durum"] == "dogrulanmis" and not k["tek_kaynak_uyarisi"]
    oa_destek = [x for x in k["kaynaklar"] if x["id"] == "oa_W111"]
    assert oa_destek and oa_destek[0]["dogrulama"]["supporting_excerpt"]
    assert sp.arastirma_dogrula(h, sentetik=False) == []


# ------------------------------------------------------------------ Gemini kota koruması + iş akışı

def test_gemini_varsayilan_model_ve_ortamdan_sira(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", ANAHTAR)
    monkeypatch.delenv("GEMINI_MODELLER", raising=False)
    assert gm.GeminiLLMProvider(tasiyici=SahteGemini()).modeller[0] == "gemini-flash-latest"
    monkeypatch.setenv("GEMINI_MODELLER", "m-bir, m-iki")
    assert gm.GeminiLLMProvider(tasiyici=SahteGemini()).modeller == ("m-bir", "m-iki")


def test_gemini_istekler_arasi_en_az_aralik(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", ANAHTAR)
    saat = [0.0]
    uykular = []

    def uyku(s):
        uykular.append(round(s, 2))
        saat[0] += s

    def t(url, govde, bas, zaman):
        saat[0] += 0.5
        return 200, json.dumps({"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})
    g = gm.GeminiLLMProvider(tasiyici=t, en_az_aralik=3.0, saat=lambda: saat[0], uyku=uyku)
    for _ in range(3):
        g.tamamla("x", "anlati", {})
    assert uykular == [2.5, 2.5]


def test_canli_dry_run_yalnizca_elle_tetiklenir():
    import yaml
    from pathlib import Path
    wf = yaml.safe_load(Path(".github/workflows/faz53a_gercek_kanit.yml").read_text())
    tetik = wf.get("on", wf.get(True))
    assert tetik["workflow_dispatch"]["inputs"]["canli_dry_run"]["default"] is False
    adim = next(a for a in wf["jobs"]["kanit"]["steps"] if a.get("name", "").startswith("5) Canlı dry-run"))
    assert "workflow_dispatch" in adim["if"] and "canli_dry_run" in adim["if"] and adim["timeout-minutes"] == 6
    assert "OPENALEX_API_KEY" in adim["env"]


def test_cumle_bolme_roma_rakami_ve_kisaltmada_bolmez():
    m = ("Otlukbeli Muharebesi, 11 Ağustos 1473 tarihinde Osmanlı padişahı II. Mehmed ile Uzun Hasan arasında yapıldı. "
         "Hz. Ali dönemine atıf yapan kaynaklar M.Ö. tarihleri vermez. Ertesi yıl barış konuşuldu.")
    c = kk._cumleler(m)
    assert c[0].endswith("arasında yapıldı.") and "II. Mehmed" in c[0] and len(c) == 3


# ------------------------------------------------------------------ Faz-55B: hata sınıfları, kota, dry-run anahtarı

def _yanit200(metin="{}"):
    return 200, json.dumps({"candidates": [{"content": {"parts": [{"text": metin}]}}]})


def _kayitci(davranis):
    """davranis(model, n) → (kod, metin) ya da istisna. İstek kayıtları: [(model, anahtar)]."""
    kayit = []

    def t(url, govde, bas, zaman):
        model = url.split("/models/")[1].split(":")[0]
        kayit.append((model, bas["x-goog-api-key"]))
        return davranis(model, len(kayit))
    return t, kayit


def test_hata_sinifi_tablosu():
    assert gm.hata_sinifi(404) == "model_bulunamadi" and gm.hata_sinifi(429) == "kota"
    assert gm.hata_sinifi(401) == gm.hata_sinifi(403) == "yetki" and gm.hata_sinifi(503) == "sunucu"
    assert gm.hata_sinifi(400) == "istek_gecersiz"
    assert gm.hata_sinifi(None, TimeoutError("x")) == "zaman_asimi" and gm.hata_sinifi(None, OSError("reset")) == "ag"


def test_404_sonraki_modele_gecer_tekrar_yok(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", ANAHTAR)
    t, kayit = _kayitci(lambda m, n: (404, '{"error": "no longer available"}') if m == "gemini-flash-latest" else _yanit200("ok"))
    g = gm.GeminiLLMProvider(tasiyici=t, uyku=lambda s: None)
    assert g.tamamla("x", "anlati", {}) == "ok"
    assert [m for m, _ in kayit] == ["gemini-flash-latest", "gemini-3.7-flash"] and g.kullanilan_model == "gemini-3.7-flash"
    assert g.hatalar == [{"model": "gemini-flash-latest", "sinif": "model_bulunamadi", "http": 404}]


def test_429_tek_istekte_kontrollu_durur_agresif_tekrar_yok(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", ANAHTAR)
    t, kayit = _kayitci(lambda m, n: (429, '{"error": {"message": "You exceeded your current quota"}}'))
    uykular = []
    g = gm.GeminiLLMProvider(tasiyici=t, uyku=uykular.append, en_cok_tekrar=2)
    with pytest.raises(gm.GeminiKotaHatasi) as e:
        g.tamamla("x", "anlati", {})
    assert len(kayit) == 1 and uykular == []          # tekrar yok, diğer modeller denenmedi, bekleme yok
    assert e.value.sinif == "kota" and "429" in str(e.value) and ANAHTAR not in str(e.value)
    with pytest.raises(gm.GeminiKotaHatasi):        # aynı koşuda sonraki çağrı istek GÖNDERMEZ
        g.tamamla("y", "sahne_plani", {})
    assert len(kayit) == 1


def test_403_yetki_durur_5xx_sinirli_tekrar_timeout_siniflanir(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", ANAHTAR)
    t, kayit = _kayitci(lambda m, n: (403, "forbidden"))
    with pytest.raises(gm.GercekUretimHatasi) as e:
        gm.GeminiLLMProvider(tasiyici=t, uyku=lambda s: None).tamamla("x", "anlati", {})
    assert e.value.sinif == "yetki" and len(kayit) == 1 and "GEMINI_API_KEY" in str(e.value)
    t2, k2 = _kayitci(lambda m, n: (503, "overloaded") if n <= 2 else _yanit200("ok"))
    g2 = gm.GeminiLLMProvider(tasiyici=t2, uyku=lambda s: None, en_cok_tekrar=1)
    assert g2.tamamla("x", "anlati", {}) == "ok"
    assert [m for m, _ in k2] == ["gemini-flash-latest", "gemini-flash-latest", "gemini-3.7-flash"]
    assert [h["sinif"] for h in g2.hatalar] == ["sunucu", "sunucu"]

    def zaman(m, n):
        raise TimeoutError("The read operation timed out")
    t3, k3 = _kayitci(zaman)
    with pytest.raises(gm.GercekUretimHatasi) as e3:
        gm.GeminiLLMProvider(tasiyici=t3, uyku=lambda s: None, en_cok_tekrar=0).tamamla("x", "anlati", {})
    assert e3.value.sinif == "zaman_asimi" and {h["sinif"] for h in e3.value.hatalar} == {"zaman_asimi"} and len(k3) == 3


@pytest.mark.parametrize("ortam,beklenen", [
    ({}, (None, None)),
    ({"GEMINI_API_KEY": "api-anahtari-1234"}, ("api-anahtari-1234", "GEMINI_API_KEY")),
    ({"GEMINI_DRYRUN_KEY": "dry-anahtari-5678", "GEMINI_API_KEY": "api-anahtari-1234"}, ("dry-anahtari-5678", "GEMINI_DRYRUN_KEY")),
    ({"GEMINI_DRYRUN_KEY": "   ", "GEMINI_API_KEY": "api-anahtari-1234"}, ("api-anahtari-1234", "GEMINI_API_KEY")),
    ({"GEMINI_DRYRUN_KEY": "dry-anahtari-5678"}, ("dry-anahtari-5678", "GEMINI_DRYRUN_KEY")),
])
def test_dryrun_anahtar_secimi(ortam, beklenen):
    from motor.orkestrasyon import canli_dry_run as cdr
    assert cdr.dryrun_anahtari_sec(ortam) == beklenen


def test_anahtar_secimi_yalnizca_dry_runda_saglayici_varsayilani_degismez(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_DRYRUN_KEY", "dry-anahtari-5678")
    with pytest.raises(gm.GercekUretimHatasi) as e:   # sağlayıcı kendi başına DRYRUN anahtarını kullanmaz
        gm.GeminiLLMProvider()
    assert e.value.sinif == "anahtar_yok"


def _dry_run_ortami(monkeypatch, davranis):
    from motor.orkestrasyon import canli_dry_run as cdr
    ag = _wp_ag()
    monkeypatch.setattr(cdr, "_kesif", lambda: kk.WikipediaKesif(ag.istemci()))
    monkeypatch.setattr(cdr, "_dogrulayici", lambda: kd.KaynakDogrulayici(ag.istemci()))
    monkeypatch.setattr(cdr, "_openalex", lambda: kk.OpenAlexKesif(ag.istemci()))
    t, kayit = _kayitci(davranis)
    gercek = gm.GeminiLLMProvider
    monkeypatch.setattr(cdr, "GeminiLLMProvider", lambda **kw: gercek(**dict(kw, tasiyici=t, uyku=lambda s: None)))
    return cdr, kayit


@pytest.mark.parametrize("dry,api,kullanilan", [("dry-anahtari-5678", "api-anahtari-1234", "dry-anahtari-5678"),
                                                (None, "api-anahtari-1234", "api-anahtari-1234")])
def test_dry_run_secilen_anahtari_kullanir_429da_durur_ve_maskeler(monkeypatch, capsys, tmp_path, dry, api, kullanilan):
    for ad, d in (("GEMINI_DRYRUN_KEY", dry), ("GEMINI_API_KEY", api)):
        if d:
            monkeypatch.setenv(ad, d)
        else:
            monkeypatch.delenv(ad, raising=False)
    cdr, kayit = _dry_run_ortami(monkeypatch, lambda m, n: (429, f'{{"error": "quota exceeded for key {kullanilan}"}}'))
    kod = cdr.main(["Örnekova Muharebesi", "--mod", "uzun,shorts", "--cikti", str(tmp_path)])
    cikti = capsys.readouterr().out + (tmp_path / "dry_run.json").read_text()
    assert kod == 4 and kayit and {a for _, a in kayit} == {kullanilan}     # yalnız seçilen anahtar gönderildi
    assert len(kayit) <= 3                                                   # paralel parçalar dahil, 429 sonrası yeni istek yok
    r = json.loads((tmp_path / "dry_run.json").read_text())
    assert r["durum"] == "gemini_kota" and r["asamalar"]["3_gemini_shorts"]["durum"] == "atlandi_kota"
    assert r["gemini_anahtar_kaynagi"] == ("GEMINI_DRYRUN_KEY" if dry else "GEMINI_API_KEY")
    for d in (dry, api):
        if d:
            assert d not in cikti                                           # anahtar değeri hiçbir çıktıda yok
    assert "KOTA" in cikti and "mock" in cikti


def test_dry_run_anahtar_yoksa_atlar(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_DRYRUN_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    cdr, kayit = _dry_run_ortami(monkeypatch, lambda m, n: _yanit200())
    assert cdr.main(["Örnekova Muharebesi", "--mod", "uzun", "--cikti", str(tmp_path)]) == 0
    r = json.loads((tmp_path / "dry_run.json").read_text())
    assert r["durum"] == "gemini_atlandi" and kayit == [] and r["gemini_anahtar_kaynagi"] is None


def test_is_akisi_dryrun_anahtarini_yalniz_canli_adimda_verir():
    import yaml
    from pathlib import Path
    wf = yaml.safe_load(Path(".github/workflows/faz53a_gercek_kanit.yml").read_text())
    for a in wf["jobs"]["kanit"]["steps"]:
        env = a.get("env") or {}
        if a.get("name", "").startswith("5) Canlı dry-run"):
            assert "GEMINI_DRYRUN_KEY" in env and "GEMINI_API_KEY" in env and "workflow_dispatch" in a["if"]
        else:
            assert "GEMINI_DRYRUN_KEY" not in env and "GEMINI_API_KEY" not in env, a.get("name")


def test_dry_run_son_guvence_maskelemesi(monkeypatch, capsys):
    """Sağlayıcı maskesinden bağımsız son katman: log satırları ve çıktı ortamdaki bütün anahtar değerlerini gizler."""
    from motor.orkestrasyon import canli_dry_run as cdr
    monkeypatch.setenv("GEMINI_DRYRUN_KEY", "dry-anahtari-5678")
    monkeypatch.setenv("GEMINI_API_KEY", "api-anahtari-1234")
    monkeypatch.setenv("OPENALEX_API_KEY", "oa-anahtari-9999")
    cdr.log("test", "sızıntı denemesi dry-anahtari-5678 api-anahtari-1234 oa-anahtari-9999")
    out = capsys.readouterr().out
    assert "5678" not in out and "1234" not in out and "9999" not in out and out.count("***") == 3
    assert cdr._maskele('{"k": "api-anahtari-1234"}') == '{"k": "***"}'
