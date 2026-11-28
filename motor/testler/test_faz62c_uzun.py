"""Faz-62c — uzun belgesel (16:9, 15–20 dk) motoru: anlatı kapıları, format seçimi, 16:9 / 9:16 bölme, SRT, kurgu
hata yolları, kalite kapıları, otonom uzun / her_ikisi akışı ve iş akışı. Çevrimdışı; ağ ve Gemini YOK.
ffmpeg gerektiren testler ffmpeg yoksa atlanır."""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import types
from pathlib import Path

import pytest

from motor.uretim import anlati, harita, render, sahne_bolucu, sozlesme, uretim_hatti, uzun_kurgu, veri

KOK = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("otonom_uret_62c", KOK / "otonom_uret.py")
ou = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ou)
PILOT = KOK / "motor/uretim/pilotlar/otlukbeli-1473"
WF = KOK / ".github" / "workflows" / "belgesel_uret.yml"
FFMPEG = shutil.which("ffmpeg") is not None
ROLLER = veri.kural("uzun")["bolum"]["roller"]


# ================================================================== yardımcılar

def _metin(i: int, n: int = 16) -> str:
    """Birbirini tekrar etmeyen, n kelimelik cümle (içerik kelimeleri cümleye özgü)."""
    return f"Belge {i} anlatımı " + " ".join(f"k{i}x{j}" for j in range(n - 3))


def _olc(cs):
    return {c["id"]: {"sure_sn": round(len(c["metin"].split()) / 2.3, 3), "harf_sn": 14.0, "motor": "sahte",
                      "wav": f"/yok/{c['id']}.wav"} for c in cs}


def _uzun_senaryo(bolum=7, cumle=20, n=16, tur="harita"):
    bs = []
    rol_gruplari = [["kanca", "baglam"], ["taraflar"], ["savas_oncesi"], ["savas"], ["sonuc"], ["etkiler"], ["kapanis"]]
    if bolum == 6:
        rol_gruplari = [["kanca", "baglam"], ["taraflar"], ["savas_oncesi"], ["savas"], ["sonuc", "etkiler"], ["kapanis"]]
    for i in range(bolum):
        bs.append({"id": f"B{i + 1}", "baslik": f"Bölüm {i + 1}", "roller": rol_gruplari[i] if i < len(rol_gruplari) else ["kapanis"]})
    cs, no = [], 1
    for b in bs:
        for _ in range(cumle):
            cs.append({"id": f"S{no}", "metin": _metin(no, n), "kartlar": ["C1"], "bolum": b["id"],
                       "niyet": {"tur": tur, "evre": "E1", "metin": f"başlık {no}"}})
            no += 1
    return {"surum": 1, "konu": "t", "format": "uzun", "baslik": "T", "bolumler": bs, "cumleler": cs,
            "kanca": "S1", "final": cs[-1]["id"]}


ARA = {"surum": 1, "konu": "t", "kaynaklar": [{"id": "K1", "baslik": "x", "url": "", "tur": "ikincil"}],
       "kartlar": [{"id": "C1", "iddia": "x", "guven": "kesin", "kaynaklar": ["K1"]}]}


# ================================================================== format seçimi

def test_format_secimi_profiller():
    assert uretim_hatti.format_profili({"format": "uzun"}) == ("uzun", {"cozunurluk": [1920, 1080], "fps": 30, "altyazi": "srt"})
    assert uretim_hatti.format_profili({"format": "shorts"})[1]["cozunurluk"] == [1080, 1920]
    assert uretim_hatti.format_profili({})[0] == "shorts" and uretim_hatti.format_profili({"format": "x"})[0] == "shorts"


def test_anlati_bicime_gore_dogru_denetimi_secer(monkeypatch):
    cagri = []
    monkeypatch.setattr(anlati, "shorts_denetle", lambda s, sr: cagri.append("shorts") or ([], {}))
    monkeypatch.setattr(anlati, "uzun_denetle", lambda s, sr: cagri.append("uzun") or ([], {}))
    anlati.denetle({"format": "shorts"}, {})
    anlati.denetle({"format": "uzun"}, {})
    anlati.denetle({}, {})
    assert cagri == ["shorts", "uzun", "shorts"]


def test_uretim_hatti_bicime_gore_anlati_cagirir():
    assert "anlati.denetle(sen, sureler)" in (KOK / "motor/uretim/uretim_hatti.py").read_text()


# ================================================================== uzun anlatı kapısı

def test_gecerli_uzun_senaryo_semadan_ve_anlatidan_gecer():
    s = _uzun_senaryo()
    assert sozlesme.senaryo_denetle(s, ARA) == []
    h, o = anlati.uzun_denetle(s, _olc(s["cumleler"]))
    assert h == [] and o["cumle_sayisi"] == 140 and len(o["bolum_konusma_sn"]) == 7


def test_shorts_sinirlari_uzuna_uygulanmaz():
    s = _uzun_senaryo(n=24)                  # 140 cümle, 24 kelime: Shorts'ta iki kural birden kırılırdı
    h, _ = anlati.uzun_denetle(s, _olc(s["cumleler"]))
    assert h == []
    hs, _ = anlati.shorts_denetle(dict(s, format="shorts", ana_fikir="x" * 12), _olc(s["cumleler"]))
    assert any("en çok 10" in x for x in hs)


@pytest.mark.parametrize("bozma, beklenen", [
    (lambda s: s.update(bolumler=s["bolumler"][:5]), "5 bölüm"),
    (lambda s: s["bolumler"][3].update(roller=["savas_oncesi"]), "eksik bölüm rolleri: savas"),
    (lambda s: s["bolumler"][1].update(roller=["sonuc"]), "kronolojik"),
    (lambda s: s["bolumler"][0].update(roller=["baglam"]), "kanca"),
    (lambda s: s["cumleler"][30].update(bolum="B1"), "bitişik"),
    (lambda s: s["cumleler"][5].update(metin=_metin(6, 40)), "40 kelime"),
    (lambda s: s["cumleler"][5].update(metin="Kısa cümle."), "en az 4"),
    (lambda s: s["cumleler"][9].update(metin=s["cumleler"][3]["metin"]), "aynı cümle"),
    (lambda s: s.update(final="S1"), "final son cümle"),
])
def test_uzun_anlati_hatalari(bozma, beklenen):
    s = _uzun_senaryo()
    bozma(s)
    h, _ = anlati.uzun_denetle(s, _olc(s["cumleler"]))
    assert any(beklenen in x for x in h), h


