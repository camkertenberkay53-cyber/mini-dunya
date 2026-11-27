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
import subprocess
import sys
import ipaddress
import re
import socket
import ssl
import time
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from html.parser import HTMLParser

EN_COK_BAYT = 2 * 1024 * 1024          # HTML/metin yanıtı
PDF_EN_COK_BAYT = 3 * 1024 * 1024      # PDF (yalnızca açık erişimli metin çıkarımı için)
PDF_EN_COK_SAYFA = 10
PDF_SURE_SN = 20
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


# ------------------------------------------------------------------ PDF metin çıkarımı (pypdf, yalıtılmış alt süreç)

# Güvenilmeyen PDF ayrı süreçte ayrıştırılır. Süreç -I ile yalıtılır. Bellek (768 MB), CPU (PDF_SURE_SN) ve duvar saati
# sınırı vardır. Yalnızca ilk PDF_EN_COK_SAYFA sayfanın metni çıkarılır. PDF içindeki JavaScript/eylemler
# çalıştırılmaz: pypdf yalnızca metin okur.
_PDF_BETIGI = r"""
import io, resource, sys
resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
resource.setrlimit(resource.RLIMIT_CPU, (int(sys.argv[2]), int(sys.argv[2])))
try:
    import pypdf
except ImportError:
    sys.stdout.write("__PYPDF_YOK__"); sys.exit(3)
r = pypdf.PdfReader(io.BytesIO(sys.stdin.buffer.read()))
if r.is_encrypted:
    sys.stdout.write("__SIFRELI__"); sys.exit(4)
out = []
for i, sayfa in enumerate(r.pages):
    if i >= int(sys.argv[1]):
        break
    out.append(sayfa.extract_text() or "")
sys.stdout.write("\f".join(out)[:400000])   # sayfalar form feed ile ayrılır
"""


def pdf_cikar(govde: bytes, en_cok_sayfa: int = PDF_EN_COK_SAYFA, sure: int = PDF_SURE_SN) -> dict:
    """PDF → {ham, metin (normalize), sayfa_sayisi, kaldirilan, dipnot_sayisi, neden, neden_kodu}. metin None ise
    neden_kodu başarısızlığın TÜRÜNÜ ayırır: pdf_zaman_asimi | pdf_kutuphanesi_yok | pdf_sifreli | pdf_parse_hatasi |
    pdf_metin_yok. Bunların hiçbiri içerik yanlışlığı değildir."""
    from motor.orkestrasyon.pdf_normal import normalize_sayfalar

    def hata(kod, neden):
        return {"ham": None, "metin": None, "sayfa_sayisi": 0, "kaldirilan": [], "dipnot_sayisi": 0,
                "neden": neden, "neden_kodu": kod}
    try:
        r = subprocess.run([sys.executable, "-I", "-c", _PDF_BETIGI, str(en_cok_sayfa), str(sure)], input=govde,
                           capture_output=True, timeout=sure + 5)
    except subprocess.TimeoutExpired:
        return hata("pdf_zaman_asimi", "pdf_zaman_asimi")
    cikti = r.stdout.decode("utf-8", errors="replace")
    if r.returncode == 3 or "__PYPDF_YOK__" in cikti:
        return hata("pdf_kutuphanesi_yok", "pdf_kutuphanesi_yok (pypdf kurulu değil)")
    if r.returncode == 4:
        return hata("pdf_sifreli", "pdf_sifreli")
    if r.returncode != 0:
        return hata("pdf_parse_hatasi", "pdf_okunamadi (parse hatası)")
    sayfalar = cikti.split("\f")
    n = normalize_sayfalar(sayfalar)
    govde_metni = re.sub(r"\[(?:pdf )?s\. [^\]]+\]", "", n["metin"]).strip()
    if len(govde_metni) < 40:
        d = hata("pdf_metin_yok", "pdf_metin_yok (taranmış görüntü olabilir)")
        d.update(ham=cikti, sayfa_sayisi=len(sayfalar))
        return d
    return {"ham": cikti, "metin": n["metin"], "sayfa_sayisi": n["sayfa_sayisi"], "kaldirilan": n["kaldirilan"],
            "dipnot_sayisi": len(n["dipnotlar"]), "neden": "pdf_metni", "neden_kodu": "pdf_metni"}


