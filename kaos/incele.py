"""Bitmiş videoyu sesiyle birlikte baştan sona inceler (Gemini video+ses, kuruşluk).
Çıktı: state/inceleme/<ad>.json (zamanlı döküm, yarıda kesilen kelimeler, altyazı-ses uyumu, kurgu hataları)
ve state/inceleme/<ad>_540.mp4 (küçük kopya: Claude kareleri kendisi kontrol edebilsin)."""
import base64
import glob
import json
import os
import subprocess
import sys

from . import paths
from .veo import _req, BASE, _sure

KONTROL = """You are a strict professional film editor reviewing a finished Turkish YouTube Short (vertical animated video with burned-in
subtitles). Watch AND listen to the whole video carefully, second by second. Return JSON:
{"dokum": [{"start": 0.0, "end": 2.1, "konusma": "exact Turkish words heard", "altyazi": "subtitle text shown on screen at that time"}],
 "kesik_kelimeler": [{"zaman": 12.3, "aciklama": "word/sentence cut off mid-way by a cut or by the video end"}],
 "altyazi_uyumsuz": [{"zaman": 5.0, "aciklama": "subtitle text/timing does not match the speech"}],
 "kurgu_hatalari": [{"zaman": 25.0, "aciklama": "jump, frozen frame, sudden costume/character change, audio jump, bad transition"}],
 "son": "does the last sentence finish completely before the video ends? describe",
 "puan": 0-100, "ozet": "short Turkish summary of the biggest problems"}
Write all descriptions in Turkish. Be specific with times."""


def incele(video, ad, log=print):
    od = os.path.join(paths.STATE, 'inceleme')
    os.makedirs(od, exist_ok=True)
    kucuk = os.path.join(od, f'{ad}_540.mp4')
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', video, '-vf', 'scale=540:-2', '-c:v', 'libx264', '-crf', '30',
                    '-preset', 'veryfast', '-c:a', 'aac', '-b:a', '96k', kucuk], check=True)
    with open(kucuk, 'rb') as f:
        data = base64.b64encode(f.read()).decode()
    rapor = None
    for model in ('gemini-3.8-flash', 'gemini-flash-latest'):
        try:
            d = _req(f'{BASE}/models/{model}:generateContent',
                     {'contents': [{'role': 'user', 'parts': [{'inline_data': {'mime_type': 'video/mp4', 'data': data}}, {'text': KONTROL}]}],
                      'generationConfig': {'temperature': 0.1, 'responseMimeType': 'application/json'}}, timeout=300)
            rapor = json.loads(''.join(p.get('text', '') for p in d['candidates'][0]['content']['parts']))
            rapor['_model'] = model
            break
        except Exception as e:
            log(f'  İnceleme ({model}) hata: {str(e)[:150]}')
    rapor = rapor or {'hata': 'inceleme yapılamadı'}
    rapor['_sure'] = _sure(video)
    with open(os.path.join(od, f'{ad}.json'), 'w', encoding='utf-8') as f:
        json.dump(rapor, f, ensure_ascii=False, indent=1)
    log(json.dumps(rapor, ensure_ascii=False, indent=1)[:4000])
    return rapor


if __name__ == '__main__':
    kok = sys.argv[1]
    for v in sorted(glob.glob(os.path.join(kok, '**', 'video.mp4'), recursive=True)):
        incele(v, os.path.basename(os.path.dirname(v))[:60])
