"""Tarihî görsel kaydı ve lisans kapısı (Faz-53A).

Kayıt: motor/varlik/tarihi_gorsel_kaydi.json — yalnızca METADATA; görsel dosyaları depoya girmez.
Dosya iki yoldan gelir (hibrit):
  - yerel_yol: kullanıcının koyduğu, doğruladığı dosya (mutlak yol)
  - indirme_url: CI iş akışının SHA-256 doğrulayarak ONBELLEK/tarihi_gorsel/ altına indirdiği dosya

Üretim kapısı (dogrulanmis_dosya): aşağıdakilerin HEPSİ sağlanmadan görsel hiçbir çekime girmez:
  - zorunlu alanlar dolu
  - lisans_turu ∈ IZINLI_LISANSLAR (CC0-1.0, PD-Old, PD-Art; atıf isteyen lisans yok)
  - lisans_dogrulandi == true VE onay.onaylayan + onay.tarih dolu (İNSAN onayı; motor bu alanları hiçbir zaman yazmaz)
  - durum != "red" (müze/arşivin fotoğraf üzerinde ayrı telif iddiası olan kopyalar 'red' kaydedilir)
  - dosya diskte ve SHA-256'sı kayıttakiyle aynı
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from motor import ayar

KAYIT = ayar.MOTOR / "varlik" / "tarihi_gorsel_kaydi.json"
INDIRME_KOK = ayar.ONBELLEK / "tarihi_gorsel"
IZINLI_LISANSLAR = ("CC0-1.0", "PD-Old", "PD-Art")
# Kullanıcı kararı (2026-11-26, otomatik Commons toplama): atıf isteyen CC-BY / CC-BY-SA lisansları da kabul edilir,
# ANCAK yalnızca 'atif' alanı (yazar, lisans, kaynak) doluysa — yayında açıklamaya yazılmak üzere. Atıfsız CC-BY reddedilir.
ATIFLI_LISANS_ONEKLERI = ("CC-BY",)
ZORUNLU_ALANLAR = ("gorsel_id", "kaynak_url", "kaynak_kurum", "eser_adi", "tarih", "bolge", "donem", "kultur",
                   "taraf_faction", "gorsel_turu", "uygun_sahne_turleri", "cozunurluk", "ozne_bilgisi",
                   "derinlik_uygunlugu", "lisans_turu", "kamu_mali_gerekcesi", "lisans_dogrulandi", "sha256")


class LisansHatasi(Exception):
    pass


YAN_DOSYA_KOK = ayar.REPO / "assets" / "tarihi_gorsel"   # <gorsel_id>.json yan dosyaları (görsel dosyası depoya girmez)


def kayit(yol: Path | None = None) -> dict:
    """Kayıt dosyası + (varsayılan kayıtta) assets/tarihi_gorsel/*.json yan dosyaları."""
    p = Path(yol or KAYIT)
    k = json.loads(p.read_text()) if p.exists() else {"gorseller": []}
    if yol is None and YAN_DOSYA_KOK.is_dir():
        k = dict(k, gorseller=list(k["gorseller"]) + [json.loads(j.read_text()) for j in sorted(YAN_DOSYA_KOK.glob("*.json"))])
    return k


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def dosya_yolu(g: dict) -> Path | None:
    if g.get("yerel_yol"):
        p = Path(g["yerel_yol"])
        return p if p.is_absolute() else ayar.REPO / p   # depoya göreli (assets/tarihi_gorsel/...) desteklenir
    if g.get("indirme_url"):
        ek = Path(g["indirme_url"].split("?")[0]).suffix.lower() or ".jpg"
        return INDIRME_KOK / f"{g['gorsel_id']}{ek}"
    return None


def denetle(g: dict, dosya_kontrol: bool = True) -> list[str]:
    """Bir kaydın üretime girmesini engelleyen nedenler (boş liste = geçer)."""
    h = [f"eksik alan {a}" for a in ZORUNLU_ALANLAR if a not in g or g[a] in (None, "", [])]
    lis = str(g.get("lisans_turu") or "")
    atif = g.get("atif") or {}
    atifli = lis.upper().startswith(ATIFLI_LISANS_ONEKLERI) and all(atif.get(a) for a in ("yazar", "lisans", "kaynak"))
    if lis not in IZINLI_LISANSLAR and not atifli:
        h.append(f"izin verilmeyen lisans {g.get('lisans_turu')!r} (izinli: {', '.join(IZINLI_LISANSLAR)}; "
                 f"CC-BY* yalnızca 'atif' alanıyla)")
    onay = g.get("onay") or {}
    insan = bool(onay.get("onaylayan")) and bool(onay.get("tarih"))
    # Kullanıcı kararı (2026-11-26): otomatik toplayıcının kayıtları da kabul edilir, ancak insan onayı gibi
    # gösterilmez — onay.kaynak_edinimi == "otomatik_toplayici" ve onay.insan_onayi == false açıkça yazılı olmalı.
    otomatik = onay.get("kaynak_edinimi") == "otomatik_toplayici" and onay.get("insan_onayi") is False and bool(onay.get("tarih"))
    if g.get("lisans_dogrulandi") is not True or not (insan or otomatik):
        h.append("lisans insan tarafından doğrulanmamış (lisans_dogrulandi + onay.onaylayan + onay.tarih; "
                 "ya da onay.kaynak_edinimi=otomatik_toplayici + insan_onayi=false + tarih)")
    if g.get("durum") == "red":
        h.append(f"reddedilmiş kayıt: {g.get('red_nedeni', 'neden yok')}")
    yol = dosya_yolu(g)
    if yol is None:
        h.append("ne yerel_yol ne indirme_url var")
    elif dosya_kontrol:
        if not yol.is_file():
            h.append(f"dosya yok: {yol}")
        elif g.get("sha256") and _sha(yol) != g["sha256"]:
            h.append("SHA-256 kayıttakiyle aynı değil")
    return h


def bul(gorsel_id: str, yol: Path | None = None) -> dict:
    for g in kayit(yol)["gorseller"]:
        if g.get("gorsel_id") == gorsel_id:
            return g
    raise LisansHatasi(f"{gorsel_id}: tarihî görsel kaydında yok")


def insan_onayli(g: dict) -> bool:
    o = g.get("onay") or {}
    return bool(o.get("onaylayan")) and bool(o.get("tarih")) and o.get("insan_onayi") is not False


def dogrulanmis_dosya(gorsel_id: str, yol: Path | None = None) -> tuple[Path, dict]:
    """Üretim kapısı: (dosya, kayıt) ya da LisansHatasi."""
    g = bul(gorsel_id, yol)
    h = denetle(g)
    if h:
        raise LisansHatasi(f"{gorsel_id}: " + "; ".join(h))
    return dosya_yolu(g), g


def kayit_denetle(yol: Path | None = None) -> list[str]:
    """Kayıt dosyasının kendi tutarlılığı (dosya varlığına bakmaz): tekrar eden kimlik, lisans dışı kayıt."""
    h, gorulen = [], set()
    for g in kayit(yol)["gorseller"]:
        i = g.get("gorsel_id")
        if i in gorulen:
            h.append(f"{i}: tekrar eden kimlik")
        gorulen.add(i)
        lis = str(g.get("lisans_turu") or "")
        if lis not in IZINLI_LISANSLAR and not lis.upper().startswith(ATIFLI_LISANS_ONEKLERI) and g.get("durum") != "red":
            h.append(f"{i}: izinli olmayan lisans ama 'red' işaretli değil")
    return h
