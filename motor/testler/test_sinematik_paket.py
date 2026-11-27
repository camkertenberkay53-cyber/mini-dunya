"""Sinematik paket: binek (at/süvari), parçacık efektleri, son işlem katmanı, dış CC0 çevre modelleri.
Hepsi genel (konudan bağımsız), açılıp kapatılabilir ve lisansı kayıtlı olmalı."""
import json

import yaml

from motor import ayar
from motor.uretim import animasyon_izni, binek, planlayici, render, secici, veri

KOK = ayar.MOTOR


def test_binek_lisansi_ve_kaynagi_kayitli():
    b = veri.kural("binek")["binekler"]["at"]
    assert b["lisans"]["lisans"] == "CC0-1.0"
    kayit = json.loads((KOK / "varlik/oga2/lisans.json").read_text())["varliklar"][0]
    assert kayit["durum"] == "TAMAM" and kayit["lisanslar_sayfada"] == ["CC0"] and kayit["yazar"] == "quaternius"
    assert (KOK / b["kaynak"]).exists()


def test_at_hizlari_olculur_ve_planda_kullanilir():
    assert binek.hazir("at")
    o = binek.olcum("at")
    assert o["animasyonlar"]["Run"]["zemin_hizi_m_sn"] > 2.0          # dörtnala ölçülmüş, uydurulmamış
    assert o["animasyonlar"]["Idle"]["zemin_hizi_m_sn"] == 0.0
    bn = binek.plan_bilgisi("suvari_hucum")
    assert bn["hiz_m_sn"] == round(binek.hiz("at", "Run"), 4)


def test_suvari_hucumu_yalniz_binekli_takimlarla_kurulur():
    n = {"tur": "3d", "roller": [{"rol": "suvari", "adet": 4}], "eylem": "suvari_hucum", "mesafe": "uzak"}
    o, eksik = planlayici.oyuncu_sec(n, "akkoyunlu-15yy")
    assert o and not eksik
    assert all(veri.takimlar()[x["takim"]].get("binek") == "at" and x["binek"]["id"] == "at" for x in o)
    k, _, _ = planlayici.dizilis_kur(o, "suvari_hucum", 3)
    assert all(abs(x["hiz_m_sn"] - binek.hiz("at", "Run")) < 1e-3 and x["binek"]["animasyon"] == "Run" for x in k)


def test_binek_yoksa_binicilik_hala_reddedilir():
    """Eski kural korunur: bağlamda binek yokken Driving_Loop anlamsal olarak geçmez; Roma süvarisinde giysi taşması
    yasağı (Faz 3b) sürer."""
    assert not animasyon_izni.anlamsal_durum("rom_suvari", "Driving_Loop")[0]
    assert not secici.sec("suvari", "roma-cumhuriyet", "orta", eylem="binicilik")["uygun"]


def test_atli_hiz_denetimi_toynak_kaymasini_yakalar():
    b = {"id": "at", "animasyon": "Run"}
    assert animasyon_izni.hiz_durumu("Driving_Loop", binek.hiz("at", "Run"), 1.0, b)[0]
    assert not animasyon_izni.hiz_durumu("Driving_Loop", 1.0, 1.0, b)[0]
    assert not animasyon_izni.izinli("akk_piyade_kilic", "Driving_Loop", {"binek": True}, 4.0, 1.0, b)[0]


def test_render_isine_efektler_ve_binek_bilgisi_girer():
    plan = json.loads((KOK / "uretim/pilotlar/otlukbeli-1473/cekim_plani.json").read_text())
    s4 = next(c for c in plan["cekimler"] if c["id"] == "S4")
    is_ = render.is_hazirla(plan, s4)
    assert all(k["binek"]["glb"].endswith("at.glb") and k["binek"]["donlar"] for k in is_["cekim"]["karakterler"])
    assert "glb" not in json.dumps(s4["karakterler"][0]["binek"])   # plan değişmez (kopyaya eklenir)
    assert is_["vfx"]["acik"] and is_["sinema"]["acik"]
    s6 = next(c for c in plan["cekimler"] if c["id"] == "S6")
    assert render.is_hazirla(plan, s6)["vfx"]["savas"]


def test_efektler_ve_sinema_katmani_kapatilabilir():
    g = veri.kural("gorsel")
    assert isinstance(g["vfx"]["acik"], bool) and isinstance(g["sinema"]["acik"], bool)
    assert 0 <= g["sinema"]["vinyet"] <= 0.6 and g["sinema"]["gren"] <= 0.05      # görüntüyü boğmaz
    assert all(abs(x - 1) <= 0.08 for x in g["sinema"]["golge_ton"] + g["sinema"]["isik_ton"])


def test_parcacik_dokulari_cc0_ve_kayitli():
    d = json.loads((KOK / "varlik/kenney_parcacik/lisans.json").read_text())
    assert d["lisans"] == "CC0-1.0" and "Creative Commons Zero" in (KOK / "varlik/kenney_parcacik/LICENSE.txt").read_text()
    g = veri.kural("gorsel")["vfx"]
    for ad in ("toz", "duman"):
        assert (KOK / g[ad]["doku"]).name in d["dosyalar"]


def test_dis_cevre_modelleri_lisansli_ve_siniflandirilmis():
    ek = yaml.safe_load((KOK / "varlik/ekipman_ek.yaml").read_text())["parcalar"]
    kayit = json.loads((KOK / "varlik/dis_cevre_kaydi.json").read_text())
    kendi = json.loads((KOK / "varlik/ekipman_kaydi.json").read_text())
    for pid in ("sur_burclu", "gozetleme_kulesi", "harabe_kemer"):
        assert pid not in kendi                    # kendi üretim kaydı yalnız kendi üretimimizi tutar
        assert ek[pid]["uretici"] == "dis_usd"
        assert kayit[pid]["lisans"] == "CC0-1.0" and kayit[pid]["kaynak"]["commit"]
        assert veri.kalite()["ekipman"][pid]["sinif"] in ("A", "B")
    assert "pazar_tezgahlari" not in ek            # 390 KB sınırını aştı: eşik düşürülmedi, varlık alınmadı


def test_godot_betikleri_bagli():
    c = (KOK / "godot/sahneler/cekim.gd").read_text()
    for x in ("D.binek_kur(", "V.toz(", "V.duman(", "S.kur("):
        assert x in c
    assert "_process_modification_with_delta" in (KOK / "godot/sahneler/binici_bacak.gd").read_text()
