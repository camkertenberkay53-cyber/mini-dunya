"""Faz-53A A1: format profili (shorts değişmez, uzun 16:9), 2.5D çekim türü, lisans kapısı, _gorsel25d_render."""
import json
import subprocess

import cv2
import numpy as np
import pytest

from motor import ayar
from motor.uretim import render, uretim_hatti, veri
from motor.varlik import tarihi_gorsel as tg


def _kayit(tmp_path, gorsel, **ek):
    g = {"gorsel_id": "deneme_g", "kaynak_url": "https://ornek.invalid/x", "kaynak_kurum": "deneme", "eser_adi": "deneme",
         "tarih": "1900", "bolge": "x", "donem": "x", "kultur": "x", "taraf_faction": "x", "gorsel_turu": "gravur",
         "uygun_sahne_turleri": ["baglam"], "cozunurluk": [400, 300], "ozne_bilgisi": "yok", "derinlik_uygunlugu": "orta",
         "lisans_turu": "PD-Old", "kamu_mali_gerekcesi": "deneme", "lisans_dogrulandi": True,
         "onay": {"onaylayan": "test", "tarih": "2026-11-26"}, "yerel_yol": str(gorsel), "sha256": tg._sha(gorsel)}
    g.update(ek)
    yol = tmp_path / "kayit.json"
    yol.write_text(json.dumps({"gorseller": [g]}))
    return yol, g


def _gorsel(tmp_path, kanal=3, boyut=(300, 400)):
    h, w = boyut
    y = np.linspace(0, 1, h)[:, None, None]
    img = (np.concatenate([np.full((h, w, 1), 200.0), 160 * (1 - y) * np.ones((h, w, 1)), 90 * y * np.ones((h, w, 1))], 2)).astype(np.uint8)
    if kanal == 4:
        img = np.dstack([img, np.full((h, w), 128, np.uint8)])
    p = tmp_path / f"g{kanal}.png"
    cv2.imwrite(str(p), img)
    return p


def test_format_profili_shorts_degismez_uzun_16_9():
    k = veri.kural("format")
    assert k["varsayilan"] == "shorts"
    assert k["profiller"]["shorts"] == {"cozunurluk": [1080, 1920], "fps": 30, "altyazi": "yak"}
    assert k["profiller"]["uzun"]["cozunurluk"] == [1920, 1080] and k["profiller"]["uzun"]["altyazi"] == "srt"
    assert uretim_hatti.format_profili({})[0] == "shorts"
    assert uretim_hatti.format_profili({"format": "uzun"})[1]["cozunurluk"] == [1920, 1080]
    for p in ("otlukbeli-1473", "roma-lejyon-kartali"):   # mevcut pilot planları shorts; 'format' alanı eklenmedi
        plan = json.loads((ayar.MOTOR / "uretim/pilotlar" / p / "cekim_plani.json").read_text())
        assert plan["cozunurluk"] == [1080, 1920] and "format" not in plan


def test_semalarda_gorsel25d_turu():
    for ad in ("cekim_plani", "senaryo"):
        s = json.loads((ayar.MOTOR / f"uretim/semalar/{ad}.schema.json").read_text())
        assert "gorsel25d" in json.dumps(s)
    s = json.loads((ayar.MOTOR / "uretim/semalar/cekim_plani.schema.json").read_text())
    assert s["properties"]["cekimler"]["items"]["properties"]["tur"]["enum"] == ["3d", "harita", "bilgi_karti", "gorsel25d"]


def test_lisans_kapisi(tmp_path):
    p = _gorsel(tmp_path)
    yol, g = _kayit(tmp_path, p)
    assert tg.dogrulanmis_dosya("deneme_g", yol)[0] == p
    assert tg.IZINLI_LISANSLAR == ("CC0-1.0", "PD-Old", "PD-Art")
    for ek, beklenen in (({"lisans_turu": "CC-BY-4.0"}, "izin verilmeyen lisans"),
                         ({"lisans_dogrulandi": False}, "insan tarafından doğrulanmamış"),
                         ({"onay": {}}, "insan tarafından doğrulanmamış"),
                         ({"durum": "red", "red_nedeni": "müze fotoğraf telifi"}, "reddedilmiş"),
                         ({"sha256": "0" * 64}, "SHA-256"),
                         ({"kaynak_url": ""}, "eksik alan kaynak_url")):
        yol, _ = _kayit(tmp_path, p, **ek)
        with pytest.raises(tg.LisansHatasi, match=beklenen):
            tg.dogrulanmis_dosya("deneme_g", yol)
    with pytest.raises(tg.LisansHatasi, match="kaydında yok"):
        tg.dogrulanmis_dosya("olmayan", yol)


