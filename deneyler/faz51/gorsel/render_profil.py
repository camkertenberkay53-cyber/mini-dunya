"""Görsel deney (Actions): bir çekimi tam uzunlukta verilen profille render eder, ölçer ve karşılaştırma karesini çıkarır.

Kullanım: python3 render_profil.py <cekim_id> <profil: V0|V2|V2_PH> <kare_no> <cikti_klasoru>
  V0 → üretim projesi (motor/godot, değiştirilmemiş). V2/V2_PH → deney proje kopyası (ortam_v2.gd) + profiller.json.
Aynı kamera, sahne, ışık preset'i ve karakterler; yalnız görsel profil değişir. Ölçüm: render süresi, tepe RAM, CPU.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

BURASI = Path(__file__).resolve().parent
REPO = BURASI.parents[2]
sys.path.insert(0, str(BURASI))
sys.path.insert(0, str(REPO / "deneyler/faz51/altyapi"))
from kare import deney_projesi, GODOT  # noqa: E402
from olc_cekim import calistir  # noqa: E402


def main() -> int:
    cid, profil, kare_no, cikti = sys.argv[1], sys.argv[2], int(sys.argv[3]), Path(sys.argv[4])
    cikti.mkdir(parents=True, exist_ok=True)
    is_ = json.loads((REPO / "deneyler/faz51/altyapi/isler" / f"{cid}.json").read_text())
    if profil == "V0":
        proje = REPO / "motor" / "godot"
    else:
        proje = deney_projesi(Path("/tmp/gv2"))
        p = json.loads((BURASI / "profiller.json").read_text())[profil]
        is_["isik"]["gorsel"] = p.get("isik", {})
        is_["arazi"]["gorsel"] = p.get("arazi", {})
    is_yolu = cikti / f"{cid}_{profil}.is.json"
    is_yolu.write_text(json.dumps(is_, ensure_ascii=False))
    kare = round(is_["cekim"]["sure_sn"] * is_["fps"])
    avi, mp4 = cikti / f"{cid}_{profil}.avi", cikti / f"{cid}_{profil}.mp4"
    r = calistir(["xvfb-run", "-a", "-s", "-screen 0 1280x1024x24", GODOT, "--path", str(proje), "--rendering-driver",
                  "opengl3", "res://sahneler/cekim.tscn", "--write-movie", str(avi), "--fixed-fps", "30",
                  "--quit-after", str(kare), "--", str(is_yolu)], 3 * 3600)
    hatalar = [s for s in r["gunluk"].splitlines() if "ERROR" in s]
    sonuc = {"cekim": cid, "profil": profil, "kare": kare, "render_sn": r["sure_sn"], "kare_basina_sn": round(r["sure_sn"] / kare, 3),
             "tepe_gb": r["tepe_gb"], "cpu_sn": r["cpu_sn"], "cikis": r["cikis"], "godot_hata": hatalar[:10],
             "durum": "TAMAM" if r["cikis"] == 0 and avi.exists() and not hatalar else "HATA"}
    if avi.exists():
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(avi), "-c:v", "libx264", "-preset", "veryfast",
                        "-crf", "18", "-pix_fmt", "yuv420p", "-an", str(mp4)], check=True)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(avi), "-vf", f"select=eq(n\\,{kare_no})",
                        "-frames:v", "1", str(cikti / f"{cid}_{profil}.png")], check=True)
        avi.unlink()
    (cikti / f"{cid}_{profil}.json").write_text(json.dumps(sonuc, ensure_ascii=False, indent=1))
    print(json.dumps(sonuc, ensure_ascii=False))
    return 0 if sonuc["durum"] == "TAMAM" else 1


if __name__ == "__main__":
    sys.exit(main())