def pdf_metin(govde: bytes, en_cok_sayfa: int = PDF_EN_COK_SAYFA, sure: int = PDF_SURE_SN) -> tuple[str | None, str]:
    """(normalize metin | None, neden). Geriye dönük uyumlu kısa yol; ayrıntı için pdf_cikar."""
    d = pdf_cikar(govde, en_cok_sayfa, sure)
    return d["metin"], d["neden"]


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


class Pencere(str):
    """Doğrulama penceresi (str). kaynakca: kaynakça/dipnot paragrafından mı. ocr: OCR rakam onarımı içeriyor mu.
    orijinal: OCR onarımı öncesi özgün pencere metni (alıntı her zaman özgün metinden verilir)."""
    kaynakca: bool = False
    ocr: bool = False
    orijinal: str | None = None


_BIBLIYO_BASLIK = re.compile(r"^\s*(?:bibliyografya|bibliography|kaynakça|kaynakca|kaynaklar|references|notlar|notes|"
                             r"dipnotlar|further reading)\s*:?\s*$", re.I)


def _paragraflar(metin: str) -> list[tuple[str, bool]]:
    """(paragraf, kaynakca_mi). Kaynakça başlığından ('BİBLİYOGRAFYA', 'References'…) sonraki kısa paragraflar da
    kaynakça sayılır (bir sonraki uzun düzyazı paragrafına kadar)."""
    from motor.orkestrasyon import iddia_atom as ia
    out, bib = [], False
    for ham in re.split(r"\n+", metin):
        p = re.sub(r"\s+", " ", ham).strip()
        if _BIBLIYO_BASLIK.match(p):
            bib = True
            continue
        if len(p) <= 30:
            continue
        k = ia.kaynakca_mi(p)
        if bib and not k and len(p) > 400:
            bib = False   # başlıktan sonra uzun düzyazı: yeni madde başladı
        out.append((p, k or bib))
    return out


def _pencereler(metin: str) -> list[Pencere]:
    out = []
    for p, kaynakca in _paragraflar(metin):
        cumleler = re.split(r"(?<=[.!?])\s+", p)
        parcalar = [p] if len(cumleler) <= 3 else [" ".join(cumleler[i:i + 3]) for i in range(0, len(cumleler) - 2)]
        for x in parcalar:
            w = Pencere(x)
            w.kaynakca = kaynakca
            out.append(w)
    return out


def dogrulama_pencereleri(metin: str) -> tuple[list[Pencere], list[dict]]:
    """Özgün metnin DOĞRULAMA KOPYASI üzerinden pencereler. OCR rakam onarımı (ı473 → 1473) yalnız bu kopyada yapılır;
    uzunluk korunduğu için pencereler özgün metinle birebir eşleşir ve her pencere özgün halini `orijinal` olarak
    taşır (boşluk sıkıştırması yüzünden pencere uzunluğu 1-2 karakter oynayabilir; sıra ve sayı aynıdır). Eşleşme
    bozulursa OCR onarımı hiç kullanılmaz."""
    from motor.orkestrasyon import iddia_atom as ia
    kopya, duz = ia.ocr_rakam_normalize(metin)
    oz = _pencereler(metin)
    if not duz:
        return oz, []
    yeni = _pencereler(kopya)
    if len(yeni) != len(oz) or any(abs(len(a) - len(b)) > 4 for a, b in zip(yeni, oz)):
        return oz, []
    for w, o in zip(yeni, oz):
        w.ocr = str(w) != str(o)
        w.orijinal = str(o)
    return yeni, duz


