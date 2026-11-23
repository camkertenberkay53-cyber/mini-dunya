"""Senaryo yazarı: Gemini (ücretsiz katman) ile bölüm yazar, kontrol eder, düzeltir."""
import json
import os
import re
import time
import urllib.error
import urllib.request

from . import paths

CHARS = ['tuna', 'nil', 'bulut', 'pire', 'benek']
SPEAKERS = ['tuna', 'nil', 'bulut', 'pire']
EMOTIONS = ['normal', 'panik', 'sinirli', 'bikkin', 'neseli', 'soguk', 'saskin', 'fisilti', 'aglamakli', 'kibirli']
ACTIONS = ['yok', 'gir_sag', 'gir_sol', 'kos_sag', 'kos_sol', 'cik', 'kac', 'yuru_sag', 'yuru_sol', 'isaret', 'egil',
           'zipla', 'titre', 'carp', 'kameraya_bak']
LOCATIONS = ['tezgah', 'lavabo', 'buzdolabi', 'baharat', 'zemin', 'cekmece', 'lonca']

# Aile dostu içerik güvenliği: bu köklerle başlayan hiçbir kelime yayına çıkmaz.
YASAK_KOKLER = [
    # küfür, hakaret, kaba söz
    'siktir', 'sikik', 'sikerim', 'amk', 'amına', 'orospu', 'piç', 'yavşak', 'kahpe', 'pezevenk', 'ibne', 'puşt',
    'kaltak', 'göt ', 'götü ', 'şerefsiz', 'haysiyetsiz', 'gerizekalı', 'salak', 'aptal', 'dangalak', 'ahmak', 'ezik', 'beyinsiz',
    'mal ', 'enayi', 'hıyar', 'it oğlu', 'köpek oğlu', 'lanet', 'kahrolası', 'defol', 'kes sesini', 'sus be', 'bok',
    'boktan', 'çüş', 'hödük', 'öküz', 'şişko', 'çirkin',
    # etnik köken, ırk, din, siyaset
    'kürt', 'arap', 'ermeni', 'yahudi', 'çingene', 'zenci', 'gavur', 'laz ', 'yörük', 'muhacir', 'göçmen', 'ırk',
    'müslüman', 'hristiyan', 'allah', 'tanrı', 'namaz', 'cami', 'kilise', 'peygamber', 'kafir', 'dinsiz',
    'seçim sandığı', 'siyasi', 'hükümet', 'cumhurbaşkanı', 'milletvekili', 'meclis', 'vatan haini',
    # şiddet, korku, bağımlılık
    'öldür', 'ölüm', 'ölü', 'kan ', 'kanlı', 'bıçakla', 'silah', 'tabanca', 'bomba', 'intihar', 'sigara', 'alkol',
    'bira', 'şarap', 'rakı', 'sarhoş', 'kumar',
]


def safety_errors(ep):
    """Bölümdeki tüm metinleri yasak köklere karşı tarar."""
    texts = [ep.get('baslik', ''), ep.get('kapak_yazisi', ''), ep.get('end_card', '')]
    yt = ep.get('youtube', {}) or {}
    texts += [yt.get('title', ''), yt.get('description', '')] + [str(t) for t in yt.get('tags', [])]
    for sc in ep.get('scenes', []):
        texts.append(sc.get('title', ''))
        texts += [ln.get('text', '') for ln in sc.get('lines', [])]
    found = set()
    for txt in texts:
        low = ' ' + str(txt).replace('I', 'ı').replace('İ', 'i').lower() + ' '
        for k in YASAK_KOKLER:
            if re.search(r'(?<![a-zçğıöşü])' + re.escape(k), low):
                found.add(k.strip())
    return [f'aile dostu olmayan ifade: {k}' for k in sorted(found)]


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


def gemini_json(prompt, cfg, temperature=1.0, log=print, rounds=6):
    key = os.environ.get('GEMINI_API_KEY', '')
    if not key:
        raise WriterError('GEMINI_API_KEY tanımlı değil')
    available = list_models(key, 'text')
    models = _model_order(cfg['senaryo'].get('modeller', []), available)
    if available:
        log(f'  Metin modelleri: {", ".join(models)}')
    errs = []
    dead = set()
    for attempt in range(rounds):
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
        log(f'  Gemini meşgul, tekrar denenecek ({attempt + 1}/{rounds})')
        time.sleep(45 * (attempt + 1))
    raise WriterError('Gemini metin isteği başarısız: ' + ' | '.join(errs[-8:]))


