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
import re
import urllib.parse
from abc import ABC, abstractmethod

from motor.orkestrasyon.kaynak_dogrulayici import (_YIL, GuvenliIstemci, KaynakDogrulayici, _katla, html_metin,
                                                   url_gizle, varliklar)

ONCELIK = {"birincil_arsiv": 4, "akademik": 3, "ansiklopedi": 2, "genel_web": 1}
CELISKI_IFADESI = "kaynaklar farklı rakamlar aktarmaktadır"
_AKADEMIK = ("doi.org", "jstor.org", "dergipark.org.tr", "academia.edu", "researchgate.net", "persee.fr", "brill.com",
             "cambridge.org", "oup.com", "tandfonline.com", "springer.com", "islamansiklopedisi.org.tr", "books.google",
             "openedition.org", "muse.jhu.edu", "semanticscholar.org")
_ARSIV = ("archive.org", "devletarsivleri.gov.tr", "gallica.bnf.fr", "loc.gov", "europeana.eu", "wdl.org",
          "digitale-sammlungen.de", "e-codices.ch")
_OLCU = {   # sayının hemen çevresinde aranan anahtarlar (ilk 5 harf, ASCII katlanmış)
    "ordu": ["asker", "kisil", "ordu", "kuvve", "sueva", "atli", "piyad", "yenic", "troop", "army", "soldi", "force",
             "caval", "infan", "streng", "janis", "men", "peopl", "warri", "horse"],
    "kayip": ["kayip", "kayb", "olu", "oldu", "olum", "sehit", "casua", "kille", "losse", "dead", "death", "slain"],
}


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
        d = self._api(dil, action="query", prop="extracts|info|extlinks|langlinks", titles=baslik, redirects=1,
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
                            "bolumler": bolumler, "ozet": self._ozet(dil, m.get("title", b)), "aday": False})
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


def _sayilar(cumle: str) -> list[dict]:
    """Yıl dışı sayılar ve ölçü türleri (sayının ±6 kelimelik çevresinde anahtar aranır)."""
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
        cevre = [_katla(x)[:5] for x in kel[max(0, i - 6): i + 7]]
        tur = next((t for t, anahtar in _OLCU.items() if any(a in c or c.startswith(a) for c in cevre for a in anahtar)), "diger")
        out.append({"deger": deger, "ham": ham, "olcu_turu": tur})
    return out


def iddialari_cikar(kaynak: dict, en_cok: int = 60) -> list[dict]:
    """Ana madde metninden yıl ya da sayı içeren cümleler (deterministik). Her biri tek iddia."""
    metin = kaynak.get("metin") or ""
    out = []
    for c in re.split(r"(?<=[.!?])\s+(?=[A-ZÇĞİÖŞÜ0-9])", re.sub(r"\s+", " ", metin)):
        c = c.strip()
        if not 40 <= len(c) <= 400:
            continue
        s = _sayilar(c)
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
    sayim = dogrulayici.onden_getir([k["url"] for k in kaynaklar])
    ilerleme("kaynak_dogrulama", f"sayfalar getirildi: {sayim}")
    olay_terimleri = olay_terimleri or [w for w in re.findall(r"\w+", konu) if len(w) >= 4]
    # aday dış kaynaklar canlı (SSRF korumalı) getirilir; metni olanlar hem bağımsızlık (kopya tespiti) hem de
    # kendi iddiaları (farklı rakamlar → çelişki) için kullanılır
    for k in kaynaklar:
        if k.get("aday") and not k.get("metin"):
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
        for i in iddialari_cikar(k):
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
        destek = []
        for k in ana + adaylar:
            d = dogrulayici.dogrula(k["url"], sorgu)   # sayfa bir kez getirilir (önbellek), iddia yerelde denetlenir
            # tarih teyidi: farklı dilde/kaynakta aynı yıl + kişi/yer + olay (içerik dili farklı olabilir)
            tarih_teyidi = (bool(idd["yillar"]) and d.get("year_match") and d.get("entity_match") and d.get("event_match") is not False
                            and d.get("number_match") is not False)
            if d["verification_status"] == "verified" or (tarih_teyidi and d["verification_status"] == "content_mismatch"):
                destek.append({"id": k["id"], "url": k["url"], "eser": k.get("baslik"), "yayinci": k.get("yayinci"),
                               "tur": k.get("tur"), "kume": kume[k["id"]],
                               "dogrulama": {x: d[x] for x in ("verification_status", "verification_method", "http_status",
                                                               "year_match", "event_match", "entity_match", "number_match",
                                                               "content_match",
                                                               "content_score", "supporting_excerpt", "neden")},
                               "teyit_turu": "icerik" if d["verification_status"] == "verified" else "yalniz_tarih"})
            rapor_kaynak.setdefault(k["id"], {"url": url_gizle(k["url"]), "tur": k.get("tur"), "yayinci": k.get("yayinci"),
                                              "kume": kume[k["id"]], "sonuclar": {}})
            rapor_kaynak[k["id"]]["sonuclar"][d["verification_status"]] = rapor_kaynak[k["id"]]["sonuclar"].get(d["verification_status"], 0) + 1
        icerik_kume = {x["kume"] for x in destek if x["teyit_turu"] == "icerik"}
        tum_kume = {x["kume"] for x in destek}
        kayitlar.append({"id": f"ark_{n:03d}", "iddia": idd["metin"], "yil": idd["yillar"][0] if idd["yillar"] else None,
                         "sayilar": idd["sayilar"], "kaynaklar": destek, "kaynak_kesfi": idd["kaynak_id"],
                         "bagimsiz_kaynak_sayisi": len(icerik_kume), "tarih_teyit_kume_sayisi": len(tum_kume),
                         "tur": ("sayi" if any(s["olcu_turu"] in ("ordu", "kayip") for s in idd["sayilar"])
                                 else "tarih" if idd["yillar"] else "olay"),
                         "olay_id": f"olay_{idd['yillar'][0]}" if idd["yillar"] else "olay_genel"})
    sayisal_koruma(kayitlar)
    ilerleme("kaynak_dogrulama", f"{len(kayitlar)} iddia denetlendi; durumlar: "
             f"{ {d: sum(k['durum'] == d for k in kayitlar) for d in ('dogrulanmis', 'tartismali', 'belirsiz')} }")
    return {"konu": konu, "kayitlar": kayitlar, "kaynak_raporu": rapor_kaynak,
            "kume_sayisi": len(set(kume.values())), "dogrulama_yontemi": "structured_and_contextual"}


