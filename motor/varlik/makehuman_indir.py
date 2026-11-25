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
import urllib.request
import zipfile
from pathlib import Path

UA = {"User-Agent": "mini-dunya-varlik (github.com/camkertenberkay53-cyber/mini-dunya)"}
SAYFA = "https://static.makehumancommunity.org/assets/assetpacks.html"


def al(url: str) -> bytes:
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=600).read()


def main(istek_yolu: str) -> int:
    istek = json.loads(Path(istek_yolu).read_text())
    kok = Path(istek_yolu).parent
    h = al(SAYFA).decode("utf-8", "replace")
    kayit = {"sayfa": SAYFA, "paketler": []}
    for p in istek["paketler"]:
        k = {"ad": p["ad"], "durum": "BASARISIZ"}
        try:
            m = re.search(r'href="([^"]*' + re.escape(p["dosya_deseni"]) + r'[^"]*\.zip)"', h)
            if not m:
                k["durum"] = "BAGLANTI_YOK"
                kayit["paketler"].append(k)
                continue
            url = html.unescape(m.group(1))
            if not url.startswith("http"):
                url = "https://static.makehumancommunity.org/assets/" + url.lstrip("./")
            # bağlantıdan önceki son bölüm başlığı ("... shared under CC0:" / "... under CC-BY:")
            once = h[: m.start()]
            bolumler = re.findall(r"shared under ([A-Za-z0-9\-\.]+)", once)
            k["bolum_lisansi"] = bolumler[-1] if bolumler else None
            k["url"] = url
            if k["bolum_lisansi"] != "CC0":
                k["durum"] = f"LISANS_RED ({k['bolum_lisansi']})"
                kayit["paketler"].append(k)
                continue
            veri = al(url)
            k["bayt"] = len(veri)
            k["sha256"] = hashlib.sha256(veri).hexdigest()
            z = zipfile.ZipFile(io.BytesIO(veri))
            (kok / f"icerik_{p['ad']}.txt").write_text("\n".join(f"{i.file_size}\t{i.filename}" for i in z.infolist()))
            desen = re.compile(p.get("zip_deseni", r"$^"), re.I)
            acilan = [n for n in z.namelist() if desen.search(n) and not n.endswith("/")]
            for n in acilan:
                z.extract(n, kok / p["ad"])
            k["acilan"] = acilan
            k["durum"] = "TAMAM"
        except Exception as e:  # noqa: BLE001
            k["hata"] = repr(e)[:300]
        kayit["paketler"].append(k)
        print(json.dumps({x: k.get(x) for x in ("ad", "durum", "bolum_lisansi", "url", "bayt")}, ensure_ascii=False))
    (kok / "lisans.json").write_text(json.dumps(kayit, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