def test_kanca_olculen_sure_ve_merak_isareti():
    s = _uzun_senaryo()
    s["cumleler"][0]["metin"] = "Bu açılış cümlesi hiçbir rakam ya da soru içermeyen düz bir anlatımdır efendim"
    sr = _olc(s["cumleler"])
    sr["S1"]["sure_sn"] = 14.0
    h, o = anlati.uzun_denetle(s, sr)
    assert any("14.00 sn" in x for x in h) and any("merak" in x for x in h) and o["kanca_sure_sn"] == 14.0


def test_tekrar_yapay_uzatma_yasak():
    k = veri.kural("uzun")["tekrar"]
    a = {"id": "S1", "metin": "Osmanlı ordusu sabah erkenden ovaya inerek düzenli saflar halinde ilerledi"}
    b = {"id": "S2", "metin": "Sabah erkenden Osmanlı ordusu düzenli saflar halinde ovaya inerek ilerledi"}
    c = {"id": "S3", "metin": "Akkoyunlu süvarileri de aynı gün sabah erkenden ovaya inerek düzenli saflar kurup bekledi"}
    h = anlati.tekrar_denetle([a, b], k)
    assert h and "aynı bilgiyi tekrar" in h[0]
    assert any("6 kelimelik" in x for x in anlati.tekrar_denetle([a, c], k))
    assert anlati.tekrar_denetle([a, {"id": "S4", "metin": "Uzun Hasan Venedik elçilerinden top ve tüfek istedi"}], k) == []


def test_uc_d_sinirli():
    s = _uzun_senaryo()
    for c in s["cumleler"][:25]:
        c["niyet"] = {"tur": "3d", "aciklama": "x"}
    h, o = anlati.uzun_denetle(s, _olc(s["cumleler"]))
    assert any("3D cümle" in x for x in h) and o["tur_dagilimi"]["3d"] == 25


# ================================================================== zaman çizelgesi ve bölme (16:9 / 9:16)

def test_shorts_cizelge_ve_bolme_regresyon():
    """9:16: Faz 5.x kuralları aynen (kanca sonrası, final öncesi, kapanış duraklaması; >5 sn çekim ikiye)."""
    d = veri.kural("shorts")["duraklama_sn"]
    s = {"format": "shorts", "cumleler": [
        {"id": "S1", "amac": "kanca", "niyet": {"tur": "3d"}}, {"id": "S2", "amac": "olay", "niyet": {"tur": "3d"}},
        {"id": "S3", "amac": "final", "niyet": {"tur": "harita"}}]}
    sr = {"S1": {"sure_sn": 1.5}, "S2": {"sure_sn": 6.0}, "S3": {"sure_sn": 3.0}}
    z = sahne_bolucu.zaman_cizelgesi(s, sr)
    assert z[0]["ses_bas_sn"] == d["baslangic"] and z[0]["goruntu_bas_sn"] == 0.0
    assert z[1]["ses_bas_sn"] == round(d["baslangic"] + 1.5 + d["kanca_sonrasi"], 3)
    assert z[2]["ses_bas_sn"] == round(z[1]["ses_bas_sn"] + 6.0 + d["final_oncesi"], 3)
    assert sahne_bolucu.toplam_sure(z) == round(z[2]["ses_bas_sn"] + 3.0 + d["kapanis"], 2)
    c = sahne_bolucu.cekimlere_bol(s, z)
    assert [x["id"] for x in c] == ["S1", "S2a", "S2b", "S3"]


def test_uzun_cizelge_bolum_duraklamasi_ve_yalniz_3d_bolunur():
    d = veri.kural("uzun")["duraklama_sn"]
    k = veri.kural("uzun")["cekim"]
    s = {"format": "uzun", "cumleler": [
        {"id": "S1", "bolum": "B1", "niyet": {"tur": "gorsel25d"}}, {"id": "S2", "bolum": "B1", "niyet": {"tur": "3d"}},
        {"id": "S3", "bolum": "B2", "niyet": {"tur": "harita"}}, {"id": "S4", "bolum": "B2", "niyet": {"tur": "gorsel25d"}}]}
    sr = {"S1": {"sure_sn": 5.0}, "S2": {"sure_sn": 20.0}, "S3": {"sure_sn": 14.0}, "S4": {"sure_sn": 4.0}}
    z = sahne_bolucu.zaman_cizelgesi(s, sr)
    assert z[0]["ses_bas_sn"] == d["baslangic"]
    assert z[2]["ses_bas_sn"] == round(z[1]["ses_bas_sn"] + 20.0 + d["bolum_arasi"], 3)     # B1 → B2
    assert z[3]["ses_bas_sn"] == round(z[2]["ses_bas_sn"] + 14.0 + d["cumle_arasi"], 3)
    c = sahne_bolucu.cekimlere_bol(s, z)
    ids = [x["id"] for x in c]
    assert ids[0] == "S1" and "S3" in ids and "S4" in ids                                # harita / 2.5D bölünmez
    uc = [x for x in c if x["cumle"] == "S2"]
    assert len(uc) == 3 and all(k["en_az_sure_sn"] <= x["sure_sn"] <= k["en_cok_sure_sn"] for x in uc)
    assert abs(sum(x["sure_sn"] for x in c) - sahne_bolucu.toplam_sure(z)) < 0.01           # boşluksuz kapsama


# ================================================================== 16:9 render

def test_harita_dikey_yerlesim_degismedi_yatay_alan_bantta():
    v = json.loads((PILOT / "konu.json").read_text())["harita"]
    alan = v.get("alan_km", [10.0, 10.0])
    W, H = 1080 * harita.S, 1920 * harita.S          # dikey: Faz 5.x formülü aynen
    olcek = W / (alan[0] * 1.08)
    import unittest.mock as um
    with um.patch.object(harita.Harita, "_taban", lambda self: None):
        dik = harita.Harita(v, (1080, 1920))
        yat = harita.Harita(v, (2880, 1620))
    assert (dik.olcek, dik.x0, dik.y0) == (olcek, (W - alan[0] * olcek) / 2, (H - alan[1] * olcek) / 2 + H * 0.02)
    ust = yat.p((0, alan[1]))[1]
    alt = yat.p((0, 0))[1]
    assert ust >= yat.H * 0.17 - 1 and alt <= yat.H * 0.95 + 1                            # başlık bandının altında


