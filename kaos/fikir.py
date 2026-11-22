"""Sonsuz Hikâye Fikir Motoru.
Günde bir kez (kanal başına) 30 fikir üretir, ikinci bir Gemini çağrısıyla geçmiş fikirlere MANTIK düzeyinde
benzerliği kontrol edip puanlar ve her yayın slotu için en iyi fikri seçer. Hata olursa üretim normal brief ile sürer."""
import json

from .writer import gemini_json, LOCATIONS

NESNELER = ['pirinç', 'makarna', 'ekmek kırıntısı', 'kaşık', 'çatal', 'pipet', 'sünger', 'buz küpü', 'plastik kap',
            'şişe kapağı', 'peçete', 'çay poşeti', 'şeker', 'un', 'su damlası', 'düğme', 'mıknatıs', 'pil', 'kablo',
            'fırça', 'ataş', 'kürdan', 'lastik bant', 'yumurta kabuğu', 'zeytin', 'bal', 'tuzluk', 'kibrit kutusu',
            'iplik makarası', 'yapışkan not', 'bozuk para', 'oyuncak bilye', 'mantar tıpa', 'çay kaşığı', 'diş macunu kapağı']
TEHLIKELER = ['ani su akışı', 'büyük bir titreşim', 'kapının kapanması', 'çekmecenin açılması', 'buzun erimesi',
              'yiyeceklerin düşmesi', 'dev bir elin yaklaşması', 'ışığın kapanması', 'süpürge', 'evcil hayvanın yaklaşması',
              'beklenmedik sıcaklık', 'kaygan yüzey', 'büyük bir nesnenin yuvarlanması', 'rüzgâr/vantilatör', 'yapışkan bir sıvı']
MEKANIZMALAR = ['keşif', 'kurtarma', 'kaçış', 'yanlış anlaşılma', 'hata', 'yarış', 'gizli bölge', 'yeni icat', 'kaybolma',
                'hayatta kalma', 'takım çalışması', 'beklenmedik dostluk', 'başarısız plan', 'ters köşe', 'zamanla yarış']
SLOTLAR = ('sabah', 'oglen', 'aksam', 'gece')


def _parmak_izi(f):
    return {k: f.get(k, '') for k in ('nesne', 'tehlike', 'mekanizma', 'cozum', 'final_turu', 'ilk_saniye', 'ana_karakter', 'mekan')}


def _uret(gun_brief, gecmis, harici, rakip, lang, cfg, log):
    hedef = 'İngilizce kardeş kanal (Mini World)' if lang == 'en' else 'Türkçe ana kanal (Mini Dünya)'
    prompt = f"""Sen "Mini Dünya" 2D animasyon dizisinin fikir motorusun ({hedef}). Süpürgeliğin arkasında yaşayan parmak boyundaki
haritacılar Büyük Ev'i keşfediyor. Karakterler: Tuna (cesur, lider, risk alır), Nil (hesapçı, planlı), Bulut (mucit), Pire (meraklı,
istemeden olay başlatır), Benek (uğur böceği, konuşmaz, özel anlarda yardım eder). Aile dostu, 7-45 yaş; şiddet, korku, küfür, din,
siyaset, etnik köken YOK.

BUGÜNÜN SEZON PLANI (her slot için bölüm türü ve bölge):
{json.dumps(gun_brief, ensure_ascii=False)}

KULLANILABİLECEK MEKÂNLAR (sadece bunlar): {', '.join(LOCATIONS)}
NESNE HAVUZU: {', '.join(NESNELER)}
TEHLİKE HAVUZU: {', '.join(TEHLIKELER)}
HİKÂYE MEKANİZMALARI: {', '.join(MEKANIZMALAR)}
{('PAZAR ARAŞTIRMASI (genel teknikler, kopyalama yok): ' + rakip) if rakip else ''}

DAHA ÖNCE KULLANILAN FİKİRLER (bunlara mantık olarak benzeme: aynı nesne+problem, aynı çözüm, aynı final, aynı açılış YOK):
{json.dumps(gecmis[-60:], ensure_ascii=False)}
{('BUGÜN DİĞER KANALDA KULLANILAN FİKİRLER (bunlardan da tamamen farklı ol): ' + json.dumps(harici, ensure_ascii=False)) if harici else ''}

Görev: 30 FARKLI hikâye fikri üret (her slot için 7-8 tane; 'slot' alanı sabah|oglen|aksam|gece). Her fikir en az İKİ unsuru
yeni bir kombinasyonla birleştirsin (ör. bir nesne + beklenmedik tehlike, bir karakter özelliği + başarısız plan, bir keşif + zaman baskısı,
bir icat + komik sonuç). Ana yolculuk slotları (sabah, aksam) sezon planındaki bölgeye ve olaya uysun.
Sadece JSON döndür: {{"fikirler": [{{"slot": "sabah", "ad": "...", "ana_karakter": "tuna|nil|bulut|pire", "mekan": "...",
"nesne": "...", "tehlike": "...", "mekanizma": "...", "ilk_saniye": "ilk 1 saniyede ekranda olan görsel olay",
"problem": "...", "surpriz": "...", "cozum": "...", "final": "...", "final_turu": "tatmin|komik|sasirtici|merak"}}]}}"""
    d = gemini_json(prompt, cfg, temperature=1.1, log=log)
    return [f for f in d.get('fikirler', []) if isinstance(f, dict) and f.get('slot') in SLOTLAR]


