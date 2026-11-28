"""Faz-62c — Uzun belgesel kurgusu (16:9, 15–20 dk). kurgu.uret() plan biçimi 'uzun' ise buraya yönlendirir;
Shorts kurgusu (kurgu.py) değişmez.

Akış:
1. Plan denetimi yeniden çalışır; hata varsa üretim yok. Her çekim render edilir ya da önbellekten okunur
   (harita / 2.5D tarihî görsel / sınırlı 3D). Tek bir çekim bile TAMAM değilse üretim HATA ile durur.
2. Bütün cümlelerin seslendirme dosyası (gerçek TTS) var mı denetlenir; eksikse HATA (sessiz boşluk ile üretim yok).
3. Ses: anlatım zaman çizelgesindeki yerlerine + kodla üretilen telifsiz müzik yatağı (bölüm başına akor) + CC0 ortam
   kaydı + savaş bölümünde hafif davul; konuşma sırasında alt katman kısılır; iki geçişli EBU R128 (loudnorm).
4. Görüntü: çekimler kesmeyle uç uca; bölüm sınırlarında karartma geçişi, başta/sonda fade, bölüm başlıkları ve
   ekran yazıları (ASS). Altyazı ayrı .srt (Türkçe, UTF-8); istenirse videoya gömülür.
5. Kalite kapıları (qa): çözünürlük/fps/codec/kapsayıcı, tam kod çözme (oynatılabilirlik), ses↔görüntü süresi,
   plan süresi, hedef süre (15–20 dk), SRT zaman kodları, siyah kare, ses düzeyi, Whisper dinleme ortalaması.
   Herhangi bir kritik bulgu varsa durum TAMAM DEĞİLDİR.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from motor import ayar
from motor.uretim import plan_denetim, render, seslendirme, veri

SR = 48000
# Bölüm başına akor (Hz; ağırlıklı minör renk). Telifsiz: kodla üretilir, dosya yok.
AKORLAR = [(110.0, 130.81, 164.81), (98.0, 116.54, 146.83), (87.31, 103.83, 130.81), (103.83, 123.47, 155.56),
           (116.54, 138.59, 174.61), (92.5, 110.0, 138.59), (82.41, 98.0, 123.47), (110.0, 130.81, 164.81)]


class UretimHatasi(RuntimeError):
    pass


# ---------------------------------------------------------------- zaman yardımcıları

def srt_zaman(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    s, ms = divmod(ms, 1000)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ass_zaman(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    s, cs = divmod(cs, 100)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def bolum_sinirlari(plan: dict, senaryo: dict) -> list[dict]:
    """Bölüm başına görüntü aralığı (zaman çizelgesinden): [{id, baslik, roller, bas, son}]."""
    bolum = {c["id"]: c.get("bolum") for c in senaryo["cumleler"]}
    bilgi = {b["id"]: b for b in senaryo.get("bolumler", [])}
    r: list[dict] = []
    for z in plan["ses"]["cizelge"]:
        b = bolum.get(z["cumle"])
        if not r or r[-1]["id"] != b:
            r.append({"id": b, "baslik": bilgi.get(b, {}).get("baslik", ""), "roller": bilgi.get(b, {}).get("roller", []),
                      "bas": z["goruntu_bas_sn"], "son": z["goruntu_son_sn"]})
        else:
            r[-1]["son"] = z["goruntu_son_sn"]
    return r


# ---------------------------------------------------------------- altyazı (SRT)

def _satirla(kelimeler: list[str], en_cok: int) -> list[str]:
    satirlar, cur = [], ""
    for w in kelimeler:
        if cur and len(cur) + 1 + len(w) > en_cok:
            satirlar.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        satirlar.append(cur)
    return satirlar


def srt_ipuclari(plan: dict, senaryo: dict, k: dict | None = None) -> list[tuple[float, float, str]]:
    """Cümle metinleri seslendirme aralıklarına harf sayısıyla dağıtılır; ipucu en çok 2 satır × 42 harf.
    Örtüşme yok, sıra korunur (TTS sabit hızlıdır: harf oranı konuşmayla örtüşür)."""
    k = k or veri.kural("uzun")["kurgu"]["altyazi"]
    metin = {c["id"]: c["metin"] for c in senaryo["cumleler"]}
    ipuclari: list[tuple[float, float, str]] = []
    for z in plan["ses"]["cizelge"]:
        satirlar = _satirla(metin[z["cumle"]].split(), k["satir_en_cok_harf"])
        parcalar = ["\n".join(satirlar[i:i + k["en_cok_satir"]]) for i in range(0, len(satirlar), k["en_cok_satir"])]
        toplam = sum(len(p) for p in parcalar) or 1
        t = z["ses_bas_sn"]
        for p in parcalar:
            d = z["ses_sure_sn"] * len(p) / toplam
            ipuclari.append((round(t, 3), round(t + d, 3), p))
            t += d
    return ipuclari


def srt_yaz(ipuclari: list[tuple[float, float, str]], yol: Path) -> Path:
    yol.write_text("".join(f"{i}\n{srt_zaman(a)} --> {srt_zaman(b)}\n{m}\n\n" for i, (a, b, m) in enumerate(ipuclari, 1)),
                   encoding="utf-8")
    return yol


SRT_ZAMAN = re.compile(r"^(\d{2}):([0-5]\d):([0-5]\d),(\d{3}) --> (\d{2}):([0-5]\d):([0-5]\d),(\d{3})$")


def srt_denetle(yol: Path, video_sure: float | None = None) -> list[str]:
    """SRT biçim ve zaman kodu denetimi: sıra numarası, HH:MM:SS,mmm biçimi, bas<son, örtüşmesiz artan sıra,
    boş metin yok, UTF-8, son ipucu video süresini aşmaz."""
    h: list[str] = []
    try:
        metin = Path(yol).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return [f"SRT okunamadı/UTF-8 değil: {e}"]
    bloklar = [b for b in metin.replace("\r\n", "\n").strip("\n").split("\n\n") if b.strip()]
    if not bloklar:
        return ["SRT boş"]
    onceki_son = -1.0
    for i, b in enumerate(bloklar, 1):
        satir = b.split("\n")
        if len(satir) < 3:
            h.append(f"ipucu {i}: eksik satır")
            continue
        if satir[0].strip() != str(i):
            h.append(f"ipucu {i}: sıra numarası '{satir[0]}'")
        m = SRT_ZAMAN.match(satir[1].strip())
        if not m:
            h.append(f"ipucu {i}: geçersiz zaman kodu '{satir[1]}'")
            continue
        g = [int(x) for x in m.groups()]
        a = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        s = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        if s <= a:
            h.append(f"ipucu {i}: bitiş başlangıçtan önce/eşit")
        if a < onceki_son - 1e-3:
            h.append(f"ipucu {i}: önceki ipucuyla örtüşüyor")
        if not "".join(satir[2:]).strip():
            h.append(f"ipucu {i}: boş metin")
        if video_sure is not None and s > video_sure + 0.5:
            h.append(f"ipucu {i}: video süresini ({video_sure:.1f} sn) aşıyor")
        onceki_son = s
    return h


# ---------------------------------------------------------------- ekran yazıları (ASS)

def ekran_ass(plan: dict, senaryo: dict, yol: Path, altyazi: list | None = None) -> Path:
    """Bölüm başlıkları + çekim ekran yazıları (tarih/yer). Altyazı yalnızca 'gom' istenirse buraya eklenir."""
    W, H = plan["cozunurluk"]
    b1, b2, b3 = int(H * 0.065), int(H * 0.035), int(H * 0.042)
    stil = (f"Style: Bolum,Baloo 2,{b1},&H00F0F4FF,&H00F0F4FF,&H64101010,&H64101010,-1,0,0,0,100,100,1,0,3,{max(8, b1 // 4)},0,1,"
            f"{int(W * 0.05)},{int(W * 0.05)},{int(H * 0.17)},1\n"
            f"Style: Ust,Baloo 2,{b2},&H0030D8FF,&H0030D8FF,&H00101010,&H78000000,-1,0,0,0,100,100,0,0,1,2,2,7,"
            f"{int(W * 0.04)},{int(W * 0.04)},{int(H * 0.05)},1\n"
            f"Style: Alt,Baloo 2,{b3},&H00FFFFFF,&H00FFFFFF,&H5A000000,&H5A000000,-1,0,0,0,100,100,0,0,3,6,0,2,"
            f"{int(W * 0.12)},{int(W * 0.12)},{int(H * 0.06)},1")
    satir = ["[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\nWrapStyle: 0\n\n[V4+ Styles]\n" % (W, H),
             "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
             "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
             "MarginR, MarginV, Encoding\n", stil, "\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, "
             "MarginV, Effect, Text\n"]
    for i, b in enumerate(bolum_sinirlari(plan, senaryo)):
        if b["baslik"]:
            bas = b["bas"] + (0.4 if i else 1.2)
            satir.append(f"Dialogue: 2,{_ass_zaman(bas)},{_ass_zaman(min(b['son'], bas + 4.0))},Bolum,,0,0,0,,"
                         f"{{\\fad(400,500)}}{b['baslik']}\n")
    t = 0.0
    for c in plan["cekimler"]:
        if c.get("metin_katmani"):
            satir.append(f"Dialogue: 1,{_ass_zaman(t + 0.15)},{_ass_zaman(t + c['sure_sn'] - 0.1)},Ust,,0,0,0,,"
                         f"{{\\fad(200,200)}}{c['metin_katmani']}\n")
        t += c["sure_sn"]
    for a, b, m in altyazi or []:
        satir.append(f"Dialogue: 0,{_ass_zaman(a)},{_ass_zaman(b)},Alt,,0,0,0,,{m.replace(chr(10), chr(92) + 'N')}\n")
    yol.write_text("".join(satir), encoding="utf-8")
    return yol


# ---------------------------------------------------------------- ses

def _wav(yol: str) -> np.ndarray:
    x, sr = sf.read(yol, dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    if sr != SR:
        from scipy.signal import resample_poly
        g = math.gcd(sr, SR)
        x = resample_poly(x, SR // g, sr // g).astype(np.float32)
    return x


def _doldur(x: np.ndarray, n: int) -> np.ndarray:
    """Kaydı n örneğe döngüyle uzatır (uçlar 1 sn çapraz geçişle eklenir; kurgu.py ile aynı yöntem)."""
    if len(x) >= n:
        return x[:n]
    cf = min(SR, len(x) // 4)
    r = np.linspace(0, 1, cf, dtype=np.float32)
    y = x.copy()
    while len(y) < n:
        y = np.concatenate([y[:-cf], y[-cf:] * (1 - r) + x[:cf] * r, x[cf:]])
    return y[:n]


def muzik_yatagi(sinirlar: list[dict], toplam: float) -> np.ndarray:
    """Telifsiz, kodla üretilen ambiyans müzik yatağı: her bölüm kendi akoru, yavaş nefes alan genlik, 3 sn geçiş."""
    n = int(math.ceil(toplam * SR))
    y = np.zeros(n, np.float32)
    gec = int(3.0 * SR)
    for i, b in enumerate(sinirlar):
        a, s = max(0, int(b["bas"] * SR) - gec // 2), min(n, int(b["son"] * SR) + gec // 2)
        if s <= a:
            continue
        t = np.arange(a, s, dtype=np.float64) / SR
        seg = np.zeros(s - a, np.float64)
        for j, f in enumerate(AKORLAR[i % len(AKORLAR)]):
            for h, g in ((0.5, 0.5), (1.0, 1.0), (2.0, 0.22)):
                seg += g * np.sin(2 * np.pi * f * h * t + j * 1.3 + h)
        seg *= 0.75 + 0.25 * np.sin(2 * np.pi * 0.05 * t + i)
        zarf = np.ones(s - a)
        k = min(gec, (s - a) // 2)
        zarf[:k] = np.linspace(0, 1, k)
        zarf[-k:] = np.minimum(zarf[-k:], np.linspace(1, 0, k))
        y[a:s] += (seg * zarf).astype(np.float32)
    return y / (np.abs(y).max() + 1e-6)


def _zarf(anlatim: np.ndarray) -> np.ndarray:
    """Konuşma zarfı (0–1), 10 ms çözünürlükte hesaplanıp örneğe ara değerlenir (uzun kayıtta O(n))."""
    adim = SR // 100
    m = len(anlatim) // adim + 1
    pad = np.zeros(m * adim, np.float32)
    pad[:len(anlatim)] = np.abs(anlatim)
    aktif = (pad.reshape(m, adim).max(axis=1) > 0.02).astype(np.float32)
    cek = np.convolve(aktif, np.ones(25), "same") > 0              # ±125 ms tutma
    yum = np.convolve(cek.astype(np.float32), np.hanning(80) / np.hanning(80).sum(), "same")   # 0,8 sn yumuşatma
    return np.interp(np.arange(len(anlatim)) / adim, np.arange(m), np.clip(yum, 0, 1)).astype(np.float32)


def ses_karisimi(plan: dict, senaryo: dict, sureler: dict, cikti: Path) -> dict:
    k = veri.kural("uzun")["kurgu"]
    cz = plan["ses"]["cizelge"]
    toplam = plan["ses"]["toplam_sn"]
    n = int(math.ceil(toplam * SR))
    anlatim = np.zeros(n, np.float32)
    for z in cz:
        x = _wav(sureler[z["cumle"]]["wav"])
        x = x / (np.abs(x).max() + 1e-6) * 0.89
        b = int(z["ses_bas_sn"] * SR)
        anlatim[b:b + len(x)] += x[: max(0, n - b)]
    sinirlar = bolum_sinirlari(plan, senaryo)
    alt = muzik_yatagi(sinirlar, toplam) * k["muzik"]["duzey"]
    p = ayar.REPO / "motor" / k["ambiyans"]["dosya"]
    if p.exists():
        amb = _wav(str(p))
        alt += _doldur(amb / (np.abs(amb).max() + 1e-6), n) * k["ambiyans"]["duzey"]
    davul = k.get("davul") or {}
    if davul.get("roller"):
        from kaos.sinema import motor as sinema
        from scipy.signal import resample_poly
        for b in sinirlar:
            if set(b["roller"]) & set(davul["roller"]):
                y = sinema._sentez("davul", b["son"] - b["bas"], 11)
                y = resample_poly(y, SR, sinema.SR).astype(np.float32) if sinema.SR != SR else y
                a = int(b["bas"] * SR)
                alt[a:a + len(y)] += y[: max(0, n - a)] * davul["duzey"]
    alt *= 1 - k["konusmada_kisma"] * _zarf(anlatim)
    mix = anlatim + alt
    tepe = float(np.abs(mix).max())
    if tepe > 0.95:
        mix *= 0.95 / tepe
    ham = cikti / "karisim_ham.wav"
    sf.write(ham, mix, SR)
    del anlatim, alt, mix
    norm = loudnorm(ham, cikti / "karisim.wav", k["ses"]["loudnorm"])
    return {"wav": str(cikti / "karisim.wav"), "sure_sn": round(n / SR, 3), "loudnorm": norm, "bolum_sayisi": len(sinirlar)}


def loudnorm(girdi: Path, cikti: Path, hedef: dict) -> dict:
    """İki geçişli EBU R128 ses seviyesi normalizasyonu (ffmpeg loudnorm; ikinci geçiş doğrusal)."""
    f = f"loudnorm=I={hedef['I']}:TP={hedef['TP']}:LRA={hedef['LRA']}"
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(girdi), "-af", f + ":print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr)
    if r.returncode or not m:
        raise UretimHatasi(f"loudnorm ölçümü başarısız: {r.stderr[-300:]}")
    o = json.loads(m.group(0))
    f2 = (f"{f}:measured_I={o['input_i']}:measured_TP={o['input_tp']}:measured_LRA={o['input_lra']}:"
          f"measured_thresh={o['input_thresh']}:offset={o['target_offset']}:linear=true")
    r = subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(girdi), "-af", f2, "-ar", str(SR), "-c:a", "pcm_s16le",
                        str(cikti)], capture_output=True, text=True)
    if r.returncode:
        raise UretimHatasi(f"loudnorm uygulanamadı: {r.stderr[-300:]}")
    return {"olculen_I": float(o["input_i"]), "hedef_I": hedef["I"], "olculen_TP": float(o["input_tp"])}


# ---------------------------------------------------------------- görüntü

def gecis_filtresi(plan: dict, sinirlar: list[dict], ass: Path, k: dict) -> str:
    """filter_complex: ASS katmanı → bölüm sınırlarında yarı karartma (tam siyah değil) → giriş/çıkış fade."""
    W, H = plan["cozunurluk"]
    fps = plan["fps"]
    T = plan["ses"]["toplam_sn"]
    from kaos import paths
    g = k["bolum_gecisi"]
    d, tepe = g["sure_sn"], g["tepe"]
    adimlar = [f"[0:v]ass={ass}:fontsdir={os.path.dirname(paths.FONT)}[v0]"]
    son = "v0"
    for i, b in enumerate(sinirlar[1:], 1):
        t = max(0.0, b["bas"] - d / 2)
        adimlar.append(f"color=c=black:s={W}x{H}:r={fps}:d={d},format=yuva420p,"
                       f"fade=t=in:st=0:d={d / 2}:alpha=1,fade=t=out:st={d / 2}:d={d / 2}:alpha=1,"
                       f"colorchannelmixer=aa={tepe},setpts=PTS-STARTPTS+{t:.3f}/TB[k{i}]")
        adimlar.append(f"[{son}][k{i}]overlay=eof_action=pass:enable='between(t,{t:.3f},{t + d:.3f})'[v{i}]")
        son = f"v{i}"
    adimlar.append(f"[{son}]fade=t=in:st=0:d={k['giris_sn']},fade=t=out:st={max(0.0, T - k['cikis_sn']):.3f}:d={k['cikis_sn']},"
                   f"format=yuv420p[vout]")
    return ";".join(adimlar)


def _ffprobe(yol: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=format_name,duration:stream=codec_type,codec_name,width,height,r_frame_rate,duration,pix_fmt",
                        "-of", "json", str(yol)], capture_output=True, text=True)
    return json.loads(r.stdout or "{}")


def qa(final: Path, srt: Path, plan: dict, hedef: list | None, sinema_kk: dict | None = None,
       dinleme: dict | None = None) -> dict:
    """Uzun format kalite kapıları. Dönüş {'kritik': [...], 'uyari': [...], ...}; kritik boş değilse üretim KALIR."""
    k = veri.kural("uzun")["kurgu"]["qa"]
    r: dict = {"kritik": [], "uyari": []}
    if not final.exists() or final.stat().st_size == 0:
        r["kritik"].append("FFmpeg çıktı dosyası oluşmadı")
        return r
    W, H = plan["cozunurluk"]
    p = _ffprobe(final)
    v = [s for s in p.get("streams", []) if s.get("codec_type") == "video"]
    a = [s for s in p.get("streams", []) if s.get("codec_type") == "audio"]
    fmt = p.get("format", {})
    if "mp4" not in fmt.get("format_name", ""):
        r["kritik"].append(f"kapsayıcı mp4 değil ({fmt.get('format_name')})")
    if not v:
        r["kritik"].append("görüntü akışı yok")
    else:
        if (v[0].get("width"), v[0].get("height")) != (W, H):
            r["kritik"].append(f"çözünürlük {v[0].get('width')}x{v[0].get('height')} (beklenen {W}x{H})")
        if v[0].get("codec_name") != "h264" or v[0].get("pix_fmt") != "yuv420p":
            r["kritik"].append(f"görüntü codec {v[0].get('codec_name')}/{v[0].get('pix_fmt')} (beklenen h264/yuv420p)")
    if not a:
        r["kritik"].append("ses akışı yok")
    elif a[0].get("codec_name") != "aac":
        r["kritik"].append(f"ses codec {a[0].get('codec_name')} (beklenen aac)")
    sure = float(fmt.get("duration") or 0)
    r["sure_sn"] = round(sure, 2)
    if v and a:
        fark = abs(float(v[0].get("duration") or 0) - float(a[0].get("duration") or 0))
        r["ses_goruntu_farki_sn"] = round(fark, 3)
        if fark > k["ses_goruntu_farki_sn"]:
            r["kritik"].append(f"ses ve görüntü süresi uyumsuz ({fark:.2f} sn)")
    if abs(sure - plan["ses"]["toplam_sn"]) > k["sure_toleransi_sn"]:
        r["kritik"].append(f"video {sure:.1f} sn; plan (gerçek TTS) {plan['ses']['toplam_sn']:.1f} sn")
    if hedef and not hedef[0] <= sure <= hedef[1]:
        r["kritik"].append(f"süre {sure / 60:.1f} dk; hedef {hedef[0] / 60:.0f}–{hedef[1] / 60:.0f} dk")
    dec = subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", str(final), "-map", "0", "-f", "null", "-"],
                         capture_output=True, text=True)
    r["oynatilabilir"] = dec.returncode == 0 and not dec.stderr.strip()
    if not r["oynatilabilir"]:
        r["kritik"].append(f"MP4 baştan sona çözülemiyor: {dec.stderr.strip()[-200:]}")
    sh = srt_denetle(srt, sure) if srt.exists() else ["SRT dosyası yok"]
    r["srt_hatalari"] = sh[:20]
    r["kritik"] += [f"SRT: {x}" for x in sh[:5]]
    if sinema_kk is not None:
        r["teknik"] = {x: sinema_kk.get(x) for x in ("cozunurluk", "fps", "ses_ortalama_db", "ses_tepe_db", "siyah_bolum", "donuk_bolum")}
        r["kritik"] += [f"teknik: {x}" for x in sinema_kk.get("kritik", [])]
        r["uyari"] += sinema_kk.get("uyari", [])
    if dinleme:
        ort = sum(x["benzerlik"] for x in dinleme.values()) / len(dinleme)
        r["dinleme_ortalama"] = round(ort, 3)
        dusuk = [i for i, x in dinleme.items() if x["benzerlik"] < 0.5]
        if dusuk:
            r["uyari"].append(f"Whisper benzerliği düşük cümleler: {', '.join(dusuk[:10])}")
        if ort < k["dinleme_ortalama_en_az"]:
            r["kritik"].append(f"seslendirme dinleme ortalaması {ort:.2f}; en az {k['dinleme_ortalama_en_az']}")
    r["gecti"] = not r["kritik"]
    return r


# ---------------------------------------------------------------- ana akış

def uret(klasor: Path, gom: bool | None = None) -> dict:
    t0 = time.time()
    plan_yolu = klasor / "cekim_plani.json"
    plan = json.loads(plan_yolu.read_text())
    senaryo = json.loads((klasor / "senaryo.json").read_text())
    konu = json.loads((klasor / "konu.json").read_text()) if (klasor / "konu.json").exists() else {}
    k = veri.kural("uzun")["kurgu"]
    gom = k["altyazi"]["gom"] if gom is None else gom
    if os.environ.get("ALTYAZI_GOM") in ("1", "true", "evet"):
        gom = True
    den = plan_denetim.denetle(plan)
    if not den["gecti"]:
        return {"durum": "REDDEDİLDİ", "hatalar": den["hatalar"]}
    if plan.get("format") != "uzun":
        return {"durum": "REDDEDİLDİ", "hatalar": ["plan biçimi uzun değil"]}
    cikti = ayar.ONBELLEK / "kurgu" / plan["konu"]
    shutil.rmtree(cikti, ignore_errors=True)
    cikti.mkdir(parents=True)
    # 1) her cümle görüntülü mü (eksik sahne) ve her çekim gerçekten render edildi mi
    ortulen = {i for c in plan["cekimler"] for i in c["cumleler"]}
    eksik_sahne = [c["id"] for c in senaryo["cumleler"] if c["id"] not in ortulen]
    if eksik_sahne:
        return {"durum": "HATA", "neden": "görüntüsü olmayan cümle", "eksik": eksik_sahne}
    cekimler, klipler = [], []
    for c in plan["cekimler"]:
        r = render.render(str(plan_yolu), c["id"])
        if r.get("durum") != "TAMAM" or not Path(r.get("video", "")).exists():
            return {"durum": "HATA", "neden": "çekim render edilemedi", "cekim": c["id"],
                    "render": {x: r.get(x) for x in ("durum", "neden", "hatalar")}}
        o = r["olculen"]
        cekimler.append({"cekim": c["id"], "tur": c["tur"], "kare": o["kare"], "render_sn": o["render_sn"],
                         "onbellekten": r.get("onbellekten", False)})
        klipler.append(r["video"])
    t_render = time.time() - t0
    # 2) gerçek TTS: her cümlenin ses dosyası var mı
    sureler = seslendirme.olc(senaryo["cumleler"])
    eksik_ses = [z["cumle"] for z in plan["ses"]["cizelge"]
                 if z["cumle"] not in sureler or not Path(sureler[z["cumle"]].get("wav", "")).exists()]
    if eksik_ses:
        return {"durum": "HATA", "neden": "seslendirme dosyası eksik", "eksik": eksik_ses}
    t2 = time.time()
    liste = cikti / "klipler.txt"
    liste.write_text("".join(f"file '{x}'\n" for x in klipler))
    goruntu = cikti / "goruntu.mp4"
    r = subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(liste), "-c", "copy",
                        str(goruntu)], capture_output=True, text=True)
    if r.returncode:
        return {"durum": "HATA", "neden": "FFmpeg birleştirme başarısız", "ffmpeg": r.stderr[-400:]}
    try:
        ses = ses_karisimi(plan, senaryo, sureler, cikti)
    except UretimHatasi as e:
        return {"durum": "HATA", "neden": str(e)}
    ipuclari = srt_ipuclari(plan, senaryo)
    srt = srt_yaz(ipuclari, cikti / f"{plan['konu']}.srt")
    ass = ekran_ass(plan, senaryo, cikti / "ekran.ass", ipuclari if gom else None)
    sinirlar = bolum_sinirlari(plan, senaryo)
    T = plan["ses"]["toplam_sn"]
    final = cikti / f"{plan['konu']}.mp4"
    gecici = cikti / f"{plan['konu']}.yapim.mp4"
    kv = k["video"]
    komut = ["ffmpeg", "-loglevel", "error", "-y", "-i", str(goruntu), "-i", ses["wav"],
             "-filter_complex", gecis_filtresi(plan, sinirlar, ass, k), "-map", "[vout]", "-map", "1:a:0",
             "-af", f"afade=t=in:st=0:d={k['giris_sn']},afade=t=out:st={max(0.0, T - k['cikis_sn']):.3f}:d={k['cikis_sn']}",
             "-c:v", "libx264", "-preset", str(kv["preset"]), "-crf", str(kv["crf"]), "-maxrate", kv["maxrate"],
             "-bufsize", kv["bufsize"], "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(plan["fps"]),
             "-movflags", "+faststart", "-c:a", "aac", "-b:a", k["ses"]["bitrate"], "-ar", str(SR), "-ac", "2",
             "-t", f"{T:.3f}", str(gecici)]
    r = subprocess.run(komut, capture_output=True, text=True)
    if r.returncode or not gecici.exists():
        return {"durum": "HATA", "neden": "FFmpeg kurgu başarısız", "ffmpeg": r.stderr[-600:]}
    gecici.replace(final)   # yarım dosya asla son ad altında kalmaz
    t_kurgu = time.time() - t2
    from kaos.sinema import motor as sinema
    from motor.uretim.kurgu import _dinle
    kk = sinema.kalite_kontrol(str(final), plan["cozunurluk"][0], plan["cozunurluk"][1], plan["fps"], T)
    dinleme = _dinle(sureler, senaryo)
    kalite = qa(final, srt, plan, konu.get("hedef_sure_sn"), kk, dinleme)
    (cikti / "altyazi.json").write_text(json.dumps([{"bas": a, "son": b, "metin": m} for a, b, m in ipuclari],
                                                   ensure_ascii=False, indent=1))
    for gereksiz in (goruntu, cikti / "karisim_ham.wav"):
        gereksiz.unlink(missing_ok=True)
    sonuc = {
        "durum": "TAMAM" if kalite["gecti"] else "KALİTE KONTROLDEN KALDI",
        "format": "uzun",
        "video": str(final),
        "srt": str(srt),
        "altyazi_gomulu": bool(gom),
        "sure_sn": kalite.get("sure_sn"),
        "bolumler": [{x: b[x] for x in ("id", "baslik", "bas", "son")} for b in sinirlar],
        "olculen": {"toplam_duvar_sn": round(time.time() - t0, 1), "render_asamasi_duvar_sn": round(t_render, 1),
                    "kurgu_sn": round(t_kurgu, 1), "cekim_sayisi": len(cekimler),
                    "tur_dagilimi": {t: sum(1 for c in cekimler if c["tur"] == t) for t in ("harita", "gorsel25d", "3d")},
                    "video_mb": round(final.stat().st_size / 1e6, 2)},
        "ses": ses,
        "kalite_kontrol": kalite,
        "dinleme": dinleme,
        "cekimler": cekimler,
        "seslendirme_motoru": next(iter(sureler.values()))["motor"],
    }
    (cikti / "uretim_raporu.json").write_text(json.dumps(sonuc, ensure_ascii=False, indent=1))
    return sonuc
