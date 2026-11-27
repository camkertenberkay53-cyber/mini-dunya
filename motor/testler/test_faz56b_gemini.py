"""Faz-56B — Gemini 503 aşırı yük dayanıklılığı ve uzun belgeselin SIRALI parça üretimi (ağsız, deterministik).

Beklemeler enjekte edilen `uyku` ile ölçülür; testler gerçekten 15/30 sn beklemez.
"""
from __future__ import annotations

import json
import threading

import pytest

from motor.orkestrasyon import gemini as gm
from motor.orkestrasyon import senaryo_planlayici as sp
from motor.orkestrasyon.llm import LLMHatasi, LLMProvider, MockLLMProvider

ANAHTAR = "AIzaTEST-faz56b-0123456789"


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


# ------------------------------------------------------------------ 503 tekrar / bekleme

def test_503_sonra_15_sn_bekleyip_ayni_modelle_basarir(monkeypatch):
    g, istek, uyku = _saglayici(monkeypatch, lambda m, n: (503, "high demand") if n == 1 else _y200("tamam"))
    assert g.tamamla("x", "anlati", {}) == "tamam"
    assert uyku == [15.0] and istek == ["gemini-flash-latest", "gemini-flash-latest"]
    assert g.tekrar_kaydi == [{"etiket": "anlati", "model": "gemini-flash-latest", "tekrar": 1, "bekleme_sn": 15.0,
                               "kaynak": "plan"}]
    assert [h["sinif"] for h in g.hatalar] == ["asiri_yuk"]


def test_ikinci_503_te_30_sn(monkeypatch):
    g, istek, uyku = _saglayici(monkeypatch, lambda m, n: (503, "x") if n <= 2 else _y200("ok"))
    assert g.tamamla("x", "anlati", {}) == "ok" and uyku == [15.0, 30.0] and len(istek) == 3
    assert len(set(istek)) == 1                                   # 503'te başka modele yük bindirilmez


@pytest.mark.parametrize("deger,beklenen", [("7", 7.0), ("0", 0.0), ("9999", gm.RETRY_AFTER_TAVANI), ("-5", 0.0)])
def test_retry_after_basligi_oncelikli(monkeypatch, deger, beklenen):
    g, istek, uyku = _saglayici(monkeypatch, lambda m, n: (503, "x", {"retry-after": deger}) if n == 1 else _y200("ok"))
    assert g.tamamla("x", "anlati", {}) == "ok" and uyku == [beklenen]
    assert g.tekrar_kaydi[0]["kaynak"] == "retry-after"


def test_retry_after_http_tarihi_ve_gecersiz_deger():
    from email.utils import formatdate
    assert gm.retry_after_sn({"retry-after": formatdate(1000 + 12, usegmt=True)}, simdi=1000.0) == pytest.approx(12.0, abs=1)
    assert gm.retry_after_sn({"retry-after": "yarın"}) is None and gm.retry_after_sn({}) is None


def test_503_tekrar_limiti_asilinca_kontrollu_durur_sonsuz_dongu_yok(monkeypatch):
    # Faz-57: yedek geçişi kapalıyken birincil modelin 503 sınırı (yedekli yol test_faz57_* içinde)
    g, istek, uyku = _saglayici(monkeypatch, lambda m, n: (503, "x"), en_cok_tekrar=5, yedek_503=False)
    with pytest.raises(gm.GercekUretimHatasi) as e:
        g.tamamla("x", "anlati", {})
    assert e.value.sinif == "asiri_yuk" and "2 tekrardan sonra" in str(e.value) and ANAHTAR not in str(e.value)
    assert uyku == [15.0, 30.0] and len(istek) == 3 and set(istek) == {"gemini-flash-latest"}