def test_godot_uzun_proje_kopyasi_asil_projeye_dokunmaz(tmp_path, monkeypatch):
    from motor import ayar
    proje = tmp_path / "proje"
    (proje / "sahneler").mkdir(parents=True)
    (proje / "sahneler" / "cekim.gd").write_text("x")
    asil = "[display]\nwindow/size/viewport_width=1080\nwindow/size/viewport_height=1920\n"
    (proje / "project.godot").write_text(asil)
    monkeypatch.setattr(ayar, "GODOT_PROJE", proje)
    monkeypatch.setattr(ayar, "ONBELLEK", tmp_path / "onb")
    k = render.godot_proje_kopyasi(1920, 1080)
    assert "viewport_width=1920" in (k / "project.godot").read_text() and "viewport_height=1080" in (k / "project.godot").read_text()
    assert (k / "sahneler").is_symlink() and (k / "sahneler").resolve() == (proje / "sahneler").resolve()
    assert (proje / "project.godot").read_text() == asil
    assert render.godot_proje_kopyasi(1920, 1080) == k                                    # tekrar çağrı kararlı


def test_shorts_3d_cozunurluk_korumasi_aynen():
    kod = (KOK / "motor/uretim/render.py").read_text()
    assert 'if plan.get("format") != "uzun":   # Shorts: proje çözünürlüğü şart (değişmedi)' in kod
    assert 'return {"durum": "HATA", "neden": f"Godot projesi {w}x{hgt} değil"}' in kod


# ================================================================== SRT

def _plan_cizelge():
    return {"cozunurluk": [1920, 1080], "fps": 30, "ses": {"toplam_sn": 30.0, "cizelge": [
        {"cumle": "S1", "ses_bas_sn": 0.8, "ses_sure_sn": 6.0, "goruntu_bas_sn": 0.0, "goruntu_son_sn": 7.7},
        {"cumle": "S2", "ses_bas_sn": 7.7, "ses_sure_sn": 9.5, "goruntu_bas_sn": 7.7, "goruntu_son_sn": 19.0}]},
        "cekimler": [{"id": "S1", "tur": "harita", "sure_sn": 7.7, "cumleler": ["S1"], "metin_katmani": "11 Ağustos 1473"},
                     {"id": "S2", "tur": "gorsel25d", "sure_sn": 11.3, "cumleler": ["S2"]}]}


SEN = {"cumleler": [
    {"id": "S1", "metin": "Otlukbeli'de iki Türk ordusu karşılaştı; ağustos sıcağında çadırlar kuruldu.", "bolum": "B1"},
    {"id": "S2", "metin": "Uzun Hasan'ın süvarileri tepelerden indi, Şehzade Mustafa'nın birlikleri ise sağ kanatta "
                          "çetin bir direniş gösterdi ve öğleden sonra savaşın yönü değişti.", "bolum": "B2"}],
    "bolumler": [{"id": "B1", "baslik": "Açılış", "roller": ["kanca"]}, {"id": "B2", "baslik": "Savaş", "roller": ["savas"]}]}


def test_srt_uretimi_satir_siniri_zaman_ve_turkce(tmp_path):
    ip = uzun_kurgu.srt_ipuclari(_plan_cizelge(), SEN)
    k = veri.kural("uzun")["kurgu"]["altyazi"]
    assert all(len(s) <= k["satir_en_cok_harf"] for _, _, m in ip for s in m.split("\n"))
    assert all(m.count("\n") < k["en_cok_satir"] for _, _, m in ip)
    assert ip[0][0] == 0.8 and abs(ip[-1][1] - (7.7 + 9.5)) < 0.01
    assert all(a < b for a, b, _ in ip) and all(ip[i][1] <= ip[i + 1][0] + 1e-6 for i in range(len(ip) - 1))
    yol = uzun_kurgu.srt_yaz(ip, tmp_path / "a.srt")
    metin = yol.read_text(encoding="utf-8")
    assert "Şehzade" in metin and "ağustos" in metin and metin.startswith("1\n00:00:00,800 --> ")
    assert uzun_kurgu.srt_denetle(yol, 30.0) == []


@pytest.mark.parametrize("icerik, beklenen", [
    ("1\n00:00:01,000 --> 00:00:02,000\nA\n\n3\n00:00:03,000 --> 00:00:04,000\nB\n", "sıra numarası"),
    ("1\n00:00:01.000 --> 00:00:02,000\nA\n", "geçersiz zaman kodu"),
    ("1\n00:00:02,000 --> 00:00:01,000\nA\n", "bitiş"),
    ("1\n00:00:01,000 --> 00:00:03,000\nA\n\n2\n00:00:02,000 --> 00:00:04,000\nB\n", "örtüşüyor"),
    ("1\n00:00:01,000 --> 00:01:40,000\nA\n", "video süresini"),
    ("1\n00:00:01,000 --> 00:00:02,000\n \n", "boş metin"),
    ("", "SRT boş"),
])
def test_srt_zaman_kodu_denetimi(tmp_path, icerik, beklenen):
    p = tmp_path / "x.srt"
    p.write_text(icerik, encoding="utf-8")
    assert any(beklenen in h for h in uzun_kurgu.srt_denetle(p, 30.0))


def test_srt_utf8_olmayan_reddedilir(tmp_path):
    p = tmp_path / "x.srt"
    p.write_bytes("1\n00:00:01,000 --> 00:00:02,000\nŞ\n".encode("cp1254"))
    assert "UTF-8" in uzun_kurgu.srt_denetle(p)[0]


def test_srt_zaman_bicimi():
    assert uzun_kurgu.srt_zaman(3723.4567) == "01:02:03,457" and uzun_kurgu.srt_zaman(-1) == "00:00:00,000"


# ================================================================== ekran yazıları, geçişler, müzik

def test_ekran_ass_bolum_basligi_ve_gomulu_altyazi(tmp_path):
    p = _plan_cizelge()
    ass = uzun_kurgu.ekran_ass(p, SEN, tmp_path / "e.ass").read_text(encoding="utf-8")
    assert "PlayResX: 1920" in ass and ",Bolum,,0,0,0,,{\\fad(400,500)}Açılış" in ass and "11 Ağustos 1473" in ass
    assert ",Alt," not in ass.split("[Events]")[1]
    ip = uzun_kurgu.srt_ipuclari(p, SEN)
    gom = uzun_kurgu.ekran_ass(p, SEN, tmp_path / "g.ass", ip).read_text(encoding="utf-8")
    assert gom.count(",Alt,") == len(ip)


def test_bolum_sinirlari_ve_gecis_filtresi(tmp_path):
    p = _plan_cizelge()
    b = uzun_kurgu.bolum_sinirlari(p, SEN)
    assert [(x["id"], x["bas"], x["son"]) for x in b] == [("B1", 0.0, 7.7), ("B2", 7.7, 19.0)]
    f = uzun_kurgu.gecis_filtresi(p, b, tmp_path / "e.ass", veri.kural("uzun")["kurgu"])
    assert f.count("overlay=") == len(b) - 1 and "colorchannelmixer=aa=0.7" in f and "fade=t=in:st=0" in f
    assert "fade=t=out:st=28.000" in f and f.endswith("[vout]")


