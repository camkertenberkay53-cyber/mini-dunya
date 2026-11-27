"""Ses kalite kontrolü (deneysel, Faz 5.1 P0). Tek bir cümle sesini, okunması gereken metinle karşılaştırır.

Whisper dökümü tek başına kanıt sayılmaz; birbirinden bağımsız kontroller birleştirilir:
  K1 kelime hata oranı (sayılar normalleştirilmiş)          K5 süre anomalisi (harf başına konuşma süresi, toplu medyana göre)
  K2 eksik kelimeler (hizalamada silinenler)                 K6 sayı / sıra / kısaltma / özel isim denetimi (metin.hazirla çıktısı)
  K3 fazla kelimeler (araya girenler)                        K7 cümle bütünlüğü (ilk ve son kelime duyuldu mu)
  K4 kuyruk/baş konuşması: ASR'nin son eşleşen kelimeden     K8 uzun iç sessizlik
     sonra duyduğu kelimeler + enerji tabanlı konuşma         K9 ASR güveni (kelime olasılık ortalaması)
     etkinliği (ASR'nin atladığı anlamsız sesi de yakalar)
Karar: KRİTİK bulgu varsa yeniden üretim; denemeler biterse FAIL. Yalnızca uyarı kalırsa İNCELEME. Hiçbir şey sessizce geçmez.
"""
from __future__ import annotations

import difflib
import re

import numpy as np

SAYI = ["bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz", "on", "yirmi", "otuz", "kırk", "elli",
        "altmış", "yetmiş", "seksen", "doksan", "yüz", "bin", "milyon", "milyar"]
_SAYI_RE = re.compile(f"^({'|'.join(SAYI)})+$")
_SAYI_EKLI_RE = re.compile(f"^({'|'.join(SAYI)})+[a-zçğıöşü]{{0,5}}$")

# Eşikler (bu deneyde belirlendi; değiştirilirse rapor edilir)
ESIK = {
    "wer_kritik": 0.30, "wer_uyari": 0.10,
    "kuyruk_kelime_kritik": 2, "kuyruk_ses_kritik_sn": 0.7, "bas_ses_kritik_sn": 0.7,
    "eksik_kritik": 2,
    "sure_orani_ust": 1.5, "sure_orani_alt": 0.6,
    "ic_sessizlik_uyari_sn": 1.0,
    "asr_olasilik_uyari": 0.60,
    "isim_benzerlik": 0.75,
}


def kucuk(t: str) -> str:
    return t.replace("I", "ı").replace("İ", "i").lower()


def _sayi_yazi(n: int) -> str:
    from metin import sayi_oku
    return sayi_oku(n).replace(" ", "")


def normal(t: str) -> list[str]:
    """Karşılaştırma biçimi: küçük harf, noktalama yok; rakamlar okunuşa (53'te → elliüçte); ardışık sayı sözcükleri birleşik."""
    t = kucuk(t).replace("’", "'")
    t = re.sub(r"(\d{1,3}(?:\.\d{3})+|\d+)'?([a-zçğıöşü]*)", lambda m: " " + _sayi_yazi(int(m.group(1).replace(".", ""))) + m.group(2) + " ", t)
    t = re.sub(r"[^\wçğıöşü' ]", " ", t).replace("'", "")
    out: list[str] = []
    for w in t.split():
        if out and _SAYI_RE.match(out[-1]) and _SAYI_EKLI_RE.match(w):
            out[-1] += w
        else:
            out.append(w)
    return out