def test_uretim_kaydi_motor_tarafindan_onaylanmaz():
    """Depodaki kayıtta lisans onayı yalnız insan tarafından girilir; motor kodu bu alanları yazmaz."""
    assert tg.kayit_denetle() == []
    for dosya in ("varlik/tarihi_gorsel.py", "uretim/render.py", "uretim/planlayici.py"):
        metin = (ayar.MOTOR / dosya).read_text()
        assert '["lisans_dogrulandi"] =' not in metin and "'lisans_dogrulandi': True" not in metin


def test_rgba_ve_16bit_uc_kanala(tmp_path):
    p4 = _gorsel(tmp_path, kanal=4)
    yeni, bilgi = render._g25_kaynak(p4, tmp_path)
    assert bilgi["kanal"] == 4 and "RGBA->BGR (nötr gri zemin)" in bilgi["donusum"]
    assert cv2.imread(str(yeni), cv2.IMREAD_UNCHANGED).shape[2] == 3
    assert cv2.imread(str(p4), cv2.IMREAD_UNCHANGED).shape[2] == 4   # özgün dosya değişmedi
    p3 = _gorsel(tmp_path)
    assert render._g25_kaynak(p3, tmp_path) == (p3, {"kaynak_boyut": [400, 300], "kanal": 3, "bit": 8, "donusum": []})
    p16 = tmp_path / "g16.png"
    cv2.imwrite(str(p16), (cv2.imread(str(p3)).astype(np.uint16) * 257))
    yeni, bilgi = render._g25_kaynak(p16, tmp_path)
    assert bilgi["bit"] == 16 and cv2.imread(str(yeni), cv2.IMREAD_UNCHANGED).dtype == np.uint8


def _plan(tmp_path, cekim):
    plan = {"surum": 1, "konu": "deneme-25d", "donem": "osmanli-15yy", "donemler": ["osmanli-15yy"], "fps": 30,
            "cozunurluk": [270, 480], "tohum": 1, "cekimler": [cekim], "eksikler": [],
            "ses": {"motor": "piper", "cizelge": [], "toplam_sn": 1.0}}
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(plan))
    return p


def test_gorsel25d_render_kapisi_anahtari_ve_cikti(tmp_path, monkeypatch):
    p = _gorsel(tmp_path)
    yol, g = _kayit(tmp_path, p)
    monkeypatch.setattr(tg, "KAYIT", yol)
    monkeypatch.setattr(render, "KOK", tmp_path / "uretim")
    cekim = {"id": "G1", "cumleler": ["C1"], "sure_sn": 0.5, "tur": "gorsel25d", "metin": "deneme",
             "gorsel25d": {"gorsel_id": "deneme_g", "hareket": "push_in", "parallax": 0.0}}
    plan = _plan(tmp_path, cekim)
    r = render.render(str(plan), "G1")
    assert r["durum"] == "TAMAM", r
    o = r["olculen"]
    assert o["tur"] == "gorsel25d" and o["uretilen_kare"] == o["kare"] == 15 and o["cozunurluk"] == "270x480"
    pr = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=pix_fmt,codec_name",
                         "-of", "json", r["video"]], capture_output=True, text=True)
    assert json.loads(pr.stdout)["streams"][0] == {"codec_name": "h264", "pix_fmt": "yuv420p"}
    assert render.render(str(plan), "G1")["onbellekten"] is True
    # anahtar içerikten: görsel içeriği değişince (sha256) yeni karma
    karma = r["karma"]
    img = cv2.imread(str(p))
    img[0, 0] = (0, 0, 0)
    cv2.imwrite(str(p), img)
    yol, _ = _kayit(tmp_path, p)
    r2 = render.render(str(plan), "G1")
    assert r2["durum"] == "TAMAM" and r2["karma"] != karma
    # lisans kapısı: onay kaldırılınca render reddedilir
    _kayit(tmp_path, p, lisans_dogrulandi=False)
    shutil_kok = tmp_path / "uretim"
    assert render.render(str(plan), "G1", onbellek=False)["durum"] == "REDDEDİLDİ"
    # tek anahtar kapalı → eski davranış (ATLANDI)
    k = dict(veri.kural("gorsel"))
    monkeypatch.setattr(veri, "kural", lambda ad, _k=k, _o=veri.kural: dict(_k, gorsel25d={"acik": False}) if ad == "gorsel" else _o(ad))
    assert render.render(str(plan), "G1")["durum"] == "ATLANDI"
    assert shutil_kok.exists()


def test_planlayici_onaysiz_gorseli_eksik_yazar(tmp_path, monkeypatch):
    from motor.uretim import planlayici
    monkeypatch.setattr(tg, "KAYIT", tmp_path / "bos.json")
    taslak = {"id": "S1", "cumle": "C1", "sure_sn": 3.0, "amac": "baglam",
              "niyet": {"tur": "gorsel25d", "aciklama": "portre", "gorsel25d": {"gorsel_id": "yok_g"}}}
    c, eks, _ = planlayici.cekim_kur(taslak, "osmanli-15yy", 16 / 9, [], 1)
    assert "gorsel25d" not in c and eks and "2.5D görsel kullanılamaz" in eks[0]
