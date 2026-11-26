"""SSRF ve DNS rebinding korumalı canlı kaynak doğrulayıcı.

HTTP 200 almak bir bilginin doğrulandığı anlamına GELMEZ. Doğrulama iki katmanlıdır:

1. Güvenli getirme (`GuvenliIstemci`):
   - Yalnızca http ve https şemaları kabul edilir.
   - DNS'ten dönen BÜTÜN A ve AAAA kayıtları denetlenir. Kayıtlardan biri bile şu aralıklardaysa istek reddedilir:
     loopback, özel, link-local, reserved, multicast, unspecified ya da IPv4-mapped özel adres.
   - Bağlantı doğrulanmış IP'ye sabitlenir. Soketin gerçekten bağlandığı uç IP, doğrulanan IP ile aynı değilse istek
     reddedilir (DNS rebinding koruması). TLS sertifikası yine alan adı için doğrulanır.
   - En çok 3 yönlendirme izlenir; her yönlendirme hedefinde şema, DNS ve IP denetimleri baştan çalışır.
   - Yanıt en çok 2 MB okunur; zaman aşımı uygulanır. HTML yalnızca ayrıştırılır, script çalıştırılmaz.
   - Raporlara ve loglara sorgu parametresi değerleri yazılmaz (`url_gizle`).
2. Bağlamsal içerik doğrulaması (`icerik_dogrula`): HTML temizlenir. Ardından aynı paragrafta yıl (`year_match`),
   olay (`event_match`), kişi/yer (`entity_match`) ve bağlamsal içerik örtüşmesi (`content_match`) BİRLİKTE
   değerlendirilir. Karar, kaynaktan alınan `supporting_excerpt` alıntısıyla denetlenebilir kalır.

HTTP durum kodu sınıflaması:
- 200: içerik kontrolüne geçilir; sonuç verified ya da content_mismatch olur.
- 403: unverified. Erişim engellidir; kaynak ölü ya da uydurma ilan EDİLMEZ.
- 404 / 410: unreachable.
- 429: kontrollü bekleme ve sınırlı yeniden deneme; deneme hakkı aşılırsa unverified.
- 5xx ya da zaman aşımı: unverified, çünkü sorun geçicidir.
"""
from __future__ import annotations

import html
import http.client
import ipaddress
import re
import socket
import ssl
import time
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from html.parser import HTMLParser

EN_COK_BAYT = 2 * 1024 * 1024
EN_COK_YONLENDIRME = 3
ZAMAN_ASIMI = 12.0
KULLANICI_AJANI = "mini-dunya-kaynak-dogrulayici/1.0 (https://github.com/camkertenberkay53-cyber/mini-dunya; egitim amacli)"
YONTEM = "structured_and_contextual"


class GuvenlikHatasi(Exception):
    """SSRF / DNS rebinding / şema / yönlendirme ihlali. İstek yapılmaz ya da yarıda kesilir."""


class AgHatasi(Exception):
    def __init__(self, tur: str, mesaj: str = ""):
        super().__init__(mesaj or tur)
        self.tur = tur   # 'zaman_asimi' | 'baglanti' | 'cok_buyuk'


# ------------------------------------------------------------------ URL ve IP denetimi

def url_gizle(url: str) -> str:
    """Loglanabilir URL: kullanıcı bilgisi ve parça atılır, sorgu parametresi DEĞERLERİ gizlenir."""
    try:
        p = urllib.parse.urlsplit(url)
    except ValueError:
        return "<gecersiz-url>"
    host = p.hostname or ""
    if p.port:
        host = f"{host}:{p.port}"
    q = "&".join(f"{k}=***" for k, _ in urllib.parse.parse_qsl(p.query, keep_blank_values=True))
    return urllib.parse.urlunsplit((p.scheme, host, p.path, q, ""))


