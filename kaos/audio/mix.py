"""Ses efektleri, müzik ve son miks (tamamı kodla üretilir, telifsiz)."""
import subprocess
import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt, resample_poly

SR = 44100


def _f(kind, x, a, b=None, order=2):
    if kind == 'band':
        return sosfilt(butter(order, [a / (SR / 2), b / (SR / 2)], 'band', output='sos'), x)
    return sosfilt(butter(order, a / (SR / 2), kind, output='sos'), x)


def T(d):
    return np.arange(int(d * SR)) / SR


class Mixer:
    def __init__(self, total, seed=1):
        self.N = int((total + 0.5) * SR)
        self.voice = np.zeros(self.N, np.float32)
        self.sfx = np.zeros(self.N, np.float32)
        self.mus = np.zeros(self.N, np.float32)
        self.rng = np.random.default_rng(seed)

    def add(self, buf, x, t, g=1.0):
        i = int(t * SR)
        if i >= self.N or i < 0:
            return
        x = np.asarray(x, np.float32)[:self.N - i]
        buf[i:i + len(x)] += x * g

    # ------------------------------------------------ efektler
    def noise(self, d):
        return self.rng.standard_normal(int(d * SR)).astype(np.float32)

    def whoosh(self, t, g=0.22):
        d = 0.45; tt = T(d)
        self.add(self.sfx, _f('band', self.noise(d), 400, 3000) * np.sin(np.pi * tt / d) ** 2, t - 0.25, g)

    def horn(self, t, g=0.16):
        tt = T(0.6)
        h = (np.sign(np.sin(2 * np.pi * 330 * tt)) + np.sign(np.sin(2 * np.pi * 415 * tt))) * np.minimum(1, tt * 30) * np.minimum(1, (0.6 - tt) * 20)
        self.add(self.sfx, _f('low', h, 2500), t, g)

    def engine(self, t, d=1.6, g=0.3):
        tt = T(d)
        e = (np.sign(np.sin(2 * np.pi * (36 + 10 * tt / d) * tt)) * 0.5 + _f('low', self.noise(d), 300)) * np.linspace(0.2, 1, len(tt)) * np.minimum(1, (d - tt) * 3)
        self.add(self.sfx, _f('low', e, 420), t, g)

    def air_brake(self, t, g=0.4):
        tt = T(0.8)
        self.add(self.sfx, _f('band', self.noise(0.8), 2000, 8000) * np.exp(-tt * 3) * np.minimum(1, tt * 50), t, g)

    def beep(self, t, g=0.12, n=3):
        for k in range(n):
            tt = T(0.18)
            self.add(self.sfx, np.sign(np.sin(2 * np.pi * 1000 * tt)) * np.minimum(1, (0.18 - tt) * 40), t + k * 0.36, g)

    def steps(self, t, d=0.9, g=0.3):
        for k, tt0 in enumerate(np.arange(0, d, 0.14)):
            tt = T(0.08)
            self.add(self.sfx, _f('band', self.noise(0.08), 600 + (k % 2) * 300, 3000) * np.exp(-tt * 60), t + tt0, g)

    def ship_horn(self, t, g=0.3):
        d = 1.6; tt = T(d)
        h = sum(np.sin(2 * np.pi * 70 * k * tt) / k for k in range(1, 6)) * np.minimum(1, tt * 4) * np.minimum(1, (d - tt) * 3)
        self.add(self.sfx, _f('low', h, 900), t, g)

    def ring(self, t, d=1.2, g=0.18):
        tt = T(d)
        r = np.sin(2 * np.pi * 1400 * tt) * (np.sin(2 * np.pi * 22 * tt) > 0) * (np.sin(2 * np.pi * 1.2 * tt) > -0.3)
        self.add(self.sfx, r, t, g)

    def boing(self, t, g=0.25):
        tt = T(0.5)
        self.add(self.sfx, np.sin(2 * np.pi * np.cumsum(180 + 260 * np.sin(np.pi * tt / 0.5) * np.exp(-tt * 3)) / SR) * np.exp(-tt * 5), t, g)

    def boom(self, t, g=0.5):
        tt = T(1.1)
        self.add(self.sfx, np.sin(2 * np.pi * np.cumsum(40 + 60 * np.exp(-tt * 8)) / SR) * np.exp(-tt * 3), t, g)

    def rumble(self, t, d, g=0.12):
        x = _f('low', np.cumsum(self.noise(d)), 160)
        x = _f('high', x, 25)
        self.add(self.sfx, x / (np.abs(x).max() + 1e-9) * np.minimum(1, T(d) * 5), t, g)

    def sting(self, t, g=0.22):
        for i, (f0, dt, d) in enumerate([(392, 0, 0.26), (370, 0.32, 0.26), (311, 0.64, 1.2)]):
            tt = T(d)
            tone = sum(np.sin(2 * np.pi * f0 * h * tt) / h for h in range(1, 7)) * np.minimum(1, tt * 40) * np.exp(-tt * (1.4 if i == 2 else 4))
            if i == 2:
                tone *= 1 + 0.15 * np.sin(2 * np.pi * 5.5 * tt)
            self.add(self.sfx, _f('low', tone, 3000), t + dt, g)

    def ambience(self, loc, total):
        n = self.N
        if loc in ('rihtim', 'gece', 'saha', 'gumruk', 'kantar'):
            w = _f('low', np.cumsum(self.rng.standard_normal(n)), 380)
            w = _f('high', w, 30)
            self.sfx += (w / (np.abs(w).max() + 1e-9) * 0.05).astype(np.float32)
        if loc == 'rihtim':
            for tt in np.arange(1.0, total, 6.5):
                d = 0.35; t_ = T(d)
                g = np.sin(2 * np.pi * np.cumsum(1400 + 600 * np.sin(np.pi * t_ / d)) / SR) * np.sin(np.pi * t_ / d) ** 2
                self.add(self.sfx, g, tt + self.rng.uniform(0, 2), 0.035)
        if loc in ('depo', 'ofis'):
            tt = np.arange(n) / SR
            self.sfx += (np.sin(2 * np.pi * 100 * tt) * 0.01 + _f('band', self.rng.standard_normal(n), 200, 900) * 0.01).astype(np.float32)
        if loc == 'gece':
            for tt in np.arange(0.5, total, 0.9):
                t_ = T(0.12)
                self.add(self.sfx, np.sin(2 * np.pi * 4200 * t_) * (np.sin(2 * np.pi * 40 * t_) > 0) * np.exp(-t_ * 10), tt, 0.02)

    # ------------------------------------------------ müzik
    def music(self, t0, t1, mood='komik', bpm=112, g=0.5):
        beat = 60 / bpm
        prog = {'komik': [43, 43, 50, 43, 46, 46, 41, 45], 'gergin': [40, 40, 41, 40, 43, 41, 40, 39],
                'sakin': [48, 52, 55, 52, 50, 53, 57, 53]}[mood]
        for i, b in enumerate(np.arange(t0, t1, beat / 2)):
            if i % 2 == 0:
                nn = prog[(i // 2) % len(prog)]
                f0 = 440 * 2 ** ((nn - 69) / 12)
                tt = T(0.22)
                self.add(self.mus, (np.sin(2 * np.pi * f0 * tt) + 0.4 * np.sin(4 * np.pi * f0 * tt)) * np.exp(-tt * 14), b, g)
                if mood != 'gergin' and (i // 2) % 4 == 2:
                    tt = T(0.3)
                    f1 = f0 * 4
                    self.add(self.mus, np.sin(2 * np.pi * f1 * tt) * np.exp(-tt * 9) * 0.25, b, g)
            tt = T(0.05)
            self.add(self.mus, _f('high', self.noise(0.05), 6000) * np.exp(-tt * 80), b, (0.12 if i % 2 else 0.06) * g / 0.5)

    def finish(self, voice_wavs, out_wav, lufs=-14):
        env = np.convolve(np.abs(self.voice), np.ones(2205) / 2205, 'same')
        act = np.convolve(np.clip(env * 30, 0, 1), np.ones(13230) / 13230, 'same')
        mix = self.voice * 1.0 + self.sfx * 0.9 + self.mus * 0.35 * (1 - 0.55 * np.clip(act * 1.5, 0, 1))
        mix = np.stack([mix, mix], 1)
        mix /= (np.abs(mix).max() + 1e-9) / 0.95
        raw = out_wav[:-4] + '_raw.wav'
        sf.write(raw, mix.astype(np.float32), SR)
        subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', raw, '-af', f'loudnorm=I={lufs}:TP=-1.5',
                        '-ar', '48000', out_wav], check=True)
        return out_wav


ENTER_SFX = {'tuna': 'steps', 'nil': 'steps', 'bulut': 'steps', 'pire': 'steps', 'benek': 'whoosh'}


def build_mix(ep, tl, out_wav):
    m = Mixer(tl['total'])
    segs = tl['segments']
    fx = ep.get('acilis_efekti')
    if not tl['long'] and fx:
        m.whoosh(0.0, 0.35)
        if fx in ('dusen_nesne', 'dev_damla'):
            m.boom(0.55, 0.75)
        else:
            m.rumble(0.0, 1.2, 0.18)
    for s in segs:
        x, sr = sf.read(s['wav'], dtype='float32', always_2d=True)
        x = x.mean(1)
        if sr != SR:
            x = resample_poly(x, SR, sr).astype(np.float32)
        m.add(m.voice, x, s['start'], 1.15 if s['emotion'] == 'sinirli' else 1.0)
        a = s['action']
        if a in ('kos_sag', 'kos_sol', 'kac'):
            m.whoosh(s['start'] - 0.25)
        if a == 'carp':
            m.boom(s['start'], 0.9)
        if a in ('gir_sag', 'gir_sol'):
            kind = ENTER_SFX.get(s['who'])
            if kind == 'truck':
                m.engine(s['start'] - 0.8); m.horn(s['start'] - 0.4); m.air_brake(s['start'] + 0.3)
            elif kind == 'forklift':
                m.beep(s['start'] - 0.6)
            elif kind == 'steps':
                m.steps(s['start'] - 0.2)
            elif kind == 'ship':
                m.ship_horn(s['start'] - 1.0)
            else:
                m.whoosh(s['start'])
        if a in ('yuru_sag', 'yuru_sol'):
            m.steps(s['start'])
        if a == 'zipla':
            m.boing(s['start'])
        if a == 'titre':
            m.rumble(s['start'], min(0.8, s['dur']))
        if a == 'cal':
            m.ring(s['start'] - 1.3)
        if s['emotion'] == 'sinirli':
            m.boom(s['start'] - 0.05, 0.35)
    # kamera kesmelerinde hafif whoosh
    prev = None
    for s in segs:
        k = s.get('shot', (0, 0, 0, None))[3]
        if prev is not None and k != prev:
            m.whoosh(s['start'], 0.12)
        prev = k
    locs = [sc.get('location', 'rihtim') for sc in ep['scenes']]
    m.ambience(locs[0], tl['total'])
    mood = ep.get('music', 'komik')
    end = tl['end_start']
    m.music(0.0, max(0.5, end - 0.9), mood, 112 if mood == 'komik' else 96)
    m.sting(end - 0.85)
    m.music(end + 0.9, tl['total'] - 0.3, 'komik', 112, 0.45)
    return m.finish(None, out_wav)
