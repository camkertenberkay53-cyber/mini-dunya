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


# İngilizce kanal: ABD (Doğu) izleyicisinin en aktif saatlerinde yayına girer (rakip verisi: 15-18 ET en viral dilim).
EN_YAYIN_ET = {'sabah': 7.0, 'oglen': 10.0, 'aksam': 16.0, 'gece': 18.0, 'uzun': 12.5}


def en_publish_at(slot, now=None):
    from zoneinfo import ZoneInfo
    et = ZoneInfo('America/New_York')
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(et)
    h = EN_YAYIN_ET.get(slot, 16.0)
    for add in range(0, 8):
        d = (now + dt.timedelta(days=add)).date()
        if slot == 'uzun' and d.weekday() != 6:
            continue
        t = dt.datetime(d.year, d.month, d.day, int(h), int(round(h % 1 * 60)), tzinfo=et)
        if t > now + dt.timedelta(minutes=20):
            return t.astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    return None


def en_memory(st):
    """İngilizce kanalın kendi bölüm hafızası (tekrar kontrolü ve çeşitlilik için)."""
    m = dict(st)
    m['karakter_hafiza'] = st.get('en_karakter_hafiza', {})
    m['cozulenler'] = st.get('en_cozulenler', [])
    m['bolumler'] = [dict(b, no=b.get('no', 0), tur=b.get('tur', ''), ozet=b.get('ozet', '')) for b in st.get('en_bolumler', [])]
    return m


def produce_en(ep, kind, no, season, today, slot, cfg, st, log=log, brief=None, plan=None):
    """İngilizce kanal için AYNI EVRENDE BAĞIMSIZ bir bölüm yazar (Türkçe bölümün kopyası değil), seslendirir, çizer, zamanlar.
    İki kanalda birebir aynı görüntünün yüklenmesi YouTube'da kopya/yeniden kullanılmış içerik riskidir."""
    ec = cfg.get('ingilizce') or {}
    if not ec.get('acik') or not youtube.configured(ec.get('token_env', 'YT_REFRESH_TOKEN_EN')):
        return
    log('— İngilizce (Mini World) bağımsız bölümü —')
    src = ep
    if brief is not None and plan is not None:
        fark = (f"\n\nÖNEMLİ: Bu bölüm İNGİLİZCE kardeş kanal için yazılıyor. Ana kanalda bugün '{ep['baslik']}' yayınlandı "
                f"(konu: {ep.get('konu', '')}; mekân: {ep['scenes'][0].get('location')}; açılış: {ep.get('acilis_efekti')}). "
                f"Bu bölüm ondan TAMAMEN FARKLI olmalı: başka bir olay, başka bir mekân, başka bir açılış efekti, başka bir odak karakter. "
                f"Aynı sezon bölgesinde geçebilir ama hikâye ve görüntüler tekrar etmesin.")
        idea_en = None
        if kind != 'uzun':
            try:
                from . import fikir
                tr_bugun = [fikir._parmak_izi(f) for f in (st.get('fikir_havuzu', {}).get('tr', {}).get(today.isoformat()) or {}).values()]
                idea_en = fikir.gunun_fikirleri(st, plan, st.get('_gun') or 0, today, cfg, 'en', harici=tr_bugun, log=log,
                                                 sadece_onbellek=True).get(slot)
            except Exception as e:
                log(f'  İngilizce fikir motoru atlandı: {e}')
        try:
            src = writer.write_episode(kind, brief + fark + (fikir.brief_ek(idea_en) if idea_en else ''), en_memory(st), plan, cfg, log=log)
            if idea_en:
                fikir.kaydet(st, idea_en, 'en')
        except Exception as e:
            log(f'  Bağımsız İngilizce bölüm yazılamadı, bugünkü bölüm uyarlanacak: {e}')
            src = ep
    en = writer.localize_en(src, cfg, log=log)
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
                         thumb if kind == 'uzun' else None, log=log, token_env=ec.get('token_env', 'YT_REFRESH_TOKEN_EN'), lang='en',
                         publish_at=en_publish_at('uzun' if kind == 'uzun' else slot))
    log(f"  İngilizce yayın zamanı (UTC): {en_publish_at('uzun' if kind == 'uzun' else slot)}")
    kanal_yonet(st, en, vid, 'en', f'Season {season}', ec.get('token_env', 'YT_REFRESH_TOKEN_EN'), log=log)
    st.setdefault('en_bolumler', []).append({'no': no, 'tarih': today.isoformat(), 'slot': slot, 'tur': kind, 'baslik': en['baslik'],
                                             'tr_baslik': src.get('baslik'), 'konu': src.get('konu', ''), 'kategori': src.get('kategori', ''),
                                             'mekan': src['scenes'][0].get('location', ''), 'ana_karakter': src.get('ana_karakter', ''),
                                             'ozet': (src.get('hafiza') or {}).get('ozet', ''), 'video_id': vid})
    st['en_bolumler'] = st['en_bolumler'][-200:]
    if src is not ep:
        sezon_hafiza_guncelle(st, src.get('hafiza') or {}, 'en_karakter_hafiza', 'en_cozulenler')