def test_503_beklemesi_sure_butcesini_asarsa_beklemeden_durur(monkeypatch):
    saat = [0.0]
    # Faz-58: yedek kapalıyken (yedekli yolda birincil, rezervi aşan beklemede yedeğe geçer: test_faz58_*)
    g, istek, uyku = _saglayici(monkeypatch, lambda m, n: (503, "x", {"retry-after": "100"}), sure_butcesi=50.0,
                                saat=lambda: saat[0], yedek_503=False)
    with pytest.raises(gm.GercekUretimHatasi) as e:
        g.tamamla("x", "anlati", {})
    assert e.value.sinif == "asiri_yuk" and "süre bütçesini aşıyor" in str(e.value) and uyku == [] and len(istek) == 1


def test_429_aninda_durur_503_beklemesi_yapilmaz(monkeypatch):
    g, istek, uyku = _saglayici(monkeypatch, lambda m, n: (503, "x") if n == 1 else (429, "quota"))
    with pytest.raises(gm.GeminiKotaHatasi):
        g.tamamla("x", "anlati", {})
    assert uyku == [15.0] and len(istek) == 2                    # 429'dan sonra bekleme ve istek yok
    with pytest.raises(gm.GeminiKotaHatasi):
        g.tamamla("y", "anlati", {})
    assert len(istek) == 2


def test_500_ve_zaman_asimi_ayrimi_korunur(monkeypatch):
    g, istek, uyku = _saglayici(monkeypatch, lambda m, n: (500, "x") if n <= 2 else _y200("ok"), en_cok_tekrar=1)
    assert g.tamamla("x", "anlati", {}) == "ok"
    assert [h["sinif"] for h in g.hatalar] == ["sunucu", "sunucu"] and 15.0 not in uyku and 30.0 not in uyku

    def zaman(m, n):
        raise TimeoutError("timed out")
    g2, istek2, uyku2 = _saglayici(monkeypatch, zaman, en_cok_tekrar=0)
    with pytest.raises(gm.GercekUretimHatasi) as e:
        g2.tamamla("x", "anlati", {})
    assert e.value.sinif == "zaman_asimi" and 15.0 not in uyku2


def test_503_kurtarma_tek_yanit_doner_cift_uretim_yok(monkeypatch):
    g, istek, uyku = _saglayici(monkeypatch, lambda m, n: (503, "x") if n == 1 else _y200(f"yanit-{n}"))
    assert g.tamamla("x", "anlati", {}) == "yanit-2" and g.cagri_sayisi == 2


def test_istek_ve_tekrar_loglanir(monkeypatch):
    log = []
    g, istek, uyku = _saglayici(monkeypatch, lambda m, n: (503, "x") if n == 1 else _y200("ok"),
                                ilerleme=lambda a, m: log.append(m))
    g.tamamla("x", "anlati", {"bolum": "hook"})
    assert any("503_tekrar=0/2" in x for x in log) and any("503_tekrar=1/2" in x for x in log)
    assert any("↻ anlati/hook" in x and "15 sn bekleniyor" in x and "tekrar 1/2" in x for x in log)


def test_testlerde_bekleme_sifirlanabilir(monkeypatch):
    g, istek, uyku = _saglayici(monkeypatch, lambda m, n: (503, "x") if n <= 2 else _y200("ok"), beklemeler_503=(0, 0))
    assert g.tamamla("x", "anlati", {}) == "ok" and uyku == [0.0, 0.0]


# ------------------------------------------------------------------ uzun belgesel: sıralı parça üretimi

class Kayitci(LLMProvider):
    """MockLLMProvider'ı sarar: çağrı sırasını, eşzamanlılığı kaydeder; belirli parçada hata enjekte eder."""
    ad, sentetik = "mock", True

    def __init__(self, hata=None):
        self.ic = MockLLMProvider()
        self.hata = hata or (lambda adim, grup, n: None)
        self.cagrilar, self.aktif, self.en_cok_aktif = [], 0, 0
        self._k = threading.Lock()

    def tamamla(self, istem, adim, baglam):
        with self._k:
            self.aktif += 1
            self.en_cok_aktif = max(self.en_cok_aktif, self.aktif)
        try:
            grup = tuple(baglam.get("bolumler") or ())
            n = sum(1 for a, g, _ in self.cagrilar if a == adim and g == grup) + 1
            self.cagrilar.append((adim, grup, istem))
            h = self.hata(adim, grup, n)
            if isinstance(h, BaseException):
                raise h
            if h == "bozuk":
                return "bu json değil"
            return self.ic.tamamla(istem, adim, baglam)
        finally:
            with self._k:
                self.aktif -= 1


