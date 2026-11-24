"""Veo bölümü (günde 1 Shorts): yapay zekâ videosu, sinematik 3D kalite.
Akış: bölüm senaryosu -> 2 planlık çekim planı (Gemini metin, ücretsiz) -> her plan için ilk kare
(Nano Banana, karakter referans görselleriyle: karakterler her planda aynı kalsın) -> Veo görselden video (8 sn) ->
birleştirme + açılış kancası yazısı + altyazı + son kart. Ücretli anahtar: GEMINI_IMAGE_KEY.
Herhangi bir adım hata verirse VeoError: çağıran taraf bölümü normal 3D hattıyla üretir (yayın aksamaz)."""
import base64
import json
import os
import subprocess
import time
import urllib.request

import cv2
import numpy as np

from . import paths

BASE = 'https://generativelanguage.googleapis.com/v1beta'
REF_DIR = os.path.join(paths.ROOT, 'assets', 'ref_omni') if os.path.isdir(os.path.join(paths.ROOT, 'assets', 'ref_omni')) else os.path.join(paths.ROOT, 'assets', 'ref')
FONT = os.path.join(paths.ROOT, 'assets', 'fonts', 'Baloo2.ttf')
KARAKTER_TARIF = {
    'tuna': 'Tuna: boy explorer, brown spiky hair, brass goggles on forehead, teal scarf, orange-yellow coat with belt, blue trousers, brown boots',
    'nil': 'Nil: girl, short dark bob hair, round glasses, navy vest with gold buttons, yellow sleeves, dark trousers',
    'bulut': 'Bulut: chubby boy inventor, red beanie, brown sweater, green apron with a pencil in the pocket',
    'pire': 'Pire: small youngest girl, ginger hair, red beret, freckles, yellow shirt, purple backpack, red shoes',
    'benek': 'Benek: friendly ladybug the size of a pony that the kids ride; it never speaks',
}
STIL = ('Premium 3D animated family film look (Pixar/Illumination quality), soft cinematic lighting, shallow depth of field, '
        'rich realistic textures on giant household objects; the characters are finger-sized toy-like vinyl figures exactly '
        'matching the reference images. Family friendly. STRICT: absolutely no readable text, letters, numbers, labels, logos or '
        'brand names anywhere; all packages, jars, boxes and cans are plain and unlabeled.')


# Bölüme özel ayarlar (tarih modu vb.): uret_perdeli başında ep'den doldurulur
OZEL = {}
SES_VARSAYILAN = 'Natural Turkish child voices, lively sound effects, light playful score without lyrics.'


def _stil():
    return OZEL.get('stil') or STIL


def _ses():
    return OZEL.get('ses') or SES_VARSAYILAN


def _kiyafet_metni(chars):
    k = OZEL.get('kiyafet') or {}
    parca = [f"{c.capitalize()} {k[c]}" for c in chars if k.get(c)]
    return (' OUTFITS IN THIS EPISODE (must stay identical in every shot, override the reference clothing): ' + '; '.join(parca) + '.') if parca else ''


def _ref(c):
    """Bölüme özel kostümlü referans varsa onu, yoksa resmî referansı verir."""
    return (OZEL.get('ref') or {}).get(c) or os.path.join(REF_DIR, f'{c}.jpg')


def _gorsel_uret(parts, path, oran='9:16', log=print):
    body = {'contents': [{'role': 'user', 'parts': parts}],
            'generationConfig': {'responseModalities': ['IMAGE'], 'imageConfig': {'aspectRatio': oran, 'imageSize': '1K'}}}
    for model in ('gemini-nano-banana-2.1', 'gemini-3-pro-image', 'gemini-3.1-flash-image'):
        try:
            d = _req(f'{BASE}/models/{model}:generateContent', body, timeout=240)
            for p in d['candidates'][0]['content']['parts']:
                data = (p.get('inlineData') or p.get('inline_data') or {}).get('data')
                if data:
                    with open(path, 'wb') as f:
                        f.write(base64.b64decode(data))
                    return path
        except Exception as e:
            log(f'  Görsel ({model}) hata: {str(e)[:120]}')
    return None


def kostum_referanslari(chars, outdir, log=print):
    """Kıyafet değişen bölümlerde her karakter için kostümlü resmî referans üretir (Nano Banana, ~0,04$/görsel):
    Omni tüm çekimlerde AYNI kostüm tasarımını görür (börk şekli vb. değişmez)."""
    k = OZEL.get('kiyafet') or {}
    refs = {}
    for c in chars:
        if not k.get(c):
            continue
        out = os.path.join(outdir, f'kostum_{c}.jpg')
        with open(os.path.join(REF_DIR, f'{c}.jpg'), 'rb') as f:
            img = base64.b64encode(f.read()).decode()
        parts = [{'text': f"Character model sheet: the SAME character as the reference image (identical face, hair, proportions, art style), "
                          f"full body, standing, front three-quarter view, neutral pose, plain soft light-grey studio background. "
                          f"Now wearing this exact costume, every detail clearly visible: {k[c]}. "
                          f"{_stil()} Absolutely no text, letters or logos."},
                 {'inline_data': {'mime_type': 'image/jpeg', 'data': img}}]
        if _gorsel_uret(parts, out, log=log):
            refs[c] = out
            log(f'  Kostümlü referans hazır: {c}')
    return refs


def perde_kontrol(klip, chars, aciklama, log=print):
    """Perde kalite kontrolü (Gemini görüş): karakter/kostüm tutarlılığı ve görsel hatalar. (puan 1-10, sorun) döner."""
    try:
        d0 = _sure(klip)
        parts = []
        for c in chars:
            with open(_ref(c), 'rb') as f:
                parts += [{'text': f'Reference for {c}:'}, {'inline_data': {'mime_type': 'image/jpeg', 'data': base64.b64encode(f.read()).decode()}}]
        for j, t in enumerate((0.15, 0.5, 0.85)):
            fn = f'{klip}.kk{j}.jpg'
            subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-ss', f'{d0 * t:.2f}', '-i', klip, '-frames:v', '1', '-vf', 'scale=360:-2', fn], check=True)
            with open(fn, 'rb') as f:
                parts += [{'text': f'Frame at {d0 * t:.1f}s:'}, {'inline_data': {'mime_type': 'image/jpeg', 'data': base64.b64encode(f.read()).decode()}}]
        parts.append({'text': f"You are a strict animation supervisor. Planned shot: {aciklama[:600]}. Compare the frames with the character "
                              f"references. Score 1-10: are the characters recognizably the same with IDENTICAL costumes (hat shape, colors, "
                              f"goggles, scarf), no morphing faces, no extra limbs, no readable text, and does the shot match the plan? "
                              f'Return JSON {{"puan": 8, "sorun": "short Turkish description or empty"}}'})
        d = _req(f'{BASE}/models/gemini-3.8-flash:generateContent',
                 {'contents': [{'role': 'user', 'parts': parts}],
                  'generationConfig': {'temperature': 0.1, 'responseMimeType': 'application/json'}}, timeout=120)
        r = json.loads(''.join(p.get('text', '') for p in d['candidates'][0]['content']['parts']))
        return int(r.get('puan', 10)), str(r.get('sorun', ''))
    except Exception as e:
        log(f'  Perde kontrolü atlandı: {str(e)[:120]}')
        return 10, ''


