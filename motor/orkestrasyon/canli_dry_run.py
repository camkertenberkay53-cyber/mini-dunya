"""Canlı uçtan uca dry-run: Kaynak Keşfi → Canlı Kaynak Doğrulama → Gemini Senaryo/Sahne Planı → Validation Gate.

python3 -m motor.orkestrasyon.canli_dry_run "<konu>" [--mod uzun|shorts] [--cikti klasor]

- Ağ yoksa ya da keşif sonuç vermezse bunu açıkça raporlar (çıkış 3).
- GEMINI_API_KEY yoksa Gemini adımı ATLANIR ve rapor bunu açıkça söyler. Mock'a GEÇİLMEZ.
- Render başlatılmaz (dry-run). Anahtar hiçbir çıktıya yazılmaz.
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

from motor.orkestrasyon.gemini import GercekUretimHatasi, GeminiLLMProvider
from motor.orkestrasyon.kaynak_dogrulayici import KaynakDogrulayici, url_gizle
from motor.orkestrasyon.kaynak_kesif import WikipediaKesif, havuz_olustur
from motor.orkestrasyon.senaryo_planlayici import plan_uret


def calistir(konu: str, mod: str = "uzun") -> dict:
    t0 = time.time()
    r = {"konu": konu, "mod": mod, "asamalar": {}}
    kesif = WikipediaKesif()
    kaynaklar = kesif.kesfet(konu)
    ana = [k for k in kaynaklar if not k.get("aday")]
    r["asamalar"]["1_kesif"] = {"ana_madde": [{"id": k["id"], "url": url_gizle(k["url"]), "baslik": k["baslik"],
                                                "bolum_sayisi": len(k.get("bolumler", [])), "metin_karakter": len(k.get("metin") or "")}
                                               for k in ana],
                                "aday_dis_kaynak": Counter(k["tur"] for k in kaynaklar if k.get("aday")), "log": kesif.log}
    if not ana:
        r["durum"] = "kesif_basarisiz"
        r["sure_sn"] = round(time.time() - t0, 1)
        return r
    havuz = havuz_olustur(konu, kaynaklar, KaynakDogrulayici())
    kay = havuz["kayitlar"]
    r["asamalar"]["2_dogrulama"] = {
        "kaynak_raporu": havuz["kaynak_raporu"], "bagimsiz_kume_sayisi": havuz["kume_sayisi"],
        "kayit_sayisi": len(kay), "durumlar": Counter(k["durum"] for k in kay),
        "tek_kaynak_uyarisi": sum(k["tek_kaynak_uyarisi"] for k in kay),
        "celiskiler": [{"id": k["id"], "celiski": k["celiski"], "iddia": k["iddia"][:200]} for k in kay if k.get("celiski")],
        "ornek_dogrulanmis": [{"id": k["id"], "iddia": k["iddia"][:200], "excerpt": k["kaynaklar"][0]["dogrulama"]["supporting_excerpt"][:200]}
                              for k in kay if k["durum"] == "dogrulanmis"][:5]}
    if not os.environ.get("GEMINI_API_KEY"):
        r["asamalar"]["3_gemini"] = {"durum": "atlandi", "neden": "GEMINI_API_KEY tanımlı değil (mock'a geçilmedi)"}
        r["durum"] = "gemini_atlandi"
    else:
        try:
            g = GeminiLLMProvider()
            p = plan_uret(konu, mod, g, arastirma=havuz)
            r["asamalar"]["3_4_gemini_plan_ve_kapi"] = {
                "durum": p["durum"], "model": g.kullanilan_model, "gemini_cagri": g.cagri_sayisi,
                "katmanlar": {k: [{"deneme": d["deneme"], "tur": d["tur"], "hata_sayisi": len(d["hatalar"]),
                                   "hata_kodlari": dict(Counter(h["kod"] for h in d["hatalar"]))} for d in v.get("denemeler", [])]
                              for k, v in p["katmanlar"].items() if isinstance(v, dict) and "denemeler" in v},
                "ozet": p.get("ozet"), "uyarilar": p.get("uyarilar"), "ozet_hata": p.get("ozet_hata"),
                "hatalar_ilk20": (p.get("hatalar") or [])[:20], "render_baslatildi": p["render_baslatildi"]}
            if p["durum"] == "uretime_hazir":
                r["plan"] = p["plan"]
                r["asamalar"]["3_4_gemini_plan_ve_kapi"]["ilk_sahneler"] = p["plan"]["sahneler"][:6]
                r["asamalar"]["3_4_gemini_plan_ve_kapi"]["guven_durumlari"] = Counter(s["guven_durumu"] for s in p["plan"]["sahneler"])
            r["durum"] = p["durum"]
        except GercekUretimHatasi as e:
            r["asamalar"]["3_gemini"] = {"durum": "basarisiz", "hata": str(e)[:500]}
            r["durum"] = "gemini_basarisiz"
    r["sure_sn"] = round(time.time() - t0, 1)
    return r


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    konu = argv[0]
    mod = argv[argv.index("--mod") + 1] if "--mod" in argv else "uzun"
    r = calistir(konu, mod)
    if "--cikti" in argv:
        k = Path(argv[argv.index("--cikti") + 1])
        k.mkdir(parents=True, exist_ok=True)
        (k / f"dry_run_{mod}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1, default=list))
    ozet = {k: v for k, v in r.items() if k != "plan"}
    print(json.dumps(ozet, ensure_ascii=False, indent=1, default=dict)[:60000])
    return {"uretime_hazir": 0, "gemini_atlandi": 0, "durduruldu": 1, "gemini_basarisiz": 1}.get(r["durum"], 3)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
