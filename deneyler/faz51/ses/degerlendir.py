"""Faz 5.1 ses P0 deneyi: üretilen sesleri aynı makinede, aynı yöntemle değerlendirir.

Kullanım: python3 degerlendir.py <wav_ve_json_klasoru> <cikti_klasoru>
Ölçülenler (hepsi otomatik, gerçek ölçüm):
- Anlaşılırlık: faster-whisper (medium, int8, CPU, tr) dökümü; sayılar yazıya çevrilerek normalleştirilmiş WER ve CER.
- Kelime atlama: hizalamadaki silinen kelimeler; telaffuz/anlaşılırlık hatası: yer değiştiren kelime çiftleri.
- Özel isim doğruluğu: test cümlelerindeki tarihî isimlerin dökümde tanınması.
- Filigran: Perth (resemble-perth) dedektörü; ham WAV, AAC 128k ve MP3 64k gidiş-dönüşü sonrası.
- Tonlama vekil ölçüsü: F0 standart sapması (yarım ton) ve konuşma hızı (kelime/dk). Doğallığın yerine geçmez;
  doğallık için kör dinleme paketi (A/B/C/D) üretilir, eşleme anahtar.json'da.
"""
from __future__ import annotations

import json
import random
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

BURASI = Path(__file__).resolve().parent


def kucuk(t: str) -> str:
    return t.replace("I", "ı").replace("İ", "i").lower()


def normal(t: str) -> list[str]:
    from num2words import num2words
    t = kucuk(t).replace("’", "'")
    t = re.sub(r"\d+", lambda m: " " + num2words(int(m.group()), lang="tr") + " ", t)
    t = re.sub(r"[^\wçğıöşü' ]", " ", t)
    t = t.replace("'", "")
    # "elli üç" ile num2words'ün "elliüç"ü aynı sayılsın: ardışık sayı sözcükleri iki tarafta da birleştirilir
    out: list[str] = []
    for w in t.split():
        if out and w in SAYI and re.fullmatch(f"({'|'.join(SAYI)})+", out[-1]):
            out[-1] += w
        else:
            out.append(w)
    return out


SAYI = ["bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz", "on", "yirmi", "otuz", "kırk", "elli",
        "altmış", "yetmiş", "seksen", "doksan", "yüz", "bin", "milyon"]


def hizala(r: list[str], h: list[str]):
    n, m = len(r), len(h)
    d = np.zeros((n + 1, m + 1), dtype=int)
    d[:, 0] = range(n + 1)
    d[0, :] = range(m + 1)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + (r[i - 1] != h[j - 1]))
    i, j, sil, ekle, deg = n, m, [], [], []
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i, j] == d[i - 1, j - 1] + (r[i - 1] != h[j - 1]):
            if r[i - 1] != h[j - 1]:
                deg.append((r[i - 1], h[j - 1]))
            i, j = i - 1, j - 1
        elif i > 0 and d[i, j] == d[i - 1, j] + 1:
            sil.append(r[i - 1])
            i -= 1
        else:
            ekle.append(h[j - 1])
            j -= 1
    return int(d[n, m]), sil[::-1], ekle[::-1], deg[::-1]


def cer(r: list[str], h: list[str]) -> float:
    a, b = "".join(r), "".join(h)
    if not a:
        return 0.0
    p = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        q = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            q[j] = min(p[j] + 1, q[j - 1] + 1, p[j - 1] + (a[i - 1] != b[j - 1]))
        p = q
    return p[-1] / len(a)


def oku(yol: Path):
    import soundfile as sf
    x, sr = sf.read(str(yol), dtype="float32")
    return (x if x.ndim == 1 else x.mean(1)), sr


def gidis_donus(yol: Path, codec: list[str], uzanti: str) -> Path:
    ara = yol.with_suffix(uzanti)
    geri = yol.with_name(yol.stem + "_" + uzanti.strip(".") + ".wav")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(yol), *codec, str(ara)], check=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(ara), "-ac", "1", str(geri)], check=True)
    return geri


