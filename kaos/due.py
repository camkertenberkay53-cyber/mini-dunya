"""Zamanı gelmiş ama henüz yapılmamış yayın slotunu bulur (sadece standart kütüphane).
Saatlik zamanlayıcı bunu çağırır; GitHub bir çalıştırmayı kaçırsa bile sonraki saatte telafi edilir."""
import datetime as dt
import json
import os
import sys

TR = dt.timezone(dt.timedelta(hours=3))
# Üretim ~25-30 dk sürer; tetikleme saatleri yükleme hedefinden önce.
# Türkçe yükleme hedefleri (rakip + sektör verisi): 10:00, 12:30, 16:00, 18:30 — 21:00 sonrası en zayıf dilim.
SLOTS = [('sabah', 9.5), ('oglen', 12.0), ('aksam', 15.5), ('gece', 18.0)]
UZUN_SAAT = 8.5  # Pazar: uzun video ~90 dk sürer, 10:00 civarı yayında (uzun video için en iyi zaman pazar sabahı)


def due(now=None):
    now = now or dt.datetime.now(TR)
    h = now.hour + now.minute / 60
    try:
        with open(os.path.join(os.path.dirname(__file__), '..', 'state', 'hafiza.json'), encoding='utf-8') as f:
            st = json.load(f)
    except Exception:
        st = {}
    done = st.get('yapilan', {}).get(now.date().isoformat(), [])
    cands = []
    if now.weekday() == 6:
        cands.append(('uzun', UZUN_SAAT))
    cands += SLOTS
    for slot, at in sorted(cands, key=lambda x: x[1]):
        if h >= at and slot not in done:
            return slot
    return 'none'


def next_wait(now=None):
    """Bir sonraki yayın saatine kaç saniye var (en fazla 5 saat 40 dk)."""
    now = now or dt.datetime.now(TR)
    best = None
    for add in range(0, 3):
        d = (now + dt.timedelta(days=add)).date()
        times = [at for _, at in SLOTS] + ([UZUN_SAAT] if d.weekday() == 6 else [])
        for at in times:
            t = dt.datetime(d.year, d.month, d.day, int(at), int(round((at % 1) * 60)), tzinfo=TR) + dt.timedelta(minutes=1)
            if t > now and (best is None or t < best):
                best = t
    return int(min((best - now).total_seconds(), 5 * 3600 + 40 * 60))


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'wait':
        print(next_wait())
    else:
        print(due())