# ------------------------------------------------------------------ istem
SCHEMA = """{
  "konu": "Bölümün tek cümlelik konusu: kim, neyi, neden istiyor, önünde ne var",
  "kategori": "yeni bolge | devlerin gunu | kurtarma | yaris | problem cozme | gizem | yeni canli | dogal guc | mucit ani | basarisiz plan | ters kose | teknolojik kesif | ela ani | kisisel macera | lonca hayati | eski izler",
  "ana_karakter": "Bölümün odaktaki karakteri: tuna | nil | bulut | pire",
  "baslik": "Kısa bölüm başlığı (en fazla 5 kelime)",
  "acilis_efekti": "Shorts'un ilk saniyesindeki ölçek şoku (biri seçilmeli): dusen_nesne (dev bir nesne karakterlerin yanına GÜM diye düşer) | dev_el (Devlerin dev eli üstlerine uzanır) | dev_pati (ev kedisinin dev patisi uzanır) | dev_damla (dev bir su damlası düşüp patlar). İlk replik bu olaya tepki olmalı.",
  "kapak_yazisi": "VİDEONUN İLK SANİYESİNDE ekranda büyük yazacak KANCA: kaydıran izleyiciyi durduran 3-6 kelimelik şaşırtıcı ifade ya da soru. Bölümün olayını anlatsın, marka ya da bölüm numarası değil. Örn: 'DEV SÜNGER HARİTAYI YUTTU!', 'BUZDOLABINDA MAHSUR KALDIK', 'BU KAŞIK BİZİ TAŞIR MI?'",
  "end_card": "Kapanış kartında izleyiciye sorulan KISA ve eğlenceli bir soru (en fazla 8 kelime). Bölümle ilgili, cevabı yorumlara yazılabilir olsun. Örn: 'Sen olsan hangi yoldan geçerdin?' ya da 'Benek'e ne isim verirdin?'",
  "music": "komik | gergin | sakin",
  "scenes": [
    {
      "title": "Sahne başlığı (sadece uzun videoda kullanılır)",
      "location": "tezgah | lavabo | buzdolabi | baharat | zemin | cekmece | lonca",
      "characters": ["sahnedeki karakter anahtarları"],
      "lines": [
        {"who": "karakter anahtarı", "text": "Replik", "emotion": "duygu", "action": "hareket"}
      ]
    }
  ],
  "youtube": {"title": "YouTube başlığı (en fazla 70 karakter, emoji yok). İşe yarayan kalıplardan birini kullan: 'Parmak Boyundaki Haritacılar [Mekân]'a Karşı!', 'Dev Bir [Eşya]'dan Kaçış!', '[Eşya] Boyunda Olsaydın Ne Olurdu?', '[Mekân]'ın Altındaki Gizemli Keşif!' ya da benzeri merak uyandıran bir kalıp", "description": "2-3 cümlelik açıklama + en sonda izleyiciye yorumda cevaplayacağı bir soru (end_card sorusunun aynısı veya benzeri)", "tags": ["5-10 etiket"]},
  "final_turu": "tatmin | komik | sasirtici | merak (son bölümlerde kullanılmayan bir tür seç; her bölüm cliffhanger ile bitmek zorunda değil)",
  "hafiza": {"ozet": "Bu bölümde ne oldu (1-2 cümle)", "acik_meseleler": ["Sonraki bölümlere taşınan açık konular"], "yeni_bolge": "Bu bölümde haritaya işlenen bölge adı (yoksa boş)",
             "cozulen_sorun": "Bu bölümde çözülen somut problem (kısa)", "karakter_gelisimi": {"tuna": "bu bölümde yaşadığı başarı/hata/ders (yoksa boş)", "nil": "", "bulut": "", "pire": ""}}
}"""

