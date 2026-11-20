"""Karakter seslendirme. Sıra: Gemini TTS (en doğal, ücretsiz kota) → Microsoft Edge sesleri (ücretsiz) → yerel Piper (yedek).
Bir bölümün tüm replikleri tek motorla üretilir ki sesler bölüm içinde tutarlı kalsın."""
import asyncio
import base64
import glob
import json
import os
import subprocess
import time
import urllib.error
import urllib.request

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

SR = 44100


class TTSError(Exception):
    pass


def _clean(text):
    return text.replace('\n', ' ').strip()


def _trim(x, thr=0.008, pad=0.06, sr=SR):
    idx = np.where(np.abs(x) > thr)[0]
    if len(idx) == 0:
        return x
    a = max(0, idx[0] - int(pad * sr))
    b = min(len(x), idx[-1] + int(pad * sr))
    return x[a:b]


def _norm(x, peak=0.9):
    m = np.abs(x).max()
    return x / m * peak if m > 0 else x


def _to_sr(x, sr):
    if sr == SR:
        return x.astype(np.float32)
    from math import gcd
    g = gcd(sr, SR)
    return resample_poly(x, SR // g, sr // g).astype(np.float32)


def _save(path, x):
    sf.write(path, _norm(_trim(x)), SR)
    return path


# ------------------------------------------------------------------ Gemini
def _gemini_request(api_key, model, prompt, voice, timeout=180):
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}'
    body = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {
            'responseModalities': ['AUDIO'],
            'speechConfig': {'voiceConfig': {'prebuiltVoiceConfig': {'voiceName': voice}}},
        },
    }
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    part = data['candidates'][0]['content']['parts'][0]['inlineData']
    pcm = np.frombuffer(base64.b64decode(part['data']), dtype='<i2').astype(np.float32) / 32768.0
    rate = 24000
    mt = part.get('mimeType', '')
    if 'rate=' in mt:
        try:
            rate = int(mt.split('rate=')[1].split(';')[0])
        except ValueError:
            pass
    return _to_sr(pcm, rate)


