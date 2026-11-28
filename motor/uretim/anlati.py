"""Anlatı yapısı denetimi.

Shorts: güçlü açılış (ölçülen süre), amaç sırası, sadelik (kurallar/shorts.yaml) — davranışı değişmez.
Uzun (Faz-62c): bölüm yapısı, kronolojik rol sırası, cümle uzunluğu, açılış kancası ve tekrar/yapay uzatma
yasağı (kurallar/uzun.yaml). denetle() senaryo biçimine göre doğru denetimi seçer."""
from __future__ import annotations

import re

from motor.uretim import veri


def kanca_merak_isareti(metin: str) -> list[str]:
    k = veri.kural("shorts")["kanca"]["merak_isaretleri"]
    bulunan = []
    if k.get("rakam") and re.search(r"\d", metin):
        bulunan.append("rakam")
    if k.get("soru") and "?" in metin:
        bulunan.append("soru")
    kelimeler = set(re.findall(r"\w+", metin.lower()))
    bulunan += [f"'{w}'" for w in k.get("kelimeler", []) if w in kelimeler]
    return bulunan


def shorts_denetle(senaryo: dict, sureler: dict) -> tuple[list[str], dict]:
    """sureler: seslendirme.olc() çıktısı. Dönüş: (hatalar, ölçümler)."""
    k = veri.kural("shorts")
    h, o = [], {}
    if senaryo["format"] != "shorts":
        return [f"senaryo biçimi '{senaryo['format']}': Shorts denetimi uygulanamaz"], o
    if not senaryo.get("ana_fikir"):
        h.append("Shorts senaryosunun tek bir 'ana_fikir' cümlesi olmalı")
    cs = senaryo["cumleler"]
    if len(cs) > k["cumle"]["en_cok"]:
        h.append(f"{len(cs)} cümle; Shorts için en çok {k['cumle']['en_cok']}")
    sira = k["amac_sirasi"]
    onceki = -1
    for c in cs:
        if "amac" not in c:
            h.append(f"{c['id']}: anlatı amacı (amac) yok")
            continue
        i = sira.index(c["amac"])
        if i < onceki:
            h.append(f"{c['id']}: '{c['amac']}' amacı anlatı sırasını bozuyor")
        onceki = max(onceki, i)
        n = len(re.findall(r"\w+", c["metin"]))
        if n > k["cumle"]["en_cok_kelime"]:
            h.append(f"{c['id']}: {n} kelime; en çok {k['cumle']['en_cok_kelime']}")
    if cs[0]["id"] != senaryo["kanca"] or cs[0].get("amac") != "kanca":
        h.append("kanca ilk cümle olmalı ve amacı 'kanca' olmalı")
    if cs[-1]["id"] != senaryo["final"] or cs[-1].get("amac") != "final":
        h.append("final son cümle olmalı ve amacı 'final' olmalı")
    kanca = cs[0]
    ks = sureler[kanca["id"]]["sure_sn"]
    o["kanca_sure_sn"] = ks
    o["kanca_merak_isaretleri"] = kanca_merak_isareti(kanca["metin"])
    if ks > k["kanca"]["en_cok_sure_sn"]:
        h.append(f"kanca seslendirmesi {ks:.2f} sn sürüyor (ölçülen); en çok {k['kanca']['en_cok_sure_sn']} sn")
    if not o["kanca_merak_isaretleri"]:
        h.append("kancada merak işareti yok (sayı, soru ya da sıradışılık bildiren kelime)")
    return h, o


# ---------------------------------------------------------------- Faz-62c: uzun belgesel

def _kelimeler(metin: str) -> list[str]:
    return re.findall(r"\w+", metin.lower())


def tekrar_denetle(cumleler: list[dict], k: dict) -> list[str]:
    """Aynı bilginin farklı cümlelerle tekrarı (yapay uzatma): birebir aynı metin, yüksek içerik-kelimesi benzerliği
    ya da ortak uzun kelime dizisi (n-gram). Konudan bağımsız, belirlenimci."""
    h = []
    en_az = k["icerik_kelime_en_az_harf"]
    n = k["ngram"]
    kume = [{w for w in _kelimeler(c["metin"]) if len(w) >= en_az} for c in cumleler]
    gorulen_metin: dict[str, str] = {}
    gorulen_ngram: dict[tuple, str] = {}
    for i, c in enumerate(cumleler):
        duz = " ".join(_kelimeler(c["metin"]))
        if duz in gorulen_metin:
            h.append(f"{c['id']}: {gorulen_metin[duz]} ile aynı cümle (tekrar)")
        gorulen_metin.setdefault(duz, c["id"])
        w = _kelimeler(c["metin"])
        for j in range(len(w) - n + 1):
            g = tuple(w[j:j + n])
            if g in gorulen_ngram and gorulen_ngram[g] != c["id"]:
                h.append(f"{c['id']}: {gorulen_ngram[g]} ile aynı {n} kelimelik ifade (\"{' '.join(g)}\") — tekrar")
                break
        for g in (tuple(w[j:j + n]) for j in range(len(w) - n + 1)):
            gorulen_ngram.setdefault(g, c["id"])
        for j in range(i):
            a, b = kume[i], kume[j]
            if len(a) >= 4 and len(b) >= 4 and len(a & b) / len(a | b) >= k["benzerlik_esigi"]:
                h.append(f"{c['id']}: {cumleler[j]['id']} ile aynı bilgiyi tekrar ediyor "
                         f"(içerik benzerliği {len(a & b) / len(a | b):.2f})")
                break
    return h


