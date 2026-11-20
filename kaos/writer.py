"""Senaryo yazarı: Gemini (ücretsiz katman) ile bölüm yazar, kontrol eder, düzeltir."""
import json
import os
import re
import time
import urllib.error
import urllib.request

from . import paths

CHARS = ['kemal', 'tayfun', 'erdal', 'necati', 'fikri', 'vedat', 'telefon']
EMOTIONS = ['normal', 'panik', 'sinirli', 'bikkin', 'neseli', 'soguk', 'saskin', 'fisilti', 'aglamakli', 'kibirli']
ACTIONS = ['yok', 'gir_sag', 'gir_sol', 'kos_sag', 'kos_sol', 'cik', 'kac', 'zipla', 'titre', 'carp', 'kameraya_bak', 'cal']
LOCATIONS = ['rihtim', 'saha', 'gumruk', 'kantar', 'depo', 'ofis', 'gece']


class WriterError(Exception):
    pass


# ------------------------------------------------------------------ Gemini metin
def _post(url, body, timeout=120):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


_MODEL_CACHE = {}


def list_models(key, kind='text'):
    """Anahtarın erişebildiği modelleri listeler (text: sohbet modelleri, tts: ses modelleri)."""
    if kind in _MODEL_CACHE:
        return _MODEL_CACHE[kind]
    names, token = [], ''
    try:
        for _ in range(5):
            url = f'https://generativelanguage.googleapis.com/v1beta/models?pageSize=200&key={key}'
            if token:
                url += f'&pageToken={token}'
            with urllib.request.urlopen(url, timeout=30) as r:
                data = json.loads(r.read())
            for m in data.get('models', []):
                if 'generateContent' in m.get('supportedGenerationMethods', []):
                    names.append(m['name'].split('/')[-1])
            token = data.get('nextPageToken', '')
            if not token:
                break
    except Exception:
        return []
    if kind == 'tts':
        c = [n for n in names if 'tts' in n]
        c.sort(key=lambda n: ('pro' in n, n))
    else:
        bad = ('tts', 'image', 'live', 'embedding', 'audio', 'vision', 'aqa', 'veo', 'imagen', 'robotics', 'computer', 'thinking')
        c = [n for n in names if 'flash' in n and not any(b in n for b in bad) and 'gemma' not in n]
        def ver(n):
            v = re.findall(r'(\d+(?:\.\d+)?)', n)
            return float(v[0]) if v else 0.0
        c.sort(key=lambda n: ('lite' in n, 'preview' in n or 'exp' in n, -ver(n), n))
    _MODEL_CACHE[kind] = c
    return c


def _model_order(configured, available):
    """Önce config'deki (hâlâ var olan) modeller, sonra bulunan diğerleri."""
    if not available:
        return list(configured)
    out = [m for m in configured if m in available]
    out += [m for m in available if m not in out]
    return out[:6]


def gemini_json(prompt, cfg, temperature=1.0, log=print):
    key = os.environ.get('GEMINI_API_KEY', '')
    if not key:
        raise WriterError('GEMINI_API_KEY tanımlı değil')
    available = list_models(key, 'text')
    models = _model_order(cfg['senaryo'].get('modeller', []), available)
    if available:
        log(f'  Metin modelleri: {", ".join(models)}')
    errs = []
    dead = set()
    for attempt in range(4):
        for model in models:
            if model in dead:
                continue
            url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}'
            body = {'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
                    'generationConfig': {'temperature': temperature, 'responseMimeType': 'application/json'}}
            try:
                data = _post(url, body, timeout=180)
                txt = ''.join(p.get('text', '') for p in data['candidates'][0]['content']['parts'])
                txt = re.sub(r'^```(json)?|```$', '', txt.strip()).strip()
                return json.loads(txt)
            except urllib.error.HTTPError as e:
                try:
                    msg = json.loads(e.read()).get('error', {}).get('message', '')[:160]
                except Exception:
                    msg = ''
                errs.append(f'{model}: HTTP {e.code} {msg}'.strip())
                if e.code in (400, 403, 404):
                    dead.add(model)
                if e.code in (429, 500, 503):
                    time.sleep(15)
            except Exception as e:
                errs.append(f'{model}: {e}')
        if all(m in dead for m in models):
            break
        log(f'  Gemini meşgul, tekrar denenecek ({attempt + 1}/4)')
        time.sleep(30 * (attempt + 1))
    raise WriterError('Gemini metin isteği başarısız: ' + ' | '.join(errs[-8:]))