def _tarif(c):
    return KARAKTER_TARIF[c] + (('; ' + OZEL['kiyafet'][c]) if OZEL.get('kiyafet', {}).get(c) else '')


class VeoError(Exception):
    pass


def acik(cfg, slot):
    v = cfg.get('veo') or {}
    slots = v.get('slotlar') or ([v['slot']] if v.get('slot') else [])
    return bool(v.get('acik')) and bool(paths.ucretli_anahtar()) and slot in slots


def uzun_acik(cfg):
    v = cfg.get('veo') or {}
    return bool(v.get('acik')) and bool(v.get('uzun')) and bool(paths.ucretli_anahtar())


def _key():
    return (paths.ucretli_anahtar() or (_ for _ in ()).throw(RuntimeError('Ücretsiz mod: ücretli anahtar kapalı')))


def _req(url, body=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method='POST' if body is not None else 'GET',
                               headers={'x-goog-api-key': _key(), 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise VeoError(f'{e.code} {e.read()[:400]!r}')


# ------------------------------------------------------------------ 1) çekim planı
def plan(ep, cfg, log=print):
    from .writer import gemini_json
    lines = [{'who': l['who'], 'text': l['text'], 'action': l.get('action')} for sc in ep['scenes'] for l in sc['lines']]
    prompt = f"""You are the director of a premium 3D animated YouTube Shorts series "Mini Dünya": finger-sized explorer kids
living behind the kitchen baseboard explore a giant house. Turn this Turkish episode script into EXACTLY 2 cinematic video shots of
8 seconds each (total 16 s, vertical 9:16). Visual storytelling first: the first 2 seconds of shot 1 must already show the
predicament/danger; shot 2 ends with the surprising payoff. Max 2 short spoken lines per shot (keep the original Turkish lines,
shorten if needed, keep them in Turkish). Characters: {json.dumps({c: KARAKTER_TARIF[c] for c in {l['who'] for l in lines} if c in KARAKTER_TARIF}, ensure_ascii=False)}
Location: {ep['scenes'][0].get('location')} | topic: {ep.get('konu', '')} | hook text: {ep.get('kapak_yazisi', '')}
Script: {json.dumps(lines, ensure_ascii=False)}
Return JSON: {{"shots": [{{"characters": ["tuna"], "first_frame": "English description of the opening frame of this shot: who is where,
poses, giant objects, composition, camera angle", "motion": "English Veo prompt: what happens during the 8 seconds, character actions,
camera movement, sound effects and ambience", "dialogue": [{{"who": "tuna", "text": "Türkçe replik"}}]}}]}}
Rules: characters only from the list; at most 3 characters per shot; Benek never speaks; no text on screen; family friendly."""
    try:
        d = gemini_json(prompt, cfg, temperature=0.8, log=log, rounds=3)
        shots = [s for s in (d.get('shots') or []) if s.get('first_frame') and s.get('motion')][:2]
        if len(shots) == 2:
            return shots
    except Exception as e:
        log(f'  Veo planı (Gemini) hata: {str(e)[:150]}')
    # yedek: senaryodan şablon plan
    half = max(1, len(lines) // 2)
    out = []
    for part in (lines[:half], lines[half:]):
        cs = list(dict.fromkeys(l['who'] for l in part if l['who'] in KARAKTER_TARIF))[:3]
        out.append({'characters': cs, 'first_frame': f"{', '.join(cs)} in the {ep['scenes'][0].get('location')} area of a giant kitchen, {ep.get('konu', '')}",
                    'motion': f"{ep.get('konu', '')}. The characters react with big expressive animation, the camera slowly pushes in.",
                    'dialogue': part[:2]})
    return out


# ------------------------------------------------------------------ 2) ilk kare (Nano Banana + referanslar)
def ilk_kare(shot, path, log=print):
    from .boya import _modeller, _say
    parts = [{'text': f"""Create the opening frame (vertical 9:16) of a shot. {STIL}
Use the attached reference images for the characters: keep their exact proportions, outfits, colors and faces.
Scene: {shot['first_frame']}"""}]
    for c in shot.get('characters', [])[:3]:
        fn = os.path.join(REF_DIR, f'{c}.jpg')
        if os.path.exists(fn):
            parts.append({'text': f'Reference image of {KARAKTER_TARIF.get(c, c)}'})
            with open(fn, 'rb') as f:
                parts.append({'inline_data': {'mime_type': 'image/jpeg', 'data': base64.b64encode(f.read()).decode()}})
    body = {'contents': [{'role': 'user', 'parts': parts}],
            'generationConfig': {'responseModalities': ['IMAGE'], 'imageConfig': {'aspectRatio': '9:16', 'imageSize': '1K'}}}
    for model in _modeller(_key())[:2]:
        try:
            d = _req(f'{BASE}/models/{model}:generateContent', body, timeout=180)
            for p in d['candidates'][0]['content']['parts']:
                data = (p.get('inlineData') or p.get('inline_data') or {}).get('data')
                if data:
                    with open(path, 'wb') as f:
                        f.write(base64.b64decode(data))
                    _say()
                    return path
        except Exception as e:
            log(f'  İlk kare ({model}) hata: {str(e)[:150]}')
    raise VeoError('ilk kare üretilemedi')


# ------------------------------------------------------------------ 3) Veo görselden video
def _veo_modelleri(v, log=print):
    """Mevcut Veo modellerini API'den bul (isimler değişebiliyor): önce Lite (ucuz), sonra Fast."""
    try:
        ms = []
        tok = ''
        for _ in range(5):
            d = _req(f'{BASE}/models?pageSize=200' + (f'&pageToken={tok}' if tok else ''))
            for m in d.get('models', []):
                if 'veo' in m['name'] and 'predictLongRunning' in (m.get('supportedGenerationMethods') or []):
                    ms.append(m['name'].split('/')[-1])
            tok = d.get('nextPageToken')
            if not tok:
                break
        def sira(m):
            return (0 if 'lite' in m else 1 if 'fast' in m else 2, '3.1' not in m, m)
        ms = sorted(set(ms), key=sira)
        ms = [m for m in ms if 'lite' in m or 'fast' in m] or ms
        log(f'  Veo modelleri: {ms[:4]}')
        if ms:
            return ms[:3]
    except Exception as e:
        log(f'  Veo model listesi alınamadı: {str(e)[:120]}')
    return v.get('modeller', ['veo-3.1-lite-generate-preview', 'veo-3.1-fast-generate-preview'])



def video(shot, img_path, out_path, cfg, log=print):
    v = cfg.get('veo') or {}
    konusma = ' '.join(f'{d["who"].capitalize()} says in Turkish: "{d["text"]}".' for d in shot.get('dialogue', [])[:2]
                       if d.get('who') != 'benek')
    prompt = f"{STIL} {shot['motion']} {konusma} Natural Turkish child voices, lively sound effects, no music with lyrics."
    with open(img_path, 'rb') as f:
        img = base64.b64encode(f.read()).decode()
    mime = 'image/png' if img_path.endswith('.png') else 'image/jpeg'
    params = {'aspectRatio': '9:16', 'durationSeconds': 8, 'resolution': v.get('cozunurluk', '720p')}
    last = None
    for model in _veo_modelleri(v, log):
        for image in ({'bytesBase64Encoded': img, 'mimeType': mime}, {'inlineData': {'mimeType': mime, 'data': img}}):
            try:
                op = _req(f'{BASE}/models/{model}:predictLongRunning', {'instances': [{'prompt': prompt, 'image': image}], 'parameters': params})
            except VeoError as e:
                last = e
                log(f'  Veo ({model}) istek hatası: {str(e)[:160]}')
                continue
            name = op.get('name')
            t0 = time.time()
            while time.time() - t0 < 600:
                time.sleep(10)
                st = _req(f'{BASE}/{name}')
                if st.get('done'):
                    if st.get('error'):
                        raise VeoError(f"Veo işlem hatası: {str(st['error'])[:300]}")
                    resp = st.get('response', {}).get('generateVideoResponse', {})
                    smp = resp.get('generatedSamples') or []
                    if not smp:
                        raise VeoError(f'Veo video döndürmedi (güvenlik filtresi olabilir): {str(resp)[:300]}')
                    uri = smp[0]['video']['uri']
                    r = urllib.request.Request(uri, headers={'x-goog-api-key': _key()})
                    with urllib.request.urlopen(r, timeout=180) as resp2, open(out_path, 'wb') as f:
                        f.write(resp2.read())
                    log(f'  Veo klip hazır ({model}, {time.time() - t0:.0f} sn)')
                    return out_path
            raise VeoError('Veo zaman aşımı (10 dk)')
    raise VeoError(f'Veo isteği kabul edilmedi: {last}')


# ------------------------------------------------------------------ 4) birleştirme + yazılar
def _yazi(img, text, y, size, renk=(255, 214, 40), golge=True, max_w=0.88):
    from PIL import Image, ImageDraw, ImageFont
    H, W = img.shape[:2]
    pil = Image.fromarray(img)
    d = ImageDraw.Draw(pil)
    font = ImageFont.truetype(FONT, size)
    words, lines, cur = text.split(), [], ''
    for w in words:
        t = (cur + ' ' + w).strip()
        if d.textlength(t, font=font) > W * max_w and cur:
            lines.append(cur)
            cur = w
        else:
            cur = t
    lines.append(cur)
    for i, ln in enumerate(lines):
        tw = d.textlength(ln, font=font)
        x, yy = (W - tw) / 2, y + i * size * 1.12
        d.text((x, yy), ln, font=font, fill=renk, stroke_width=max(3, size // 9), stroke_fill=(20, 12, 8))
    return np.array(pil)


def birlestir(clips, shots, ep, out_path, log=print, zamanli=False, W=1080, H=1920, son_kart=True):
    FPS = 30
    yat = W > H
    Y = (lambda y: int(y * H / 1920)) if not yat else (lambda y: int(y * H / 1920 * 1.0))
    FS = (lambda sz: sz) if not yat else (lambda sz: int(sz * 0.8))
    tmp = out_path + '.ham.mp4'
    lst = out_path + '.txt'
    norm = []
    for i, c in enumerate(clips):
        n = f'{c}.n.mp4'
        subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', c, '-vf', f'scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS}',
                        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-ar', '48000', '-ac', '2', n], check=True)
        norm.append(n)
    with open(lst, 'w') as f:
        f.writelines(f"file '{os.path.abspath(n)}'\n" for n in norm)
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-c', 'copy', tmp], check=True)
    dur = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', tmp],
                               capture_output=True, text=True).stdout.strip() or 16)
    # altyazı zamanlaması: her planın replikleri o planın süresine yayılır
    subs = []
    per = dur / max(1, len(shots))
    if zamanli:  # Omni planı replik zamanlarını veriyor
        for d in shots[0].get('dialogue', []):
            if d.get('who') != 'benek' and d.get('text'):
                subs.append((float(d.get('start', 0)), float(d.get('end', 0)) or float(d.get('start', 0)) + 2.5, d['who'], d['text']))
        shots = []
    for i, s in enumerate(shots):
        ds = [d for d in s.get('dialogue', [])[:2] if d.get('who') != 'benek']
        for k, d in enumerate(ds):
            a = i * per + 0.6 + k * (per - 0.8) / max(1, len(ds))
            subs.append((a, a + (per - 0.8) / max(1, len(ds)) - 0.15, d['who'], d['text']))
    kanca = (ep.get('kapak_yazisi') or ep.get('baslik', '')).upper()
    SON = (4.0 if yat else 1.6) if zamanli else 2.4  # son kart süresi
    if zamanli and son_kart and not yat:
        # Son kart konuşmanın ÜSTÜNE binmesin: video bittikten sonra son kareyi dondurup 2,5 sn ekle (ses: konuşma tam biter, sonra sessizlik)
        SON = 2.5
        ek = out_path + '.ek.mp4'
        subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', tmp, '-vf', f'tpad=stop_mode=clone:stop_duration={SON}',
                        '-af', f'apad=pad_dur={SON}', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '17', '-pix_fmt', 'yuv420p',
                        '-c:a', 'aac', '-ar', '48000', '-ac', '2', ek], check=True)
        os.replace(ek, tmp)
        dur = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', tmp],
                                   capture_output=True, text=True).stdout.strip() or dur)
    soru = ep.get('end_card') or 'Sen olsan ne yapardın?'
    from .engine.characters import CHARS
    dec = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-i', tmp, '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE)
    enc = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
                            '-i', tmp, '-map', '0:v', '-map', '1:a', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '19', '-pix_fmt', 'yuv420p',
                            '-c:a', 'aac', '-b:a', '192k', '-af', 'loudnorm=I=-14:TP=-1.5', '-movflags', '+faststart', out_path], stdin=subprocess.PIPE)
    i = 0
    while True:
        buf = dec.stdout.read(W * H * 3)
        if len(buf) < W * H * 3:
            break
        fr = np.frombuffer(buf, np.uint8).reshape(H, W, 3).copy()
        t = i / FPS
        if t < 3.0 and not yat:
            fr = _yazi(fr, kanca, 150, 96)
        for a, b, who, text in subs:
            if a <= t < b and (t < dur - SON or not son_kart):
                col = CHARS.get(who, {}).get('color', (255, 255, 255))
                if yat:
                    fr = _yazi(fr, CHARS.get(who, {}).get('name', who.upper()) + ': ' + text, H - 150, 46, renk=(255, 255, 255), max_w=0.8)
                else:
                    if who != 'diger':
                        fr = _yazi(fr, CHARS.get(who, {}).get('name', who.upper()), 1390, 50, renk=tuple(col))
                    fr = _yazi(fr, text, 1455, 62, renk=(255, 255, 255))
        if son_kart and t > dur - SON:
            k = min(1.0, (t - (dur - SON)) / 0.3)
            fr = (fr * (1 - 0.55 * k)).astype(np.uint8)
            fr = _yazi(fr, 'MİNİ DÜNYA', Y(640), FS(110))
            fr = _yazi(fr, soru, Y(820), FS(70), renk=(255, 255, 255))
            fr = _yazi(fr, 'CEVABINI YORUMLARA YAZ!' if not yat else 'ABONE OL, YENİ BÖLÜMÜ KAÇIRMA!', Y(1060), FS(56), renk=(255, 120, 90))
        enc.stdin.write(fr.tobytes())
        i += 1
    enc.stdin.close()
    enc.wait()
    dec.wait()
    if enc.returncode:
        raise VeoError('birleştirme (ffmpeg) başarısız')
    return out_path, dur