def _sec(fikirler, gecmis, harici, cfg, log):
    prompt = f"""Sen bir YouTube Shorts animasyon yapımcısı ve editörsün. Aşağıdaki aday fikirleri değerlendir.
GEÇMİŞ FİKİRLER (bunlara HİKÂYE MANTIĞI olarak benzeyen adayları reddet; sadece kelime değil: aynı nesne+aynı problem,
aynı çözüm yolu, aynı final, aynı olay sırası, aynı açılış benzer sayılır):
{json.dumps(gecmis[-60:] + (harici or []), ensure_ascii=False)}

ADAYLAR (indeks sırasıyla):
{json.dumps([dict(i=i, **f) for i, f in enumerate(fikirler)], ensure_ascii=False)}

Her aday için puan ver (0-10): yenilik, izlenme_potansiyeli (ilk saniye ne kadar durdurucu, tek cümlede anlaşılır mı, sessiz
izlenince anlaşılır mı), uygunluk (aile dostu ve evrene uygun). Benzerse reddet. Sonra her slot (sabah, oglen, aksam, gece) için
reddedilmemiş en iyi adayı seç; seçilen dört fikir de birbirinden farklı olsun (farklı nesne, mekanizma, ana karakter).
Sadece JSON döndür: {{"puanlar": [{{"i": 0, "yenilik": 0, "izlenme_potansiyeli": 0, "uygunluk": 0, "red": "benzerse kısa neden, değilse boş"}}],
"secim": {{"sabah": 0, "oglen": 0, "aksam": 0, "gece": 0}}}}"""
    return gemini_json(prompt, cfg, temperature=0.3, log=log)


def gunun_fikirleri(st, plan, day, today, cfg, lang='tr', harici=None, log=print):
    """Bugünün slot -> fikir eşlemesi (önbellekli: günde kanal başına 2 Gemini çağrısı)."""
    havuz = st.setdefault('fikir_havuzu', {}).setdefault(lang, {})
    key = today.isoformat()
    if key in havuz:
        return havuz[key]
    rows = (plan or {}).get('gunler', [])
    row = rows[day - 1] if 0 < day <= len(rows) else {}
    gun_brief = {s: row.get(s, '') for s in SLOTLAR}
    gun_brief['bolge'] = row.get('bolge', '')
    gecmis = st.setdefault('fikir_gecmisi', {}).setdefault(lang, [])
    if not gecmis:  # ilk çalıştırma: yayınlanmış bölümlerin konularıyla başlat
        src = st.get('bolumler' if lang == 'tr' else 'en_bolumler', [])
        gecmis.extend({'konu': b.get('konu') or b.get('baslik'), 'mekan': b.get('mekan', ''), 'ana_karakter': b.get('ana_karakter', '')}
                      for b in src[-40:])
    rakip = ''
    try:
        import os
        from . import paths
        with open(os.path.join(paths.ROOT, 'state', 'rakip.json'), encoding='utf-8') as f:
            ins = json.load(f).get('icgoruler') or {}
        rakip = '; '.join((ins.get('kanca_teknikleri') or [])[:3] + (ins.get('konu_firsatlari') or [])[:4])
    except Exception:
        pass
    fikirler = _uret(gun_brief, gecmis, harici, rakip, lang, cfg, log)
    if len(fikirler) < 8:
        raise ValueError(f'fikir motoru yeterli fikir üretemedi ({len(fikirler)})')
    sec = _sec(fikirler, gecmis, harici, cfg, log)
    puan = {p.get('i'): p for p in sec.get('puanlar', []) if isinstance(p, dict)}
    secim = {}
    for slot in SLOTLAR:
        i = (sec.get('secim') or {}).get(slot)
        if not isinstance(i, int) or not (0 <= i < len(fikirler)) or (puan.get(i, {}).get('red') or '').strip():
            aday = [(j, f) for j, f in enumerate(fikirler) if f['slot'] == slot and not (puan.get(j, {}).get('red') or '').strip()]
            aday.sort(key=lambda x: -sum(puan.get(x[0], {}).get(k, 0) or 0 for k in ('yenilik', 'izlenme_potansiyeli', 'uygunluk')))
            i = aday[0][0] if aday else None
        if i is not None:
            f = dict(fikirler[i])
            p = puan.get(i, {})
            f['yenilik_puani'] = p.get('yenilik')
            f['izlenme_potansiyeli'] = p.get('izlenme_potansiyeli')
            secim[slot] = f
    red = sum(1 for p in puan.values() if (p.get('red') or '').strip())
    log(f'  Fikir motoru ({lang}): {len(fikirler)} fikir, {red} tanesi tekrar/benzerlik nedeniyle reddedildi, seçilen: '
        + ' | '.join(f"{s}: {f.get('ad')}" for s, f in secim.items()))
    havuz[key] = secim
    for k in sorted(havuz)[:-3]:
        havuz.pop(k, None)
    return secim


def brief_ek(f):
    if not f:
        return ''
    return ("\n\nBU BÖLÜMÜN FİKRİ (fikir motoru 30 aday arasından seçti; bu fikre sadık kal, detayları ve diyalogları sen geliştir): "
            + json.dumps({k: f.get(k) for k in ('ad', 'ana_karakter', 'mekan', 'nesne', 'tehlike', 'mekanizma', 'ilk_saniye',
                                                 'problem', 'surpriz', 'cozum', 'final', 'final_turu')}, ensure_ascii=False))


def kaydet(st, f, lang='tr'):
    if f:
        g = st.setdefault('fikir_gecmisi', {}).setdefault(lang, [])
        g.append(_parmak_izi(f))
        st['fikir_gecmisi'][lang] = g[-150:]
