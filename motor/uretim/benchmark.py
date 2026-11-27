"""Faz 5.2 ölçüm disiplini: sabit plan + sabit çekimler üzerinde tam render ölçümü (önbelleksiz).

python3 -m motor.uretim.benchmark <ad> [--plan deneyler/faz52/plan_taban.json] [--cekimler S1,S2,S6]

Her ölçüm deneyler/faz52/olcum/<ad>.json dosyasına yazılır: çekim başına render süresi, kare başına süre, en yüksek
RAM, kodlama süresi, kare sayısı; ayrıca git sürümü, görsel anahtarların durumu ve makine bilgisi. Her çekimin orta
karesi deneyler/faz52/kareler/<ad>_<çekim>.jpg olarak saklanır (önce/sonra görsel kanıtı aynı kareden).
Karşılaştırma: kiyasla(taban, yeni) → çekim başına yüzde fark; kabul kapısı KAPI (+%10 kabul, +%25 üstü kapalı).
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from motor import ayar
from motor.uretim import render, veri

KOK = ayar.REPO / "deneyler" / "faz52"
PLAN = KOK / "plan_taban.json"
CEKIMLER = ["S1", "S2", "S6"]   # yakın/orta, kalabalık, savaş
KAPI = {"kabul": 0.10, "rapor": 0.25}


def _anahtarlar() -> dict:
    g = veri.kural("gorsel")
    durum = {ad: g.get(ad, {}).get("acik") for ad in ("sinematik_render", "mekan_kalite", "belgesel_kalite", "karakter_kalite",
                                                      "vfx", "sinema", "isik_onayarlari", "renk_profilleri", "portre_dof")}
    durum["insan"] = veri.kural("insan").get("acik")
    durum["kalabalik_salinim"] = veri.kural("kalabalik").get("salinim", {}).get("acik")
    return durum


def _orta_kare(video: str, hedef: Path) -> None:
    sure = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video],
                                capture_output=True, text=True).stdout.strip() or 0)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{sure / 2:.2f}", "-i", video, "-frames:v", "1", "-q:v", "3",
                    str(hedef)], check=True)


def olc(ad: str, plan: Path = PLAN, cekimler: list[str] = CEKIMLER) -> dict:
    (KOK / "olcum").mkdir(parents=True, exist_ok=True)
    (KOK / "kareler").mkdir(parents=True, exist_ok=True)
    sonuc = {"ad": ad, "tarih": time.strftime("%Y-%m-%d %H:%M"), "plan": str(plan.relative_to(ayar.REPO)),
             "git": subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ayar.REPO, capture_output=True, text=True).stdout.strip(),
             "anahtarlar": _anahtarlar(), "cekimler": {}}
    for c in cekimler:
        r = render.render(str(plan), c, onbellek=False)
        if r.get("durum") != "TAMAM":
            sonuc["cekimler"][c] = {"durum": r.get("durum"), "neden": r.get("neden") or r.get("hatalar")}
            continue
        o = r["olculen"]
        sonuc["makine"] = r.get("makine")
        sonuc["cekimler"][c] = {"render_sn": o["render_sn"], "kare": o["kare"], "kare_basina_sn": o["kare_basina_sn_acilis_dahil"],
                                "tepe_bellek_gb": o["render_tepe_bellek_gb"], "kodlama_sn": o.get("kodlama_sn"),
                                "karakter": o.get("karakter"), "video": r["video"]}
        _orta_kare(r["video"], KOK / "kareler" / f"{ad}_{c}.jpg")
        print(f"ÖLÇÜM {ad} {c}: {o['render_sn']} sn, {o['kare_basina_sn_acilis_dahil']} sn/kare, {o['render_tepe_bellek_gb']} GB", flush=True)
    toplam = [x["render_sn"] for x in sonuc["cekimler"].values() if "render_sn" in x]
    sonuc["toplam_render_sn"] = round(sum(toplam), 1)
    (KOK / "olcum" / f"{ad}.json").write_text(json.dumps(sonuc, ensure_ascii=False, indent=1))
    return sonuc


def kiyasla(taban: str, yeni: str) -> dict:
    a = json.loads((KOK / "olcum" / f"{taban}.json").read_text())
    b = json.loads((KOK / "olcum" / f"{yeni}.json").read_text())
    out = {}
    for c, x in b["cekimler"].items():
        y = a["cekimler"].get(c)
        if not y or "render_sn" not in x or "render_sn" not in y:
            continue
        fark = (x["render_sn"] - y["render_sn"]) / y["render_sn"]
        out[c] = {"taban_sn": y["render_sn"], "yeni_sn": x["render_sn"], "fark": round(fark, 3),
                  "bellek_gb": [y["tepe_bellek_gb"], x["tepe_bellek_gb"]],
                  "karar": "kabul" if fark <= KAPI["kabul"] else ("rapor" if fark <= KAPI["rapor"] else "varsayilan_kapali")}
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    plan = Path(a[a.index("--plan") + 1]) if "--plan" in a else PLAN
    cek = a[a.index("--cekimler") + 1].split(",") if "--cekimler" in a else CEKIMLER
    print(json.dumps(olc(a[0], plan if plan.is_absolute() else ayar.REPO / plan, cek), ensure_ascii=False, indent=1))