def _split_by_silence(x, n, texts):
    """Uzun sessizliklerden n parçaya böl. Başarısızsa None."""
    if n == 1:
        return [x]
    hop = int(0.01 * SR)
    frames = len(x) // hop
    e = np.array([np.sqrt(np.mean(x[i * hop:(i + 1) * hop] ** 2)) for i in range(frames)])
    thr = max(0.004, np.percentile(e, 60) * 0.08)
    quiet = e < thr
    runs, i = [], 0
    while i < frames:
        if quiet[i]:
            j = i
            while j < frames and quiet[j]:
                j += 1
            if i > 0 and j < frames:
                runs.append((j - i, i, j))
            i = j
        else:
            i += 1
    if len(runs) < n - 1:
        return None
    runs = sorted(runs, reverse=True)[:n - 1]
    if runs[-1][0] < 25:  # en kısa ayırıcı en az 0.25 sn olmalı
        return None
    cuts = sorted(((a + b) // 2) * hop for _, a, b in runs)
    parts, prev = [], 0
    for c in cuts + [len(x)]:
        parts.append(x[prev:c])
        prev = c
    # süre/metin uzunluğu oranı makul mü?
    rates = [len(p) / SR / max(4, len(t)) for p, t in zip(parts, texts)]
    med = np.median(rates)
    if any(r < med * 0.35 or r > med * 2.8 for r in rates):
        return None
    return parts


def gemini_tts(lines, cfg, outdir, api_key):
    """lines: [(key, who, text, emotion)] → {key: wav}. Karakter başına tek istek."""
    voices = cfg['voices']
    models = cfg['tts'].get('gemini_models', ['gemini-2.5-flash-preview-tts'])
    by_char = {}
    for key, who, text, emo in lines:
        by_char.setdefault(who, []).append((key, text, emo))
    out = {}
    for who, items in by_char.items():
        v = voices[who]['gemini']
        style = voices[who].get('style', '')
        texts = [_clean(t) for _, t, _ in items]
        listing = '\n\n'.join(texts)
        prompt = (f"{style}\nAşağıdaki {len(texts)} repliği Türkçe, doğal ve oyunculu şekilde sırayla seslendir. "
                  f"Her replikten sonra tam iki saniye sessiz kal. Başka hiçbir şey söyleme.\n\n{listing}")
        if len(texts) == 1:
            prompt = f"{style}\nŞu repliği Türkçe, doğal ve oyunculu şekilde seslendir:\n\n{texts[0]}"
        audio, last_err = None, None
        for model in models:
            for attempt in range(2):
                try:
                    audio = _gemini_request(api_key, model, prompt, v)
                    break
                except urllib.error.HTTPError as e:
                    last_err = f'{model}: HTTP {e.code}'
                    if e.code == 429:
                        break  # kota bitti → sonraki model
                    time.sleep(4)
                except Exception as e:  # ağ, json vb.
                    last_err = f'{model}: {e}'
                    time.sleep(3)
            if audio is not None:
                parts = _split_by_silence(audio, len(texts), texts)
                if parts is None:
                    last_err = f'{model}: replikler ayrıştırılamadı'
                    audio = None
                    continue
                for (key, _, _), p in zip(items, parts):
                    out[key] = _save(os.path.join(outdir, f'line_{key[0]}_{key[1]}.wav'), p)
                break
        if audio is None:
            raise TTSError(f'Gemini TTS başarısız ({who}): {last_err}')
        time.sleep(21)  # ücretsiz katman: dakikada 3 istek sınırı
    return out


# ------------------------------------------------------------------ Edge
def edge_tts(lines, cfg, outdir):
    try:
        import edge_tts as et
    except ImportError as e:
        raise TTSError('edge-tts paketi yok') from e
    voices = cfg['voices']

    async def one(key, who, text):
        v = voices[who]['edge']
        mp3 = os.path.join(outdir, f'line_{key[0]}_{key[1]}.mp3')
        com = et.Communicate(_clean(text), v['voice'], rate=v.get('rate', '+0%'), pitch=v.get('pitch', '+0Hz'))
        await com.save(mp3)
        return mp3

    out = {}
    for key, who, text, emo in lines:
        mp3 = None
        for attempt in range(3):
            try:
                mp3 = asyncio.run(one(key, who, text))
                break
            except Exception as e:
                err = e
                time.sleep(2)
        if mp3 is None:
            raise TTSError(f'Edge TTS başarısız: {err}')
        wav = mp3[:-4] + '.wav'
        subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', mp3, '-ar', str(SR), '-ac', '1', wav], check=True)
        x, _ = sf.read(wav, dtype='float32')
        out[key] = _save(wav, x)
    return out


# ------------------------------------------------------------------ Piper (yerel yedek)
_piper_cache = {}


def piper_tts(lines, cfg, outdir, model_dir):
    try:
        import sherpa_onnx
    except ImportError as e:
        raise TTSError('sherpa-onnx yok') from e
    voices = cfg['voices']
    out = {}
    for key, who, text, emo in lines:
        v = voices[who]['piper']
        d = os.path.join(model_dir, f"vits-piper-tr_TR-{v['voice']}")
        if v['voice'] not in _piper_cache:
            onnx = glob.glob(d + '/*.onnx')
            if not onnx:
                raise TTSError(f'Piper modeli yok: {d}')
            _piper_cache[v['voice']] = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=onnx[0], tokens=d + '/tokens.txt', data_dir=d + '/espeak-ng-data',
                    noise_scale=0.45, noise_scale_w=0.6), num_threads=2)))
        a = _piper_cache[v['voice']].generate(_clean(text), sid=0, speed=v.get('speed', 1.0))
        x = np.array(a.samples, np.float32)
        pitch = v.get('pitch', 1.0)
        if pitch != 1.0:
            up = int(round(100 / pitch))
            x = resample_poly(x, up, 100).astype(np.float32)
        x = _to_sr(x, a.sample_rate)
        out[key] = _save(os.path.join(outdir, f'line_{key[0]}_{key[1]}.wav'), x)
    return out


def synthesize(ep, cfg, outdir, model_dir=None, log=print):
    os.makedirs(outdir, exist_ok=True)
    lines = []
    for si, sc in enumerate(ep['scenes']):
        for li, ln in enumerate(sc['lines']):
            lines.append(((si, li), ln['who'], ln['text'], ln.get('emotion', 'normal')))
    order = cfg['tts'].get('order', ['gemini', 'edge', 'piper'])
    key = os.environ.get('GEMINI_API_KEY', '')
    errors = []
    for eng in order:
        try:
            if eng == 'gemini':
                if not key:
                    raise TTSError('GEMINI_API_KEY tanımlı değil')
                res = gemini_tts(lines, cfg, outdir, key)
            elif eng == 'edge':
                res = edge_tts(lines, cfg, outdir)
            elif eng == 'piper':
                res = piper_tts(lines, cfg, outdir, model_dir or os.path.join(os.path.dirname(outdir), 'models'))
            else:
                continue
            log(f'Seslendirme motoru: {eng}')
            return res, eng
        except Exception as e:
            log(f'  {eng} kullanılamadı: {e}')
            errors.append(f'{eng}: {e}')
    raise TTSError('Hiçbir seslendirme motoru çalışmadı: ' + ' | '.join(errors))
