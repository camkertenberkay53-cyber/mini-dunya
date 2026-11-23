"""Boyalı arka plan: her bölüm için o bölümün olayına özel, Nano Banana ile üretilmiş 9:16 sahne resmi.
Karakterler kendi motorumuzda çizilir ve resmin önüne konur; resim büyütülüp hafif odak dışı bırakılır
(dev dünya / parmak boyu kahraman ölçeği ve stil uyumu için).
Ayrı ve ücretli bir anahtar kullanır (GEMINI_IMAGE_KEY); ücretsiz senaryo/ses anahtarı etkilenmez.
Maliyet kontrolü: günlük ve aylık görsel sınırı state/boya_sayac.json'da tutulur."""
import base64
import datetime as dt
import json
import os
import urllib.request

import cv2
import numpy as np

from . import paths

MEKAN = {
    'tezgah': 'a kitchen countertop seen from a tiny explorer\'s eye level: giant mugs, cutting board, utensils towering like buildings',
    'lavabo': 'a kitchen sink area: giant faucet, soap bubbles, water droplets, a sponge as big as a hill',
    'buzdolabi': 'inside an open refrigerator: giant jars, frosty shelves, cold blue light mixed with warm kitchen light',
    'baharat': 'a kitchen spice rack: giant glass spice jars with cork and metal lids, wooden shelf',
    'zemin': 'a kitchen floor seen from ground level: giant chair legs, tiles stretching like a plain, crumbs like rocks',
    'cekmece': 'inside an open kitchen drawer: giant spoons, forks, rubber bands, paper clips, matchboxes',
    'lonca': 'a cozy hidden workshop behind a baseboard: tiny maps pinned on walls, thimble lamps, thread-spool tables',
}
GUNLUK_SINIR = 8
AYLIK_SINIR = 160


def acik(cfg, slot):
    b = cfg.get('boya') or {}
    return bool(b.get('acik')) and bool(os.environ.get('GEMINI_IMAGE_KEY')) and slot in (b.get('slotlar') or [])


def _sayac():
    p = os.path.join(paths.STATE, 'boya_sayac.json')
    try:
        with open(p, encoding='utf-8') as f:
            return p, json.load(f)
    except Exception:
        return p, {}


def _sinir_ok():
    _, s = _sayac()
    bugun, ay = dt.date.today().isoformat(), dt.date.today().isoformat()[:7]
    return s.get('gun', {}).get(bugun, 0) < GUNLUK_SINIR and s.get('ay', {}).get(ay, 0) < AYLIK_SINIR