def uzun_denetle(senaryo: dict, sureler: dict) -> tuple[list[str], dict]:
    """Uzun belgesel anlatı denetimi. sureler: seslendirme.olc() çıktısı (gerçek TTS). Dönüş: (hatalar, ölçümler).
    Toplam süre kapısı (15–20 dk) uretim_hatti'nda zaman çizelgesi üzerinden uygulanır."""
    k = veri.kural("uzun")
    h, o = [], {}
    if senaryo.get("format") != "uzun":
        return [f"senaryo biçimi '{senaryo.get('format')}': uzun belgesel denetimi uygulanamaz"], o
    cs = senaryo["cumleler"]
    bolumler = senaryo.get("bolumler") or []
    kb = k["bolum"]
    if not kb["en_az"] <= len(bolumler) <= kb["en_cok"]:
        h.append(f"{len(bolumler)} bölüm; uzun belgesel için {kb['en_az']}–{kb['en_cok']} ana bölüm gerekli")
    roller = kb["roller"]
    bids = [b.get("id") for b in bolumler]
    if len(set(bids)) != len(bids):
        h.append("bölüm kimlikleri tekrar ediyor")
    onceki, kapsanan = -1, []
    for b in bolumler:
        if not b.get("baslik"):
            h.append(f"{b.get('id')}: bölüm başlığı yok")
        for r in b.get("roller") or []:
            if r not in roller:
                h.append(f"{b.get('id')}: bilinmeyen bölüm rolü '{r}' (geçerli: {', '.join(roller)})")
                continue
            if roller.index(r) < onceki:
                h.append(f"{b.get('id')}: '{r}' rolü kronolojik bölüm sırasını bozuyor")
            onceki = max(onceki, roller.index(r))
            kapsanan.append(r)
        if not b.get("roller"):
            h.append(f"{b.get('id')}: bölümün rolü yok")
    eksik = [r for r in roller if r not in kapsanan]
    if eksik:
        h.append(f"eksik bölüm rolleri: {', '.join(eksik)}")
    if bolumler and "kanca" not in (bolumler[0].get("roller") or []):
        h.append("ilk bölüm açılış kancasını (kanca) taşımalı")
    if bolumler and "kapanis" not in (bolumler[-1].get("roller") or []):
        h.append("son bölüm kapanışı (kapanis) taşımalı")
    # cümleler bölümlere bitişik ve bölüm sırasıyla dağılmalı
    sira = {b: i for i, b in enumerate(bids)}
    say: dict[str, int] = {}
    son_i = -1
    for c in cs:
        b = c.get("bolum")
        if b not in sira:
            h.append(f"{c['id']}: bölümü yok ya da tanımsız ('{b}')")
            continue
        if sira[b] < son_i:
            h.append(f"{c['id']}: '{b}' bölümüne dönüyor (bölümler bitişik ve sıralı olmalı)")
        son_i = max(son_i, sira[b])
        say[b] = say.get(b, 0) + 1
        n = len(_kelimeler(c["metin"]))
        if n > k["cumle"]["en_cok_kelime"]:
            h.append(f"{c['id']}: {n} kelime; uzun formatta en çok {k['cumle']['en_cok_kelime']}")
        if n < k["cumle"]["en_az_kelime"]:
            h.append(f"{c['id']}: {n} kelime; en az {k['cumle']['en_az_kelime']}")
    for b in bids:
        if say.get(b, 0) < kb["en_az_cumle"]:
            h.append(f"{b}: {say.get(b, 0)} cümle; bölüm başına en az {kb['en_az_cumle']}")
    if cs and cs[0]["id"] != senaryo.get("kanca"):
        h.append("kanca ilk cümle olmalı")
    if cs and cs[-1]["id"] != senaryo.get("final"):
        h.append("final son cümle olmalı")
    if cs and cs[0]["id"] in sureler:
        ks = sureler[cs[0]["id"]]["sure_sn"]
        o["kanca_sure_sn"] = ks
        o["kanca_merak_isaretleri"] = kanca_merak_isareti(cs[0]["metin"])
        if ks > k["kanca"]["en_cok_sure_sn"]:
            h.append(f"açılış kancası {ks:.2f} sn sürüyor (ölçülen); en çok {k['kanca']['en_cok_sure_sn']} sn")
        if not o["kanca_merak_isaretleri"]:
            h.append("açılış kancasında merak işareti yok (sayı, soru ya da sıradışılık bildiren kelime)")
    h += tekrar_denetle(cs, k["tekrar"])
    uc = [c for c in cs if c["niyet"]["tur"] == "3d"]
    kg = k["gorsel"]
    if cs and (len(uc) > kg["en_cok_3d_cumle"] or len(uc) / len(cs) > kg["en_cok_3d_payi"]):
        h.append(f"{len(uc)} 3D cümle (%{100 * len(uc) / len(cs):.0f}); uzun formatta en çok {kg['en_cok_3d_cumle']} ve "
                 f"%{100 * kg['en_cok_3d_payi']:.0f} (render önceliği: harita, tarihî görsel, sınırlı 3D)")
    o["bolum_konusma_sn"] = {b: round(sum(sureler[c["id"]]["sure_sn"] for c in cs if c.get("bolum") == b
                                          and c["id"] in sureler), 2) for b in bids}
    o["cumle_sayisi"] = len(cs)
    o["tur_dagilimi"] = {t: sum(1 for c in cs if c["niyet"]["tur"] == t) for t in ("3d", "harita", "gorsel25d", "bilgi_karti")}
    return h, o


def denetle(senaryo: dict, sureler: dict) -> tuple[list[str], dict]:
    """Biçime göre anlatı denetimi: 'uzun' → uzun_denetle, diğerleri → shorts_denetle (değişmemiş Shorts davranışı)."""
    if senaryo.get("format") == "uzun":
        return uzun_denetle(senaryo, sureler)
    return shorts_denetle(senaryo, sureler)
