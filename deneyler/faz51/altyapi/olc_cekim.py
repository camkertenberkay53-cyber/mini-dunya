"""Faz 5.1 altyapı deneyi: bir GitHub Actions işinde verilen çekimleri render eder ve gerçek ölçüm kaydeder.

Kullanım: python3 olc_cekim.py <is_ad> <cikti_klasoru> <cekim_id> [<cekim_id> ...]
Her çekim için: Godot render süresi, süreç ağacının tepe belleği, CPU saniyesi, ortalama çekirdek kullanımı,
H.264 kodlama süresi, üretilen kare sayısı, Godot hata satırları. Tahmin yok; yalnızca ölçüm.
Render komutu motor/uretim/render.py ile aynıdır (Compatibility / opengl3, aynı kodlama ayarları).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

BURASI = Path(__file__).resolve().parent
REPO = BURASI.parents[2]
GODOT = os.environ.get("GODOT", "/tmp/godot/Godot_v4.7.2-stable_linux.x86_64")
PROJE = REPO / "motor" / "godot"
FPS = 30


def calistir(komut: list[str], zaman_asimi: int) -> dict:
    t0 = time.time()
    p = subprocess.Popen(komut, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    ana = psutil.Process(p.pid)
    tepe, cpu = 0, {}
    cikti: list[str] = []
    okuyucu = threading.Thread(target=lambda: cikti.append(p.stdout.read()), daemon=True)
    okuyucu.start()
    while p.poll() is None:
        try:
            surecler = [ana] + ana.children(recursive=True)
            tepe = max(tepe, sum(s.memory_info().rss for s in surecler))
            for s in surecler:
                c = s.cpu_times()
                cpu[s.pid] = c.user + c.system
        except psutil.Error:
            pass
        if time.time() - t0 > zaman_asimi:
            p.kill()
            return {"sure_sn": round(time.time() - t0, 1), "cikis": "ZAMAN_ASIMI", "tepe_gb": round(tepe / 1e9, 2),
                    "cpu_sn": round(sum(cpu.values()), 1), "gunluk": ""}
        time.sleep(0.3)
    okuyucu.join(5)
    sure = time.time() - t0
    return {"sure_sn": round(sure, 1), "cikis": p.returncode, "tepe_gb": round(tepe / 1e9, 2),
            "cpu_sn": round(sum(cpu.values()), 1), "gunluk": "".join(cikti)}


def cekim(cid: str, cikti: Path) -> dict:
    # "S2_k07" = S2 çekiminin 7. kopyası: aynı iş, farklı tohum (uzun video yük testi; gerçek render işi)
    taban, _, kopya = cid.partition("_k")
    is_ = json.loads((BURASI / "isler" / f"{taban}.json").read_text())
    if kopya:
        is_["tohum"] = 1000 + int(kopya)
    is_yolu = cikti / f"{cid}.is.json"
    cikti.mkdir(parents=True, exist_ok=True)
    is_yolu.write_text(json.dumps(is_, ensure_ascii=False))
    kare = round(is_["cekim"]["sure_sn"] * is_["fps"])
    avi = cikti / f"{cid}.avi"
    mp4 = cikti / f"{cid}.mp4"
    r = calistir(["xvfb-run", "-a", "-s", "-screen 0 1280x1024x24", GODOT, "--path", str(PROJE),
                  "--rendering-driver", "opengl3", "res://sahneler/cekim.tscn", "--write-movie", str(avi),
                  "--fixed-fps", str(FPS), "--quit-after", str(kare), "--", str(is_yolu)], 3 * 3600)
    hatalar = [s for s in r["gunluk"].splitlines() if "ERROR" in s]
    sonuc = {"cekim": cid, "kare": kare, "karakter": len(is_["cekim"].get("karakterler", [])),
             "render_sn": r["sure_sn"], "render_cikis": r["cikis"], "render_tepe_gb": r["tepe_gb"],
             "render_cpu_sn": r["cpu_sn"], "ort_cekirdek": round(r["cpu_sn"] / max(r["sure_sn"], 0.1), 2),
             "kare_basina_sn": round(r["sure_sn"] / kare, 2), "godot_hata": hatalar[:10]}
    if r["cikis"] != 0 or not avi.exists():
        sonuc["durum"] = "HATA"
        return sonuc
    k = calistir(["ffmpeg", "-y", "-loglevel", "error", "-i", str(avi), "-c:v", "libx264", "-preset", "veryfast",
                  "-crf", "18", "-pix_fmt", "yuv420p", "-an", str(mp4)], 3600)
    sonuc["kodlama_sn"] = k["sure_sn"]
    sonuc["ara_avi_mb"] = round(avi.stat().st_size / 1e6, 1)
    avi.unlink()
    pr = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries",
                         "stream=width,height,nb_read_frames", "-of", "json", str(mp4)], capture_output=True, text=True)
    akis = json.loads(pr.stdout)["streams"][0]
    sonuc["uretilen_kare"] = int(akis.get("nb_read_frames", 0))
    sonuc["cozunurluk"] = f"{akis['width']}x{akis['height']}"
    sonuc["mp4_mb"] = round(mp4.stat().st_size / 1e6, 2)
    sonuc["durum"] = "TAMAM" if sonuc["uretilen_kare"] == kare and not hatalar else "HATA"
    return sonuc


def main() -> int:
    is_ad, cikti, cekimler = sys.argv[1], Path(sys.argv[2]), sys.argv[3:]
    cikti.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    rapor = {"is": is_ad, "makine": {
        "cpu": open("/proc/cpuinfo").read().split("model name")[1].split("\n")[0].strip(": \t"),
        "cekirdek": os.cpu_count(), "bellek_gb": round(psutil.virtual_memory().total / 1e9, 1)},
        "kurulum_sn": float(os.environ.get("KURULUM_SN", "nan")),
        "baslangic_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "cekimler": []}
    for cid in cekimler:
        s = cekim(cid, cikti)
        print(json.dumps({k: v for k, v in s.items() if k != "godot_hata"}, ensure_ascii=False), flush=True)
        rapor["cekimler"].append(s)
    rapor["is_render_toplam_sn"] = round(time.time() - t0, 1)
    rapor["bitis_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    rapor["basarili"] = all(c["durum"] == "TAMAM" for c in rapor["cekimler"])
    (cikti / f"olcum_{is_ad}.json").write_text(json.dumps(rapor, ensure_ascii=False, indent=1))
    return 0 if rapor["basarili"] else 1


if __name__ == "__main__":
    sys.exit(main())
