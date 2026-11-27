"""PDF metin normalizasyonu: pypdf'in satır satır verdiği metni doğrulanabilir paragraflara çevirir.

Sorun (Run 45956710301): pypdf her PDF satırını ayrı satır olarak verir. Doğrulayıcı her satırı ayrı bir pencere
sayınca yıl, kişi ve olay aynı pencereye düşmez. TDV İslam Ansiklopedisi'nin ilgili madde PDF'i bu yüzden tek bir
iddiayı bile doğrulayamadı.

Kurallar (deterministik; ham metin ayrıca saklanır, hiçbir bilgi silinmez — yalnızca yeniden düzenlenir):
- Unicode NFC uygulanır, bağlı harfler çözülür (ﬁ → fi). Türkçe harfler (ç ğ ı İ ö ş ü) korunur.
- Satır sonundaki tireyle bölünmüş kelime birleştirilir: "muhare-" + "besi" → "muharebesi". Sonraki satır büyük
  harfle başlıyorsa tire bileşik ad tiresidir ve korunur: "Ak-" + "Koyunlu" → "Ak-Koyunlu".
- Tiresiz bölünmüş kelime ("tarih" + "inde") yalnızca birleşik hal belgede başka bir yerde de geçiyorsa birleştirilir.
  Emin olunamayan durumda boşlukla ayrılır; kelime uydurulmaz.
- Paragraf sınırları korunur: boş satır ya da noktalama ile biten belirgin kısa satırdan sonra büyük harf.
- Sayfa başında `[s. N]` işareti bulunur. N, basılı sayfa numarası bulunursa odur; bulunamazsa `[pdf s. N]`.
- Her sayfanın üst/alt kenarında tekrar eden başlık/altbilgi satırları ve yalnız sayfa numarası olan satırlar ana
  metinden çıkarılır ve `kaldirilan` listesine yazılır.
- Sayfa sonundaki dipnot bloğu ana metne karışmaz; ayrı bir `[dipnot s. N]` paragrafı olur.
"""
from __future__ import annotations

import re
import statistics
import unicodedata
from collections import Counter

_BAGLI = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}
_KUCUK = "a-zçğıöşüâîûéèàäëïô"
_SAYFA_NO = re.compile(r"^\s*[-–—]?\s*(\d{1,4})\s*[-–—]?\s*$")
_DIPNOT = re.compile(r"^\s*(\d{1,3}|[*†‡])[\s.)]\s*\S")
_SON_NOKTA = re.compile(r"[.!?:;»”\")]\s*$")


def _unicode(s: str) -> str:
    s = unicodedata.normalize("NFC", s)
    for k, v in _BAGLI.items():
        s = s.replace(k, v)
    return s.replace(" ", " ").replace("\t", " ")


def _kucuk_mu(c: str) -> bool:
    return bool(c) and bool(re.match(f"[{_KUCUK}]", c))


def _harf_mi(c: str) -> bool:
    return bool(c) and c.isalpha()


def _sozluk(sayfalar: list[list[str]]) -> tuple[Counter, Counter]:
    """(iç, tüm): iç = satır ortasındaki tam kelimeler (kenardakiler bölünmüş olabilir); tüm = bütün kelimeler."""
    ic, tum = Counter(), Counter()
    for satirlar in sayfalar:
        for s in satirlar:
            k = re.findall(r"\w+", s.lower())
            tum.update(k)
            ic.update(k[1:-1] if len(k) > 2 else [])
    return ic, tum


def _baslik_mi(satir: str) -> bool:
    """Kısa, noktalamasız, harflerinin çoğu büyük satır: madde/bölüm başlığı (ana metne karıştırılmaz)."""
    x = satir.strip()
    harf = [c for c in x if c.isalpha()]
    return (3 <= len(x) <= 80 and len(harf) >= 3 and not _SON_NOKTA.search(x)
            and sum(c.isupper() for c in harf) / len(harf) >= 0.8)