# ------------------------------------------------------------------ Omni (Gemini Omni Flash): tek klip, referans görselli
def _metin_json(prompt, log=print):
    """Ücretli anahtarla JSON metin (ücretsiz kota sık doluyor)."""
    for model in ('gemini-3.8-flash', 'gemini-flash-latest', 'gemini-3.7-flash'):
        try:
            d = _req(f'{BASE}/models/{model}:generateContent',
                     {'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
                      'generationConfig': {'temperature': 0.8, 'responseMimeType': 'application/json'}}, timeout=120)
            return json.loads(''.join(p.get('text', '') for p in d['candidates'][0]['content']['parts']))
        except Exception as e:
            log(f'  Plan ({model}) hata: {str(e)[:120]}')
    return None


def altyazi_cikar(klipler, chars, outdir, plan_subs=None, log=print):
    """Altyazıyı plandan değil, Omni'nin GERÇEKTEN seslendirdiği sözlerden çıkarır (zaman + metin sesle birebir).
    Klipler birleştirilmiş sesin üzerinden Gemini'ye dinletilir. Olmazsa None döner (plan altyazısı kullanılır)."""
    try:
        lst = os.path.join(outdir, 'ses_liste.txt')
        with open(lst, 'w') as f:
            f.writelines(f"file '{os.path.abspath(c)}'\n" for c in klipler)
        mp3 = os.path.join(outdir, 'ses_tum.mp3')
        subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-vn', '-ac', '1', '-ar', '16000',
                        '-b:a', '48k', mp3], check=True)
        toplam = _sure(mp3)
        with open(mp3, 'rb') as f:
            ses = base64.b64encode(f.read()).decode()
        ipucu = json.dumps([{'who': d['who'], 'text': d['text']} for d in (plan_subs or [])], ensure_ascii=False)
        prompt = (f"This is the {toplam:.1f}-second soundtrack of a Turkish animated short. Transcribe ONLY the spoken dialogue, EXACTLY the "
                  f"words actually heard (not what was planned), with precise start and end times in seconds from 0. Split long sentences "
                  f"into readable chunks of max ~8 words, each with its own exact timing. Speakers: kids {chars} (identify by voice and by the "
                  f"planned lines below), any adult or unknown voice = \"diger\". Ignore music, drums, shouts without words and sound effects. "
                  f"Planned lines (only to help identify speakers and spelling; if a line was not spoken, leave it out): {ipucu}. "
                  f'Return JSON: {{"lines": [{{"who": "tuna", "text": "Türkçe", "start": 1.2, "end": 3.4}}]}}')
        for model in ('gemini-3.8-flash', 'gemini-flash-latest'):
            try:
                d = _req(f'{BASE}/models/{model}:generateContent',
                         {'contents': [{'role': 'user', 'parts': [{'inline_data': {'mime_type': 'audio/mpeg', 'data': ses}}, {'text': prompt}]}],
                          'generationConfig': {'temperature': 0.1, 'responseMimeType': 'application/json'}}, timeout=180)
                out = json.loads(''.join(p.get('text', '') for p in d['candidates'][0]['content']['parts']))
            except Exception as e:
                log(f'  Altyazı dökümü ({model}) hata: {str(e)[:120]}')
                continue
            satirlar = []
            for l in out.get('lines') or []:
                try:
                    a, b = float(l['start']), float(l['end'])
                except (KeyError, TypeError, ValueError):
                    continue
                t = str(l.get('text', '')).strip()
                if not t or b <= a or a >= toplam:
                    continue
                who = l.get('who') if l.get('who') in chars else 'diger'
                satirlar.append({'who': who, 'text': t, 'start': max(0.0, a - 0.05), 'end': min(toplam, b + 0.15)})
            if satirlar:
                satirlar.sort(key=lambda x: x['start'])
                for x, y in zip(satirlar, satirlar[1:]):  # üst üste binmesin
                    x['end'] = min(x['end'], y['start'])
                log(f'  Altyazı sesten çıkarıldı: {len(satirlar)} satır ({model})')
                with open(os.path.join(outdir, 'altyazi_ses.json'), 'w', encoding='utf-8') as f:
                    json.dump(satirlar, f, ensure_ascii=False, indent=1)
                return satirlar
    except Exception as e:
        log(f'  Altyazı dökümü atlandı: {str(e)[:150]}')
    return None


