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

Faz-57 çelişki yanlış pozitif korumaları (yalnızca çelişki taramasını daraltır):
- Kaynakça / dipnot pencereleri (`kaynakca_mi`: "↑ Yazar (1986).", ISBN, "222-223, 272" sayfa listesi, "[dipnot …]",
  BİBLİYOGRAFYA başlığı…) yıl/gün-ay/sayı çelişkisi üretmez.
- Genel olay sözcükleri (savaş, muharebe, battle, war…) tek başına olay bağlamı ve yıl çelişkisi tetikleyicisi
  değildir. Yıl, yalnızca konuya ÖZGÜ olay adına bağlıysa olayın yılı sayılır; "<Başka Ad> Savaşı (yıl)" kalıbında
  yıl o başka olaya bağlanır.
- Sayı çelişkisi: değer + ölçü türü (kelime sınırıyla: "men" ≠ "document") + tarihsel özne/taraf (aynı yan cümlede
  en yakın özel ad) + olay (yan cümlede iddiada olmayan bir yıl varsa başka olay) birlikte eşleşmelidir. Taraf
  bilinmiyorsa çelişki işaretlenmez.
- OCR rakam onarımı (`ocr_rakam_normalize`): yalnızca DOĞRULAMA KOPYASINDA ve güçlü rakam/tarih bağlamında `ı → 1`
  ("ı473", "ı ı Ağustos"). Uzunluk korunur; pencereler özgün metne birebir eşlenir. OCR'a bağlı pencere çelişki
  üretmez ve tek başına doğrulama kanıtı sayılmaz (`ocr_bagimli`).
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
# Ölçü türü anahtarları KELİME SINIRIYLA eşleşir (katlanmış token): "onek" token başı, "tam" tam token.
# (Faz-56'daki serbest alt dize araması "men"i "document"/"comment" içinde bulup yanlış ölçü veriyordu.)
_OLCU = {
    "ordu": {"onek": ("asker", "ordu", "kuvvet", "suvari", "piyade", "yenicer", "troop", "armie", "soldier", "warrior",
                      "cavalr", "infantr", "janissar", "horsem", "sipahi", "akinci", "nefer", "savasci", "mercenar", "kisi"),
             "tam": ("men", "army", "force", "forces", "person", "persons",
                     "people", "strength", "host", "atli", "atlisi", "atliyla")},
    "kayip": {"onek": ("kayip", "kayb", "sehit", "casualt", "killed", "slain", "losses", "fatalit", "telef", "maktul"),
              "tam": ("olu", "olusu", "oluler", "olum", "dead", "death", "deaths", "loss", "kaybi")},
}
_CARPAN = {"bin": 1000, "thousand": 1000, "milyon": 1_000_000, "million": 1_000_000}
# Olay AŞAMASI / birlik bölümü işaretleri (yan cümlede, kelime başı eşleşmesi). Farklı aşama → karşılaştırılmaz.
_ASAMA = {"oncu": ("oncu", "vanguard", "advance"), "kanat": ("kanat", "wing", "flank"),
          "takip": ("takip", "pursu", "ricat", "retreat"), "garnizon": ("garnizon", "garris", "muhafiz"),
          "takviye": ("takviye", "reinforc", "auxiliar"), "pusu": ("pusu", "ambush", "baskin")}
# Sayının SAĞINDA özne aranırken arada bulunabilecek sözcükler ("5,000 men of X", "100,000-strong X army").
# Başka bir sözcük (fiil vb.) gelirse sağda aranmaz: "60,000 … began to harass X's forces" → X nesnedir, özne değil.
_SAG_GECIRGEN = {"of", "from", "under", "strong", "guclu", "kadar", "civarinda", "yaklasik", "about", "some", "around",
                 "nearly", "over", "more", "than", "fazla", "askin", "the", "an", "a", "his", "its", "their"}
_GENEL_OLAY = {"savas", "muhar", "battl", "war", "wars", "harbi", "harp", "siege", "kusat", "sefer", "campa", "catis",
               "confl", "meyda", "ceng"}
_ILISKI = {"ardindan", "sonra", "sonrasinda", "sonraki", "once", "oncesinde", "onceki", "after", "before", "following",
           "since", "until", "kadar", "itibaren", "later", "earlier", "yil", "yillar", "years"}
