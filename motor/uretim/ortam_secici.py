"""M7 — Ortam ve varlık seçici: arazi ve ışık hazır ayarı, dönem çevre varlıkları.

Çevre varlığı yalnızca kendi döneminde, kalite sınıfının izin verdiği mesafede ve lisansı kayıtlıysa kullanılır.
Tarih güveni 'belirsiz' ya da 'tartismali' olan varlık planda 'temsili: true' olmadan kullanılamaz.
"""
from __future__ import annotations

from motor.karakter import kalite as kalite_mod
from motor.uretim import veri

TEMSILI_GEREKEN = {"belirsiz", "tartismali"}


def arazi_var_mi(ad: str) -> bool:
    return ad in veri.kural("arazi")["araziler"]


def isik_var_mi(ad: str) -> bool:
    return ad in veri.kural("arazi")["isiklar"]


def cevre_uygun_mu(pid: str, donem: str, mesafe: str, temsili: bool = False) -> tuple[bool, list[str]]:
    p = veri.parca(pid)
    if p is None or p.get("kategori") != "cevre":
        return False, [f"{pid}: kayıtlı çevre varlığı değil"]
    h = []
    if donem not in p.get("donem", []):
        h.append(f"{pid}: dönemi {p.get('donem')}, istenen {donem}")
    k = veri.kalite()["ekipman"].get(pid)
    if k is None or k["sinif"] == "RED":
        h.append(f"{pid}: kalite kaydı yok ya da RED")
    elif not kalite_mod.kullanilabilir_mi(k, mesafe):
        h.append(f"{pid}: {k['sinif']} sınıfı {mesafe} planda kullanılamaz")
    if p.get("tarih", {}).get("guven") in TEMSILI_GEREKEN and not temsili:
        h.append(f"{pid}: tarih güveni '{p['tarih']['guven']}'; 'temsili' işareti olmadan kullanılamaz")
    return not h, h


def donem_cevreleri(donem: str) -> list[str]:
    return sorted(pid for pid, p in veri.ekipman_katalogu()["parcalar"].items()
                  if p.get("kategori") == "cevre" and donem in p.get("donem", []))
