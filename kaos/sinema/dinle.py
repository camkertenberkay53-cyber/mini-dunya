"""Ücretsiz yerel konuşma tanıma (Whisper base, sherpa-onnx, CPU): seslendirmenin gerçekten anlaşılır olduğunu ölçer.
Kalite kontrolde her repliğin sesi yazıya çevrilir ve senaryodaki metinle karşılaştırılır."""
import difflib
import glob
import os
import re

import numpy as np

from .. import paths

_TANI = {}


def _tanici():
    if 'r' in _TANI:
        return _TANI['r']
    import sherpa_onnx
    d = os.path.join(os.environ.get('PIPER_MODELS', os.path.join(paths.ROOT, 'models')), 'sherpa-onnx-whisper-base')
    enc = (glob.glob(d + '/*encoder.int8.onnx') or glob.glob(d + '/*encoder.onnx'))[0]
    dec = (glob.glob(d + '/*decoder.int8.onnx') or glob.glob(d + '/*decoder.onnx'))[0]
    tok = glob.glob(d + '/*tokens.txt')[0]
    _TANI['r'] = sherpa_onnx.OfflineRecognizer.from_whisper(encoder=enc, decoder=dec, tokens=tok, language='tr',
                                                            task='transcribe', num_threads=2)
    return _TANI['r']


def yaziya_cevir(x, sr):
    r = _tanici()
    s = r.create_stream()
    s.accept_waveform(sr, np.asarray(x, np.float32))
    r.decode_stream(s)
    return s.result.text.strip()


def _norm(t):
    t = t.lower().replace('i̇', 'i')
    t = re.sub(r'\d+', lambda m: m.group(0), t)
    return re.sub(r"[^\wçğıöşü ]", ' ', t).split()


def benzerlik(beklenen, duyulan):
    """Kelime ve harf düzeyinde benzerliğin büyüğü (rakam/yazı farkı ve 'Otlukbeli'/'Otluk beli' bölünmesi cezalandırılmaz)."""
    from .motor import okunus
    a, b = _norm(okunus(beklenen)), _norm(okunus(duyulan))
    if not a:
        return 1.0
    kelime = difflib.SequenceMatcher(None, a, b).ratio()
    harf = difflib.SequenceMatcher(None, ''.join(a), ''.join(b)).ratio()
    return max(kelime, harf)