def sayisal_koruma(kayitlar: list[dict]) -> None:
    """Durum ataması (yerinde):
    - doğrulanmış kaynak yok → belirsiz
    - ordu/kayıp ölçüsünde kümeler arası farklı rakam → tartismali + celiski (değerler AYRI; ortalama YOK)
    - tek bağımsız küme + sayısal (ordu/kayıp ya da yalnızca tek kümede teyitli tarih) → tartismali + tek_kaynak_uyarisi
    - aksi → dogrulanmis
    """
    degerler: dict[str, dict[int, set]] = {}
    for k in kayitlar:
        kumeler = {x["kume"] for x in k["kaynaklar"] if x["teyit_turu"] == "icerik"}
        for s in k["sayilar"]:
            if s["olcu_turu"] in ("ordu", "kayip") and kumeler:
                degerler.setdefault(s["olcu_turu"], {}).setdefault(s["deger"], set()).update(kumeler)
    celiskili = {}
    for tur, d in degerler.items():
        kumeler = set().union(*d.values()) if d else set()
        if len(d) > 1 and len(kumeler) > 1:
            celiskili[tur] = [{"deger": v, "kume": sorted(c)} for v, c in sorted(d.items())]
    for k in kayitlar:
        icerik = [x for x in k["kaynaklar"] if x["teyit_turu"] == "icerik"]
        k["tek_kaynak_uyarisi"] = False
        olcu = {s["olcu_turu"] for s in k["sayilar"]}
        if not icerik:
            k["durum"] = "belirsiz"
            continue
        c = [celiskili[t] for t in olcu if t in celiskili]
        if c:
            k["durum"] = "tartismali"
            k["celiski"] = {"olcu_turleri": sorted(t for t in olcu if t in celiskili), "degerler": c[0],
                            "kural": "ortalama alınmaz; değerler ayrı aktarılır"}
            k["celiski_notu"] = CELISKI_IFADESI
            continue
        # ordu/kayıp ya da sınıflanamamış büyük rakam (≥100): tek bağımsız kaynakla kesin anlatılamaz
        sayisal = bool(olcu & {"ordu", "kayip"}) or any(s["olcu_turu"] == "diger" and s["deger"] >= 100 for s in k["sayilar"])
        tarih_tek = bool(k["yil"]) and k["tarih_teyit_kume_sayisi"] < 2
        if (sayisal and k["bagimsiz_kaynak_sayisi"] < 2) or tarih_tek:
            k["durum"] = "tartismali"
            k["tek_kaynak_uyarisi"] = True
            k["celiski_notu"] = "tek bağımsız kaynak; kesin anlatılamaz"
            continue
        k["durum"] = "dogrulanmis"