def benzer(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def hizala(r: list[str], h: list[str]) -> list[tuple[str, int | None, int | None]]:
    """Levenshtein hizalaması; işlemler: ('esit'|'degis'|'sil'|'ekle', ref_i, hip_j)."""
    n, m = len(r), len(h)
    d = np.zeros((n + 1, m + 1), dtype=int)
    d[:, 0] = range(n + 1)
    d[0, :] = range(m + 1)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + (r[i - 1] != h[j - 1]))
    ops = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i, j] == d[i - 1, j - 1] + (r[i - 1] != h[j - 1]):
            ops.append(("esit" if r[i - 1] == h[j - 1] else "degis", i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i > 0 and d[i, j] == d[i - 1, j] + 1:
            ops.append(("sil", i - 1, None))
            i -= 1
        else:
            ops.append(("ekle", None, j - 1))
            j -= 1
    return ops[::-1]


def konusma_etkinligi(x: np.ndarray, sr: int, pencere_sn: float = 0.03) -> tuple[np.ndarray, float]:
    """Enerji tabanlı konuşma etkinliği (çerçeve başına bool) — ASR'den bağımsız."""
    n = max(1, int(sr * pencere_sn))
    k = len(x) // n
    if k == 0:
        return np.zeros(0, bool), pencere_sn
    e = 20 * np.log10(np.sqrt((x[:k * n].reshape(k, n) ** 2).mean(1)) + 1e-9)
    esik = max(e.max() - 35, -50)
    return e > esik, pencere_sn


def denetle(x: np.ndarray, sr: int, konusma: str, ozel: list[dict], asr: dict, hiz_harf_sn: float | None) -> dict:
    ref = normal(konusma)
    # ASR kelimelerini normalleştirilmiş belirteçlere yay (her belirteç kendi zaman aralığını taşır)
    from asr_birim import hip_olustur
    hip, zaman, olas = hip_olustur(asr["kelimeler"], normal, _SAYI_RE, _SAYI_EKLI_RE)
    ops = hizala(ref, hip)
    hata = sum(o[0] != "esit" for o in ops)
    wer = hata / max(1, len(ref))
    eslesen = [(i, j) for k, i, j in ops if k in ("esit", "degis") and benzer(ref[i], hip[j]) >= 0.6]
    eksik = [ref[i] for k, i, j in ops if k == "sil"]
    ilk_j = eslesen[0][1] if eslesen else None
    son_j = eslesen[-1][1] if eslesen else None
    fazla_ic = [hip[j] for k, i, j in ops if k == "ekle" and ilk_j is not None and ilk_j < j < son_j]
    kuyruk_kel = [hip[j] for j in range(son_j + 1, len(hip))] if son_j is not None else hip[:]
    bas_kel = [hip[j] for j in range(0, ilk_j)] if ilk_j is not None else []
    # Enerji tabanlı: son eşleşen kelimeden sonra / ilk eşleşenden önce konuşma etkinliği
    etk, p = konusma_etkinligi(x, sr)
    t_son = zaman[son_j][1] if son_j is not None else 0.0
    t_ilk = zaman[ilk_j][0] if ilk_j is not None else len(x) / sr
    kuyruk_ses = float(etk[int((t_son + 0.25) / p):].sum() * p) if len(etk) else 0.0
    bas_ses = float(etk[:max(0, int((t_ilk - 0.25) / p))].sum() * p) if len(etk) else 0.0
    # İç sessizlik ve süre
    aktif = np.flatnonzero(etk)
    konusma_sn = float((aktif[-1] - aktif[0] + 1) * p) if len(aktif) else 0.0
    en_uzun_sessizlik = 0.0
    if len(aktif) > 1:
        bosluk = np.diff(aktif) - 1
        en_uzun_sessizlik = float(bosluk.max() * p)
    harf = len(re.findall(r"[a-zçğıöşü]", kucuk(konusma)))
    sure_orani = (konusma_sn / (harf / hiz_harf_sn)) if (hiz_harf_sn and harf) else None
    # Özel öğeler: okunuşun (ya da yazımın) dökümde art arda bulunması
    ozel_sonuc = []
    for o in ozel:
        adaylar = [normal(o["okunus"]), normal(o["yazim"])]
        bulundu = False
        for toks in adaylar:
            if not toks:
                continue
            for s in range(0, len(hip) - len(toks) + 1):
                if o["tur"] in ("sayi", "sira"):
                    ok = all(hip[s + q] == toks[q] or (q == len(toks) - 1 and hip[s + q].startswith(toks[q][:-1]))
                             for q in range(len(toks)))
                else:
                    ok = all(benzer(hip[s + q][:len(toks[q]) + 1], toks[q]) >= ESIK["isim_benzerlik"]
                             or hip[s + q].startswith(toks[q][:max(3, len(toks[q]) - 2)]) for q in range(len(toks)))
                if ok:
                    bulundu = True
                    break
            if bulundu:
                break
        ozel_sonuc.append({**o, "bulundu": bulundu})
    olas_ort = float(np.mean(olas)) if olas else 0.0
    butunluk = bool(eslesen) and eslesen[0][0] == 0 and eslesen[-1][0] == len(ref) - 1

    kritik, uyari = [], []
    if len(kuyruk_kel) >= ESIK["kuyruk_kelime_kritik"] or kuyruk_ses >= ESIK["kuyruk_ses_kritik_sn"]:
        kritik.append(f"cümle sonunda fazladan konuşma ({len(kuyruk_kel)} kelime, {kuyruk_ses:.1f} sn ses)")
    if (len(bas_kel) >= 2) or bas_ses >= ESIK["bas_ses_kritik_sn"]:
        kritik.append(f"cümle başında fazladan konuşma ({len(bas_kel)} kelime, {bas_ses:.1f} sn ses)")
    if len(eksik) >= ESIK["eksik_kritik"]:
        kritik.append(f"eksik kelime: {' '.join(eksik)}")
    if not butunluk:
        kritik.append("cümle bütünlüğü: ilk ya da son kelime duyulmadı")
    if wer > ESIK["wer_kritik"]:
        kritik.append(f"kelime hata oranı yüksek ({wer:.2f})")
    if sure_orani is not None and (sure_orani > ESIK["sure_orani_ust"] or sure_orani < ESIK["sure_orani_alt"]):
        kritik.append(f"süre anomalisi (beklenenin {sure_orani:.2f} katı)")
    for o in ozel_sonuc:
        if not o["bulundu"] and o["tur"] in ("sayi", "sira", "kisaltma"):
            kritik.append(f"{o['tur']} okunmadı/yanlış: '{o['yazim']}' → beklenen '{o['okunus']}'")
    if ESIK["wer_uyari"] < wer <= ESIK["wer_kritik"]:
        uyari.append(f"kelime hata oranı ({wer:.2f})")
    if len(eksik) == 1:
        uyari.append(f"eksik kelime: {eksik[0]}")
    if fazla_ic:
        uyari.append(f"araya giren kelime: {' '.join(fazla_ic)}")
    if 0 < len(kuyruk_kel) < ESIK["kuyruk_kelime_kritik"] and kuyruk_ses < ESIK["kuyruk_ses_kritik_sn"]:
        uyari.append(f"sonda tek fazla kelime: {kuyruk_kel[0]}")
    for o in ozel_sonuc:
        if not o["bulundu"] and o["tur"] == "isim":
            uyari.append(f"özel isim doğrulanamadı: {o['yazim']}")
    if en_uzun_sessizlik > ESIK["ic_sessizlik_uyari_sn"]:
        uyari.append(f"uzun iç sessizlik ({en_uzun_sessizlik:.1f} sn)")
    if olas_ort < ESIK["asr_olasilik_uyari"]:
        uyari.append(f"ASR güveni düşük ({olas_ort:.2f})")
    puan = max(0.0, 100 - 25 * len(kritik) - 8 * len(uyari) - 40 * wer)
    return {
        "durum": "KRITIK" if kritik else ("UYARI" if uyari else "GECTI"),
        "puan": round(puan, 1), "kritik": kritik, "uyari": uyari,
        "olcum": {"wer": round(wer, 3), "eksik": eksik, "fazla_ic": fazla_ic, "kuyruk_kelime": kuyruk_kel,
                  "bas_kelime": bas_kel, "kuyruk_ses_sn": round(kuyruk_ses, 2), "bas_ses_sn": round(bas_ses, 2),
                  "konusma_sn": round(konusma_sn, 2), "ses_sn": round(len(x) / sr, 2),
                  "sure_orani": None if sure_orani is None else round(sure_orani, 2),
                  "en_uzun_sessizlik_sn": round(en_uzun_sessizlik, 2), "asr_olasilik": round(olas_ort, 3),
                  "butunluk": butunluk, "ozel": ozel_sonuc, "dokum": asr["metin"]},
    }


def harf_hizi(x: np.ndarray, sr: int, konusma: str) -> float | None:
    etk, p = konusma_etkinligi(x, sr)
    a = np.flatnonzero(etk)
    harf = len(re.findall(r"[a-zçğıöşü]", kucuk(konusma)))
    if len(a) < 2 or not harf:
        return None
    return harf / ((a[-1] - a[0] + 1) * p)