def ip_izinli(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped is not None:
        a = a.ipv4_mapped
    if (a.is_loopback or a.is_private or a.is_link_local or a.is_reserved or a.is_multicast or a.is_unspecified
            or getattr(a, "is_site_local", False)):
        return False
    return a.is_global


def _sistem_cozucu(host: str, port: int) -> list[str]:
    return sorted({i[4][0] for i in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})


def dns_denetle(host: str, port: int, cozucu=None) -> list[str]:
    """Bütün A/AAAA kayıtları izinli olmalı; tek bir özel/loopback kayıt bile isteği düşürür."""
    if not host:
        raise GuvenlikHatasi("host_yok")
    h = host.strip("[]").rstrip(".").lower()
    if h == "localhost" or h.endswith(".localhost") or h.endswith(".local") or h.endswith(".internal"):
        raise GuvenlikHatasi(f"yasak_host: {h}")
    try:
        ipaddress.ip_address(h)
        ipler = [h]
    except ValueError:
        try:
            ipler = (cozucu or _sistem_cozucu)(h, port)
        except OSError as e:
            raise AgHatasi("dns", f"DNS çözümlenemedi: {type(e).__name__}") from None
    if not ipler:
        raise AgHatasi("dns", "DNS kaydı yok")
    yasak = [ip for ip in ipler if not ip_izinli(ip)]
    if yasak:
        raise GuvenlikHatasi(f"yasak_ip: {h} → {yasak}")
    return list(ipler)


# ------------------------------------------------------------------ bağlantı (IP'ye sabitli)

@dataclass
class HamYanit:
    durum: int
    basliklar: dict
    govde: bytes
    uc_ip: str


class _SabitBaglanti:
    """Doğrulanmış IP'ye doğrudan bağlanır; TLS'te SNI ve sertifika alan adı için doğrulanır."""

    def __init__(self, sema: str, host: str, port: int, ip: str, zaman: float):
        self.sema, self.host, self.port, self.ip, self.zaman = sema, host, port, ip, zaman

    def istek(self, yol: str, basliklar: dict, en_cok: int) -> HamYanit:
        try:
            sock = socket.create_connection((self.ip, self.port), timeout=self.zaman)
        except socket.timeout:
            raise AgHatasi("zaman_asimi") from None
        except OSError as e:
            raise AgHatasi("baglanti", type(e).__name__) from None
        try:
            if self.sema == "https":
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self.host)
            uc = sock.getpeername()[0]
            c = http.client.HTTPConnection(self.host, self.port, timeout=self.zaman)
            c.sock = sock
            c.request("GET", yol, headers=basliklar)
            r = c.getresponse()
            govde = r.read(en_cok + 1)
            return HamYanit(r.status, {k.lower(): v for k, v in r.getheaders()}, govde, uc)
        except socket.timeout:
            raise AgHatasi("zaman_asimi") from None
        except (OSError, http.client.HTTPException, ssl.SSLError) as e:
            raise AgHatasi("baglanti", type(e).__name__) from None
        finally:
            try:
                sock.close()
            except OSError:
                pass


def _varsayilan_baglayici(sema, host, port, ip, zaman):
    return _SabitBaglanti(sema, host, port, ip, zaman)


@dataclass
class Yanit:
    url: str
    durum: int
    basliklar: dict
    govde: bytes
    zincir: list = field(default_factory=list)


