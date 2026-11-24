"""M10 + M12 + M13 — Kurgu: denetlenmiş çekim planından videoyu üretir ve ÖLÇER.

python3 -m motor.uretim.kurgu <klasor>   (klasörde senaryo.json ve uretim_hatti'nın yazdığı cekim_plani.json)

Akış:
1. Plan denetimi yeniden çalışır; hata varsa üretim yok.
2. Her 3D çekim ayrı render edilir (render.py: ölçüm + önbellek). Çekim başına süre ve bellek kaydedilir.
3. Çekimler kesmeyle uç uca eklenir (yeniden kodlama yok).
4. Ses: ölçülmüş seslendirme dosyaları zaman çizelgesindeki yerlerine konur; altına kodla üretilmiş (telifsiz)
   rüzgâr ve isteğe bağlı davul eklenir, konuşma sırasında kısılır. Hepsi eski botun mevcut fonksiyonlarıdır.
5. Altyazı (cümle cümle) ve ekran yazıları (metin_katmani) ASS katmanı olarak basılır.
6. Kalite kontrol: eski botun teknik kontrolü (çözünürlük, fps, süre, siyah/donuk kare, ses seviyesi) + her cümlenin
   seslendirmesinin yerel Whisper ile yazıya çevrilip metinle karşılaştırılması.
Konuya özel hiçbir şey yoktur: davul gibi ses seçimleri cümle amacına göre (kurallar/kurgu.yaml) yapılır.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from motor import ayar
from motor.uretim import plan_denetim, render, seslendirme, veri

SR = 48000


def _wav(yol: str) -> np.ndarray:
    x, sr = sf.read(yol, dtype="float32")
    if x.ndim > 1:
        x = x.mean(axis=1)
    if sr != SR:
        from scipy.signal import resample_poly
        g = math.gcd(sr, SR)
        x = resample_poly(x, SR // g, sr // g).astype(np.float32)
    return x


def _ses_karisimi(plan: dict, senaryo: dict, sureler: dict, cikti: Path) -> dict:
    from kaos.sinema import motor as sinema
    k = veri.kural("kurgu")
    cz = plan["ses"]["cizelge"]
    toplam = plan["ses"]["toplam_sn"]
    n = int(math.ceil(toplam * SR))
    anlatim = np.zeros(n, np.float32)
    for z in cz:
        x = _wav(sureler[z["cumle"]]["wav"])
        x = x / (np.abs(x).max() + 1e-6) * 0.89
        b = int(z["ses_bas_sn"] * SR)
        anlatim[b:b + len(x)] += x[: max(0, n - b)]
    # alt katman: kodla üretilmiş ses (eski botun _sentez'i 24 kHz üretir; 48 kHz'e çevrilir)
    alt = np.zeros(n, np.float32)
    from scipy.signal import resample_poly
    def sentez(tip, sure, tohum):
        y = sinema._sentez(tip, sure, tohum)
        return resample_poly(y, 2, 1).astype(np.float32) if sinema.SR * 2 == SR else y
    alt += sentez("ruzgar", toplam, 7)[:n] * k["ruzgar_duzeyi"]
    amac = {c["id"]: c.get("amac") for c in senaryo["cumleler"]}
    for z in cz:
        if amac.get(z["cumle"]) in k["davul_amaclari"]:
            b, s = int(z["goruntu_bas_sn"] * SR), z["goruntu_son_sn"] - z["goruntu_bas_sn"]
            y = sentez("davul", s, 11)
            alt[b:b + len(y)] += y[: max(0, n - b)] * k["davul_duzeyi"]
    aktif = np.convolve((np.abs(anlatim) > 0.02).astype(np.float32), np.ones(int(0.25 * SR)), "same") > 0
    zarf = np.convolve(aktif.astype(np.float32), np.hanning(int(0.8 * SR)) / np.hanning(int(0.8 * SR)).sum(), "same")
    alt *= 1 - k["konusmada_kisma"] * np.clip(zarf, 0, 1)
    mix = anlatim + alt
    tepe = float(np.abs(mix).max())
    if tepe > 0.95:
        mix *= 0.95 / tepe
    wav = cikti / "karisim.wav"
    sf.write(wav, mix, SR)
    return {"wav": str(wav), "tepe": round(min(tepe, 0.95), 3), "sure_sn": round(n / SR, 3)}


def _altyazi(plan: dict, senaryo: dict, cikti: Path) -> Path:
    from kaos.sinema import motor as sinema
    W, H = plan["cozunurluk"]
    metin = {c["id"]: c["metin"] for c in senaryo["cumleler"]}
    satirlar = []
    for z in plan["ses"]["cizelge"]:
        satirlar += sinema.altyazi_parcala(metin[z["cumle"]], z["ses_bas_sn"], z["ses_sure_sn"])
    ass = cikti / "altyazi.ass"
    sinema.ass_yaz(satirlar, str(ass), W, H)
    # ekran yazıları (tarih, yer): çekim boyunca üstte, eski botun "Kanca" biçemiyle
    t = 0.0
    with open(ass, "a", encoding="utf-8") as f:
        for c in plan["cekimler"]:
            if c.get("metin_katmani"):
                f.write(f"Dialogue: 1,{sinema._ass_zaman(t + 0.1)},{sinema._ass_zaman(t + c['sure_sn'] - 0.05)},Kanca,,0,0,0,,"
                        f"{{\\fad(150,150)}}{c['metin_katmani']}\n")
            t += c["sure_sn"]
    (cikti / "altyazi.json").write_text(json.dumps([{"bas": round(a, 2), "son": round(b, 2), "metin": m} for a, b, m in satirlar],
                                                   ensure_ascii=False, indent=1))
    return ass


def _dinle(sureler: dict, senaryo: dict) -> dict:
    """Her cümlenin seslendirmesi yerel Whisper ile yazıya çevrilir; okunuş metniyle benzerliği ölçülür."""
    from kaos.sinema import dinle
    r = {}
    for c in senaryo["cumleler"]:
        x, sr = sf.read(sureler[c["id"]]["wav"], dtype="float32")
        if sr != 16000:
            from scipy.signal import resample_poly
            g = math.gcd(sr, 16000)
            x = resample_poly(x, 16000 // g, sr // g).astype(np.float32)
        duyulan = dinle.yaziya_cevir(x, 16000)
        r[c["id"]] = {"beklenen": sureler[c["id"]]["metin"], "duyulan": duyulan,
                      "benzerlik": round(dinle.benzerlik(sureler[c["id"]]["metin"], duyulan), 3)}
    return r


def uret(klasor: Path) -> dict:
    t0 = time.time()
    plan_yolu = klasor / "cekim_plani.json"
    plan = json.loads(plan_yolu.read_text())
    senaryo = json.loads((klasor / "senaryo.json").read_text())
    den = plan_denetim.denetle(plan)
    if not den["gecti"]:
        return {"durum": "REDDEDİLDİ", "hatalar": den["hatalar"]}
    cikti = ayar.ONBELLEK / "kurgu" / plan["konu"]
    shutil.rmtree(cikti, ignore_errors=True)
    cikti.mkdir(parents=True)
    cekimler, klipler = [], []
    for c in plan["cekimler"]:
        t1 = time.time()
        r = render.render(str(plan_yolu), c["id"])
        if r["durum"] != "TAMAM":
            return {"durum": "HATA", "cekim": c["id"], "render": r}
        o = r["olculen"]
        cekimler.append({"cekim": c["id"], "kare": o["kare"], "uretilen_kare": o["uretilen_kare"], "render_sn": o["render_sn"],
                         "kare_basina_sn": o["kare_basina_sn_acilis_dahil"], "tepe_bellek_gb": o["render_tepe_bellek_gb"],
                         "karakter": o["karakter"], "cevre": o["cevre_varligi"], "onbellekten": r.get("onbellekten", False),
                         "duvar_sn": round(time.time() - t1, 1)})
        klipler.append(r["video"])
        print(f"ÇEKİM {c['id']}: {o['kare']} kare, {o['render_sn']} sn, {o['render_tepe_bellek_gb']} GB", flush=True)
    t_render = time.time() - t0
    t2 = time.time()
    liste = cikti / "klipler.txt"
    liste.write_text("".join(f"file '{k}'\n" for k in klipler))
    goruntu = cikti / "goruntu.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(liste), "-c", "copy", str(goruntu)], check=True)
    sureler = seslendirme.olc(senaryo["cumleler"])
    ses = _ses_karisimi(plan, senaryo, sureler, cikti)
    ass = _altyazi(plan, senaryo, cikti)
    from kaos import paths
    final = cikti / f"{plan['konu']}.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(goruntu), "-i", ses["wav"],
                    "-vf", f"ass={ass}:fontsdir={os.path.dirname(paths.FONT)}", "-c:v", "libx264", "-preset", "medium",
                    "-crf", "19", "-maxrate", "12M", "-bufsize", "24M", "-profile:v", "high", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2", "-shortest", str(final)], check=True)
    t_kurgu = time.time() - t2
    from kaos.sinema import motor as sinema
    kk = sinema.kalite_kontrol(str(final), plan["cozunurluk"][0], plan["cozunurluk"][1], plan["fps"], plan["ses"]["toplam_sn"])
    pr = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries",
                         "stream=nb_read_frames,r_frame_rate", "-of", "json", str(final)], capture_output=True, text=True)
    akis = json.loads(pr.stdout)["streams"][0]
    dinleme = _dinle(sureler, senaryo)
    sonuc = {
        "durum": "TAMAM" if kk.get("gecti") else "KALİTE KONTROLDEN KALDI",
        "video": str(final),
        "makine": {"cpu": open("/proc/cpuinfo").read().split("model name")[1].split("\n")[0].strip(": \t"), "cekirdek": os.cpu_count()},
        "olculen": {
            "toplam_duvar_sn": round(time.time() - t0, 1),
            "render_toplam_sn": round(sum(c["render_sn"] for c in cekimler), 1),
            "render_asamasi_duvar_sn": round(t_render, 1),
            "kurgu_sn": round(t_kurgu, 1),
            "kare_plan": sum(c["kare"] for c in cekimler),
            "kare_video": int(akis.get("nb_read_frames", 0)),
            "fps": akis.get("r_frame_rate"),
            "tepe_bellek_gb": max(c["tepe_bellek_gb"] for c in cekimler),
            "video_mb": round(final.stat().st_size / 1e6, 2),
        },
        "cekimler": cekimler,
        "ses": ses,
        "kalite_kontrol": kk,
        "dinleme": dinleme,
        "seslendirme_motoru": next(iter(sureler.values()))["motor"],
    }
    (cikti / "uretim_raporu.json").write_text(json.dumps(sonuc, ensure_ascii=False, indent=1))
    return sonuc


if __name__ == "__main__":
    r = uret(Path(sys.argv[1]))
    print(json.dumps({k: v for k, v in r.items() if k not in ("cekimler", "dinleme")}, ensure_ascii=False, indent=1))
    sys.exit(0 if r["durum"] == "TAMAM" else 1)