def omni_plan(ep, sure, log=print):
    lines = [{'who': l['who'], 'text': l['text'], 'action': l.get('action'), 'sahne': l.get('sahne')} for sc in ep['scenes'] for l in sc['lines']]
    chars = list(dict.fromkeys(l['who'] for l in lines if l['who'] in KARAKTER_TARIF))[:3]
    prompt = f"""You are the director of a premium 3D animated YouTube Shorts series "Mini Dünya": finger-sized explorer kids
living behind the kitchen baseboard explore a giant house. Write ONE video-generation prompt for a single continuous {sure}-second
vertical (9:16) cinematic shot sequence based on this Turkish script. Use timecodes like [0-3s], [3-7s]... covering 0-{sure}s.
[0-2s] must already show the predicament/danger (strong hook); the last seconds deliver a surprising, funny payoff.
Use dynamic camera moves (push-in, whip pan, low angle hero shot, close-up reactions). Describe sound effects and ambience.
Characters (refer to them as <IMAGE_REF_0>, <IMAGE_REF_1>... in this order): {json.dumps([KARAKTER_TARIF[c] for c in chars])}
Keep at most 4 short spoken lines total, in TURKISH, taken/shortened from the script; write them in the prompt as
CharacterName says in Turkish: "..." at the right timecode. Benek never speaks. No on-screen text, family friendly.
Location: {ep.get('mekan') or ep['scenes'][0].get('location')} | topic: {ep.get('konu', '')}
Signature visual moment (must appear, ideally as the climax): {ep.get('gorsel_an', '')}
Small non-speaking creatures/props mentioned in the script may appear (they are not in the reference images; design them cute).
Script (each line may include "sahne" = what is on screen): {json.dumps(lines, ensure_ascii=False)}
Return JSON: {{"prompt": "...", "dialogue": [{{"who": "tuna", "text": "Türkçe", "start": 0.5, "end": 2.5}}]}}"""
    d = _metin_json(prompt, log=log) or {}
    if not d.get('prompt'):
        d = {'prompt': f"[0-{sure}s] {ep.get('konu', '')}. The characters <IMAGE_REF_0> react with big expressive animation; dynamic camera.",
             'dialogue': [{'who': l['who'], 'text': l['text'], 'start': 1 + 3 * i, 'end': 3.6 + 3 * i}
                          for i, l in enumerate([l for l in lines if l['who'] != 'benek'][:3])]}
    d['characters'] = chars
    return d


