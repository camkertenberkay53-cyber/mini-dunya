"""M6 — Karakter ve dönem seçici.

Bir görsel niyetteki rolü (piyade, komutan...), dönemi, kamera mesafesini, eylemi ve taşınması gereken nesneyi
alır; Faz 3b'nin kabul edilmiş karakterleri arasından kurallara uyanları döndürür. Uyan yoksa uydurmaz: eksik raporlar.
Ret nedenleri her aday için kaydedilir (rapor ve hata ayıklama için).
"""
from __future__ import annotations

from motor.karakter import kalite as kalite_mod
from motor.uretim import animasyon_izni, veri


def eylem_animasyonlari(eylem: str) -> list[str]:
    return [a for a, k in veri.kural("animasyon")["animasyonlar"].items() if eylem in k.get("eylemler", [])]


def karakter_uygun_mu(ad: str, donem: str, mesafe: str, animasyon: str | None = None,
                     nesne: str | None = None, baglam: dict | None = None) -> tuple[bool, list[str]]:
    t = veri.takimlar().get(ad)
    if t is None:
        return False, [f"{ad}: derlenmiş takım yok"]
    h = []
    if veri.kit_donemi(t["kit"]) != donem:
        h.append(f"{ad}: dönemi {veri.kit_donemi(t['kit'])}, istenen {donem}")
    k = veri.kalite()["karakter"].get(ad)
    if k is None or k["sinif"] == "RED":
        h.append(f"{ad}: kalite sınıfı RED ya da kayıtsız")
    elif not kalite_mod.kullanilabilir_mi(k, mesafe):
        h.append(f"{ad}: {k['sinif']} sınıfı {mesafe} planda kullanılamaz")
    if nesne and nesne not in {e["id"] for e in t["takilanlar"]} and nesne not in {veri.ekipman_turu(e["id"]) for e in t["takilanlar"]}:
        h.append(f"{ad}: '{nesne}' taşımıyor")
    if animasyon:
        ok, n = animasyon_izni.teknik_durum(ad, animasyon)
        ok2, n2 = animasyon_izni.anlamsal_durum(ad, animasyon, baglam)
        h += n + n2
    return not h, h


def sec(rol: str, donem: str, mesafe: str, eylem: str | None = None, nesne: str | None = None,
        baglam: dict | None = None) -> dict:
    """Dönüş: {"uygun": [(ad, animasyon)], "red": {ad: [neden]}, "eksik": str|None}"""
    anims = eylem_animasyonlari(eylem) if eylem else [None]
    if eylem and not anims:
        return {"uygun": [], "red": {}, "eksik": f"'{eylem}' eylemine karşılık gelen animasyon kütüphanede yok"}
    uygun, red = [], {}
    for ad, t in sorted(veri.takimlar().items()):
        if t["rol"] != rol and not (rol == "isci_sivil" and t["rol"] == "isci_sivil"):
            continue
        for a in anims:
            ok, n = karakter_uygun_mu(ad, donem, mesafe, a, nesne, baglam)
            if ok:
                uygun.append((ad, a))
                break
            red.setdefault(ad, []).extend(n)
    eksik = None
    if not uygun:
        eksik = f"{donem} döneminde {mesafe} planda '{rol}' rolü" + (f", '{eylem}' eylemi" if eylem else "") + \
                (f", '{nesne}' nesnesiyle" if nesne else "") + " için uygun karakter yok"
    return {"uygun": uygun, "red": red, "eksik": eksik}