RULES_COMMON = f"""
KARAKTER ANAHTARLARI: tuna (cesur, aceleci öncü), nil (analitik haritacı, kuru espri), bulut (iri, sakin, sakar mucit), pire (en küçük, meraklı çaylak), benek (uğur böceği binek; KONUŞMAZ, sadece sahnede durur ve tepki verir, ona replik yazma).
DUYGULAR (emotion): {', '.join(EMOTIONS)}
HAREKETLER (action): yok, gir_sag / gir_sol (sahneye yürüyerek girer), kos_sag / kos_sol (sahneye koşarak dalar), cik (sahneden çıkar), kac (hızla kaçar), yuru_sag / yuru_sol (sahne içinde birkaç adım yürür), isaret (bir yeri ya da şeyi eliyle gösterir), egil (eğilip yakından bakar, saklanır), zipla (zıplar), titre (kısa titreme), carp (bir şeye çarpar ya da üstüne bir şey düşer: GÜM!), kameraya_bak (seyirciye döner, final için ideal).
MEKÂNLAR: {', '.join(LOCATIONS)} (tezgah = mutfak tezgâhı; lavabo = lavabo ve damlayan musluk; buzdolabi = buzdolabının içi; baharat = baharat rafı; zemin = mutfak zemini, kedi mama kabı, karınca yolu; cekmece = çatal bıçak çekmecesi; lonca = süpürgeliğin arkasındaki Harita Odası)
KURALLAR:
- Dil Türkçe, günlük ve doğal. Replikler kısa ve vurucu (Shorts'ta en fazla 12, uzun videoda en fazla 16 kelime).
- KESİNLİKLE YASAK: küfür, argo, hakaret, alay, lakap takma; etnik köken, ırk, din, milliyet, siyaset, ayrımcılık ya da herhangi bir grubu kötüleyen söz; şiddet, kan, korku, ölüm; alkol, sigara; gerçek firma, marka ya da kişi adı. Karakterler birbirine asla kaba davranmaz; tartışsalar bile saygılı ve tatlıdır.
- İZLEYİCİ: 7-45 yaş, aile kitlesi. Çocuk güvenli ama bebeksi değil; yetişkin de keyif alsın.
- Sayıları yazıyla yaz ("üç yüz", "300" değil) çünkü seslendirilecek.
- HAREKET ÇOK ÖNEMLİ: Karakterler sabit durmasın, macera hissi olsun. Shorts'ta repliklerin en az yarısında 'yok' dışında bir hareket olsun (yuru_*, isaret, egil, zipla, kos_*, carp, kac). Duran karakter sadece gerektiğinde dursun. Aynı hareketi üst üste kullanma; 'titre' en fazla 1 kez.
- Sahneye sonradan giren karakterin İLK repliğinde action gir_sag, gir_sol, kos_sag ya da kos_sol olsun.
- MACERA + MERAK + DOĞAL KOMEDİ: ölçek farkı (dev nesneler), başarısız plan, yanlış anlama, karakter farkları, görsel ters köşe. Zoraki şaka ya da bağırış yok.
- Tehlikeler heyecanlı ama korkutucu değil; kimse zarar görmez.
- Her karakterin kişiliğine sadık kal. Devler (insanlar) hiç konuşmaz, yüzleri görünmez; sadece bahsedilirler.
- Sadece JSON döndür, başka metin yazma.
"""


def sezon_blogu(kind, memory, plan):
    """Sezon hikâye yöneticisi: ana gizem (cevapsız), bugünün ipucu, karakter yolculuğu ve hafızası, çözülmüş sorunlar."""
    if not plan:
        return ''
    gun = memory.get('_gun') or 0
    rows = plan.get('gunler', [])
    row = rows[gun - 1] if 0 < gun <= len(rows) else {}
    son_gun = gun >= len(rows) and gun > 0
    out = ['', 'SEZON HİKÂYE YÖNETİCİSİ:']
    if plan.get('gizem'):
        out.append(f"- SEZONUN ANA GİZEMİ (izleyicinin merak ettiği soru; cevabı ASLA açıklama{'' if not son_gun else ' — bugün FİNAL günü, akşam bölümünde açıklanabilir'}): {plan['gizem']}")
        if son_gun and plan.get('gizem_cozumu'):
            out.append(f"- GİZEMİN ÇÖZÜMÜ (sadece final bölümünde kullan): {plan['gizem_cozumu']}")
    if row.get('ipucu'):
        if kind == 'ana':
            out.append(f"- BUGÜNÜN İPUCU (ana bölümde doğal bir şekilde, görsel bir an ya da tek bir repliğe yerleştir; bölümün kendi problemi önde olsun): {row['ipucu']}")
        else:
            out.append(f"- Sezonun gizemine en fazla küçük bir gönderme yapabilirsin (zorunlu değil). Bugünkü ipucu: {row['ipucu']}")
    if row.get('odak'):
        out.append(f"- Bugünün sezon odak karakteri: {row['odak']}")
    yol = plan.get('karakter_yolculugu') or {}
    if yol:
        out.append('- KARAKTER YOLCULUKLARI (sezon boyunca yavaş yavaş gelişsinler): ' + ' | '.join(f'{k}: {v}' for k, v in yol.items()))
    kh = memory.get('karakter_hafiza') or {}
    if kh:
        out.append('- KARAKTERLERİN ŞİMDİYE KADAR YAŞADIKLARI (unutmasınlar, tutarlı davransınlar): ' +
                   ' | '.join(f"{k}: {'; '.join(v[-3:])}" for k, v in kh.items() if v))
    coz = memory.get('cozulenler') or []
    if coz:
        out.append('- DAHA ÖNCE ÇÖZÜLMÜŞ SORUNLAR (aynı problemi ya da aynı çözümü tekrar kullanma): ' + '; '.join(coz[-15:]))
    ft = [b.get('final_turu') for b in memory.get('bolumler', [])[-3:] if b.get('final_turu')]
    if ft:
        out.append(f"- Son bölümlerin final türleri: {', '.join(ft)}. Bu bölümde farklı bir final türü seç.")
    return '\n'.join(out)