def omni(ep, outdir, cfg, log=print):
    v = cfg.get('veo') or {}
    sure = int(v.get('sure', 12))
    p = omni_plan(ep, sure, log=log)
    with open(os.path.join(outdir, 'omni_plan.json'), 'w', encoding='utf-8') as f:
        json.dump(p, f, ensure_ascii=False, indent=1)
    out = os.path.join(outdir, 'omni_klip.mp4')
    return omni_cagri(p['characters'], p['prompt'], sure, out, cfg, log=log), p


SON_ID = {}


def _video_cikar(d):
    data = None
    for stp in d.get('steps', []) or []:
        for c in stp.get('content', []) or []:
            if c.get('type') == 'video' and c.get('data'):
                data = c['data']
    return data or (d.get('output_video') or {}).get('data')


def uzat(prev_id, chars, prompt, sure, out, cfg, log=print, oran='9:16'):
    """Omni ile önceki üretimi kesintisiz uzatır (aynı sahnenin devamı). Çıktı yolunu döndürür."""
    v = cfg.get('veo') or {}
    inp = []
    for c in chars:  # karakterler uzatmada da referans olarak verilir (tutarlılık)
        with open(_ref(c), 'rb') as f:
            inp.append({'type': 'image', 'data': base64.b64encode(f.read()).decode(), 'mime_type': 'image/jpeg'})
    inp.append({'type': 'text', 'text': f"Continue the scene seamlessly for {sure} more seconds (0s = start of the new part). "
                                        f"Keep the characters' faces exactly as in the references.{_kiyafet_metni(chars)} {_stil()} {prompt} {_ses()}"})
    last = None
    for model in v.get('omni_modeller', ['gemini-omni-1.2-flash']):
        for rf in ({'type': 'video', 'aspect_ratio': oran, 'resolution': v.get('cozunurluk', '720p'), 'duration': f'{sure}s'},
                   {'type': 'video', 'resolution': v.get('cozunurluk', '720p')}, None):
            body = {'model': model, 'previous_interaction_id': prev_id, 'input': inp, 'background': False, 'store': True,
                    'stream': False}  # API: previous_interaction_id ile 'task' gönderilemez
            if rf:
                body['response_format'] = rf
            t0 = time.time()
            try:
                d = _req(f'{BASE}/interactions', body, timeout=900)
            except VeoError as e:
                last = e
                log(f'  Omni uzatma hata: {str(e)[:200]}')
                continue
            data = _video_cikar(d)
            if not data:
                last = VeoError(f"uzatma video döndürmedi: {str(d)[:200]}")
                continue
            with open(out, 'wb') as f:
                f.write(base64.b64decode(data))
            SON_ID['id'] = d.get('id')
            log(f'  Omni uzatma hazır ({time.time() - t0:.0f} sn)')
            return out
    raise VeoError(f'uzatma olmadı: {last}')


def omni_cagri(chars, prompt, sure, out, cfg, log=print, oran='9:16', sureklilik=None, store=False):
    """Tek Omni üretimi: karakter referansları (+ isteğe bağlı önceki klibin son karesi) ile video; dosya yolunu döndürür."""
    v = cfg.get('veo') or {}
    inp = []
    for c in chars:
        with open(_ref(c), 'rb') as f:
            inp.append({'type': 'image', 'data': base64.b64encode(f.read()).decode(), 'mime_type': 'image/jpeg'})
    ek = ''
    if sureklilik and os.path.exists(sureklilik):
        with open(sureklilik, 'rb') as f:
            inp.append({'type': 'image', 'data': base64.b64encode(f.read()).decode(), 'mime_type': 'image/jpeg'})
        ek = (f' The last reference image (<IMAGE_REF_{len(chars)}>) is the final frame of the previous shot: continue seamlessly '
              f'from it (same location, lighting, character positions and outfits).')
    txt = (f"Use the given images as references (not as literal frames); keep the characters' exact look in every shot.{ek} "
           f"{_kiyafet_metni(chars)} {_stil()} {sure}-second video. {prompt} {_ses()}")
    inp.append({'type': 'text', 'text': txt})
    last = None
    for model in v.get('omni_modeller', ['gemini-omni-1.2-flash', 'gemini-omni-1.1-flash']):
        for rf in ({'type': 'video', 'aspect_ratio': oran, 'resolution': v.get('cozunurluk', '720p'), 'duration': f'{sure}s'},
                   {'type': 'video', 'aspect_ratio': oran, 'resolution': v.get('cozunurluk', '720p')}):
            body = {'model': model, 'input': inp, 'response_format': rf, 'background': False, 'store': store, 'stream': False,
                    'generation_config': {'video_config': {'task': 'reference_to_video'}}}
            t0 = time.time()
            try:
                d = _req(f'{BASE}/interactions', body, timeout=900)
            except VeoError as e:
                last = e
                log(f'  Omni ({model}) hata: {str(e)[:200]}')
                continue
            data = None
            for stp in d.get('steps', []) or []:
                for c in stp.get('content', []) or []:
                    if c.get('type') == 'video' and c.get('data'):
                        data = c['data']
            data = data or (d.get('output_video') or {}).get('data')
            if not data:
                last = VeoError(f"Omni video döndürmedi: durum={d.get('status')} {str(d)[:300]}")
                log(f'  {last}')
                continue
            with open(out, 'wb') as f:
                f.write(base64.b64decode(data))
            SON_ID['id'] = d.get('id')
            log(f'  Omni klip hazır ({model}, {time.time() - t0:.0f} sn)')
            return out
    raise VeoError(f'Omni üretilemedi: {last}')


def _sure(path):
    return float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
                                capture_output=True, text=True).stdout.strip() or 0)


