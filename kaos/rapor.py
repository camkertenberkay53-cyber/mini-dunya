"""Abone Dönüşüm Raporu (haftalık toplantı için).
Her Shorts'u 4 sınıfa ayırır:
  A: çok izlenen + çok abone   -> formülü koru, devamını yap
  B: çok izlenen + az abone    -> izlenme var ama karakter/seri bağı zayıf; final ve seri çağrısı güçlendirilmeli
  C: az izlenen + yüksek dönüşüm -> içerik iyi, açılış/başlık zayıf; yeniden paketlenebilir
  D: az izlenen + az abone     -> formül bırakılır
Ölçüt: 1.000 izlenmede kazanılan abone. Analytics verisi yoksa tahmin yapmaz, 'veri yok' yazar.
Gemini kullanmaz (kota harcamaz)."""
import datetime as dt
import json
import os
import statistics

from . import paths


def _sinif(b, med_izl, med_don):
    cok = b['izlenme'] >= med_izl
    iyi = b['donusum'] >= med_don and b['abone'] > 0
    return 'A' if cok and iyi else 'B' if cok else 'C' if iyi else 'D'


def hesapla(bolumler, bugun=None):
    bugun = bugun or dt.date.today().isoformat()
    # en az 2 günlük videolar (Analytics 24-48 saat gecikir)
    sinir = (dt.date.fromisoformat(bugun) - dt.timedelta(days=2)).isoformat()
    olc, eksik = [], []
    for b in bolumler:
        if not b.get('video_id') or b.get('tarih', '9') > sinir or b.get('izlenme') is None:
            continue
        if b.get('abone_kazanci') is None:
            eksik.append(b.get('baslik', '?'))
            continue
        izl = int(b['izlenme'] or 0)
        ab = int(b['abone_kazanci'] or 0)
        if izl < 100:  # oran anlamsız (örneklem çok küçük)
            continue
        olc.append(dict(no=b.get('no'), baslik=b.get('baslik', ''), tarih=b.get('tarih'), slot=b.get('slot'), tur=b.get('tur'),
                        izlenme=izl, abone=ab, donusum=round(ab * 1000 / izl, 2) if izl else 0.0,
                        izleme_yuzdesi=b.get('izleme_yuzdesi'), kategori=b.get('kategori', ''), mekan=b.get('mekan', ''),
                        ana_karakter=b.get('ana_karakter', ''), final_turu=b.get('final_turu', ''), format=b.get('format', 'normal'), boya='boyali' if b.get('boya') else 'cizim',
                        yonetmen=(b.get('yonetmen') or {}).get('toplam')))
    if not olc:
        return {'tarih': bugun, 'durum': 'veri yok', 'eksik': eksik[:20], 'videolar': []}
    med_izl = statistics.median(x['izlenme'] for x in olc)
    med_don = statistics.median(x['donusum'] for x in olc)
    for x in olc:
        x['sinif'] = _sinif(x, med_izl, med_don)
    top_izl = sum(x['izlenme'] for x in olc)
    top_ab = sum(x['abone'] for x in olc)

    def grup(alan):
        g = {}
        for x in olc:
            k = x.get(alan) or '?'
            d = g.setdefault(k, {'video': 0, 'izlenme': 0, 'abone': 0})
            d['video'] += 1
            d['izlenme'] += x['izlenme']
            d['abone'] += x['abone']
            if x.get('izleme_yuzdesi') is not None:
                d.setdefault('_y', []).append(x['izleme_yuzdesi'])
        for d in g.values():
            d['ort_izlenme'] = round(d['izlenme'] / d['video'])
            d['donusum'] = round(d['abone'] * 1000 / d['izlenme'], 2) if d['izlenme'] else 0.0
            y = d.pop('_y', [])
            d['izleme_yuzdesi'] = round(sum(y) / len(y), 1) if y else None
        return dict(sorted(g.items(), key=lambda kv: -kv[1]['donusum']))

    # yönetmen puanı ile izlenme arasındaki ilişki (kalibrasyon için)
    yp = [(x['yonetmen'], x['izlenme']) for x in olc if x.get('yonetmen') is not None]
    kal = None
    if len(yp) >= 5:
        try:
            kal = round(statistics.correlation([a for a, _ in yp], [b for _, b in yp]), 2)
        except Exception:
            kal = None
    return {'tarih': bugun, 'durum': 'tamam', 'video_sayisi': len(olc), 'toplam_izlenme': top_izl, 'toplam_abone': top_ab,
            'genel_donusum': round(top_ab * 1000 / top_izl, 2) if top_izl else 0.0,
            'medyan_izlenme': med_izl, 'medyan_donusum': med_don,
            'siniflar': {s: [x for x in sorted(olc, key=lambda x: -x['donusum']) if x['sinif'] == s] for s in 'ABCD'},
            'kategori': grup('kategori'), 'karakter': grup('ana_karakter'), 'mekan': grup('mekan'),
            'final_turu': grup('final_turu'), 'slot': grup('slot'), 'format': grup('format'), 'boya': grup('boya'),
            'yonetmen_izlenme_korelasyonu': kal, 'eksik': eksik[:20], 'videolar': olc}


