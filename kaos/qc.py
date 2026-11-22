"""Teknik video kontrolü (ücretsiz: FFmpeg + OpenCV).
Kritik hata: yayınlanmaz (QCError). Orta: güvenliyse otomatik düzeltilir (ses seviyesi). Düşük: raporlanır."""
import json
import os
import re
import shutil
import subprocess

import numpy as np


class QCError(Exception):
    pass


def _run(args, timeout=600):
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def probe(path):
    code, out, err = _run(['ffprobe', '-v', 'error', '-show_entries',
                           'format=duration,size:stream=codec_type,width,height,r_frame_rate,nb_frames',
                           '-of', 'json', path])
    if code != 0:
        raise QCError(f'dosya okunamadı: {err[:200]}')
    return json.loads(out)


def _filters(path):
    """Tek geçişte siyah kare, donma, sessizlik ve ses seviyesi analizi."""
    _, _, err = _run(['ffmpeg', '-hide_banner', '-nostats', '-i', path,
                      '-vf', 'blackdetect=d=0.4:pic_th=0.97,freezedetect=n=0.0015:d=3.5',
                      '-af', 'silencedetect=n=-45dB:d=2.5,volumedetect,ebur128=peak=true',
                      '-f', 'null', '-'], timeout=900)
    black = [(float(a), float(b)) for a, b in re.findall(r'black_start:([\d.]+) black_end:([\d.]+)', err)]
    fr_s = [float(x) for x in re.findall(r'freeze_start: ([\d.]+)', err)]
    fr_e = [float(x) for x in re.findall(r'freeze_end: ([\d.]+)', err)]
    freezes = list(zip(fr_s, fr_e + [None] * (len(fr_s) - len(fr_e))))
    sil_s = [float(x) for x in re.findall(r'silence_start: ([\d.]+)', err)]
    sil_e = [float(x) for x in re.findall(r'silence_end: ([\d.]+)', err)]
    silences = list(zip(sil_s, sil_e + [None] * (len(sil_s) - len(sil_e))))
    mean = re.findall(r'mean_volume: (-?[\d.]+) dB', err)
    peak = re.findall(r'max_volume: (-?[\d.]+) dB', err)
    lufs = re.findall(r'I:\s+(-?[\d.]+) LUFS', err)
    tpk = re.findall(r'Peak:\s+(-?[\d.]+) dBFS', err)
    return dict(black=black, freezes=freezes, silences=silences,
                mean_db=float(mean[-1]) if mean else None, max_db=float(peak[-1]) if peak else None,
                lufs=float(lufs[-1]) if lufs else None, true_peak=float(tpk[-1]) if tpk else None)


def _frames(path, dur, n=12):
    """Eşit aralıklı kareler: tekrar eden ve boş/tekdüze kareleri yakalamak için."""
    import cv2
    cap = cv2.VideoCapture(path)
    out = []
    for i in range(n):
        t = min(dur - 0.05, max(0.0, dur * (i + 0.5) / n))
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, fr = cap.read()
        if ok:
            out.append((t, cv2.resize(fr, (90, 160))))
    cap.release()
    return out