def main() -> int:
    kaynak, cikti = Path(sys.argv[1]), Path(sys.argv[2])
    cikti.mkdir(parents=True, exist_ok=True)
    cum = json.loads((BURASI / "cumleler.json").read_text())
    from faster_whisper import WhisperModel
    import librosa
    import perth
    asr = WhisperModel("medium", device="cpu", compute_type="int8")
    wm = perth.PerthImplicitWatermarker()
    motorlar = sorted(p.stem.split("_", 1)[1] for p in kaynak.glob("uretim_*.json"))
    harfler = list("ABCDEFGH")[:len(motorlar)]
    random.Random(51).shuffle(harfler)
    anahtar = dict(zip(motorlar, harfler))
    sonuc = {"asr": "faster-whisper medium int8 (cpu, tr, beam 5)", "motorlar": {}}
    for motor in motorlar:
        u = json.loads((kaynak / f"uretim_{motor}.json").read_text())
        satirlar = []
        for r in u["test"]:
            yol = kaynak / r["dosya"]
            segs, _ = asr.transcribe(str(yol), language="tr", beam_size=5, condition_on_previous_text=False)
            dokum = " ".join(s.text.strip() for s in segs)
            ref, hip = normal(r["metin"]), normal(dokum)
            hata, sil, ekle, deg = hizala(ref, hip)
            isimler = [n for n in cum["ozel_isimler"] if kucuk(n.split()[0]) in kucuk(r["metin"])]
            tanindi = [n for n in isimler if all(any(w.startswith(kucuk(p)[:max(3, len(p) - 1)]) for w in hip)
                                                  for p in n.split())]
            x, sr = oku(yol)
            f0, v, _ = librosa.pyin(librosa.resample(x, orig_sr=sr, target_sr=16000), fmin=60, fmax=400, sr=16000)
            f0 = f0[~np.isnan(f0)]
            st = float(np.std(12 * np.log2(f0 / np.median(f0)))) if len(f0) > 10 else None
            fil = {"ham": float(np.mean(wm.get_watermark(x, sample_rate=sr)))}
            for ad, codec, uz in (("aac128k", ["-c:a", "aac", "-b:a", "128k"], ".m4a"),
                                  ("mp3_64k", ["-c:a", "libmp3lame", "-b:a", "64k"], ".mp3")):
                y, ysr = oku(gidis_donus(yol, codec, uz))
                fil[ad] = float(np.mean(wm.get_watermark(y, sample_rate=ysr)))
            satirlar.append({"no": r["no"], "dokum": dokum, "wer": round(hata / len(ref), 3), "cer": round(cer(ref, hip), 3),
                             "atlanan_kelime": sil, "eklenen_kelime": ekle, "degisen": deg,
                             "isim": len(isimler), "isim_taninan": len(tanindi),
                             "f0_std_yarimton": None if st is None else round(st, 2),
                             "kelime_dk": round(len(ref) / max(r["ses_sn"], 0.1) * 60, 1),
                             "filigran": {k: round(v, 3) for k, v in fil.items()}})
            dinleme = cikti / f"dinle_{anahtar[motor]}_{r['no']:02d}.mp3"
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(yol), "-c:a", "libmp3lame", "-b:a", "96k",
                            str(dinleme)], check=True)
        for r in u["pilot"]:
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(kaynak / r["dosya"]), "-c:a", "libmp3lame",
                            "-b:a", "96k", str(cikti / f"pilot_{anahtar[motor]}_{r['no']:02d}.mp3")], check=True)
        n_ref = sum(len(normal(r["metin"])) for r in u["test"])
        ozet = {
            "wer_ort": round(float(np.mean([s["wer"] for s in satirlar])), 3),
            "cer_ort": round(float(np.mean([s["cer"] for s in satirlar])), 3),
            "atlanan_kelime_toplam": sum(len(s["atlanan_kelime"]) for s in satirlar),
            "kelime_toplam": n_ref,
            "isim_dogruluk": f"{sum(s['isim_taninan'] for s in satirlar)}/{sum(s['isim'] for s in satirlar)}",
            "f0_std_yarimton_ort": round(float(np.mean([s["f0_std_yarimton"] for s in satirlar if s["f0_std_yarimton"]])), 2),
            "kelime_dk_ort": round(float(np.mean([s["kelime_dk"] for s in satirlar])), 1),
            "filigran_ham_ort": round(float(np.mean([s["filigran"]["ham"] for s in satirlar])), 3),
            "filigran_aac128k_ort": round(float(np.mean([s["filigran"]["aac128k"] for s in satirlar])), 3),
            "filigran_mp3_64k_ort": round(float(np.mean([s["filigran"]["mp3_64k"] for s in satirlar])), 3),
            "yukleme_sn": u["yukleme_sn"], "test_uretim_sn": u["test_toplam_uretim_sn"], "test_ses_sn": u["test_toplam_ses_sn"],
            "rtf": round(u["test_toplam_uretim_sn"] / max(u["test_toplam_ses_sn"], 0.1), 3),
            "pilot_anlatim_sn_yukleme_dahil": u["pilot_anlatim_toplam_sn_yukleme_dahil"],
            "pilot_ses_sn": u["pilot_toplam_ses_sn"],
            "tepe_bellek_gb": u["tepe_bellek_gb"],
            "wav_kb_saniye_basina": round(sum(r["wav_kb"] for r in u["test"]) / max(u["test_toplam_ses_sn"], 0.1), 1),
            "ornekleme_hz": u["test"][0]["sr"],
        }
        sonuc["motorlar"][motor] = {"ozet": ozet, "cumleler": satirlar, "makine": u["makine"]}
        print(motor, json.dumps(ozet, ensure_ascii=False), flush=True)
    (cikti / "degerlendirme.json").write_text(json.dumps(sonuc, ensure_ascii=False, indent=1))
    (cikti / "anahtar.json").write_text(json.dumps(anahtar, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
