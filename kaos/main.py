"""LOJİSTİK KAOS botu.
Kullanım:
  python -m kaos.main --slot auto            # saate göre sabah/oglen/aksam/uzun bölümü üretir ve yükler
  python -m kaos.main --slot sabah --no-upload
  python -m kaos.main --json episodes/x.json --no-upload   # hazır senaryodan video üretir
"""
import argparse
import datetime as dt
import json
import os
import re
import shutil
import sys
import traceback

import yaml

from . import paths, writer, youtube
from .audio import tts, mix
from .engine import render

TZ = dt.timezone(dt.timedelta(hours=3))  # Türkiye


def log(*a):
    print(*a, flush=True)


def load_cfg():
    with open(paths.CONFIG, encoding='utf-8') as f:
        return yaml.safe_load(f)


def load_state():
    p = os.path.join(paths.STATE, 'hafiza.json')
    if os.path.exists(p):
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    return {'sezon': 1, 'sezon_baslangic': None, 'bolum_no': 0, 'kemal_gun': 45, 'bolumler': [],
            'acik_meseleler': [], 'en_cok_izlenen': [], 'yapilan': {}}


def save_state(st):
    os.makedirs(paths.STATE, exist_ok=True)
    with open(os.path.join(paths.STATE, 'hafiza.json'), 'w', encoding='utf-8') as f:
        json.dump(st, f, ensure_ascii=False, indent=1)


def load_plan(n):
    p = os.path.join(paths.EVREN, f'sezon{n:02d}.yaml')
    if os.path.exists(p):
        with open(p, encoding='utf-8') as f:
            return yaml.safe_load(f)
    return None


def slug(s):
    tr = str.maketrans('çğıöşüÇĞİÖŞÜ', 'cgiosuCGIOSU')
    return re.sub(r'[^a-z0-9]+', '-', s.translate(tr).lower()).strip('-')[:40]


def auto_slot(now):
    h = now.hour + now.minute / 60
    if now.weekday() in (2, 6) and 17 <= h < 19:
        return 'uzun'
    if h < 11:
        return 'sabah'
    if h < 16:
        return 'oglen'
    return 'aksam'


def season_day(st, cfg, today):
    if not st.get('sezon_baslangic'):
        st['sezon_baslangic'] = today.isoformat()
    start = dt.date.fromisoformat(st['sezon_baslangic'])
    day = (today - start).days + 1
    plan = load_plan(st['sezon'])
    if plan is None or day > len(plan.get('gunler', [])):
        if plan is not None:
            st['sezon'] += 1
        log(f"Yeni sezon planı hazırlanıyor: Sezon {st['sezon']}")
        plan = load_plan(st['sezon'])
        if plan is None:
            plan = writer.new_season_plan(st['sezon'], st, cfg, log=log)
            with open(os.path.join(paths.EVREN, f"sezon{st['sezon']:02d}.yaml"), 'w', encoding='utf-8') as f:
                yaml.safe_dump(plan, f, allow_unicode=True, sort_keys=False)
        st['sezon_baslangic'] = today.isoformat()
        st['kemal_gun'] = plan.get('kemal_gun_baslangic', st.get('kemal_gun', 1))
        day = 1
    return plan, day


def brief_for(slot, plan, day, today):
    if slot == 'uzun':
        week = 1 if day <= 7 else 2
        which = 'pazar' if today.weekday() == 6 else 'carsamba'
        return 'uzun', plan['uzun'].get(f'hafta{week}_{which}', 'Haftanın en kaotik olayının uzun hikâyesi.')
    row = plan['gunler'][day - 1]
    if slot == 'oglen':
        return 'bagimsiz', row['oglen']
    return 'ana', row[slot]


def description(ep, kind, no, season):
    yt = ep['youtube']
    base = yt.get('description', '').strip()
    tail = (f"\n\nLOJİSTİK KAOS · Sezon {season} · Bölüm {no}\n"
            "Limanda konuşan tırlar, konteynerler, gemiler ve evraklar... Lojistik dünyasının sitcom'u.\n"
            "Her gün yeni bölüm! Abone olmayı unutma.\n\n#lojistik #komedi #animasyon #liman #tır #konteyner")
    if kind != 'uzun':
        tail += ' #shorts'
    return base + tail


def produce(ep, kind, meta, outdir, cfg, log=log):
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, 'senaryo.json'), 'w', encoding='utf-8') as f:
        json.dump(ep, f, ensure_ascii=False, indent=1)
    model_dir = os.environ.get('PIPER_MODELS', os.path.join(paths.ROOT, 'models'))
    wavs, engine = tts.synthesize(ep, cfg, os.path.join(outdir, 'ses'), model_dir=model_dir, log=log)
    long_form = kind == 'uzun'
    W, H = (1920, 1080) if long_form else (1080, 1920)
    tl = render.build_timeline(ep, wavs, long_form=long_form)
    log(f"Video süresi: {tl['total']:.1f} sn — çiziliyor...")
    vid = os.path.join(outdir, 'goruntu.mp4')
    render.render_video(ep, tl, vid, W, H, meta)
    wav = os.path.join(outdir, 'miks.wav')
    mix.build_mix(ep, tl, wav)
    final = os.path.join(outdir, 'video.mp4')
    import subprocess
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', vid, '-i', wav, '-map', '0:v', '-map', '1:a', '-c:v', 'copy',
                    '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', '-shortest', final], check=True)
    os.remove(vid)
    thumb = render.thumbnail(ep, tl, os.path.join(outdir, 'kapak.jpg'), W, H, meta)
    return final, thumb, engine, tl['total']


