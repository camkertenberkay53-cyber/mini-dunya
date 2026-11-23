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
REF_DIR = os.path.join(paths.ROOT, 'assets', 'ref')
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
        'matching the reference images. Family friendly, no text, no logos, no brands.')


class VeoError(Exception):
    pass


def acik(cfg, slot):
    v = cfg.get('veo') or {}
    return bool(v.get('acik')) and bool(os.environ.get('GEMINI_IMAGE_KEY')) and slot == v.get('slot')


def _key():
    return os.environ['GEMINI_IMAGE_KEY']


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
    for model in v.get('modeller', ['veo-3.1-lite-generate-preview', 'veo-3.1-fast-generate-preview']):
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


def birlestir(clips, shots, ep, out_path, log=print):
    W, H, FPS = 1080, 1920, 30
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
    for i, s in enumerate(shots):
        ds = [d for d in s.get('dialogue', [])[:2] if d.get('who') != 'benek']
        for k, d in enumerate(ds):
            a = i * per + 0.6 + k * (per - 0.8) / max(1, len(ds))
            subs.append((a, a + (per - 0.8) / max(1, len(ds)) - 0.15, d['who'], d['text']))
    kanca = (ep.get('kapak_yazisi') or ep.get('baslik', '')).upper()
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
        if t < 3.0:
            fr = _yazi(fr, kanca, 150, 96)
        for a, b, who, text in subs:
            if a <= t < b and t < dur - 2.4:
                col = CHARS.get(who, {}).get('color', (255, 255, 255))
                fr = _yazi(fr, CHARS.get(who, {}).get('name', who.upper()), 1390, 50, renk=tuple(col))
                fr = _yazi(fr, text, 1455, 62, renk=(255, 255, 255))
        if t > dur - 2.4:
            k = min(1.0, (t - (dur - 2.4)) / 0.4)
            fr = (fr * (1 - 0.55 * k)).astype(np.uint8)
            fr = _yazi(fr, 'MİNİ DÜNYA', 640, 110)
            fr = _yazi(fr, soru, 820, 70, renk=(255, 255, 255))
            fr = _yazi(fr, 'CEVABINI YORUMLARA YAZ!', 1060, 56, renk=(255, 120, 90))
        enc.stdin.write(fr.tobytes())
        i += 1
    enc.stdin.close()
    enc.wait()
    dec.wait()
    if enc.returncode:
        raise VeoError('birleştirme (ffmpeg) başarısız')
    return out_path, dur


def uret(ep, outdir, cfg, log=print):
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
    ep_path = sorted(glob.glob(os.path.join(paths.EPISODES, '*.json')))[-1]
    with open(ep_path, encoding='utf-8') as f:
        ep = json.load(f)
    out = os.path.join(paths.OUTPUT, 'veo_test')
    final, thumb, dur = uret(ep, out, cfg, log=log)
    shutil.copy(final, os.path.join(paths.STATE, 'veo_test.mp4'))
    shutil.copy(thumb, os.path.join(paths.STATE, 'veo_test_kapak.jpg'))
    log(f'Test: {ep_path} -> state/veo_test.mp4 ({dur:.1f} sn)')


if __name__ == '__main__':
    test()