def icerik_dogrula(metin: str, iddia: dict) -> dict:
    """iddia: {'metin', 'yillar'?, 'olay_terimleri'?, 'varliklar'?}. Atomik değerlendirme (iddia_atom): yalnızca
    `supported` → verified. Eski alanlar (year/event/entity/number/content_match) geriye dönük uyum için korunur.
    Özgün metin değişmez; OCR onarımı yalnızca doğrulama kopyasındadır (bkz. dogrulama_pencereleri)."""
    from motor.orkestrasyon import iddia_atom as ia
    pencereler, duz = dogrulama_pencereleri(metin or "")
    r = ia.degerlendir(pencereler, iddia)
    at = r["atomlar"]
    if not r["supporting_excerpt"] and not at:
        neden = "metin_bos"
    elif r["destek_sinifi"] == "supported":
        neden = "uyumlu" + ("; ocr_onarimina_bagli" if r.get("ocr_bagimli") else "")
    else:
        eksik = [k for k, v in at.items() if v is False] + ([] if r["icerik_orani"] >= ia.ICERIK_ESIGI else ["content_match"])
        neden = f"destek={r['destek_sinifi']}" + (f"; eksik: {','.join(eksik)}" if eksik else "") + (
            f"; çelişki: {','.join(r['celiski'])}" if r["celiski"] else "")
    return {"verification_status": "verified" if r["destek_sinifi"] == "supported" else "content_mismatch",
            "destek_sinifi": r["destek_sinifi"], "atomlar": at, "iddia_atomlari": r["iddia_atomlari"],
            "celiski": r["celiski"],
            "year_match": at.get("yil"), "event_match": at.get("olay"), "entity_match": at.get("varlik"),
            "number_match": at.get("sayi"), "content_score": r["icerik_orani"],
            "content_match": r["icerik_orani"] >= ia.ICERIK_ESIGI,
            "supporting_excerpt": r["supporting_excerpt"], "neden": neden,
            "kaynakca_penceresi": r.get("kaynakca_penceresi", False), "ocr_duzeltmeli": r.get("ocr_duzeltmeli", False),
            "ocr_bagimli": r.get("ocr_bagimli", False), "ocr_duzeltme_sayisi": len(duz)}


# ------------------------------------------------------------------ kaynak politikası (SSRF'den AYRI katman)

# Dosya paylaşım / korsan kütüphane barındırıcıları: içerik kaynağı doğrulanamaz ve telif ihlali riski taşır.
# Bunlar ağa hiç çıkılmadan reddedilir. SSRF korumasının yerine geçmez, ona ek bir katmandır.
REDDEDILEN_HOSTLAR = ("cdn.discordapp.com", "media.discordapp.net", "discordapp.com", "discord.com", "mega.nz",
                      "mediafire.com", "rapidgator.net", "uploaded.net", "4shared.com", "scribd.com", "dokumen.pub",
                      "vdoc.pub", "ebin.pub", "pdfdrive.com", "pdfcoffee.com", "idoc.pub", "kupdf.net", "dokumen.tips",
                      "library.lol", "libgen.rs", "libgen.is", "libgen.li", "sci-hub.se", "sci-hub.ru", "sci-hub.st")
REDDEDILEN_ETIKETLER = ("z-lib", "zlibrary", "1lib", "b-ok", "libgen", "annas-archive", "sci-hub")


def _ozgun(url: str) -> str:
    m = re.match(r"https?://web\.archive\.org/web/\d+[a-z_]*/(.+)$", url, re.I)
    if not m:
        return url
    o = m.group(1)
    return o if re.match(r"https?://", o, re.I) else "http://" + o


