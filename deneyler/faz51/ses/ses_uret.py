"""Faz 5.1 ses P0 deneyi: bir TTS motoruyla sabit 10 test cümlesini ve 9 pilot cümlesini üretir, gerçek ölçüm kaydeder.

Kullanım: python3 ses_uret.py <motor> <cikti_klasoru>
  motor: piper_fahrettin | piper_fettah | piper_dfki | chatterbox
Ölçülenler: model yükleme süresi, cümle başına üretim süresi, RTF (üretim süresi / ses süresi), CPU saniyesi,
tepe bellek, ses süresi, WAV boyutu. Değerlendirme (anlaşılırlık, filigran) degerlendir.py'de yapılır.
Piper sesleri yalnızca geliştirme/test karşılaştırması içindir (ticari onaylı değil).
"""
from __future__ import annotations

import json
import os
import sys
import time
import wave
from pathlib import Path

import numpy as np
import psutil

BURASI = Path(__file__).resolve().parent
PR = psutil.Process()


def wav_yaz(yol: Path, x: np.ndarray, sr: int) -> None:
    with wave.open(str(yol), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("int16").tobytes())


def cpu() -> float:
    c = PR.cpu_times()
    return c.user + c.system


def piper(ses: str):
    import sherpa_onnx
    d = Path(os.environ.get("PIPER_DIZIN", "/tmp/piper")) / f"vits-piper-tr_TR-{ses}-medium"
    tts = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
        vits=sherpa_onnx.OfflineTtsVitsModelConfig(model=str(d / f"tr_TR-{ses}-medium.onnx"), tokens=str(d / "tokens.txt"),
                                                   data_dir=str(d / "espeak-ng-data")), num_threads=os.cpu_count())))

    def uret(metin: str):
        a = tts.generate(metin, sid=0, speed=1.0)
        return np.array(a.samples, dtype=np.float32), a.sample_rate
    return uret


def chatterbox():
    import torch
    torch.set_num_threads(os.cpu_count())
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    m = ChatterboxMultilingualTTS.from_pretrained(device="cpu")

    def uret(metin: str):
        torch.manual_seed(1)
        w = m.generate(metin, language_id="tr")   # varsayılan konuşmacı koşulu; filigran üretici içinde uygulanır
        return w.squeeze(0).numpy().astype(np.float32), m.sr
    return uret


def main() -> int:
    motor, cikti = sys.argv[1], Path(sys.argv[2])
    cikti.mkdir(parents=True, exist_ok=True)
    c = json.loads((BURASI / "cumleler.json").read_text())
    t0, c0 = time.time(), cpu()
    uret = chatterbox() if motor == "chatterbox" else piper(motor.split("_", 1)[1])
    rapor = {"motor": motor, "makine": {
        "cpu": open("/proc/cpuinfo").read().split("model name")[1].split("\n")[0].strip(": \t"),
        "cekirdek": os.cpu_count(), "bellek_gb": round(psutil.virtual_memory().total / 1e9, 1)},
        "yukleme_sn": round(time.time() - t0, 1), "yukleme_cpu_sn": round(cpu() - c0, 1), "test": [], "pilot": []}
    tepe = PR.memory_info().rss
    for grup in ("test", "pilot"):
        for i, metin in enumerate(c[grup]):
            t, c1 = time.time(), cpu()
            x, sr = uret(metin)
            g = time.time() - t
            tepe = max(tepe, PR.memory_info().rss)
            dosya = cikti / f"{motor}_{grup}_{i:02d}.wav"
            wav_yaz(dosya, x, sr)
            sure = len(x) / sr
            r = {"no": i, "metin": metin, "uretim_sn": round(g, 2), "cpu_sn": round(cpu() - c1, 1), "ses_sn": round(sure, 2),
                 "rtf": round(g / max(sure, 0.01), 3), "wav_kb": round(dosya.stat().st_size / 1024, 1), "sr": sr,
                 "dosya": dosya.name}
            rapor[grup].append(r)
            print(grup, json.dumps({k: v for k, v in r.items() if k != "metin"}), flush=True)
    rapor["tepe_bellek_gb"] = round(tepe / 1e9, 2)
    for grup in ("test", "pilot"):
        rapor[f"{grup}_toplam_uretim_sn"] = round(sum(r["uretim_sn"] for r in rapor[grup]), 1)
        rapor[f"{grup}_toplam_ses_sn"] = round(sum(r["ses_sn"] for r in rapor[grup]), 1)
    rapor["pilot_anlatim_toplam_sn_yukleme_dahil"] = round(rapor["yukleme_sn"] + rapor["pilot_toplam_uretim_sn"], 1)
    (cikti / f"uretim_{motor}.json").write_text(json.dumps(rapor, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
