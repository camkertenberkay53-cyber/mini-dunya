"""Render ölçümü: ölçüm sahnesini 1080x1920 30 fps render eder, gerçek süreyi ve kaynak kullanımını kaydeder.

python3 -m motor.olcum.render_olc <ortam_adi> [kare_sayisi=180]
Çıktı: motor/olcum/sonuc_<ortam_adi>.json

Ölçülenler: içe aktarma süresi, kare başına render süresi, tepe bellek, disk, H.264 kodlama süresi.
Tahmin edilenler (açıkça "tahmin" diye işaretli): 50 sn'lik bir Shorts ve günde 2 Shorts için toplam süre.
Ölçüm sahnesi: 15 tam animasyonlu asker, atlı, 420 uzak asker, 9000 ot, toz, sis (cinematic_test_2 ile aynı yük).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from motor import ayar

BURASI = Path(__file__).resolve().parent
FPS = 30
SHORTS_SN = 50


def _calistir(komut: list[str], zaman_asimi: int) -> tuple[float, int, str]:
    """Komutu çalıştırır; süreyi ve süreç ağacının tepe belleğini (kB) ölçer."""
    import psutil
    t0 = time.time()
    p = subprocess.Popen(komut, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    ana = psutil.Process(p.pid)
    tepe = 0
    cikti: list[str] = []
    import threading
    okuyucu = threading.Thread(target=lambda: cikti.append(p.stdout.read()), daemon=True)
    okuyucu.start()
    while p.poll() is None:
        try:
            rss = sum(c.memory_info().rss for c in [ana] + ana.children(recursive=True))
            tepe = max(tepe, rss)
        except psutil.Error:
            pass
        if time.time() - t0 > zaman_asimi:
            p.kill()
            raise SystemExit(f"ZAMAN AŞIMI: {' '.join(komut[:4])}")
        time.sleep(0.5)
    okuyucu.join(5)
    sure = time.time() - t0
    metin = "".join(cikti)
    if p.returncode != 0:
        print(metin[-3000:])
        raise SystemExit(f"KOMUT BAŞARISIZ ({p.returncode}): {' '.join(komut[:4])}")
    return sure, tepe // 1024, metin


def olc(ortam: str, kare: int = 180) -> dict:
    proje = str(ayar.GODOT_PROJE)
    is_klasoru = ayar.ONBELLEK / "olcum"
    shutil.rmtree(is_klasoru, ignore_errors=True)
    is_klasoru.mkdir(parents=True)
    xvfb = ["xvfb-run", "-a", "-s", "-screen 0 1280x1024x24"]

    ice_sn, ice_ram, _ = _calistir([ayar.GODOT, "--headless", "--path", proje, "--import"], 1800)
    def render(n: int, avi: Path):
        return _calistir(xvfb + [ayar.GODOT, "--path", proje, "--rendering-driver", "opengl3",
                                 "res://sahneler/olcum.tscn", "--write-movie", str(avi),
                                 "--fixed-fps", str(FPS), "--quit-after", str(n)], 7200)

    # Sabit açılış maliyeti (sahne kurulumu, shader derleme) kare maliyetinden ayrı ölçülür.
    acilis_sn, _, _ = render(2, is_klasoru / "acilis.avi")
    avi = is_klasoru / "olcum.avi"
    rnd_sn, rnd_ram, cikti = render(kare, avi)
    mp4 = is_klasoru / "olcum.mp4"
    kod_sn, kod_ram, _ = _calistir(["ffmpeg", "-y", "-loglevel", "error", "-i", str(avi), "-c:v", "libx264", "-preset", "veryfast",
                                    "-crf", "20", "-maxrate", "12M", "-bufsize", "24M", "-pix_fmt", "yuv420p", str(mp4)], 3600)
    pr = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries",
                         "stream=width,height,nb_read_frames", "-of", "json", str(mp4)], capture_output=True, text=True)
    akis = json.loads(pr.stdout)["streams"][0]
    kare_sn = max(0.0, rnd_sn - acilis_sn) / max(1, kare - 2)
    shorts_kare = SHORTS_SN * FPS
    shorts_dk = (acilis_sn + kare_sn * shorts_kare + kod_sn / kare * shorts_kare) / 60
    sonuc = {
        "ortam": ortam,
        "tarih": time.strftime("%Y-%m-%d %H:%M"),
        "cpu": open("/proc/cpuinfo").read().split("model name")[1].split("\n")[0].strip(": \t"),
        "cekirdek": os.cpu_count(),
        "bellek_gb": round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9, 1),
        "olculen": {
            "ice_aktarma_sn": round(ice_sn, 1),
            "render_kare": kare,
            "render_cozunurluk": f"{akis['width']}x{akis['height']}",
            "uretilen_kare": int(akis.get("nb_read_frames", 0)),
            "render_sn": round(rnd_sn, 1),
            "acilis_sn": round(acilis_sn, 1),
            "kare_basina_sn": round(kare_sn, 2),
            "render_tepe_bellek_gb": round(rnd_ram / 1e6, 2),
            "kodlama_sn": round(kod_sn, 1),
            "ara_dosya_avi_mb": round(avi.stat().st_size / 1e6, 1),
            "mp4_mb": round(mp4.stat().st_size / 1e6, 2),
        },
        "tahmin": {
            "aciklama": "Ölçülen kare süresinin 50 sn x 30 fps'e doğrusal uzatılması. Sahne yükü değişirse değişir.",
            "shorts_50sn_dk": round(shorts_dk, 1),
            "gunde_2_shorts_dk": round(2 * shorts_dk, 1),
            "shorts_ara_dosya_gb": round(avi.stat().st_size / kare * shorts_kare / 1e9, 2),
        },
    }
    if sonuc["olculen"]["uretilen_kare"] != kare or akis["width"] != 1080 or akis["height"] != 1920:
        sonuc["hata"] = "beklenen kare sayısı ya da çözünürlük tutmadı"
    (BURASI / f"sonuc_{ortam}.json").write_text(json.dumps(sonuc, ensure_ascii=False, indent=1))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{kare / FPS / 2:.2f}", "-i", str(mp4), "-frames:v", "1", str(BURASI / f"kare_{ortam}.jpg")])
    return sonuc


if __name__ == "__main__":
    print(json.dumps(olc(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 180), ensure_ascii=False, indent=1))
