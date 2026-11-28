"""Kaynak keşfi, kaynak bağımsızlığı ve sayısal iddia koruması → doğrulanmış araştırma havuzu.

İlke: LLM'in kendi hafızası tarihsel araştırma kabul EDİLMEZ. Sistem önce dış kaynakları keşfeder ve doğrular, sonra
statüleri işaretlenmiş havuzu LLM'e senaryolaştırması için verir.

- Keşif: `KaynakKesifSaglayici` soyut arayüzü. İlk uygulama `WikipediaKesif`'tir (TR ve EN MediaWiki API, REST
  özet uç noktası). Çektikleri: ana madde, bölüm başlıkları, dil bağlantıları ve kaynakçadaki dış bağlantılar
  (aday olarak). Arayüz, ileride arama motoru ya da akademik API eklenebilecek biçimdedir.
- Tür ve öncelik: birincil_arsiv (4) > akademik (3) > ansiklopedi (2) > genel_web (1).
- Bağımsızlık: Aynı yayıncı (TR ve EN Wikipedia → tek yayıncı, Wikimedia) ya da metin benzerliği (5'li kelime
  zinciri örtüşmesi; Wikipedia kopyası siteler) aynı kümeye düşer. `bagimsiz_kaynak_sayisi` kaynak sayısı değil,
  küme sayısıdır.
- Sayısal koruma (ordu büyüklüğü, kayıp, tarih):
  - Tek bağımsız kümeden gelen sayısal iddia `tek_kaynak_uyarisi: true` alır ve tartışmalı sayılır; kesin
    anlatılamaz.
  - Farklı kümelerden gelen farklı rakamlar ayrı ayrı tutulur. ASLA ortalama alınmaz. Kayıt `tartismali` olur ve
    anlatımda "kaynaklar farklı rakamlar aktarmaktadır" ifadesi zorunludur (Validation Gate denetler).
  - Ölçü türü eşleştirmesi bilerek temkinlidir: aynı ölçü türündeki farklı rakamlar, farklı taraflara ait olsalar
    bile tartışmalı işaretlenir. Bu yanlış "kesin" anlatımdan daha güvenlidir.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.parse
from abc import ABC, abstractmethod

from motor.orkestrasyon.kaynak_dogrulayici import (_YIL, YONTEM, GuvenliIstemci, KaynakDogrulayici, _katla, html_metin,
                                                   icerik_dogrula, url_gizle, varliklar)

ONCELIK = {"birincil_arsiv": 4, "akademik": 3, "ansiklopedi": 2, "genel_web": 1}
CELISKI_IFADESI = "kaynaklar farklı rakamlar aktarmaktadır"
_AKADEMIK = ("doi.org", "jstor.org", "dergipark.org.tr", "academia.edu", "researchgate.net", "persee.fr", "brill.com",
             "cambridge.org", "oup.com", "tandfonline.com", "springer.com", "islamansiklopedisi.org.tr", "books.google",
             "openedition.org", "muse.jhu.edu", "semanticscholar.org")
_ARSIV = ("archive.org", "devletarsivleri.gov.tr", "gallica.bnf.fr", "loc.gov", "europeana.eu", "wdl.org",
          "digitale-sammlungen.de", "e-codices.ch")
# Ölçü türü ve taraf (özne) tespiti iddia_atom.sayi_baglamlari'ndadır: kelime sınırlı ölçü + aynı yan cümlede özne.


def ozgun_url(url: str) -> str:
    """web.archive.org/web/<zaman>/<özgün> → özgün URL (anlık görüntü yayıncıyı/türü değiştirmez)."""
    m = re.match(r"https?://web\.archive\.org/web/\d+[a-z_]*/(.+)$", url, re.I)
    if m:
        o = m.group(1)
        return o if re.match(r"https?://", o, re.I) else "http://" + o
    return url


def kaynak_turu(url: str) -> str:
    url = ozgun_url(url)
    h = (urllib.parse.urlsplit(url).hostname or "").lower()
    if any(h == d or h.endswith("." + d) or d in h for d in _ARSIV):
        return "birincil_arsiv"
    if any(h == d or h.endswith("." + d) or d in h for d in _AKADEMIK) or h.endswith(".edu") or ".edu." in h or ".ac." in h:
        return "akademik"
    if h.endswith("wikipedia.org") or h.endswith("wikimedia.org") or h.endswith("wikidata.org"):
        return "ansiklopedi"
    return "genel_web"


def yayinci(url: str) -> str:
    h = (urllib.parse.urlsplit(ozgun_url(url)).hostname or "").lower()
    if h.endswith("wikipedia.org") or h.endswith("wikimedia.org") or h.endswith("wikidata.org"):
        return "Wikimedia"   # TR ve EN Wikipedia aynı yayıncı: birbirinden bağımsız sayılmaz
    parca = h.split(".")
    return ".".join(parca[-3:]) if len(parca) >= 3 and parca[-2] in ("com", "org", "gov", "edu", "ac", "co") else ".".join(parca[-2:])


# ------------------------------------------------------------------ keşif arayüzü

def koordinat(sayfa: dict) -> dict | None:
    """Faz-66: Wikipedia 'coordinates' özelliğinden birincil (yoksa ilk) dünya koordinatı; geçersizse None."""
    ks = [c for c in sayfa.get("coordinates") or [] if isinstance(c, dict) and c.get("globe", "earth") == "earth"]
    c = next((c for c in ks if c.get("primary") not in (None, False)), ks[0] if ks else None)
    try:
        enlem, boylam = float(c["lat"]), float(c["lon"])
    except (TypeError, KeyError, ValueError):
        return None
    return {"enlem": enlem, "boylam": boylam} if -90 <= enlem <= 90 and -180 <= boylam <= 180 else None


class KaynakKesifSaglayici(ABC):
    ad = "soyut"

    @abstractmethod
    def kesfet(self, konu: str) -> list[dict]:
        """Kaynak listesi: {id, url, baslik, yayinci, tur, oncelik, dil?, metin?, aday?: bool}"""


class WikipediaKesif(KaynakKesifSaglayici):
    ad = "wikipedia"

    def __init__(self, istemci: GuvenliIstemci | None = None, diller=("tr", "en"), dis_baglanti_sayisi: int = 12):
        self.istemci = istemci or GuvenliIstemci()
        self.diller, self.dis_baglanti_sayisi = diller, dis_baglanti_sayisi
        self.log: list[str] = []

    def _json(self, url: str) -> dict:
        y = self.istemci.getir(url)
        if y.durum != 200:
            raise RuntimeError(f"HTTP {y.durum}: {url_gizle(url)}")
        return json.loads(y.govde.decode("utf-8"))

    def _api(self, dil: str, **p) -> dict:
        p.update({"format": "json", "formatversion": "2"})
        return self._json(f"https://{dil}.wikipedia.org/w/api.php?" + urllib.parse.urlencode(p))

    def _ara(self, dil: str, konu: str) -> str | None:
        d = self._api(dil, action="query", list="search", srsearch=konu, srlimit=1)
        s = d.get("query", {}).get("search", [])
        return s[0]["title"] if s else None

    def _madde(self, dil: str, baslik: str) -> dict | None:
        d = self._api(dil, action="query", prop="extracts|info|extlinks|langlinks|coordinates", titles=baslik, redirects=1,
                      explaintext=1, exsectionformat="wiki", inprop="url", ellimit=200, lllimit=50)
        sayfalar = d.get("query", {}).get("pages", [])
        if not sayfalar or sayfalar[0].get("missing"):
            return None
        return sayfalar[0]

    def _ozet(self, dil: str, baslik: str) -> str:
        try:
            d = self._json(f"https://{dil}.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(baslik.replace(" ", "_")))
            return d.get("extract", "")
        except Exception as e:   # özet isteğe bağlı; madde metni zaten var
            self.log.append(f"ozet {dil}: {type(e).__name__}")
            return ""

    def kesfet(self, konu: str) -> list[dict]:
        out, basliklar = [], {}
        for dil in self.diller:
            try:
                b = basliklar.get(dil) or self._ara(dil, konu)
                if not b:
                    self.log.append(f"{dil}: madde bulunamadı")
                    continue
                m = self._madde(dil, b)
                if not m:
                    continue
                for ll in m.get("langlinks", []):   # diğer dil maddesi: TR başlığını EN'de aramak yerine dil bağlantısı
                    if ll.get("lang") in self.diller and ll.get("lang") not in basliklar:
                        basliklar[ll["lang"]] = ll.get("title")
                metin = m.get("extract", "")
                bolumler = re.findall(r"^==+\s*(.+?)\s*==+\s*$", metin, re.M)
                out.append({"id": f"wp_{dil}_{m['pageid']}", "url": m.get("fullurl") or f"https://{dil}.wikipedia.org/wiki/{b}",
                            "baslik": m.get("title", b), "yayinci": "Wikimedia", "tur": "ansiklopedi",
                            "oncelik": ONCELIK["ansiklopedi"], "dil": dil, "metin": re.sub(r"^==+.*?==+\s*$", "", metin, flags=re.M),
                            "bolumler": bolumler, "ozet": self._ozet(dil, m.get("title", b)), "aday": False,
                            **({"koordinat": kd} if (kd := koordinat(m)) else {})})
                dis = sorted({e.get("url", "") if isinstance(e, dict) else str(e) for e in m.get("extlinks", [])} - {""},
                             key=lambda u: (-ONCELIK[kaynak_turu(u)], u))
                for u in dis[: self.dis_baglanti_sayisi]:
                    if urllib.parse.urlsplit(u).scheme not in ("http", "https"):
                        continue
                    t = kaynak_turu(u)
                    out.append({"id": "web_" + hashlib.sha1(u.encode()).hexdigest()[:10], "url": u, "baslik": u,
                                "yayinci": yayinci(u), "tur": t, "oncelik": ONCELIK[t], "aday": True,
                                "kesif": f"wp_{dil}_{m['pageid']} kaynakçası"})
            except Exception as e:
                self.log.append(f"{dil}: {type(e).__name__}: {str(e)[:120]}")
        tekil = {}
        for k in out:
            tekil.setdefault(k["id"], k)
        return list(tekil.values())


class OpenAlexKesif(KaynakKesifSaglayici):
    """OpenAlex (CC0 akademik meta veri): Wikipedia'dan BAĞIMSIZ akademik kaynak kümesi.

    - Yayın başlığı ve özeti (abstract_inverted_index'ten yeniden kurulur) API metni olarak kullanılır. Özet,
      sayfa getirilmeden doğrudan bağlamsal doğrulamaya girer (`api_metni: true`).
    - Açık erişimli PDF bağlantısı varsa aday olarak eklenir. Bu PDF SSRF korumalı getirilir ve pypdf ile okunur.
    - Anahtar: Şubat 2026'dan beri OpenAlex API anahtarı istiyor (ücretsiz, 0 TL). `OPENALEX_API_KEY` ortam
      değişkeni varsa kullanılır. Yoksa anahtarsız denenir; anahtarsız günlük bütçe çok küçüktür. Anahtar yalnızca
      ortamdan okunur; kaynak URL'lerine ve loglara yazılmaz (url_gizle sorgu değerlerini gizler).
    - 401/403/429 alınırsa sessizce değil, `log` alanında açıkça atlanır; keşif durmaz.
    - Konuyla ilgisiz yayınlar elenir: başlıkta ya da özette konu/ipucu terimi geçmelidir.
    """
    ad = "openalex"
    API = "https://api.openalex.org/works"

    def __init__(self, istemci: GuvenliIstemci | None = None, en_cok: int = 8):
        self.istemci = istemci or GuvenliIstemci()
        self.en_cok = en_cok
        self.log: list[str] = []

    @staticmethod
    def ozet_kur(ters: dict | None) -> str:
        if not isinstance(ters, dict):
            return ""
        konum = [(i, w) for w, yer in ters.items() for i in (yer or []) if isinstance(i, int)]
        return " ".join(w for _, w in sorted(konum))

    def kesfet(self, konu: str, ipuclari: list[str] | tuple = ()) -> list[dict]:
        sorgular = list(dict.fromkeys([konu] + [i for i in ipuclari if i]))[:2]
        terimler = {_katla(w)[:5] for q in sorgular for w in re.findall(r"\w+", q) if len(w) >= 4}
        terimler -= {"savas", "battl", "muhar", "harbi"}   # genel olay sözcükleri tek başına ilgi kanıtı değil
        anahtar = os.environ.get("OPENALEX_API_KEY", "").strip()
        out, gor = [], set()
        for q in sorgular:
            p = {"search": q, "per_page": str(self.en_cok),
                 "select": "id,display_name,publication_year,doi,abstract_inverted_index,primary_location,open_access,language"}
            if anahtar:
                p["api_key"] = anahtar
            url = self.API + "?" + urllib.parse.urlencode(p)
            try:
                y = self.istemci.getir(url)
            except Exception as e:
                self.log.append(f"openalex: {type(e).__name__}: {str(e)[:100]}")
                continue
            if y.durum != 200:
                self.log.append(f"openalex: HTTP {y.durum} ({'API anahtarı/bütçe gerekebilir' if y.durum in (401, 403, 429) else 'atlandı'})")
                continue
            try:
                isler = json.loads(y.govde.decode("utf-8")).get("results", [])
            except (ValueError, AttributeError):
                self.log.append("openalex: yanit_bicimi")
                continue
            for w in isler:
                wid = str(w.get("id", "")).rsplit("/", 1)[-1]
                if not wid or wid in gor:
                    continue
                baslik = w.get("display_name") or ""
                ozet = self.ozet_kur(w.get("abstract_inverted_index"))
                metin = (baslik + ". " + ozet).strip()
                if not any(t in _katla(metin) for t in terimler):
                    continue   # konu dışı yayın
                gor.add(wid)
                pl = w.get("primary_location") or {}
                kaynak = (pl.get("source") or {}) if isinstance(pl, dict) else {}
                yay = kaynak.get("display_name") or kaynak.get("host_organization_name") or (w.get("doi") or "openalex")
                kurl = w.get("doi") or f"https://openalex.org/{wid}"
                out.append({"id": f"oa_{wid}", "url": kurl, "baslik": baslik, "yayinci": f"openalex:{yay}",
                            "tur": "akademik", "oncelik": ONCELIK["akademik"], "metin": metin if ozet else "",
                            "api_metni": bool(ozet), "aday": True, "yil": w.get("publication_year"),
                            "kesif": "OpenAlex özeti" if ozet else "OpenAlex (özet yok)"})
                oa = (w.get("open_access") or {}).get("oa_url") or (pl.get("pdf_url") if isinstance(pl, dict) else None)
                if oa and str(oa).lower().split("?")[0].endswith(".pdf"):
                    out.append({"id": "web_" + hashlib.sha1(oa.encode()).hexdigest()[:10], "url": oa, "baslik": baslik,
                                "yayinci": f"openalex:{yay}", "tur": "akademik", "oncelik": ONCELIK["akademik"],
                                "aday": True, "kesif": f"oa_{wid} açık erişim PDF"})
        return out


# ------------------------------------------------------------------ bağımsızlık

def _zincirler(metin: str, n: int = 5) -> set:
    w = re.findall(r"[a-z0-9]+", _katla(metin))
    return {" ".join(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def benzerlik(a: str, b: str) -> float:
    """Kopya ölçüsü: 5'li kelime zinciri kapsama oranı (küçük metnin büyük metinde ne kadar geçtiği)."""
    za, zb = _zincirler(a), _zincirler(b)
    if min(len(za), len(zb)) < 40:   # kısa/kalıp metin (boş sayfa, menü) kopya kanıtı sayılmaz
        return 0.0
    return len(za & zb) / min(len(za), len(zb))


def bagimsizlik_kumeleri(kaynaklar: list[dict], kopya_esigi: float = 0.5) -> dict[str, int]:
    """kaynak_id → küme no. Aynı yayıncı, kopya metin ya da 'Wikipedia'dan alınmıştır' işareti → aynı küme."""
    ids = [k["id"] for k in kaynaklar]
    ata = {i: i for i in ids}

    def bul(x):
        while ata[x] != x:
            ata[x] = ata[ata[x]]
            x = ata[x]
        return x

    def birlestir(a, b):
        ata[bul(a)] = bul(b)
    for i, a in enumerate(kaynaklar):
        for b in kaynaklar[i + 1:]:
            ayni = a.get("yayinci") and a.get("yayinci") == b.get("yayinci")
            if not ayni and a.get("metin") and b.get("metin"):
                ayni = benzerlik(a["metin"], b["metin"]) >= kopya_esigi
            if ayni:
                birlestir(a["id"], b["id"])
        m = _katla(a.get("metin") or "")
        if a.get("yayinci") != "Wikimedia" and re.search(r"from wikipedia|vikipedi'den|wikipedia'dan|kaynak: vikipedi|source: wikipedia", m):
            wp = next((k["id"] for k in kaynaklar if k.get("yayinci") == "Wikimedia"), None)
            if wp:
                birlestir(a["id"], wp)
    koklar = {}
    return {i: koklar.setdefault(bul(i), len(koklar)) for i in ids}


# ------------------------------------------------------------------ iddia çıkarımı ve sayısal analiz

_SAYI = re.compile(r"(?<![\w.,])(\d{1,3}(?:[.,]\d{3})+|\d+)(?![\w])")


def _sayilar(cumle: str, olay_kokleri=frozenset()) -> list[dict]:
    """Yıl dışı sayılar, ölçü türleri ve taraf (özne) kökleri. Ölçü kelime sınırıyla ve aynı yan cümlede aranır
    (iddia_atom.sayi_baglamlari); 'men' artık 'document' içinde bulunmaz."""
    from motor.orkestrasyon import iddia_atom as ia
    baglam = ia.sayi_baglamlari(cumle, frozenset(olay_kokleri))
    out = []
    kel = re.findall(r"\S+", cumle)
    for i, w in enumerate(kel):
        m = _SAYI.search(w)
        if not m:
            continue
        ham = m.group(1)
        deger = int(re.sub(r"[.,]", "", ham))
        if _YIL.fullmatch(ham) and deger >= 500:
            out.append({"deger": deger, "ham": ham, "olcu_turu": "tarih"})
            continue
        if deger < 50:
            continue   # gün, sıra vb. küçük sayılar ölçü sayılmaz
        b = next((x for x in baglam if x["deger"] == deger and not x.get("_kullanildi")), None)
        if b is not None:
            b["_kullanildi"] = True
        out.append({"deger": deger, "ham": ham, "olcu_turu": (b or {}).get("olcu") or "diger",
                    "taraf": sorted((b or {}).get("taraf") or ()), "asama": sorted((b or {}).get("asama") or ())})
    return out


_KISALTMA = re.compile(r"(?:\b[IVXLC]{1,6}|\b(?:St|Dr|Prof|vb|vs|Hz|bkz|yy|ö|M\.Ö|M\.S|c|ca|cf|no|Bk|Sl|ed|trans|vol|pp))\.$")


def _cumleler(metin: str) -> list[str]:
    """Cümle bölme: "II. Mehmed", "Hz. Ali", "M.Ö." gibi kısaltma/romen rakamı noktalarında bölmez."""
    parcalar = re.split(r"(?<=[.!?])\s+(?=[A-ZÇĞİÖŞÜ0-9\"“])", re.sub(r"\s+", " ", metin))
    out = []
    for p in parcalar:
        if out and _KISALTMA.search(out[-1]):
            out[-1] = out[-1] + " " + p
        else:
            out.append(p)
    return out


def iddialari_cikar(kaynak: dict, en_cok: int = 60, olay_kokleri=frozenset()) -> list[dict]:
    """Ana madde metninden yıl ya da sayı içeren cümleler (deterministik). Her biri tek iddia."""
    metin = kaynak.get("metin") or ""
    out = []
    for c in _cumleler(metin):
        c = c.strip()
        if not 40 <= len(c) <= 400:
            continue
        s = _sayilar(c, olay_kokleri)
        if not s:
            continue
        out.append({"metin": c, "sayilar": s, "yillar": sorted({x["deger"] for x in s if x["olcu_turu"] == "tarih"}),
                    "varliklar": varliklar(c)[:6], "kaynak_id": kaynak["id"]})
        if len(out) >= en_cok:
            break
    return out


def havuz_olustur(konu: str, kaynaklar: list[dict], dogrulayici: KaynakDogrulayici, olay_terimleri: list[str] | None = None,
                  ilerleme=None) -> dict:
    """Kaynaklar + iddialar → planlayıcının araştırma biçiminde havuz (statüler işaretli). LLM kullanılmaz."""
    ilerleme = ilerleme or (lambda *a: None)
    ilerleme("kaynak_dogrulama", f"{len(kaynaklar)} kaynak sayfası paralel getiriliyor (SSRF korumalı)")
    sayim = dogrulayici.onden_getir([k["url"] for k in kaynaklar if not k.get("api_metni")])
    ilerleme("kaynak_dogrulama", f"sayfalar getirildi: {sayim}")
    olay_terimleri = olay_terimleri or [w for w in re.findall(r"\w+", konu) if len(w) >= 4]
    # aday dış kaynaklar canlı (SSRF korumalı) getirilir; metni olanlar hem bağımsızlık (kopya tespiti) hem de
    # kendi iddiaları (farklı rakamlar → çelişki) için kullanılır
    for k in kaynaklar:
        if k.get("aday") and not k.get("metin") and not k.get("api_metni"):
            sinif, kod, metin, neden = dogrulayici.sayfa(k["url"])
            k["erisim"] = {"durum": sinif, "http_status": kod, "neden": neden}
            if sinif == "ok":
                k["metin"] = metin
    kume = bagimsizlik_kumeleri(kaynaklar)
    ana = [k for k in kaynaklar if not k.get("aday") and k.get("metin")]
    adaylar = [k for k in kaynaklar if k.get("aday")]
    terim = [_katla(t)[:5] for t in olay_terimleri]
    iddialar, gor = [], set()
    for k in kaynaklar:
        if not k.get("metin"):
            continue
        for i in iddialari_cikar(k, olay_kokleri=frozenset(terim)):
            # aday dış sayfalardan yalnızca konuyla ilgili (konu terimi geçen) cümleler iddia olur
            if k.get("aday") and not any(t in _katla(i["metin"]) for t in terim):
                continue
            n = " ".join(re.findall(r"[a-z0-9]+", _katla(i["metin"])))
            if n in gor:
                continue
            gor.add(n)
            iddialar.append(i)
    rapor_kaynak = {}
    kayitlar = []
    for n, idd in enumerate(iddialar, 1):
        sorgu = {"metin": idd["metin"], "yillar": idd["yillar"], "varliklar": idd["varliklar"], "olay_terimleri": olay_terimleri}
        destek, karsi = [], []
        for k in ana + adaylar:
            if k.get("api_metni"):   # API'den gelen metin (OpenAlex özeti): sayfa getirilmez, aynı bağlamsal kontrol
                d = dict({"url": url_gizle(k["url"]), "http_status": 200, "verification_method": YONTEM},
                         **icerik_dogrula(k["metin"], sorgu))
            else:
                d = dogrulayici.dogrula(k["url"], sorgu)   # sayfa bir kez getirilir (önbellek), iddia yerelde denetlenir
            # Atomik destek (iddia_atom): yalnız 'supported' tam teyittir. Tarih teyidi: yıl + (iddiada varsa) gün-ay +
            # olay/varlık aynı pencerede; sayı teyidi: aynı rakam aynı pencerede. 'mention' hiçbir teyit sayılmaz.
            at = d.get("atomlar") or {}
            sinif = d.get("destek_sinifi")
            baglam = at.get("olay") is True or at.get("varlik") is True or (at.get("olay") is None and at.get("varlik") is None)
            tarih_teyidi = (sinif in ("supported", "partial") and bool(idd["yillar"]) and at.get("yil") is True
                            and at.get("gun_ay") is not False and baglam and at.get("sayi") is not False)
            sayi_teyidi = sinif in ("supported", "partial") and at.get("sayi") is True and baglam
            ozet_d = {x: d.get(x) for x in ("verification_status", "verification_method", "http_status", "destek_sinifi",
                                           "atomlar", "celiski", "year_match", "event_match", "entity_match",
                                           "number_match", "content_match", "content_score", "supporting_excerpt", "neden",
                                           "kaynakca_penceresi", "ocr_duzeltmeli", "ocr_bagimli")}
            if sinif == "contradicts":
                karsi.append({"id": k["id"], "url": k["url"], "eser": k.get("baslik"), "yayinci": k.get("yayinci"),
                              "tur": k.get("tur"), "kume": kume[k["id"]], "dogrulama": ozet_d})
            elif sinif == "supported" or tarih_teyidi or sayi_teyidi:
                destek.append({"id": k["id"], "url": k["url"], "eser": k.get("baslik"), "yayinci": k.get("yayinci"),
                               "tur": k.get("tur"), "kume": kume[k["id"]], "dogrulama": ozet_d,
                               "teyit_turu": "icerik" if sinif == "supported" else ("yalniz_tarih" if tarih_teyidi else "yalniz_sayi"),
                               "tarih_teyidi": bool(tarih_teyidi or (sinif == "supported" and idd["yillar"])),
                               "sayi_teyidi": bool(sayi_teyidi)})
            rapor_kaynak.setdefault(k["id"], {"url": url_gizle(k["url"]), "tur": k.get("tur"), "yayinci": k.get("yayinci"),
                                              "kume": kume[k["id"]], "sonuclar": {},
                                              "erisim": ({"durum": "ok", "neden_kodu": "api_metni", "http_status": 200}
                                                         if k.get("api_metni") else dict(dogrulayici.erisim.get(k["url"], {})))})
            rapor_kaynak[k["id"]]["sonuclar"][d["verification_status"]] = rapor_kaynak[k["id"]]["sonuclar"].get(d["verification_status"], 0) + 1
            if d.get("destek_sinifi"):
                ds = rapor_kaynak[k["id"]].setdefault("destek", {})
                ds[d["destek_sinifi"]] = ds.get(d["destek_sinifi"], 0) + 1
        ocr_tek_basina_isaretle(destek)
        sayilan = [x for x in destek if not x.get("sayilmadi")]
        icerik_kume = {x["kume"] for x in sayilan if x["teyit_turu"] == "icerik"}
        tum_kume = {x["kume"] for x in sayilan if x.get("tarih_teyidi")}
        sayi_kume = {x["kume"] for x in sayilan if x.get("sayi_teyidi")}
        karsi_kume = {x["kume"] for x in karsi} - icerik_kume
        kayitlar.append({"id": f"ark_{n:03d}", "iddia": idd["metin"], "yil": idd["yillar"][0] if idd["yillar"] else None,
                         "sayilar": idd["sayilar"], "kaynaklar": destek, "kaynak_kesfi": idd["kaynak_id"],
                         "bagimsiz_kaynak_sayisi": len(icerik_kume), "tarih_teyit_kume_sayisi": len(tum_kume),
                         "sayi_teyit_kume_sayisi": len(sayi_kume), "karsi_kaynaklar": karsi,
                         "karsi_kume_sayisi": len(karsi_kume),
                         "iddia_atomlari": _atom_ozeti(sorgu),
                         "tur": ("sayi" if any(s["olcu_turu"] in ("ordu", "kayip") for s in idd["sayilar"])
                                 else "tarih" if idd["yillar"] else "olay"),
                         "olay_id": f"olay_{idd['yillar'][0]}" if idd["yillar"] else "olay_genel"})
    sayisal_koruma(kayitlar)
    for r in rapor_kaynak.values():   # kaynak bazında karar: erişim mi, PDF mi, içerik mi, yetersiz doğrulama mı?
        e, ds = r.get("erisim") or {}, r.get("destek", {})
        if e.get("durum") not in (None, "ok"):
            r["dogrulama_sonucu"] = f"erisilemedi:{e.get('neden_kodu')}"
        elif ds.get("supported"):
            r["dogrulama_sonucu"] = "destekledi"
        elif ds.get("contradicts"):
            r["dogrulama_sonucu"] = "celisti"
        elif ds.get("partial"):
            r["dogrulama_sonucu"] = "dogrulama_yetersiz"   # verification insufficient: yalnız iddia parçaları
        else:
            r["dogrulama_sonucu"] = "icerik_uyusmazligi"   # content mismatch: yalnız anma ya da kanıt yok
    ilerleme("kaynak_dogrulama", f"{len(kayitlar)} iddia denetlendi; durumlar: "
             f"{ {d: sum(k['durum'] == d for k in kayitlar) for d in ('dogrulanmis', 'tartismali', 'belirsiz')} }")
    return {"konu": konu, "kayitlar": kayitlar, "kaynak_raporu": rapor_kaynak,
            "kume_sayisi": len(set(kume.values())), "dogrulama_yontemi": "structured_and_contextual"}


def ocr_tek_basina_isaretle(destek: list[dict]) -> list[dict]:
    """OCR rakam onarımına BAĞLI destek tek başına doğrulama kanıtı sayılmaz: iddianın OCR'sız hiçbir desteği yoksa
    bütün destekler `sayilmadi` ile işaretlenir (küme sayımlarına girmez; iddia doğrulanmış olamaz). OCR'sız en az bir
    destek varsa OCR'a bağlı destekler de sayılır. Yerinde günceller ve listeyi döndürür."""
    if destek and all(x["dogrulama"].get("ocr_bagimli") for x in destek):
        for x in destek:
            x["sayilmadi"] = "ocr_onarimina_bagli_tek_basina"
    return destek


def _atom_ozeti(sorgu: dict) -> dict:
    from motor.orkestrasyon import iddia_atom as ia
    at = ia.atomlar(sorgu)
    return {k: (v if k != "varlik" else [x["ad"] for x in v]) for k, v in at.items() if v and k != "icerik"}


def sayisal_koruma(kayitlar: list[dict]) -> None:
    """Durum ataması (yerinde). Faz-56: atomik destek.
    - Tam destekleyen (supported) küme yok → belirsiz.
    - Ordu/kayıp ölçüsünde AYNI taraf ve olay için kümeler arası farklı rakam → tartismali + celiski. Değerler AYRI
      tutulur, ortalama YOK. (Faz-57: farklı ordulara/birliklere ait rakamlar çelişki değildir.)
    - OCR onarımına bağlı destek tek başına sayılmaz (`sayilmadi`).
    - Bağımsız bir küme çelişiyor (contradicts: farklı yıl/gün-ay/rakam) → tartismali + karsi_kanit.
    - Sayısal iddia (ordu/kayıp ya da ≥ 100 rakam): aynı rakam en az 2 bağımsız kümede değilse tek_kaynak_uyarisi.
    - Tarih iddiası: yıl (ve iddiada varsa gün-ay) en az 2 bağımsız kümede değilse tek_kaynak_uyarisi.
    - Tarihsel yorum (dönüm noktası, belirleyici…): 2 bağımsız kümede tam destek yoksa tek_kaynak_uyarisi.
    - Aksi → dogrulanmis.
    """
    # Kümeler arası sayı çelişkisi yalnızca AYNI ölçü türü + AYNI taraf (özne kökü kesişimi) + AYNI olay (olay_id eşit
    # ya da biri genel) + AYNI aşama için aranır: 'A ordusu 70.000' ile 'B ordusu 40.000' çelişki DEĞİLDİR. Tarafı
    # belirsiz rakamlar karşılaştırılmaz. Aynı kümenin verdiği farklı değerler o kümede çelişki sayılmaz (Faz-58).
    # Değerler ayrı tutulur, ortalama alınmaz.
    girdiler = []
    for k in kayitlar:
        kumeler = {x["kume"] for x in k["kaynaklar"] if not x.get("sayilmadi")
                   and (x["teyit_turu"] == "icerik" or x.get("sayi_teyidi"))}
        for s_ in k["sayilar"]:
            if s_["olcu_turu"] in ("ordu", "kayip") and s_.get("taraf") and kumeler:
                girdiler.append((s_["olcu_turu"], set(s_["taraf"]), k.get("olay_id"), s_["deger"], kumeler,
                                 tuple(s_.get("asama") or ())))

    def _celiski(k):
        for s_ in k["sayilar"]:
            if s_["olcu_turu"] not in ("ordu", "kayip") or not s_.get("taraf"):
                continue
            grup: dict[int, set] = {}
            for tur, taraf, olay, deger, kumeler, asama in girdiler:
                if (tur == s_["olcu_turu"] and taraf & set(s_["taraf"]) and asama == tuple(s_.get("asama") or ())
                        and (olay == k.get("olay_id") or "olay_genel" in (olay, k.get("olay_id")))):
                    grup.setdefault(deger, set()).update(kumeler)
            # Faz-58: AYNI kümede birden çok değer → o küme farklı bağlamları anlatıyor olabilir; karşılaştırmadan çıkar
            cok = {c for c in set().union(*grup.values()) if sum(c in v for v in grup.values()) > 1} if grup else set()
            grup = {v: c - cok for v, c in grup.items() if c - cok}
            tum = set().union(*grup.values()) if grup else set()
            if len(grup) > 1 and len(tum) > 1:
                return s_["olcu_turu"], [{"deger": v, "kume": sorted(c)} for v, c in sorted(grup.items())], sorted(s_["taraf"])
        return None
    for k in kayitlar:
        icerik = [x for x in k["kaynaklar"] if x["teyit_turu"] == "icerik" and not x.get("sayilmadi")]
        k["tek_kaynak_uyarisi"] = False
        olcu = {s_["olcu_turu"] for s_ in k["sayilar"]}
        if not icerik:
            k["durum"] = "belirsiz"
            continue
        c = _celiski(k)
        if c:
            k["durum"] = "tartismali"
            k["celiski"] = {"olcu_turleri": [c[0]], "taraf": c[2], "degerler": c[1],
                            "kural": "ortalama alınmaz; değerler ayrı aktarılır"}
            k["celiski_notu"] = CELISKI_IFADESI
            continue
        if k.get("karsi_kume_sayisi", 0) > 0:
            k["durum"] = "tartismali"
            k["karsi_kanit"] = [{"id": x["id"], "celiski": x["dogrulama"].get("celiski"),
                                 "alinti": x["dogrulama"].get("supporting_excerpt", "")[:200]} for x in k.get("karsi_kaynaklar", [])]
            k["celiski_notu"] = "bağımsız bir kaynak bu iddiayla çelişiyor; kesin anlatılamaz"
            continue
        # ordu/kayıp ya da sınıflanamamış büyük rakam (≥100): aynı rakam 2 bağımsız kümede değilse kesinleşmez
        sayisal = bool(olcu & {"ordu", "kayip"}) or any(s["olcu_turu"] == "diger" and s["deger"] >= 100 for s in k["sayilar"])
        sayi_kume = max(k.get("sayi_teyit_kume_sayisi", 0), k["bagimsiz_kaynak_sayisi"])
        tarih_tek = bool(k["yil"]) and k["tarih_teyit_kume_sayisi"] < 2
        yorum_tek = bool((k.get("iddia_atomlari") or {}).get("yorum")) and k["bagimsiz_kaynak_sayisi"] < 2
        if (sayisal and sayi_kume < 2) or tarih_tek or yorum_tek:
            k["durum"] = "tartismali"
            k["tek_kaynak_uyarisi"] = True
            k["celiski_notu"] = ("tarihsel yorum tek bağımsız kaynakta; kesin anlatılamaz" if yorum_tek and not
                                 ((sayisal and sayi_kume < 2) or tarih_tek) else "tek bağımsız kaynak; kesin anlatılamaz")
            continue
        k["durum"] = "dogrulanmis"