def test_muzik_yatagi_belirlenimci_ve_normalize():
    b = [{"bas": 0.0, "son": 4.0}, {"bas": 4.0, "son": 8.0}]
    a, c = uzun_kurgu.muzik_yatagi(b, 8.0), uzun_kurgu.muzik_yatagi(b, 8.0)
    assert len(a) == 8 * uzun_kurgu.SR and abs(float(abs(a).max()) - 1.0) < 1e-3 and (a == c).all()


# ================================================================== kurgu: yönlendirme ve hata yolları

def test_kurgu_uzun_plani_uzun_kurguya_yonlendirir(tmp_path, monkeypatch):
    from motor.uretim import kurgu
    (tmp_path / "cekim_plani.json").write_text(json.dumps({"format": "uzun"}))
    monkeypatch.setattr(uzun_kurgu, "uret", lambda k: {"durum": "YONLENDI", "k": str(k)})
    assert kurgu.uret(tmp_path)["durum"] == "YONLENDI"


@pytest.fixture
def kurgu_ortami(tmp_path, monkeypatch):
    from motor import ayar
    from motor.uretim import plan_denetim, seslendirme
    monkeypatch.setattr(ayar, "ONBELLEK", tmp_path / "onb")
    klip = tmp_path / "klip.mp4"
    klip.write_bytes(b"x")
    wav = tmp_path / "s.wav"
    wav.write_bytes(b"x")
    plan = dict(_plan_cizelge(), konu="t", format="uzun")
    (tmp_path / "cekim_plani.json").write_text(json.dumps(plan))
    (tmp_path / "senaryo.json").write_text(json.dumps(SEN))
    monkeypatch.setattr(plan_denetim, "denetle", lambda p: {"gecti": True, "hatalar": [], "uyarilar": []})
    durum = {"render": "TAMAM", "wav": {"S1": str(wav), "S2": str(wav)}}
    monkeypatch.setattr(render, "render", lambda py, cid: {"durum": durum["render"], "video": str(klip),
                                                            "olculen": {"kare": 1, "render_sn": 0.1}})
    monkeypatch.setattr(seslendirme, "olc", lambda cs: {k: {"sure_sn": 1.0, "wav": v, "motor": "piper"}
                                                         for k, v in durum["wav"].items()})
    return tmp_path, durum


def test_eksik_sahne_hata(kurgu_ortami):
    k, _ = kurgu_ortami
    p = json.loads((k / "cekim_plani.json").read_text())
    p["cekimler"] = p["cekimler"][:1]
    (k / "cekim_plani.json").write_text(json.dumps(p))
    r = uzun_kurgu.uret(k)
    assert r["durum"] == "HATA" and r["eksik"] == ["S2"]


def test_render_basarisiz_cekim_uretimi_durdurur(kurgu_ortami):
    k, d = kurgu_ortami
    d["render"] = "REDDEDİLDİ"
    r = uzun_kurgu.uret(k)
    assert r["durum"] == "HATA" and r["cekim"] == "S1" and "render" in r["neden"]


def test_eksik_tts_hata_sessiz_uretim_yok(kurgu_ortami):
    k, d = kurgu_ortami
    d["wav"] = {"S1": d["wav"]["S1"], "S2": "/yok/S2.wav"}
    r = uzun_kurgu.uret(k)
    assert r["durum"] == "HATA" and r["neden"] == "seslendirme dosyası eksik" and r["eksik"] == ["S2"]


def test_ffmpeg_birlestirme_hatasi_basari_sayilmaz(kurgu_ortami, monkeypatch):
    k, _ = kurgu_ortami
    monkeypatch.setattr(uzun_kurgu.subprocess, "run",
                        lambda *a, **kw: types.SimpleNamespace(returncode=1, stderr="Invalid data found", stdout=""))
    r = uzun_kurgu.uret(k)
    assert r["durum"] == "HATA" and "birleştirme" in r["neden"] and "Invalid data" in r["ffmpeg"]


def test_ffmpeg_kurgu_hatasi_yarim_dosya_birakmaz(kurgu_ortami, monkeypatch):
    k, _ = kurgu_ortami
    gercek = subprocess.run

    def sahte(komut, *a, **kw):
        if "-f" in komut and "concat" in komut:
            return types.SimpleNamespace(returncode=0, stderr="", stdout="")
        if "-filter_complex" in komut:
            Path(komut[-1]).write_bytes(b"yarim")
            return types.SimpleNamespace(returncode=1, stderr="Error while filtering", stdout="")
        return gercek(komut, *a, **kw)
    monkeypatch.setattr(uzun_kurgu.subprocess, "run", sahte)
    monkeypatch.setattr(uzun_kurgu, "ses_karisimi", lambda *a: {"wav": "x.wav"})
    r = uzun_kurgu.uret(k)
    from motor import ayar
    assert r["durum"] == "HATA" and "kurgu" in r["neden"]
    assert not (ayar.ONBELLEK / "kurgu" / "t" / "t.mp4").exists()                       # yarım dosya son ad altında yok


def test_uzun_olmayan_plan_reddedilir(kurgu_ortami):
    k, _ = kurgu_ortami
    p = json.loads((k / "cekim_plani.json").read_text())
    p.pop("format")
    (k / "cekim_plani.json").write_text(json.dumps(p))
    assert uzun_kurgu.uret(k)["durum"] == "REDDEDİLDİ"


# ================================================================== kalite kapıları (gerçek ffmpeg)