def kaynak_politikasi(url: str) -> tuple[bool, str]:
    """(izinli, neden). Arşiv anlık görüntüsü (web.archive.org) özgün adrese göre değerlendirilir."""
    try:
        h = (urllib.parse.urlsplit(_ozgun(url)).hostname or "").lower().rstrip(".")
    except ValueError:
        return False, "gecersiz_url"
    if any(h == d or h.endswith("." + d) for d in REDDEDILEN_HOSTLAR):
        return False, f"dosya_paylasim_barindiricisi ({h})"
    if any(lbl == e or lbl.startswith(e) for lbl in h.split(".") for e in REDDEDILEN_ETIKETLER):
        return False, f"korsan_kutuphane_supheli ({h})"
    return True, ""


# ------------------------------------------------------------------ kaynak doğrulama

def _sonuc(url, durum, http_kodu=None, neden="", **ek) -> dict:
    d = {"url": url_gizle(url), "http_status": http_kodu, "verification_status": durum, "verification_method": YONTEM,
         "destek_sinifi": None, "atomlar": {}, "celiski": [],
         "year_match": None, "event_match": None, "entity_match": None, "number_match": None, "content_match": None,
         "content_score": None,
         "supporting_excerpt": "", "neden": neden}
    d.update(ek)
    return d