class GuvenliIstemci:
    def __init__(self, cozucu=None, baglayici=None, zaman_asimi: float = ZAMAN_ASIMI, en_cok_bayt: int = EN_COK_BAYT,
                 en_cok_yonlendirme: int = EN_COK_YONLENDIRME):
        self.cozucu = cozucu
        self.baglayici = baglayici or _varsayilan_baglayici
        self.zaman_asimi, self.en_cok_bayt, self.en_cok_yonlendirme = zaman_asimi, en_cok_bayt, en_cok_yonlendirme

    def getir(self, url: str) -> Yanit:
        zincir = []
        for _ in range(self.en_cok_yonlendirme + 1):
            p = urllib.parse.urlsplit(url)
            sema = (p.scheme or "").lower()
            if sema not in ("http", "https"):
                raise GuvenlikHatasi(f"yasak_sema: {sema or '-'}")
            if p.username or p.password:
                raise GuvenlikHatasi("url_kullanici_bilgisi")
            port = p.port or (443 if sema == "https" else 80)
            ipler = dns_denetle(p.hostname or "", port, self.cozucu)
            ip = ipler[0]
            yol = urllib.parse.urlunsplit(("", "", p.path or "/", p.query, ""))
            b = self.baglayici(sema, p.hostname, port, ip, self.zaman_asimi)
            ham = b.istek(yol, {"Host": p.netloc.rsplit("@", 1)[-1], "User-Agent": KULLANICI_AJANI,
                                "Accept": "text/html,application/json;q=0.9,*/*;q=0.5", "Accept-Encoding": "identity"},
                          self.en_cok_bayt)
            if ham.uc_ip.split("%", 1)[0] != ip.split("%", 1)[0] or not ip_izinli(ham.uc_ip):
                raise GuvenlikHatasi(f"dns_rebinding: beklenen {ip}, bağlanılan {ham.uc_ip}")
            if len(ham.govde) > self.en_cok_bayt:
                raise AgHatasi("cok_buyuk", f"yanıt {self.en_cok_bayt} baytı aşıyor")
            zincir.append({"url": url_gizle(url), "durum": ham.durum, "ip": ip})
            if ham.durum in (301, 302, 303, 307, 308) and ham.basliklar.get("location"):
                url = urllib.parse.urljoin(url, ham.basliklar["location"])
                continue
            return Yanit(url, ham.durum, ham.basliklar, ham.govde, zincir)
        raise GuvenlikHatasi(f"cok_yonlendirme: > {self.en_cok_yonlendirme}")


# ------------------------------------------------------------------ HTML temizliği

