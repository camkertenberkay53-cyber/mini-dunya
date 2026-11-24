"""Sahne motoru: sahne listesi (JSON) -> sinematik video.

Sahne alanları:
  id, gorsel | katmanlar[{gorsel, derinlik, alfa?}], kamera (HAREKETLER adı ya da {bas, son, ease}), guc, odak [x,y],
  sarsinti (0..1), efektler [{tip: toz|kivilcim|kar|yagmur|duman|sis|isik|parlama|dof, guc, kaynak/odak}],
  ton (sicak|soguk|teal_turuncu), anlatim (metin), konusan (ses anahtarı), sure (en az sn),
  gecis {tip: kesme|cozunme|karartma|flas|savurma|zoom|yonlu, sure} (bir SONRAKİ sahneye geçiş), sesler [davul|top|ruzgar|kalabalik]

Akış: seslendirme (süreyi belirler) -> sahne başına render (önbellekli) -> geçişlerle birleştirme ->
ses karışımı (anlatım + üretilmiş efekt/davul, anlatım altında kısılır) -> ayrı katman altyazı (ASS) -> kalite kontrol.
Hiçbir ücretli servis kullanılmaz."""
import hashlib
import json
import math
import os
import shutil
import subprocess
import time

import cv2
import numpy as np
import soundfile as sf

from .. import paths
from . import efekt, kamera

SURUM = 'sinema-1'
SR = 24000
GECIS_FFMPEG = {'cozunme': 'fade', 'karartma': 'fadeblack', 'flas': 'fadewhite', 'savurma': 'smoothleft',
                'zoom': 'zoomin', 'yonlu': 'wipeleft', 'kesme': 'fade'}


class SinemaHatasi(Exception):
    pass


# ---------------------------------------------------------------- görüntü

def _yukle(path, W, H, zmax=1.45):
    """Görseli bir kez yükle; çıkış çerçevesini en büyük zoomda ~1:1 karşılayacak boyuta getir (hız + keskinlik)."""
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise SinemaHatasi(f'Görsel okunamadı: {path}')
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    ih, iw = img.shape[:2]
    kapla = max(W / iw, H / ih) * 1.04
    hedef = kapla * zmax
    if hedef < 1.0:  # küçült (alias olmasın diye INTER_AREA)
        img = cv2.resize(img, (int(iw * hedef), int(ih * hedef)), interpolation=cv2.INTER_AREA)
    return img


def _cerceve(img, W, H, cx, cy, z, aci, dx=0.0, dy=0.0):
    ih, iw = img.shape[:2]
    s = max(W / iw, H / ih) * 1.04 * z
    hw, hh = W / (2 * s), H / (2 * s)
    px = min(max(cx * iw, hw), iw - hw)
    py = min(max(cy * ih, hh), ih - hh)
    M = cv2.getRotationMatrix2D((px, py), aci, s)
    M[0, 2] += W / 2 - px + dx
    M[1, 2] += H / 2 - py + dy
    bayrak = cv2.INTER_AREA if s < 0.7 else cv2.INTER_LINEAR
    return cv2.warpAffine(img, M, (W, H), flags=bayrak, borderMode=cv2.BORDER_REFLECT)


def _bilesik(katmanlar, W, H, cx, cy, z, aci, dx, dy):
    """Parallax: her katman kamera hareketini derinliği oranında izler (arka plan az, ön plan çok)."""
    taban = None
    for k in katmanlar:
        d = k['derinlik']
        kx, ky = 0.5 + (cx - 0.5) * d, 0.5 + (cy - 0.5) * d
        kz = 1 + (z - 1) * d
        f = _cerceve(k['img'], W, H, kx, ky, kz, aci * d, dx * d, dy * d)
        if f.ndim == 3 and f.shape[2] == 4 and taban is not None:
            a = f[..., 3:4].astype(np.float32) / 255
            taban = (taban * (1 - a) + f[..., :3] * a).astype(np.uint8)
        else:
            taban = np.ascontiguousarray(f[..., :3])
    return taban