def check(path, W, H, fps=30, expected_dur=None, outdir=None, log=print, fix=True):
    rep = {'dosya': os.path.basename(path), 'kritik': [], 'orta': [], 'dusuk': [], 'duzeltmeler': []}
    if not os.path.exists(path) or os.path.getsize(path) < 50_000:
        raise QCError('video dosyası yok ya da çok küçük (render yarıda kalmış olabilir)')
    info = probe(path)
    fmt = info.get('format', {})
    dur = float(fmt.get('duration', 0) or 0)
    size_mb = int(fmt.get('size', 0) or 0) / 1e6
    v = [s for s in info.get('streams', []) if s.get('codec_type') == 'video']
    a = [s for s in info.get('streams', []) if s.get('codec_type') == 'audio']
    rep.update(sure_sn=round(dur, 1), boyut_mb=round(size_mb, 1))
    if not v:
        rep['kritik'].append('görüntü akışı yok')
    else:
        vs = v[0]
        rep['cozunurluk'] = f"{vs.get('width')}x{vs.get('height')}"
        num, den = (vs.get('r_frame_rate') or '0/1').split('/')
        rep['fps'] = round(float(num) / max(1.0, float(den)), 2)
        if (vs.get('width'), vs.get('height')) != (W, H):
            rep['kritik'].append(f"çözünürlük {rep['cozunurluk']}, beklenen {W}x{H}")
        if abs(rep['fps'] - fps) > 0.5:
            rep['kritik'].append(f"fps {rep['fps']}, beklenen {fps}")
    if not a:
        rep['kritik'].append('ses akışı yok')
    if dur < 8:
        rep['kritik'].append(f'video çok kısa ({dur:.1f} sn)')
    if expected_dur and abs(dur - expected_dur) > max(2.0, expected_dur * 0.08):
        rep['kritik'].append(f'süre {dur:.1f} sn, beklenen {expected_dur:.1f} sn (render eksik olabilir)')
    if W < H and dur > 180:
        rep['orta'].append(f'dikey video 3 dakikadan uzun ({dur:.0f} sn); Shorts sayılmayabilir')
    mb_per_min = size_mb / max(dur / 60, 0.01)
    if mb_per_min < 0.8:
        rep['orta'].append(f'dosya boyutu anormal küçük ({mb_per_min:.1f} MB/dk)')

    f = _filters(path)
    black_total = sum(b - a_ for a_, b in f['black'])
    rep['siyah_sn'] = round(black_total, 1)
    long_black = [(a_, b) for a_, b in f['black'] if b - a_ > 1.6]
    if long_black:
        rep['kritik'].append(f'uzun siyah ekran: {[(round(a_, 1), round(b, 1)) for a_, b in long_black]}')
    elif black_total > 0.5:
        rep['dusuk'].append(f'kısa siyah kareler toplam {black_total:.1f} sn (geçişler)')
    if f['freezes']:
        fr = [(round(s, 1), round(e, 1) if e else None) for s, e in f['freezes']]
        rep['orta' if any((e or dur) - s > 6 for s, e in f['freezes']) else 'dusuk'].append(f'donmuş görüntü: {fr}')
    long_sil = [(s, e) for s, e in f['silences'] if ((e or dur) - s) > 4.0]
    if long_sil:
        rep['dusuk'].append(f'uzun sessizlik: {[(round(s, 1), round(e, 1) if e else None) for s, e in long_sil]}')
    rep['ses_lufs'] = f['lufs']
    rep['ses_tepe_db'] = f['true_peak']
    if f['mean_db'] is not None and f['mean_db'] < -50:
        rep['kritik'].append(f"ses neredeyse yok (ortalama {f['mean_db']} dB)")
    audio_fix = None
    if f['lufs'] is not None and (f['lufs'] < -19 or f['lufs'] > -10):
        audio_fix = f"ses seviyesi {f['lufs']} LUFS (hedef -14)"
    if f['true_peak'] is not None and f['true_peak'] > -0.3:
        audio_fix = (audio_fix + '; ' if audio_fix else '') + f"ses tepe noktası {f['true_peak']} dBFS (patlama riski)"
    if audio_fix:
        rep['orta'].append(audio_fix)

    # kare bazlı: tekrar eden / tekdüze kareler
    try:
        frames = _frames(path, dur)
        flat = [round(t, 1) for t, fr in frames if fr.std() < 6]
        if flat:
            rep['dusuk'].append(f'tekdüze (boş) görünen kareler: {flat}')
        same = 0
        for (_, a1), (_, b1) in zip(frames, frames[1:]):
            if np.abs(a1.astype(np.int16) - b1.astype(np.int16)).mean() < 1.0:
                same += 1
        if same >= 3:
            rep['orta'].append(f'{same} örnek kare birbirinin aynısı (animasyon durmuş olabilir)')
    except Exception as e:
        rep['dusuk'].append(f'kare analizi yapılamadı: {e}')

    # orta seviye: ses düzeltmesi (görüntüye dokunmadan)
    if fix and audio_fix and a and not rep['kritik']:
        tmp = path + '.ses.mp4'
        code, _, err = _run(['ffmpeg', '-y', '-loglevel', 'error', '-i', path, '-c:v', 'copy',
                             '-af', 'loudnorm=I=-14:TP=-1.0:LRA=11', '-c:a', 'aac', '-b:a', '160k', tmp])
        if code == 0 and os.path.getsize(tmp) > 50_000:
            shutil.move(tmp, path)
            rep['duzeltmeler'].append('ses seviyesi -14 LUFS / tepe -1 dBFS olarak normalize edildi')
        else:
            rep['dusuk'].append(f'ses düzeltmesi yapılamadı: {err[:120]}')

    rep['karar'] = 'YAYINLANMAZ' if rep['kritik'] else ('yayınlanabilir (düzeltildi/raporlandı)' if rep['orta'] else 'yayına hazır')
    if outdir:
        with open(os.path.join(outdir, 'qc.json'), 'w', encoding='utf-8') as fh:
            json.dump(rep, fh, ensure_ascii=False, indent=1)
    log(f"Teknik kontrol: {rep['karar']} | {rep.get('sure_sn')} sn, {rep.get('cozunurluk')}, {rep.get('fps')} fps, "
        f"ses {rep.get('ses_lufs')} LUFS, siyah {rep.get('siyah_sn')} sn"
        + (f" | kritik: {rep['kritik']}" if rep['kritik'] else '')
        + (f" | orta: {rep['orta']}" if rep['orta'] else '')
        + (f" | düşük: {rep['dusuk']}" if rep['dusuk'] else '')
        + (f" | düzeltme: {rep['duzeltmeler']}" if rep['duzeltmeler'] else ''))
    if rep['kritik']:
        raise QCError('; '.join(rep['kritik']))
    return rep