G1, G2, G3 = (tuple(g) for g in sp.PARCA_GRUPLARI)


def _parca_cagrilari(k, adim):
    return [g for a, g, _ in k.cagrilar if a == adim and g]


def test_uzun_uc_parca_sirali_ve_eszamansiz_degil():
    k = Kayitci()
    r = sp.plan_uret("Örnek Kale", "uzun", k, parcali=True)
    assert r["durum"] == "uretime_hazir"
    assert _parca_cagrilari(k, "anlati") == [G1, G2, G3] and _parca_cagrilari(k, "sahne_plani") == [G1, G2, G3]
    assert k.en_cok_aktif == 1                                   # hiçbir an iki parça birlikte istenmedi
    sira = [c[0] for c in k.cagrilar]
    assert sira.index("sahne_plani") > max(i for i, a in enumerate(sira) if a == "anlati")


def test_uzun_sirali_yapi_regresyonu():
    r = sp.plan_uret("Örnek Kale", "uzun", MockLLMProvider(), parcali=True)
    s = r["plan"]["sahneler"]
    sira = ["hook", "baglam", "catisma", "donum_noktasi", "sonuc"]
    idx = [sira.index(x["bolum"]) for x in s]
    assert idx == sorted(idx) and set(idx) == set(range(5))
    assert [x["id"] for x in s] == [f"s{i + 1:03d}" for i in range(len(s))] and sum(x["hook"] for x in s) == 1
    assert 900 <= r["ozet"]["toplam_sn"] <= 1200 and len(s) == 118
    bolum_sirasi = [b["bolum"] for b in r["anlati"]["birimler"]]
    assert bolum_sirasi == sorted(bolum_sirasi, key=sira.index)


def test_onceki_parca_baglami_sonraki_isteme_tasinir():
    k = Kayitci()
    sp.plan_uret("Örnek Kale", "uzun", k, parcali=True)
    an = [(g, ist) for a, g, ist in k.cagrilar if a == "anlati"]
    assert "ÖNCEKİ PARÇANIN SON BİRİMLERİ" not in an[0][1]
    assert "ÖNCEKİ PARÇANIN SON BİRİMLERİ" in an[1][1] and "ÖNCEKİ PARÇANIN SON BİRİMLERİ" in an[2][1]
    pl = [(g, ist) for a, g, ist in k.cagrilar if a == "sahne_plani"]
    assert "ÖNCEKİ PARÇANIN SON SAHNELERİ" in pl[1][1] and "gorsel_tur" in pl[1][1]


def test_birinci_parca_basarisiz_ikinci_ve_ucuncu_cagrilmaz():
    k = Kayitci(hata=lambda adim, grup, n: "bozuk" if (adim, grup) == ("anlati", G1) else None)
    r = sp.plan_uret("Örnek Kale", "uzun", k, parcali=True)
    assert r["durum"] == "durduruldu" and r["durdugu_katman"] == "3_anlati"
    assert _parca_cagrilari(k, "anlati") == [G1, G1, G1]           # 3 deneme, yalnız 1. parça
    assert not _parca_cagrilari(k, "sahne_plani") and r["render_baslatildi"] is False


def test_ikinci_parca_basarisiz_ucuncu_cagrilmaz():
    k = Kayitci(hata=lambda adim, grup, n: "bozuk" if (adim, grup) == ("anlati", G2) else None)
    r = sp.plan_uret("Örnek Kale", "uzun", k, parcali=True)
    assert r["durum"] == "durduruldu"
    assert _parca_cagrilari(k, "anlati") == [G1, G2, G2, G2]       # 1. parça yeniden istenmedi (önbellek)
    assert G3 not in _parca_cagrilari(k, "anlati")


