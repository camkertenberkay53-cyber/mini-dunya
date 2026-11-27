"""Mekân vitrini: planlayıcıyla (konuya özel kod yok) altı örnek ortam. Kullanım: mekan_vitrin.py [once]"""
import json, sys
from pathlib import Path
from motor.uretim import planlayici, plan_denetim
plan = json.loads(Path("motor/uretim/pilotlar/otlukbeli-1473/cekim_plani.json").read_text())
ONCE = "once" in sys.argv
def r(rol, donem, adet=None, odak=False):
    d = {"rol": rol, "donem": donem}
    if adet: d["adet"] = adet
    if odak: d["odak"] = True
    return d
T = [
 ("osmanli-15yy", "M1", "Dağlık vadide savaş düzeni.", "baglam", [r("komutan","osmanli-15yy",odak=True), r("piyade","osmanli-15yy",8)], {"mekan": "dagli_savas_alani"}, "bekleme"),
 ("akkoyunlu-15yy", "M2", "Orman kenarında ilerleyen birlik.", "olay", [r("piyade","akkoyunlu-15yy",odak=True), r("piyade","akkoyunlu-15yy",6)], {"mekan": "orman"}, "yuruyus"),
 ("bizans-15yy", "M3", "Kalenin önünde savunma hattı.", "baglam", [r("komutan","bizans-15yy",odak=True), r("piyade","bizans-15yy",8)], {"mekan": "kale"}, "bekleme"),
 ("osmanli-15yy", "M4", "Kasabanın meydanında askerler.", "baglam", [r("komutan","osmanli-15yy",odak=True), r("piyade","osmanli-15yy",5)], {"mekan": "kasaba"}, "bekleme"),
 ("osmanli-15yy", "M5", "Kıyıda demirli gemiler.", "baglam", [r("komutan","osmanli-15yy",odak=True), r("piyade","osmanli-15yy",5)], {"mekan": "liman"}, "bekleme"),
 ("bizans-15yy", "M6", "Nehir kıyısında karargâh.", "baglam", [r("komutan","bizans-15yy",odak=True), r("piyade","bizans-15yy",6)], {"mekan": "nehir_kiyisi"}, "bekleme"),
]
for donem, cid, cumle, amac, roller, ortam, eylem in T:
    if ONCE:
        ortam = {"arazi": "ova_cimen", "isik": "aksam_ustu"}
    t = {"id": cid, "cumle": cumle, "sure_sn": 4.0, "amac": amac,
         "niyet": {"tur": "3d", "roller": roller, "mesafe": "uzak", "ortam": ortam, "eylem": eylem}}
    c, eksik, _ = planlayici.cekim_kur(t, donem, 9 / 16, [], 17)
    v = dict(plan, konu=f"mekan-{cid}{'-once' if ONCE else ''}", cekimler=[c], donem=donem)
    d = plan_denetim.denetle(v)
    print(cid, "eksik:", eksik, c.get("kamera", {}).get("plan"), c["ortam"], "DENETIM", d["gecti"], d["hatalar"][:2])
    Path(f"/tmp/mekan_{cid}{'_once' if ONCE else ''}.json").write_text(json.dumps(v, ensure_ascii=False, indent=1))