def update_stats(st, log=log):
    ids = [b['video_id'] for b in st['bolumler'][-40:] if b.get('video_id')]
    if not ids or not youtube.configured():
        return
    try:
        views = youtube.stats(ids)
    except Exception as e:
        log(f'  İzlenme verisi alınamadı: {e}')
        return
    for b in st['bolumler']:
        if b.get('video_id') in views:
            b['izlenme'] = views[b['video_id']]
    ranked = sorted([b for b in st['bolumler'] if b.get('izlenme') is not None], key=lambda b: -b['izlenme'])[:5]
    st['en_cok_izlenen'] = [f"{b['baslik']} ({b['izlenme']} izlenme, {b['tur']}): {b.get('ozet', '')}" for b in ranked]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--slot', default='auto', choices=['auto', 'sabah', 'oglen', 'aksam', 'uzun'])
    ap.add_argument('--json', help='Hazır senaryo dosyasından üret')
    ap.add_argument('--no-upload', action='store_true')
    ap.add_argument('--force', action='store_true', help='Bugün bu slot yapılmış olsa da üret')
    args = ap.parse_args()

    cfg = load_cfg()
    st = load_state()
    now = dt.datetime.now(TZ)
    today = now.date()
    slot = auto_slot(now) if args.slot == 'auto' else args.slot
    done = st.setdefault('yapilan', {}).setdefault(today.isoformat(), [])
    if slot in done and not args.force and not args.json:
        log(f'Bugünün {slot} bölümü zaten yapılmış, atlanıyor.')
        return 0
    # eski günlerin kayıtlarını temizle
    st['yapilan'] = {k: v for k, v in st['yapilan'].items() if k >= (today - dt.timedelta(days=7)).isoformat()}

    update_stats(st)
    if args.json:
        with open(args.json, encoding='utf-8') as f:
            ep = json.load(f)
        kind = ep.get('tur', 'ana')
        writer.validate(ep, kind)
        plan = load_plan(st['sezon']) or {}
    else:
        plan, day = season_day(st, cfg, today)
        kind, brief = brief_for(slot, plan, day, today)
        log(f"Sezon {st['sezon']} · Gün {day} · {slot} ({kind}): {brief}")
        ep = writer.write_episode(kind, brief, st, plan, cfg, log=log)
        ep['tur'] = kind

    no = st['bolum_no'] + 1
    meta = {'subtitle': f"Bölüm {no} · {ep['baslik']}" if kind != 'bagimsiz' else f"Skeç · {ep['baslik']}",
            'thumb': ep.get('kapak_yazisi', ep['baslik'])}
    outdir = os.path.join(paths.OUTPUT, f"{today.isoformat()}_{slot}_{no:04d}_{slug(ep['baslik'])}")
    final, thumb, engine, dur = produce(ep, kind, meta, outdir, cfg)
    log(f'Video hazır: {final} ({dur:.0f} sn, ses: {engine})')

    vid_id = None
    upload = cfg['yayin'].get('yukle', True) and not args.no_upload
    if upload:
        if not youtube.configured():
            log('YouTube anahtarları tanımlı değil; video sadece üretildi (Actions sayfasından indirilebilir).')
        else:
            title = ep['youtube']['title']
            if kind != 'uzun' and '#shorts' not in title.lower():
                title = (title[:88] + ' #shorts')
            tags = list(dict.fromkeys(ep['youtube'].get('tags', []) + cfg['yayin'].get('shorts_etiketleri', [])))
            vid_id = youtube.upload(final, title, description(ep, kind, no, st['sezon']), tags,
                                    cfg['yayin'].get('gizlilik', 'public'), cfg['yayin'].get('kategori', 23),
                                    thumb if kind == 'uzun' else None, log=log)

    # hafıza
    st['bolum_no'] = no
    h = ep.get('hafiza', {})
    if kind == 'ana' and isinstance(h.get('kemal_gun'), int) and h['kemal_gun'] > 0:
        st['kemal_gun'] = h['kemal_gun']
    if kind != 'bagimsiz' and isinstance(h.get('acik_meseleler'), list):
        st['acik_meseleler'] = [str(x) for x in h['acik_meseleler']][:8]
    st['bolumler'].append({'no': no, 'tarih': today.isoformat(), 'slot': slot, 'tur': kind, 'baslik': ep['baslik'],
                           'ozet': h.get('ozet', ''), 'video_id': vid_id, 'ses': engine})
    st['bolumler'] = st['bolumler'][-200:]
    done.append(slot)
    st['yapilan'][today.isoformat()] = done
    save_state(st)
    os.makedirs(paths.EPISODES, exist_ok=True)
    shutil.copy(os.path.join(outdir, 'senaryo.json'), os.path.join(paths.EPISODES, f"{no:04d}_{slug(ep['baslik'])}.json"))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