def _say():
    p, s = _sayac()
    bugun, ay = dt.date.today().isoformat(), dt.date.today().isoformat()[:7]
    s.setdefault('gun', {})[bugun] = s.get('gun', {}).get(bugun, 0) + 1
    s.setdefault('ay', {})[ay] = s.get('ay', {}).get(ay, 0) + 1
    s['gun'] = {k: v for k, v in s['gun'].items() if k >= (dt.date.today() - dt.timedelta(days=40)).isoformat()}
    os.makedirs(paths.STATE, exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(s, f, ensure_ascii=False, indent=1)


def istem(ep):
    loc = ep['scenes'][0].get('location', 'tezgah')
    return f"""Vertical 9:16 background plate for a premium 2D animated family series (storybook painting quality, warm cinematic light,
rich textures, soft depth). Setting: {MEKAN.get(loc, MEKAN['tezgah'])}. Everything is seen from the eye level of a finger-sized
explorer, so ordinary household objects look gigantic.
What is happening in this episode (show the environment and the event, NOT any character): {ep.get('konu', '')}
Composition rules: the bottom third of the image is a flat, empty, walkable surface (the floor/shelf/counter the tiny heroes stand on),
clear of objects. Big dramatic shapes in the upper two thirds. No people, no animals, no characters, no faces, no hands.
No text, no letters, no labels with writing, no logos, no brands. Family friendly."""


def _modeller(key):
    try:
        with urllib.request.urlopen(f'https://generativelanguage.googleapis.com/v1beta/models?key={key}&pageSize=200', timeout=30) as r:
            ms = [m['name'].split('/')[-1] for m in json.loads(r.read()).get('models', [])]
    except Exception:
        ms = []
    img = [m for m in ms if 'image' in m or 'banana' in m]
    tercih = ['gemini-nano-banana-2.1', 'nano-banana', 'flash-image', 'image']
    img.sort(key=lambda m: next((i for i, t in enumerate(tercih) if t in m), 9) + (0.5 if 'pro' in m else 0))
    return img or ['gemini-nano-banana-2.1']


def uret(ep, outdir, cfg, log=print):
    """Bölüm için arka plan üretir; yolunu döndürür ya da None (hata/sınır: normal çizim arka plan kullanılır)."""
    key = os.environ.get('GEMINI_IMAGE_KEY', '')
    if not key:
        return None
    if not _sinir_ok():
        log('Boyalı arka plan: günlük/aylık sınır doldu, çizim arka plan kullanılıyor')
        return None
    from .writer import _post
    body = {'contents': [{'role': 'user', 'parts': [{'text': istem(ep)}]}],
            'generationConfig': {'responseModalities': ['IMAGE'],
                                 'imageConfig': {'aspectRatio': '9:16', 'imageSize': (cfg.get('boya') or {}).get('boyut', '2K')}}}
    for model in _modeller(key)[:2]:
        try:
            d = _post(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}', body, timeout=180)
            for p in d['candidates'][0]['content']['parts']:
                data = (p.get('inlineData') or p.get('inline_data') or {}).get('data')
                if data:
                    fn = os.path.join(outdir, 'arka_plan.png')
                    with open(fn, 'wb') as f:
                        f.write(base64.b64decode(data))
                    _say()
                    img = cv2.imread(fn)
                    log(f'Boyalı arka plan üretildi ({model}, {img.shape[1]}x{img.shape[0]})')
                    return fn
            log(f'  Boya ({model}): görsel dönmedi')
        except Exception as e:
            log(f'  Boya ({model}) hata: {str(e)[:150]}')
    return None


class Boya:
    """Renderer için: resmi kamera hareketine göre (hafif paralaks) ekrana yerleştirir."""
    ZOOM = 1.85
    ZEMIN = 0.73  # resimde karakterlerin bastığı yüzeyin yüksekliği (oran)

    def __init__(self, path, ground_y):
        img = cv2.imread(path)
        img = cv2.GaussianBlur(img, (0, 0), max(1.2, img.shape[1] / 600))  # sinematik odak dışı
        self.img = img[..., ::-1].astype(np.float32) / 255
        self.ground_y = ground_y

    def draw(self, cam):
        ih, iw = self.img.shape[:2]
        W, H = cam.W, cam.H
        _, gy = cam.p(cam.cx, self.ground_y)
        s = max(W / iw, H / ih) * self.ZOOM * (cam.z / 0.9) ** 0.35
        dx = -(cam.cx - 550) * cam.z * 0.35
        M = np.array([[s, 0, W / 2 - iw * 0.5 * s + dx + cam.sx * 0.5],
                      [0, s, gy - ih * self.ZEMIN * s + cam.sy * 0.5]], np.float32)
        return cv2.warpAffine(self.img, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def test(ep_path, outdir='output/boya_test', log=print):
    """Ücretsiz kota harcamadan: kayıtlı bir bölüm için arka plan üret, birkaç kare çiz (gorev=boya_test)."""
    import wave
    from .engine import render
    from .main import load_cfg
    cfg = load_cfg()
    os.makedirs(outdir, exist_ok=True)
    with open(ep_path, encoding='utf-8') as f:
        ep = json.load(f)
    bg = uret(ep, outdir, cfg, log=log)
    if not bg:
        raise SystemExit('Arka plan üretilemedi (anahtar/ödeme kontrol edilmeli)')
    wavs = {}
    for si, sc in enumerate(ep['scenes']):
        for li, ln in enumerate(sc['lines']):
            p = os.path.join(outdir, f'w{si}_{li}.wav')
            n = int(24000 * (0.8 + 0.3 * len(ln['text'].split())))
            with wave.open(p, 'wb') as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
                w.writeframes((np.sin(np.arange(n) * 0.05) * 3000).astype(np.int16).tobytes())
            wavs[(si, li)] = p
    tl = render.build_timeline(ep, wavs)
    r = render.Renderer(ep, tl, 1080, 1920, {'subtitle': ep.get('baslik', ''), 'boya': bg})
    segs = [s for s in tl['segments'] if s['scene'] == 0]
    for i, s in enumerate(segs[::2][:4]):
        f = r.frame(s['start'] + s['dur'] * 0.6)
        cv2.imwrite(os.path.join(outdir, f'kare_{i}.jpg'), (np.clip(f, 0, 1) * 255).astype(np.uint8)[..., ::-1], [cv2.IMWRITE_JPEG_QUALITY, 88])
    ims = [cv2.resize(cv2.imread(bg), (540, 960))] + [cv2.resize(cv2.imread(os.path.join(outdir, f'kare_{i}.jpg')), (540, 960)) for i in range(min(4, len(segs[::2])))]
    cv2.imwrite(os.path.join(paths.STATE, 'onizleme.jpg'), np.hstack(ims), [cv2.IMWRITE_JPEG_QUALITY, 82])
    log(f'Test kareleri: {outdir} + state/onizleme.jpg')


if __name__ == '__main__':
    import glob
    import sys
    test(sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob(os.path.join(paths.EPISODES, '*.json')))[-1])
