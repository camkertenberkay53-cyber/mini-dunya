"""Ücretsiz yapay zekâ büyütme (Real-ESRGAN animevideov3, BSD-3, CPU).
Omni'yi ucuz 360p'de çektirip burada 4x büyütürüz: ek ücret yok, GitHub runner'da 45 sn ~15-20 dk.
Hata olursa çağıran taraf ham klibi kullanır (birleştirme zaten 1080x1920'ye ölçekler)."""
import os
import subprocess
import time

import numpy as np

from . import paths

AGIRLIK = os.path.join(paths.ROOT, 'assets', 'models', 'realesr-animevideov3.pth')
_MODEL = {}


def _model():
    if 'm' in _MODEL:
        return _MODEL['m']
    import torch
    import torch.nn as nn

    class SRVGG(nn.Module):
        def __init__(s, nf=64, nc=16, up=4):
            super().__init__()
            s.up = up
            L = [nn.Conv2d(3, nf, 3, 1, 1), nn.PReLU(nf)]
            for _ in range(nc):
                L += [nn.Conv2d(nf, nf, 3, 1, 1), nn.PReLU(nf)]
            L += [nn.Conv2d(nf, 3 * up * up, 3, 1, 1)]
            s.body = nn.ModuleList(L)
            s.ps = nn.PixelShuffle(up)

        def forward(s, x):
            o = x
            for m in s.body:
                o = m(o)
            return s.ps(o) + nn.functional.interpolate(x, scale_factor=s.up, mode='nearest')

    m = SRVGG()
    sd = torch.load(AGIRLIK, map_location='cpu')
    m.load_state_dict(sd.get('params', sd))
    m.eval()
    torch.set_num_threads(max(1, os.cpu_count() or 2))
    _MODEL['m'] = (torch, m)
    return _MODEL['m']


def _bilgi(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height,r_frame_rate',
                          '-of', 'csv=p=0', path], capture_output=True, text=True).stdout.strip().split(',')
    w, h = int(out[0]), int(out[1])
    a, b = (out[2].split('/') + ['1'])[:2]
    return w, h, float(a) / float(b or 1)


def buyut(src, dst, log=print, hedef_kisa=1080):
    """src klibini 4x büyütür, kısa kenarı hedef_kisa olacak şekilde dst'ye yazar (ses korunur)."""
    torch, m = _model()
    w, h, fps = _bilgi(src)
    W, H = w * 4, h * 4
    k = hedef_kisa / min(W, H)
    ow, oh = int(round(W * k / 2) * 2), int(round(H * k / 2) * 2)
    t0 = time.time()
    tmp = dst + '.tmp.mp4'
    dec = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-i', src, '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE)
    enc = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', f'{fps}',
                            '-i', '-', '-i', src, '-map', '0:v', '-map', '1:a?', '-vf', f'scale={ow}:{oh}:flags=lanczos',
                            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '17', '-pix_fmt', 'yuv420p', '-c:a', 'copy', tmp],
                           stdin=subprocess.PIPE)
    n = 0
    with torch.inference_mode():
        while True:
            buf = dec.stdout.read(w * h * 3)
            if len(buf) < w * h * 3:
                break
            x = torch.from_numpy(np.frombuffer(buf, np.uint8).reshape(h, w, 3).copy()).permute(2, 0, 1)[None].float() / 255.0
            y = m(x).clamp_(0, 1)[0].permute(1, 2, 0).mul_(255).round_().byte().numpy()
            enc.stdin.write(y.tobytes())
            n += 1
    enc.stdin.close()
    dec.wait()
    if enc.wait() != 0 or n == 0:
        raise RuntimeError('büyütme kodlaması başarısız')
    os.replace(tmp, dst)
    log(f'  Büyütüldü: {w}x{h} -> {ow}x{oh}, {n} kare, {time.time() - t0:.0f} sn')
    return dst
