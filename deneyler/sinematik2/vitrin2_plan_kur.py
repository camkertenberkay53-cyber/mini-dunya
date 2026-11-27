"""Vitrin 2: motorun planlayıcısıyla (konuya özel kod yok) topçu hattı + ordugâh ve kuşatma (sur + arka plan ordusu)."""
import json
from pathlib import Path
from motor.uretim import planlayici, plan_denetim
plan = json.loads(Path("motor/uretim/pilotlar/otlukbeli-1473/cekim_plani.json").read_text())
T = [
 ("osmanli-15yy", {"id": "V3", "cumle": "Osmanlı topları ateş açıyor.", "sure_sn": 4.0, "amac": "baglam",
  "niyet": {"tur": "3d", "roller": [{"rol": "komutan", "donem": "osmanli-15yy", "odak": True}, {"rol": "piyade", "donem": "osmanli-15yy", "adet": 6}],
            "mesafe": "uzak", "ortam": {"arazi": "ova_cimen", "isik": "aksam_ustu", "cevre": ["top_arabasi", "top_arabasi", "top_arabasi"]}, "eylem": "bekleme"}}),
 ("bizans-15yy", {"id": "V4", "cumle": "Surların önünde büyük ordu.", "sure_sn": 4.0, "amac": "baglam",
  "niyet": {"tur": "3d", "roller": [{"rol": "komutan", "donem": "bizans-15yy", "odak": True}, {"rol": "piyade", "donem": "bizans-15yy", "adet": 8}],
            "mesafe": "uzak", "ortam": {"arazi": "ova_cimen", "isik": "aksam_ustu", "cevre": ["sur_burclu", "gozetleme_kulesi"], "kalabalik": "ordu"},
            "eylem": "bekleme"}}),
]
for donem, t in T:
    c, eksik, _ = planlayici.cekim_kur(t, donem, 9 / 16, [], 13)
    v = dict(plan, konu=f"vitrin2-{t['id']}", cekimler=[c], donem=donem)
    d = plan_denetim.denetle(v)
    print(t["id"], "eksik:", eksik, c["kamera"]["plan"], c["kamera"]["hareket"], "DENETIM", d["gecti"], d["hatalar"][:3])
    Path(f"/tmp/vitrin2_{t['id']}.json").write_text(json.dumps(v, ensure_ascii=False, indent=1))
