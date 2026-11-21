"""Rakip analizi: son 30 günün en çok izlenen animasyon Shorts'larını bulur, en iyilerini Gemini'ye izletir,
kopyalamadan genel teknikleri çıkarır ve senaryo yazarına verilecek içgörüleri state/rakip.json'a yazar.
Çalıştırma: python -m kaos.rakip"""
import datetime as dt
import json
import os
import re
import urllib.parse
import urllib.request

from . import paths, youtube
from .writer import gemini_json, list_models, _model_order, _post

SORGULAR = {
    'tr': ['animasyon shorts', 'çizgi film kısa', 'komik animasyon', 'minik insanlar animasyon', 'animasyon hikaye'],
    'en': ['animation shorts', 'animated story shorts', 'tiny people animation', 'funny cartoon shorts', '2d animation short story'],
}
OUT = os.path.join(paths.ROOT, 'state', 'rakip.json')


def _get(url, tok):
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {tok}'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _dur(iso):
    m = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', iso or '')
    if not m:
        return 0
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


def topla(log=print):
    """YouTube'da dil başına en çok izlenen yeni animasyon Shorts'larını toplar (kota: sorgu başına ~100 birim)."""
    tok = youtube.access_token()
    since = (dt.datetime.utcnow() - dt.timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%SZ')
    out = {}
    for lang, qs in SORGULAR.items():
        ids = []
        for q in qs:
            params = {'part': 'id', 'type': 'video', 'q': q, 'videoDuration': 'short', 'order': 'viewCount',
                      'publishedAfter': since, 'maxResults': 25, 'relevanceLanguage': lang,
                      'regionCode': 'TR' if lang == 'tr' else 'US'}
            try:
                d = _get('https://www.googleapis.com/youtube/v3/search?' + urllib.parse.urlencode(params), tok)
                ids += [it['id']['videoId'] for it in d.get('items', [])]
            except Exception as e:
                log(f'  arama hatası ({q}): {e}')
        ids = list(dict.fromkeys(ids))
        vids = []
        for i in range(0, len(ids), 50):
            d = _get('https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics,contentDetails&id=' + ','.join(ids[i:i + 50]), tok)
            for it in d.get('items', []):
                sec = _dur(it['contentDetails'].get('duration'))
                if not sec or sec > 180:
                    continue
                pub = dt.datetime.strptime(it['snippet']['publishedAt'][:19], '%Y-%m-%dT%H:%M:%S')
                days = max(1.0, (dt.datetime.utcnow() - pub).total_seconds() / 86400)
                views = int(it['statistics'].get('viewCount', 0))
                vids.append({'id': it['id'], 'baslik': it['snippet']['title'], 'kanal': it['snippet']['channelTitle'],
                             'sure': sec, 'izlenme': views, 'gunluk': int(views / days),
                             'begeni': int(it['statistics'].get('likeCount', 0) or 0),
                             'yorum': int(it['statistics'].get('commentCount', 0) or 0),
                             'etiket': it['snippet'].get('tags', [])[:8]})
        vids.sort(key=lambda v: -v['gunluk'])
        out[lang] = vids[:30]
        log(f'  {lang}: {len(vids)} video bulundu, en hızlı: {vids[0]["baslik"][:60] if vids else "-"}')
    return out


def izle(video_id, cfg, log=print):
    """Gemini'ye herkese açık videoyu izletir; kopyalanmayacak, genel teknik çıkarılır."""
    key = os.environ.get('GEMINI_API_KEY', '')
    models = _model_order(cfg['senaryo'].get('modeller', []), list_models(key, 'text'))
    prompt = ("Bu kısa animasyon videosunu izle ve bir animasyon yapımcısına TEKNİK analiz ver. Hikâyeyi, karakter adlarını ya da "
              "özgün fikri kopyalanacak şekilde anlatma; sadece genel, aktarılabilir teknikleri çıkar. Sadece JSON döndür: "
              '{"ilk_2_saniye": "ilk 2 saniyede ekranda ne oluyor (genel teknik olarak)", "kanca_tipi": "soru/şok/tehlike/gizem/komedi...", '
              '"konu_turu": "genel tema", "mekan_turu": "genel mekân tipi", "tempo": "kaç saniyede bir kesme/olay", '
              '"diyalog": "az/orta/çok; anlatıcı var mı", "duygu": "neden izlettiriyor", "final": "final tekniği", '
              '"yazi_kullanimi": "ekrandaki yazılar", "ses_muzik": "ses ve müzik kullanımı", "uygulanabilir_ders": "bizim kanala uygulanabilecek 1-2 genel ders"}')
    for model in models[:3]:
        url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}'
        body = {'contents': [{'role': 'user', 'parts': [{'file_data': {'file_uri': f'https://www.youtube.com/watch?v={video_id}'}},
                                                        {'text': prompt}]}],
                'generationConfig': {'temperature': 0.4, 'responseMimeType': 'application/json'}}
        try:
            d = _post(url, body, timeout=240)
            txt = ''.join(p.get('text', '') for p in d['candidates'][0]['content']['parts'])
            return json.loads(re.sub(r'^```(json)?|```$', '', txt.strip()).strip())
        except Exception as e:
            log(f'    izleme hatası ({model}): {str(e)[:120]}')
    return None


