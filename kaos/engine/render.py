"""Senaryo + ses zamanlamasından videoyu çizer."""
import math
import os
import subprocess
from functools import lru_cache

import numpy as np
import cv2
import soundfile as sf
from PIL import Image, ImageDraw, ImageFont

from .. import paths
from . import backgrounds
from .characters import CHARS, St
from .draw import Cam, ease, seg, lerp, line, circle, fill

FPS = 30
GROUND_Y = 1250
DEFAULT_EMO = {'tuna': 'neseli', 'nil': 'normal', 'bulut': 'normal', 'pire': 'saskin', 'benek': 'normal'}
LINE_GAP = 0.28
TOPS = {c: v['h'] for c, v in CHARS.items()}


# ---------------------------------------------------------------- ses analizi
def analyze(path):
    x, sr = sf.read(path, dtype='float32', always_2d=True)
    x = x.mean(1)
    n = int(len(x) / sr * FPS) + 1
    env, zcr = np.zeros(n), np.zeros(n)
    for i in range(n):
        s = x[int(i * sr / FPS):int((i + 1) * sr / FPS)]
        if len(s) == 0:
            continue
        env[i] = np.sqrt(np.mean(s ** 2))
        zcr[i] = np.mean(np.abs(np.diff(np.sign(s)))) / 2 if len(s) > 1 else 0
    env = np.clip(env / (np.percentile(env, 95) + 1e-9) * 1.1, 0, 1)
    env = np.convolve(env, [0.25, 0.5, 0.25], 'same')
    z = np.clip((zcr - 0.03) / 0.15, 0, 1)
    return env, z, len(x) / sr


# ---------------------------------------------------------------- zaman çizelgesi
def build_timeline(ep, line_wavs, long_form=False):
    segs, scenes = [], []
    t = 3.6 if long_form else 0.35
    for si, sc in enumerate(ep['scenes']):
        if long_form and si > 0:
            t += 1.4  # sahne geçişi
        s0 = t
        for li, ln in enumerate(sc['lines']):
            env, zcr, dur = analyze(line_wavs[(si, li)])
            segs.append(dict(scene=si, line=li, who=ln['who'], text=ln['text'], emotion=ln.get('emotion', 'normal'),
                             action=ln.get('action', 'yok'), start=t, dur=dur, env=env, zcr=zcr, wav=line_wavs[(si, li)]))
            gap = LINE_GAP + (0.35 if ln['text'].rstrip().endswith(('?', '!', '...')) else 0.0)
            t += dur + gap
        scenes.append((s0, t))
    end_start = t + 0.6
    total = end_start + (5.0 if long_form else 3.2)
    return dict(segments=segs, scenes=scenes, end_start=end_start, total=total, long=long_form)


# ---------------------------------------------------------------- sahne düzeni
def layout(scene, order=None):
    chars = [c for c in (order or scene['characters']) if c in CHARS]
    ground = [c for c in chars if CHARS[c]['ground']]
    pos = {}
    widths = [CHARS[c]['w'] for c in ground]
    total = sum(widths) + 50 * max(0, len(ground) - 1)
    cx = 550
    x = cx - total / 2
    for c, w in zip(ground, widths):
        pos[c] = (x + w / 2, GROUND_Y)
        x += w + 50
    return pos


def face_pt(c, pos):
    x, y = pos[c]
    dx, dy = CHARS[c]['face']
    return x + dx, y + dy


# ---------------------------------------------------------------- kamera
def bbox(chars, pos):
    xs, ys = [], []
    for c in chars:
        x, y = pos[c]
        w = CHARS[c]['w']
        if True:
            xs += [x - w / 2, x + w / 2]; ys += [y - TOPS.get(c, 320), y + 30]
    return min(xs), max(xs), min(ys), max(ys)


