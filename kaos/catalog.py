"""Ses kataloğu: her karakter için aday sesleri aynı repliklerle seslendirip tek bir dikey video yapar.
python -m kaos.catalog   → output/ses_katalogu/video.mp4"""
import os
import subprocess
import time
import traceback

import numpy as np
import soundfile as sf

from . import paths
from .audio import tts, mix
from .engine import render
from .main import load_cfg, log

SAMPLE = {
    'tayfun': 'Benim bekleme param kim ödeyecek? Üç saattir kapıdayım!',
    'kemal': 'Kırk beş gündür buradayım! Artık beni biri gönderecek mi?',
    'erdal': 'Kaşe var, imza var... ama aslı gibidir yok. Eksik var.',
    'necati': 'Ben gelince başlar bu iş. Bekleyin bakalım.',
    'fikri': 'Of... Bu yükü de kaldırırsam mesaiye girer mi?',
    'vedat': 'Ben bir şey görmedim... ama anlatayım.',
    'telefon': 'Alo? Yüküm nerede? Dün gelecekti!',
}
GEMINI_ALT = {'tayfun': ['Fenrir'], 'kemal': ['Leda'], 'erdal': ['Iapetus'], 'necati': ['Alnilam'],
              'fikri': ['Umbriel'], 'vedat': ['Achird'], 'telefon': ['Aoede']}
EDGE_ALT = {'tayfun': [('tr-TR-AhmetNeural', '+18%', '-20Hz')], 'kemal': [('en-US-AndrewMultilingualNeural', '+5%', '+10Hz')],
            'erdal': [('tr-TR-AhmetNeural', '-6%', '+6Hz')], 'necati': [('en-US-BrianMultilingualNeural', '-15%', '-15Hz')],
            'fikri': [('tr-TR-AhmetNeural', '-10%', '-6Hz')], 'vedat': [('it-IT-GiuseppeMultilingualNeural', '+0%', '+0Hz')],
            'telefon': [('en-US-AvaMultilingualNeural', '+10%', '+0Hz')]}


def main():
    cfg = load_cfg()
    out = os.path.join(paths.OUTPUT, 'ses_katalogu')
    sdir = os.path.join(out, 'ses')
    os.makedirs(sdir, exist_ok=True)
    key = os.environ.get('GEMINI_API_KEY', '')
    gem_extra = os.environ.get('KATALOG_GEMINI_ALT', '0') == '1'
    scenes, wavs = [], {}
    for si, (who, text) in enumerate(SAMPLE.items()):
        v = cfg['voices'][who]
        options = []
        gvoices = [v['gemini']] + (GEMINI_ALT[who] if gem_extra else [])
        for gv in gvoices:
            options.append(('gemini', gv, None))
        options.append(('edge', v['edge']['voice'], (v['edge'].get('rate', '+0%'), v['edge'].get('pitch', '+0Hz'))))
        for ev in EDGE_ALT[who]:
            options.append(('edge', ev[0], (ev[1], ev[2])))
        lines = []
        for oi, (eng, name, extra) in enumerate(options):
            path = os.path.join(sdir, f'{who}_{oi}.wav')
            label = f"{chr(65 + oi)}) {'Gemini' if eng == 'gemini' else 'Edge'} · {name.replace('Neural', '')}"
            if extra:
                label += f' ({extra[0]}, {extra[1]})'
            try:
                if eng == 'gemini':
                    if not key:
                        raise RuntimeError('anahtar yok')
                    prompt = f"{v.get('style', '')}\nŞu repliği Türkçe, doğal ve oyunculu şekilde seslendir:\n\n{text}"
                    x = None
                    for model in cfg['tts']['gemini_models']:
                        try:
                            x = tts._gemini_request(key, model, prompt, name)
                            break
                        except Exception as e:
                            log(f'  {model}: {e}')
                    if x is None:
                        raise RuntimeError('Gemini kotası/erişimi yok')
                    tts._save(path, x)
                    time.sleep(21)
                else:
                    import asyncio
                    import edge_tts
                    mp3 = path[:-4] + '.mp3'
                    asyncio.run(edge_tts.Communicate(text, name, rate=extra[0], pitch=extra[1]).save(mp3))
                    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', mp3, '-ar', '44100', '-ac', '1', path], check=True)
                    xx, _ = sf.read(path, dtype='float32')
                    tts._save(path, xx)
            except Exception as e:
                log(f'{who} {label}: atlandı ({e})')
                continue
            wavs[(len(scenes), len(lines))] = path
            lines.append({'who': who, 'text': label, 'emotion': 'normal', 'action': 'yok'})
            log(f'{who} {label}: tamam')
        if lines:
            scenes.append({'location': 'saha', 'characters': [who], 'lines': lines})
    ep = {'scenes': scenes, 'end_card': 'Her karakter için beğendiğin harfi yaz!'}
    tl = render.build_timeline(ep, wavs, long_form=False)
    for s in tl['segments']:
        s['action'] = 'yok'
    meta = {'subtitle': 'Ses Kataloğu'}
    vid = os.path.join(out, 'goruntu.mp4')
    render.render_video(ep, tl, vid, 1080, 1920, meta)
    wav = os.path.join(out, 'miks.wav')
    m = mix.Mixer(tl['total'])
    for s in tl['segments']:
        x, sr = sf.read(s['wav'], dtype='float32')
        m.add(m.voice, x, s['start'])
    m.finish(None, wav)
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', vid, '-i', wav, '-map', '0:v', '-map', '1:a', '-c:v', 'copy',
                    '-c:a', 'aac', '-b:a', '192k', '-shortest', os.path.join(out, 'video.mp4')], check=True)
    os.remove(vid)
    log('Ses kataloğu hazır: output/ses_katalogu/video.mp4')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