# ------------------------------------------------------------------ istem
SCHEMA = """{
  "baslik": "Kısa bölüm başlığı (en fazla 5 kelime)",
  "kapak_yazisi": "Kapak görseli için 2-4 kelimelik çarpıcı yazı",
  "end_card": "Kapanış kartında yazacak tek cümle (ana hikâyede merak bırakan 'Devamı...' cümlesi; bağımsız skeçte esprili bir kapanış)",
  "music": "komik | gergin | sakin",
  "scenes": [
    {
      "title": "Sahne başlığı (sadece uzun videoda kullanılır)",
      "location": "rihtim | saha | gumruk | kantar | depo | ofis | gece",
      "characters": ["sahnedeki karakter anahtarları"],
      "lines": [
        {"who": "karakter anahtarı", "text": "Replik", "emotion": "duygu", "action": "hareket"}
      ]
    }
  ],
  "youtube": {"title": "YouTube başlığı (merak uyandıran, en fazla 70 karakter, emoji yok)", "description": "2-3 cümlelik açıklama", "tags": ["5-10 etiket"]},
  "hafiza": {"ozet": "Bu bölümde ne oldu (1-2 cümle)", "acik_meseleler": ["Sonraki bölümlere taşınan açık konular"], "kemal_gun": 0}
}"""

RULES_COMMON = f"""
KARAKTER ANAHTARLARI: kemal (Konteyner Kemal), tayfun (Tır Tayfun), erdal (Evrak Erdal), necati (Gemi Necati), fikri (Forklift Fikri), vedat (Vinç Vedat), telefon (Müşteri hattı: hep 'Yüküm nerede?' diye arayan sabırsız müşteri; sadece sesi var, görünmeyen kişi).
DUYGULAR (emotion): {', '.join(EMOTIONS)}
HAREKETLER (action): yok, gir_sag / gir_sol (sahneye normal girer), kos_sag / kos_sol (sahneye hızla koşarak/kayarak dalar — aksiyon girişi), cik (sahneden çıkar), kac (panikle hızla kaçar), zipla (zıplar), titre (kısa titreme, korku/soğuk), carp (bir şeye çarpar ya da üstüne bir şey düşer: GÜM! efekti), kameraya_bak (seyirciye döner, final için ideal), cal (sadece telefon: çalarak konuşmaya başlar). kos_* ve kac sadece kemal, tayfun, erdal, fikri için.
MEKÂNLAR: {', '.join(LOCATIONS)} (necati varsa mekân rihtim ya da gece olmalı)
KURALLAR:
- Dil Türkçe, günlük ve doğal. Replikler kısa ve vurucu (en fazla 18 kelime). Küfür, argo hakaret, siyaset, din, gerçek firma ya da kişi adı YOK.
- Sayıları yazıyla yaz ("kırk beş", "45" değil) çünkü seslendirilecek. Kısaltmaları açık yaz ya da okunuşuyla yaz ("e te a" yerine "varış saati").
- Sahneye sonradan giren karakterin İLK repliğinde action gir_sag, gir_sol, kos_sag ya da kos_sol olsun; baştan sahnede olanlarda 'yok'.
- İZLEYİCİ: Çocuklar dahil genel aile kitlesi. Tamamen aile dostu: korkutucu şiddet, kan, alkol, sigara, kaba laf yok; çarpışmalar çizgi film usulü (kimse gerçekten zarar görmez, hemen toparlanır).
- AKSİYON + KOMEDİ: Her bölümde sadece konuşma değil, bir AKSİYON anı olsun: bir kovalamaca, son saniye yetiştirme, kaçan konteyner, devrilen yük, fırtına, bozulan fren, yarış, kurtarma gibi. Bunu hareketlerle göster (kos_*, kac, carp, zipla). Shorts'ta en az 2, uzun videoda her sahnede en az 1 hareketli an olsun; ama 'titre'yi bölümde en fazla 1 kez kullan.
- KOMEDİ TEKNİKLERİ: üçlü kuralı (üçüncü şey beklenmedik), yanlış anlama, karakterin sabit lafının en kötü anda gelmesi, büyüyen kaos (her replik durumu daha da kötüleştirir), ciddi anda saçma detay, beklenmedik ters köşe final. Çocukların anlayacağı fiziksel komedi (çarpma, kayma, sıkışma) + yetişkinlerin güleceği sektör şakası birlikte.
- Her karakterin kişiliğine, sabit lafına ve ses tonuna sadık kal. Herkes sistemin kurbanı, kimse gerçekten kötü değil.
- Sektör bilgisi gerçekçi olsun (sektörde çalışan güldüğü için), ama sektörü hiç bilmeyen de anlamalı ve gülmeli.
- Sadece JSON döndür, başka metin yazma.
"""