def frame_box(box, W, H, fill_w, fill_h, zmax, screen_y):
    bx0, bx1, by0, by1 = box
    z = min(W * fill_w / (bx1 - bx0 + 80), H * fill_h / (by1 - by0 + 80), zmax)
    cx = (bx0 + bx1) / 2
    cy = (by0 + by1) / 2 + (H / 2 - H * screen_y) / z
    return cx, cy, z


def shot_for(seg_, idx, n, prev_who, W, H, pos):
    who = seg_['who']
    em, act = seg_['emotion'], seg_['action']
    vertical = H > W
    sy = 0.46 if vertical else 0.47
    if who not in pos or act in ('gir_sag', 'gir_sol', 'cik', 'kos_sag', 'kos_sol', 'kac', 'yuru_sag', 'yuru_sol'):
        kind = 'wide'
    elif act == 'kameraya_bak' or idx == n - 1:
        kind = 'xclose'
    elif idx == 0 or em in ('sinirli', 'saskin', 'panik'):
        kind = 'close'
    elif prev_who and prev_who != who and prev_who in pos and idx % 3 != 2:
        kind = 'two'
    else:
        kind = 'wide'
    if kind == 'wide' or len(pos) == 1 and kind == 'two':
        box = bbox(list(pos.keys()), pos)
        cx, cy, z = frame_box(box, W, H, 0.9, 0.56 if vertical else 0.8, 1.75, sy)
    elif kind == 'two':
        box = bbox([who, prev_who], pos)
        cx, cy, z = frame_box(box, W, H, 0.92, 0.48 if vertical else 0.8, 1.9, sy)
    else:
        box = bbox([who], pos)
        fw = 0.7 if kind == 'close' else 0.84
        fh = (0.34 if kind == 'close' else 0.4) if vertical else (0.6 if kind == 'close' else 0.7)
        cx, cy, z = frame_box(box, W, H, fw, fh, 2.6, sy)
        if kind == 'xclose':  # yüze biraz daha yakın
            fx, fy = face_pt(who, pos)
            cy = lerp(cy, fy + (H / 2 - H * sy) / z, 0.4)
    return cx, cy, z, kind


# ---------------------------------------------------------------- metin
@lru_cache(16)
def font(size):
    f = ImageFont.truetype(paths.FONT, size)
    try:
        f.set_variation_by_axes([800])
    except Exception:
        pass
    return f


def wrap(text, size, maxw):
    f = font(size)
    words, lines, cur = text.split(), [], ''
    for w in words:
        cand = (cur + ' ' + w).strip()
        if f.getlength(cand) <= maxw or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return '\n'.join(lines)