ACIKLAMA = {'A': 'Çok izlenen + çok abone → formülü koru, devamını yap',
            'B': 'Çok izlenen + az abone → final ve seri bağı güçlendirilmeli',
            'C': 'Az izlenen + yüksek dönüşüm → açılış/başlık zayıf, yeniden paketlenebilir',
            'D': 'Az izlenen + az abone → bu formül bırakılır'}


def metin(r):
    if r['durum'] != 'tamam':
        s = f"# Abone Dönüşüm Raporu — {r['tarih']}\n\nVeri yok: Analytics abone verisi henüz gelmedi."
        if r.get('eksik'):
            s += f" ({len(r['eksik'])} video bekliyor)"
        return s + '\n'
    L = [f"# Abone Dönüşüm Raporu — {r['tarih']}", '',
         f"- Ölçülen video: {r['video_sayisi']} | toplam izlenme {r['toplam_izlenme']:,} | kazanılan abone {r['toplam_abone']}",
         f"- **1.000 izlenmede abone: {r['genel_donusum']}** (medyan video: {r['medyan_donusum']})", '']
    for s in 'ABCD':
        v = r['siniflar'][s]
        L.append(f"## {s} sınıfı ({len(v)}) — {ACIKLAMA[s]}")
        for x in v[:6]:
            L.append(f"- {x['baslik']} — {x['izlenme']:,} izlenme, +{x['abone']} abone ({x['donusum']}/1000)"
                     + (f", izleme %{x['izleme_yuzdesi']}" if x.get('izleme_yuzdesi') is not None else '')
                     + (f", yönetmen {x['yonetmen']}" if x.get('yonetmen') is not None else ''))
        L.append('')
    for alan, ad in (('karakter', 'Odak karakter'), ('kategori', 'Kategori'), ('mekan', 'Mekân'),
                     ('final_turu', 'Final türü'), ('slot', 'Yayın saati'), ('format', 'Format (A/B)'), ('boya', 'Arka plan (A/B)')):
        L.append(f"## {ad} bazında dönüşüm")
        for k, d in list(r[alan].items())[:8]:
            L.append(f"- {k}: {d['video']} video, ort. {d['ort_izlenme']:,} izlenme, {d['donusum']}/1000 abone"
                     + (f", izlenme oranı %{d['izleme_yuzdesi']}" if d.get('izleme_yuzdesi') is not None else ''))
        L.append('')
    k = r.get('yonetmen_izlenme_korelasyonu')
    L.append('## Yönetmen kalibrasyonu')
    L.append(f"- Yönetmen puanı ↔ izlenme korelasyonu: {k}" if k is not None
             else '- Henüz yeterli yönetmen puanlı video yok (en az 5 gerekli).')
    if r.get('eksik'):
        L.append(f"\nAbone verisi bekleyen {len(r['eksik'])} video var.")
    return '\n'.join(L) + '\n'


def yazdir_ozet(r, st):
    """Senaryo yazarına gidecek kısa ders (A sınıfının ortak noktaları, D'den kaçınma)."""
    if r['durum'] != 'tamam':
        return
    iyi = r['siniflar']['A'] + r['siniflar']['C']
    kotu = r['siniflar']['D']
    st['donusum_dersleri'] = {
        'tarih': r['tarih'], 'genel': r['genel_donusum'],
        'iyi': [f"{x['baslik']} (odak {x['ana_karakter']}, {x['kategori']}, final {x['final_turu']})" for x in iyi[:4]],
        'kotu': [f"{x['baslik']} (odak {x['ana_karakter']}, {x['kategori']}, final {x['final_turu']})" for x in kotu[:3]]}


def main():
    from .main import load_state, save_state, update_stats, log
    st = load_state()
    update_stats(st, log=log)
    r = hesapla(st.get('bolumler', []))
    yazdir_ozet(r, st)
    save_state(st)
    os.makedirs(paths.STATE, exist_ok=True)
    with open(os.path.join(paths.STATE, 'rapor.json'), 'w', encoding='utf-8') as f:
        json.dump(r, f, ensure_ascii=False, indent=1)
    t = metin(r)
    try:
        with open(os.path.join(paths.STATE, 'rakip.json'), encoding='utf-8') as f:
            tf = (json.load(f).get('icgoruler') or {}).get('trend_firsatlari') or []
        if tf:
            t += '\n## Bu haftanın trend fırsatları (puana göre)\n' + '\n'.join(
                f"- [{x.get('puan')}] {x.get('trend', '')} → {x.get('mini_dunya_uyarlamasi', '')} (risk: {x.get('risk', '?')})"
                for x in sorted([x for x in tf if isinstance(x, dict)], key=lambda x: -float(x.get('puan') or 0))) + '\n'
    except Exception:
        pass
    with open(os.path.join(paths.STATE, 'rapor.md'), 'w', encoding='utf-8') as f:
        f.write(t)
    print(t)


if __name__ == '__main__':
    main()