class _Metin(HTMLParser):
    ATLA = {"script", "style", "noscript", "template", "svg", "head", "iframe", "object"}
    BLOK = {"p", "div", "li", "br", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "blockquote", "dd", "dt"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parcalar, self.derinlik = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.ATLA:
            self.derinlik += 1
        elif tag in self.BLOK:
            self.parcalar.append("\n")

    def handle_endtag(self, tag):
        if tag in self.ATLA:
            self.derinlik = max(0, self.derinlik - 1)
        elif tag in self.BLOK:
            self.parcalar.append("\n")

    def handle_data(self, data):
        if not self.derinlik:
            self.parcalar.append(re.sub(r"\s+", " ", data))   # blok içi satır sonları boşluk; bloklar \n ile ayrılır


def html_metin(govde: bytes, basliklar: dict | None = None) -> str:
    tur = (basliklar or {}).get("content-type", "")
    m = re.search(r"charset=([\w-]+)", tur)
    try:
        metin = govde.decode(m.group(1) if m else "utf-8", errors="replace")
    except LookupError:
        metin = govde.decode("utf-8", errors="replace")
    if "html" in tur or "<html" in metin[:2000].lower() or "<p" in metin[:5000].lower():
        p = _Metin()
        p.feed(metin)
        metin = "".join(p.parcalar)
    metin = html.unescape(metin)
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*\n+", "\n\n", metin)).strip()


# ------------------------------------------------------------------ bağlamsal içerik doğrulaması

_DURAK = set("""ve ile bir bu da de için olarak olan daha sonra ancak gibi kadar çok en ki ise veya ya hem the a an of and in
on at to by for with from was were is are as that which this his her its their it be been had has have after
before during into than also not""".split())
_YIL = re.compile(r"(?<!\d)(1[0-9]{3}|[5-9][0-9]{2})(?!\d)")


def _katla(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.replace("İ", "I").replace("ı", "i")).encode("ascii", "ignore").decode()
    return s.lower()


def _kokler(s: str) -> list[str]:
    """Türkçe ekleri tolere etmek için ilk 5 harf (Mehmed'in → mehme, savaşı → savas)."""
    return [w[:5] for w in re.findall(r"[a-z0-9]+", _katla(s)) if len(w) >= 4 and w not in _DURAK]


def varliklar(metin: str) -> list[str]:
    """Büyük harfle başlayan, cümle başı olmayan özel ad adayları (kişi/yer). Kesin değil; doğrulamada kullanılır."""
    out = []
    for c in re.split(r"(?<=[.!?])\s+", metin):
        kel = re.findall(r"[^\W\d_][\w'’-]*", c)
        for i, w in enumerate(kel):
            if i > 0 and w[:1].isupper() and len(w) >= 3 and _katla(w) not in _DURAK:
                out.append(re.split(r"['’]", w)[0])
    return list(dict.fromkeys(out))


def _pencereler(metin: str) -> list[str]:
    paragraflar = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n+", metin) if len(p.strip()) > 30]
    out = []
    for p in paragraflar:
        cumleler = re.split(r"(?<=[.!?])\s+", p)
        if len(cumleler) <= 3:
            out.append(p)
        else:
            out += [" ".join(cumleler[i:i + 3]) for i in range(0, len(cumleler) - 2)]
    return out


def icerik_dogrula(metin: str, iddia: dict, esik_icerik: float = 0.5) -> dict:
    """iddia: {'metin', 'yillar'?, 'olay_terimleri'?, 'varliklar'?}. Aynı pencerede dört boyut birlikte aranır."""
    yillar = [str(y) for y in (iddia.get("yillar") or _YIL.findall(iddia.get("metin", "")))]
    # yıl dışı sayılar (ordu, kayıp…): kaynakta AYNI rakam geçmeli; farklı rakam doğrulama değil çelişkidir
    sayilar = {re.sub(r"[.,]", "", x) for x in re.findall(r"(?<![\w.,])\d{1,3}(?:[.,]\d{3})+|(?<![\w.,])\d{2,}(?![\w])",
                                                         iddia.get("metin", ""))
               if not _YIL.fullmatch(re.sub(r"[.,]", "", x)) and int(re.sub(r"[.,]", "", x)) >= 50}
    # olay terimi: yalnızca iddianın KENDİSİNDE geçen olay terimleri kaynakta aranır
    olay = [o for o in (_katla(t)[:5] for t in iddia.get("olay_terimleri", []) if t) if o in _katla(iddia.get("metin", ""))]
    var = [_katla(v)[:5] for v in (iddia.get("varliklar") or varliklar(iddia.get("metin", "")))]
    icerik = list(dict.fromkeys(_kokler(iddia.get("metin", ""))))
    en = None
    for w in _pencereler(metin):
        k = set(_kokler(w))
        kv = {t[:5] for t in re.findall(r"[a-z0-9]+", _katla(w)) if len(t) >= 3}   # özel adlar kısa olabilir (Han, Bey)
        wy = set(_YIL.findall(w))
        ws = {re.sub(r"[.,]", "", x) for x in re.findall(r"\d{1,3}(?:[.,]\d{3})+|\d+", w)}
        sonuc = {
            "year_match": all(y in wy for y in yillar) if yillar else None,
            "event_match": any(o in k for o in olay) if olay else None,
            "entity_match": (sum(v in kv for v in var) / len(var) >= 0.5) if var else None,
            "content_score": round(sum(c in k for c in icerik) / len(icerik), 3) if icerik else 0.0,
            "number_match": (sayilar <= ws) if sayilar else None,
        }
        sonuc["content_match"] = sonuc["content_score"] >= esik_icerik
        puan = (sonuc["content_score"] + (sonuc["year_match"] is True) + (sonuc["entity_match"] is True)
                + (sonuc["event_match"] is True) + (sonuc["number_match"] is True))
        if en is None or puan > en[0]:
            en = (puan, sonuc, w)
    if en is None:
        return {"verification_status": "content_mismatch", "year_match": False, "event_match": False, "entity_match": False,
                "number_match": None, "content_match": False, "content_score": 0.0, "supporting_excerpt": "", "neden": "metin_bos"}
    _, s, w = en
    gerekli = {k: s[k] for k in ("year_match", "event_match", "entity_match", "number_match") if s[k] is not None}
    tamam = s["content_match"] and all(gerekli.values())
    eksik = [k for k, v in gerekli.items() if not v] + ([] if s["content_match"] else ["content_match"])
    return {"verification_status": "verified" if tamam else "content_mismatch",
            "year_match": bool(s["year_match"]) if s["year_match"] is not None else None,
            "event_match": bool(s["event_match"]) if s["event_match"] is not None else None,
            "entity_match": bool(s["entity_match"]) if s["entity_match"] is not None else None,
            "content_match": bool(s["content_match"]), "content_score": s["content_score"],
            "number_match": s["number_match"],
            "supporting_excerpt": w[:400], "neden": "uyumlu" if tamam else "eksik: " + ",".join(eksik)}


# ------------------------------------------------------------------ kaynak doğrulama

def _sonuc(url, durum, http_kodu=None, neden="", **ek) -> dict:
    d = {"url": url_gizle(url), "http_status": http_kodu, "verification_status": durum, "verification_method": YONTEM,
         "year_match": None, "event_match": None, "entity_match": None, "number_match": None, "content_match": None,
         "content_score": None,
         "supporting_excerpt": "", "neden": neden}
    d.update(ek)
    return d


class KaynakDogrulayici:
    def __init__(self, istemci: GuvenliIstemci | None = None, uyku=time.sleep, en_cok_429: int = 2, bekleme_tavani: float = 10.0):
        self.istemci = istemci or GuvenliIstemci()
        self.uyku, self.en_cok_429, self.bekleme_tavani = uyku, en_cok_429, bekleme_tavani
        self._onbellek: dict[str, tuple] = {}

    def sayfa(self, url: str):
        """(durum_sinifi, http_kodu, metin, neden). Aynı URL bir kez getirilir."""
        if url in self._onbellek:
            return self._onbellek[url]
        sonuc = self._getir(url)
        self._onbellek[url] = sonuc
        return sonuc

    def _getir(self, url: str):
        for deneme in range(self.en_cok_429 + 1):
            try:
                y = self.istemci.getir(url)
            except GuvenlikHatasi as e:
                return ("unverified", None, "", f"guvenlik_reddi: {e}")
            except AgHatasi as e:
                return ("unverified", None, "", f"ag_{e.tur}")
            if y.durum == 429:
                if deneme < self.en_cok_429:
                    try:
                        bekle = float(y.basliklar.get("retry-after", 2 ** deneme))
                    except ValueError:
                        bekle = 2.0 ** deneme
                    self.uyku(min(self.bekleme_tavani, max(0.5, bekle)))
                    continue
                return ("unverified", 429, "", "rate_limit_asildi")
            if y.durum == 200:
                tur = (y.basliklar.get("content-type") or "").lower()
                if "pdf" in tur or y.govde[:5] == b"%PDF-":
                    return ("unverified", 200, "", "pdf_metin_cikarimi_desteklenmiyor (içerik yanlış sayılmaz)")
                if tur and not any(t in tur for t in ("html", "text/plain", "xml")):
                    return ("unverified", 200, "", f"desteklenmeyen_icerik_turu: {tur.split(';')[0]}")
                return ("ok", 200, html_metin(y.govde, y.basliklar), "")
            if y.durum == 403:
                return ("unverified", 403, "", "erisim_engelli (kaynak ölü/uydurma sayılmaz)")
            if y.durum in (404, 410):
                return ("unreachable", y.durum, "", "sayfa_bulunamadi")
            if y.durum >= 500:
                return ("unverified", y.durum, "", "gecici_sunucu_hatasi")
            return ("unverified", y.durum, "", f"beklenmeyen_http_{y.durum}")
        return ("unverified", 429, "", "rate_limit_asildi")

    def dogrula(self, url: str, iddia: dict) -> dict:
        sinif, kod, metin, neden = self.sayfa(url)
        if sinif != "ok":
            return _sonuc(url, sinif, kod, neden)
        return dict(_sonuc(url, "verified", kod), **icerik_dogrula(metin, iddia))
