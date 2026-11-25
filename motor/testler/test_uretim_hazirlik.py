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
    for c in plan["cekimler"]:
        assert len({k["takim"].split("_")[0] for k in c.get("karakterler", [])}) == 1, c["id"]


def test_konunun_donemleri_disindaki_karakter_reddedilir():
    plan = json.loads((PILOTLAR / "otlukbeli-1473/cekim_plani.json").read_text())
    p = copy.deepcopy(plan)
    p["cekimler"][0]["karakterler"][0]["takim"] = "rom_centurio"
    assert any("dönemi" in h for h in plan_denetim.denetle(p)["hatalar"])
    p = copy.deepcopy(plan)
    p["cekimler"][0]["donem"] = "bizans-15yy"
    assert any("konunun dönemleri" in h for h in plan_denetim.denetle(p)["hatalar"])
