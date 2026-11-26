"""Commons toplayıcı (Faz-53A): ağ YOK — API yanıtları ve indirme taklit edilir."""
import hashlib
import json

import cv2
import numpy as np
import pytest

from motor.varlik import commons_toplayici as ct
from motor.varlik import tarihi_gorsel as tg


def _ii(baslik, gen, yuk, mime="image/jpeg", lisans="Public domain", kod="pd", kullanim="Public domain", sha1="x",
        artist="Ressam", atif="false"):
    return {"title": baslik, "imageinfo": [{
        "url": f"https://upload.invalid/{baslik}", "descriptionurl": f"https://commons.invalid/wiki/{baslik}",
        "width": gen, "height": yuk, "mime": mime, "sha1": sha1,
        "extmetadata": {"LicenseShortName": {"value": lisans}, "UsageTerms": {"value": kullanim}, "License": {"value": kod},
                        "Artist": {"value": f"<a href='x'>{artist}</a>"}, "AttributionRequired": {"value": atif},
                        "DateTimeOriginal": {"value": "1480"}, "ObjectName": {"value": baslik.replace("File:", "")}}}]}


def _goruntu_bayt(w, h):
    img = np.full((h, w, 3), 200, np.uint8)
    cv2.rectangle(img, (w // 4, h // 6), (3 * w // 4, h - h // 10), (40, 50, 60), -1)
    ok, b = cv2.imencode(".jpg", img)
    return b.tobytes()


@pytest.fixture
def sahte_ag(monkeypatch):
    sayfalar, dosyalar, istekler = [], {}, []

    def istek(params):
        istekler.append(params)
        return {"query": {"pages": sayfalar}}

    def indir(url, hedef):
        hedef.write_bytes(dosyalar[url])
    monkeypatch.setattr(ct, "_istek_json", istek)
    monkeypatch.setattr(ct, "_indir", indir)
    return sayfalar, dosyalar, istekler


def _ekle(sayfalar, dosyalar, baslik, w, h, **k):
    b = _goruntu_bayt(w, h)
    sayfalar.append(_ii(baslik, w, h, sha1=hashlib.sha1(b).hexdigest(), **k))
    dosyalar[f"https://upload.invalid/{baslik}"] = b
    return b


def test_suzgec_kucuk_svg_ve_telifli_elenir_serbest_lisanslar_kalir():
    ad = lambda **k: {"mime": "image/jpeg", "gen": 3000, "yuk": 2000, "meta": {"LicenseShortName": "Public domain", **k}}  # noqa: E731
    assert ct.elenme_nedeni(ad()) is None
    assert "çözünürlük" in ct.elenme_nedeni(dict(ad(), gen=1200, yuk=900))
    assert "biçim" in ct.elenme_nedeni(dict(ad(), mime="image/svg+xml"))
    assert ct.elenme_nedeni(dict(ad(), mime="image/tiff")) is None
    assert "telifli" in ct.elenme_nedeni(ad(LicenseShortName="All rights reserved"))
    assert "telifli" in ct.elenme_nedeni(ad(LicenseShortName="Copyrighted"))
    assert "telifli" in ct.elenme_nedeni(ad(LicenseShortName="Fair use"))
    assert ct.elenme_nedeni(ad(LicenseShortName="Copyrighted free use")) is None    # serbest Commons lisansı
    assert ct.elenme_nedeni(ad(LicenseShortName="CC BY-SA 4.0")) is None


def test_lisans_kategorisi():
    assert ct.lisans_kategorisi({"LicenseShortName": "Public domain", "License": "pd"}) == ("PD-Old", False)
    assert ct.lisans_kategorisi({"LicenseShortName": "PD-Art (PD-old-100)", "License": "pd"}) == ("PD-Art", False)
    assert ct.lisans_kategorisi({"LicenseShortName": "CC0", "License": "cc0"}) == ("CC0-1.0", False)
    assert ct.lisans_kategorisi({"LicenseShortName": "CC BY-SA 4.0", "License": "cc-by-sa-4.0"}) == ("CC-BY-SA-4.0", True)
    assert ct.lisans_kategorisi({"LicenseShortName": "CC BY 2.0", "License": "cc-by-2.0"}) == ("CC-BY-2.0", True)


def test_secim_sorgu_ortusmesi_serbest_lisans_ve_cozunurluk():
    a = [{"baslik": "File:Bellini kopya.jpg", "gen": 5000, "yuk": 6000, "mime": "image/jpeg", "meta": {"License": "cc-by-sa-4.0", "LicenseShortName": "CC BY-SA 4.0"}},
         {"baslik": "File:Gentile Bellini Sultan Mehmed II.jpg", "gen": 3000, "yuk": 4000, "mime": "image/jpeg", "meta": {"License": "pd"}},
         {"baslik": "File:Gentile Bellini Sultan Mehmed II kucuk.jpg", "gen": 800, "yuk": 1000, "mime": "image/jpeg", "meta": {"License": "pd"}}]
    s, elenen = ct.sec(a, "Gentile Bellini Sultan Mehmed II")
    assert s["baslik"] == "File:Gentile Bellini Sultan Mehmed II.jpg" and len(elenen) == 1
    s2, _ = ct.sec(a, "Gentile Bellini Sultan Mehmed II", tercih="Bellini kopya")   # tercih ipucu öne geçer
    assert s2["baslik"] == "File:Bellini kopya.jpg"


def test_topla_indirir_dogrular_ve_kapidan_gecer(sahte_ag, tmp_path, monkeypatch):
    sayfalar, dosyalar, istekler = sahte_ag
    _ekle(sayfalar, dosyalar, "File:Ikon.jpg", 300, 300)
    b = _ekle(sayfalar, dosyalar, "File:Gentile Bellini 003.jpg", 2100, 2800, lisans="Public domain", kod="pd")
    k = ct.topla({"gorsel_id": "t_portre", "sorgu": "Gentile Bellini Sultan Mehmed II", "tur": "insan_portre",
                  "derinlik_uygunlugu": "dusuk", "donem": "osmanli-15yy"}, tmp_path)
    assert istekler[0]["generator"] == "search" and istekler[0]["gsrnamespace"] == 6 and "extmetadata" in istekler[0]["iiprop"]
    p = tmp_path / "t_portre.jpg"
    assert p.read_bytes() == b and k["sha256"] == hashlib.sha256(b).hexdigest()
    assert k["cozunurluk"] == [2100, 2800] and k["lisans_turu"] == "PD-Old" and k["lisans_dogrulandi"] is True
    assert k["lisans_commons"]["LicenseShortName"] == "Public domain" and "atif" not in k
    kutu = k["ozne_bilgisi"]["kutu"]
    assert 0 <= kutu[0] < kutu[2] <= 1 and 0 <= kutu[1] < kutu[3] <= 1 and k["ozne_bilgisi"]["tur"] == "insan_portre"
    j = json.loads((tmp_path / "t_portre.json").read_text())
    assert j == k
    monkeypatch.setattr(tg, "YAN_DOSYA_KOK", tmp_path)
    monkeypatch.setattr(tg, "KAYIT", tmp_path / "yok.json")
    yol, kayit = tg.dogrulanmis_dosya("t_portre")    # mevcut üretim kapısı: lisans + onay + SHA-256
    assert yol == p


def test_atifli_lisans_kapidan_atifla_gecer(sahte_ag, tmp_path, monkeypatch):
    sayfalar, dosyalar, _ = sahte_ag
    _ekle(sayfalar, dosyalar, "File:Kale gravur.jpg", 3000, 2000, lisans="CC BY-SA 4.0", kod="cc-by-sa-4.0", atif="true", artist="Foto Çeken")
    k = ct.topla({"gorsel_id": "t_kale", "sorgu": "Kale gravur", "tur": "mimari"}, tmp_path)
    assert k["lisans_turu"] == "CC-BY-SA-4.0" and k["atif"] == {"yazar": "Foto Çeken", "lisans": "CC BY-SA 4.0",
                                                                "kaynak": "https://commons.invalid/wiki/File:Kale gravur.jpg"}
    monkeypatch.setattr(tg, "YAN_DOSYA_KOK", tmp_path)
    monkeypatch.setattr(tg, "KAYIT", tmp_path / "yok.json")
    assert tg.dogrulanmis_dosya("t_kale")[0].name == "t_kale.jpg"
    atifsiz = dict(k)
    atifsiz.pop("atif")
    assert any("izin verilmeyen lisans" in h for h in tg.denetle(atifsiz))


def test_telifli_ve_kucuk_adaylar_varsa_hata(sahte_ag, tmp_path):
    sayfalar, dosyalar, _ = sahte_ag
    _ekle(sayfalar, dosyalar, "File:A.jpg", 3000, 2000, lisans="All rights reserved", kod="arr")
    _ekle(sayfalar, dosyalar, "File:B.jpg", 900, 600)
    with pytest.raises(ct.ToplayiciHatasi, match="uygun aday yok"):
        ct.topla({"gorsel_id": "t_yok", "sorgu": "A B"}, tmp_path)
    assert not list(tmp_path.glob("t_yok*"))


def test_sha1_uyusmazsa_dosya_silinir(sahte_ag, tmp_path):
    sayfalar, dosyalar, _ = sahte_ag
    _ekle(sayfalar, dosyalar, "File:C.jpg", 3000, 2000)
    sayfalar[-1]["imageinfo"][0]["sha1"] = "0" * 40
    with pytest.raises(ct.ToplayiciHatasi, match="SHA-1"):
        ct.topla({"gorsel_id": "t_sha", "sorgu": "C"}, tmp_path)
    assert not (tmp_path / "t_sha.jpg").exists()


def test_yedek_sorgu_ve_kategori(sahte_ag, tmp_path):
    sayfalar, dosyalar, istekler = sahte_ag
    _ekle(sayfalar, dosyalar, "File:D kucuk.jpg", 500, 500)
    with pytest.raises(ct.ToplayiciHatasi):
        ct.topla({"gorsel_id": "t_d", "sorgu": "D", "yedek_sorgular": ["D2"], "kategori": "Ornek kategori"}, tmp_path)
    assert [i.get("gsrsearch") or i.get("gcmtitle") for i in istekler] == ["D", "D2", "Category:Ornek kategori"]


def test_ag_yoksa_acik_hata(monkeypatch):
    def kopuk(*a, **k):
        raise OSError("403 proxy")
    monkeypatch.setattr(ct.urllib.request, "urlopen", kopuk)
    monkeypatch.setattr(ct.time, "sleep", lambda *_: None)
    with pytest.raises(ct.ToplayiciHatasi, match="Commons API'ye ulaşılamadı"):
        ct.ara(sorgu="x")


def test_sorgu_dosyasi_ve_is_akisi():
    from motor import ayar
    s = json.loads((ayar.REPO / "deneyler/faz53a/gercek/sorgular.json").read_text())
    assert {x["gorsel_id"] for x in s} == {"fatih_portre_bellini_1480", "matrakci_istanbul_1537"}
    assert {x["tur"] for x in s} == {"insan_portre", "mimari"} and all(x["derinlik_uygunlugu"] == "dusuk" for x in s)
    y = (ayar.REPO / ".github/workflows/faz53a_gercek_kanit.yml").read_text()
    for parca in ("workflow_dispatch", "commons_toplayici", "olc_kanit.py gercek hepsi", "upload-artifact", "pytest"):
        assert parca in y
    assert "git push" not in y and "git commit" not in y          # kaynak görseller depoya girmez