class KaynakDogrulayici:
    def __init__(self, istemci: GuvenliIstemci | None = None, uyku=time.sleep, en_cok_429: int = 2, bekleme_tavani: float = 10.0,
                 html_en_cok_bayt: int = EN_COK_BAYT, pdf_en_cok_bayt: int = PDF_EN_COK_BAYT, politika=None):
        # istemci PDF sınırı kadar (3 MB) okur; HTML/metin için 2 MB sınırı burada ayrıca uygulanır
        self.istemci = istemci or GuvenliIstemci(en_cok_bayt=pdf_en_cok_bayt)
        self.html_en_cok_bayt, self.pdf_en_cok_bayt = html_en_cok_bayt, pdf_en_cok_bayt
        self.uyku, self.en_cok_429, self.bekleme_tavani = uyku, en_cok_429, bekleme_tavani
        self.politika = politika or kaynak_politikasi
        self.erisim: dict[str, dict] = {}      # url → erişim/neden kaydı (kaynak raporu için)
        self.ham_metin: dict[str, str] = {}    # url → PDF ham metni (normalizasyon öncesi)
        self._onbellek: dict[str, tuple] = {}

    def sayfa(self, url: str):
        """(durum_sinifi, http_kodu, metin, neden). Aynı URL bir kez getirilir."""
        if url in self._onbellek:
            return self._onbellek[url]
        sonuc = self._getir(url)
        self._onbellek[url] = sonuc
        return sonuc

    def _getir(self, url: str):
        """(sinif, http_kodu, metin, neden). Ayrıca self.erisim[url] = {neden_kodu, …}: başarısızlığın TÜRÜ."""
        def kayit(sinif, kod, metin, neden, neden_kodu, **ek):
            self.erisim[url] = dict({"durum": sinif, "http_status": kod, "neden_kodu": neden_kodu, "neden": neden}, **ek)
            return (sinif, kod, metin, neden)
        izin, politika_nedeni = self.politika(url)
        if not izin:   # ağa hiç çıkılmaz
            return kayit("unverified", None, "", f"politika_reddi: {politika_nedeni}", "politika_reddi")
        for deneme in range(self.en_cok_429 + 1):
            try:
                y = self.istemci.getir(url)
            except GuvenlikHatasi as e:
                return kayit("unverified", None, "", f"guvenlik_reddi: {e}", "guvenlik_reddi")
            except AgHatasi as e:
                kod = {"zaman_asimi": "timeout", "cok_buyuk": "cok_buyuk"}.get(e.tur, "ag_hatasi")
                return kayit("unverified", None, "", f"ag_{e.tur}", kod)
            if y.durum == 429:
                if deneme < self.en_cok_429:
                    try:
                        bekle = float(y.basliklar.get("retry-after", 2 ** deneme))
                    except ValueError:
                        bekle = 2.0 ** deneme
                    self.uyku(min(self.bekleme_tavani, max(0.5, bekle)))
                    continue
                return kayit("unverified", 429, "", "rate_limit_asildi", "http_429")
            if y.durum == 200:
                tur = (y.basliklar.get("content-type") or "").lower()
                if "pdf" in tur or y.govde[:5] == b"%PDF-":
                    if len(y.govde) > self.pdf_en_cok_bayt:
                        return kayit("unverified", 200, "", "ag_cok_buyuk (PDF > 3 MB)", "cok_buyuk", belge="pdf")
                    p = pdf_cikar(y.govde)
                    pdf = {"sayfa_sayisi": p["sayfa_sayisi"], "ham_karakter": len(p["ham"] or ""),
                           "normal_karakter": len(p["metin"] or ""), "kaldirilan_satir": len(p["kaldirilan"]),
                           "dipnot": p["dipnot_sayisi"]}
                    if p["metin"] is None:   # HTTP erişimi başarılı; sorun PDF'in kendisinde
                        return kayit("unverified", 200, "", p["neden"] + " (içerik yanlış sayılmaz)", p["neden_kodu"],
                                     belge="pdf", pdf=pdf)
                    self.ham_metin[url] = p["ham"]   # normalize metin doğrulamada; ham metin kaybolmaz
                    return kayit("ok", 200, p["metin"], "pdf_metni", "ok", belge="pdf", pdf=pdf)
                if tur and not any(t in tur for t in ("html", "text/plain", "xml")):
                    return kayit("unverified", 200, "", f"desteklenmeyen_icerik_turu: {tur.split(';')[0]}",
                                 "desteklenmeyen_belge")
                if len(y.govde) > self.html_en_cok_bayt:
                    return kayit("unverified", 200, "", "ag_cok_buyuk (HTML > 2 MB)", "cok_buyuk", belge="html")
                metin = html_metin(y.govde, y.basliklar)
                if len(metin.strip()) < 30:
                    return kayit("unverified", 200, "", "bos_icerik (sayfa metni yok/çok kısa; JS ile yükleniyor olabilir)",
                                 "bos_icerik", belge="html")
                return kayit("ok", 200, metin, "", "ok", belge="html")
            if y.durum == 403:
                return kayit("unverified", 403, "", "erisim_engelli (kaynak ölü/uydurma sayılmaz)", "http_403")
            if y.durum in (404, 410):
                return kayit("unreachable", y.durum, "", "sayfa_bulunamadi", f"http_{y.durum}")
            if y.durum >= 500:
                return kayit("unverified", y.durum, "", "gecici_sunucu_hatasi", "http_5xx")
            return kayit("unverified", y.durum, "", f"beklenmeyen_http_{y.durum}", "http_diger")
        return kayit("unverified", 429, "", "rate_limit_asildi", "http_429")

    def onden_getir(self, urller: list[str], paralel: int = 8) -> dict:
        """Sayfaları paralel getirip önbelleğe alır (her biri SSRF korumalı). Dönüş: durum sınıfı sayımı."""
        from concurrent.futures import ThreadPoolExecutor
        eksik = [u for u in dict.fromkeys(urller) if u not in self._onbellek]
        with ThreadPoolExecutor(max_workers=max(1, min(paralel, len(eksik) or 1))) as ex:
            list(ex.map(self.sayfa, eksik))
        sayim: dict = {}
        for u in urller:
            sayim[self._onbellek[u][0]] = sayim.get(self._onbellek[u][0], 0) + 1
        return sayim

    def dogrula(self, url: str, iddia: dict) -> dict:
        sinif, kod, metin, neden = self.sayfa(url)
        if sinif != "ok":
            return _sonuc(url, sinif, kod, neden)
        return dict(_sonuc(url, "verified", kod), **icerik_dogrula(metin, iddia))