def perde_plan(ep, perdeler, log=print):
    """Bölümü kesintisiz bir sahnenin ardışık perdelerine böler (ilk perde üretim, diğerleri uzatma)."""
    lines = [{'who': l['who'], 'text': l['text'], 'action': l.get('action'), 'sahne': l.get('sahne')} for sc in ep['scenes'] for l in sc['lines']]
    chars = list(dict.fromkeys(l['who'] for l in lines if l['who'] in KARAKTER_TARIF))[:3]
    adlar = ep.get('perde_adlari') or ['HOOK + SETUP: within the first 2 seconds the characters are already in the predicament; establish place and goal',
             'COMPLICATION: they try a plan, it goes wrong in a funny way, stakes rise',
             'CLIMAX: the boldest attempt, the signature visual moment, peak tension and action',
             'PAYOFF: surprising clever/funny resolution, characters celebrate, a final gag or hint of the next mystery']
    tanim = ep.get('yonetmen_notu') or ('a premium 3D animated family series (finger-sized explorer kids in a giant house)')
    prompt = f"""You are the director and editor of "Mini Dünya", {tanim}. Plan ONE continuous vertical (9:16) YouTube Short of {sum(perdeler)} seconds made of {len(perdeler)} consecutive parts
generated as a single take that is EXTENDED part by part (each part continues exactly where the previous ended, same location,
same lighting, same characters, no jumps). Durations: {perdeler} seconds. Parts: {json.dumps(adlar[:len(perdeler)])}.
The story must have clear cause and effect: every part follows logically from the previous one. Use expressive acting, dynamic but
motivated camera moves (push-ins, follow shots, low angles), sound effects. A cut to a closer angle is allowed inside a part only if
stated as "the camera cuts to a close-up of ...". Use timecodes relative to the part start, e.g. [0-4s].
Characters (in this order as <IMAGE_REF_0>...): {json.dumps([_tarif(c) for c in chars], ensure_ascii=False)}. Benek never speaks.
TIMING RULE (critical): every spoken line must START after 0.5s and FINISH at least 1.5 seconds before its part ends (the last part:
at least 2 seconds before the end), so no word is ever cut by a part boundary. Keep lines short enough to be spoken calmly in the time given.
Spoken lines: TURKISH only, short, taken/adapted from the script, max 2 per part, written in the prompt as
CharacterName says in Turkish: "...". No on-screen text, no labels, family friendly.
Place: {ep.get('mekan') or ep['scenes'][0].get('location')} | style: {_stil()} | topic: {ep.get('konu', '')} | signature moment: {ep.get('gorsel_an', '')}
Script: {json.dumps(lines, ensure_ascii=False)}
Return JSON: {{"parts": [{{"prompt": "English prompt for this part", "dialogue": [{{"who": "tuna", "text": "Türkçe", "start": 1.0, "end": 3.2}}]}}]}}
(dialogue start/end are seconds within that part)."""
    d = _metin_json(prompt, log=log) or {}
    parts = [x for x in (d.get('parts') or []) if x.get('prompt')][:len(perdeler)]
    if len(parts) < len(perdeler):
        raise VeoError(f'perde planı eksik ({len(parts)}/{len(perdeler)})')
    return chars, parts


def uret_perdeli(ep, outdir, cfg, log=print, oran='9:16'):
    """40-50 sn Shorts: 15 sn açılış + kesintisiz uzatmalar; uzatma olmazsa son kareden süreklilikli yeni çekim."""
    v = cfg.get('veo') or {}
    perdeler = ep.get('perdeler') or v.get('perdeler') or [15, 10, 10, 10]
    t0 = time.time()
    os.makedirs(outdir, exist_ok=True)
    OZEL.clear()
    OZEL.update({k: ep[k] for k in ('stil', 'ses', 'kiyafet') if ep.get(k)})
    if OZEL:
        log(f"  Bölüme özel mod: {', '.join(OZEL)}")
    chars, parts = perde_plan(ep, perdeler, log=log)
    if OZEL.get('kiyafet'):
        OZEL['ref'] = kostum_referanslari(chars, outdir, log=log)
    tekrar_hak = int(v.get('perde_tekrar', 1))  # bütçe tavanı: en fazla bu kadar perde yeniden çekilir
    with open(os.path.join(outdir, 'omni_perde_plan.json'), 'w', encoding='utf-8') as f:
        json.dump({'characters': chars, 'parts': parts}, f, ensure_ascii=False, indent=1)
    parcalar, subs, offset, prev = [], [], 0.0, None
    for i, (sure, p) in enumerate(zip(perdeler, parts)):
        out = os.path.join(outdir, f'omni_perde_{i}.mp4')
        tam_mi = False
        prev_once, zincir_once = prev, (zincir if i else 0)
        for deneme in range(2):
            zincir = zincir_once
            tam_mi = False
            if i == 0:
                omni_cagri(chars, p['prompt'], sure, out, cfg, log=log, oran=oran, store=True)
                zincir = sure
                zincir_bas_idx, zincir_bas_ofs = 0, 0.0
            elif zincir + sure > ZINCIR_MAX:  # Omni 30 sn'den uzun videoyu uzatmıyor: son kareden yeni zincir
                log(f'  Zincir {zincir} sn: son kareden devam eden yeni çekim')
                son = os.path.join(outdir, f'omni_perde_{i - 1}_son.jpg')
                subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-sseof', '-0.1', '-i', parcalar[-1], '-frames:v', '1', son], check=True)
                omni_cagri(chars, p['prompt'], sure, out, cfg, log=log, oran=oran, sureklilik=son, store=True)
                zincir = sure
                zincir_bas_idx, zincir_bas_ofs = len(parcalar), offset
            else:
                zincir += sure
                try:
                    uzat(prev, chars, p['prompt'], sure, out, cfg, log=log, oran=oran)
                    d_new = _sure(out)
                    tam_mi = d_new > sure + 1.5  # uzatma, zincirin tamamını (önceki perdeler + yeni) döndürdüyse
                except VeoError as e:
                    log(f'  Uzatma olmadı, son kareden devam eden yeni çekim: {str(e)[:120]}')
                    son = os.path.join(outdir, f'omni_perde_{i - 1}_son.jpg')
                    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-sseof', '-0.1', '-i', parcalar[-1], '-frames:v', '1', son], check=True)
                    omni_cagri(chars, p['prompt'], sure, out, cfg, log=log, oran=oran, sureklilik=son, store=True)
                    zincir = sure
                    zincir_bas_idx, zincir_bas_ofs = len(parcalar), offset
            puan, sorun = perde_kontrol(out, chars, p['prompt'], log=log)
            log(f'  Perde {i + 1} kontrol: {puan}/10 {sorun[:100]}')
            if puan >= 7 or tekrar_hak <= 0 or deneme == 1:
                break
            tekrar_hak -= 1
            prev = prev_once
            log(f'  Perde {i + 1} yeniden çekiliyor (kalan hak {tekrar_hak})')
        prev = SON_ID.get('id')
        d = _sure(out)
        bas = offset if not tam_mi else offset  # repliğin perde içi zamanı -> toplam zaman
        for dl in p.get('dialogue', [])[:2]:
            if dl.get('who') != 'benek' and dl.get('text'):
                a = bas + float(dl.get('start', 0))
                subs.append({'who': dl['who'], 'text': dl['text'], 'start': a, 'end': bas + float(dl.get('end', 0) or dl.get('start', 0) + 2.5)})
        if tam_mi:  # zincirin önceki parçalarını at, yerine tam zincir videosunu koy (aynı görüntü iki kez oynamasın)
            parcalar = parcalar[:zincir_bas_idx] + [out]
            offset = zincir_bas_ofs + d
        else:
            parcalar.append(out)
            offset += d
        log(f'  Perde {i + 1}/{len(perdeler)} tamam, toplam {offset:.1f} sn')
    gercek = altyazi_cikar(parcalar, chars, outdir, plan_subs=subs, log=log)
    if gercek:
        subs = gercek
    else:
        log('  Uyarı: altyazı plandan (sesle tam uyumlu olmayabilir)')
    ham_parcalar = list(parcalar)
    if v.get('buyut') and v.get('cozunurluk', '720p') in ('360p', '480p'):
        try:
            from . import buyut as _b
            parcalar = [_b.buyut(c, c.replace('.mp4', '_hd.mp4'), log=log) for c in parcalar]
        except Exception as e:
            log(f'  Büyütme atlandı (ham klip kullanılacak): {str(e)[:150]}')
            parcalar = ham_parcalar
    final, dur = birlestir(parcalar, [{'dialogue': subs}], ep, os.path.join(outdir, 'video.mp4'), log=log, zamanli=True)
    fn = os.path.join(outdir, 'omni_kare.jpg')
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-ss', str(min(1.0, _sure(parcalar[0]) / 2)), '-i', parcalar[0], '-frames:v', '1', fn], check=True)
    k = cv2.resize(cv2.imread(fn), (1080, 1920))[..., ::-1]
    k = _yazi(np.ascontiguousarray(k), (ep.get('kapak_yazisi') or ep['baslik']).upper(), 160, 104)
    thumb = os.path.join(outdir, 'kapak.jpg')
    cv2.imwrite(thumb, k[..., ::-1], [cv2.IMWRITE_JPEG_QUALITY, 90])
    log(f'Omni perdeli Shorts hazır: {dur:.1f} sn, {(time.time() - t0) / 60:.1f} dk, tahmini maliyet ~${FIYAT.get(v.get('cozunurluk', '720p'), 0.07) * dur:.2f}')
    OZEL.clear()
    return final, thumb, dur