# A/B testi: kısa format (20-25 sn). main.py slot'a göre açar/kapatır.
KISA = False
# Omni (yapay zekâ video) bölümü: görüntü motoru sınırı yok -> serbest sinema modu. main.py açar/kapatır.
OMNI = False
SINEMA = """SİNEMA MODU (bu bölüm sinematik 3D yapay zekâ videosu olarak çekilecek; motor sınırı YOK, hayal gücünü kullan):
- MEKÂN SERBEST: Büyük Ev'in herhangi bir yeri (oturma odası halısı, kitaplık rafları, çiçek saksısı ormanı, akvaryum kenarı,
  çalışma masası, banyo küveti, balkon, çatı arası, pencere pervazı...). "location" alanına yine listeden EN YAKIN olanı yaz,
  ama gerçek yeri "mekan" alanında canlı ve görsel olarak tarif et.
- DÜNYA ZENGİN: konuşmayan küçük canlılar (örümcek, karınca kolonisi, kelebek, sinek, salyangoz, uyuyan dev kedi), araçlar ve
  icatlar (kâğıt uçak, şişe kapağı tekne, balon, oyuncak araba, ataş kanca, ip asansör), doğa olayları (su baskını, toz fırtınası,
  rüzgâr) kullanılabilir. Türk evinin tanıdık nesneleri (çaydanlık, ince belli çay bardağı, simit, lokum, nazar boncuğu, Türk
  kahvesi fincanı, terlik) dev ölçekte harika sahneler verir.
- GÖRSEL AN: her bölümde akılda kalacak tek bir muhteşem görüntü olsun ("gorsel_an" alanı): ör. kâğıt uçakla mutfaktan süzülüş,
  dev kedinin bıyıklarının arasından kaçış, çay buharında kaybolan harita. Bunu final ya da doruk noktasına koy.
- GÖSTER, ANLATMA: replikler az ve kısa; olay görüntüyle anlaşılsın. Her repliğe kısa bir "sahne" alanı ekle: o an ekranda ne
  görünüyor (kamera, hareket, nesne) — tek cümle.
- Aksiyon gerçek ve büyük olabilir (kovalamaca, uçuş, düşme-kurtulma) ama korkutucu/şiddetli değil; tehlike hep komik ve tatlı biter.
- Karakterlerin görünüşü ve kişilikleri AYNI kalır; Benek konuşmaz.
"""