def _mp4(yol: Path, w=1920, h=1080, sure=3.0, ses=True):
    komut = ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s={w}x{h}:r=30:d={sure}"]
    if ses:
        komut += ["-f", "lavfi", "-i", f"sine=f=440:d={sure}", "-c:a", "aac"]
    komut += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-shortest", str(yol)]
    subprocess.run(komut, check=True)
    return yol


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg yok")
def test_qa_gecerli_mp4_ve_srt(tmp_path):
    mp4 = _mp4(tmp_path / "a.mp4")
    srt = uzun_kurgu.srt_yaz([(0.2, 1.5, "Merhaba Şehzade")], tmp_path / "a.srt")
    plan = {"cozunurluk": [1920, 1080], "fps": 30, "ses": {"toplam_sn": 3.0}}
    r = uzun_kurgu.qa(mp4, srt, plan, None)
    assert r["gecti"] and r["oynatilabilir"] and r["sure_sn"] == pytest.approx(3.0, abs=0.1)
    r = uzun_kurgu.qa(mp4, srt, plan, [900, 1200])
    assert not r["gecti"] and any("hedef 15–20 dk" in x for x in r["kritik"])         # süre kapısı


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg yok")
def test_qa_cozunurluk_ses_srt_ve_eksik_dosya(tmp_path):
    plan = {"cozunurluk": [1920, 1080], "fps": 30, "ses": {"toplam_sn": 3.0}}
    dik = _mp4(tmp_path / "d.mp4", 1080, 1920)
    sessiz = _mp4(tmp_path / "s.mp4", ses=False)
    srt = uzun_kurgu.srt_yaz([(0.2, 1.5, "a")], tmp_path / "a.srt")
    assert any("1080x1920" in x for x in uzun_kurgu.qa(dik, srt, plan, None)["kritik"])
    assert "ses akışı yok" in uzun_kurgu.qa(sessiz, srt, plan, None)["kritik"]
    assert any("SRT dosyası yok" in x for x in uzun_kurgu.qa(dik, tmp_path / "yok.srt", plan, None)["kritik"])
    r = uzun_kurgu.qa(tmp_path / "yok.mp4", srt, plan, None)
    assert r["kritik"] == ["FFmpeg çıktı dosyası oluşmadı"] and "gecti" not in r
    bozuk = tmp_path / "b.mp4"
    bozuk.write_bytes(_mp4(tmp_path / "t.mp4").read_bytes()[:20000])
    assert not uzun_kurgu.qa(bozuk, srt, plan, None)["gecti"]                            # kesik dosya başarı değil
    kotu_plan = dict(plan, ses={"toplam_sn": 10.0})
    assert any("plan (gerçek TTS)" in x for x in uzun_kurgu.qa(_mp4(tmp_path / "x.mp4"), srt, kotu_plan, None)["kritik"])


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg yok")
def test_loudnorm_iki_gecis(tmp_path):
    import numpy as np
    import soundfile as sf
    t = np.arange(48000 * 4) / 48000
    sf.write(tmp_path / "h.wav", (0.05 * np.sin(2 * np.pi * 220 * t)).astype("float32"), 48000)
    r = uzun_kurgu.loudnorm(tmp_path / "h.wav", tmp_path / "n.wav", {"I": -16, "TP": -1.5, "LRA": 11})
    assert (tmp_path / "n.wav").exists() and r["hedef_I"] == -16 and r["olculen_I"] < -20


def test_qa_dinleme_ortalamasi_kapisi(tmp_path, monkeypatch):
    monkeypatch.setattr(uzun_kurgu, "_ffprobe", lambda y: {"format": {"format_name": "mov,mp4", "duration": "3.0"},
                                                          "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1920,
                                                                       "height": 1080, "pix_fmt": "yuv420p", "duration": "3.0"},
                                                                      {"codec_type": "audio", "codec_name": "aac", "duration": "3.0"}]})
    monkeypatch.setattr(uzun_kurgu.subprocess, "run", lambda *a, **k: types.SimpleNamespace(returncode=0, stderr="", stdout=""))
    mp4 = tmp_path / "a.mp4"
    mp4.write_bytes(b"x")
    srt = uzun_kurgu.srt_yaz([(0.2, 1.5, "a")], tmp_path / "a.srt")
    plan = {"cozunurluk": [1920, 1080], "fps": 30, "ses": {"toplam_sn": 3.0}}
    r = uzun_kurgu.qa(mp4, srt, plan, None, dinleme={"S1": {"benzerlik": 0.3}, "S2": {"benzerlik": 0.5}})
    assert not r["gecti"] and any("dinleme ortalaması" in x for x in r["kritik"])
    assert uzun_kurgu.qa(mp4, srt, plan, None, dinleme={"S1": {"benzerlik": 0.95}})["gecti"]


# ================================================================== otonom: uzun ve her_ikisi

class Sahte:
    def __init__(self, yanitlar):
        self.yanitlar, self.istemler, self.cagri_sayisi, self.kullanilan_model = list(yanitlar), [], 0, "sahte"

    def tamamla(self, istem, adim, baglam):
        self.istemler.append((adim, istem))
        self.cagri_sayisi += 1
        y = self.yanitlar.pop(0) if self.yanitlar else None
        if callable(y) and not isinstance(y, type):
            self.yanitlar.insert(0, y)          # üreteç: her çağrıda yeni yanıt
            y = y(self.cagri_sayisi)
        if isinstance(y, BaseException):
            raise y
        return y if isinstance(y, str) else json.dumps(y, ensure_ascii=False)


def _kayit(i):
    return {"id": f"ark_{i}", "durum": "dogrulanmis", "iddia": f"iddia {i}", "bagimsiz_kaynak_sayisi": 2,
            "kaynaklar": [{"id": f"wp_{i}", "eser": "w", "url": "u", "tur": "ansiklopedi"},
                          {"id": f"tdv_{i}", "eser": "t", "url": "u", "tur": "ansiklopedi"}]}


TASLAK = {"baslik": "Otlukbeli", "bolumler": [
    {"baslik": "Açılış", "roller": ["kanca", "baglam"], "hedef_sn": 150, "kartlar": ["C1"]},
    {"baslik": "Taraflar", "roller": ["taraflar"], "hedef_sn": 150}, {"baslik": "Öncesi", "roller": ["savas_oncesi"], "hedef_sn": 150},
    {"baslik": "Savaş", "roller": ["savas"], "hedef_sn": 150}, {"baslik": "Sonuç", "roller": ["sonuc"], "hedef_sn": 150},
    {"baslik": "Etkiler", "roller": ["etkiler"], "hedef_sn": 150}, {"baslik": "Kapanış", "roller": ["kapanis"], "hedef_sn": 150}]}


def _bolum_yaniti(b: int, adet=20, gorsel=None, uc=None):
    cs = []
    for j in range(adet):
        no = b * 100 + j
        n = {"tur": "harita", "evre": "E1", "metin": f"başlık {no}"}
        if gorsel and j in (1, 7, 13):
            n = {"tur": "gorsel25d", "gorsel_id": gorsel, "aciklama": f"görsel açıklama {no}", "hareket": "pan_sol"}
        if uc and j == 4:
            n = {"tur": "3d", "katalog": uc}
        cs.append({"metin": _metin(no), "kartlar": ["C1"], "olgusal": True, "niyet": n})
    return {"cumleler": cs}


def _sahte_planla(is_):
    sen = json.loads((is_ / "senaryo.json").read_text())
    cekimler = [{"id": c["id"], "tur": c["niyet"]["tur"], "sure_sn": 7.0, "cumleler": [c["id"]]} for c in sen["cumleler"]]
    (is_ / "cekim_plani.json").write_text(json.dumps({"konu": sen["konu"], "format": sen["format"], "cekimler": cekimler}))
    return {"gecti": True, "hatalar": {}, "toplam_sure_sn": 1000.0}