def build_prompt(kind, brief, evren, memory, plan, extra=''):
    recent = memory.get('bolumler', [])[-12:]
    recent_txt = '\n'.join(f"- {b['no']}. bölüm ({b['tur']}): {b['baslik']} — {b.get('ozet', '')}" for b in recent) or '- (henüz bölüm yok)'
    acik = '\n'.join(f'- {a}' for a in memory.get('acik_meseleler', [])) or '- (yok)'
    top = memory.get('en_cok_izlenen', [])
    top_txt = ('\nEN ÇOK İZLENEN BÖLÜMLER (bu tarz şakalara ağırlık ver):\n' + '\n'.join(f'- {x}' for x in top[:5])) if top else ''
    kemal_gun = memory.get('kemal_gun', plan.get('kemal_gun_baslangic', 45))
    if kind == 'uzun':
        fmt = """FORMAT: YATAY UZUN VİDEO (6-7 dakika). 6-9 sahne, toplam 75-110 replik, toplam yaklaşık 850-1000 kelime.
Her sahnenin kendi küçük şakası ve başlığı olsun; sahneler bir hikâye halinde ilerlesin ve büyük bir finalle bitsin.
Shorts'larda yayınlanmamış yeni olaylar ve sahneler mutlaka olsun (aynı Shorts'ları tekrar etme). İlk sahne yeni izleyiciye durumu anlatsın."""
    else:
        fmt = """FORMAT: DİKEY SHORTS (25-40 saniye). Tek sahne, 2-4 karakter, 5-9 replik, toplam 55-95 kelime.
- İLK REPLİK KANCA: Durumu bilmeyen birine bile tek cümlede anlatan bir bağırış ya da soru (en fazla 12 kelime).
- Bölüm tek başına anlaşılır ve tek başına komik olmalı.
- SON REPLİK TERS KÖŞE: güldüren bir punchline; tercihen action 'kameraya_bak'."""
    if kind == 'ana':
        tur = 'ANA HİKÂYE bölümü: sezon hikâyesini bir adım ilerlet, sonunda merak bırak (end_card "Devamı..." ile).'
    elif kind == 'bagimsiz':
        tur = 'BAĞIMSIZ SKEÇ: sezon hikâyesinden bağımsız, sektörden tek bir olayı komediye çevir. Ana hikâyeye en fazla küçük bir gönderme yapabilirsin.'
    else:
        tur = 'UZUN VİDEO bölümü.'
    return f"""Sen "MİNİ DÜNYA" adlı Türkçe animasyon sitcom'unun baş senaristisin. Bir liman ve lojistik merkezinde konuşan araçlar, eşyalar ve belgeler var.

=== EVREN KİTABI ===
{evren}

=== SEZON: {plan.get('ad', '')} ===
{plan.get('ana_hikaye', '')}

=== ŞU ANA KADAR (son bölümler) ===
{recent_txt}

AÇIK MESELELER:
{acik}
KEMAL'İN LİMANDAKİ GÜN SAYACI ŞU AN: {kemal_gun} (ana hikâyede gerekiyorsa 1 artır){top_txt}

=== BU BÖLÜM ===
TÜR: {tur}
KONU: {brief}
{fmt}
{RULES_COMMON}
{extra}
JSON ŞEMASI:
{SCHEMA}
"""