def fikir_uret():
    """Günlük fikir motoru: yayınlardan önce (07:00) çalışır; üretim anında sadece hazır fikir kullanılır."""
    from . import fikir
    cfg = load_cfg()
    st = load_state()
    today = dt.datetime.now(TZ).date()
    plan, day = season_day(st, cfg, today)
    st['_gun'] = day
    done = st.setdefault('yapilan', {}).setdefault(today.isoformat(), [])
    try:
        tr = fikir.gunun_fikirleri(st, plan, day, today, cfg, 'tr', log=log)
        save_state(st)
        if (cfg.get('ingilizce') or {}).get('acik'):
            fikir.gunun_fikirleri(st, plan, day, today, cfg, 'en', harici=[fikir._parmak_izi(f) for f in tr.values()], log=log)
    except Exception as e:
        log(f'Fikir motoru başarısız: {e}')
    if 'fikir' not in done:
        done.append('fikir')
    save_state(st)
    return 0


def kanal_kurulum():
    """Tek seferlik: yayınlanmış tüm bölümleri sezon listelerine ekler ve kanal yorumu bırakır."""
    st = load_state()
    plan = load_plan(st['sezon']) or {}
    for key, lang, env in (('bolumler', 'tr', 'YT_REFRESH_TOKEN'), ('en_bolumler', 'en', 'YT_REFRESH_TOKEN_EN')):
        if not youtube.configured(env):
            continue
        for b in st.get(key, []):
            if not b.get('video_id') or b.get('kuruldu'):
                continue
            ep = {'end_card': '', 'hafiza': {}}
            fn = os.path.join(paths.EPISODES, f"{b['no']:04d}_{slug(b.get('tr_baslik') or b['baslik'])}.json")
            if lang == 'tr' and os.path.exists(fn):
                with open(fn, encoding='utf-8') as f:
                    ep = json.load(f)
            if not ep.get('end_card'):
                ep['end_card'] = 'Sen olsan ne yapardın?' if lang == 'tr' else 'What would you do?'
            name = (plan.get('ad') or f"Sezon {st['sezon']}") if lang == 'tr' else f"Season {st['sezon']}"
            if kanal_yonet(st, ep, b['video_id'], lang, name, env):
                b['kuruldu'] = True
            save_state(st)
    return 0


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


def sezon_hafiza_guncelle(st, h, kh_key='karakter_hafiza', coz_key='cozulenler'):
    """Karakter gelişimi ve çözülmüş sorunlar sezon hafızasına yazılır (karakterler olayları unutmasın)."""
    kh = st.setdefault(kh_key, {})
    for c, v in (h.get('karakter_gelisimi') or {}).items():
        v = str(v or '').strip()
        if v and c in ('tuna', 'nil', 'bulut', 'pire'):
            kh.setdefault(c, []).append(v[:140])
            kh[c] = kh[c][-8:]
    cz = str(h.get('cozulen_sorun') or '').strip()
    if cz:
        st.setdefault(coz_key, []).append(cz[:140])
        st[coz_key] = st[coz_key][-40:]