ZINCIR_MAX = 30  # Omni uzatma sınırı (sn)
FIYAT = {'360p': 0.023, '720p': 0.07, '1080p': 0.104}  # Omni saniye fiyatı ($)


def uret(ep, outdir, cfg, log=print):
    v = cfg.get('veo') or {}
    if v.get('motor', 'omni') == 'omni' and v.get('perdeler'):
        return uret_perdeli(ep, outdir, cfg, log=log)
    if v.get('motor', 'omni') == 'omni':
        return uret_omni(ep, outdir, cfg, log=log)
    return uret_veo(ep, outdir, cfg, log=log)


def uret_omni(ep, outdir, cfg, log=print):
    t0 = time.time()
    os.makedirs(outdir, exist_ok=True)
    klip, p = omni(ep, outdir, cfg, log=log)
    shots = [{'dialogue': p.get('dialogue', [])}]
    final, dur = birlestir([klip], shots, ep, os.path.join(outdir, 'video.mp4'), log=log, zamanli=True)
    # kapak: klibin 1. saniyesinden kare + kanca yazısı
    fn = os.path.join(outdir, 'omni_kare.jpg')
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-ss', '1.0', '-i', klip, '-frames:v', '1', fn], check=True)
    k = cv2.resize(cv2.imread(fn), (1080, 1920))[..., ::-1]
    k = _yazi(np.ascontiguousarray(k), (ep.get('kapak_yazisi') or ep['baslik']).upper(), 160, 104)
    thumb = os.path.join(outdir, 'kapak.jpg')
    cv2.imwrite(thumb, k[..., ::-1], [cv2.IMWRITE_JPEG_QUALITY, 90])
    log(f'Omni bölümü hazır: {dur:.1f} sn, {(time.time() - t0) / 60:.1f} dk, tahmini maliyet ~${0.07 * dur:.2f}')
    return final, thumb, dur