def test_ikinci_parca_bir_kez_bozuk_sonra_duzelir_birinci_tekrar_uretilmez():
    k = Kayitci(hata=lambda adim, grup, n: "bozuk" if (adim, grup) == ("anlati", G2) and n == 1 else None)
    r = sp.plan_uret("Örnek Kale", "uzun", k, parcali=True)
    assert r["durum"] == "uretime_hazir"
    assert _parca_cagrilari(k, "anlati") == [G1, G2, G2, G3]       # çift üretim yok
    d = r["katmanlar"]["3_anlati"]["denemeler"]
    assert d[0]["hatalar"][0]["kod"] == "json_parse" and len(d) == 2


def test_parcada_429_aninda_durur_sonraki_parcalar_istenmez():
    k = Kayitci(hata=lambda adim, grup, n: gm.GeminiKotaHatasi("kota", "kota") if (adim, grup) == ("anlati", G2) else None)
    r = sp.plan_uret("Örnek Kale", "uzun", k, parcali=True)
    assert r["durum"] == "durduruldu" and r["hatalar"][0]["kod"] == "saglayici_hatasi" and r["hatalar"][0]["sinif"] == "kota"
    assert _parca_cagrilari(k, "anlati") == [G1, G2] and not _parca_cagrilari(k, "sahne_plani")


def test_parcada_503_limiti_asilinca_durur():
    k = Kayitci(hata=lambda adim, grup, n: gm.GercekUretimHatasi("503", "asiri_yuk") if (adim, grup) == ("sahne_plani", G1) else None)
    r = sp.plan_uret("Örnek Kale", "uzun", k, parcali=True)
    assert r["durum"] == "durduruldu" and r["hatalar"][0]["sinif"] == "asiri_yuk"
    assert _parca_cagrilari(k, "sahne_plani") == [G1]


def test_shorts_davranisi_degismez():
    a, b = MockLLMProvider(), MockLLMProvider()
    r1 = sp.plan_uret("Örnek Kale", "shorts", a, parcali=True)
    r2 = sp.plan_uret("Örnek Kale", "shorts", b, parcali=False)
    assert [c["adim"] for c in a.cagrilar] == ["arastirma", "anlati", "sahne_plani"]
    assert r1["plan"] == r2["plan"] and [c["istem"] for c in a.cagrilar] == [c["istem"] for c in b.cagrilar]


def test_gercek_saglayici_parca_ici_503_sonra_bozuk_parca_sonrakiler_istenmez(monkeypatch):
    """Sahte Gemini: ilk istek 503, sonrakiler geçersiz parça ("{}"). Beklenen: 15 sn → aynı parça tekrar; parça
    JSON üretemediği için 2. ve 3. parçalar HİÇ istenmez; 3 deneme sonunda kontrollü durma, render yok."""
    from motor.testler.test_kaynak_dogrulama import _havuz as gercek_havuz  # gerçek-kip araştırma havuzu fixture'ı
    monkeypatch.setenv("GEMINI_API_KEY", ANAHTAR)
    istemler = []

    def t(url, govde, bas, zaman):
        istemler.append(json.loads(govde)["contents"][0]["parts"][0]["text"])
        return (503, "high demand") if len(istemler) == 1 else _y200("{}")
    uyku = []
    g = gm.GeminiLLMProvider(tasiyici=t, uyku=uyku.append)
    r = sp.plan_uret("Örnekova Muharebesi", "uzun", g, arastirma=gercek_havuz(), parcali=True)
    assert uyku == [15.0] and len(g.tekrar_kaydi) == 1 and g.cagri_sayisi == 4   # 503 + 3 deneme
    ilk = "YALNIZCA şu bölüm(ler)i yaz, bu sırayla: " + ", ".join(sp.PARCA_GRUPLARI[0])
    assert all(ilk in x for x in istemler)                                     # yalnız 1. parça istendi
    assert r["durum"] == "durduruldu" and r["durdugu_katman"] == "3_anlati" and r["render_baslatildi"] is False