@pytest.fixture
def gorsel_kapisi(tmp_path, monkeypatch):
    from motor.varlik import tarihi_gorsel
    monkeypatch.setattr(tarihi_gorsel, "dogrulanmis_dosya", lambda gid: (tmp_path / gid, {}))
    monkeypatch.setattr(ou, "GORSEL_KOK", tmp_path / "gorsel")


def test_uzun_otonom_bolum_bolum_gercek_kapilarla(tmp_path, gorsel_kapisi):
    gid = "otlukbeli-1473-oto-portre"
    yan = [[{"gorsel_id": "portre", "sorgu": "q", "aciklama": "portre"}], TASLAK]
    yan += [_bolum_yaniti(b, gorsel=gid if b in (1, 3) else None, uc="3D-S6" if b == 4 else None) for b in range(7)]
    s = Sahte(yan)
    havuz_cagri = []
    r = ou.planla("Otlukbeli Savaşı", "uzun", tmp_path / "is", "AIza", 4,
                  havuz_fn=lambda k: havuz_cagri.append(k) or {"kayitlar": [_kayit(i) for i in range(1, 9)]},
                  saglayici_fn=lambda: s, topla=lambda q, h: {"lisans_turu": "PD-Old", "eser_adi": "p"},
                  planla_fn=_sahte_planla, olc=_olc)
    i = r["isler"][0]
    sen = json.loads((Path(i["is"]) / "senaryo.json").read_text())
    konu = json.loads((Path(i["is"]) / "konu.json").read_text())
    assert i["bicim"] == "uzun" and i["kimlik"] == "otlukbeli-1473-oto-uzun" and konu["hedef_sure_sn"] == [900, 1200]
    assert len(sen["bolumler"]) == 7 and len(sen["cumleler"]) == 140 and sen["kanca"] == "S1" and sen["final"] == "S140"
    assert anlati.uzun_denetle(sen, _olc(sen["cumleler"]))[0] == [] and sozlesme.senaryo_denetle(sen, json.loads(
        (Path(i["is"]) / "arastirma.json").read_text())) == []
    toplam = sahne_bolucu.toplam_sure(sahne_bolucu.zaman_cizelgesi(sen, _olc(sen["cumleler"])))
    assert 900 <= toplam <= 1200
    g = [c["niyet"] for c in sen["cumleler"] if c["niyet"]["tur"] == "gorsel25d"]
    assert g and all(n["gorsel25d"]["hareket"] == "pan_sol" and n["aciklama"] for n in g)
    uc = [c["niyet"] for c in sen["cumleler"] if c["niyet"]["tur"] == "3d"]
    pilot = json.loads((PILOT / "senaryo.json").read_text())["cumleler"][5]["niyet"]
    assert uc == [pilot]                                                               # 3D yalnız denetlenmiş katalogdan
    assert [a for a, _ in s.istemler] == ["gorsel_sorgu", "uzun_taslak"] + [f"uzun_B{b}" for b in range(1, 8)]
    assert len(havuz_cagri) == 1 and r["gemini_cagri"] == 9
    assert "k0x1" in s.istemler[3][1]                                                  # önceki bölüm tekrar karşıtı istemde
    assert all(p["kimlik"] == i["kimlik"] and "maliyet" in p for p in r["parcalar"]) and len(r["parcalar"]) == 8
    assert sum(len(p["cekimler"]) for p in r["parcalar"]) == 140                       # uzun: bütün türler paralel


def test_uzun_bolum_sure_geri_bildirimi_ve_yerel_kapilar(tmp_path, gorsel_kapisi):
    kisa = _bolum_yaniti(0, adet=6)
    kotu = {"cumleler": [{"metin": _metin(5), "kartlar": ["C99"], "niyet": {"tur": "bilgi_karti"}}]}
    yan = [[], TASLAK, kotu, kisa, _bolum_yaniti(0)] + [_bolum_yaniti(b) for b in range(1, 7)]
    s = Sahte(yan)
    r = ou.planla("Otlukbeli Savaşı", "uzun", tmp_path / "is", "AIza", havuz_fn=lambda k: {"kayitlar": [_kayit(1)]},
                  saglayici_fn=lambda: s, topla=lambda q, h: {}, planla_fn=_sahte_planla, olc=_olc)
    istem = {a: [] for a, _ in s.istemler}
    for a, x in s.istemler:
        istem[a].append(x)
    assert len(istem["uzun_B1"]) == 3
    assert "tanımsız kart C99" in istem["uzun_B1"][1] and "bilgi_karti" in istem["uzun_B1"][1]
    assert "kelime daha yaz" in istem["uzun_B1"][2]                                     # gerçek TTS süresi geri bildirimi
    assert r["isler"][0]["senaryo"]["cumle"] == 140


def test_uzun_sure_tutmazsa_onarim_sonra_acik_hata(tmp_path, gorsel_kapisi):
    s = Sahte([[], TASLAK, lambda n: _bolum_yaniti(100 + n, adet=6)])   # her bölüm hep kısa (yeni cümlelerle)
    with pytest.raises(ou.UretimHatasi) as e:
        ou.planla("Otlukbeli Savaşı", "uzun", tmp_path / "is", "AIza", havuz_fn=lambda k: {"kayitlar": [_kayit(1)]},
                  saglayici_fn=lambda: s, topla=lambda q, h: {}, planla_fn=_sahte_planla, olc=_olc)
    assert e.value.asama == "senaryo" and "hedef 900–1200 sn" in str(e.value)
    assert s.cagri_sayisi <= ou.EN_COK_GEMINI_CAGRI + 1                               # sınırlı deneme, sonsuz döngü yok


def test_uzun_kota_aninda_durur(tmp_path, gorsel_kapisi):
    class Kota(Exception):
        sinif = "kota"
    s = Sahte([[], Kota("429")])
    with pytest.raises(ou.UretimHatasi) as e:
        ou.planla("Otlukbeli Savaşı", "uzun", tmp_path / "is", "AIza", havuz_fn=lambda k: {"kayitlar": [_kayit(1)]},
                  saglayici_fn=lambda: s, topla=lambda q, h: {}, planla_fn=_sahte_planla, olc=_olc)
    assert e.value.kod == 4 and s.cagri_sayisi == 2


