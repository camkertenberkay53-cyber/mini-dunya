"""MİNİ DÜNYA botu.
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
    return {'sezon': 1, 'sezon_baslangic': None, 'bolum_no': 0, 'harita': [], 'bolumler': [],
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
    if now.weekday() == 6 and 17 <= h < 19:
        return 'uzun'
    if h < 11:
        return 'sabah'
    if h < 16:
        return 'oglen'
    if h < 20.5:
        return 'aksam'
    return 'gece'


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
        day = 1
    return plan, day


def brief_for(slot, plan, day, today):
    if slot == 'uzun':
        week = 1 if day <= 7 else 2
        return 'uzun', plan['uzun'].get(f'hafta{week}_pazar', plan['uzun'].get(f'hafta{week}', 'Haftanın en büyük keşif macerası.'))
    row = plan['gunler'][day - 1]
    if slot in ('oglen', 'gece'):
        return 'bagimsiz', row.get(slot) or row['oglen']
    return 'ana', row[slot]


def description(ep, kind, no, season):
    yt = ep['youtube']
    base = yt.get('description', '').strip()
    tail = (f"\n\nMİNİ DÜNYA · Sezon {season} · Bölüm {no}\n"
            "Süpürgeliğin arkasında yaşayan minik haritacılar, Büyük Ev'i bölge bölge keşfediyor.\n"
            "Her gün yeni bölüm! Abone olmayı unutma.\n\n#minidünya #animasyon #macera #keşif #çizgifilm")
    if kind != 'uzun':
        tail += ' #shorts'
    return base + tail


def description_en(ep, kind, no, season):
    base = (ep.get('youtube') or {}).get('description', '').strip()
    tail = (f"\n\nMINI WORLD · Season {season} · Episode {no}\n"
            "Tiny mapmakers living behind the baseboard explore the Big House, one room at a time.\n"
            "New episodes every day! Subscribe for the next adventure.\n\n#miniworld #animation #cartoon #adventure #animatedseries")
    if kind != 'uzun':
        tail += ' #shorts'
    return base + tail


def produce_en(ep, kind, no, season, today, slot, cfg, st, log=log):
    """Aynı bölümü İngilizce kanal için uyarlar, seslendirir, çizer ve yükler."""
    ec = cfg.get('ingilizce') or {}
    if not ec.get('acik') or not youtube.configured(ec.get('token_env', 'YT_REFRESH_TOKEN_EN')):
        return
    log('— İngilizce (Mini World) sürümü —')
    en = writer.localize_en(ep, cfg, log=log)
    cfg_en = dict(cfg)
    cfg_en['lang'] = 'en'
    cfg_en['voices'] = ec['voices']
    cfg_en['tts'] = dict(cfg['tts'], order=ec.get('tts_order', ['gemini', 'edge']))
    meta = {'lang': 'en', 'subtitle': f"Episode {no} · {en['baslik']}", 'thumb': en.get('kapak_yazisi', en['baslik'])}
    outdir = os.path.join(paths.OUTPUT, f"{today.isoformat()}_{slot}_{no:04d}_en")
    final, thumb, engine, dur = produce(en, kind, meta, outdir, cfg_en)
    log(f'İngilizce video hazır: {final} ({dur:.0f} sn, ses: {engine})')
    title = (en.get('youtube') or {}).get('title') or en['baslik']
    if kind != 'uzun' and '#shorts' not in title.lower():
        title = title[:88] + ' #shorts'
    tags = list(dict.fromkeys(((en.get('youtube') or {}).get('tags') or []) + ec.get('etiketler', [])))
    vid = youtube.upload(final, title, description_en(en, kind, no, season), tags,
                         cfg['yayin'].get('gizlilik', 'public'), cfg['yayin'].get('kategori', 1),
                         thumb if kind == 'uzun' else None, log=log, token_env=ec.get('token_env', 'YT_REFRESH_TOKEN_EN'), lang='en')
    st.setdefault('en_bolumler', []).append({'no': no, 'tarih': today.isoformat(), 'slot': slot, 'baslik': en['baslik'], 'video_id': vid})
    st['en_bolumler'] = st['en_bolumler'][-200:]


def en_backfill():
    cfg = load_cfg()
    st = load_state()
    today = dt.datetime.now(TZ).date()
    have = {b['no'] for b in st.get('en_bolumler', [])}
    todo = [b for b in st['bolumler'] if b['tarih'] == today.isoformat() and b['no'] not in have]
    if not todo:
        log('İngilizce sürümü eksik bölüm yok.')
        return 0
    for b in todo:
        fn = os.path.join(paths.EPISODES, f"{b['no']:04d}_{slug(b['baslik'])}.json")
        if not os.path.exists(fn):
            log(f'Senaryo bulunamadı: {fn}')
            continue
        with open(fn, encoding='utf-8') as f:
            ep = json.load(f)
        produce_en(ep, b['tur'], b['no'], st['sezon'], today, b['slot'], cfg, st)
        save_state(st)
    return 0


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
    ap.add_argument('--slot', default='auto', choices=['auto', 'sabah', 'oglen', 'aksam', 'gece', 'uzun'])
    ap.add_argument('--json', help='Hazır senaryo dosyasından üret')
    ap.add_argument('--no-upload', action='store_true')
    ap.add_argument('--force', action='store_true', help='Bugün bu slot yapılmış olsa da üret')
    ap.add_argument('--en-telafi', action='store_true', help='Bugünün İngilizce sürümü olmayan bölümlerini İngilizce üret')
    args = ap.parse_args()
    if args.en_telafi:
        return en_backfill()

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
    yb = str(h.get('yeni_bolge') or '').strip()
    if yb and yb not in st.setdefault('harita', []):
        st['harita'].append(yb)
    if kind != 'bagimsiz' and isinstance(h.get('acik_meseleler'), list):
        st['acik_meseleler'] = [str(x) for x in h['acik_meseleler']][:8]
    st['bolumler'].append({'no': no, 'tarih': today.isoformat(), 'slot': slot, 'tur': kind, 'baslik': ep['baslik'],
                           'ozet': h.get('ozet', ''), 'video_id': vid_id, 'ses': engine,
                           'kategori': ep.get('kategori', ''), 'konu': ep.get('konu', ''),
                           'mekan': ep['scenes'][0].get('location', ''), 'ana_karakter': ep.get('ana_karakter', ''),
                           'final': ep['scenes'][-1]['lines'][-1].get('text', '') if ep['scenes'][-1].get('lines') else ''})
    st['bolumler'] = st['bolumler'][-200:]
    done.append(slot)
    st['yapilan'][today.isoformat()] = done
    save_state(st)
    os.makedirs(paths.EPISODES, exist_ok=True)
    shutil.copy(os.path.join(outdir, 'senaryo.json'), os.path.join(paths.EPISODES, f"{no:04d}_{slug(ep['baslik'])}.json"))
    # İngilizce kardeş kanal: Türkçe bölüm kaydedildikten sonra; hata olursa Türkçe yayını etkilemez
    if upload:
        try:
            produce_en(ep, kind, no, st['sezon'], today, slot, cfg, st)
            save_state(st)
        except Exception as e:
            log(f'İngilizce sürüm üretilemedi: {e}')
            traceback.print_exc()
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
