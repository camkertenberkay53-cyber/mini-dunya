"""Faz 5.1 altyapı deneyi: paralel işlerden gelen çekim MP4'lerini plan sırasıyla birleştirir ve kurgu
aşamasının son kodlamasını (ses karışımı + yakılı altyazı) motor/uretim/kurgu.py ile aynı ayarlarla yapar.

Kullanım: python3 birlestir.py <mp4_klasoru> <cikti_klasoru>
Ölçülenler: birleştirme (concat) süresi, son kodlama süresi, toplam kare, süre, dosya boyutu.
Ses karışımı burada yeniden üretilmez: pilotun ölçülmüş karışımı (karisim.m4a) kullanılır; bu yalnızca kurgu
kodlama maliyetini ölçmek içindir.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

BURASI = Path(__file__).resolve().parent
REPO = BURASI.parents[2]


PILOT_SN = 35.05


def ses_ve_altyazi(tekrar: int, cikti: Path) -> tuple[Path, Path]:
    """Uzun video yük testi için pilot ses karışımını ve altyazıyı `tekrar` kez art arda dizer (gerçek kodlama yükü)."""
    kaynak_ses, kaynak_ass = BURASI / "kurgu" / "karisim.m4a", BURASI / "kurgu" / "altyazi.ass"
    if tekrar <= 1:
        return kaynak_ses, kaynak_ass
    liste = cikti / "ses_liste.txt"
    liste.write_text("".join(f"file '{kaynak_ses}'\n" for _ in range(tekrar)))
    ses = cikti / "ses_uzun.m4a"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(liste), "-c", "copy",
                    str(ses)], check=True)
    satirlar = kaynak_ass.read_text().splitlines()
    ust = [s for s in satirlar if not s.startswith("Dialogue:")]
    olaylar = [s for s in satirlar if s.startswith("Dialogue:")]

    def kaydir(z: str, ek: float) -> str:
        h, m, sn = z.split(":")
        t = int(h) * 3600 + int(m) * 60 + float(sn) + ek
        return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"
    yeni = []
    for k in range(tekrar):
        for o in olaylar:
            a = o.split(",", 3)
            a[1], a[2] = kaydir(a[1], k * PILOT_SN), kaydir(a[2], k * PILOT_SN)
            yeni.append(",".join(a))
    ass = cikti / "altyazi_uzun.ass"
    ass.write_text("\n".join(ust + yeni) + "\n")
    return ses, ass


def main() -> int:
    kaynak, cikti = Path(sys.argv[1]), Path(sys.argv[2])
    cikti.mkdir(parents=True, exist_ok=True)
    kosu = json.loads((BURASI / "kosu.json").read_text())
    sira = kosu.get("sira") or [o["cekim"] for o in json.loads((BURASI / "isler" / "ozet.json").read_text())]
    tekrar = int(kosu.get("ses_tekrar", 1))
    eksik = [c for c in sira if not (kaynak / f"{c}.mp4").exists()]
    if eksik:
        (cikti / "birlestirme.json").write_text(json.dumps({"durum": "HATA", "eksik_cekim": eksik}, ensure_ascii=False))
        print("EKSİK ÇEKİM:", eksik)
        return 1
    liste = cikti / "klipler.txt"
    liste.write_text("".join(f"file '{(kaynak / f'{c}.mp4').resolve()}'\n" for c in sira))
    t0 = time.time()
    goruntu = cikti / "goruntu.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(liste), "-c", "copy",
                    str(goruntu)], check=True)
    concat_sn = time.time() - t0
    t1 = time.time()
    final = cikti / "pilot.mp4"
    fonts = REPO / "assets" / "fonts"
    ses, ass = ses_ve_altyazi(tekrar, cikti)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(goruntu), "-i", str(ses),
                    "-map", "0:v:0", "-map", "1:a:0",
                    "-vf", f"ass={ass}:fontsdir={fonts}", "-c:v", "libx264", "-preset",
                    "medium", "-crf", "19", "-maxrate", "12M", "-bufsize", "24M", "-profile:v", "high", "-pix_fmt",
                    "yuv420p", "-movflags", "+faststart", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
                    "-shortest", str(final)], check=True)
    kodlama_sn = time.time() - t1
    pr = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries",
                         "stream=nb_read_frames,width,height", "-show_entries", "format=duration", "-of", "json",
                         str(final)], capture_output=True, text=True)
    j = json.loads(pr.stdout)
    sonuc = {"durum": "TAMAM", "concat_sn": round(concat_sn, 1), "son_kodlama_sn": round(kodlama_sn, 1),
             "birlestirme_toplam_sn": round(concat_sn + kodlama_sn, 1),
             "kare": int(j["streams"][0].get("nb_read_frames", 0)),
             "cozunurluk": f"{j['streams'][0]['width']}x{j['streams'][0]['height']}",
             "sure_sn": round(float(j["format"]["duration"]), 2), "mb": round(final.stat().st_size / 1e6, 1),
             "cekirdek": os.cpu_count()}
    for i, an in enumerate((1.5, 12.0, 30.0, sonuc["sure_sn"] - 3)):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", str(an), "-i", str(final), "-frames:v", "1",
                        "-vf", "scale=540:-1", str(cikti / f"kare_{i}.jpg")])
    (cikti / "birlestirme.json").write_text(json.dumps(sonuc, ensure_ascii=False, indent=1))
    print(json.dumps(sonuc, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
