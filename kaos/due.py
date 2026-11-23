"""Zamanı gelmiş ama henüz yapılmamış yayın slotunu bulur (sadece standart kütüphane).
Saatlik zamanlayıcı bunu çağırır; GitHub bir çalıştırmayı kaçırsa bile sonraki saatte telafi edilir."""
import datetime as dt
import json
import os
import sys

TR = dt.timezone(dt.timedelta(hours=3))
# Üretim ~25-30 dk sürer; tetikleme saatleri yükleme hedefinden önce.
# Türkçe yükleme hedefleri ~08:00, 11:30, 15:00, 18:30 (aralar 3,5 saat); tetikleme 3D render süresi kadar önce.
# Kanal verisi (20-22 Kasım): öncekine 2,5 saatten yakın ya da 21:00 sonrası yüklenen Shorts YouTube'un test havuzuna hiç
# girmedi (0-5 izlenme); aralıklı olanlar ~1.100-1.300 aldı. Bu yüzden: en az 3 saat ara, 21:00 sonrası Shorts yok,
# geciken slot sonrakine yığılmaz (kaçan slot atlanır).
SLOTS = [('aksam', 14.5)]  # 45 sn Omni Shorts ~15:00
YAYIN_GUNLERI = {2, 5}  # çarşamba, cumartesi (bütçe: kredi eklenince artırılır)
UZUN_AKTIF = False      # haftalık uzun video kredi eklenene kadar kapalı
MIN_ARA_SAAT = 3.0
SON_SHORTS_SAAT = 21.0
RAKIP_SAAT = 11.6  # pazartesi, kota yenilendikten sonra: haftalık rakip analizi + dönüşüm raporu
UZUN_SAAT = 8.5  # Pazar: uzun video ~90 dk sürer, 10:00 civarı yayında (uzun video için en iyi zaman pazar sabahı)


def due(now=None):
    now = now or dt.datetime.now(TR)
    h = now.hour + now.minute / 60
    root = os.path.join(os.path.dirname(__file__), '..', 'state')
    try:
        with open(os.path.join(root, 'hafiza.json'), encoding='utf-8') as f:
            st = json.load(f)
    except Exception:
        st = {}
    done = st.get('yapilan', {}).get(now.date().isoformat(), [])
    # 1) uzun video (pazar)
    if UZUN_AKTIF and now.weekday() == 6 and h >= UZUN_SAAT and 'uzun' not in done:
        return 'uzun'
    # 2) Shorts: geçmiş ve yapılmamış slotlardan EN SONUNCUSU (eskiler atlanır, yığılma olmaz)
    gecmis = [s for s, at in SLOTS if h >= at and s not in done]
    if gecmis and h < SON_SHORTS_SAAT and now.weekday() in YAYIN_GUNLERI:
        son = st.get('son_yukleme')
        ara_ok = True
        if son:
            try:
                ara_ok = (now - dt.datetime.fromisoformat(son)).total_seconds() >= MIN_ARA_SAAT * 3600
            except Exception:
                pass
        if ara_ok:
            return gecmis[-1]
    # 3) fikir havuzu (Gemini kotası 11:00 TR'de yenilenir)
    if h >= 11.25 and 'fikir' not in done:
        return 'fikir'
    # 4) pazartesi rakip analizi + rapor
    if now.weekday() == 0 and h >= RAKIP_SAAT:
        try:
            with open(os.path.join(root, 'rakip.json'), encoding='utf-8') as f:
                tarih = json.load(f).get('tarih')
        except Exception:
            tarih = None
        if tarih != now.date().isoformat() and 'rakip' not in done:
            return 'rakip'
    return 'none'


def next_wait(now=None):
    """Bir sonraki yayın saatine kaç saniye var (en fazla 5 saat 40 dk)."""
    now = now or dt.datetime.now(TR)
    best = None
    for add in range(0, 3):
        d = (now + dt.timedelta(days=add)).date()
        times = [11.25] + [at for _, at in SLOTS] + ([UZUN_SAAT] if d.weekday() == 6 else []) + ([RAKIP_SAAT] if d.weekday() == 0 else [])
        for at in times:
            t = dt.datetime(d.year, d.month, d.day, int(at), int(round((at % 1) * 60)), tzinfo=TR) + dt.timedelta(minutes=1)
            if t > now and (best is None or t < best):
                best = t
    # 3 saat kuralı yüzünden bekleyen slot varsa, ara dolduğu anda uyan
    try:
        with open(os.path.join(os.path.dirname(__file__), '..', 'state', 'hafiza.json'), encoding='utf-8') as f:
            son = json.load(f).get('son_yukleme')
        if son:
            t = dt.datetime.fromisoformat(son) + dt.timedelta(hours=MIN_ARA_SAAT, minutes=2)
            if t > now and t < best and t.hour + t.minute / 60 < SON_SHORTS_SAAT:
                best = t
    except Exception:
        pass
    return int(min((best - now).total_seconds(), 5 * 3600 + 40 * 60))


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'wait':
        print(next_wait())
    else:
        print(due())