def _kenar_satirlari(sayfalar: list[list[str]]) -> set[str]:
    """Sayfaların en az yarısında (en az 2 sayfa) üst/alt kenarda tekrar eden satırlar: başlık/altbilgi."""
    if len(sayfalar) < 2:
        return set()
    sayac = Counter()
    for satirlar in sayfalar:
        dolu = [x.strip() for x in satirlar if x.strip()]
        kenar = set(dolu[:2] + dolu[-2:])
        sayac.update(re.sub(r"\d+", "#", x).lower() for x in kenar)
    esik = max(2, (len(sayfalar) + 1) // 2)
    return {k for k, n in sayac.items() if n >= esik}


def _birlestir(a: str, b: str, sozluk: tuple[Counter, Counter]) -> tuple[str, str] | None:
    """a satırı ile b satırı aynı paragrafta nasıl birleşir? (ayraç, b_metni). None → paragraf sınırı."""
    bs = b.lstrip()
    if not a.strip() or not bs:
        return None
    son, ilk = a.rstrip()[-1:], bs[:1]
    if son in "-­" and len(a.rstrip()) >= 2 and _harf_mi(a.rstrip()[-2]):
        if _kucuk_mu(ilk):
            return "TIRE_SIL", bs               # tireyle bölünmüş kelime
        return "BITISIK", bs                    # bileşik ad (Ak-Koyunlu): tire kalır
    if son in "'’":
        return "BITISIK", bs                    # Mehmed'\nin
    if b[:1] == " ":
        return " ", bs                          # pypdf satır başı boşluğu: kelime sınırı
    if _harf_mi(son) and _kucuk_mu(ilk):
        w1 = re.findall(r"\w+$", a.rstrip())
        w2 = re.findall(r"^\w+", bs)
        if w1 and w2:
            butun = (w1[0] + w2[0]).lower()
            ic, tum = sozluk
            if tum.get(butun, 0) > 0 and (ic.get(w1[0].lower(), 0) == 0 or ic.get(w2[0].lower(), 0) == 0):
                return "BITISIK", bs            # tiresiz bölünme ("tarih"+"inde" → "tarihinde"; belgede geçiyor)
    return " ", bs


def normalize_sayfalar(sayfalar_ham: list[str]) -> dict:
    """Ham sayfa metinleri (pypdf, sayfa başına bir dize) → {metin, paragraflar, kaldirilan, dipnotlar, sayfa_sayisi}."""
    sayfalar = [[_unicode(x.rstrip()) for x in (p or "").split("\n")] for p in sayfalar_ham]
    sozluk = _sozluk(sayfalar)
    kenar = _kenar_satirlari(sayfalar)
    paragraflar, kaldirilan, dipnotlar = [], [], []
    for no, satirlar in enumerate(sayfalar, 1):
        dolu_idx = [i for i, x in enumerate(satirlar) if x.strip()]
        basili = None
        sil = set()
        if len(dolu_idx) >= 3:   # tek/iki satırlık sayfada kenar ayıklaması yapılmaz (içerik olabilir)
            for i in dolu_idx[:2] + dolu_idx[-2:]:
                x = satirlar[i].strip()
                m = _SAYFA_NO.match(x)
                if m:
                    basili = basili or m.group(1)
                    sil.add(i)
                elif re.sub(r"\d+", "#", x).lower() in kenar:
                    sil.add(i)
        for i in sorted(sil):
            kaldirilan.append({"sayfa": no, "satir": satirlar[i].strip()})
        govde = [x for i, x in enumerate(satirlar) if i not in sil]
        # dipnot bloğu: sayfanın son %40'ında, noktalamayla biten satırdan sonra dipnot işaretiyle başlayan satırdan sona
        dip = []
        dolu = [i for i, x in enumerate(govde) if x.strip()]
        if len(dolu) >= 5:
            for j in range(len(dolu) - 1, 0, -1):
                i, onceki = dolu[j], dolu[j - 1]
                if i < dolu[0] + 0.6 * (dolu[-1] - dolu[0]):
                    break
                if _DIPNOT.match(govde[i]) and _SON_NOKTA.search(govde[onceki]):
                    dip = govde[i:]
                    govde = govde[:i]
                    break
        isaret = f"[s. {basili}]" if basili else f"[pdf s. {no}]"
        paragraflar.append(isaret)
        uzunluk = [len(x.strip()) for x in govde if len(x.strip()) > 20]
        tipik = statistics.median(uzunluk) if uzunluk else 60
        mevcut, son_satir = "", ""
        for x in govde:
            if not x.strip():
                if mevcut.strip():
                    paragraflar.append(mevcut.strip())
                mevcut, son_satir = "", ""
                continue
            if _baslik_mi(x):   # başlık kendi paragrafı olur; önceki ve sonraki metne birleştirilmez
                if mevcut.strip():
                    paragraflar.append(mevcut.strip())
                paragraflar.append(x.strip())
                mevcut, son_satir = "", ""
                continue
            if not mevcut:
                mevcut, son_satir = x.strip(), x
                continue
            # paragraf sınırı: noktalamayla biten belirgin kısa satırdan sonra büyük harf/rakamla başlayan satır
            if (_SON_NOKTA.search(mevcut) and len(son_satir.strip()) < 0.7 * tipik
                    and (x.lstrip()[:1].isupper() or x.lstrip()[:1].isdigit())):
                paragraflar.append(mevcut.strip())
                mevcut, son_satir = x.strip(), x
                continue
            b = _birlestir(mevcut, x, sozluk)
            if b is None:
                paragraflar.append(mevcut.strip())
                mevcut = x.strip()
            elif b[0] == "TIRE_SIL":
                mevcut = mevcut.rstrip()[:-1] + b[1]
            elif b[0] == "BITISIK":
                mevcut = mevcut.rstrip() + b[1]
            else:
                mevcut = mevcut.rstrip() + " " + b[1]
            son_satir = x
        if mevcut.strip():
            paragraflar.append(mevcut.strip())
        if dip:
            d = " ".join(x.strip() for x in dip if x.strip())
            dipnotlar.append({"sayfa": no, "metin": d})
            paragraflar.append(f"[dipnot {isaret[1:-1]}] {d}")
    paragraflar = [re.sub(r" {2,}", " ", p) for p in paragraflar]
    return {"metin": "\n\n".join(paragraflar), "paragraflar": paragraflar, "kaldirilan": kaldirilan,
            "dipnotlar": dipnotlar, "sayfa_sayisi": len(sayfalar)}