CRITIC = """Aşağıda "MİNİ DÜNYA" için yazılmış bir bölüm var. Sen deneyimli bir komedi yazarı ve editörsün.
Kontrol et ve gerekiyorsa DÜZELT:
1. Bölüm, diziyi hiç izlememiş biri için tek başına anlaşılıyor mu? İlk replik durumu anlatıyor mu?
2. Gerçekten komik mi? Punchline güçlü mü? Zayıf replikleri daha komik yap; sıradan replikleri esprili olanlarla değiştir.
2b. Aksiyon var mı? Yalnızca konuşan karakterler varsa en az bir hareketli an ekle (kos_sag/kos_sol/kac/carp/zipla). 'titre' en fazla 1 kez.
2c. Çocuklar dahil aile kitlesine uygun mu? Değilse düzelt.
3. Karakterler kişiliklerine sadık mı? Sektör detayı doğru mu?
4. Kurallar: sayılar yazıyla, replikler kısa, küfür/siyaset/gerçek isim yok, JSON şeması aynen korunuyor.
5. Son {n} bölümün şakalarını tekrar ediyor mu? Ediyorsa değiştir: {recent}
Düzeltilmiş bölümü AYNI JSON ŞEMASIYLA döndür (sadece JSON).

BÖLÜM:
{ep}
"""


# ------------------------------------------------------------------ doğrulama
def validate(ep, kind):
    errs = []
    if not isinstance(ep, dict) or 'scenes' not in ep or not ep['scenes']:
        return ['scenes yok']
    total_words, total_lines = 0, 0
    for sc in ep['scenes']:
        loc = sc.get('location', 'rihtim')
        if loc not in LOCATIONS:
            sc['location'] = 'rihtim'
        lines = sc.get('lines', [])
        if not lines:
            errs.append('boş sahne')
            continue
        whos = []
        for ln in lines:
            w = str(ln.get('who', '')).lower().strip()
            if w not in CHARS:
                errs.append(f"bilinmeyen karakter: {ln.get('who')}")
                continue
            ln['who'] = w
            whos.append(w)
            if ln.get('emotion') not in EMOTIONS:
                ln['emotion'] = 'normal'
            if ln.get('action') not in ACTIONS:
                ln['action'] = 'yok'
            if ln['action'] == 'cal' and w != 'telefon':
                ln['action'] = 'yok'
            if ln['action'] in ('kos_sag', 'kos_sol') and w not in ('kemal', 'tayfun', 'erdal', 'fikri'):
                ln['action'] = 'gir_' + ln['action'][4:]
            if ln['action'] == 'kac' and w not in ('kemal', 'tayfun', 'erdal', 'fikri'):
                ln['action'] = 'cik'
            if ln['action'] in ('carp', 'kos_sag', 'kos_sol', 'kac') and w == 'telefon':
                ln['action'] = 'yok'
            ln['text'] = re.sub(r'\s+', ' ', str(ln.get('text', ''))).strip()
            if not ln['text']:
                errs.append('boş replik')
            total_words += len(ln['text'].split())
            total_lines += 1
        chars = [c for c in sc.get('characters', []) if c in CHARS]
        for w in whos:
            if w not in chars:
                chars.append(w)
        sc['characters'] = chars
        if 'necati' in chars and sc['location'] not in ('rihtim', 'gece'):
            sc['location'] = 'rihtim'
        ground = [c for c in chars if c not in ('necati', 'vedat')]
        if len(ground) > 4:
            errs.append('bir sahnede en fazla 4 yer karakteri olabilir')
        # telefon ilk kez konuşurken çalsın
        seen = set()
        for ln in lines:
            if ln.get('who') == 'telefon' and 'telefon' not in seen:
                ln['action'] = 'cal'
            seen.add(ln.get('who'))
    if kind == 'uzun':
        if total_lines < 45:
            errs.append(f'uzun video için çok az replik ({total_lines}); en az 75 olmalı')
        if total_words < 500:
            errs.append(f'uzun video için çok az kelime ({total_words}); yaklaşık 900 olmalı')
    else:
        if len(ep['scenes']) > 1:
            ep['scenes'] = ep['scenes'][:1]
        if total_lines < 4 or total_lines > 12:
            errs.append(f'shorts için replik sayısı {total_lines}; 5-9 olmalı')
        if total_words > 130:
            errs.append(f'shorts çok uzun ({total_words} kelime); en fazla 95 olmalı')
    yt = ep.setdefault('youtube', {})
    yt['title'] = str(yt.get('title') or ep.get('baslik') or 'Mini Dünya')[:95]
    yt.setdefault('description', '')
    yt.setdefault('tags', [])
    ep.setdefault('end_card', '')
    ep.setdefault('baslik', yt['title'])
    ep.setdefault('kapak_yazisi', ep['baslik'])
    if ep.get('music') not in ('komik', 'gergin', 'sakin'):
        ep['music'] = 'komik'
    ep.setdefault('hafiza', {})
    return errs


