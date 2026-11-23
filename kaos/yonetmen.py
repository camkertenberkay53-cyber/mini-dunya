"""Yapay Zekâ Video Yönetmeni (eleştirmen).
Üretilen GERÇEK videodan kritik anlarda kare alır, Gemini'ye (görsel) değerlendirtir, 100 üzerinden puanlar ve rapor yazar.
Şimdilik RAPOR MODU: yayını durdurmaz (puanlar gerçek izlenmelerle karşılaştırılıp kalibre edildikten sonra karar verici olacak).
Ses puanı, teknik kontrolün (qc) ölçümlerinden hesaplanır."""
import base64
import json
import os
import re

import cv2

KRITER = {'acilis': 20, 'anlasilirlik': 15, 'animasyon': 15, 'karakter_tutarliligi': 10, 'tempo': 15, 'gorsel': 10, 'final': 10, 'ses': 5}


def kareler(path, tl, outdir):
    """İlk kare, 1. ve 3. saniye, sahne başları, orta, sürpriz (en büyük hareket), final ve son kare."""
    cap = cv2.VideoCapture(path)
    dur = (cap.get(cv2.CAP_PROP_FRAME_COUNT) or 1) / (cap.get(cv2.CAP_PROP_FPS) or 30)
    end = tl.get('end_start', dur - 3)
    anlar = {'ilk_kare': 0.0, '1_saniye': 1.0, '3_saniye': 3.0, 'orta': end * 0.5, 'final': max(0.0, end - 1.0), 'son_kare': dur - 0.1}
    for i, sc in enumerate(tl.get('scenes', [])[:6]):
        anlar[f'sahne_{i + 1}'] = sc[0] + 0.8
    # sürpriz anı: iki kare arası en büyük değişim (kaba tarama)
    best, prev, t = (0, end * 0.65), None, 2.0
    while t < end:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, fr = cap.read()
        if not ok:
            break
        small = cv2.resize(fr, (54, 96)).astype('float32')
        if prev is not None:
            d = float(abs(small - prev).mean())
            if d > best[0]:
                best = (d, t)
        prev, t = small, t + 0.5
    anlar['surpriz'] = best[1]
    out = []
    for ad, t in sorted(anlar.items(), key=lambda x: x[1]):
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, min(dur - 0.05, t)) * 1000)
        ok, fr = cap.read()
        if not ok:
            continue
        h, w = fr.shape[:2]
        fr = cv2.resize(fr, (w // 2, h // 2))
        fn = os.path.join(outdir, f'kare_{ad}.jpg')
        cv2.imwrite(fn, fr, [cv2.IMWRITE_JPEG_QUALITY, 80])
        out.append((ad, round(t, 1), fn))
    cap.release()
    return out


def degerlendir(ep, tl, video, outdir, cfg, qc_rep=None, log=print):
    from .writer import list_models, _model_order, _post
    ks = kareler(video, tl, outdir)
    try:  # önizleme: Claude'un ve ekibin videoyu görebilmesi için kareleri state/'e yaz (her bölümde üzerine yazılır)
        from . import paths
        ims = [cv2.resize(cv2.imread(fn), (270, 480)) for _, _, fn in ks[:10]]
        while len(ims) % 5:
            ims.append(ims[-1] * 0)
        import numpy as _np
        sheet = _np.vstack([_np.hstack(ims[i:i + 5]) for i in range(0, len(ims), 5)])
        cv2.imwrite(os.path.join(paths.STATE, 'onizleme_son.jpg'), sheet, [cv2.IMWRITE_JPEG_QUALITY, 80])
    except Exception as e:
        log(f'  önizleme yazılamadı: {e}')
    senaryo = [f"{l['who']}: {l['text']} ({l.get('action', 'yok')})" for sc in ep['scenes'] for l in sc['lines']]
    prompt = f"""Sen deneyimli bir animasyon yönetmeni ve YouTube Shorts editörüsün. Aşağıda "Mini Dünya" (2D, parmak boyundaki
haritacıların evi keşfettiği aile dizisi) için ÜRETİLMİŞ GERÇEK VİDEODAN alınmış kareler var. Karelerin hangi anda alındığı
etiketlerinde yazıyor. Senaryo yalnızca bağlam içindir; puanı GÖRDÜĞÜN karelere göre ver.
Senaryo: {json.dumps(senaryo, ensure_ascii=False)}
Açılış yazısı: {ep.get('kapak_yazisi')} | açılış efekti: {ep.get('acilis_efekti')} | süre: {tl.get('total', 0):.0f} sn

Kontrol et: karakter kaybolması/yanlış yerde olması, boyut tutarsızlığı, yüz-göz bozulması, katman hatası, zemine oturmama,
havada kalan nesne, kötü kamera/kadraj, boş sahne, görsel karmaşa, okunmayan ya da taşan yazı, ilk karenin durduruculuğu,
sessiz izlenince anlaşılırlık, tempo, finalin tatmin ediciliği, tekrar izlenebilirlik.
Puanla (tam sayı): acilis 0-20, anlasilirlik 0-15, animasyon 0-15, karakter_tutarliligi 0-10, tempo 0-15, gorsel 0-10, final 0-10.
Sadece JSON döndür: {{"puanlar": {{"acilis": 0, "anlasilirlik": 0, "animasyon": 0, "karakter_tutarliligi": 0, "tempo": 0, "gorsel": 0, "final": 0}},
"en_iyi_sahne": "kare etiketi + neden", "en_zayif_sahne": "kare etiketi + neden", "acilis_degerlendirmesi": "...",
"tempo_degerlendirmesi": "...", "gorsel_hatalar": ["somut hata (kare etiketiyle)"], "oneriler": ["bir sonraki bölüm için 1-3 somut öneri"]}}"""
    parts = [{'text': prompt}]
    for ad, t, fn in ks:
        parts.append({'text': f'[{ad} — {t} sn]'})
        with open(fn, 'rb') as f:
            parts.append({'inline_data': {'mime_type': 'image/jpeg', 'data': base64.b64encode(f.read()).decode()}})
    key = os.environ.get('GEMINI_API_KEY', '')
    models = _model_order(cfg['senaryo'].get('modeller', []), list_models(key, 'text'))
    rep = None
    import time
    deneme = [m for m in models[:3]] * 2  # Gemini yoğunluk (503) verirse 30 sn bekleyip bir tur daha dene
    for k, model in enumerate(deneme):
        if k == 3:
            time.sleep(30)
        try:
            d = _post(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}',
                      {'contents': [{'role': 'user', 'parts': parts}],
                       'generationConfig': {'temperature': 0.3, 'responseMimeType': 'application/json'}}, timeout=180)
            txt = ''.join(p.get('text', '') for p in d['candidates'][0]['content']['parts'])
            rep = json.loads(re.sub(r'^```(json)?|```$', '', txt.strip()).strip())
            break
        except Exception as e:
            log(f'  Yönetmen ({model}) hata: {str(e)[:120]}')
    if not rep:
        return None
    p = rep.get('puanlar') or {}
    for k, mx in KRITER.items():
        p[k] = max(0, min(mx, int(p.get(k) or 0)))
    # ses puanı ölçümden (5): seviye -16..-12 LUFS, tepe < -0.5 dBFS, ses var
    ses = 5
    if qc_rep:
        lufs, tp = qc_rep.get('ses_lufs'), qc_rep.get('ses_tepe_db')
        if lufs is None or lufs < -20 or lufs > -9:
            ses -= 2
        if tp is not None and tp > -0.3:
            ses -= 2
        if any('sessizlik' in str(x) for x in qc_rep.get('dusuk', [])):
            ses -= 1
    p['ses'] = max(0, ses)
    toplam = sum(p.values())
    karar = ('Yayına hazır' if toplam >= 90 else 'Yayınlanabilir, küçük kusurlar' if toplam >= 80
             else 'Düzeltme önerilir' if toplam >= 70 else 'Yeniden üretim / manuel inceleme gerekli')
    rep.update(puanlar=p, toplam=toplam, karar=karar, mod='rapor (yayını durdurmaz)', kareler=[a for a, _, _ in ks])
    with open(os.path.join(outdir, 'yonetmen.json'), 'w', encoding='utf-8') as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    log(f"Yönetmen puanı: {toplam}/100 ({karar}) | " + ', '.join(f'{k} {v}/{KRITER[k]}' for k, v in p.items())
        + f" | en zayıf: {rep.get('en_zayif_sahne', '')[:80]}")
    return rep


def son_video(kok='output/son', log=print):
    """gorev=yonetmen: son yüklenen bölümün videosunu (GitHub çıktısından indirilmiş) yeniden değerlendir."""
    import glob
    import subprocess
    from . import paths
    from .main import load_cfg
    vids = sorted(glob.glob(os.path.join(kok, '**', 'video.mp4'), recursive=True))
    vids = [v for v in vids if '_en' not in v] or vids
    if not vids:
        raise SystemExit('Video bulunamadı')
    v = vids[0]
    d = os.path.dirname(v)
    with open(os.path.join(d, 'senaryo.json'), encoding='utf-8') as f:
        ep = json.load(f)
    dur = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', v],
                               capture_output=True, text=True).stdout.strip() or 30)
    tl = {'total': dur, 'end_start': dur - 3.2, 'scenes': []}
    qc_rep = None
    try:
        with open(os.path.join(d, 'qc.json'), encoding='utf-8') as f:
            qc_rep = json.load(f)
    except Exception:
        pass
    rep = degerlendir(ep, tl, v, d, load_cfg(), qc_rep=qc_rep, log=log)
    with open(os.path.join(paths.STATE, 'yonetmen_son.json'), 'w', encoding='utf-8') as f:
        json.dump({'video': v, 'baslik': ep.get('baslik'), 'rapor': rep}, f, ensure_ascii=False, indent=1)
    print(json.dumps(rep, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    son_video()
