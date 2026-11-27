"""Atomik iddia doğrulaması: bir kaynak iddianın hangi PARÇALARINI destekliyor?

Sorun (Run 45956710301): Tek bir kelime örtüşme eşiği (%50) uzun iddialarda yanlış pozitif üretti. Savaşı yalnızca
anan kaynaklar ("<Savaş> (1473)"), "<gün ay yıl> … dönüm noktası" iddiasını "doğrulamış" sayıldı.

İddia atomlara ayrılır (iddiada geçenler):
- `yil`: yıllar. `gun_ay`: gün + ay ("11 Ağustos", "August 11").
- `sayi`: yıl dışı rakamlar (≥ 50).
- `varlik`: kişi/yer özel adları; bunlardan bir unvanın (Sultan, Paşa, Bey, Han, Şah…) yanında geçenler `komutan`
  olarak işaretlenir.
- `olay`: konu terimi. `sonuc`: zafer, yenilgi, çekilme, fetih… `yorum`: dönüm noktası, belirleyici, önemli…
- `icerik`: kalan içerik sözcükleri.

Bir kaynağın destek sınıfı, AYNI pencerede (paragraf ya da 3 cümle) aranır:
- `supported`: iddiadaki bütün atomlar sağlanıyor ve kalan içerik örtüşmesi en az `ICERIK_ESIGI`. Örtüşme oranı tek
  başına hiçbir zaman yeterli değildir.
- `contradicts`: aynı olay bağlamında farklı yıl, farklı gün-ay ya da aynı ölçü için farklı rakam veriyor.
- `partial`: olgusal atomların (yıl, gün-ay, sayı, sonuç, yorum ya da en az iki varlık) bir kısmı sağlanıyor.
- `mention`: yalnızca olay/konu adı ya da tek bir varlık geçiyor; olgusal destek yok.
- `no_evidence`: hiçbiri.
"""
from __future__ import annotations

import re
import unicodedata

ICERIK_ESIGI = 0.4   # supported için kalan içerik sözcüklerinin örtüşme alt sınırı (fixture testleriyle belirlendi)
VARLIK_ESIGI = 0.75  # supported için varlık kapsama alt sınırı