def sahne_anahtari(s, W, H, fps):
    alan = {k: s.get(k) for k in ('gorsel', 'katmanlar', 'kamera', 'guc', 'odak', 'sarsinti', 'efektler', 'ton', 'sure_render')}
    h = hashlib.sha1(json.dumps([SURUM, alan, W, H, fps], sort_keys=True, ensure_ascii=False).encode())
    for g in [s.get('gorsel')] + [k.get('gorsel') for k in s.get('katmanlar') or []]:
        if g and os.path.exists(g):
            st = os.stat(g)
            h.update(f'{g}:{st.st_size}:{int(st.st_mtime)}'.encode())
    return h.hexdigest()[:16]


def sahne_render(s, out, W, H, fps, log=print):
    """Tek sahneyi (sessiz, altyazısız) render eder. Altyazı/ses ayrı katman olduğundan metin değişse de önbellek geçerli kalır."""
    sure = s['sure_render']
    n = int(round(sure * fps))
    if s.get('katmanlar'):
        katmanlar = [dict(k, img=_yukle(k['gorsel'], W, H)) for k in s['katmanlar']]
    else:
        katmanlar = [{'img': _yukle(s['gorsel'], W, H), 'derinlik': 1.0}]
    tohum = int(hashlib.md5(s['id'].encode()).hexdigest()[:6], 16)
    fx = []
    for e in s.get('efektler') or []:
        tip, g = e['tip'], float(e.get('guc', 1.0))
        if tip in efekt.Partikul.AYAR:
            fx.append(efekt.Partikul(tip, W, H, g, tohum))
        elif tip in ('duman', 'sis'):
            fx.append(efekt.Duman(tip, W, H, g, tohum))
        elif tip == 'isik':
            fx.append(efekt.IsikHuzmesi(W, H, tuple(e.get('kaynak', (0.75, -0.05))), g, tohum))
        else:
            fx.append(e)  # kare-bazlı fonksiyonlar (parlama, dof)
    vin = efekt.vinyet_maskesi(W, H, s.get('vinyet', 1.0))
    sars = kamera.Sarsinti(guc=14 * float(s.get('sarsinti', 0)), tohum=tohum) if s.get('sarsinti') else None
    darbe_zamanlari = s.get('darbeler') or []  # top atışı vb. anlarda ani sarsıntı
    tmp = out + '.tmp.mp4'
    enc = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{H}', '-r', str(fps),
                            '-i', '-', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '17', '-pix_fmt', 'yuv420p', '-r', str(fps), tmp],
                           stdin=subprocess.PIPE)
    onceki = None
    for i in range(n):
        t = i / fps
        u = t / max(sure, 1e-6)
        cx, cy, z, aci = kamera.konum(s.get('kamera', 'zoom_in'), u, s.get('odak'), float(s.get('guc', 1.0)))
        dx = dy = 0.0
        if sars:
            darbe = 1.0 + sum(4.0 * math.exp(-(t - d) * 5) for d in darbe_zamanlari if t >= d)
            dx, dy, da = sars(t, darbe)
            aci += da
        kare = _bilesik(katmanlar, W, H, cx, cy, z, aci, dx, dy)
        # hızlı kamera hareketinde hareket bulanıklığı
        if onceki is not None:
            hiz = math.hypot(cx - onceki[0], cy - onceki[1]) * fps + abs(z - onceki[2]) * fps
            if hiz > 0.35:
                ara = _bilesik(katmanlar, W, H, (cx + onceki[0]) / 2, (cy + onceki[1]) / 2, (z + onceki[2]) / 2, aci, dx, dy)
                kare = cv2.addWeighted(kare, 0.5, ara, 0.5, 0)
        onceki = (cx, cy, z)
        for f in fx:
            if isinstance(f, dict):
                if f['tip'] == 'parlama':
                    kare = efekt.parlama(kare, float(f.get('guc', 1.0)))
                elif f['tip'] == 'dof':
                    kare = efekt.alan_derinligi(kare, tuple(f.get('odak', (0.5, 0.45))), guc=float(f.get('guc', 1.0)))
            else:
                kare = f.uygula(kare, t)
        if s.get('ton'):
            kare = efekt.renk_tonu(kare, s['ton'], float(s.get('ton_guc', 1.0)))
        kare = (kare.astype(np.float32) * vin).astype(np.uint8)
        kare = efekt.gren(kare, t, 0.6, tohum)
        enc.stdin.write(kare.tobytes())
    enc.stdin.close()
    if enc.wait() != 0:
        raise SinemaHatasi(f'Sahne kodlanamadı: {s["id"]}')
    os.replace(tmp, out)
    return out


