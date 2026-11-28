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

SURUM = 'sinema-4'
SR = 24000
GECIS_FFMPEG = {'cozunme': 'fade', 'karartma': 'fadeblack', 'flas': 'fade', 'savurma': 'smoothleft',
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


EK_ALANLAR = ('ozne_maskesi', 'arka_plan_dolgu', 'zemin_derinlik_aktif', 'izleme_oranlari', 'nefes_aktif', 'nefes_genlik',
              'titresimsiz')


def sahne_anahtari(s, W, H, fps):
    alan = {k: s.get(k) for k in ('gorsel', 'katmanlar', 'kamera', 'guc', 'odak', 'sarsinti', 'efektler', 'ton', 'sure_render', 'kirp',
                                  'parallax', 'ozne', 'ufuk', 'atislar', 'darbeler', 'giris_flas', 'yorunge', 'gren', 'vinyet')}
    ek = {k: s[k] for k in EK_ALANLAR if k in s}  # isteğe bağlı alanlar yalnızca verilince (eski anahtarlar değişmez)
    h = hashlib.sha1(json.dumps([SURUM, alan, W, H, fps] + ([ek] if ek else []), sort_keys=True, ensure_ascii=False).encode())
    for g in [s.get('gorsel')] + [k.get('gorsel') for k in s.get('katmanlar') or []] + [s.get('ozne_maskesi'), s.get('arka_plan_dolgu')]:
        if g and os.path.exists(g):
            st = os.stat(g)
            h.update(f'{g}:{st.st_size}:{int(st.st_mtime)}'.encode())
    return h.hexdigest()[:16]


def _goruntu_konumu(M, p, iw, ih):
    return (M[0, 0] * p[0] * iw + M[0, 1] * p[1] * ih + M[0, 2], M[1, 0] * p[0] * iw + M[1, 1] * p[1] * ih + M[1, 2])


def _matris(img, W, H, cx, cy, z, aci, dx=0.0, dy=0.0):
    ih, iw = img.shape[:2]
    s_ = max(W / iw, H / ih) * 1.04 * z
    hw, hh = W / (2 * s_), H / (2 * s_)
    px = min(max(cx * iw, hw), iw - hw)
    py = min(max(cy * ih, hh), ih - hh)
    M = cv2.getRotationMatrix2D((px, py), aci, s_)
    M[0, 2] += W / 2 - px + dx
    M[1, 2] += H / 2 - py + dy
    return M, s_


def _isik(kare, xy, r, renk, guc):
    """Noktasal ışık (namlu ışığı, ateş): yumuşak radyal parlama, eklemeli."""
    if guc <= 0.01:
        return kare
    H, W = kare.shape[:2]
    x0, y0 = int(max(0, xy[0] - 2 * r)), int(max(0, xy[1] - 2 * r))
    x1, y1 = int(min(W, xy[0] + 2 * r)), int(min(H, xy[1] + 2 * r))
    if x1 <= x0 or y1 <= y0:
        return kare
    yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
    m = np.exp(-((xx - xy[0]) ** 2 + (yy - xy[1]) ** 2) / (2 * (r * 0.6) ** 2)) * guc
    bolge = kare[y0:y1, x0:x1].astype(np.float32) + m[..., None] * np.array(renk, np.float32)
    kare = kare.copy()
    kare[y0:y1, x0:x1] = np.clip(bolge, 0, 255).astype(np.uint8)
    return kare


def _omuz(kare, esik=0.78):
    """Parlaklık koruması: açık tonları yumuşakça sıkıştırır, beyaza patlamayı önler."""
    k = kare.astype(np.float32) / 255
    ust = k > esik
    k[ust] = esik + (1 - esik) * (1 - np.exp(-(k[ust] - esik) / (1 - esik) * 1.6)) / (1 - np.exp(-1.6))
    return (k * 255).astype(np.uint8)


def sahne_render(s, out, W, H, fps, log=print):
    """Tek sahneyi (sessiz, altyazısız) render eder. Altyazı/ses ayrı katman olduğundan metin değişse de önbellek geçerli kalır.
    Derinlik parallax'ı: yakın pikseller kamerayla daha çok kayar ve büyür; özne (ozne kutusu) nefes alır gibi hafifçe canlıdır."""
    from . import derinlik
    sure = s['sure_render']
    n = int(round(sure * fps))
    img = _yukle(s['gorsel'], W, H)
    if s.get('kirp'):  # görsele gömülü yazı vb. kısmı kesip atmak için
        ih, iw = img.shape[:2]
        x0, y0, x1, y1 = s['kirp']
        img = img[int(y0 * ih):int(y1 * ih), int(x0 * iw):int(x1 * iw)].copy()
    ih, iw = img.shape[:2]
    tohum = int(hashlib.md5(s['id'].encode()).hexdigest()[:6], 16)
    par = float(s.get('parallax', 1.0))
    D = mask = on = None
    if par > 0 and s.get('ozne_maskesi'):
        # İsteğe bağlı (Faz-53A): dışarıda hazırlanmış alfa maskesi + dolgulu arka plan (aynı en-boy oranında dosyalar).
        # Verilmezse aşağıdaki özgün yol birebir çalışır.
        alfa = cv2.imread(s['ozne_maskesi'], cv2.IMREAD_UNCHANGED)
        alfa = cv2.resize(alfa, (iw, ih), interpolation=cv2.INTER_LINEAR).astype(np.float32) / (65535.0 if alfa.dtype == np.uint16 else 255.0)
        arka = cv2.resize(cv2.imread(s['arka_plan_dolgu'], cv2.IMREAD_COLOR), (iw, ih), interpolation=cv2.INTER_AREA)
        on = np.dstack([img[..., :3], (np.clip(alfa, 0, 1) * 255).astype(np.uint8)])
        img = arka
        D = derinlik.harita(arka, None, float(s.get('ufuk', 0.38)))[0]
    elif par > 0:
        D, mask = derinlik.harita(img, s.get('ozne'), float(s.get('ufuk', 0.38)))
        if mask is not None:
            # Katmanlı parallax: özne bükülmeden ayrı katman olur; arkasındaki boşluk onarılır (inpaint)
            k = 540 / max(ih, iw)
            ks = cv2.resize(img, (int(iw * k), int(ih * k)), interpolation=cv2.INTER_AREA)
            mk = cv2.resize(mask, (ks.shape[1], ks.shape[0]))
            delik = cv2.dilate((mk > 0.25).astype(np.uint8) * 255, np.ones((15, 15), np.uint8))
            onarim = cv2.resize(cv2.inpaint(ks, delik, 9, cv2.INPAINT_TELEA), (iw, ih), interpolation=cv2.INTER_CUBIC)
            onarim = cv2.GaussianBlur(onarim, (0, 0), 3)
            mf = cv2.GaussianBlur(cv2.resize(delik.astype(np.float32) / 255, (iw, ih)), (0, 0), 6)[..., None]
            arka = (img.astype(np.float32) * (1 - mf) + onarim.astype(np.float32) * mf).astype(np.uint8)
            on = np.dstack([img, (np.clip((mask - 0.25) * 2.2, 0, 1) * 255).astype(np.uint8)])  # keskin kenar: yarı saydam 'hayalet' olmasın
            img = arka
            D = derinlik.harita(arka, None, float(s.get('ufuk', 0.38)))[0]
    if s.get('zemin_derinlik_aktif', True) is False:  # isteğe bağlı: zemin bükmesi kapalı (perspektifsiz görseller)
        D = None
    io_ = s.get('izleme_oranlari') or {}  # isteğe bağlı: katmanların kamerayı izleme oranları (varsayılanlar özgün değerler)
    a_kon, a_zum = float(io_.get('arka_konum', 0.75)), float(io_.get('arka_zoom', 0.8))
    o_kon, o_zum = float(io_.get('ozne_konum', 1 + 0.2 * par)), float(io_.get('ozne_zoom', 1 + 0.15 * par))
    o_sar = float(io_.get('ozne_sarsinti', 1.3))
    ng = float(s.get('nefes_genlik', 1.0)) if s.get('nefes_aktif', True) else 0.0  # isteğe bağlı: özne nefesi
    fx, ateslar = [], []
    for e in s.get('efektler') or []:
        tip, g = e['tip'], float(e.get('guc', 1.0))
        if tip in efekt.Partikul.AYAR:
            fx.append(efekt.Partikul(tip, W, H, g, tohum))
        elif tip in ('duman', 'sis'):
            fx.append(efekt.Duman(tip, W, H, g, tohum))
        elif tip == 'isik':
            fx.append(efekt.IsikHuzmesi(W, H, tuple(e.get('kaynak', (0.75, -0.05))), g, tohum))
        elif tip == 'ates':
            ateslar.append(e)
        else:
            fx.append(e)  # kare-bazlı fonksiyonlar (parlama, dof)
    atislar = s.get('atislar') or []
    duman_doku = efekt._gurultu_dokusu(512, 512, tohum, (60, 20, 8)) if atislar else None
    vin = efekt.vinyet_maskesi(W, H, s.get('vinyet', 1.0))
    sars = kamera.Sarsinti(guc=14 * float(s.get('sarsinti', 0.15)), tohum=tohum)
    if s.get('titresimsiz'):  # isteğe bağlı (mini-dunya Faz-65): konum ve AÇI titreşimi yok, yalnız pürüzsüz kamera eğrisi
        sars = lambda t, darbe=1.0: (0.0, 0.0, 0.0)  # noqa: E731
    darbeler = list(s.get('darbeler') or []) + [a['zaman'] for a in atislar]
    X, Y = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))
    k0 = kamera.konum(s.get('kamera', 'zoom_in'), 0, s.get('odak'), float(s.get('guc', 1.0)))
    yorunge = float(s.get('yorunge', 0.6))  # parallax'ı görünür kılan hafif yanal kamera kayması
    tmp = out + '.tmp.mp4'
    enc = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{H}', '-r', str(fps),
                            '-i', '-', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '15', '-pix_fmt', 'yuv420p', '-r', str(fps), tmp],
                           stdin=subprocess.PIPE)
    for i in range(n):
        t = i / fps
        u = t / max(sure, 1e-6)
        cx, cy, z, aci = kamera.konum(s.get('kamera', 'zoom_in'), u, s.get('odak'), float(s.get('guc', 1.0)))
        # top atışı geri tepmesi: ani geri çekilme + sarsıntı darbesi
        tepme = sum(a.get('guc', 1.0) * math.exp(-(t - a['zaman']) * 7) for a in atislar if t >= a['zaman'])
        z = max(1.0, z * (1 - 0.03 * min(tepme, 1.5)))
        darbe = 1.0 + sum(5.0 * math.exp(-(t - d) * 6) for d in darbeler if t >= d)
        dx, dy, da = sars(t, darbe)
        if on is not None:
            M, olcek = _matris(img, W, H, k0[0] + (cx - k0[0]) * a_kon, k0[1] + (cy - k0[1]) * a_kon, k0[2] + (z - k0[2]) * a_zum, aci + da, dx, dy)
        else:
            M, olcek = _matris(img, W, H, cx, cy, z, aci + da, dx, dy)
        kare = cv2.warpAffine(img, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        if D is not None:
            # zemin derinliği: küçük ve sınırlı kayma (görüntüyü bükmeden derinlik hissi)
            Dk = cv2.warpAffine(D, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            sinir = W * 0.018
            px_ = float(np.clip(((cx - k0[0]) * 1.2 + yorunge * 0.006 * math.sin(math.pi * u)) * W * par, -sinir, sinir))
            py_ = float(np.clip((cy - k0[1]) * 0.8 * H * par, -sinir, sinir))
            zz = float(np.clip((z - k0[2]) * 0.25 * par, -0.04, 0.04))
            fark = Dk - 0.45
            mx = X - fark * px_ - (X - W / 2) * fark * zz
            my = Y - fark * py_ - (Y - H / 2) * fark * zz
            kare = cv2.remap(kare, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        if on is not None:
            # özne katmanı: kamerayı biraz fazla izler (arka plan ~%75 izler) -> ayrışma; nefes: tabana sabit hafif dikey esneme
            cxo = k0[0] + (cx - k0[0]) * o_kon
            cyo = k0[1] + (cy - k0[1]) * o_kon
            zo = k0[2] + (z - k0[2]) * o_zum
            Mo, _ = _matris(on, W, H, cxo, cyo, zo, aci + da, dx * o_sar, dy * o_sar)
            sy = 1 + 0.006 * ng * math.sin(2 * math.pi * t / 3.2)
            yb = H * 0.98
            A = np.array([[1, 0, 2.0 * ng * math.sin(2 * math.pi * t / 4.1)], [0, sy, (1 - sy) * yb]], np.float64)
            Mo = A @ np.vstack([Mo, [0, 0, 1]])
            ust = cv2.warpAffine(on, Mo, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
            al = ust[..., 3:4].astype(np.float32) / 255
            kare = (kare.astype(np.float32) * (1 - al) + ust[..., :3].astype(np.float32) * al).astype(np.uint8)
        for f in fx:
            if isinstance(f, dict):
                if f['tip'] == 'parlama':
                    kare = efekt.parlama(kare, float(f.get('guc', 1.0)))
                elif f['tip'] == 'dof':
                    kare = efekt.alan_derinligi(kare, tuple(f.get('odak', (0.5, 0.45))), guc=float(f.get('guc', 1.0)))
            else:
                kare = f.uygula(kare, t)
        # ateş titremesi: düzensiz sıcak ışık
        for e in ateslar:
            xy = _goruntu_konumu(M, e['konum'], iw, ih)
            fl = 0.72 + 0.14 * math.sin(t * 23) + 0.09 * math.sin(t * 37 + 1.3) + 0.06 * math.sin(t * 61 + 0.4)
            kare = _isik(kare, xy, W * float(e.get('yaricap', 0.12)) * (0.9 + 0.2 * fl), (40, 130, 255), 0.9 * fl * float(e.get('guc', 1.0)))
        # top atışı: namlu ışığı + sahne aydınlanması + büyüyen duman bulutu
        for a in atislar:
            dt = t - a['zaman']
            if dt < 0:
                continue
            g = float(a.get('guc', 1.0))
            xy = _goruntu_konumu(M, a['konum'], iw, ih)
            fl = math.exp(-dt * 13) * g
            if fl > 0.01:
                kare = _isik(kare, xy, W * 0.2, (120, 200, 255), 1.1 * fl)
                kare = np.clip(kare.astype(np.float32) * (1 + 0.12 * fl), 0, 255).astype(np.uint8)
            if 0.03 < dt < 3.5:
                r = int(W * (0.05 + 0.22 * (1 - math.exp(-dt * 1.4))) * g)
                al = 0.5 * math.exp(-dt * 0.7) * min(1, dt * 12)
                cx_, cy_ = int(xy[0] + W * 0.05 * dt), int(xy[1] - H * 0.02 * dt)
                x0, y0, x1, y1 = max(0, cx_ - r), max(0, cy_ - r), min(W, cx_ + r), min(H, cy_ + r)
                if x1 > x0 and y1 > y0:
                    yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
                    rad = np.exp(-((xx - cx_) ** 2 + (yy - cy_) ** 2) / (2 * (r * 0.5) ** 2))
                    tex = cv2.resize(duman_doku, (x1 - x0, y1 - y0))
                    m = np.clip(rad * (0.5 + tex) - 0.25, 0, 1) * al
                    bolge = kare[y0:y1, x0:x1].astype(np.float32)
                    kare[y0:y1, x0:x1] = (bolge * (1 - m[..., None]) + np.array([205, 210, 215], np.float32) * m[..., None]).astype(np.uint8)
        if s.get('giris_flas'):  # flaş geçişinin yumuşak devamı (beyaza patlamadan)
            fl = math.exp(-t * 9)
            if fl > 0.02:
                kare = np.clip(kare.astype(np.float32) * (1 + 0.35 * fl) + 25 * fl, 0, 255).astype(np.uint8)
        if s.get('ton'):
            kare = efekt.renk_tonu(kare, s['ton'], float(s.get('ton_guc', 1.0)))
        kare = _omuz(kare)
        kare = (kare.astype(np.float32) * vin).astype(np.uint8)
        if s.get('gren'):
            kare = efekt.gren(kare, t, float(s['gren']), tohum)
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


def ass_yaz(satirlar, path, W, H, kanca=None, kanca_sure=2.6, son_yazi=None, toplam=None):
    # Shorts güvenli alanı: alt %25 (başlık/kanal) ve sağ %15 (beğen/yorum butonları) arayüzle kaplı; üst %8 arama/kamera
    boy = int(W * 0.078)
    kboy = int(W * 0.098)
    # Ana altyazı: yarı saydam koyu kutu (BorderStyle 3) -> parlak/karışık zeminde de okunur, temiz tipografi
    stil = (f'Style: Ana,Baloo 2,{boy},&H00FFFFFF,&H00FFFFFF,&H5A000000,&H5A000000,-1,0,0,0,100,100,0,0,3,{max(6, boy // 6)},0,2,'
            f'{int(W * 0.09)},{int(W * 0.17)},{int(H * 0.33)},1\n'
            f'Style: Kanca,Baloo 2,{kboy},&H0030D8FF,&H0030D8FF,&H00101010,&H78000000,-1,0,0,0,100,100,0,0,1,{max(4, kboy // 12)},3,8,'
            f'{int(W * 0.07)},{int(W * 0.17)},{int(H * 0.13)},1')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(f'[Script Info]\nScriptType: v4.00+\nPlayResX: {W}\nPlayResY: {H}\nWrapStyle: 0\n\n[V4+ Styles]\n'
                'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, '
                'StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n'
                f'{stil}\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n')
        for a, b, t in satirlar:
            f.write(f'Dialogue: 0,{_ass_zaman(a)},{_ass_zaman(b)},Ana,,0,0,0,,{{\\fad(80,80)}}{t}\n')
        if son_yazi and toplam:
            f.write(f'Dialogue: 1,{_ass_zaman(toplam - 2.3)},{_ass_zaman(toplam)},Kanca,,0,0,0,,{{\\fad(200,0)}}{son_yazi}\n')
        if kanca:
            f.write(f'Dialogue: 1,{_ass_zaman(0.05)},{_ass_zaman(kanca_sure)},Kanca,,0,0,0,,{{\\fad(120,250)}}{kanca}\n')


# ---------------------------------------------------------------- kalite kontrol

def ses_akisi_kontrol(anlatim, efektler, sesler, sahneler, basl, planlar, toplam, muzik_davul=False):
    """Ses akışı: cümle kesilmesi, uzun sessizlik, ani seviye sıçraması, müzik/konuşma dengesi, son cümlenin tamamlanması."""
    r = {'kritik': [], 'uyari': [], 'olcum': {}}
    db = lambda v: 20 * math.log10(max(v, 1e-6))
    # 1) cümle sonu kesilmesi: TTS dosyasının son 40 ms'i hâlâ yüksekse cümle yarıda kesilmiştir
    for i, x in sesler.items():
        son = x[-int(0.04 * SR):]
        if len(son) and np.sqrt(np.mean(son ** 2)) > 0.08 * (np.abs(x).max() + 1e-6):
            r['kritik'].append(f'{sahneler[i]["id"]}: cümle sonu kesik görünüyor')
    # 2) son cümle video bitmeden tamamlanıyor mu
    son_bitis = max([basl[i] + planlar[i][0] + planlar[i][1] for i in sesler] or [0])
    r['olcum']['son_cumle_bitis'] = round(son_bitis, 2)
    r['olcum']['video_sonu'] = round(toplam, 2)
    if son_bitis > toplam - 0.5:
        r['kritik'].append(f'son cümle video sonuna çok yakın ({son_bitis:.1f}/{toplam:.1f} sn)')
    # 3) uzun sessizlik (konuşma da efekt de yok)
    pen = int(0.1 * SR)
    mix = (anlatim + efektler)[:int(toplam * SR)]
    rms = np.array([np.sqrt(np.mean(mix[k:k + pen] ** 2)) for k in range(0, len(mix) - pen, pen)])
    sessiz = 0
    en_uzun = 0
    for v in rms:
        sessiz = sessiz + 1 if v < 10 ** (-48 / 20) else 0
        en_uzun = max(en_uzun, sessiz)
    r['olcum']['en_uzun_sessizlik_sn'] = round(en_uzun * 0.1, 1)
    if en_uzun * 0.1 > 2.5:
        r['kritik'].append(f'{en_uzun * 0.1:.1f} sn sessizlik')
    elif en_uzun * 0.1 > 1.2:
        r['uyari'].append(f'{en_uzun * 0.1:.1f} sn sessizlik')
    # 4) ani seviye sıçraması (100 ms pencereler arası > 18 dB artış, top atışı gibi planlı efektler hariç)
    planli = [basl[i] + (float(x.get('zaman', 0)) if isinstance(x, dict) else 0.0)
              for i, s in enumerate(sahneler) for x in (s.get('sesler') or [])]  # planlı efekt girişleri (top, davul, rüzgâr)
    a_rms = np.array([np.sqrt(np.mean(anlatim[k:k + pen] ** 2)) for k in range(0, len(mix) - pen, pen)])
    e_rms = np.array([np.sqrt(np.mean(efektler[k:k + pen] ** 2)) for k in range(0, len(mix) - pen, pen)])
    sicrama = []
    for k in range(1, len(rms)):
        if a_rms[k] > a_rms[k - 1] * 4 and a_rms[k] > 0.01:  # cümle içi duraktan sonra konuşmanın doğal yeniden başlaması
            continue
        if muzik_davul and db(e_rms[k]) - db(e_rms[k - 1] + 1e-6) > 12 and db(e_rms[k]) < db(a_rms.max()) - 3:  # ritmik davul vuruşu
            continue
        konusma_basi = any(abs(k * 0.1 - (basl[i] + planlar[i][0])) < 0.4 for i in sesler)
        if rms[k - 1] > 1e-4 and db(rms[k]) - db(rms[k - 1]) > 18 and not konusma_basi and not any(abs(k * 0.1 - p) < 0.4 for p in planli):
            sicrama.append(round(k * 0.1, 1))
    if sicrama:
        r['uyari'].append(f'ani seviye artışı: {sicrama[:4]} sn')
    # 5) konuşma sırasında müzik/efekt dengesi
    konusma = np.abs(anlatim) > 0.02
    if konusma.any():
        a_db = db(np.sqrt(np.mean(anlatim[konusma] ** 2)))
        e_db = db(np.sqrt(np.mean(efektler[:len(konusma)][konusma] ** 2)))
        r['olcum']['konusma_db'] = round(a_db, 1)
        r['olcum']['konusma_altinda_efekt_db'] = round(e_db, 1)
        if e_db > a_db - 8:
            r['kritik'].append(f'müzik/efekt konuşmayı bastırıyor (fark {a_db - e_db:.1f} dB, en az 8 dB olmalı)')
    return r


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
        # 'kesme': xfade 1 karelik süreyle çalışmıyor (video orada bitiyor, test edildi) -> 3 karelik, gözle kesme gibi görünen geçiş
        T = 3.0 / fps if g['tip'] == 'kesme' else max(3.0 / fps, float(g.get('sure', 0.5)))
        gecisler.append((g['tip'], T) if i < len(sahneler) - 1 else ('yok', 0.0))
    for i in range(1, len(sahneler)):
        if gecisler[i - 1][0] == 'flas':
            sahneler[i]['giris_flas'] = True
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
                        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '16', '-pix_fmt', 'yuv420p', sessiz], check=True)
        # not: burada çıkışa '-r' verilirse xfade zaman damgaları bozulup video kısalıyor (test edildi)

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
    # yumuşak kısma: konuşmadan ~0,3 sn önce iner, bittikten sonra ~0,8 sn'de yavaşça açılır (ani yükselme olmaz)
    aktif = (np.abs(anlatim) > 0.02).astype(np.float32)
    aktif = np.convolve(aktif, np.ones(int(0.25 * SR)), 'same') > 0
    zarf = np.convolve(aktif.astype(np.float32), np.hanning(int(0.8 * SR)) / (np.hanning(int(0.8 * SR)).sum() / 1.0), 'same')
    efektler *= (1 - 0.6 * np.clip(zarf, 0, 1))
    mix = anlatim + efektler
    ses_sorun = ses_akisi_kontrol(anlatim, efektler, sesler, sahneler, basl, planlar, toplam, 'davul' in (senaryo.get('muzik') or []))
    tepe = np.abs(mix).max()
    if tepe > 0.95:
        mix *= 0.95 / tepe
    wav = os.path.join(outdir, 'karisim.wav')
    sf.write(wav, mix[:int(toplam * SR)], SR)

    # 6) altyazı katmanı + birleştir
    ass = os.path.join(outdir, 'altyazi.ass')
    ass_yaz(altyazi, ass, W, H, kanca=senaryo.get('kanca'), son_yazi=senaryo.get('son_yazi'), toplam=toplam)
    final = os.path.join(outdir, 'video.mp4')
    fontdir = os.path.dirname(paths.FONT)
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', sessiz, '-i', wav,
                    '-vf', f"ass={ass}:fontsdir={fontdir}", '-c:v', 'libx264', '-preset', 'slow', '-crf', str(senaryo.get('crf', 20)),
                    '-maxrate', '12M', '-bufsize', '24M', '-profile:v', 'high', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
                    '-c:a', 'aac', '-b:a', '160k', '-ar', '48000', '-ac', '2', '-shortest', final], check=True)
    with open(os.path.join(outdir, 'altyazi.json'), 'w', encoding='utf-8') as f:
        json.dump([{'bas': round(a, 2), 'son': round(b, 2), 'metin': t} for a, b, t in altyazi], f, ensure_ascii=False, indent=1)

    # 7) kalite kontrol
    rapor = kalite_kontrol(final, W, H, fps, toplam, sahneler)
    rapor['render_sn'] = round(time.time() - t0, 1)
    rapor['seslendirme'] = motor
    rapor['dinleme'] = dinleme
    rapor['ses_akisi'] = ses_sorun
    rapor['kritik'] += ses_sorun['kritik']
    rapor['uyari'] += ses_sorun['uyari']
    rapor['gecti'] = not rapor['kritik']
    rapor['boyut_mb'] = round(os.path.getsize(final) / 1e6, 1)
    with open(os.path.join(outdir, 'kalite.json'), 'w', encoding='utf-8') as f:
        json.dump(rapor, f, ensure_ascii=False, indent=1)
    log(f"  Kalite: {'GEÇTİ' if rapor['gecti'] else 'KALDI'} | {rapor}")
    return final, rapor