_YIL = re.compile(r"(?<!\d)(1[0-9]{3}|[5-9][0-9]{2})(?!\d)")
_AYLAR = {"ocak": 1, "subat": 2, "mart": 3, "nisan": 4, "mayis": 5, "haziran": 6, "temmuz": 7, "agustos": 8,
          "eylul": 9, "ekim": 10, "kasim": 11, "aralik": 12, "january": 1, "february": 2, "march": 3, "april": 4,
          "may": 5, "june": 6, "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12}
_UNVAN = {"sultan", "pasa", "pasha", "bey", "han", "khan", "sah", "shah", "mirza", "padisah", "hukumdar", "emir",
          "komutan", "serasker", "beylerbeyi", "vezir", "imparator", "emperor", "king", "kral", "hakan"}
_SONUC = {   # grup → kökler (ilk 5 harf, ASCII katlanmış); iddiada geçen grup kaynakta da geçmeli
    "kazanma": ["zafer", "galip", "galeb", "kazan", "yendi", "yenmi", "victo", "won", "triump", "defea"],
    "kaybetme": ["yenil", "maglu", "kaybe", "bozgu", "hezim", "defea", "lost", "routed", "rout"],
    "cekilme": ["cekil", "geri ", "retre", "withd", "kacti", "fled"],
    "fetih": ["fethe", "fethi", "zapte", "ele g", "conqu", "captu", "seize"],
    "olum": ["oldu", "olumu", "oldur", "katle", "shehi", "sehit", "kille", "slain", "died", "death"],
}
_YORUM = {
    "donum": ["donum noktas", "turning point", "pivotal", "milestone", "landmark", "kirilma noktas"],
    "belirleyici": ["belirleyici", "kesin sonuc", "decisive", "kader"],
    "onem": ["buyuk onem", "onemli", "onem tas", "significan", "crucial", "important", "great importance"],
    "birlik": ["birliginin", "birligi", "unity", "unification"],
}
_OLCU = {
    "ordu": ["asker", "kisil", "ordu", "kuvve", "sueva", "atli", "piyad", "yenic", "troop", "army", "soldi", "force",
             "caval", "infan", "streng", "janis", "men", "peopl", "warri", "horse"],
    "kayip": ["kayip", "kayb", "olu", "oldu", "olum", "sehit", "casua", "kille", "losse", "dead", "death", "slain"],
}
_ILISKI = {"ardindan", "sonra", "sonrasinda", "sonraki", "once", "oncesinde", "onceki", "after", "before", "following",
           "since", "until", "kadar", "itibaren", "later", "earlier", "yil", "yillar", "years"}
_DURAK = set("""ve ile bir bu da de icin olarak olan daha sonra ancak gibi kadar cok en ki ise veya ya hem the a an of
and in on at to by for with from was were is are as that which this his her its their it be been had has have after
before during into than also not yilinda tarihinde arasinda yapilan yapildi""".split())


def katla(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").replace("İ", "I").replace("ı", "i")).encode("ascii", "ignore").decode()
    return s.lower()


def _tokenler(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", katla(s))


def _sayilar(s: str) -> list[tuple[int, int]]:
    """(değer, token konumu): yıl olmayan ≥ 50 rakamlar."""
    out = []
    for i, t in enumerate(re.findall(r"\d{1,3}(?:[.,]\d{3})+|\d+|[^\W\d_]+", s)):
        if t[:1].isdigit():
            d = int(re.sub(r"[.,]", "", t))
            if not _YIL.fullmatch(re.sub(r"[.,]", "", t)) and d >= 50:
                out.append((d, i))
    return out


def _gun_ay(s: str) -> set[tuple[int, int]]:
    k = katla(s)
    out = set()
    for m in re.finditer(r"(?<!\d)(\d{1,2})\s+([a-z]+)", k):
        if m.group(2) in _AYLAR and 1 <= int(m.group(1)) <= 31:
            out.add((int(m.group(1)), _AYLAR[m.group(2)]))
    for m in re.finditer(r"([a-z]+)\s+(\d{1,2})(?!\d)", k):
        if m.group(1) in _AYLAR and 1 <= int(m.group(2)) <= 31:
            out.add((int(m.group(2)), _AYLAR[m.group(1)]))
    return out


def _gruplar(s: str, sozluk: dict) -> set[str]:
    k = " " + " ".join(_tokenler(s)) + " "
    return {g for g, kokler in sozluk.items() if any((" " + kk) in k for kk in kokler)}


def _varliklar(metin: str) -> list[dict]:
    out, gor = [], set()
    for c in re.split(r"(?<=[.!?])\s+", metin):
        kel = re.findall(r"[^\W\d_][\w'’-]*", c)
        for i, w in enumerate(kel):
            ad = re.split(r"['’]", w)[0]
            if i > 0 and w[:1].isupper() and len(ad) >= 3 and katla(ad) not in _DURAK and katla(ad) not in _AYLAR:
                parca = [t[:5] for t in _tokenler(ad) if len(t) >= 2]   # "Ak-Koyunlu" → ["ak", "koyun"]
                kok = " ".join(parca)
                if not parca or kok in gor:
                    continue
                gor.add(kok)
                yan = {katla(re.split(r"['’]", x)[0]) for x in kel[max(0, i - 2): i + 3]}
                out.append({"ad": ad, "kok": kok, "parca": parca, "komutan": bool(yan & _UNVAN) and katla(ad) not in _UNVAN})
    return out


def atomlar(iddia: dict) -> dict:
    m = iddia.get("metin", "")
    yillar = sorted({int(y) for y in (iddia.get("yillar") or _YIL.findall(m))})
    olay = [o for o in (katla(t)[:5] for t in iddia.get("olay_terimleri", []) if t) if o in katla(m)]
    var = _varliklar(m) if not iddia.get("varliklar") else [
        {"ad": v, "kok": " ".join(t[:5] for t in _tokenler(v)), "parca": [t[:5] for t in _tokenler(v) if len(t) >= 2],
         "komutan": False} for v in iddia["varliklar"] if _tokenler(v)]
    atom_tok = set(str(y) for y in yillar) | {p for v in var for p in v["parca"]} | set(olay)
    icerik = [t[:5] for t in _tokenler(m) if len(t) >= 4 and t not in _DURAK and t[:5] not in atom_tok
              and not t.isdigit() and t not in _AYLAR]
    return {"yil": yillar, "gun_ay": sorted(_gun_ay(m)), "sayi": sorted({d for d, _ in _sayilar(m)}),
            "varlik": var, "olay": olay, "sonuc": sorted(_gruplar(m, _SONUC)), "yorum": sorted(_gruplar(m, _YORUM)),
            "icerik": list(dict.fromkeys(icerik))}


def _olay_yili_bagli(tok: list[str], olay: list[str]) -> list[int]:
    """Olay teriminin hemen yanındaki (≤3 sözcük, arada 'ardından/sonra/önce/after…' gibi ilişki sözcüğü olmayan)
    yıllar: bu yıllar olayın KENDİ yılıdır. 'Savaşın ardından 1502'de' → 1502 savaşın yılı değildir."""
    out = []
    for i, t in enumerate(tok):
        if t[:5] not in olay:
            continue
        for j in range(max(0, i - 3), min(len(tok), i + 4)):
            if tok[j].isdigit() and _YIL.fullmatch(tok[j]):
                ara = tok[min(i, j) + 1: max(i, j)]
                if not (set(ara) & _ILISKI):
                    out.append(int(tok[j]))
    return out


def _olcu_turu(metin: str, konum: int) -> str | None:
    kel = re.findall(r"\d{1,3}(?:[.,]\d{3})+|\d+|[^\W\d_]+", metin)
    cevre = [katla(x)[:5] for x in kel[max(0, konum - 6): konum + 7]]
    for t, anahtar in _OLCU.items():
        if any(c.startswith(a) or a in c for c in cevre for a in anahtar):
            return t
    return None


def pencere_degerlendir(w: str, a: dict) -> dict:
    tok = _tokenler(w)
    kok5 = {t[:5] for t in tok}
    wy = {int(y) for y in _YIL.findall(w)}
    sag = {}
    if a["yil"]:
        sag["yil"] = all(y in wy for y in a["yil"])
    if a["gun_ay"]:
        sag["gun_ay"] = set(a["gun_ay"]) <= _gun_ay(w)
    if a["sayi"]:
        ws = {d for d, _ in _sayilar(w)}
        sag["sayi"] = set(a["sayi"]) <= ws
    def _var(v):
        return all(p in kok5 for p in v["parca"])
    var_oran = (sum(_var(v) for v in a["varlik"]) / len(a["varlik"])) if a["varlik"] else None
    if a["varlik"]:
        sag["varlik"] = var_oran >= VARLIK_ESIGI
        kom = [v for v in a["varlik"] if v["komutan"]]
        if kom:
            sag["komutan"] = all(_var(v) for v in kom)
    if a["olay"]:
        sag["olay"] = any(o in kok5 for o in a["olay"])
    if a["sonuc"]:
        sag["sonuc"] = bool(set(a["sonuc"]) & _gruplar(w, _SONUC))
    if a["yorum"]:
        sag["yorum"] = set(a["yorum"]) <= _gruplar(w, _YORUM)
    icerik_oran = (sum(c in kok5 for c in a["icerik"]) / len(a["icerik"])) if a["icerik"] else 1.0

    # çelişki: aynı olay bağlamında (olay terimi ya da varlıkların çoğu) farklı yıl / gün-ay / aynı ölçüde farklı rakam
    baglam = (sag.get("olay") is True) or (var_oran is not None and var_oran >= 0.5)
    celiski = []
    if baglam and a["yil"] and not sag["yil"] and a["olay"] and a.get("_olay_yili"):
        # yalnızca iddianın olay yılı (olay adına bağlı yıl) ile kaynağın olay yılı farklıysa çelişki
        kaynak_olay_yili = _olay_yili_bagli(tok, a["olay"])
        if kaynak_olay_yili and not (set(kaynak_olay_yili) & set(a["_olay_yili"])):
            celiski.append("yil")
    if baglam and a["gun_ay"] and sag.get("yil") and not sag["gun_ay"] and _gun_ay(w):
        celiski.append("gun_ay")
    if baglam and a["sayi"] and not sag.get("sayi"):
        olculer: dict = {}
        for d, i in _sayilar(w):
            olculer.setdefault(_olcu_turu(w, i), set()).add(d)
        for d, t in a.get("_olcu", {}).items():   # aynı ölçü türünde (ordu/kayıp) farklı rakam
            if t and t in olculer and d not in olculer[t]:
                celiski.append("sayi")
                break

    olgusal = [k for k in ("yil", "gun_ay", "sayi", "sonuc", "yorum") if sag.get(k)]
    if a["varlik"] and len(a["varlik"]) >= 2 and var_oran is not None and var_oran >= 0.5:
        olgusal.append("varlik")
    if celiski:
        sinif = "contradicts"
    elif sag and all(sag.values()) and icerik_oran >= ICERIK_ESIGI:
        sinif = "supported"
    elif olgusal:
        sinif = "partial"
    elif sag.get("olay") or (var_oran or 0) > 0:
        sinif = "mention"
    else:
        sinif = "no_evidence"
    return {"destek_sinifi": sinif, "atomlar": sag, "icerik_orani": round(icerik_oran, 3),
            "varlik_orani": None if var_oran is None else round(var_oran, 3), "celiski": celiski}


_ONCELIK = {"supported": 4, "contradicts": 3, "partial": 2, "mention": 1, "no_evidence": 0}


def degerlendir(pencereler: list[str], iddia: dict) -> dict:
    a = atomlar(iddia)
    a["_olcu"] = {d: _olcu_turu(iddia.get("metin", ""), i) for d, i in _sayilar(iddia.get("metin", ""))}
    a["_olay_yili"] = _olay_yili_bagli(_tokenler(iddia.get("metin", "")), a["olay"])
    en = None
    for w in pencereler:
        r = pencere_degerlendir(w, a)
        puan = (_ONCELIK[r["destek_sinifi"]], sum(1 for v in r["atomlar"].values() if v), r["icerik_orani"])
        if en is None or puan > en[0]:
            en = (puan, r, w)
    atom_ozet = {k: (v if k != "varlik" else [x["ad"] for x in v]) for k, v in a.items() if not k.startswith("_") and v}
    if en is None:
        return {"destek_sinifi": "no_evidence", "atomlar": {}, "iddia_atomlari": atom_ozet, "icerik_orani": 0.0,
                "varlik_orani": None, "celiski": [], "supporting_excerpt": ""}
    _, r, w = en
    return dict(r, iddia_atomlari=atom_ozet, supporting_excerpt=w[:400])