def analiz(veri, izlenen, cfg, log=print):
    """Toplanan veriden kanala uygulanacak strateji içgörülerini çıkarır."""
    ozet = {lang: [{k: v[k] for k in ('baslik', 'sure', 'gunluk', 'begeni', 'yorum')} for v in vids[:25]]
            for lang, vids in veri.items()}
    prompt = f"""Sen bir YouTube Shorts animasyon stratejistisin. Kanalımız: "Mini Dünya / Mini World" — süpürgeliğin arkasında yaşayan
parmak boyundaki dört haritacının (Tuna, Nil, Bulut, Pire) ve uğur böceği Benek'in evin içini keşfettiği 2D macera dizisi. 7-45 yaş, aile dostu.

SON 30 GÜNÜN EN HIZLI BÜYÜYEN ANİMASYON SHORTS'LARI (günlük izlenmeye göre):
{json.dumps(ozet, ensure_ascii=False)}

BU VİDEOLARIN BİR KISMININ İZLENEREK ÇIKARILMIŞ TEKNİK ANALİZLERİ:
{json.dumps(izlenen, ensure_ascii=False)}

Görev: kopyalamadan, bizim evrenimize uygulanabilecek GENEL dersleri çıkar. Başka kanalların karakterlerini, isimlerini,
özgün hikâyelerini ya da görsel kimliğini ASLA önerme. Sadece JSON döndür:
{{"baslik_kaliplari": ["işe yarayan 3-5 başlık kalıbı (genel)"],
 "kanca_teknikleri": ["ilk 2 saniye için 3-5 teknik"],
 "konu_firsatlari": ["evrenimize uyarlanabilecek 5-8 genel konu/tema fikri"],
 "mekan_fikirleri": ["evin içinden 3-5 mekân önerisi"],
 "ideal_sure_sn": 0,
 "tempo": "önerilen tempo",
 "kacinilacaklar": ["tutmayan şeyler"],
 "yazar_notu": "senaryo yazarına verilecek 3-4 cümlelik özet talimat"}}"""
    return gemini_json(prompt, cfg, temperature=0.5, log=log)


def main(log=print):
    from .main import load_cfg
    cfg = load_cfg()
    log('Rakip analizi: veriler toplanıyor...')
    veri = topla(log=log)
    izlenen = []
    for lang in ('en', 'tr'):
        for v in veri.get(lang, [])[:3]:
            r = izle(v['id'], cfg, log=log)
            if r:
                izlenen.append({'dil': lang, 'baslik': v['baslik'], 'gunluk': v['gunluk'], 'sure': v['sure'], 'analiz': r})
                log(f"  izlendi: {v['baslik'][:60]}")
    ins = analiz(veri, izlenen, cfg, log=log)
    rapor = {'tarih': dt.date.today().isoformat(), 'icgoruler': ins, 'izlenen': izlenen,
             'en_hizli': {k: v[:10] for k, v in veri.items()}}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(rapor, f, ensure_ascii=False, indent=1)
    log('İçgörüler:\n' + json.dumps(ins, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
