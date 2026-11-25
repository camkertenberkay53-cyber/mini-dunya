"""Vitrin: motorun planlayıcısıyla (konuya özel kod yok) Bizans surları önünde piyade + süvari çekimleri kurar ve denetler."""
import json, sys
from pathlib import Path
from motor.uretim import planlayici, plan_denetim
plan = json.loads(Path("motor/uretim/pilotlar/otlukbeli-1473/cekim_plani.json").read_text())
taslaklar = [
 {"id": "V1", "cumle": "Surların önünde savunma hattı.", "sure_sn": 4.0, "amac": "baglam",
  "niyet": {"tur": "3d", "roller": [{"rol": "komutan", "donem": "bizans-15yy", "odak": True}, {"rol": "piyade", "donem": "bizans-15yy", "adet": 9}],
            "mesafe": "uzak", "ortam": {"arazi": "ova_cimen", "isik": "aksam_ustu", "cevre": ["sur_burclu", "gozetleme_kulesi", "harabe_kemer"]}, "eylem": "bekleme"}},
 {"id": "V2", "cumle": "Bizans süvarisi kapıdan çıkıyor.", "sure_sn": 4.0, "amac": "olay",
  "niyet": {"tur": "3d", "roller": [{"rol": "suvari", "donem": "bizans-15yy", "odak": True}, {"rol": "suvari", "donem": "bizans-15yy", "adet": 5}],
            "mesafe": "uzak", "ortam": {"arazi": "ova_cimen", "isik": "aksam_ustu", "cevre": ["sur_burclu", "gozetleme_kulesi"]}, "eylem": "suvari_hucum"}},
]
cekimler, gecmis = [], []
for t in taslaklar:
    c, eksik, _ = planlayici.cekim_kur(t, "bizans-15yy", 9 / 16, gecmis, 11)
    print(t["id"], "eksik:", eksik, c["kamera"]["plan"], c["kamera"]["hareket"], [x["id"] for x in c["ortam"].get("cevre", [])])
    cekimler.append(c); gecmis.append(c.get("meta", {}))
v = dict(plan, konu="vitrin-bizans", cekimler=cekimler, donem="bizans-15yy")
v.pop("donemler", None)
Path("/tmp/vitrin_plan.json").write_text(json.dumps(v, ensure_ascii=False, indent=1))
d = plan_denetim.denetle(v)
print("DENETIM", d["gecti"], d["hatalar"][:6])