def kanal_yonet(st, ep, vid, lang, season_name, token_env, log=log):
    """Videoyu sezon oynatma listesine ekler ve kanal adına yorum bırakır (yetki yoksa sessizce atlar)."""
    if not vid:
        return False
    ok = False
    tr = lang == 'tr'
    key = 'oynatma' if tr else 'oynatma_en'
    title = (f"Mini Dünya · {season_name}" if tr else f"Mini World · {season_name}")[:150]
    try:
        pls = st.setdefault(key, {})
        if title not in pls:
            desc = ("Mini Dünya bölümleri sırasıyla. Baştan izle, haritanın her köşesini keşfet!" if tr
                    else "Every Mini World episode in order. Start from the beginning and explore every corner of the map!")
            pls[title] = youtube.playlist_ensure(title, desc, token_env, lang)
        youtube.playlist_add(pls[title], vid, token_env)
        log(f'  Oynatma listesine eklendi: {title}')
        ok = True
    except Exception as e:
        log(f'  Oynatma listesi atlandı: {e}')
    soru = ep.get('end_card', '').strip()
    devam = ((ep.get('hafiza') or {}).get('acik_meseleler') or [''])[0]
    if tr:
        text = f"{soru} Cevabını yorumlara yaz! 👇\n\n🗺️ Haritanın devamı yarın: {devam}\nKaçırmamak için abone ol, bildirimleri aç! 🔔"
    else:
        text = f"{soru} Tell us in the comments! 👇\n\n🗺️ The map continues tomorrow. Subscribe and turn on notifications so you don't miss it! 🔔"
    if ok:
        st.setdefault('bekleyen_yorum', []).append({'video_id': vid, 'token': token_env, 'metin': text})
        yorumlari_gonder(st, log=log)
    return ok


def yorumlari_gonder(st, log=log):
    """Bekleyen yorumları gönderir; zamanlanmış (henüz özel) videolar yayına girince sonraki çalıştırmada gönderilir."""
    kalan = []
    for y in st.get('bekleyen_yorum', []):
        try:
            youtube.comment(y['video_id'], y['metin'], y['token'])
            log(f"  Kanal yorumu yazıldı: {y['video_id']}")
        except Exception as e:
            y['deneme'] = y.get('deneme', 0) + 1
            if 'insufficient' in str(e).lower() or y['deneme'] >= 12:
                log(f'  Yorum atlandı: {str(e)[:160]}')
            else:
                kalan.append(y)
    st['bekleyen_yorum'] = kalan[-40:]


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
    # teknik kalite kontrolü: kritik hatada QCError -> bu bölüm yayınlanmaz, slot sonraki saatte yeniden denenir
    from . import qc
    rep = qc.check(final, W, H, 30, expected_dur=tl['total'], outdir=outdir, log=log)
    ep['_qc'] = {k: rep.get(k) for k in ('karar', 'sure_sn', 'ses_lufs', 'siyah_sn', 'orta', 'dusuk', 'duzeltmeler')}
    thumb = render.thumbnail(ep, tl, os.path.join(outdir, 'kapak.jpg'), W, H, meta)
    return final, thumb, engine, tl['total']


def update_analytics(st, log=log):
    """Kalma oranı, ortalama izlenme süresi ve kazanılan abone (Analytics yetkisi varsa)."""
    end = dt.date.today().isoformat()
    start = (dt.date.today() - dt.timedelta(days=60)).isoformat()
    for key, env in (('bolumler', 'YT_REFRESH_TOKEN'), ('en_bolumler', 'YT_REFRESH_TOKEN_EN')):
        ids = [b['video_id'] for b in st.get(key, [])[-60:] if b.get('video_id')]
        if not ids or not youtube.configured(env):
            continue
        try:
            a = youtube.analytics(ids, start, end, env)
            for b in st[key]:
                r = a.get(b.get('video_id'))
                if r:
                    b['izleme_yuzdesi'] = round(float(r.get('averageViewPercentage', 0)), 1)
                    b['ort_sure_sn'] = int(r.get('averageViewDuration', 0))
                    b['abone_kazanci'] = int(r.get('subscribersGained', 0))
                    b['paylasim'] = int(r.get('shares', 0))
        except Exception as e:
            log(f'  Analytics alınamadı ({key}): {str(e)[:120]}')


