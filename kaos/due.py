"""Zamanı gelmiş ama henüz yapılmamış yayın slotunu bulur (sadece standart kütüphane).
Saatlik zamanlayıcı bunu çağırır; GitHub bir çalıştırmayı kaçırsa bile sonraki saatte telafi edilir."""
import datetime as dt
import json
import os
import sys

TR = dt.timezone(dt.timedelta(hours=3))
SLOTS = [('sabah', 8.5), ('oglen', 13.5), ('aksam', 19.5), ('gece', 21.5)]


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
        cands.append(('uzun', 18.0))
    cands += SLOTS
    for slot, at in sorted(cands, key=lambda x: x[1]):
        if h >= at and slot not in done:
            return slot
    return 'none'


if __name__ == '__main__':
    print(due())
