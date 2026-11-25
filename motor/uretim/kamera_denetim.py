"""Faz 5.3 — Kamera QC: bir çekimin kamera hareketi boyunca kadraj ve çarpışma kusurlarını ÖLÇER.

Kusurlar (kurallar/kamera.yaml → denetim):
- kamera zemine çok yakın
- kamera bir karakterin gövdesinin içinden geçiyor
- kadrajdaki bir karakter objektife çok yakın (kesik / bulanık ön plan)
- odak karakterin başı kadraj dışına taşıyor, ya da yanlardan taşıyor; uzak planda ayakları da kadrajda kalmalı
  (orta planda ayakların alt kenardan çıkması normal kadrajdır)
- bakış yönü ya da kamera konumu çok hızlı değişiyor
Planlayıcı kusurlu adayı reddedip sıradaki türe geçer; plan denetimi kalan kusuru hata sayar."""
from __future__ import annotations

import math

import numpy as np

from motor.uretim import kadraj, veri


def denetle(c: dict, odak_i: int, en_boy: float) -> list[str]:
    d = veri.kural("kamera")["denetim"]
    boy0 = veri.kural("mesafe")["karakter_boyu_m"]
    kam, sure, ks = c["kamera"], c["sure_sn"], c.get("karakterler", [])
    if not ks or not (0 <= odak_i < len(ks)):
        return []
    n = d["ornek"]
    tam_beden = kam.get("plan") == "uzak"
    kusur: set = set()
    onceki = None
    for j in range(n):
        t = j / (n - 1)
        k, h, fov = kadraj.kamera_ani(kam, t)
        if k[1] < d["zemin_en_az_m"]:
            kusur.add(f"kamera zemine çok yakın ({k[1]:.2f} m)")
        for i, ch in enumerate(ks):
            p = kadraj.karakter_konumu(ch, t * sure)
            boy = boy0 * ch.get("olcek", 1.0)
            if math.dist((k[0], k[2]), (p[0], p[2])) < d["govde_yaricap_m"] and k[1] < boy + 0.3:
                kusur.add(f"kamera {ch['takim']}#{i} gövdesinin içinden geçiyor")
                continue
            e = kadraj.ekran(k, h, fov, p + np.array([0, boy * 0.6, 0]), en_boy)
            if e and abs(e[0]) < 1.1 and abs(e[1]) < 1.1 and e[2] < d["objektif_en_az_m"]:
                kusur.add(f"{ch['takim']}#{i} objektife {e[2]:.2f} m (kesik/bulanık ön plan)")
        f = ks[odak_i]
        p = kadraj.karakter_konumu(f, t * sure)
        boy = boy0 * f.get("olcek", 1.0)
        for ad, nokta in (("ayağı", p), ("başı", p + np.array([0, boy, 0]))):
            e = kadraj.ekran(k, h, fov, nokta, en_boy)
            kenar = d["odak_kenar"]
            if e is None or abs(e[0]) > kenar or e[1] > kenar or (e[1] < -kenar and (ad == "başı" or tam_beden)):
                kusur.add(f"odak karakterin {ad} kadraj dışına taşıyor")
        if onceki is not None:
            dt = sure / (n - 1)
            v0, v1 = onceki[1] - onceki[0], h - k
            don = abs((math.degrees(math.atan2(v1[0], v1[2]) - math.atan2(v0[0], v0[2])) + 180) % 360 - 180) / dt
            hiz = float(np.linalg.norm(k - onceki[0])) / dt
            if don > d["en_cok_donus_der_sn"]:
                kusur.add(f"bakış dönüşü çok hızlı ({don:.0f}°/sn)")
            if hiz > d["en_cok_hiz_m_sn"]:
                kusur.add(f"kamera çok hızlı ({hiz:.1f} m/sn)")
        onceki = (k, h)
    return sorted(kusur)
