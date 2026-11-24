"""Görsel deney: bir çekimin belirli bir karesini verilen görsel profille render eder (Compatibility, aynı kamera/sahne).

Kullanım: python3 kare.py <cekim_id> <profil_adi|uretim> <kare_no> <cikti.png> [profiller.json] [proje_klasoru]
  'uretim' → motor/godot (değiştirilmemiş üretim kodu). Diğerleri → deney proje kopyası (ortam_v2.gd) + profil.
Ölçülen: render süresi (açılış dahil) ve kare sayısı; sonuç JSON olarak stdout'a.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

BURASI = Path(__file__).resolve().parent
REPO = BURASI.parents[2]
GODOT = os.environ.get("GODOT", "/tmp/godot/Godot_v4.7.2-stable_linux.x86_64")


def deney_projesi(hedef: Path) -> Path:
    if not (hedef / "project.godot").exists():
        shutil.copytree(REPO / "motor" / "godot", hedef, ignore=shutil.ignore_patterns(".godot"))
        shutil.copy(BURASI / "ortam_v2.gd", hedef / "sahneler" / "ortam.gd")
        subprocess.run([GODOT, "--headless", "--path", str(hedef), "--import"], capture_output=True)
    return hedef


def main() -> int:
    cid, profil, kare, cikti = sys.argv[1], sys.argv[2], int(sys.argv[3]), Path(sys.argv[4])
    profiller = json.loads(Path(sys.argv[5]).read_text()) if len(sys.argv) > 5 else {}
    proje = REPO / "motor" / "godot" if profil == "uretim" else deney_projesi(Path(sys.argv[6] if len(sys.argv) > 6 else "/tmp/gv2"))
    is_ = json.loads((REPO / "deneyler/faz51/altyapi/isler" / f"{cid}.json").read_text())
    if profil != "uretim":
        p = profiller[profil]
        is_["isik"]["gorsel"] = p.get("isik", {})
        is_["arazi"]["gorsel"] = p.get("arazi", {})
    gecici = Path(f"/tmp/kare_{cid}_{profil}")
    shutil.rmtree(gecici, ignore_errors=True)
    gecici.mkdir(parents=True)
    (gecici / "is.json").write_text(json.dumps(is_, ensure_ascii=False))
    t = time.time()
    r = subprocess.run(["xvfb-run", "-a", "-s", "-screen 0 1280x1024x24", GODOT, "--path", str(proje), "--rendering-driver",
                        "opengl3", "res://sahneler/cekim.tscn", "--write-movie", str(gecici / "k.png"), "--fixed-fps", "30",
                        "--quit-after", str(kare + 1), "--", str(gecici / "is.json")], capture_output=True, text=True)
    sure = time.time() - t
    kareler = sorted(gecici.glob("k*.png"))
    hatalar = [s for s in (r.stdout + r.stderr).splitlines() if "ERROR" in s]
    if not kareler or hatalar:
        print(json.dumps({"durum": "HATA", "hatalar": hatalar[:10]}, ensure_ascii=False))
        return 1
    cikti.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(kareler[-1], cikti)
    print(json.dumps({"durum": "TAMAM", "cekim": cid, "profil": profil, "kare": kare, "sure_sn": round(sure, 1),
                      "kare_sayisi": len(kareler), "hatalar": hatalar[:10]}, ensure_ascii=False))
    shutil.rmtree(gecici, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