def update_stats(st, log=log):
    try:
        yorumlari_gonder(st, log=log)
        update_analytics(st, log=log)
    except Exception as e:
        log(f'  Kanal yönetimi adımı atlandı: {e}')
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
    try:
        full = youtube.stats(ids, full=True)
        for b in st['bolumler']:
            if b.get('video_id') in full:
                b['begeni'] = full[b['video_id']].get('likeCount', 0)
                b['yorum'] = full[b['video_id']].get('commentCount', 0)
    except Exception:
        pass
    # İngilizce kanal istatistikleri (haftalık değerlendirme için)
    en_ids = [b['video_id'] for b in st.get('en_bolumler', [])[-40:] if b.get('video_id')]
    if en_ids and youtube.configured('YT_REFRESH_TOKEN_EN'):
        try:
            full = youtube.stats(en_ids, token_env='YT_REFRESH_TOKEN_EN', full=True)
            for b in st['en_bolumler']:
                if b.get('video_id') in full:
                    b['izlenme'] = full[b['video_id']].get('viewCount', 0)
                    b['begeni'] = full[b['video_id']].get('likeCount', 0)
                    b['yorum'] = full[b['video_id']].get('commentCount', 0)
        except Exception as e:
            log(f'  İngilizce izlenme verisi alınamadı: {e}')
    def puan(b):
        # izlenme + izleyiciyi tutma + abone kazandırma (veri varsa)
        return (b.get('izlenme') or 0) * (0.5 + (b.get('izleme_yuzdesi') or 50) / 100) + 300 * (b.get('abone_kazanci') or 0)

    def satir(b):
        ek = f", izleme %{b['izleme_yuzdesi']}" if b.get('izleme_yuzdesi') is not None else ''
        ek += f", +{b['abone_kazanci']} abone" if b.get('abone_kazanci') else ''
        return (f"{b['baslik']} ({b['izlenme']} izlenme{ek}; kategori {b.get('kategori', '?')}, mekân {b.get('mekan', '?')}, "
                f"odak {b.get('ana_karakter', '?')}): {b.get('ozet', '')}")
    olc = [b for b in st['bolumler'] if b.get('izlenme') is not None and b.get('tarih', '') < dt.date.today().isoformat()]
    ranked = sorted(olc, key=lambda b: -puan(b))
    st['en_cok_izlenen'] = [satir(b) for b in ranked[:5]]
    st['en_zayif'] = [satir(b) for b in ranked[-3:]] if len(ranked) >= 8 else []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--slot', default='auto', choices=['auto', 'sabah', 'oglen', 'aksam', 'gece', 'uzun'])
    ap.add_argument('--json', help='Hazır senaryo dosyasından üret')
    ap.add_argument('--no-upload', action='store_true')
    ap.add_argument('--force', action='store_true', help='Bugün bu slot yapılmış olsa da üret')
    ap.add_argument('--fikir', action='store_true', help='Bugünün fikir havuzunu (TR + EN) üret')
    ap.add_argument('--kanal-kurulum', action='store_true', help='Mevcut videoları oynatma listelerine ekle, yorum bırak')
    ap.add_argument('--en-telafi', action='store_true', help='Bugünün İngilizce sürümü olmayan bölümlerini İngilizce üret')
    args = ap.parse_args()
    if args.en_telafi:
        return en_backfill()
    if args.kanal_kurulum:
        return kanal_kurulum()
    if args.fikir:
        return fikir_uret()

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
        brief = None
    else:
        plan, day = season_day(st, cfg, today)
        kind, brief = brief_for(slot, plan, day, today)
        log(f"Sezon {st['sezon']} · Gün {day} · {slot} ({kind}): {brief}")
        st['_gun'] = day
        idea = None
        if kind != 'uzun':
            try:
                from . import fikir
                idea = fikir.gunun_fikirleri(st, plan, day, today, cfg, 'tr', log=log, sadece_onbellek=True).get(slot)
                if not idea:
                    log('  Bugün için hazır fikir yok; sezon planıyla devam.')
            except Exception as e:
                log(f'  Fikir motoru atlandı: {e}')
        ep = writer.write_episode(kind, brief + (fikir.brief_ek(idea) if idea else ''), st, plan, cfg, log=log)
        ep['_fikir'] = idea
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
            kanal_yonet(st, ep, vid_id, 'tr', (plan or {}).get('ad') or f"Sezon {st['sezon']}", 'YT_REFRESH_TOKEN', log=log)

    # hafıza
    st['bolum_no'] = no
    h = ep.get('hafiza', {})
    yb = str(h.get('yeni_bolge') or '').strip()
    if yb and yb not in st.setdefault('harita', []):
        st['harita'].append(yb)
    sezon_hafiza_guncelle(st, h)
    if ep.get('_fikir'):
        from . import fikir
        fikir.kaydet(st, ep['_fikir'], 'tr')
    if kind != 'bagimsiz' and isinstance(h.get('acik_meseleler'), list):
        st['acik_meseleler'] = [str(x) for x in h['acik_meseleler']][:8]
    st['bolumler'].append({'no': no, 'tarih': today.isoformat(), 'slot': slot, 'tur': kind, 'baslik': ep['baslik'],
                           'ozet': h.get('ozet', ''), 'video_id': vid_id, 'ses': engine,
                           'kategori': ep.get('kategori', ''), 'konu': ep.get('konu', ''), 'qc': ep.get('_qc'),
                           'final_turu': ep.get('final_turu', ''), 'fikir': ep.get('_fikir'),
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
            produce_en(ep, kind, no, st['sezon'], today, slot, cfg, st, brief=brief, plan=plan)
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
