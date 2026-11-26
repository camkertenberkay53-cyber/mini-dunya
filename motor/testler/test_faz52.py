"""Faz 5.2 (sinematik belgesel) ölçüm disiplini ve adım testleri."""
import json

from motor import ayar
from motor.uretim import benchmark

KOK = ayar.REPO / "deneyler" / "faz52"


def test_taban_plani_ve_olcumu_kayitli():
    p = json.loads((KOK / "plan_taban.json").read_text())
    ids = {c["id"] for c in p["cekimler"]}
    assert set(benchmark.CEKIMLER) <= ids                      # sabit çekimler planda
    t = json.loads((KOK / "olcum" / "taban.json").read_text())
    for c in benchmark.CEKIMLER:
        x = t["cekimler"][c]
        assert x["render_sn"] > 0 and x["tepe_bellek_gb"] > 0 and x["kare"] > 0
        assert (KOK / "kareler" / f"taban_{c}.jpg").exists()   # görsel kanıt aynı kareden
    assert t["git"] and t["anahtarlar"]


def test_kapi_karari(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark, "KOK", tmp_path)
    (tmp_path / "olcum").mkdir()
    a = {"cekimler": {"S1": {"render_sn": 100.0, "tepe_bellek_gb": 1.0}, "S2": {"render_sn": 100.0, "tepe_bellek_gb": 1.0},
                      "S6": {"render_sn": 100.0, "tepe_bellek_gb": 1.0}}}
    b = {"cekimler": {"S1": {"render_sn": 108.0, "tepe_bellek_gb": 1.0}, "S2": {"render_sn": 120.0, "tepe_bellek_gb": 1.1},
                      "S6": {"render_sn": 140.0, "tepe_bellek_gb": 1.0}}}
    (tmp_path / "olcum" / "a.json").write_text(json.dumps(a))
    (tmp_path / "olcum" / "b.json").write_text(json.dumps(b))
    k = benchmark.kiyasla("a", "b")
    assert [k[c]["karar"] for c in ("S1", "S2", "S6")] == ["kabul", "rapor", "varsayilan_kapali"]
    assert benchmark.KAPI == {"kabul": 0.10, "rapor": 0.25}    # onaylanan kapı değişmedi