# ---------------------------------------------------------------- ses

_BIR = ['', 'bir', 'iki', 'üç', 'dört', 'beş', 'altı', 'yedi', 'sekiz', 'dokuz']
_ON = ['', 'on', 'yirmi', 'otuz', 'kırk', 'elli', 'altmış', 'yetmiş', 'seksen', 'doksan']


def sayi_yazi(n):
    """Türkçe sayı okunuşu (0..999999): 1473 -> 'bin dört yüz yetmiş üç'."""
    if n == 0:
        return 'sıfır'
    out = []
    if n >= 1000:
        b = n // 1000
        out.append('bin' if b == 1 else f'{sayi_yazi(b)} bin')
        n %= 1000
    if n >= 100:
        y = n // 100
        out.append('yüz' if y == 1 else f'{_BIR[y]} yüz')
        n %= 100
    if n >= 10:
        out.append(_ON[n // 10])
        n %= 10
    if n:
        out.append(_BIR[n])
    return ' '.join(out)


def okunus(metin):
    """Seslendirme metni: rakamları yazıya çevirir (ücretsiz TTS sayıları bozuk okuyor). Altyazı rakamlı kalır."""
    import re
    return re.sub(r'\d{1,6}', lambda m: sayi_yazi(int(m.group(0))), metin.replace('.', '. ').replace('  ', ' ')).strip()


def _seslendir(sahneler, cfg, outdir, log):
    """Ücretsiz TTS (config sırası: ücretsiz Gemini kotası -> edge-tts -> yerel Piper).
    Aynı metin + ses ayarı daha önce seslendirildiyse önbellekten gelir (süre sabit kalır, sahne önbelleği bozulmaz)."""
    from ..audio import tts
    kok = os.path.join(paths.OUTPUT, 'ses_onbellek')
    os.makedirs(kok, exist_ok=True)
    os.makedirs(outdir, exist_ok=True)
    sonuc, eksik = {}, []
    for i, s in enumerate(sahneler):
        if not s.get('anlatim'):
            continue
        who = s.get('konusan', 'anlatici')
        a = hashlib.sha1(json.dumps([okunus(s['anlatim']), who, cfg['voices'].get(who), cfg['tts'].get('order')],
                                    sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
        yol = os.path.join(kok, a + '.wav')
        if os.path.exists(yol):
            sonuc[i] = yol
        else:
            eksik.append((i, who, yol))
    motor = 'önbellek'
    if eksik:
        ep = {'scenes': [{'lines': [{'who': who, 'text': okunus(sahneler[i]['anlatim'])}]} for i, who, _ in eksik]}
        model_dir = os.environ.get('PIPER_MODELS', os.path.join(paths.ROOT, 'models'))
        wavs, motor = tts.synthesize(ep, cfg, outdir, model_dir=model_dir, log=log)
        for j, (i, who, yol) in enumerate(eksik):
            shutil.copy(wavs[(j, 0)], yol)
            sonuc[i] = yol
    return sonuc, motor


def _wav(path):
    x, sr = sf.read(path, dtype='float32')
    if x.ndim > 1:
        x = x.mean(axis=1)
    if sr != SR:
        from scipy.signal import resample_poly
        g = math.gcd(sr, SR)
        x = resample_poly(x, SR // g, sr // g).astype(np.float32)
    return x


def ses_kalitesi(x, metin):
    """Kötü sesi yayınlamamak için basit ölçütler."""
    sure = len(x) / SR
    rms = float(np.sqrt(np.mean(x ** 2))) if len(x) else 0
    harf = len(metin.replace(' ', ''))
    hiz = harf / max(sure, 0.1)
    sorun = []
    if rms < 0.01:
        sorun.append('ses çok kısık/boş')
    if np.mean(np.abs(x) > 0.99) > 0.002:
        sorun.append('ses patlıyor (clipping)')
    if not 7 <= hiz <= 24:
        sorun.append(f'konuşma hızı anormal ({hiz:.1f} harf/sn)')
    return sorun


def _sentez(tip, sure, tohum=0):
    """Kendi ürettiğimiz (telifsiz) efekt sesleri."""
    r = np.random.default_rng(tohum)
    n = int(sure * SR)
    t = np.arange(n) / SR
    if tip == 'top':  # top atışı: alçak gümbürtü + gürültü patlaması + kuyruk
        boom = np.sin(2 * np.pi * (38 + 40 * np.exp(-t * 6)) * t) * np.exp(-t * 1.6)
        g = r.normal(0, 1, n) * np.exp(-t * 9)
        g = np.convolve(g, np.ones(40) / 40, 'same')
        return (boom * 0.9 + g * 1.4).astype(np.float32)
    if tip == 'ruzgar':
        g = np.cumsum(r.normal(0, 1, n))
        g -= np.convolve(g, np.ones(4000) / 4000, 'same')
        g /= (np.abs(g).max() + 1e-6)
        return (g * (0.5 + 0.5 * np.sin(2 * np.pi * 0.13 * t + 1))).astype(np.float32) * 0.5
    if tip == 'kalabalik':  # uzak tezahürat: bant geçiren gürültü dalgalanması
        g = r.normal(0, 1, n)
        g = np.convolve(g, np.hanning(60) / 30, 'same') - np.convolve(g, np.hanning(600) / 300, 'same')
        return (g * (0.6 + 0.4 * np.sin(2 * np.pi * 0.7 * t)) * 0.6).astype(np.float32)
    if tip == 'davul':  # savaş davulu (kös): 84 vuruş/dk, vurgulu
        out = np.zeros(n, np.float32)
        aralik = 60 / 84
        k = 0
        while k * aralik < sure:
            b = int(k * aralik * SR)
            tt = np.arange(min(int(0.9 * SR), n - b)) / SR
            vurgu = 1.0 if k % 4 == 0 else 0.6
            hit = np.sin(2 * np.pi * (52 + 70 * np.exp(-tt * 30)) * tt) * np.exp(-tt * 5.5) * vurgu
            hit += r.normal(0, 1, len(tt)) * np.exp(-tt * 60) * 0.25 * vurgu
            out[b:b + len(tt)] += hit.astype(np.float32)
            k += 1
        return out
    return np.zeros(n, np.float32)


# ---------------------------------------------------------------- altyazı

def _ass_zaman(x):
    h = int(x // 3600)
    m = int(x % 3600 // 60)
    s = x % 60
    return f'{h}:{m:02d}:{s:05.2f}'


def altyazi_parcala(metin, bas, sure, en_cok=5):
    """Metni okunur parçalara böler; zamanı harf sayısına göre dağıtır (TTS sabit hızlı olduğundan sesle örtüşür)."""
    kelime = metin.split()
    parcalar, cur = [], []
    for w in kelime:
        cur.append(w)
        if len(cur) >= en_cok or w[-1:] in '.!?,;:…':
            parcalar.append(' '.join(cur))
            cur = []
    if cur:
        parcalar.append(' '.join(cur))
    toplam = sum(len(p) + 3 for p in parcalar)
    out, t = [], bas
    for p in parcalar:
        d = sure * (len(p) + 3) / toplam
        out.append((t, t + d, p))
        t += d
    return out


def ass_yaz(satirlar, path, W, H, kanca=None, kanca_sure=2.6):
    boy = int(W * 0.084)
    kboy = int(W * 0.105)
    stil = (f'Style: Ana,Baloo 2,{boy},&H00FFFFFF,&H00FFFFFF,&H00101010,&H64000000,-1,0,0,0,100,100,0,0,1,{max(3, boy // 14)},2,2,'
            f'{int(W * 0.07)},{int(W * 0.07)},{int(H * 0.27)},1\n'
            f'Style: Kanca,Baloo 2,{kboy},&H0030D8FF,&H0030D8FF,&H00101010,&H78000000,-1,0,0,0,100,100,0,0,1,{max(4, kboy // 12)},3,8,'
            f'{int(W * 0.06)},{int(W * 0.06)},{int(H * 0.16)},1')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(f'[Script Info]\nScriptType: v4.00+\nPlayResX: {W}\nPlayResY: {H}\nWrapStyle: 0\n\n[V4+ Styles]\n'
                'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, '
                'StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n'
                f'{stil}\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n')
        for a, b, t in satirlar:
            f.write(f'Dialogue: 0,{_ass_zaman(a)},{_ass_zaman(b)},Ana,,0,0,0,,{{\\fad(80,80)}}{t}\n')
        if kanca:
            f.write(f'Dialogue: 1,{_ass_zaman(0.05)},{_ass_zaman(kanca_sure)},Kanca,,0,0,0,,{{\\fad(120,250)}}{kanca}\n')


# ---------------------------------------------------------------- kalite kontrol

def kalite_kontrol(path, W, H, fps, hedef_sure=None, sahneler=None):
    """Yayın öncesi teknik kontrol. Yalnızca gerçekten ölçülen değerler raporlanır."""
    r = {'kritik': [], 'uyari': []}
    p = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type,width,height,r_frame_rate:format=duration',
                        '-of', 'json', path], capture_output=True, text=True)
    info = json.loads(p.stdout or '{}')
    v = [s for s in info.get('streams', []) if s['codec_type'] == 'video']
    a = [s for s in info.get('streams', []) if s['codec_type'] == 'audio']
    sure = float(info.get('format', {}).get('duration', 0))
    r['sure'] = round(sure, 2)
    if not v:
        r['kritik'].append('görüntü akışı yok')
        return r
    r['cozunurluk'] = f"{v[0]['width']}x{v[0]['height']}"
    num, den = v[0]['r_frame_rate'].split('/')
    r['fps'] = round(float(num) / float(den), 2)
    if (v[0]['width'], v[0]['height']) != (W, H):
        r['kritik'].append(f'çözünürlük {r["cozunurluk"]} (beklenen {W}x{H})')
    if abs(r['fps'] - fps) > 0.5:
        r['kritik'].append(f'fps {r["fps"]} (beklenen {fps})')
    if not a:
        r['kritik'].append('ses akışı yok')
    else:
        vd = subprocess.run(['ffmpeg', '-hide_banner', '-i', path, '-af', 'volumedetect', '-vn', '-f', 'null', '-'], capture_output=True, text=True).stderr
        mv = [float(l.split(':')[1].split()[0]) for l in vd.splitlines() if 'mean_volume' in l]
        mx = [float(l.split(':')[1].split()[0]) for l in vd.splitlines() if 'max_volume' in l]
        r['ses_ortalama_db'] = mv[0] if mv else None
        r['ses_tepe_db'] = mx[0] if mx else None
        if mv and mv[0] < -40:
            r['kritik'].append(f'ses çok düşük ({mv[0]} dB)')
        if mx and mx[0] >= -0.05:
            r['uyari'].append('ses tepe noktası 0 dB (patlama riski)')
    bd = subprocess.run(['ffmpeg', '-hide_banner', '-i', path, '-vf', 'blackdetect=d=0.25:pix_th=0.06', '-an', '-f', 'null', '-'],
                        capture_output=True, text=True).stderr
    siyah = [l for l in bd.splitlines() if 'black_start' in l]
    r['siyah_bolum'] = len(siyah)
    if siyah:
        r['kritik'].append(f'{len(siyah)} siyah bölüm')
    fd = subprocess.run(['ffmpeg', '-hide_banner', '-i', path, '-vf', 'freezedetect=n=0.0008:d=1.5', '-an', '-f', 'null', '-'],
                        capture_output=True, text=True).stderr
    don = [l.split('freeze_start:')[1].strip() for l in fd.splitlines() if 'freeze_start' in l]
    r['donuk_bolum'] = len(don)
    if don:
        r['uyari'].append(f'donuk görüntü: {", ".join(don[:3])} sn')
    if hedef_sure and abs(sure - hedef_sure) > 1.0:
        r['kritik'].append(f'süre {sure:.1f} sn (planlanan {hedef_sure:.1f})')
    if sahneler:
        imza = [(s.get('gorsel'), json.dumps(s.get('kamera'))) for s in sahneler]
        if len(set(imza)) < len(imza):
            r['kritik'].append('aynı görsel aynı kamera hareketiyle tekrar kullanılmış')
    r['gecti'] = not r['kritik']
    return r


# ---------------------------------------------------------------- ana akış

def video_uret(senaryo, outdir, cfg, W=1080, H=1920, fps=30, log=print):
    """senaryo: {'baslik', 'sahneler': [...], 'muzik': [davul, ruzgar...]} -> (video yolu, rapor)."""
    t0 = time.time()
    os.makedirs(outdir, exist_ok=True)
    cache = os.path.join(paths.OUTPUT, 'sahne_onbellek')
    os.makedirs(cache, exist_ok=True)
    sahneler = [dict(s) for s in senaryo['sahneler']]
    for i, s in enumerate(sahneler):
        s.setdefault('id', f's{i + 1}')
        for k in [s] + list(s.get('katmanlar') or []):  # repo içi göreli yollar
            if k.get('gorsel') and not os.path.isabs(k['gorsel']):
                k['gorsel'] = os.path.join(paths.ROOT, k['gorsel'])

    # 1) seslendirme: sahne süresini konuşma belirler
    wavs, motor = _seslendir(sahneler, cfg, os.path.join(outdir, 'ses'), log)
    log(f'  Seslendirme: {motor}')
    sesler, dinleme = {}, []
    for i, s in enumerate(sahneler):
        if i in wavs:
            x = _wav(wavs[i])
            sorun = ses_kalitesi(x, okunus(s['anlatim']))
            try:  # sesi yazıya çevir: senaryodaki metin gerçekten anlaşılıyor mu?
                from . import dinle
                duyulan = dinle.yaziya_cevir(x, SR)
                oran = dinle.benzerlik(okunus(s['anlatim']), duyulan)
                dinleme.append({'sahne': s['id'], 'beklenen': s['anlatim'], 'duyulan': duyulan, 'benzerlik': round(oran, 2)})
                if oran < 0.6:
                    sorun.append(f'anlaşılmıyor (duyulan: "{duyulan}", benzerlik {oran:.2f})')
            except Exception as e:
                log(f'  Dinleme kontrolü yapılamadı: {str(e)[:100]}')
            if sorun:
                raise SinemaHatasi(f'Ses kalitesi yetersiz ({s["id"]}): {", ".join(sorun)}')
            sesler[i] = x

    # 2) süreler: konuşma, geçiş bindirmesinin içine düşmesin
    gecisler = []
    for i, s in enumerate(sahneler):
        g = s.get('gecis') or {'tip': 'cozunme', 'sure': 0.5}
        T = 1.0 / fps if g['tip'] == 'kesme' else float(g.get('sure', 0.5))
        gecisler.append((g['tip'], T) if i < len(sahneler) - 1 else ('yok', 0.0))
    planlar = []
    for i, s in enumerate(sahneler):
        T_in = gecisler[i - 1][1] if i else 0.0
        T_out = gecisler[i][1]
        on = max(0.35, T_in + 0.15)
        konusma = len(sesler[i]) / SR if i in sesler else 0.0
        arka = max(0.5, T_out + 0.2) + (0.8 if i == len(sahneler) - 1 else 0)
        s['sure_render'] = round(max(float(s.get('sure', 0)), on + konusma + arka), 2)
        planlar.append((on, konusma))

    # 3) sahne render (önbellek)
    klipler = []
    for s in sahneler:
        anahtar = sahne_anahtari(s, W, H, fps)
        yol = os.path.join(cache, f'{anahtar}.mp4')
        if os.path.exists(yol):
            log(f'  {s["id"]}: önbellekten ({s["sure_render"]} sn)')
        else:
            ts = time.time()
            sahne_render(s, yol, W, H, fps, log)
            log(f'  {s["id"]}: render {s["sure_render"]} sn -> {time.time() - ts:.0f} sn sürdü')
        klipler.append(yol)

    # 4) geçişlerle birleştir
    basl = [0.0]
    for i in range(1, len(sahneler)):
        basl.append(basl[-1] + sahneler[i - 1]['sure_render'] - gecisler[i - 1][1])
    toplam = basl[-1] + sahneler[-1]['sure_render']
    sessiz = os.path.join(outdir, 'goruntu.mp4')
    if len(klipler) == 1:
        shutil.copy(klipler[0], sessiz)
    else:
        girdi, fc, son = [], [], '[0:v]'
        for k in klipler:
            girdi += ['-i', k]
        for i in range(1, len(klipler)):
            tip, T = gecisler[i - 1]
            etiket = f'[v{i}]'
            fc.append(f'{son}[{i}:v]xfade=transition={GECIS_FFMPEG.get(tip, "fade")}:duration={T:.3f}:offset={basl[i]:.3f}{etiket}')
            son = etiket
        subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', *girdi, '-filter_complex', ';'.join(fc), '-map', son,
                        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '17', '-pix_fmt', 'yuv420p', '-r', str(fps), sessiz], check=True)

    # 5) ses karışımı
    n = int(math.ceil(toplam * SR)) + SR
    anlatim = np.zeros(n, np.float32)
    efektler = np.zeros(n, np.float32)
    altyazi = []
    for i, s in enumerate(sahneler):
        on, konusma = planlar[i]
        if i in sesler:
            b = int((basl[i] + on) * SR)
            x = sesler[i] / (np.abs(sesler[i]).max() + 1e-6) * 0.89
            anlatim[b:b + len(x)] += x
            altyazi += altyazi_parcala(s['anlatim'], basl[i] + on, konusma)
        for j, tip in enumerate(s.get('sesler') or []):
            ad, ofs = (tip, 0.0) if isinstance(tip, str) else (tip['tip'], float(tip.get('zaman', 0)))
            d = min(s['sure_render'] - ofs, 6.0 if ad == 'top' else s['sure_render'])
            y = _sentez(ad, d, i * 10 + j)
            b = int((basl[i] + ofs) * SR)
            efektler[b:b + len(y)] += y * {'top': 0.9, 'davul': 0.45, 'ruzgar': 0.35, 'kalabalik': 0.3}.get(ad, 0.4)
    for j, tip in enumerate(senaryo.get('muzik') or []):  # tüm video boyunca altta
        efektler[:int(toplam * SR)] += _sentez(tip, toplam, 99 + j)[:int(toplam * SR)] * {'davul': 0.32, 'ruzgar': 0.22}.get(tip, 0.25)
    # konuşma varken efektleri kıs (ducking)
    zarf = np.convolve((np.abs(anlatim) > 0.02).astype(np.float32), np.ones(SR // 5) / (SR // 5), 'same')
    efektler *= (1 - 0.6 * np.clip(zarf * 3, 0, 1))
    mix = anlatim + efektler
    tepe = np.abs(mix).max()
    if tepe > 0.95:
        mix *= 0.95 / tepe
    wav = os.path.join(outdir, 'karisim.wav')
    sf.write(wav, mix[:int(toplam * SR)], SR)

    # 6) altyazı katmanı + birleştir
    ass = os.path.join(outdir, 'altyazi.ass')
    ass_yaz(altyazi, ass, W, H, kanca=senaryo.get('kanca'))
    final = os.path.join(outdir, 'video.mp4')
    fontdir = os.path.dirname(paths.FONT)
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', sessiz, '-i', wav,
                    '-vf', f"ass={ass}:fontsdir={fontdir}", '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18',
                    '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k', '-shortest', final], check=True)
    with open(os.path.join(outdir, 'altyazi.json'), 'w', encoding='utf-8') as f:
        json.dump([{'bas': round(a, 2), 'son': round(b, 2), 'metin': t} for a, b, t in altyazi], f, ensure_ascii=False, indent=1)

    # 7) kalite kontrol
    rapor = kalite_kontrol(final, W, H, fps, toplam, sahneler)
    rapor['render_sn'] = round(time.time() - t0, 1)
    rapor['seslendirme'] = motor
    rapor['dinleme'] = dinleme
    with open(os.path.join(outdir, 'kalite.json'), 'w', encoding='utf-8') as f:
        json.dump(rapor, f, ensure_ascii=False, indent=1)
    log(f"  Kalite: {'GEÇTİ' if rapor['gecti'] else 'KALDI'} | {rapor}")
    return final, rapor