def build_prompt(kind, brief, evren, memory, plan, extra=''):
    if OMNI:
        brief = SINEMA + '\n' + brief
    recent = memory.get('bolumler', [])[-12:]
    recent_txt = '\n'.join(f"- {b['no']}. bölüm ({b['tur']}, kategori: {b.get('kategori', '?')}, mekân: {b.get('mekan', '?')}, odak: {b.get('ana_karakter', '?')}): {b['baslik']} — {b.get('ozet', '')} | final: {b.get('final', '')}" for b in recent) or '- (henüz bölüm yok)'
    sezon_txt = sezon_blogu(kind, memory, plan)
    son = memory.get('bolumler', [])[-6:]
    yasak_kat = sorted({b.get('kategori') for b in son if b.get('kategori')})
    yasak_kar = [b.get('ana_karakter') for b in son[-2:] if b.get('ana_karakter')]
    cesit = (f"\nÇEŞİTLİLİK ZORUNLU (YouTube birbirinin tekrarı içeriği para kazanmaya kapatır): "
             f"Bu kategorileri KULLANMA: {', '.join(yasak_kat) or 'yok'}. Odak karakter şunlar OLMASIN: {', '.join(yasak_kar) or 'yok'}. "
             f"Son bölümlerin olay örgüsünü, şakasını, final cümlesini ya da başlık kalıbını tekrar etme; her bölümde yeni bir nesne, yeni bir engel ve yeni bir çözüm olsun.")
    acik = '\n'.join(f'- {a}' for a in memory.get('acik_meseleler', [])) or '- (yok)'
    harita = ', '.join(memory.get('harita', [])[-30:]) or '(henüz yok)'
    rakip_txt = ''
    try:
        with open(os.path.join(paths.ROOT, 'state', 'rakip.json'), encoding='utf-8') as f:
            rk = json.load(f).get('icgoruler') or {}
        rakip_txt = ('\nPAZAR ARAŞTIRMASI (en çok izlenen animasyon Shortslarından çıkarılan GENEL teknikler; başka kanalların '
                     'karakterini, ismini, hikâyesini ASLA kullanma, sadece tekniği kendi evrenimize uygula):\n'
                     f"- Yazar notu: {rk.get('yazar_notu', '')}\n- Kanca teknikleri: {'; '.join(rk.get('kanca_teknikleri', [])[:5])}\n"
                     f"- Konu fırsatları: {'; '.join(rk.get('konu_firsatlari', [])[:6])}\n- Kaçınılacaklar: {'; '.join(rk.get('kacinilacaklar', [])[:4])}")
    except Exception:
        pass
    top = memory.get('en_cok_izlenen', [])
    top_txt = ('\nEN BAŞARILI BÖLÜMLER (izlenme + izleyiciyi tutma + abone; bu tarz hikâye, kanca, kategori ve karakterlere ağırlık ver, ama tekrar etme):\n'
               + '\n'.join(f'- {x}' for x in top[:5])) if top else ''
    zayif = memory.get('en_zayif', [])
    if zayif:
        top_txt += '\nEN ZAYIF BÖLÜMLER (bu tarzlardan uzak dur):\n' + '\n'.join(f'- {x}' for x in zayif[:3])
    dd = memory.get('donusum_dersleri') or {}
    if dd.get('iyi'):
        top_txt += ('\nABONE KAZANDIRAN BÖLÜMLER (izleyiciyi seriye bağlayan karakter/final tarzı; bu bağı güçlendir):\n'
                    + '\n'.join(f'- {x}' for x in dd['iyi'][:4]))
    if dd.get('kotu'):
        top_txt += '\nABONE KAZANDIRMAYAN BÖLÜMLER (bu kombinasyonlardan kaçın):\n' + '\n'.join(f'- {x}' for x in dd['kotu'][:3])
    if kind == 'uzun':
        fmt = """FORMAT: YATAY UZUN VİDEO (4-5 dakika). 6-8 sahne, toplam 55-80 replik, toplam yaklaşık 600-750 kelime.
Haftanın büyük macerası: yeni bir bölge, büyük bir problem, karakterlerin bir karar vermesi ve büyük bir final. Sahneler farklı mekânlarda geçebilir.
Shorts'ların tekrarı değil. İlk sahne yeni izleyiciye durumu anlatsın. Son sahnede yeni bölge haritaya işlensin."""
    else:
        fmt = ("""ÖNCELİKLİ KURAL (aşağıdaki uzunluk sınırlarını EZER) — DİKEY KISA SHORTS (20-25 saniye; izleyici sonuna kadar izlesin, tekrar izlesin). Tek sahne, 2-3 karakter,
4-6 replik, toplam 30-55 kelime. Tek bir olay: kanca -> tek deneme -> sürpriz sonuç. Ara açıklama ve yan şaka YOK.
Son an ilk anla bağlansın (izleyici başa sardığında akış devam ediyor gibi hissetsin).\n""" if KISA else "") + """FORMAT: DİKEY SHORTS (30-45 saniye). Tek sahne, 2-4 karakter (istersen benek de), 6-9 replik, toplam 55-95 kelime.
- 0-2 sn KANCA (rakip analizine göre en çok izlenen tekniktir): Bölüm OLAYIN TAM ORTASINDA başlar; giriş, selamlaşma, tanıtım YOK.
  İlk saniyede 'acilis_efekti' ile bir ölçek şoku olur (dev nesne düşer / dev el ya da pati uzanır / dev damla düşer) ve
  ilk replik buna verilen panik ya da şaşkınlık tepkisidir (en fazla 7 kelime, örn. "Kaçın! Dev bir düğme düşüyor!").
- KANAL VERİSİ (en yüksek izlenme oranı %85, diğerleri %30): İLK REPLİK karakterlerin O AN İÇİNE DÜŞTÜĞÜ somut bir çıkmazdır
  ("Dev menteşeye yapışıp kaldık ve ipimiz düştü!" gibi: mahsur kaldık / sıkıştık / düşüyoruz / kapandı). Bir hedef ya da hikâye
  bilgisiyle ("...ulaşmalıyız", "...keşfetmeliyiz") AÇMA; hedef, çıkmazdan kurtulma çabasının içinde kendiliğinden anlaşılsın.
  Sonra her replik bir öncekinin sonucu olsun (deneme -> ters gitti -> yeni fikir -> beklenmedik çözüm).
- DİYALOG AZ VE KISA: replikler en fazla 12 kelime; hikâye karakterlerin HAREKETLERİYLE ilerlesin, konuşma sadece destek olsun.
- MİZAH ÖLÇEK FARKINDAN: sıradan ev eşyalarını beklenmedik amaçla kullan (ataş tırmanma kancası, düğme kalkan, kürdan kürek).
- SÜRE: 35-50 saniye; hızlı tempo, her 3-5 saniyede bir yeni gelişme.
- ANLAMLI HİKÂYE (en önemli kural): Bölümün tek cümlelik net bir konusu olsun: "KİM, NEYİ, NEDEN istiyor ve önünde NE var?"
  Örnek: "Pire, Benek'i karşıdaki şeker küpünden kurtarmak istiyor ama arada lavabo gölü var."
  Yapı: 1) HEDEF ilk iki replikte belli olur. 2) ENGEL somut ve görseldir (dev nesne, su, rüzgâr, kedi). 3) İlk PLAN başarısız olur ya da ters gider.
  4) Karakterlerin farklı yetenekleri birleşir ve ÇÖZÜM bulunur (Bulut'un aracı, Nil'in ölçümü, Tuna'nın cesareti, Pire'nin küçüklüğü).
  5) SONUÇ: hedefe ulaşılır, öğrenilen ya da bulunan bir şey olur; son replik gülümseten bir ters köşe.
  Rastgele şakalar dizisi YAZMA; her replik hikâyeyi bir adım ilerletsin. Diyalog olan biteni anlatsın ki ses kapalı izleyen bile anlasın.
- Bölüm tek başına anlaşılır ve tatmin edici biter; ama sezon yolculuğunu bir adım ilerletir.
- SON REPLİK: ters köşe ya da sıcak bir an; tercihen action 'kameraya_bak'."""
    if kind == 'ana':
        tur = 'ANA YOLCULUK bölümü: sezon yolculuğunu bir adım ilerlet, kendi küçük maceranı bitir, sonunda merak bırak (end_card "Yarın: ..." ile).'
    elif kind == 'bagimsiz':
        tur = 'YAN MACERA: aynı bölgede, ana yolculuktan bağımsız tek bir olay (kategoriler: kurtarma, yarış, problem çözme, gizem, yeni canlı, doğal güç, mucit anı, başarısız plan, ters köşe, teknolojik keşif, Ela anı, kişisel macera). Son bölümlerde kullanılmamış bir kategori seç.'
    else:
        tur = 'UZUN VİDEO bölümü.'
    return f"""Sen "MİNİ DÜNYA" adlı Türkçe 2D animasyon macera dizisinin baş senaristisin. Süpürgeliğin arkasında yaşayan parmak boyundaki haritacılar Büyük Ev'i bölge bölge keşfediyor.

=== EVREN KİTABI ===
{evren}

=== SEZON: {plan.get('ad', '')} ===
{plan.get('ana_hikaye', '')}

=== ŞU ANA KADAR (son bölümler) ===
{recent_txt}

AÇIK MESELELER:
{acik}
HARİTAYA İŞLENMİŞ BÖLGELER: {harita}{sezon_txt}{top_txt}{cesit}{rakip_txt}

=== BU BÖLÜM ===
TÜR: {tur}
KONU: {brief}
{fmt}
{RULES_COMMON}
{extra}
JSON ŞEMASI:
{SCHEMA}
"""