def test_her_ikisi_ortak_arastirma_ve_gorseller(tmp_path, gorsel_kapisi, monkeypatch):
    monkeypatch.setattr(ou, "senaryo_denetle", lambda *a, **k: [])                     # Shorts kapıları 62b testlerinde
    shorts = {"cumleler": [{"id": "S1", "metin": "a", "kartlar": ["C1"], "niyet": {"tur": "3d"}}], "kanca": "S1", "final": "S1"}
    yan = [[{"gorsel_id": "portre", "sorgu": "q", "aciklama": "portre"}], shorts, TASLAK] + [_bolum_yaniti(b) for b in range(7)]
    s = Sahte(yan)
    havuz_cagri = []
    r = ou.planla("Otlukbeli Savaşı", "her_ikisi", tmp_path / "is", "AIza", 3,
                  havuz_fn=lambda k: havuz_cagri.append(k) or {"kayitlar": [_kayit(i) for i in range(1, 40)]},
                  saglayici_fn=lambda: s, topla=lambda q, h: {"lisans_turu": "CC0-1.0", "eser_adi": "p"},
                  planla_fn=_sahte_planla, olc=_olc)
    assert [i["bicim"] for i in r["isler"]] == ["shorts", "uzun"] and len(havuz_cagri) == 1
    assert [a for a, _ in s.istemler].count("gorsel_sorgu") == 1 and len(r["gorseller"]) == 1
    sk = json.loads((Path(r["isler"][0]["is"]) / "arastirma.json").read_text())
    uk = json.loads((Path(r["isler"][1]["is"]) / "arastirma.json").read_text())
    assert len(sk["kartlar"]) == 30 and len(uk["kartlar"]) == 39 and uk["kartlar"][:30] == sk["kartlar"]
    assert {p["kimlik"] for p in r["parcalar"]} == {"otlukbeli-1473-oto", "otlukbeli-1473-oto-uzun"}


def test_cli_matris_ciktisi(tmp_path, monkeypatch):
    gh = tmp_path / "gh"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh))
    monkeypatch.setattr(ou, "planla", lambda *a, **k: {"kimlik": "a", "isler": [{"kimlik": "a"}, {"kimlik": "a-uzun"}],
                                                       "parcalar": [{"kimlik": "a", "parca": 0}, {"kimlik": "a-uzun", "parca": 0},
                                                                    {"kimlik": "a-uzun", "parca": 1}]})
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    assert ou.main(["planla", "--konu", "Otlukbeli Savaşı", "--mod", "her_ikisi", "--cikti", str(tmp_path / "c")]) == 0
    satir = dict(x.split("=", 1) for x in gh.read_text().splitlines())
    assert json.loads(satir["kimlikler"]) == ["a", "a-uzun"] and len(json.loads(satir["matris"])) == 3


def test_dogrulama_fiksturu_uzun_motor_ve_atlanan_kapi_acik(tmp_path, gorsel_kapisi):
    def planla_fn(is_):
        r = _sahte_planla(is_)
        return dict(r, hatalar={"anlati": ["3 bölüm; uzun belgesel için 6–8 ana bölüm gerekli"]}) if "-uzun" in str(is_) else r
    r = ou.dogrulama_plani(KOK / "deneyler/faz62b/dogrulama.json", tmp_path / "is", 3,
                           topla=lambda s, h: {"lisans_turu": "PD-Old"}, planla_fn=planla_fn)
    u = r["isler"][1]
    assert r["dogrulama_fiksturu"] is True and u["bicim"] == "uzun" and u["kimlik"].endswith("-dogrulama-uzun")
    assert u["plan"]["gecti"] and "motor doğrulaması" in u["anlati_kapisi_atlandi"] and u["atlanan_hatalar"]["anlati"]
    sen = json.loads((Path(u["is"]) / "senaryo.json").read_text())
    assert sen["format"] == "uzun" and len(sen["bolumler"]) == 3 and all(c.get("bolum") for c in sen["cumleler"])
    konu = json.loads((Path(u["is"]) / "konu.json").read_text())
    assert konu["format"] == "uzun" and konu["hedef_sure_sn"] == [20, 120]
    n = {c["id"]: c["niyet"] for c in sen["cumleler"]}
    assert n["S8"]["aciklama"] != n["S2"]["aciklama"] and n["S8"]["gorsel25d"]["hareket"] == "pull_back"


def test_dogrulama_shorts_disi_hata_atlanmaz(tmp_path, gorsel_kapisi):
    def planla_fn(is_):
        r = _sahte_planla(is_)
        return dict(r, hatalar={"plan_denetimi": ["S3: tekrar"]}) if "-uzun" in str(is_) else r
    with pytest.raises(ou.UretimHatasi) as e:
        ou.dogrulama_plani(KOK / "deneyler/faz62b/dogrulama.json", tmp_path / "is", 3,
                           topla=lambda s, h: {"lisans_turu": "PD-Old"}, planla_fn=planla_fn)
    assert "plan_denetimi" in str(e.value)


# ================================================================== iş akışı

def _wf():
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(WF.read_text())


def test_is_akisi_uzun_ve_her_ikisi_gercek_uretim():
    wf = _wf()
    yazi = WF.read_text()
    assert "UZUN_ENGELI" not in yazi and "exit 3" not in yazi
    adim = next(a for a in wf["jobs"]["plan"]["steps"] if a.get("id") == "plan")
    assert adim["env"]["MOD"] == "${{ inputs.mod || 'shorts' }}" and '--mod "$MOD"' in adim["run"]
    g = wf.get("on", wf.get(True))["workflow_dispatch"]["inputs"]
    assert g["altyazi_gom"]["type"] == "boolean" and g["altyazi_gom"]["default"] is False
    assert wf["jobs"]["kurgu"]["env"]["ALTYAZI_GOM"] == "${{ inputs.altyazi_gom && '1' || '0' }}"


def test_is_akisi_artifact_mp4_ve_srt():
    j = _wf()["jobs"]
    yuk = [a for a in j["kurgu"]["steps"] if str(a.get("uses", "")).startswith("actions/upload-artifact")][-1]
    assert yuk["with"]["name"] == "video-${{ matrix.kimlik }}"
    assert "*.mp4" in yuk["with"]["path"] and "*.srt" in yuk["with"]["path"]
    assert j["render"]["timeout-minutes"] >= 120 and j["kurgu"]["timeout-minutes"] >= 120 and j["plan"]["timeout-minutes"] >= 90
    indir = [a for a in j["render"]["steps"] if str(a.get("uses", "")).startswith("actions/download-artifact")]
    assert any(a["with"].get("name") == "gorseller" for a in indir)                      # 2.5D render işlerde de
    assert j["kurgu"]["strategy"]["fail-fast"] is False


def test_is_akisi_yukleme_yok():
    yazi = "\n".join(x for x in WF.read_text().splitlines() if not x.lstrip().startswith("#")).lower()
    for yasak in ("youtube", "upload_video", "tiktok", "git push", "client_secret"):
        assert yasak not in yazi


# ================================================================== mutasyon turunda eklenen kapı testleri

