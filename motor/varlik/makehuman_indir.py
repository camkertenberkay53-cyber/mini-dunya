"""MakeHuman (CC0) asset paketi indirici — Actions'ta çalışır (sandbox makehumancommunity.org'a erişemez).

Kullanım: python3 -m motor.varlik.makehuman_indir motor/varlik/makehuman/istek.json
1) Asset paketleri sayfasını okur; istenen paketin bağlantısının sayfanın "shared under CC0" bölümünde olduğunu
   doğrular (CC-BY bölümündekiler reddedilir). 2) Zip'i indirir. 3) Yalnız istekteki desenlere uyan dosyaları açar.
4) Kayıt: motor/varlik/makehuman/lisans.json (sayfa, bölüm başlığı, zip url, sha256, açılan dosyalar). Ayrıca
   zip içeriğinin tam listesi icerik_<paket>.txt'ye yazılır (alt küme seçimini sonradan yapmak için)."""
from __future__ import annotations

import hashlib
import html
import io
import json
import re
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

UA = {"User-Agent": "mini-dunya-varlik (github.com/camkertenberkay53-cyber/mini-dunya)"}
SAYFA = "https://static.makehumancommunity.org/assets/assetpacks.html"


def al(url: str) -> bytes:
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=600).read()


class UzakDosya(io.RawIOBase):
    """HTTP Range ile okunan, aranabilir uzak dosya: zip'in yalnız merkez dizini ve istenen üyeleri indirilir
    (paketin tamamı çok büyük; bütün zip'i indirmek Actions süre sınırını aşıyordu)."""

    def __init__(self, url: str, parca: int = 1 << 20):
        self.url, self.parca, self.konum, self.onbellek, self.indirilen = url, parca, 0, {}, 0
        r = urllib.request.urlopen(urllib.request.Request(url, method="HEAD", headers=UA), timeout=120)
        self.boy = int(r.headers["Content-Length"])
        if r.headers.get("Accept-Ranges", "").lower() != "bytes":
            raise IOError("sunucu Range desteklemiyor")

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.konum

    def seek(self, ofs, nereden=0):
        self.konum = {0: ofs, 1: self.konum + ofs, 2: self.boy + ofs}[nereden]
        return self.konum

    def _blok(self, i):
        if i not in self.onbellek:
            a, b = i * self.parca, min(self.boy, (i + 1) * self.parca) - 1
            h = dict(UA, Range=f"bytes={a}-{b}")
            self.onbellek[i] = urllib.request.urlopen(urllib.request.Request(self.url, headers=h), timeout=300).read()
            self.indirilen += len(self.onbellek[i])
            if len(self.onbellek) > 64:
                self.onbellek.pop(next(iter(self.onbellek)))
        return self.onbellek[i]

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.boy - self.konum
        n = max(0, min(n, self.boy - self.konum))
        out = bytearray()
        while len(out) < n:
            i = self.konum // self.parca
            b = self._blok(i)
            ofs = self.konum - i * self.parca
            al_ = b[ofs: ofs + (n - len(out))]
            out += al_
            self.konum += len(al_)
        return bytes(out)

    def readinto(self, b):
        d = self.read(len(b))
        b[: len(d)] = d
        return len(d)


def main(istek_yolu: str) -> int:
    istek = json.loads(Path(istek_yolu).read_text())
    kok = Path(istek_yolu).parent
    h = al(SAYFA).decode("utf-8", "replace")
    kayit = {"sayfa": SAYFA, "paketler": []}
    for p in istek["paketler"]:
        k = {"ad": p["ad"], "durum": "BASARISIZ"}
        try:
            m = re.search(r'href="([^"]*' + re.escape(p["dosya_deseni"]) + r'[^"]*)"', h)
            if not m:
                k["durum"] = "BAGLANTI_YOK"
                k["sayfadaki_baglantilar"] = re.findall(r'href="([^"]+)"', h)[:200]
                kayit["paketler"].append(k)
                continue
            url = urllib.parse.urljoin(SAYFA, html.unescape(m.group(1)))
            if not url.lower().endswith(".zip"):   # paket alt sayfası: zip bağlantısı orada
                alt = al(url).decode("utf-8", "replace")
                k["alt_sayfa"] = url
                z2 = re.search(r'href="([^"]+\.zip)"', alt)
                if not z2:
                    k["durum"] = "ZIP_YOK"
                    k["alt_baglantilar"] = re.findall(r'href="([^"]+)"', alt)[:100]
                    kayit["paketler"].append(k)
                    continue
                k["alt_sayfa_lisans"] = re.findall(r"(CC0|CC-BY[^<\s]*)", alt)[:5]
                url = urllib.parse.urljoin(url, html.unescape(z2.group(1)))
            # bağlantıdan önceki son bölüm başlığı ("... shared under CC0:" / "... under CC-BY:")
            once = h[: m.start()]
            bolumler = re.findall(r"shared under ([A-Za-z0-9\-\.]+)", once)
            k["bolum_lisansi"] = bolumler[-1] if bolumler else None
            k["url"] = url
            # Lisans: ana sayfa bölüm başlığı CC0 ya da (paket alt sayfası yalnız CC0 diyor ve zip adı _cc0)
            alt_lis = k.get("alt_sayfa_lisans") or []
            cc0 = k["bolum_lisansi"] == "CC0" or (alt_lis and all(x == "CC0" for x in alt_lis) and url.lower().endswith("_cc0.zip"))
            k["lisans_karari"] = "CC0" if cc0 else None
            if not cc0:
                k["durum"] = f"LISANS_RED ({k['bolum_lisansi']})"
                kayit["paketler"].append(k)
                continue
            uzak = UzakDosya(url)
            k["bayt"] = uzak.boy
            z = zipfile.ZipFile(io.BufferedReader(uzak, buffer_size=1 << 20))
            (kok / f"icerik_{p['ad']}.txt").write_text("\n".join(f"{i.file_size}\t{i.filename}" for i in z.infolist()))
            desen = re.compile(p.get("zip_deseni", r"$^"), re.I)
            acilan = [n for n in z.namelist() if desen.search(n) and not n.endswith("/")]
            ozet = {}
            for n in acilan:
                z.extract(n, kok / p["ad"])
                ozet[n] = hashlib.sha256((kok / p["ad"] / n).read_bytes()).hexdigest()
                print("  açıldı", n, flush=True)
            k["acilan"] = acilan
            k["acilan_sha256"] = ozet
            k["indirilen_bayt"] = uzak.indirilen
            k["durum"] = "TAMAM"
        except Exception as e:  # noqa: BLE001
            k["hata"] = repr(e)[:300]
        kayit["paketler"].append(k)
        print(json.dumps({x: k.get(x) for x in ("ad", "durum", "bolum_lisansi", "url", "bayt")}, ensure_ascii=False))
    (kok / "lisans.json").write_text(json.dumps(kayit, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