def write_episode(kind, brief, memory, plan, cfg, log=print):
    evren = open(os.path.join(paths.EVREN, 'evren.md'), encoding='utf-8').read()
    prompt = build_prompt(kind, brief, evren, memory, plan)
    ep, errs = None, ['başlamadı']
    for attempt in range(3):
        extra = '' if attempt == 0 else f"\nÖNCEKİ DENEMEDEKİ HATALAR (düzelt): {'; '.join(errs)}"
        ep = gemini_json(prompt + extra, cfg, log=log)
        errs = validate(ep, kind)
        if not errs:
            break
        log(f'  Senaryo hataları: {errs}')
    if errs:
        raise WriterError('Senaryo kurallara uymadı: ' + '; '.join(errs))
    if cfg['senaryo'].get('kalite_kontrol', True):
        recent = '; '.join(b['baslik'] for b in memory.get('bolumler', [])[-10:]) or 'yok'
        try:
            ep2 = gemini_json(CRITIC.format(n=10, recent=recent, ep=json.dumps(ep, ensure_ascii=False)), cfg, temperature=0.7, log=log)
            if not validate(ep2, kind):
                ep = ep2
                log('  Kalite kontrolden geçti (düzeltilmiş sürüm)')
        except Exception as e:
            log(f'  Kalite kontrol atlandı: {e}')
    return ep


def new_season_plan(season_no, memory, cfg, log=print):
    evren = open(os.path.join(paths.EVREN, 'evren.md'), encoding='utf-8').read()
    recent = '\n'.join(f"- {b['baslik']}: {b.get('ozet', '')}" for b in memory.get('bolumler', [])[-30:])
    prompt = f"""Sen "MİNİ DÜNYA" animasyon sitcom'unun baş senaristisin.
EVREN KİTABI:
{evren}

ÖNCEKİ SEZONDAN OLANLAR:
{recent}

Sezon {season_no} için 14 günlük plan yaz. Her gün: sabah (ana hikâye), aksam (ana hikâye, sabahın devamı), oglen (bağımsız sektör skeci).
7. ve 14. gün sabahı 'Haftanın Özeti' olsun. Ayrıca 4 uzun video konusu yaz (hafta1_carsamba, hafta1_pazar, hafta2_carsamba, hafta2_pazar).
Bu sezonda farklı bir karakter öne çıksın; önceki sezondan bir kanca devam etsin. Sektör olay havuzundan yararlan.
Sadece JSON döndür:
{{"sezon": {season_no}, "ad": "...", "ana_hikaye": "...", "kemal_gun_baslangic": 1,
 "gunler": [{{"gun": 1, "sabah": "...", "aksam": "...", "oglen": "..."}}],
 "uzun": {{"hafta1_carsamba": "...", "hafta1_pazar": "...", "hafta2_carsamba": "...", "hafta2_pazar": "..."}}}}"""
    plan = gemini_json(prompt, cfg, log=log)
    if len(plan.get('gunler', [])) < 14:
        raise WriterError('Sezon planı eksik geldi')
    return plan
