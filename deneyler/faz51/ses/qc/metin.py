"""Seslendirme metni hazırlama (deneysel, Faz 5.1 P0): yazılı metni TTS'in okuyacağı konuşma biçimine çevirir.

- Rakamlar → Türkçe sözcükler (boşluklu: 53 → "elli üç"); ekli yazımlar ("53'te" → "elli üçte").
- Sıra sayıları ("3." , "II.") → "üçüncü", "ikinci".
- Bilinen kısaltmalar (MÖ, MS, yy., km, %) → açık okunuş.
- Telaffuz sözlüğü (sozluk.yaml): yazım → okunuş (yabancı/tarihî isimler). Konuya özel kod yok; veri dosyası.
- Açılamayan kısaltmalar ve tanınmayan biçimler sessizce geçmez: 'uyarilar' listesinde döner.
Çıktı: (konusma_metni, uyarilar, ozel_ogeler). ozel_ogeler kalite kontrolünde ayrıca denetlenir.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

BURASI = Path(__file__).resolve().parent
BIRLER = ["", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
ONLAR = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"]
SIRA_EK = {"bir": "birinci", "iki": "ikinci", "üç": "üçüncü", "dört": "dördüncü", "beş": "beşinci", "altı": "altıncı",
           "yedi": "yedinci", "sekiz": "sekizinci", "dokuz": "dokuzuncu", "on": "onuncu", "yirmi": "yirminci",
           "otuz": "otuzuncu", "kırk": "kırkıncı", "elli": "ellinci", "altmış": "altmışıncı", "yetmiş": "yetmişinci",
           "seksen": "sekseninci", "doksan": "doksanıncı", "yüz": "yüzüncü", "bin": "bininci", "milyon": "milyonuncu"}
ROMA = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def sayi_oku(n: int) -> str:
    if n == 0:
        return "sıfır"
    parca = []
    for deger, ad in ((1_000_000_000, "milyar"), (1_000_000, "milyon"), (1000, "bin")):
        if n >= deger:
            k, n = divmod(n, deger)
            parca.append(ad if (ad == "bin" and k == 1) else f"{sayi_oku(k)} {ad}")
    if n >= 100:
        k, n = divmod(n, 100)
        parca.append("yüz" if k == 1 else f"{BIRLER[k]} yüz")
    if n >= 10:
        parca.append(ONLAR[n // 10])
        n %= 10
    if n:
        parca.append(BIRLER[n])
    return " ".join(parca)


def sira_oku(n: int) -> str:
    s = sayi_oku(n).split()
    s[-1] = SIRA_EK[s[-1]]
    return " ".join(s)


def roma(s: str) -> int | None:
    if not re.fullmatch(r"[IVXLCDM]+", s):
        return None
    t = 0
    for i, c in enumerate(s):
        v = ROMA[c]
        t += -v if i + 1 < len(s) and ROMA[s[i + 1]] > v else v
    return t


def sozluk() -> dict:
    return yaml.safe_load((BURASI / "sozluk.yaml").read_text()) or {}


def hazirla(metin: str) -> tuple[str, list[str], list[dict]]:
    sz = sozluk()
    uyari: list[str] = []
    ozel: list[dict] = []
    t = metin.replace("’", "'")
    for k, v in (sz.get("kisaltmalar") or {}).items():
        desen = r"(?<!\w)" + re.escape(k) + r"(?!\w)"
        if re.search(desen, t):
            ozel.append({"tur": "kisaltma", "yazim": k, "okunus": v})
            t = re.sub(desen, v, t)
    # Yüzde: %40 → yüzde kırk
    t = re.sub(r"%\s?(\d+)", lambda m: "yüzde " + sayi_oku(int(m.group(1))), t)
    # Roma rakamlı sıra (II. Mehmed) ve rakamlı sıra (3. yüzyıl)
    def _sira(m):
        r = roma(m.group(1)) if not m.group(1).isdigit() else int(m.group(1))
        if r is None:
            return m.group(0)
        ok = sira_oku(r)
        ozel.append({"tur": "sira", "yazim": m.group(0).strip(), "okunus": ok})
        return ok + " "
    t = re.sub(r"\b([IVXLCDM]{1,6}|\d{1,4})\.\s(?=\w)", _sira, t)
    # Rakam + kesme ekli (53'te) ve düz rakam
    def _sayi(m):
        n = int(m.group(1).replace(".", ""))
        ok = sayi_oku(n)
        ek = m.group(2) or ""
        ozel.append({"tur": "sayi", "yazim": m.group(0), "okunus": ok + ek.lstrip("'"), "kok": ok})
        return ok + ek.lstrip("'")
    t = re.sub(r"(\d{1,3}(?:\.\d{3})+|\d+)('\w+)?", _sayi, t)
    for k, v in (sz.get("telaffuz") or {}).items():
        desen = r"(?<!\w)" + re.escape(k)
        if re.search(desen, t, flags=re.IGNORECASE):
            ozel.append({"tur": "isim", "yazim": k, "okunus": v})
            t = re.sub(desen, lambda m: v if m.group(0)[0].islower() else v[0].upper() + v[1:], t, flags=re.IGNORECASE)
    for ad in sz.get("isimler") or []:
        if re.search(r"(?<!\w)" + re.escape(ad), t):
            ozel.append({"tur": "isim", "yazim": ad, "okunus": ad})
    isim = [o for o in ozel if o["tur"] == "isim"]
    ozel = [o for o in ozel if o["tur"] != "isim" or not any(
        b is not o and b["yazim"].startswith(o["yazim"]) and len(b["yazim"]) > len(o["yazim"]) for b in isim)]
    kalan = re.findall(r"\b[A-ZÇĞİÖŞÜ]{2,}\b", t)
    if kalan:
        uyari.append(f"açılamayan kısaltma: {', '.join(sorted(set(kalan)))}")
    if re.search(r"\d", t):
        uyari.append("okunuşa çevrilemeyen rakam kaldı")
    return re.sub(r"\s+", " ", t).strip(), uyari, ozel
