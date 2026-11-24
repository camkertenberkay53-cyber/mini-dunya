"""Chatterbox + metin hazırlama + kalite kontrol + sınırlı yeniden üretim (deneysel, Faz 5.1 P0).

Kullanım: python3 uret_qc.py <grup: test|pilot> <cikti_klasoru> [--ham]
  --ham: metin hazırlama YOK, yeniden üretim YOK (önceki durumu yeniden üretmek için kontrol grubu)
Akış: her cümle için en fazla MAKS_DENEME üretim. Deneme 1 varsayılan ayarlar; sonrakiler farklı tohum ve daha düşük
sıcaklık. Her deneme kalite kontrolünden geçer; KRİTİK bulgusu olmayan ilk GEÇTİ sonucu kabul edilir, yoksa en iyi
deneme saklanır ve cümle FAIL (kritik kalmışsa) ya da İNCELEME (yalnız uyarı kalmışsa) olarak işaretlenir.
Toplu karar: herhangi bir FAIL → üretim FAIL; FAIL yok ama İNCELEME var → İNCELEME_GEREKLİ; hepsi GEÇTİ → GEÇTİ.
Filigran (Perth) dokunulmadan kalır; her kabul edilen dosyada varlığı ayrıca doğrulanır.
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
sys.path.insert(0, str(BURASI))
from kalite import denetle, harf_hizi  # noqa: E402
from metin import hazirla  # noqa: E402

MAKS_DENEME = 4
AYAR = [dict(tohum=1, temperature=0.8, cfg_weight=0.5), dict(tohum=2, temperature=0.8, cfg_weight=0.5),
        dict(tohum=3, temperature=0.6, cfg_weight=0.5), dict(tohum=4, temperature=0.5, cfg_weight=0.6)]
VARSAYILAN_HIZ = 13.0   # harf/sn; toplu medyan hesaplanana kadar


def wav_yaz(yol: Path, x: np.ndarray, sr: int) -> None:
    with wave.open(str(yol), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("int16").tobytes())


class ASR:
    def __init__(self):
        from faster_whisper import WhisperModel
        self.m = WhisperModel("medium", device="cpu", compute_type="int8", cpu_threads=os.cpu_count())

    def __call__(self, yol: Path) -> dict:
        segs, _ = self.m.transcribe(str(yol), language="tr", beam_size=5, condition_on_previous_text=False,
                                    word_timestamps=True, vad_filter=False)
        kel, metin = [], []
        for s in segs:
            metin.append(s.text.strip())
            for w in s.words or []:
                kel.append({"kelime": w.word.strip(), "bas": w.start, "son": w.end, "olasilik": w.probability})
        return {"kelimeler": kel, "metin": " ".join(metin)}


def main() -> int:
    grup, cikti = sys.argv[1], Path(sys.argv[2])
    ham = "--ham" in sys.argv
    cikti.mkdir(parents=True, exist_ok=True)
    cumleler = json.loads((BURASI.parent / "cumleler.json").read_text())[grup]
    import torch
    import perth
    torch.set_num_threads(os.cpu_count())
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    t0 = time.time()
    tts = ChatterboxMultilingualTTS.from_pretrained(device="cpu")
    asr = ASR()
    wm = perth.PerthImplicitWatermarker()
    yukleme = time.time() - t0
    pr = psutil.Process()
    tepe = pr.memory_info().rss
    hazir = [(m,) + (hazirla(m) if not ham else (m, [], [])) for m in cumleler]

    def uret(i: int, d: int) -> dict:
        orijinal, konusma, uyari_m, ozel = hazir[i]
        a = AYAR[d]
        torch.manual_seed(a["tohum"])
        t = time.time()
        w = tts.generate(konusma, language_id="tr", temperature=a["temperature"], cfg_weight=a["cfg_weight"])
        g = time.time() - t
        x = w.squeeze(0).numpy().astype(np.float32)
        yol = cikti / f"{grup}_{i:02d}_d{d + 1}.wav"
        wav_yaz(yol, x, tts.sr)
        t = time.time()
        a_ = asr(yol)
        return {"deneme": d + 1, "ayar": a, "dosya": yol.name, "uretim_sn": round(g, 1), "asr_sn": round(time.time() - t, 1),
                "x": x, "asr": a_}

    sonuc = []
    # Aşama 1: tüm cümlelerin ilk denemesi (toplu konuşma hızı medyanı için)
    ilk = [uret(i, 0) for i in range(len(cumleler))]
    tepe = max(tepe, pr.memory_info().rss)
    hizlar = [harf_hizi(r["x"], tts.sr, hazir[i][1]) for i, r in enumerate(ilk)]
    hizlar = [h for h in hizlar if h]
    hiz = float(np.median(hizlar)) if len(hizlar) >= 5 else VARSAYILAN_HIZ
    for i, r0 in enumerate(ilk):
        orijinal, konusma, uyari_m, ozel = hazir[i]
        denemeler = []
        r = r0
        d = 0
        while True:
            q = denetle(r["x"], tts.sr, konusma, ozel, r["asr"], hiz)
            denemeler.append({k: v for k, v in r.items() if k not in ("x", "asr")} | {"qc": q})
            if q["durum"] == "GECTI" or ham or d + 1 >= MAKS_DENEME:
                break
            d += 1
            r = uret(i, d)
            tepe = max(tepe, pr.memory_info().rss)
        en_iyi = max(denemeler, key=lambda z: (z["qc"]["durum"] != "KRITIK", z["qc"]["puan"]))
        durum = {"GECTI": "GECTI", "UYARI": "INCELEME", "KRITIK": "FAIL"}[en_iyi["qc"]["durum"]]
        if uyari_m:
            durum = "FAIL" if durum == "FAIL" else "INCELEME"
        import soundfile as sf
        xs, ssr = sf.read(str(cikti / en_iyi["dosya"]), dtype="float32")
        filigran = float(np.mean(wm.get_watermark(xs, sample_rate=ssr)))
        sonuc.append({"no": i, "orijinal": orijinal, "konusma": konusma, "metin_uyarilari": uyari_m,
                      "durum": durum, "secilen": en_iyi["dosya"], "deneme_sayisi": len(denemeler),
                      "filigran": round(filigran, 3), "denemeler": denemeler})
        print(i, durum, len(denemeler), en_iyi["qc"]["puan"], en_iyi["qc"]["kritik"], en_iyi["qc"]["uyari"], flush=True)
    toplu = "FAIL" if any(s["durum"] == "FAIL" for s in sonuc) else (
        "INCELEME_GEREKLI" if any(s["durum"] == "INCELEME" for s in sonuc) else "GECTI")
    rapor = {"grup": grup, "mod": "ham" if ham else "hazirla+qc+yeniden", "maks_deneme": 1 if ham else MAKS_DENEME,
             "toplu_durum": toplu, "harf_hizi_medyan": round(hiz, 2), "yukleme_sn": round(yukleme, 1),
             "toplam_sn": round(time.time() - t0, 1), "tepe_bellek_gb": round(tepe / 1e9, 2),
             "uretim_toplam_sn": round(sum(dn["uretim_sn"] for s in sonuc for dn in s["denemeler"]), 1),
             "asr_toplam_sn": round(sum(dn["asr_sn"] for s in sonuc for dn in s["denemeler"]), 1),
             "insan_incelemesi": [{"no": s["no"], "orijinal": s["orijinal"], "durum": s["durum"],
                                   "neden": next(d for d in s["denemeler"] if d["dosya"] == s["secilen"])["qc"]["kritik"]
                                   + next(d for d in s["denemeler"] if d["dosya"] == s["secilen"])["qc"]["uyari"]
                                   + s["metin_uyarilari"]} for s in sonuc if s["durum"] != "GECTI"],
             "cumleler": sonuc}
    (cikti / f"qc_{grup}_{'ham' if ham else 'qc'}.json").write_text(json.dumps(rapor, ensure_ascii=False, indent=1))
    print("TOPLU:", toplu)
    return 0


if __name__ == "__main__":
    sys.exit(main())
