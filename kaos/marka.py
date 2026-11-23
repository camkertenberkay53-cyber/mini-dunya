"""Kanal görselleri ve resmî karakter referansları (Omni tarzı), Nano Banana ile (GEMINI_IMAGE_KEY).
gorev=marka -> state/marka/ altına: karakter referansları (5), kanal kapağı sanatı (16:9), profil sanatı (1:1).
Yazılar sonradan (PIL) eklenir; yapay zekâ görselinde yazı yok."""
import base64
import json
import os

from . import paths
from .veo import KARAKTER_TARIF, _req, BASE
REF_DIR = os.path.join(paths.ROOT, 'assets', 'ref')  # marka üretimi ham 3D referanslardan

OUT = os.path.join(paths.STATE, 'marka')
STIL = ('Premium 3D animated feature film still (Pixar / Illumination quality), soft cinematic lighting, rich realistic textures, '
        'shallow depth of field. Absolutely no text, letters, labels, logos or brand names anywhere.')


def _img(prompt, refs, oran, boyut, path):
    parts = [{'text': prompt}]
    for c in refs:
        parts.append({'text': f'Reference image of {KARAKTER_TARIF[c]} — keep exact outfit, colors, proportions and face:'})
        with open(os.path.join(REF_DIR, f'{c}.jpg'), 'rb') as f:
            parts.append({'inline_data': {'mime_type': 'image/jpeg', 'data': base64.b64encode(f.read()).decode()}})
    body = {'contents': [{'role': 'user', 'parts': parts}],
            'generationConfig': {'responseModalities': ['IMAGE'], 'imageConfig': {'aspectRatio': oran, 'imageSize': boyut}}}
    for model in ('gemini-nano-banana-2.1', 'gemini-3-pro-image', 'gemini-3.1-flash-image'):
        try:
            d = _req(f'{BASE}/models/{model}:generateContent', body, timeout=240)
            for p in d['candidates'][0]['content']['parts']:
                data = (p.get('inlineData') or p.get('inline_data') or {}).get('data')
                if data:
                    with open(path, 'wb') as f:
                        f.write(base64.b64decode(data))
                    print('OK', path, model, flush=True)
                    return path
        except Exception as e:
            print('  hata', model, str(e)[:150], flush=True)
    print('BAŞARISIZ', path, flush=True)


def main():
    os.makedirs(OUT, exist_ok=True)
    poz = {'tuna': 'confident, one hand on hip, other hand holding a rolled paper map, adventurous grin',
           'nil': 'thoughtful smile, pushing up her glasses, holding a tiny notebook',
           'bulut': 'cheerful, holding a small homemade gadget made of a bottle cap and paper clips',
           'pire': 'energetic, jumping pose with a big excited smile',
           'benek': 'friendly ladybug standing, wings closed, curious big eyes'}
    for c in ('tuna', 'nil', 'bulut', 'pire', 'benek'):
        _img(f"""{STIL} Official character reference portrait for the series "Mini Dünya": full body, front three-quarter view,
{poz[c]}, standing on a plain warm light-grey studio background, centered, whole body visible with margin, even soft studio lighting.
The character is a toy-like vinyl figure exactly as in the reference image, upgraded to feature-film quality materials.""",
             [c], '3:4', '1K', os.path.join(OUT, f'ref_{c}.jpg'))
    _img(f"""{STIL} Key art for a family animated series about four finger-sized explorer kids and their pet ladybug in a giant house.
Epic wide shot on a giant kitchen counter at golden hour: the four kids stand together heroically on a giant wooden cutting board,
the ladybug beside them; behind them a giant tea glass, a steaming teapot, a simit and spice jars tower like mountains; a paper map
flutters. Keep the CENTER horizontal band of the image visually calm (characters centered), wide cinematic 16:9 composition.""",
         ['tuna', 'nil', 'bulut', 'pire'], '16:9', '2K', os.path.join(OUT, 'kapak_sanat.jpg'))
    _img(f"""{STIL} Channel profile picture: close-up of the boy explorer (first reference) grinning at the camera with brass goggles
on his forehead, the ladybug peeking over his shoulder, warm golden background with giant blurred kitchen objects, centered, works as
a small circle avatar.""",
         ['tuna', 'benek'], '1:1', '1K', os.path.join(OUT, 'profil_sanat.jpg'))


if __name__ == '__main__':
    main()
