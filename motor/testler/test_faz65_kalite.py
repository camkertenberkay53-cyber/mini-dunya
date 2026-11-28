"""Faz-65 — Shorts görsel, altyazı, kalabalık sahne ve seslendirme kalitesi (offline).

1. Altyazı: dikey (Shorts) çıktıda 'Ana' altyazı alt güvenli bantta (H·0.22; alt %20–24); üst kanca başlığı görünürken
   kanca cümlesi altyazı olarak tekrar basılmaz. Yatay (uzun) biçim değişmez.
2. 2.5D: titreşim/açı salınımı, yörünge ve nefes kapalı; zoom 1.0–1.08 (yön korunur), kaydırma görüntü içinde, eğri
   ease in-out. kaos sahne_render'a eklenen 'titresimsiz' anahtarı isteğe bağlıdır: verilmezse eski davranış aynen.
   Commons: sorgu istemiyorsa gemi/belge/harita sayfaları elenir.
3. Kalabalık: toplu askerî ölçek + geniş kadrajda tek asker yerine en az 4, hedef 6 kişilik birlik (aynı rol/eylem).
4. Seslendirme: MOTOR_TTS=edge → Edge (tr-TR-AhmetNeural); ağ/paket hatasında senaryonun TAMAMI Piper'a düşer
   (yapışkan, kayıtlı neden). Kurgu planın motorunu yedeksiz ister ve süre uyuşmazlığında video kurmaz."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
import yaml

from motor.uretim import gorsel25d, planlayici, seslendirme, veri

KOK = Path(__file__).resolve().parents[2]


def _onbellek_var() -> bool:
    try:
        return bool(veri.kitler()) and bool(veri.takimlar())
    except Exception:   # noqa: BLE001
        return False


ONBELLEK = pytest.mark.skipif(not _onbellek_var(), reason="varlık önbelleği yok (gerçek planlayıcı testi)")


# ================================================================== 1) altyazı

def _altyazi_plan(W=1080, H=1920, kanca_ses=1.6, ilk_cekim=2.2):
    plan = {"cozunurluk": [W, H], "cekimler": [{"sure_sn": ilk_cekim}, {"sure_sn": 4.0}],
            "ses": {"cizelge": [{"cumle": "S1", "ses_bas_sn": 0.3, "ses_sure_sn": kanca_ses},
                                {"cumle": "S2", "ses_bas_sn": 2.4, "ses_sure_sn": 3.5}]}}
    sen = {"kanca": "S1", "cumleler": [{"id": "S1", "metin": "Tek bir gün her şeyi değiştirdi mi?"},
                                       {"id": "S2", "metin": "Osmanlı ordusu doğuya yürüdü ve Tercan yakınlarında durdu."}]}
    return plan, sen


def _ass(tmp_path, plan, sen):
    from motor.uretim import kurgu
    ass = kurgu._altyazi(plan, sen, tmp_path)
    satir = ass.read_text(encoding="utf-8").splitlines()
    stil = {x.split(",")[0][7:]: x.split(",") for x in satir if x.startswith("Style: ")}
    diyalog = [x.split(",", 9) for x in satir if x.startswith("Dialogue: ")]
    return stil, diyalog, json.loads((tmp_path / "altyazi.json").read_text())


def test_dikey_altyazi_alt_guvenli_bantta(tmp_path):
    from motor.uretim import kurgu
    stil, _, _ = _ass(tmp_path, *_altyazi_plan())
    pay = veri.kural("kurgu")["altyazi_dikey_alt_pay"]
    assert pay == kurgu.ALTYAZI_DIKEY_ALT_PAY == 0.22 and 0.20 <= pay <= 0.24
    assert stil["Ana"][18] == "2" and stil["Ana"][21] == str(round(1920 * 0.22))        # alta hizalı, MarginV
    assert stil["Kanca"][18] == "8" and stil["Kanca"][21] == str(int(1920 * 0.13))      # üst başlık yerinde kaldı
    assert len(stil["Ana"]) == len(stil["Kanca"]) == 23                                 # V4+ biçimi bozulmadı


def test_yatay_altyazi_degismez(tmp_path):
    stil, _, _ = _ass(tmp_path, *_altyazi_plan(W=1920, H=1080))
    assert stil["Ana"][21] == str(int(1080 * 0.33))


def test_kanca_ust_basliktayken_altyazida_tekrar_basilmaz(tmp_path):
    plan, sen = _altyazi_plan()
    _, diyalog, js = _ass(tmp_path, plan, sen)
    kanca = sen["cumleler"][0]["metin"]
    ana = [d[9] for d in diyalog if d[3] == "Ana"]
    ust = [d[9] for d in diyalog if d[3] == "Kanca"]
    assert sum(kanca in t for t in ust) == 1                                            # üstte bir kez
    assert not any(w in " ".join(ana) for w in ("Tek bir gün", "değiştirdi"))           # altta yok
    assert ana and all(t.split("}")[-1] in " ".join(x["metin"] for x in js) for t in ana)
    assert any("Osmanlı" in t for t in ana)                                             # diğer cümleler duruyor


def test_kanca_sesi_baslik_suresini_asarsa_kalan_parca_altyazida_kalir(tmp_path):
    from kaos.sinema import motor as sinema
    plan, sen = _altyazi_plan(kanca_ses=3.4, ilk_cekim=1.6)                              # başlık 1.5 sn'de kalkar
    _, diyalog, js = _ass(tmp_path, plan, sen)
    parca = sinema.altyazi_parcala(sen["cumleler"][0]["metin"], 0.3, 3.4)
    beklenen = [p for p in parca if p[0] >= 1.5]
    assert beklenen and [x["metin"] for x in js[:len(beklenen)]] == [p[2] for p in beklenen]


# ================================================================== 2a) 2.5D yumuşak kamera

@pytest.mark.parametrize("ad", ["zoom_in", "zoom_out", "push_in", "pull_back", "pan_sol", "pan_sag", "pan_yukari",
                                "pan_asagi", "capraz", "takip", "sabit"])
def test_yumusak_kamera_zoom_1_ile_1_08_arasi_yon_korunur(ad):
    from kaos.sinema import kamera
    b, s, _ = kamera.HAREKETLER[ad]
    k = gorsel25d.yumusak_kamera(ad)
    zb, zs = k["bas"][2], k["son"][2]
    assert k["ease"] == "inout" and 1.0 <= zb <= 1.08 and 1.0 <= zs <= 1.08
    assert max(zb, zs) == pytest.approx(min(1.08, max(b[2], s[2])), abs=1e-4)
    assert np.sign(round(zs - zb, 4)) == np.sign(round(s[2] - b[2], 4))
    for v in (k["bas"], k["son"]):                                                       # kenar dışına taşmaz
        m = gorsel25d._kayma_siniri(v[2]) * 0.9 + 1e-4
        assert abs(v[0] - 0.5) <= m and abs(v[1] - 0.5) <= m


def test_yumusak_kamera_guc_gomulur_tavan_asilmaz():
    assert gorsel25d.yumusak_kamera("zoom_in", guc=2.5)["son"][2] == 1.08
    assert gorsel25d.yumusak_kamera("zoom_in", guc=0.5)["son"][2] == pytest.approx(1.08)
    k = gorsel25d.yumusak_kamera("pan_sol", guc=0.3)                       # güç tavanın altında: aynen uygulanır
    assert k["son"][2] == pytest.approx(1 + 0.22 * 0.3, abs=1e-4) and k["bas"][0] < 0.5 + 0.12 * 0.3 + 1e-4
    assert gorsel25d.yumusak_kamera({"bas": [0.5, 0.5, 1.0], "son": [0.5, 0.5, 1.04]})["son"][2] == 1.04


def test_yumusat_titresim_ve_salinimi_kapatir_ozgunu_degistirmez():
    g = {"gorsel_id": "x", "hareket": "push_in", "guc": 1.4, "sarsinti": 0.3, "yorunge": 0.6, "odak": [0.4, 0.4]}
    y = gorsel25d.yumusat(g)
    assert (y["sarsinti"], y["yorunge"], y["guc"]) == (0.0, 0.0, 1.0) and y["odak"] == [0.4, 0.4]
    assert isinstance(y["hareket"], dict) and y["hareket"]["son"][2] <= 1.08
    assert g["hareket"] == "push_in" and g["sarsinti"] == 0.3
    assert gorsel25d.yumusak_ayar() == {"acik": True, "zoom_tavani": 1.08, "pay": 0.9}


def _sahne_kayit(tmp_path, monkeypatch, titresimsiz: bool):
    import cv2
    from kaos.sinema import motor
    yol = tmp_path / "g.png"
    cv2.imwrite(str(yol), (np.random.default_rng(1).random((400, 300, 3)) * 255).astype(np.uint8))
    kayit, orj = [], motor._matris

    def kaydet(img, W, H, cx, cy, z, aci, dx=0.0, dy=0.0):
        kayit.append((cx, cy, z, aci, dx, dy))
        return orj(img, W, H, cx, cy, z, aci, dx, dy)

    monkeypatch.setattr(motor, "_matris", kaydet)
    s = {"id": "x", "gorsel": str(yol), "sure_render": 0.6, "kamera": gorsel25d.yumusak_kamera("zoom_in"), "vinyet": 0.0}
    if titresimsiz:
        s.update(titresimsiz=True, sarsinti=0.0, yorunge=0.0, nefes_aktif=False)
    motor.sahne_render(s, str(tmp_path / "o.mp4"), 90, 160, 10, log=lambda *_: None)
    return np.array(kayit)


def test_sahne_render_titresimsiz_aci_ve_kayma_sifir_zoom_monoton(tmp_path, monkeypatch):
    a = _sahne_kayit(tmp_path, monkeypatch, True)
    assert len(a) == 6 and np.abs(a[:, 3:]).max() == 0.0                                 # açı, dx, dy
    assert (np.diff(a[:, 2]) >= -1e-9).all() and 1.0 <= a[:, 2].min() and a[:, 2].max() <= 1.08


def test_sahne_render_anahtarsiz_eski_davranis_korunur(tmp_path, monkeypatch):
    """kaos (eski bot) varsayılanı değişmedi: anahtar verilmezse titreşim sürer; anahtar önbellek anahtarına girer."""
    from kaos.sinema import motor
    a = _sahne_kayit(tmp_path, monkeypatch, False)
    assert np.abs(a[:, 3]).max() > 0 and np.abs(a[:, 4:]).max() > 0
    s = {"id": "x", "gorsel": "/yok.png", "kamera": "zoom_in", "sure_render": 1.0}
    assert motor.sahne_anahtari(s, 9, 16, 30) != motor.sahne_anahtari(dict(s, titresimsiz=True), 9, 16, 30)


def test_render_2_5d_titresimsiz_yumusak_girdi_verir(tmp_path, monkeypatch):
    import subprocess
    from kaos.sinema import motor as sinema
    from motor.uretim import render
    from motor.varlik import tarihi_gorsel
    import cv2
    yol = tmp_path / "g.png"
    cv2.imwrite(str(yol), np.full((300, 200, 3), 120, np.uint8))
    monkeypatch.setattr(tarihi_gorsel, "dogrulanmis_dosya", lambda gid: (yol, {"sha256": "a", "lisans_turu": "CC0-1.0"}))
    monkeypatch.setattr(gorsel25d, "kalite_acik", lambda: False)
    monkeypatch.setattr(render, "KOK", tmp_path / "uretim")
    gelen = {}

    def sahte(s, out, W, H, fps, log=None):
        gelen.update(s)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"color=c=gray:s={W}x{H}:r={fps}",
                        "-frames:v", str(round(s["sure_render"] * fps)), "-pix_fmt", "yuv420p", out], check=True)

    monkeypatch.setattr(sinema, "sahne_render", sahte)
    plan = {"konu": "t", "fps": 10, "cozunurluk": [90, 160]}
    c = {"id": "S2", "sure_sn": 1.0, "tur": "gorsel25d",
         "gorsel25d": {"gorsel_id": "g", "hareket": "push_in", "sarsinti": 0.4, "yorunge": 0.6, "guc": 1.3}}
    r = render._gorsel25d_render(plan, c, onbellek=False)
    assert r["durum"] == "TAMAM", (r.get("neden"), r.get("olculen"))
    assert gelen["titresimsiz"] is True and gelen["nefes_aktif"] is False
    assert (gelen["sarsinti"], gelen["yorunge"], gelen["guc"]) == (0.0, 0.0, 1.0)
    assert max(gelen["kamera"]["bas"][2], gelen["kamera"]["son"][2]) <= 1.08
    assert c["gorsel25d"]["hareket"] == "push_in"                                         # plan girdisi değişmedi


# ================================================================== 2b) Commons ilgisiz sayfa elemesi

def _a(baslik, gen=3000, ad=""):
    return {"baslik": baslik, "mime": "image/jpeg", "gen": gen, "yuk": 2000, "url": "u", "aciklama_url": "d",
            "meta": {"LicenseShortName": "Public domain", "License": "pd", "ObjectName": ad}}


@pytest.mark.parametrize("baslik,sorgu,tur", [
    ("File:Ottoman ship at the Bosphorus.jpg", "Battle of Otlukbeli Ottoman army", "gemi"),
    ("File:Ferman of Mehmed II.jpg", "Mehmed II", "belge"),
    ("File:Letter_from_Uzun_Hasan.jpg", "Uzun Hasan", "belge"),
    ("File:Map of Anatolia 1473.png", "Akkoyunlu cavalry", "harita"),
    ("File:Osmanlı donanması.jpg", "Osmanlı ordusu", "gemi"),
])
def test_ilgisiz_sayfa_elenir(baslik, sorgu, tur):
    from motor.varlik import commons_toplayici as ct
    n = ct.ilgisizlik(_a(baslik), sorgu)
    assert n and n.startswith(f"bağlamla ilgisiz {tur} sayfası")


@pytest.mark.parametrize("baslik,sorgu", [
    ("File:Ottoman galley ship.jpg", "Ottoman galley ship"),          # sorgu gemi istiyor
    ("File:Battle map of Otlukbeli.png", "Otlukbeli battle map"),     # sorgu harita istiyor
    ("File:Mehmed II portrait.jpg", "Mehmed II"),
    ("File:Shipka pass.jpg", "Balkan mountains pass"),                # kelime sınırı: 'Shipka' ≠ 'ship'
    ("File:Mapping the Akkoyunlu court.jpg", "Akkoyunlu court"),      # 'mapping' ≠ 'map'
    ("File:Hünername folio 25.jpg", "Hunername miniature"),           # minyatür sayfası belge sayılmaz
])
def test_ilgili_aday_elenmez(baslik, sorgu):
    from motor.varlik import commons_toplayici as ct
    assert ct.ilgisizlik(_a(baslik), sorgu) is None


def test_sec_ilgisizi_cozunurluk_ve_ortusmeye_ragmen_secmez():
    from motor.varlik import commons_toplayici as ct
    sorgu = "Otlukbeli battle Ottoman army"
    adaylar = [_a("File:Otlukbeli battle Ottoman army ship.jpg", gen=9000), _a("File:Ottoman army camp.jpg", gen=2100),
               _a("File:Otlukbeli map.png", gen=8000, ad="Battle")]
    secilen, elenen = ct.sec(adaylar, sorgu)
    assert secilen["baslik"] == "File:Ottoman army camp.jpg"
    assert {b for b, n in elenen if "ilgisiz" in n} == {adaylar[0]["baslik"], adaylar[2]["baslik"]}


def test_topla_yalniz_ilgisiz_varsa_yedek_sorguya_gecer(monkeypatch, tmp_path):
    from motor.varlik import commons_toplayici as ct
    sorgular = []

    def ara(sorgu=None, kategori=None, adet=30, dosya=None):
        sorgular.append(sorgu)
        return [_a("File:Ottoman fleet.jpg")] if sorgu == "Ottoman army" else [_a("File:Map of Tercan.png")]

    monkeypatch.setattr(ct, "ara", ara)
    with pytest.raises(ct.ToplayiciHatasi, match="ilgisiz"):
        ct.topla({"gorsel_id": "g1", "sorgu": "Ottoman army", "yedek_sorgular": ["Otlukbeli 1473"]}, tmp_path)
    assert sorgular == ["Ottoman army", "Otlukbeli 1473"]


# ================================================================== 3) kalabalık birlik

def _n(roller, mesafe="uzak", eylem="yuruyus", **k):
    return {"tur": "3d", "eylem": eylem, "mesafe": mesafe, "roller": roller, **k}


def test_toplu_olcek_genis_kadrajda_birlik_tamamlanir():
    n = _n([{"rol": "komutan", "odak": True}, {"rol": "suvari", "donem": "akkoyunlu-15yy"}])
    y, kayit = planlayici.birlik_tamamla(n, "Akkoyunlu ordusu zafer elde etti.")
    assert [r.get("adet", 1) for r in y["roller"]] == [1, 5] and sum(r.get("adet", 1) for r in y["roller"]) == 6
    assert kayit == {"uygulandi": True, "neden": "metin 'ordusu'", "rol": "suvari", "onceki_toplam": 2, "toplam": 6}
    assert "adet" not in n["roller"][1]                                                  # özgün niyet değişmez
    k = veri.kural("kalabalik")["birlik"]
    assert (k["en_az"], k["hedef"]) == (4, 6)


@pytest.mark.parametrize("metin,niyet", [
    ("Bir anlık sessizlik.", _n([{"rol": "suvari"}])),                                     # toplu değil
    ("Ordu zafer kazandı.", _n([{"rol": "suvari"}], mesafe="orta")),                        # geniş kadraj değil
    ("Ordu zafer kazandı.", _n([{"rol": "suvari", "adet": 4}])),                            # zaten birlik
    ("Anadolu'nun birliği yolunda.", _n([{"rol": "suvari"}])),                              # 'birlik' = unity
    ("Birlikte yürüdüler.", _n([{"rol": "piyade"}])),                                       # 'birlikte' = together
    ("Ordu zafer kazandı.", {"tur": "harita", "evre": "E1"}),
])
def test_birlik_kurali_uygulanmaz(metin, niyet):
    y, kayit = planlayici.birlik_tamamla(niyet, metin)
    assert y is niyet and kayit is None


def test_birlik_eylem_ve_kusbakisi_kamera_ile_tetiklenir_komutan_cogaltilmaz():
    y, k = planlayici.birlik_tamamla(_n([{"rol": "piyade"}], eylem="hucum"), "Sessiz bir an.")
    assert k["neden"] == "eylem 'hucum'" and y["roller"][0]["adet"] == 6
    y, k = planlayici.birlik_tamamla(_n([{"rol": "okcu"}], mesafe="orta", kamera="drone_gecis"), "Akkoyunlu birlikleri.")
    assert k["uygulandi"] and y["roller"][0]["adet"] == 6
    n = _n([{"rol": "komutan"}, {"rol": "isci_sivil"}])
    y, k = planlayici.birlik_tamamla(n, "Ordu dağıldı.")
    assert y is n and k == {"uygulandi": False, "neden": "metin 'ordu'", "gerekce": "çoğaltılabilir askerî rol yok",
                            "toplam": 2}
    y, k = planlayici.birlik_tamamla(_n([{"rol": "piyade"}, {"rol": "okcu", "adet": 2}]), "Ordular karşılaştı.")
    assert [r.get("adet", 1) for r in y["roller"]] == [1, 5]                               # en kalabalık rol büyür


def test_pilot_senaryolarinda_birlik_kurali_degisiklik_yapmaz():
    """Gerçek pilot genel planları zaten 7+ kişilik: kural yalnız tek/az asker kalan geniş çekimi değiştirir."""
    for p in sorted((KOK / "motor/uretim/pilotlar").iterdir()):
        for c in json.loads((p / "senaryo.json").read_text())["cumleler"]:
            assert planlayici.birlik_tamamla(c["niyet"], c["metin"])[1] is None, (p.name, c["id"])


@ONBELLEK
@pytest.mark.parametrize("rol,donem,eylem", [("suvari", "osmanli-15yy", "yuruyus"), ("piyade", "osmanli-15yy", "yuruyus"),
                                             ("suvari", "akkoyunlu-15yy", "suvari_hucum")])
def test_gercek_planlayici_birligi_kadrajda_gosterir(rol, donem, eylem):
    t = {"id": "S5", "cumle": "S5", "sure_sn": 4.0, "amac": "olay", "metin": "Akkoyunlu ordusu zafer elde etti.",
         "niyet": _n([{"rol": rol, "donem": donem, "odak": True}], eylem=eylem)}
    c, eks, kayit = planlayici.cekim_kur(t, "osmanli-15yy", 9 / 16, [], 7)
    assert eks == [] and c["meta"]["birlik"]["toplam"] == 6
    assert len(c["karakterler"]) >= 4 and isinstance(c.get("kamera"), dict)              # budamadan sonra da birlik
    if eylem not in veri.kural("kalabalik")["birlik"]["eylemler"]:   # toplu eylem (hücum) metinden bağımsız birliktir
        tek = dict(t, metin="Bir anlık sessizlik.")
        c1, _, _ = planlayici.cekim_kur(tek, "osmanli-15yy", 9 / 16, [], 7)
        assert len(c1["karakterler"]) == 1 and "birlik" not in c1["meta"]


# ================================================================== 4) Edge-TTS → Piper yedeği

def _wav_yaz(yol, sure):
    sf.write(str(yol), np.zeros(int(44100 * sure), np.float32), 44100)
    return str(yol)


@pytest.fixture
def tts(monkeypatch, tmp_path):
    from kaos.audio import tts as kt
    monkeypatch.setattr(seslendirme, "ONBELLEK", tmp_path / "ses")
    monkeypatch.setattr(seslendirme, "_DUSEN", {})
    monkeypatch.delenv("MOTOR_TTS", raising=False)
    cagri = {"edge": 0, "piper": 0, "edge_hata": None}

    def edge(lines, cfg, outdir):
        cagri["edge"] += 1
        if cagri["edge_hata"]:
            raise kt.TTSError(cagri["edge_hata"])
        assert cfg["voices"]["anlatici"]["edge"]["voice"] == "tr-TR-AhmetNeural"
        return {k: _wav_yaz(Path(outdir) / f"line_{k[0]}_{k[1]}.wav", 0.05 * len(t)) for k, _, t, _ in lines}

    def piper(lines, cfg, outdir, model_dir):
        cagri["piper"] += 1
        return {k: _wav_yaz(Path(outdir) / f"line_{k[0]}_{k[1]}.wav", 0.07 * len(t)) for k, _, t, _ in lines}

    monkeypatch.setattr(kt, "edge_tts", edge)
    monkeypatch.setattr(kt, "piper_tts", piper)
    return cagri


CUMLELER = [{"id": "S1", "metin": "Tek gün."}, {"id": "S2", "metin": "Ordu doğuya yürüdü."}]


def test_varsayilan_piper_edge_ortam_degiskeniyle(tts, monkeypatch):
    assert seslendirme.tercih() == "piper"
    r = seslendirme.olc(CUMLELER)
    assert {x["motor"] for x in r.values()} == {"piper"} and tts["edge"] == 0
    monkeypatch.setenv("MOTOR_TTS", "edge")
    assert seslendirme.tercih() == "edge"
    r = seslendirme.olc(CUMLELER)
    assert {x["motor"] for x in r.values()} == {"edge"} and tts["edge"] == 1
    assert all("yedek_nedeni" not in x for x in r.values()) and r["S2"]["sure_sn"] == pytest.approx(0.05 * 19, abs=1e-3)
    assert not list((seslendirme.ONBELLEK).glob("*.mp3"))
    monkeypatch.setenv("MOTOR_TTS", "gemini")
    with pytest.raises(SystemExit, match="tanınmıyor"):
        seslendirme.tercih()


def test_edge_hatasinda_tum_senaryo_pipera_duser_ve_yapiskan(tts, capsys):
    tts["edge_hata"] = "ağ yok"
    r = seslendirme.olc(CUMLELER, motor="edge")
    assert {x["motor"] for x in r.values()} == {"piper"} and tts["piper"] == 1
    assert all(x["yedek_nedeni"] == "edge: TTSError: ağ yok" for x in r.values())
    assert "senaryonun tamamı piper ile üretiliyor" in capsys.readouterr().err
    r2 = seslendirme.olc([{"id": "S3", "metin": "Yeni cümle."}], motor="edge")       # aynı süreçte ağa gidilmez
    assert tts["edge"] == 1 and r2["S3"]["motor"] == "piper" and "yedek_nedeni" in r2["S3"]


def test_kismi_edge_onbellegi_ses_karistirmaz(tts):
    seslendirme.olc(CUMLELER[:1], motor="edge")                                         # S1 edge önbellekte
    tts["edge_hata"] = "zaman aşımı"
    r = seslendirme.olc(CUMLELER, motor="edge")                                         # S2 edge'de düşer
    assert {x["motor"] for x in r.values()} == {"piper"}                                # S1 dahil hepsi Piper


def test_yedeksiz_istekte_edge_hatasi_yukselir(tts):
    from kaos.audio import tts as kt
    tts["edge_hata"] = "ağ yok"
    with pytest.raises(kt.TTSError):
        seslendirme.olc(CUMLELER, motor="edge", yedek=False)
    assert tts["piper"] == 0


def test_onbellekteki_edge_sesi_aga_gitmeden_kullanilir(tts):
    seslendirme.olc(CUMLELER, motor="edge")
    tts["edge_hata"] = "ağ yok"
    r = seslendirme.olc(CUMLELER, motor="edge", yedek=False)                            # kurgu job'u: indirilen önbellek
    assert {x["motor"] for x in r.values()} == {"edge"} and tts["edge"] == 1


def test_piper_onbellek_anahtari_faz65_oncesiyle_ayni(tts):
    import hashlib
    cfg = yaml.safe_load((KOK / "config.yaml").read_text())
    r = seslendirme.olc(CUMLELER[:1])
    metin = seslendirme.okunus(CUMLELER[0])
    eski = hashlib.sha1(json.dumps([metin, "anlatici", cfg["voices"]["anlatici"], "piper"], ensure_ascii=False)
                        .encode()).hexdigest()[:16]
    assert Path(r["S1"]["wav"]).name == f"{eski}.wav"
    assert list(r["S1"]) == ["metin", "wav", "sure_sn", "harf_sn", "motor"]


def test_plana_uygun():
    cz = [{"cumle": "S1", "ses_sure_sn": 1.5}, {"cumle": "S2", "ses_sure_sn": 2.0}]
    ok = {"S1": {"sure_sn": 1.52, "motor": "edge"}, "S2": {"sure_sn": 2.0, "motor": "edge"}}
    assert seslendirme.plana_uygun(ok, cz) == []
    kotu = {"S1": {"sure_sn": 1.9, "motor": "piper"}}
    assert seslendirme.plana_uygun(kotu, cz) == ["S1: seslendirme 1.9 sn, plan 1.5 sn (piper)", "S2: seslendirme yok"]


def test_shorts_kurgu_planin_motorunu_yedeksiz_ister_uyusmazlikta_video_kurmaz(tmp_path, monkeypatch):
    from motor import ayar
    from motor.uretim import kurgu, plan_denetim, render
    monkeypatch.setattr(ayar, "ONBELLEK", tmp_path / "onb")
    plan = {"konu": "t", "format": "shorts", "cekimler": [{"id": "S1", "sure_sn": 2.0}],
            "ses": {"motor": "edge", "cizelge": [{"cumle": "S1", "ses_sure_sn": 1.5}], "toplam_sn": 2.0}}
    (tmp_path / "cekim_plani.json").write_text(json.dumps(plan))
    (tmp_path / "senaryo.json").write_text(json.dumps({"kanca": "S1", "cumleler": [{"id": "S1", "metin": "x"}]}))
    monkeypatch.setattr(plan_denetim, "denetle", lambda p: {"gecti": True, "hatalar": []})
    monkeypatch.setattr(render, "render", lambda py, cid: {"durum": "TAMAM", "video": "v.mp4", "olculen": {
        "kare": 1, "uretilen_kare": 1, "render_sn": 0.1, "kare_basina_sn_acilis_dahil": 0.1, "render_tepe_bellek_gb": 0.1,
        "karakter": 0, "cevre_varligi": 0}})
    monkeypatch.setattr(kurgu.subprocess, "run", lambda *a, **k: None)
    istek = {}

    def olc(cs, **k):
        istek.update(k)
        return {"S1": {"sure_sn": 1.9, "motor": k["motor"], "wav": "x"}}

    monkeypatch.setattr(seslendirme, "olc", olc)
    monkeypatch.setattr(kurgu, "_ses_karisimi", lambda *a: pytest.fail("uyuşmazlıkta ses karışımı kurulmamalı"))
    r = kurgu.uret(tmp_path)
    assert istek == {"motor": "edge", "yedek": False}
    assert r == {"durum": "HATA", "neden": "seslendirme planla uyuşmuyor",
                 "hatalar": ["S1: seslendirme 1.9 sn, plan 1.5 sn (edge)"]}


def test_workflow_gercek_uretimde_edge_ve_ses_onbellegini_tasir():
    w = yaml.safe_load((KOK / ".github/workflows/belgesel_uret.yml").read_text())
    assert w["env"]["MOTOR_TTS"] == "${{ github.event_name == 'workflow_dispatch' && 'edge' || 'piper' }}"
    yukle = [s for s in w["jobs"]["plan"]["steps"] if (s.get("with") or {}).get("name") == "seslendirme"]
    assert yukle and yukle[0]["with"]["path"] == "/tmp/motor_onbellek/seslendirme"
    indir = [s for s in w["jobs"]["kurgu"]["steps"] if (s.get("with") or {}).get("name") == "seslendirme"]
    assert indir and indir[0]["uses"].startswith("actions/download-artifact")
    assert "edge-tts" in (KOK / "requirements.txt").read_text()