CRITIC = """Aşağıda "MİNİ DÜNYA" için yazılmış bir bölüm var. Sen deneyimli bir çocuk-aile animasyonu yazarı ve editörsün.
Kontrol et ve gerekiyorsa DÜZELT:
1. Bölüm, diziyi hiç izlememiş biri için tek başına anlaşılıyor mu? İlk replik durumu anlatıyor mu?
1b. HİKÂYE ANLAMLI MI: Net bir hedef, somut bir engel, başarısız bir ilk deneme, karakter yetenekleriyle bulunan çözüm ve tatmin edici bir sonuç var mı? Bölümün konusunu tek cümleyle söyleyebiliyor musun? Yoksa hikâyeyi bu yapıya göre yeniden yaz; hikâyeyi ilerletmeyen replikleri çıkar.
2. Gerçekten eğlenceli mi? Son replik gülümsetiyor mu? Zayıf replikleri güçlendir.
2b. Aksiyon var mı? Yalnızca konuşan karakterler varsa en az bir hareketli an ekle (kos_sag/kos_sol/kac/carp/zipla). 'titre' en fazla 1 kez.
2c. Çocuklar dahil aile kitlesine uygun mu? Değilse düzelt.
3. Karakterler kişiliklerine sadık mı? Benek konuşmuyor mu?
3b. HAREKET: karakterler sabit mi duruyor? Repliklerin en az yarısında anlamlı bir hareket olsun (yuru_sag/yuru_sol, isaret, egil, zipla, kos_*, carp, kac).
4. GÜVENLİK: küfür, argo, hakaret, alay, etnik köken, ırk, din, milliyet, siyaset, ayrımcılık, şiddet, korku, alkol, sigara, gerçek marka/kişi KESİNLİKLE YOK. Varsa tamamen çıkar.
4b. Kurallar: sayılar yazıyla, replikler kısa, JSON şeması aynen korunuyor.
5. TEKRAR YOK: Son {n} bölüme (başlık, konu, şaka, final) benziyor mu? YouTube birbirinin tekrarı içeriği para kazanmaya kapatır; benziyorsa özgünleştir: {recent}
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
            sc['location'] = 'tezgah'
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
            if w == 'benek':
                errs.append('benek konuşmaz; ona replik yazma')
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
        if len(chars) > 5:
            errs.append('bir sahnede en fazla 5 karakter olabilir')
    if kind == 'uzun':
        if total_lines < 40:
            errs.append(f'uzun video için çok az replik ({total_lines}); en az 55 olmalı')
        if total_words < 420:
            errs.append(f'uzun video için çok az kelime ({total_words}); yaklaşık 650 olmalı')
    else:
        if len(ep['scenes']) > 1:
            ep['scenes'] = ep['scenes'][:1]
        lo, hi = (4, 7) if KISA else (5, 11)
        if total_lines < lo or total_lines > hi:
            errs.append(f'shorts için replik sayısı {total_lines}; ' + ('4-6' if KISA else '6-9') + ' olmalı')
        moving = sum(1 for sc in ep['scenes'] for ln in sc.get('lines', []) if ln.get('action', 'yok') not in ('yok', 'kameraya_bak'))
        if moving < max(2, total_lines // 3):
            errs.append(f'karakterler çok sabit: sadece {moving} replikte hareket var; en az yarısında hareket olsun')
        if total_words > (70 if KISA else 130):
            errs.append(f'shorts çok uzun ({total_words} kelime); en fazla ' + ('55' if KISA else '95') + ' olmalı')
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
    if kind != 'uzun' and ep.get('acilis_efekti') not in ('dusen_nesne', 'dev_el', 'dev_pati', 'dev_damla'):
        ep['acilis_efekti'] = ['dusen_nesne', 'dev_el', 'dev_pati', 'dev_damla'][sum(map(ord, ep.get('baslik', 'x'))) % 4]
    errs += safety_errors(ep)
    return errs


def _words(t):
    return set(w for w in re.findall(r'[a-zçğıöşü]+', str(t).replace('I', 'ı').replace('İ', 'i').lower()) if len(w) > 2)


def repetition_errors(ep, memory):
    """Son bölümlere fazla benzeyen başlık, konu ya da kategori tekrarını yakalar."""
    errs = []
    past = memory.get('bolumler', [])
    title = _words(ep.get('baslik', ''))
    for b in past[-60:]:
        pt = _words(b.get('baslik', ''))
        if title and pt and len(title & pt) / max(1, min(len(title), len(pt))) >= 0.67:
            errs.append(f"başlık eski bir bölüme çok benziyor: '{b.get('baslik')}'")
            break
    konu = _words(ep.get('konu', ''))
    for b in past[-30:]:
        pk = _words(b.get('konu', ''))
        if konu and pk and len(konu & pk) / max(1, len(konu | pk)) >= 0.5:
            errs.append(f"konu eski bir bölüme çok benziyor: '{b.get('konu')}'")
            break
    kat = str(ep.get('kategori', '')).strip()
    if kat and kat in [b.get('kategori') for b in past[-3:]]:
        errs.append(f"'{kat}' kategorisi son 3 bölümde kullanıldı; başka kategori seç")
    return errs


def write_episode(kind, brief, memory, plan, cfg, log=print):
    evren = open(os.path.join(paths.EVREN, 'evren.md'), encoding='utf-8').read()
    prompt = build_prompt(kind, brief, evren, memory, plan)
    ep, errs = None, ['başlamadı']
    for attempt in range(3):
        extra = '' if attempt == 0 else f"\nÖNCEKİ DENEMEDEKİ HATALAR (düzelt): {'; '.join(errs)}"
        ep = gemini_json(prompt + extra, cfg, log=log)
        errs = validate(ep, kind) + repetition_errors(ep, memory)
        if not errs:
            break
        log(f'  Senaryo hataları: {errs}')
    if errs:
        raise WriterError('Senaryo kurallara uymadı: ' + '; '.join(errs))
    if safety_errors(ep):
        raise WriterError('Güvenlik kontrolü: ' + '; '.join(safety_errors(ep)))
    if cfg['senaryo'].get('kalite_kontrol', True):
        recent = '; '.join(b['baslik'] for b in memory.get('bolumler', [])[-10:]) or 'yok'
        try:
            ep2 = gemini_json(CRITIC.format(n=10, recent=recent, ep=json.dumps(ep, ensure_ascii=False)), cfg, temperature=0.7, log=log)
            if not validate(ep2, kind) and not repetition_errors(ep2, memory):
                ep = ep2
                log('  Kalite kontrolden geçti (düzeltilmiş sürüm)')
            assert not safety_errors(ep)
        except Exception as e:
            log(f'  Kalite kontrol atlandı: {e}')
    return ep


def new_season_plan(season_no, memory, cfg, log=print):
    evren = open(os.path.join(paths.EVREN, 'evren.md'), encoding='utf-8').read()
    recent = '\n'.join(f"- {b['baslik']}: {b.get('ozet', '')}" for b in memory.get('bolumler', [])[-30:])
    prompt = f"""Sen "MİNİ DÜNYA" 2D animasyon macera dizisinin baş senaristisin.
