"""M8 — Animasyon izin denetimi (beyaz liste).

Bir animasyon bir karakterde ancak şu üçü birden doğruysa kullanılır:
1. TEKNİK: o karakterde gerçekten ölçülmüş ve geçmiş olmalı (Faz 3b montaj testi ya da Faz 4 ek animasyon testi).
   Ölçülmemiş animasyon "yasak değil" diye kabul edilmez.
2. ANLAMSAL: animasyonun gerektirdiği ekipman/nesne/binek sahnede olmalı (kurallar/animasyon.yaml).
3. YER DEĞİŞTİRME: yürüyüş/koşu, ölçülmüş zemin hızıyla ilerletilmeli (ayak kayması olmasın).
"""
from __future__ import annotations

from motor.karakter import montaj as montaj_mod
from motor.uretim import veri


def teknik_durum(takim: str, anim: str) -> tuple[bool, list[str]]:
    m = veri.montaj()["takimlar"].get(takim)
    if m is None:
        return False, [f"{takim}: montaj testinde yok"]
    if not m["gecti"]:
        return False, [f"{takim}: montaj testinden kalmış (RED)"]
    t = veri.takimlar().get(takim, {})
    faz3_olculen = set(montaj_mod.ANIMASYONLAR) | (set(montaj_mod.ANIMASYON_SUVARI) if t.get("binek") else set())
    if anim in faz3_olculen:
        if anim in m.get("yasak_animasyon", {}):
            return False, [f"{anim}: {takim} için yasak (giysi taşması: {', '.join(m['yasak_animasyon'][anim])})"]
        return True, []
    ek = veri.animasyon_testi()
    if anim in ek.get("animasyonlar", []):
        r = ek["takimlar"].get(takim, {}).get(anim)
        if r is None:
            return False, [f"{anim}: {takim} ek animasyon testinde ölçülmemiş"]
        if not r["gecti"]:
            return False, [f"{anim}: {takim} ek animasyon testinden kaldı: " + "; ".join(r["hatalar"][:3])]
        if r.get("uyarilar"):
            return False, [f"{anim}: {takim} için uyarılı (" + "; ".join(r["uyarilar"][:2]) + ")"]
        return True, []
    return False, [f"{anim}: {takim} üzerinde hiç test edilmedi (beyaz listede değil)"]


def anlamsal_durum(takim: str, anim: str, baglam: dict | None = None) -> tuple[bool, list[str]]:
    """baglam: {"binek": bool, "nesneler": [..]} — sahnede neler var."""
    baglam = baglam or {}
    kural = veri.kural("animasyon")["animasyonlar"].get(anim)
    if kural is None:
        return False, [f"{anim}: kurallar/animasyon.yaml içinde tanımsız"]
    g = kural.get("gerekli") or {}
    h = []
    t = veri.takimlar()[takim]
    yuva_turleri: dict[str, set] = {}
    for e in t["takilanlar"]:
        yuva = "sag_el" if e["yuva"] == "sag_el_dik" else e["yuva"]
        yuva_turleri.setdefault(yuva, set()).add(veri.ekipman_turu(e["id"]))
    for yuva, turler in (g.get("yuva_turu") or {}).items():
        if not yuva_turleri.get(yuva, set()) & set(turler):
            h.append(f"{anim}: {takim} {yuva} yuvasında {'/'.join(turler)} taşımıyor")
    if g.get("binek") and not baglam.get("binek"):
        h.append(f"{anim}: binek gerekir (sahnede yok; at modeli karakterlerle test edilmedi)")
    if g.get("nesne") and g["nesne"] not in (baglam.get("nesneler") or []):
        h.append(f"{anim}: sahnede '{g['nesne']}' nesnesi gerekir")
    if g.get("alet"):
        h.append(f"{anim}: işçi aleti gerekir (kütüphanede yok; yönetim kararıyla alet gerektiren sahne üretilmez)")
    return not h, h


def zemin_hizi(anim: str) -> float:
    return float(veri.animasyon_olcum()[anim]["zemin_hizi_m_sn"])


def hiz_durumu(anim: str, hiz: float | None, olcek: float = 1.0, binek_: dict | None = None) -> tuple[bool, list[str]]:
    kural = veri.kural("animasyon")["animasyonlar"].get(anim, {})
    hiz = hiz or 0.0
    if binek_:   # atlı: binici yerinde oturur, at kendi ölçülen yürüyüş hızıyla ilerler
        from motor.uretim import binek as binek_mod
        olculen = binek_mod.hiz(binek_["id"], binek_["animasyon"])
        tol = veri.kural("animasyon")["hiz_toleransi"]
        if abs(hiz - olculen) > tol * max(olculen, 0.05) and not (olculen == 0 and hiz == 0):
            return False, [f"{anim}: atlı hız {hiz:.2f} m/sn, atın ölçülen yürüyüş hızı {olculen:.3f} m/sn (toynak kayar)"]
        return True, []
    if kural.get("tur") == "yer_degistiren":
        olculen = zemin_hizi(anim) * olcek   # ölçeklenmiş karakterin adımı da aynı oranda uzar
        tol = veri.kural("animasyon")["hiz_toleransi"]
        if abs(hiz - olculen) > tol * olculen:
            return False, [f"{anim}: hız {hiz:.2f} m/sn, ölçülen zemin hızı {olculen:.3f} m/sn (ayak kayar)"]
    elif hiz > 0:
        return False, [f"{anim}: yerinde animasyon ama karakter {hiz:.2f} m/sn kaydırılıyor (ayak kayar)"]
    return True, []


def izinli(takim: str, anim: str, baglam: dict | None = None, hiz: float | None = None, olcek: float = 1.0,
           binek_: dict | None = None) -> tuple[bool, list[str]]:
    sonuc, neden = True, []
    if binek_ and veri.takimlar().get(takim, {}).get("binek") != binek_.get("id"):
        return False, [f"{takim}: '{binek_.get('id')}' bineği olan bir takım değil"]
    for ok, n in (teknik_durum(takim, anim), anlamsal_durum(takim, anim, baglam), hiz_durumu(anim, hiz, olcek, binek_)):
        sonuc &= ok
        neden += n
    return sonuc, neden


def beyaz_liste(takim: str, baglam: dict | None = None) -> list[str]:
    """Bu karakterin bu bağlamda kullanılabilecek bütün animasyonları."""
    return [a for a in veri.kural("animasyon")["animasyonlar"]
            if teknik_durum(takim, a)[0] and anlamsal_durum(takim, a, baglam)[0]]