def test_cesitlilik_olceklemesi_yalniz_uzun():
    from motor.uretim import cesitlilik
    meta = {"hareket": "dolly", "yukseklik": "goz", "aci_kovasi": "on", "dizilis": "a", "odak": "x", "arazi": "ova", "tur": "t"}
    cekimler = [{"id": f"S{i}", "tur": "3d", "kamera": {"plan": "orta"}, "meta": dict(meta, hareket=f"h{i}", odak=f"o{i}")}
                for i in range(2)]
    den = {"cekimler": {}}
    hs, _ = cesitlilik.denetle({"cekimler": cekimler}, den)
    hu, _ = cesitlilik.denetle({"cekimler": cekimler, "format": "uzun"}, den)
    assert any("farklı hareket sayısı 2; en az 4" in x for x in hs)                     # Shorts eşiği aynen
    assert hu == []                                                                    # uzun: 2 çekimde ölçeklenir
    hb, _ = cesitlilik.denetle({"cekimler": [], "format": "uzun"}, den)
    assert hb == []                                                                    # 3D'siz uzun belgesel


def test_gemini_cagri_tavani(tmp_path, gorsel_kapisi, monkeypatch):
    monkeypatch.setattr(ou, "EN_COK_GEMINI_CAGRI", 3)
    s = Sahte([[], TASLAK, lambda n: _bolum_yaniti(200 + n, adet=6)])
    with pytest.raises(ou.UretimHatasi) as e:
        ou.planla("Otlukbeli Savaşı", "uzun", tmp_path / "is", "AIza", havuz_fn=lambda k: {"kayitlar": [_kayit(1)]},
                  saglayici_fn=lambda: s, topla=lambda q, h: {}, planla_fn=_sahte_planla, olc=_olc)
    assert "çağrı tavanı (3)" in str(e.value) and s.cagri_sayisi == 4                 # 1 görsel sorgusu + 3 senaryo


def test_gorsel_en_cok_kullanim_ve_art_arda_yasak():
    konu = ou.konu_kur(PILOT, "Otlukbeli Savaşı", "uzun")
    g = [{"gorsel_id": "g1", "aciklama": "x"}]
    ara = {"kartlar": [{"id": "C1", "guven": "kesin", "iddia": "x"}]}
    def y(idx):
        return {"cumleler": [{"metin": _metin(300 + j), "kartlar": ["C1"], "niyet":
                              ({"tur": "gorsel25d", "gorsel_id": "g1", "aciklama": f"a{j}"} if j in idx else
                               {"tur": "harita", "evre": "E1", "metin": f"m{j}"})} for j in range(16)]}
    _, h = ou.bolum_cumleleri(y(range(0, 14, 2)), ara, konu, g, [], {}, "B1", 1, [])
    assert any("6 kereden fazla" in x for x in h)
    _, h = ou.bolum_cumleleri(y([3, 4]), ara, konu, g, [], {}, "B1", 1, [])
    assert any("art arda" in x for x in h)
    _, h = ou.bolum_cumleleri(y([1, 3, 5]), ara, konu, g, [], {}, "B1", 1, [])
    assert h == []


def test_dogrulama_shorts_anlati_kapisi_atlanmaz(tmp_path, gorsel_kapisi):
    def planla_fn(is_):
        r = _sahte_planla(is_)
        return dict(r, hatalar={"anlati": ["kanca 3 sn"]}) if "-uzun" not in str(is_) else r
    with pytest.raises(ou.UretimHatasi) as e:
        ou.dogrulama_plani(KOK / "deneyler/faz62b/dogrulama.json", tmp_path / "is", 3,
                           topla=lambda s, h: {"lisans_turu": "PD-Old"}, planla_fn=planla_fn)
    assert "(shorts)" in str(e.value) and "kanca 3 sn" in str(e.value)


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg yok")
def test_uzun_kurgu_uctan_uca_gercek_ffmpeg(kurgu_ortami, monkeypatch):
    """Render ve Whisper dışında gerçek: birleştirme, müzik + ortam + davul karışımı, loudnorm, ASS + bölüm geçişi,
    16:9 H.264/AAC çıktı, SRT ve bütün kalite kapıları. Çıktı dosyası oynatılabilir ve boş değil."""
    import numpy as np
    import soundfile as sf
    from motor.uretim import kurgu
    k, d = kurgu_ortami
    klip1, klip2 = _mp4(k / "k1.mp4", sure=7.7, ses=False), _mp4(k / "k2.mp4", sure=11.3, ses=False)
    for i, n in ((1, 6.0), (2, 9.5)):
        t = np.arange(int(22050 * n)) / 22050
        sf.write(k / f"S{i}.wav", (0.3 * np.sin(2 * np.pi * 180 * t) * (np.sin(2 * np.pi * 3 * t) > 0)).astype("float32"), 22050)
    d["wav"] = {"S1": str(k / "S1.wav"), "S2": str(k / "S2.wav")}
    klipler = {"S1": klip1, "S2": klip2}
    monkeypatch.setattr(render, "render", lambda py, cid: {"durum": "TAMAM", "video": str(klipler[cid]),
                                                            "olculen": {"kare": 1, "render_sn": 0.1}})
    monkeypatch.setattr(kurgu, "_dinle", lambda sr, sen: {c["id"]: {"benzerlik": 0.9} for c in sen["cumleler"]})
    p = json.loads((k / "cekim_plani.json").read_text())
    p["ses"]["toplam_sn"] = 19.0
    (k / "cekim_plani.json").write_text(json.dumps(p))
    (k / "senaryo.json").write_text(json.dumps(dict(SEN, cumleler=[dict(c, bolum=b) for c, b in
                                                               zip(SEN["cumleler"], ("B1", "B2"))])))
    (k / "konu.json").write_text(json.dumps({"hedef_sure_sn": [10, 30]}))
    r = uzun_kurgu.uret(k)
    assert r["durum"] == "TAMAM", r.get("kalite_kontrol") or r
    mp4, srt = Path(r["video"]), Path(r["srt"])
    assert mp4.stat().st_size > 10_000 and srt.exists() and not (mp4.parent / "goruntu.mp4").exists()
    kk = r["kalite_kontrol"]
    assert kk["gecti"] and kk["oynatilabilir"] and kk["teknik"]["cozunurluk"] == "1920x1080" and kk["srt_hatalari"] == []
    assert r["ses"]["bolum_sayisi"] == 2 and abs(r["ses"]["loudnorm"]["hedef_I"] + 16) < 1e-9
    assert [b["id"] for b in r["bolumler"]] == ["B1", "B2"]
    assert json.loads((mp4.parent / "uretim_raporu.json").read_text())["durum"] == "TAMAM"