EVREN KİTABI:
{evren}

ÖNCEKİ SEZONDAN OLANLAR:
{recent}

Sezon {season_no} için 14 günlük plan yaz. Sezon Büyük Ev'in yeni bir bölgesini (ör. banyo, salon, çalışma odası, çamaşırlık, balkon) keşfeder ve bir hedefe doğru ilerler.
Her gün bir alt bölge ve dört bölüm: sabah (ana yolculuk), aksam (ana yolculuk, sabahın devamı), oglen ve gece (aynı bölgede yan macera).
Ayrıca 2 pazar uzun videosu yaz (hafta1_pazar, hafta2_pazar). Sezonun bir ANA GİZEMİ olsun; her gün bir ipucu, 14. günde tatmin edici çözüm. Karakterler sezon boyunca gelişsin. Önceki sezondan bir merak ipi devam etsin; İlk Haritacı gizemi yavaş ilerlesin.
Küfür, hakaret, etnik köken, ırk, din, siyaset, şiddet, korku KESİNLİKLE yok.
Sadece JSON döndür:
{{"sezon": {season_no}, "ad": "...", "ana_hikaye": "...",
 "gizem": "Sezonun ana gizemi (izleyiciye soru olarak; ilk bölümde açıklanmaz)",
 "gizem_cozumu": "Gizemin cevabı (sadece 14. gün akşam bölümünde açıklanır) ve bir sonraki sezona açılan kapı",
 "karakter_yolculugu": {{"tuna": "sezon boyunca hatası ve öğrendiği ders", "nil": "...", "bulut": "...", "pire": "..."}},
 "gunler": [{{"gun": 1, "bolge": "...", "odak": "tuna|nil|bulut|pire", "sabah": "...", "oglen": "...", "aksam": "...", "gece": "...",
   "ipucu": "Bu gün ana bölümlerde bulunan gizem ipucu (ipuçları gün gün çözüme yaklaştırsın)"}}],
 "uzun": {{"hafta1_pazar": "...", "hafta2_pazar": "..."}}}}"""
    plan = gemini_json(prompt, cfg, log=log)
    if len(plan.get('gunler', [])) < 14:
        raise WriterError('Sezon planı eksik geldi')
    return plan


YASAK_EN = ['fuck', 'shit', 'bitch', 'damn', 'hell ', 'stupid', 'idiot', 'dumb', 'moron', 'shut up', 'kill', 'dead', 'blood',
            'gun', 'beer', 'wine', 'cigarette', 'god ', 'jesus', 'allah', 'church', 'mosque', 'election', 'president',
            'race ', 'racist', 'fat ', 'ugly']


def localize_en(ep, cfg, log=print):
    """Türkçe bölümü İngilizce kanala UYARLAR (kelime kelime çeviri değil): aynı sahne, karakter, hareket ve duygu."""
    src = {'baslik': ep.get('baslik'), 'kapak_yazisi': ep.get('kapak_yazisi'), 'end_card': ep.get('end_card'),
           'konu': ep.get('konu'), 'youtube': ep.get('youtube'),
           'scenes': [{'title': sc.get('title', ''), 'lines': [{'who': l['who'], 'text': l['text']} for l in sc['lines']]}
                      for sc in ep['scenes']]}
    prompt = f"""You adapt episodes of a Turkish 2D animated adventure series into natural, funny ENGLISH for the sister channel "MINI WORLD"