def uzun_plan(ep, n_seg, seg_sure, log=print):
    """Uzun bölüm senaryosunu n_seg adet ardışık Omni çekimine böler (her biri seg_sure sn)."""
    sahneler = [{'location': sc.get('location'), 'characters': sc.get('characters'),
                 'lines': [{'who': l['who'], 'text': l['text'], 'action': l.get('action'), 'sahne': l.get('sahne')} for l in sc['lines']]} for sc in ep['scenes']]
    prompt = f"""You are the director of "Mini Dünya", a premium 3D animated family series (finger-sized explorer kids in a giant house).
Turn this Turkish episode into EXACTLY {n_seg} consecutive cinematic shots of {seg_sure} seconds each (total {n_seg * seg_sure} s,
horizontal 16:9). The shots must flow continuously like one film: each shot starts where the previous ended. Start with a strong
hook (danger/predicament in the first seconds), build adventure and comedy, end with a satisfying payoff and a hint for the next episode.
For each shot: up to 3 characters (ids from: {list(KARAKTER_TARIF)}), an English Veo/Omni prompt with timecodes [0-5s] etc., dynamic
camera, sound effects; spoken lines in TURKISH written as CharacterName says in Turkish: "..." (max 3 lines per shot, from the script,
shortened). Benek never speaks. No on-screen text, family friendly.
Character looks: {json.dumps(KARAKTER_TARIF, ensure_ascii=False)}
Episode: {ep.get('baslik')} | topic: {ep.get('konu', '')} | place: {ep.get('mekan', '')}
Signature visual moment (build up to it): {ep.get('gorsel_an', '')}
Script: {json.dumps(sahneler, ensure_ascii=False)}
Return JSON: {{"shots": [{{"characters": ["tuna"], "prompt": "...", "dialogue": [{{"who": "tuna", "text": "Türkçe", "start": 1.0, "end": 3.5}}]}}]}}
(dialogue start/end are seconds within that shot)."""
    d = _metin_json(prompt, log=log) or {}
    shots = [x for x in (d.get('shots') or []) if x.get('prompt')]
    if len(shots) < max(2, n_seg // 2):
        raise VeoError(f'uzun plan yetersiz ({len(shots)} çekim)')
    for x in shots:
        x['characters'] = [c for c in (x.get('characters') or []) if c in KARAKTER_TARIF][:3] or ['tuna']
    return shots[:n_seg]


def uret_uzun(ep, outdir, cfg, log=print):
    """Haftalık uzun video (3-5 dk) Omni ile: ardışık çekimler, her çekim önceki çekimin son karesinden devam eder."""
    v = cfg.get('veo') or {}
    t0 = time.time()
    os.makedirs(outdir, exist_ok=True)
    seg = int(v.get('uzun_segment', 15))
    n = max(int(v.get('uzun_min_cekim', 6)), int(v.get('uzun_sure', 240)) // seg)
    shots = uzun_plan(ep, n, seg, log=log)
    with open(os.path.join(outdir, 'omni_uzun_plan.json'), 'w', encoding='utf-8') as f:
        json.dump(shots, f, ensure_ascii=False, indent=1)
    clips, son, subs_all, offset = [], None, [], 0.0
    for i, sh in enumerate(shots):
        out = os.path.join(outdir, f'omni_uzun_{i:02d}.mp4')
        try:
            omni_cagri(sh['characters'], sh['prompt'], seg, out, cfg, log=log, oran='16:9', sureklilik=son)
        except VeoError as e:
            if len(clips) >= max(2, n * 2 // 3):  # yeterince çekim varsa kısa bitir
                log(f'  Çekim {i} üretilemedi, {len(clips)} çekimle bitiriliyor: {str(e)[:120]}')
                break
            raise
        d = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', out],
                                 capture_output=True, text=True).stdout.strip() or seg)
        for dl in sh.get('dialogue', []):
            subs_all.append({'who': dl.get('who'), 'text': dl.get('text', ''), 'start': offset + float(dl.get('start', 0)),
                             'end': offset + float(dl.get('end', 0) or float(dl.get('start', 0)) + 2.5)})
        offset += d
        son = os.path.join(outdir, f'omni_uzun_{i:02d}_son.jpg')
        subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-sseof', '-0.1', '-i', out, '-frames:v', '1', son], check=True)
        clips.append(out)
        log(f'  Uzun video: {len(clips)}/{len(shots)} çekim, {offset:.0f} sn')
    final, dur = birlestir(clips, [{'dialogue': subs_all}], ep, os.path.join(outdir, 'video.mp4'), log=log, zamanli=True, W=1920, H=1080)
    fn = os.path.join(outdir, 'omni_kare.jpg')
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-ss', '2.0', '-i', clips[0], '-frames:v', '1', fn], check=True)
    k = cv2.resize(cv2.imread(fn), (1280, 720))[..., ::-1]
    k = _yazi(np.ascontiguousarray(k), (ep.get('kapak_yazisi') or ep['baslik']).upper(), 60, 84, max_w=0.9)
    thumb = os.path.join(outdir, 'kapak.jpg')
    cv2.imwrite(thumb, k[..., ::-1], [cv2.IMWRITE_JPEG_QUALITY, 90])
    log(f'Omni uzun video hazır: {dur / 60:.1f} dk, {(time.time() - t0) / 60:.0f} dk sürdü, tahmini maliyet ~${0.07 * dur:.2f}')
    return final, thumb, dur


def uret_veo(ep, outdir, cfg, log=print):
    """Veo bölümünü üretir: (video, kapak, süre). Hata -> VeoError."""
    t0 = time.time()
    os.makedirs(outdir, exist_ok=True)
    shots = plan(ep, cfg, log=log)
    with open(os.path.join(outdir, 'veo_plan.json'), 'w', encoding='utf-8') as f:
        json.dump(shots, f, ensure_ascii=False, indent=1)
    clips = []
    for i, s in enumerate(shots):
        img = ilk_kare(s, os.path.join(outdir, f'veo_kare_{i}.png'), log=log)
        clips.append(video(s, img, os.path.join(outdir, f'veo_klip_{i}.mp4'), cfg, log=log))
    final, dur = birlestir(clips, shots, ep, os.path.join(outdir, 'video.mp4'), log=log)
    # kapak: ilk karenin üstüne kanca yazısı
    k = cv2.imread(os.path.join(outdir, 'veo_kare_0.png'))
    k = cv2.resize(k, (1080, 1920))[..., ::-1]
    k = _yazi(np.ascontiguousarray(k), (ep.get('kapak_yazisi') or ep['baslik']).upper(), 160, 104)
    thumb = os.path.join(outdir, 'kapak.jpg')
    cv2.imwrite(thumb, k[..., ::-1], [cv2.IMWRITE_JPEG_QUALITY, 90])
    log(f'Veo bölümü hazır: {dur:.1f} sn, {(time.time() - t0) / 60:.1f} dk, tahmini maliyet ~${0.05 * 8 * len(clips) + 0.04 * len(clips):.2f}')
    return final, thumb, dur


def test(log=print):
    """gorev=veo_test: son bölümden yayınlamadan Veo videosu üret; videoyu ve kareleri state/'e yaz (önizleme)."""
    import glob
    import shutil
    from .main import load_cfg
    cfg = load_cfg()
    try:  # tanı: bu anahtarla açık olan görsel/video modelleri
        d = _req(f'{BASE}/models?pageSize=200')
        log('Modeller: ' + ', '.join(f"{m['name'].split('/')[-1]}[{','.join(m.get('supportedGenerationMethods', []))}]"
                                     for m in d.get('models', []) if any(k in m['name'] for k in ('veo', 'video', 'image', 'imagen', 'banana'))))
    except Exception as e:
        log(f'Model listesi hatası: {e}')
    ep_path = sorted(glob.glob(os.path.join(paths.EPISODES, '*.json')))[-1]
    with open(ep_path, encoding='utf-8') as f:
        ep = json.load(f)
    out = os.path.join(paths.OUTPUT, 'veo_test')
    final, thumb, dur = uret(ep, out, cfg, log=log)
    shutil.copy(final, os.path.join(paths.STATE, 'veo_test.mp4'))
    shutil.copy(thumb, os.path.join(paths.STATE, 'veo_test_kapak.jpg'))
    log(f'Test: {ep_path} -> state/veo_test.mp4 ({dur:.1f} sn)')


def test_uzun(log=print):
    """gorev=veo_test uzun: ucuz uzun video testi (2 x 6 sn yatay çekim, süreklilik + birleştirme)."""
    import glob
    import shutil
    from .main import load_cfg
    cfg = load_cfg()
    cfg['veo'].update(uzun_sure=12, uzun_segment=6, uzun_min_cekim=2)
    eps = sorted(glob.glob(os.path.join(paths.EPISODES, '*.json')))
    ep_path = next((p for p in reversed(eps) if 'uzun' in json.load(open(p, encoding='utf-8')).get('tur', '')), eps[-1])
    with open(ep_path, encoding='utf-8') as f:
        ep = json.load(f)
    out = os.path.join(paths.OUTPUT, 'veo_test_uzun')
    final, thumb, dur = uret_uzun(ep, out, cfg, log=log)
    shutil.copy(final, os.path.join(paths.STATE, 'veo_test_uzun.mp4'))
    log(f'Test uzun: {ep_path} -> state/veo_test_uzun.mp4 ({dur:.1f} sn)')


if __name__ == '__main__':
    import sys
    test_uzun() if 'uzun' in sys.argv else test()
