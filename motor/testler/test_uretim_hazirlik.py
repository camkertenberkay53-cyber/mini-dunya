"""Pilot hazırlık: konu değiştirildiğinde (çok taraflı konu dahil) motorun evrensel planlama hattı çalışır."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from motor.uretim import plan_denetim, uretim_hatti

PILOTLAR = Path(__file__).resolve().parents[1] / "uretim/pilotlar"


def test_cok_tarafli_konu_planlanir_ve_denetimden_gecer():
    r = uretim_hatti.planla(PILOTLAR / "otlukbeli-1473")
    assert r["gecti"], r["hatalar"]
    plan = json.loads((PILOTLAR / "otlukbeli-1473/cekim_plani.json").read_text())
    assert plan["donemler"] == ["osmanli-15yy", "akkoyunlu-15yy"]
    kitler = {k["takim"].split("_")[0] for c in plan["cekimler"] for k in c.get("karakterler", [])}
    assert {"osm", "akk"} <= kitler
    # her çekimin karakterleri tek tarafa aittir (taraflar karışmaz) ve çevre varlığı çekimin döneminden gelir
    # İstisna yalnız kayıtlı düello koreografisi: rakipler 'karsi_' rolüyle, TEK karşı taraftan, çift sayısı kadar.
    for c in plan["cekimler"]:
        ks = c.get("karakterler", [])
        kendi = [k for k in ks if not str(k.get("rol", "")).startswith("karsi_")]
        karsi = [k for k in ks if str(k.get("rol", "")).startswith("karsi_")]
        assert len({k["takim"].split("_")[0] for k in kendi}) == 1, c["id"]
        if karsi:
            kor = c.get("meta", {}).get("koreografi", {})
            assert kor.get("tur") == "duello", c["id"]
            taraf = {k["takim"].split("_")[0] for k in karsi}
            assert len(taraf) == 1 and taraf != {kendi[0]["takim"].split("_")[0]}, c["id"]
            assert kor["karsi_donem"] in plan["donemler"] and kor["karsi_donem"] != c.get("donem", plan["donemler"][0]), c["id"]
            assert len(karsi) <= kor["cift"], c["id"]                 # kadrajda görünmeyen budanmış olabilir


def test_konunun_donemleri_disindaki_karakter_reddedilir():
    plan = json.loads((PILOTLAR / "otlukbeli-1473/cekim_plani.json").read_text())
    p = copy.deepcopy(plan)
    p["cekimler"][0]["karakterler"][0]["takim"] = "rom_centurio"
    assert any("dönemi" in h for h in plan_denetim.denetle(p)["hatalar"])
    p = copy.deepcopy(plan)
    p["cekimler"][0]["donem"] = "bizans-15yy"
    assert any("konunun dönemleri" in h for h in plan_denetim.denetle(p)["hatalar"])


# ---------------------------------------------------------------- Faz 5.5 ücretsiz varlık paketi (CC0)

def _oga_lisans():
    return json.loads((Path(__file__).resolve().parents[1] / "varlik/oga/lisans.json").read_text())


def test_ek_animasyon_kutuphanesi_lisansli_ve_her_animasyon_olculmus():
    from motor.uretim import veri
    k = veri.kural("animasyon")
    lis = {v["kimlik"]: v for v in _oga_lisans()["varliklar"]}
    for ad, yol in k["kutuphaneler"].items():
        assert (Path(__file__).resolve().parents[1] / yol).exists(), yol
        assert lis[ad]["durum"] == "TAMAM" and lis[ad]["lisanslar_sayfada"] == ["CC0"]
    test = veri.animasyon_testi()
    ek = [a for a in k["animasyonlar"] if "/" in a]
    assert len(ek) >= 8
    for a in ek:
        assert a in test["animasyonlar"], a
        assert all(a in x for x in test["takimlar"].values()), a          # 52 karakterin hepsinde ölçüldü
        assert any(x[a]["gecti"] for x in test["takimlar"].values()), a   # en az bir karakterde geçer


def test_olculmemis_ya_da_kalan_ek_animasyon_reddedilir():
    from motor.uretim import animasyon_izni, veri
    test = veri.animasyon_testi()
    kalan = next((t, a) for t, x in test["takimlar"].items() for a, r in x.items() if "/" in a and not r["gecti"])
    ok, n = animasyon_izni.teknik_durum(*kalan)
    assert not ok and n


def test_kayit_sesleri_cc0_ve_karisima_girer(tmp_path):
    import glob
    import numpy as np
    from motor.uretim import kurgu, veri
    ks = veri.kural("kurgu")["kayit_sesleri"]
    kok = Path(__file__).resolve().parents[1]
    lis = {v["kimlik"] for v in _oga_lisans()["varliklar"] if v["lisanslar_sayfada"] == ["CC0"]}
    yollar = [ks["ambiyans"]["dosya"], ks["kus"]["dosya"]] + [g for e in ks["eylem_sesleri"] for g in
                                                              glob.glob(str(kok / e["desen"]))]
    for y in yollar:
        p = Path(y) if Path(y).is_absolute() else kok / y
        assert p.exists(), y
        assert p.relative_to(kok / "varlik/oga").parts[0] in lis, y
    plan = json.loads((PILOTLAR / "otlukbeli-1473/cekim_plani.json").read_text())
    alt = np.zeros(int(plan["ses"]["toplam_sn"] * kurgu.SR), np.float32)
    kurgu._eylem_sesleri(alt, plan, ks, {})
    assert np.abs(alt).max() > 0.01            # savaş çekiminde kılıç sesi var
    alt2 = np.zeros_like(alt)
    kurgu._eylem_sesleri(alt2, plan, ks, {})
    assert np.array_equal(alt, alt2)           # belirlenimci