_BAGLAC = {"ve", "and", "while", "whereas", "iken", "but", "ancak", "fakat", "oysa", "whilst"}
_DURAK = set("""ve ile bir bu da de icin olarak olan daha sonra ancak gibi kadar cok en ki ise veya ya hem the a an of
and in on at to by for with from was were is are as that which this his her its their it be been had has have after
before during into than also not yilinda tarihinde arasinda yapilan yapildi""".split())


def katla(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").replace("İ", "I").replace("ı", "i")).encode("ascii", "ignore").decode()
    return s.lower()


def _tokenler(s: str) -> list[str]:
    # kıvrık kesme işareti ASCII katlamada düşer ("1473’te" → "1473te"); önce boşluğa çevrilir
    return re.findall(r"[a-z0-9]+", katla((s or "").replace("’", " ").replace("‘", " ")))


def _sayilar(s: str) -> list[tuple[int, int]]:
    """(değer, token konumu): yıl olmayan ≥ 50 rakamlar. "40 bin" / "40 thousand" → 40000."""
    out = []
    kel = re.findall(r"\d{1,3}(?:[.,]\d{3})+|\d+|[^\W\d_]+", s)
    for i, t in enumerate(kel):
        if t[:1].isdigit():
            ham = re.sub(r"[.,]", "", t)
            d = int(ham)
            carpan = _CARPAN.get(katla(kel[i + 1])) if i + 1 < len(kel) and "." not in t and "," not in t else None
            if carpan and d < 1000:
                d *= carpan
            elif _YIL.fullmatch(ham):
                continue
            if d >= 50:
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


def ozgul_olay(olay: list[str]) -> list[str]:
    """Konuya özgü olay kökleri (genel 'savaş/muharebe/battle/war…' kökleri çıkarılmış)."""
    return [o for o in olay if o not in _GENEL_OLAY]


def _olay_capalari(tok: list[str], ozgul: list[str]) -> list[tuple[int, int, bool]]:
    """(baş, son, bizim_olay_mi) olay adı aralıkları. Bizim olay: özgül olay kökü (ardından gelen genel sözcükle
    birlikte: '<ad> savaşı'). Başka olay: genel olay sözcüğünün hemen önündeki ad ('<ad> savaşı') ya da 'battle/war of
    <ad>' kalıbı."""
    cap = []
    for i, t in enumerate(tok):
        if t[:5] in ozgul:
            son = i + 1 if i + 1 < len(tok) and tok[i + 1][:5] in _GENEL_OLAY else i
            bas = i - 2 if i >= 2 and tok[i - 1] in ("of", "at") and tok[i - 2][:5] in _GENEL_OLAY else i
            cap.append((bas, son, True))
    for k, t in enumerate(tok):
        if t[:5] not in _GENEL_OLAY:
            continue
        for a, (bas, son) in ([(k - 1, (k - 1, k))] if k > 0 else []) + (
                [(k + 2, (k, k + 2))] if k + 2 < len(tok) and tok[k + 1] in ("of", "at") else []):
            x = tok[a]
            if x.isdigit() or len(x) < 3 or x in _DURAK or x in _ILISKI or x[:5] in _GENEL_OLAY or x[:5] in ozgul:
                continue
            cap.append((bas, son, False))
    return cap


def _olay_yili_bagli(tok: list[str], olay: list[str]) -> list[int]:
    """Konuya ÖZGÜ olay adına bağlı yıllar: yıl olay adı aralığından en çok 3 sözcük uzakta, arada ilişki sözcüğü
    ('ardından/sonra/önce/after…') ya da başka yıl yok, ve yıla en yakın olay adı bizim olayımız (eşit uzaklıkta başka
    bir olay adı varsa bağlanmaz). 'Savaşın ardından 1502'de' → 1502 savaşın yılı değildir; '<Başka> Savaşı (1514)' →
    1514 başka olayın. Yalnız genel olay sözcüğü (savaş, battle…) varsa hiçbir yıl bağlanmaz."""
    ozgul = ozgul_olay(olay)
    if not ozgul:
        return []
    cap = _olay_capalari(tok, ozgul)
    out = []
    for j, t in enumerate(tok):
        if not (t.isdigit() and _YIL.fullmatch(t)):
            continue
        yakin = []
        for bas, son, biz in cap:
            if bas <= j <= son:
                continue
            d = j - son if j > son else bas - j
            if d <= 3:
                ara = tok[son + 1: j] if j > son else tok[j + 1: bas]
                if not (set(ara) & _ILISKI) and not any(x.isdigit() and _YIL.fullmatch(x) for x in ara):
                    yakin.append((d, biz))
        if not yakin:
            continue
        en = min(d for d, _ in yakin)
        if {biz for d, biz in yakin if d == en} == {True}:
            out.append(int(t))
    return out


# ------------------------------------------------------------------ kaynakça / dipnot tespiti

_KAYNAKCA_BASI = re.compile(
    r"^\s*(?:[↑^]|\[dipnot|\[\d{1,3}\]\s|(?:bibliyografya|bibliography|kaynakça|kaynakca|kaynaklar|references|"
    r"notlar|notes|dipnotlar|further reading|ek okuma)\s*(?::|$))", re.I)
_SAYFA_LISTESI = re.compile(r"\b\d{1,4}\s?[-–]\s?\d{1,4},\s\d{1,4}\b")
_KAYNAKCA_ZAYIF = (re.compile(r"\(\d{4}[a-z]?\)\s?[.,:]"), re.compile(r"\(PDF\)", re.I),
                   re.compile(r"\b(?:pp?|ss?|vol|cilt|c|nr|no)\.\s?[IVXLC\d]", re.I), re.compile(r"\bdoi\b|doi\.org", re.I),
                   re.compile(r"\b(?:Retrieved|Erişim tarihi|Erişim|Archived|Arşivlendi|Accessed)\b", re.I),
                   re.compile(r"\b(?:ed|eds|yay|nşr|trc|haz|çev|trans)\.", re.I),
                   re.compile(r"\b(?:Yayınları|Yayınevi|Press|Kitabevi|Matbaası|Basımevi|Verlag)\b"),
                   re.compile(r"\b\d{1,4}\s?[-–]\s?\d{1,4}\b(?!\s*(?:yıl|years?))"))


def kaynakca_mi(metin: str) -> bool:
    """Kaynakça / dipnot / atıf satırı mı? Güçlü işaret (↑, [dipnot, BİBLİYOGRAFYA:, ISBN, '222-223, 272' sayfa
    listesi) tek başına yeter; zayıf işaretlerden (yayın yılı '(1986).', '(PDF)', 's./pp./vol.', 'doi', 'Erişim',
    'yay./ed.', yayınevi, sayfa aralığı) en az ikisi gerekir."""
    m = metin or ""
    if _KAYNAKCA_BASI.search(m) or re.search(r"\bISBN\b", m) or _SAYFA_LISTESI.search(m):
        return True
    return sum(1 for d in _KAYNAKCA_ZAYIF if d.search(m)) >= 2


# ------------------------------------------------------------------ OCR rakam onarımı (yalnız doğrulama kopyası)

_AY_ADLARI = ("ocak", "şubat", "mart", "nisan", "mayıs", "haziran", "temmuz", "ağustos", "eylül", "ekim", "kasım",
              "aralık", "subat", "mayis", "agustos", "eylul", "kasim", "aralik", "january", "february", "march", "april",
              "may", "june", "july", "august", "september", "october", "november", "december")
_AY_DESEN = "|".join(sorted({x for a in _AY_ADLARI for x in (a, a.upper(), a.replace("i", "İ").upper(), a.capitalize())},
                            key=len, reverse=True))
_OCR_TOKEN = re.compile(r"(?<!\w)(?=[ı\d]*ı)(?=[ı\d]*\d)[ı\d]{2,4}(?!\w)")
_OCR_GUN_CIFT = re.compile(r"(?<!\w)ı ?ı(?=\s+(?:" + _AY_DESEN + r")(?!\w))")
_OCR_GUN_TEK = re.compile(r"(?<!\w)ı(?=\s+(?:" + _AY_DESEN + r")(?!\w))")


def ocr_rakam_normalize(metin: str) -> tuple[str, list[dict]]:
    """(doğrulama_kopyası, düzeltmeler). Özgün metin DEĞİŞMEZ. Uzunluk korunur (karakter karakter eşleme):
    - rakam içeren ı/rakam tokenı: 'ı473' → '1473' (3-4 hane yalnızca geçerli yıl olursa; 2 hane yalnızca ay adından
      önce gün olarak);
    - ay adından önce tek başına 'ı' / 'ı ı' / 'ıı': '1' / '11 ' / '11'.
    Normal Türkçe sözcüklerdeki ı'ya dokunulmaz (sözcük içinde rakam yoksa token kuralı uygulanmaz)."""
    if not metin or "ı" not in metin:
        return metin, []
    duz: list[dict] = []
    ks = list(metin)

    def _koy(bas: int, eski: str, yeni: str):
        ks[bas: bas + len(eski)] = list(yeni)
        duz.append({"konum": bas, "eski": eski, "yeni": yeni.strip()})

    for m in _OCR_GUN_CIFT.finditer(metin):
        _koy(m.start(), m.group(0), "11" + " " * (len(m.group(0)) - 2))
    ara = "".join(ks)
    for m in _OCR_GUN_TEK.finditer(ara):
        _koy(m.start(), m.group(0), "1")
    ara = "".join(ks)
    for m in _OCR_TOKEN.finditer(ara):
        t = m.group(0)
        y = t.replace("ı", "1")
        sonra = ara[m.end(): m.end() + 12].strip()
        if len(t) >= 3 and _YIL.fullmatch(y):
            _koy(m.start(), t, y)
        elif len(t) == 2 and 1 <= int(y) <= 31 and re.match(r"(?:" + _AY_DESEN + r")(?!\w)", sonra):
            _koy(m.start(), t, y)
    yeni = "".join(ks)
    assert len(yeni) == len(metin)
    return yeni, sorted(duz, key=lambda d: d["konum"])


# ------------------------------------------------------------------ sayı bağlamı: ölçü + taraf + olay yılı

_TOK_NOKTALI = re.compile(r"\d{1,3}(?:[.,]\d{3})+|\d+|[^\W\d_][\w'’]*|[;:]|,(?=\s)|[.!?](?=\s|$)")


def _olcu_kelime(t: str) -> str | None:
    k = katla(re.split(r"['’]", t)[0])
    for tur, d in _OLCU.items():
        if k in d["tam"] or any(k.startswith(o) for o in d["onek"]):
            return tur
    return None


def _taraf_adayi(t: str, haric=frozenset()) -> bool:
    ad = re.split(r"['’]", t)[0]
    k = katla(ad)
    return (ad[:1].isupper() and k[:5] not in haric and len(ad) >= 2 and not ad[:1].isdigit() and k not in _DURAK and k not in _AYLAR
            and k not in _UNVAN and k not in _ILISKI and k not in _BAGLAC and _olcu_kelime(ad) is None
            and k[:5] not in _GENEL_OLAY)


def sayi_baglamlari(metin: str, haric=frozenset()) -> list[dict]:
    """Yıl olmayan ≥ 50 rakamlar için {deger, olcu, taraf, yillar}. Hepsi AYNI YAN CÜMLEDE aranır (sınır: . ; : ', '
    ve/and/while/iken/ancak…):
    - olcu: sayıdan sonraki ya da önceki en çok 3 sözcükte kelime sınırıyla eşleşen ölçü sözcüğü (ordu/kayip);
    - taraf: önce sağda bitişik nitelemedeki özel ad ("5,000 men of X"; araya fiil girerse sağda aranmaz — nesne özne
      sayılmaz), yoksa soldaki en yakın özel ad kökü; olay adları (`haric` kökleri) taraf sayılmaz; kısa bir adla
      bitişik özel ad birleşik kök de verir ('Kara Kale' → 'karak');
    - yillar: yan cümledeki yıllar (iddiada olmayan bir yıl → başka olay);
    - asama: yan cümledeki olay aşaması / birlik bölümü işaretleri (öncü, kanat, takip, garnizon, takviye, pusu);
      aşaması farklı rakamlar karşılaştırılmaz."""
    tok = _TOK_NOKTALI.findall(metin or "")
    sinir = [i for i, t in enumerate(tok) if t in (";", ":", ",", ".", "!", "?") or katla(t) in _BAGLAC]
    out = []
    for i, t in enumerate(tok):
        if not t[:1].isdigit():
            continue
        ham = re.sub(r"[.,]", "", t)
        d = int(ham)
        carpan = _CARPAN.get(katla(tok[i + 1])) if i + 1 < len(tok) and "." not in t and "," not in t else None
        if carpan and d < 1000:
            d *= carpan
        elif _YIL.fullmatch(ham):
            continue
        if d < 50:
            continue
        bas = max([b for b in sinir if b < i], default=-1) + 1
        son = min([b for b in sinir if b > i], default=len(tok))
        olcu = None
        for j in list(range(i + 1, min(son, i + 4))) + list(range(i - 1, max(bas, i - 4) - 1, -1)):
            if not tok[j][:1].isdigit():
                olcu = _olcu_kelime(tok[j])
                if olcu:
                    break
        taraf: set[str] = set()
        sag = []   # sağda yalnızca bitişik nitelemede ("5,000 men of X") özne aranır; fiil vb. görülünce durulur
        for j in range(i + 1, min(son, i + 9)):
            k_ = katla(re.split(r"['’]", tok[j])[0])
            if _taraf_adayi(tok[j], haric):
                sag.append(j)
                break
            if not (k_ in _SAG_GECIRGEN or k_ in _CARPAN or _olcu_kelime(tok[j]) or tok[j][:1].isdigit()):
                break
        sira = sag + list(range(i - 1, max(bas, i - 9) - 1, -1))
        for j in sira:
            if _taraf_adayi(tok[j], haric):
                ad = re.split(r"['’]", tok[j])[0]
                if len(ad) >= 3:
                    taraf.add(katla(ad)[:5])
                for k in (j - 1, j + 1):   # kısa ilk adla bitişik özel ad: birleşik kök ('Ak Koyun…' → 'akkoy')
                    if bas <= k < son and k != i and _taraf_adayi(tok[k], haric):
                        a, b = (tok[k], tok[j]) if k < j else (tok[j], tok[k])
                        a, b = re.split(r"['’]", a)[0], re.split(r"['’]", b)[0]
                        if len(katla(a)) < 5:
                            taraf.add(katla(a + b)[:5])
                if taraf:
                    break
        yillar = {int(x) for x in tok[bas:son] if x.isdigit() and _YIL.fullmatch(x)}
        kk = [katla(x) for x in tok[bas:son]]
        asama = frozenset(e for e, onek in _ASAMA.items() if any(x.startswith(o) for x in kk for o in onek))
        out.append({"deger": d, "olcu": olcu, "taraf": taraf, "yillar": yillar, "asama": asama})
    return out


def _olcu_turu(metin: str, konum: int) -> str | None:
    """Geriye dönük uyum: _sayilar konumundaki sayının ölçü türü (kelime sınırlı)."""
    kel = re.findall(r"\d{1,3}(?:[.,]\d{3})+|\d+|[^\W\d_]+", metin)
    for j in list(range(konum + 1, min(len(kel), konum + 4))) + list(range(konum - 1, max(-1, konum - 4), -1)):
        if not kel[j][:1].isdigit():
            t = _olcu_kelime(kel[j])
            if t:
                return t
    return None


def pencere_degerlendir(w: str, a: dict, kaynakca: bool | None = None, ocr: bool = False) -> dict:
    """kaynakca: pencere kaynakça/dipnot paragrafından mı (None → pencerenin kendisine bakılır). ocr: pencere OCR
    rakam onarımı içeriyor mu. İkisi de çelişki taramasını kapatır; destek sınıflaması etkilenmez."""
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
    ozgul = ozgul_olay(a["olay"])
    if a["olay"]:   # konuya özgü terim varsa olay bağlamı YALNIZ onunla kurulur (genel 'savaş' yetmez)
        sag["olay"] = any(o in kok5 for o in (ozgul or a["olay"]))
    if a["sonuc"]:
        sag["sonuc"] = bool(set(a["sonuc"]) & _gruplar(w, _SONUC))
    if a["yorum"]:
        sag["yorum"] = set(a["yorum"]) <= _gruplar(w, _YORUM)
    icerik_oran = (sum(c in kok5 for c in a["icerik"]) / len(a["icerik"])) if a["icerik"] else 1.0

    # çelişki: aynı olay bağlamında (özgül olay terimi ya da varlıkların çoğu) farklı yıl / gün-ay / aynı ölçü+taraf+
    # olayda farklı rakam. Kaynakça/dipnot ve OCR onarımlı pencereler çelişki üretmez.
    if kaynakca is None:
        kaynakca = kaynakca_mi(w)
    baglam = (any(o in kok5 for o in ozgul) or (var_oran is not None and var_oran >= 0.5)) and not kaynakca and not ocr
    celiski = []
    if baglam and a["yil"] and not sag["yil"] and a.get("_olay_yili"):
        # yalnızca iddianın olay yılı (özgül olay adına bağlı yıl) ile kaynağın olay yılı farklıysa çelişki
        kaynak_olay_yili = _olay_yili_bagli(tok, a["olay"])
        if kaynak_olay_yili and not (set(kaynak_olay_yili) & set(a["_olay_yili"])):
            celiski.append("yil")
    if baglam and a["gun_ay"] and sag.get("yil") and not sag["gun_ay"] and _gun_ay(w):
        celiski.append("gun_ay")
    if baglam and a.get("_sayi_baglam"):
        pb = sayi_baglamlari(w, frozenset(a["olay"]))
        iddia_yil = set(a["yil"])
        for c in a["_sayi_baglam"]:
            if c["olcu"] not in ("ordu", "kayip") or not c["taraf"]:
                continue   # ölçüsü ya da öznesi belirsiz rakam karşılaştırılmaz
            aday = [x for x in pb if x["olcu"] == c["olcu"] and x["taraf"] & c["taraf"] and not (x["yillar"] - iddia_yil)
                    and x["asama"] == c["asama"]]
            if aday and all(x["deger"] != c["deger"] for x in aday):
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


def degerlendir(pencereler: list, iddia: dict) -> dict:
    """pencereler: str listesi; öğeler `kaynakca` / `ocr` / `orijinal` öznitelikleri taşıyabilir
    (kaynak_dogrulayici.Pencere). OCR onarımlı en iyi pencere için özgün pencere de değerlendirilir: sınıf ancak
    OCR sayesinde yükseliyorsa `ocr_bagimli=True` (tek başına doğrulama kanıtı sayılmaz). Alıntı özgün metinden."""
    m = iddia.get("metin", "")
    a = atomlar(iddia)
    a["_olcu"] = {d: _olcu_turu(m, i) for d, i in _sayilar(m)}
    a["_olay_yili"] = _olay_yili_bagli(_tokenler(m), a["olay"])
    a["_sayi_baglam"] = sayi_baglamlari(m, frozenset(a["olay"]))
    def _sec(a_):
        en_, sayi_var = None, False
        for w in pencereler:
            r = pencere_degerlendir(w, a_, kaynakca=getattr(w, "kaynakca", None), ocr=bool(getattr(w, "ocr", False)))
            sayi_var = sayi_var or bool(r["atomlar"].get("sayi"))
            puan = (_ONCELIK[r["destek_sinifi"]], sum(1 for v in r["atomlar"].values() if v), r["icerik_orani"])
            if en_ is None or puan > en_[0]:
                en_ = (puan, r, w)
        return en_, sayi_var
    en, sayi_var = _sec(a)
    if en is not None and "sayi" in en[1]["celiski"] and sayi_var:
        # Aynı kaynak iddianın rakamını başka bir yerde de veriyor: kaynaktaki farklı rakam büyük olasılıkla farklı
        # bağlama ait; tek başına sayı çelişkisi sayılmaz (yıl/gün-ay çelişkisi korunur)
        en, _ = _sec(dict(a, _sayi_baglam=[]))
    atom_ozet = {k: (v if k != "varlik" else [x["ad"] for x in v]) for k, v in a.items() if not k.startswith("_") and v}
    if en is None:
        return {"destek_sinifi": "no_evidence", "atomlar": {}, "iddia_atomlari": atom_ozet, "icerik_orani": 0.0,
                "varlik_orani": None, "celiski": [], "supporting_excerpt": "", "kaynakca_penceresi": False,
                "ocr_duzeltmeli": False, "ocr_bagimli": False}
    _, r, w = en
    ocr = bool(getattr(w, "ocr", False))
    ozgun = getattr(w, "orijinal", None) or w
    ocr_bagimli = False
    if ocr:
        r0 = pencere_degerlendir(ozgun, a, kaynakca=getattr(w, "kaynakca", None), ocr=True)
        ocr_bagimli = _ONCELIK[r0["destek_sinifi"]] < _ONCELIK[r["destek_sinifi"]]
    return dict(r, iddia_atomlari=atom_ozet, supporting_excerpt=str(ozgun)[:400],
                kaynakca_penceresi=bool(getattr(w, "kaynakca", None) if getattr(w, "kaynakca", None) is not None
                                        else kaynakca_mi(w)),
                ocr_duzeltmeli=ocr, ocr_bagimli=ocr_bagimli)