(tiny explorers living behind the baseboard map the "Big House"). Characters keep their names: Tuna (brave hasty leader), Nil (analytical
mapmaker, dry humor), Bulut (big gentle inventor), Pire (tiniest curious kid). Humans are called "the Giants".
Rules: adapt, don't translate word by word; jokes and wordplay must work in English; keep EXACTLY the same number of scenes and lines,
same order and same 'who'; each line max 12 words (16 in long videos); write numbers as words; family friendly: no insults, no slang swearing, no religion,
politics, ethnicity, violence, alcohol. kapak_yazisi = 3-6 word ALL-CAPS hook shown in the first second (e.g. "A GIANT SPONGE ATE OUR MAP!").
end_card = a short fun question for viewers to answer in comments. youtube.title max 70 chars, curiosity-driven, no emoji;
youtube.description 2-3 sentences ending with the same question; youtube.tags 6-10 English tags.
Return ONLY JSON with the same structure as the input:
{json.dumps(src, ensure_ascii=False)}"""
    for attempt in range(3):
        en = gemini_json(prompt, cfg, temperature=0.7, log=log)
        try:
            out = json.loads(json.dumps(ep, ensure_ascii=False))
            for k in ('baslik', 'kapak_yazisi', 'end_card', 'konu'):
                if en.get(k):
                    out[k] = str(en[k])
            out['youtube'] = en.get('youtube') or {}
            assert len(en['scenes']) == len(ep['scenes'])
            for sc, esc in zip(out['scenes'], en['scenes']):
                assert len(esc['lines']) == len(sc['lines'])
                sc['title'] = esc.get('title', '')
                for l, el in zip(sc['lines'], esc['lines']):
                    l['text'] = str(el['text']).strip()
            alltext = ' '.join([out['baslik'], out['kapak_yazisi'], out['end_card'], str(out['youtube'])] +
                               [l['text'] for sc in out['scenes'] for l in sc['lines']]).lower()
            bad = [w for w in YASAK_EN if re.search(r'(?<![a-z])' + re.escape(w), ' ' + alltext + ' ')]
            if bad:
                raise ValueError(f'unsafe words: {bad}')
            return out
        except Exception as e:
            log(f'  İngilizce uyarlama tekrar deneniyor: {e}')
    raise WriterError('İngilizce uyarlama başarısız')