def draw_texts(frame, items):
    im = Image.fromarray((np.clip(frame, 0, 1) * 255).astype(np.uint8))
    d = ImageDraw.Draw(im)
    for it in items:
        kind = it[0]
        if kind == 'text':
            _, txt, x, y, size, col, anchor = it
            d.multiline_text((x, y), txt, font=font(size), fill=col, anchor=anchor, align='center',
                             stroke_width=max(4, size // 9), stroke_fill=(15, 15, 20), spacing=6)
        elif kind == 'button':
            _, txt, x, y, size = it
            tw = font(size).getlength(txt)
            d.rounded_rectangle([x - tw / 2 - 30, y - size * 0.75, x + tw / 2 + 30, y + size * 0.75], radius=int(size * 0.5), fill=(230, 30, 40))
            d.text((x, y), txt, font=font(size), fill=(255, 255, 255), anchor='mm')
    return np.asarray(im).astype(np.float32) / 255.0



def speed_lines(f, cam, x, y, side, t, w):
    """Koşu: karakterin arkasında hız çizgileri ve toz."""
    for i in range(7):
        yy = y - 80 - i * 70
        ln = 220 + 90 * ((i * 37 + int(t * 30)) % 3)
        x0 = x + side * (w * 0.45 + 30)
        a, b = cam.p(x0, yy), cam.p(x0 + side * ln, yy)
        line(f, a, b, (0.97, 0.95, 0.88), cam.lw(3))
    for j in range(4):
        r = 30 + 14 * j
        cx = x + side * (w * 0.4 + 60 * j)
        circle(f, cam.p(cx, y - 15), r * 0.6 * cam.z, (0.86, 0.78, 0.62), False)


def impact_burst(f, cam, x, y, dt):
    """Çarpma: patlama yıldızı."""
    k = 1 - dt / 0.5
    R, r = (110 + 80 * (1 - k)), 55
    pts = []
    for i in range(20):
        a = i * math.pi / 10 + 0.2
        rr = R if i % 2 == 0 else r
        pts.append((x + math.cos(a) * rr, y + math.sin(a) * rr))
    fill(f, cam.P(pts), (1.0, 0.86, 0.2), True, cam.lw(6))

# ---------------------------------------------------------------- render
class Renderer:
    def __init__(self, ep, tl, W, H, meta):
        self.ep, self.tl, self.W, self.H, self.meta = ep, tl, W, H, meta
        self.vertical = H > W
        self.layouts = [layout(sc) for sc in ep['scenes']]
        self.segs = tl['segments']
        # her sahne için çekimler
        self.shots = []
        for si, sc in enumerate(ep['scenes']):
            ss = [s for s in self.segs if s['scene'] == si]
            prev = None
            for k, s in enumerate(ss):
                s['shot'] = shot_for(s, k, len(ss), prev, W, H, self.layouts[si])
                prev = s['who']
            self.wide = getattr(self, 'wide', {})
            self.wide[si] = shot_for(dict(who=None, emotion='normal', action='gir_sag'), 0, 1, None, W, H, self.layouts[si])
        # karakter giriş/çıkış zamanları
        self.enter, self.exit = {}, {}
        for s in self.segs:
            key = (s['scene'], s['who'])
            a = s['action']
            if a in ('gir_sag', 'gir_sol', 'kos_sag', 'kos_sol') and key not in self.enter:
                fast = a.startswith('kos')
                self.enter[key] = (s['start'] - (0.25 if fast else 0), 1 if a.endswith('sag') else -1, 0.45 if fast else 0.9)
            if a in ('cik', 'kac'):
                self.exit[key] = (s['start'] + s['dur'], 0.45 if a == 'kac' else 0.8)
        self.impacts = [(s['start'], s['scene'], s['who']) for s in self.segs if s['action'] == 'carp']
        # sahne içi yürüyüşler: her biri 0.9 sn'de 170 birim
        self.moves = {}
        for s in self.segs:
            if s['action'] in ('yuru_sag', 'yuru_sol'):
                self.moves.setdefault((s['scene'], s['who']), []).append((s['start'] + 0.1, 170 if s['action'] == 'yuru_sag' else -170))
        for si2, sc2 in enumerate(ep['scenes']):
            cs = [c for c in sc2['characters'] if c in CHARS]
            left = [c for c in cs if self.enter.get((si2, c), (0, 0, 0))[1] == -1]
            right = [c for c in cs if self.enter.get((si2, c), (0, 0, 0))[1] == 1]
            mid = [c for c in cs if c not in left and c not in right and c != 'benek']
            ben = ['benek'] if 'benek' in cs and 'benek' not in left + right else []
            order = left[::-1] + mid + ben + right
            self.layouts[si2] = layout(sc2, order)
            self.wide[si2] = shot_for(dict(who=None, emotion='normal', action='gir_sag'), 0, 1, None, W, H, self.layouts[si2])
        # kamera çekimlerini, o anda sahnede gerçekten olan karakterlerin GÜNCEL konumlarına göre yeniden hesapla
        for si2 in range(len(ep['scenes'])):
            ss = [q for q in self.segs if q['scene'] == si2]
            prev = None
            for k, q in enumerate(ss):
                q['shot'] = shot_for(q, k, len(ss), prev, W, H, self.present(si2, q))
                prev = q['who']
        # dinleyen tepkileri: biri şaşırır ya da panikler ise diğerleri hafifçe sıçrar
        self.reacts = [(s['start'] + 0.15, s['scene'], s['who']) for s in self.segs if s['emotion'] in ('panik', 'saskin') or s['action'] == 'carp']
        rng = np.random.default_rng(7)
        self.blink_off = {c: rng.uniform(0, 4) for c in CHARS}

    def present(self, si, q):
        """Bu replik sırasında sahnede olan karakterler ve replik sonundaki konumları."""
        t_end = q['start'] + q['dur']
        out = {}
        for c, (x, y) in self.layouts[si].items():
            key = (si, c)
            if key in self.enter and self.enter[key][0] > q['start'] + 0.05 and c != q['who']:
                continue
            if key in self.exit and self.exit[key][0] < q['start'] - 0.05:
                continue
            dx = sum(d for tm, d in self.moves.get(key, []) if tm <= t_end)
            out[c] = (x + dx, y)
        return out or dict(self.layouts[si])

    def scene_at(self, t):
        for i, (a, b) in enumerate(self.tl['scenes']):
            if t < b + (1.4 if self.tl['long'] else 0.6):
                return i
        return len(self.tl['scenes']) - 1

    def seg_at(self, t, scene):
        cur = None
        for s in self.segs:
            if s['scene'] != scene:
                continue
            if s['start'] <= t:
                cur = s
        return cur

    def mouth_of(self, who, t, scene):
        for s in self.segs:
            if s['scene'] == scene and s['who'] == who and s['start'] <= t < s['start'] + s['dur']:
                i = min(int((t - s['start']) * FPS), len(s['env']) - 1)
                return float(s['env'][i]), float(s['zcr'][i]), s
        return 0.0, 0.5, None

    def frame(self, t):
        W, H = self.W, self.H
        si = self.scene_at(t)
        sc = self.ep['scenes'][si]
        pos = self.layouts[si]
        cur = self.seg_at(t, si)
        # kamera
        if cur is None:
            first = [s for s in self.segs if s['scene'] == si][0]
            cx, cy, z, kind = first['shot']
            u = 0
        elif t >= self.tl['end_start']:
            cx, cy, z, kind = self.wide[si]
            u = seg(t, self.tl['end_start'], self.tl['total'])
        else:
            cx, cy, z, kind = cur['shot']
            u = seg(t, cur['start'], cur['start'] + cur['dur'] + 0.5)
        z = z * (1 + 0.035 * ease(u))
        if not self.tl['long'] and t < 1.4:
            z *= 1 + 0.45 * (1 - ease(seg(t, 0.0, 1.4)))  # açılış kancası: hızlı geri çekilme
        sh = 0.0
        if cur is not None:
            mo, _, s = self.mouth_of(cur['who'], t, si)
            if cur['emotion'] == 'sinirli' and s is not None:
                sh = 1.5 * mo
            if cur['action'] == 'titre' and s is not None:
                sh = 3.0 * max(0.0, 1 - (t - cur['start']) / 0.8)
        for ti, _, _ in self.impacts:
            if 0 <= t - ti < 0.4:
                sh = max(sh, 16 * (1 - (t - ti) / 0.4))
                z *= 1 + 0.05 * (1 - (t - ti) / 0.4)
        cam = Cam(W, H, cx, cy, z, sh * math.sin(t * 61), sh * math.cos(t * 47))
        loc = sc.get('location', 'tezgah')
        f = backgrounds.draw(loc, cam)
        # karakterler: önce gökyüzü/deniz karakterleri, sonra soldan sağa yer karakterleri
        def depth(c):
            n = sum(1 for tm, _ in self.moves.get((si, c), []) if t > tm)
            return (n % 2, pos[c][0])
        order = sorted(pos.keys(), key=depth)
        speaker = cur['who'] if cur is not None else None
        for c in order:
            x, y = pos[c]
            key = (si, c)
            moving = 0.0
            if key in self.enter:
                te, side, edur = self.enter[key]
                if t < te:
                    continue
                k = ease(seg(t, te, te + edur))
                x = lerp(x + side * 1100, x, k)
                if edur < 0.6 and t < te + edur:
                    moving = side
            if key in self.exit and t > self.exit[key][0]:
                tx, xdur = self.exit[key]
                k = ease(seg(t, tx, tx + xdur))
                x = lerp(x, x + 1200, k)
                if xdur < 0.6 and t < tx + xdur + 0.1:
                    moving = -1
            if moving:
                speed_lines(f, cam, x, y, moving, t, CHARS[c]['w'] if 'w' in CHARS[c] else 300)
            walk_in = 0.0
            for n_mv, (tm, dxm) in enumerate(self.moves.get(key, [])):
                if t > tm:
                    k2 = ease(seg(t, tm, tm + 0.9))
                    x += dxm * k2
                    y += (45 if n_mv % 2 == 0 else -45) * k2
                    if k2 < 1:
                        walk_in = 1.0
            # boşta küçük kıpırdanma (ağırlık aktarma)
            ph0 = self.blink_off[c] * 1.7
            x += 7 * math.sin(t * 0.55 + ph0)
            mo, zc, s = self.mouth_of(c, t, si)
            last = [q for q in self.segs if q['scene'] == si and q['who'] == c and q['start'] <= t]
            emo = last[-1]['emotion'] if last else DEFAULT_EMO.get(c, 'normal')
            if s is None and emo in ('sinirli',) and speaker and speaker != c:
                emo = 'sinirli'
            # bakış
            if speaker and speaker != c and speaker in pos:
                dx = pos[speaker][0] - x
                look = (max(-1, min(1, dx / 300)) * 0.85, 0.05)
            else:
                look = (0.0, 0.05) if (cur and cur['action'] == 'kameraya_bak' and c == speaker) or c == speaker else (0.0, 0.0)
                if c == speaker and cur and cur['action'] != 'kameraya_bak':
                    others = [o for o in pos if o != c]
                    if others:
                        look = (max(-1, min(1, (pos[others[0]][0] - x) / 300)) * 0.7, 0.05)
            ph = (t + self.blink_off[c]) % 3.9
            blink = 1.0 if ph < 0.12 else 0.0
            dy, sq, shake = 0.0, 1.0, 0.0
            if s is not None:
                if s['action'] == 'zipla':
                    u2 = seg(t, s['start'], s['start'] + 0.5)
                    dy = -90 * math.sin(math.pi * u2)
                    sq = 1 + 0.08 * math.sin(math.pi * u2)
                if s['action'] == 'titre':
                    shake = 1.0
                sq *= 1 + 0.03 * mo
            walk = walk_in
            point = crouch = 0.0
            if s is not None and s['action'] == 'isaret':
                point = ease(seg(t, s['start'], s['start'] + 0.35)) * (1 - ease(seg(t, s['start'] + s['dur'] + 0.2, s['start'] + s['dur'] + 0.6)))
            if s is not None and s['action'] == 'egil':
                crouch = ease(seg(t, s['start'], s['start'] + 0.35)) * (1 - ease(seg(t, s['start'] + s['dur'], s['start'] + s['dur'] + 0.4)))
            for tr, rsi, rw in self.reacts:
                if rsi == si and rw != c and 0 <= t - tr < 0.35:
                    dy = min(dy, -26 * math.sin(math.pi * (t - tr) / 0.35))
            if key in self.enter and self.enter[key][0] <= t < self.enter[key][0] + self.enter[key][2]:
                walk = 1.0
            if key in self.exit and t > self.exit[key][0]:
                walk = 1.0
            st = St(t=t, mo=mo, ms=zc, emotion=emo, look=look, blink=blink, dy=dy, sq=sq, shake=shake,
                    talking=s is not None, walk=walk, point=point, crouch=crouch,
                    face_dir=1.0 if look[0] >= 0 else -1.0)
            CHARS[c]['fn'](f, cam, x, y, st)
            for ti, isi, iw in self.impacts:
                if isi == si and iw == c and 0 <= t - ti < 0.5:
                    fy = y + CHARS[c]['face'][1]
                    impact_burst(f, cam, x + CHARS[c]['w'] * 0.42, fy - 200, t - ti)
        f = backgrounds.draw_fg(loc, cam, f)
        f = backgrounds.post(loc, f, cam, t)
        for ti, isi, _ in self.impacts:
            if isi == si and 0 <= t - ti < 0.09:
                f = f * 0.65 + 0.35
        # metinler
        items = self.texts(t, cur, si)
        for ti, isi, iw in self.impacts:
            if isi == si and 0 <= t - ti < 0.6 and iw in pos:
                px, py = cam.p(pos[iw][0] + CHARS[iw]['w'] * 0.42, pos[iw][1] + CHARS[iw]['face'][1] - 200)
                word = ('GÜM!', 'BAM!', 'ÇAT!', 'PAT!')[int(ti * 7) % 4]
                items.append(('text', word, px, py, int(110 + 40 * (1 - (t - ti) / 0.6)), (255, 220, 40), 'mm'))
        # sahne geçişi (uzun)
        if self.tl['long']:
            a, b = self.tl['scenes'][si]
            if si > 0 and t < a:
                k = seg(t, a - 1.4, a)
                f = f * (0.15 + 0.85 * k)
                title = self.ep['scenes'][si].get('title', '')
                if title:
                    items.append(('text', title.upper(), W / 2, H / 2, 70, (255, 210, 60), 'mm'))
        if t < 0.25 and self.tl['long']:
            f = f * (t / 0.25)  # Shorts'ta ilk kare hemen parlak başlar (akışta ilk görünen kare)
        return draw_texts(f, items) if items else f

    @lru_cache(1)
    def vignette(self):
        Y, X = np.mgrid[0:self.H, 0:self.W].astype(np.float32)
        d = np.sqrt(((X - self.W / 2) / (self.W / 2)) ** 2 + ((Y - self.H / 2) / (self.H / 2)) ** 2)
        return np.clip(1.08 - 0.22 * d ** 2, 0.7, 1)[..., None].astype(np.float32)

    def texts(self, t, cur, si):
        W, H = self.W, self.H
        meta = self.meta
        items = []
        end = self.tl['end_start']
        if cur is not None and t < cur['start'] + cur['dur'] + LINE_GAP + 0.35 and t < end:
            name, col = CHARS[cur['who']]['name'], CHARS[cur['who']]['color']
            if meta.get('lang') == 'en':
                name = NAMES_EN.get(cur['who'], name)
            if self.vertical:
                txt = wrap(cur['text'], 66, W - 120)
                items.append(('text', name, W / 2, 1370, 46, col, 'mm'))
                items.append(('text', txt, W / 2, 1415, 66, (255, 255, 255), 'ma'))
            else:
                txt = wrap(cur['text'], 52, W - 300)
                nl = txt.count('\n')
                items.append(('text', name, W / 2, H - 150 - nl * 58, 38, col, 'mm'))
                items.append(('text', txt, W / 2, H - 120 - nl * 58, 52, (255, 255, 255), 'ma'))
        # açılış başlığı
        if not self.tl['long'] and t < 3.2:
            # açılış kancası: bölümün merak cümlesi, ilk karede büyük ve zıplayarak
            hook = str(self.ep.get('kapak_yazisi') or self.ep.get('baslik', '')).upper()
            pop = 1 + 0.35 * (1 - ease(seg(t, 0.0, 0.22)))
            fade = 1 - seg(t, 2.8, 3.2)
            if fade > 0:
                items.append(('text', wrap(hook, int(96 * pop), W - 110), W / 2, 150, int(96 * pop), (255, 214, 50), 'ma'))
            items.append(('text', UI[meta.get('lang', 'tr')]['brand'], W / 2, 92, 38, (255, 255, 255), 'mm'))
        if self.tl['long'] and t < 3.6:
            items.append(('text', UI[meta.get('lang', 'tr')]['brand'], W / 2, H / 2 - 70, 110, (255, 210, 60), 'mm'))
            items.append(('text', meta.get('subtitle', ''), W / 2, H / 2 + 40, 56, (255, 255, 255), 'mm'))
        # kapanış kartı
        if t >= end:
            items.append(('text', UI[meta.get('lang', 'tr')]['brand'], W / 2, H * (0.38 if self.vertical else 0.3), 96, (255, 210, 60), 'mm'))
            items.append(('text', meta.get('subtitle', ''), W / 2, H * (0.38 if self.vertical else 0.3) + 95, 50, (255, 255, 255), 'mm'))
            ec = self.ep.get('end_card', '')
            if ec and t > end + 0.6:
                y0 = H * (0.38 if self.vertical else 0.3) + 170
                items.append(('text', wrap(ec, 60, W - 140), W / 2, y0, 60, (255, 255, 255), 'ma'))
                items.append(('text', UI[meta.get('lang', 'tr')]['comment'], W / 2, y0 + (190 if self.vertical else 150), 44, (255, 210, 60), 'ma'))
            if t > end + 1.2:
                items.append(('button', UI[meta.get('lang', 'tr')]['sub'], W / 2, H * (0.62 if self.vertical else 0.75), 56))
        return items


UI = {
    'tr': {'brand': 'MİNİ DÜNYA', 'comment': 'CEVABINI YORUMLARA YAZ!', 'sub': 'ABONE OL'},
    'en': {'brand': 'MINI WORLD', 'comment': 'TELL US IN THE COMMENTS!', 'sub': 'SUBSCRIBE'},
}
NAMES_EN = {'tuna': 'TUNA', 'nil': 'NIL', 'bulut': 'BULUT', 'pire': 'PIRE', 'benek': 'BENEK'}


def render_video(ep, tl, out_path, W, H, meta):
    r = Renderer(ep, tl, W, H, meta)
    n = int(tl['total'] * FPS)
    tmp = out_path + '.tmp.mp4'
    p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}',
                          '-r', str(FPS), '-i', '-', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
                          '-pix_fmt', 'yuv420p', tmp], stdin=subprocess.PIPE)
    end = tl['end_start']
    for i in range(n):
        t = i / FPS
        f = r.frame(t)
        if t >= end:
            k = ease(seg(t, end, end + 0.6))
            f = f * (1 - 0.55 * k) if k < 1 else f
        if t > tl['total'] - 0.5:
            f = f * max(0.0, (tl['total'] - t) / 0.5)
        p.stdin.write((np.clip(f, 0, 1) * 255).astype(np.uint8).tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError('ffmpeg video yazımı başarısız')
    os.replace(tmp, out_path)
    return out_path


def thumbnail(ep, tl, path, W, H, meta):
    r = Renderer(ep, tl, W, H, meta)
    segs = tl['segments']
    pool = [s for s in segs if s['start'] > 4.0] or segs
    best = max(pool, key=lambda s: (s['emotion'] in ('sinirli', 'saskin', 'panik'), -s['start']))
    t = best['start'] + min(0.6, best['dur'] / 2)
    r.texts = lambda *a, **k: []
    f = r.frame(t)
    f = draw_texts(f, [('text', wrap(meta.get('thumb', ''), 120, W - 140), W / 2, 120, 120, (255, 220, 60), 'ma')])
    cv2.imwrite(path, (np.clip(f, 0, 1) * 255).astype(np.uint8)[..., ::-1], [cv2.IMWRITE_JPEG_QUALITY, 92])
    return path
