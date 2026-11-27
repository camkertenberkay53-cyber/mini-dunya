"""OpenGameArt varlık indirici (Actions'ta çalışır; sandbox OGA'ya erişemez).

Kullanım: python3 -m motor.varlik.oga_indir motor/varlik/oga/istek.json
Her istek için içerik sayfası okunur, LİSANS SAYFADAN doğrulanır (yalnız istenen lisanslar: varsayılan CC0), dosya
bağlantıları sayfadan alınır, isteğin 'dosya_deseni' ile süzülür, indirilir, zip ise açılır. Lisans tutmazsa hiçbir
dosya alınmaz. Kayıt: motor/varlik/oga/lisans.json (sayfa, yazar, lisans, dosyalar, sha256)."""
from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

UA = {"User-Agent": "mini-dunya-varlik (github.com/camkertenberkay53-cyber/mini-dunya)"}


def al(url: str) -> bytes:
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120).read()


def main(istek_yolu: str) -> int:
    istek = json.loads(Path(istek_yolu).read_text())
    kok = Path(istek_yolu).parent
    kayit = []
    for it in istek["varliklar"]:
        sayfa = f"https://opengameart.org/content/{it['sayfa']}"
        k = {"kimlik": it["kimlik"], "sayfa": sayfa, "amac": it.get("amac"), "durum": "BASARISIZ", "dosyalar": []}
        try:
            h = al(sayfa).decode("utf-8", "replace")
            lis = re.search(r"License\(s\):.*?</div>\s*</div>", h, re.S)
            lisanslar = re.findall(r">\s*(CC0|CC-BY [0-9.]+|CC-BY-SA [0-9.]+|GPL [0-9.]+|OGA-BY [0-9.]+)\s*<", lis.group(0) if lis else "")
            yazar = re.search(r"Author:.*?<a[^>]*>([^<]+)</a>", h, re.S)
            k["lisanslar_sayfada"] = lisanslar
            k["yazar"] = html.unescape(yazar.group(1)).strip() if yazar else None
            izin = istek.get("izinli_lisanslar", ["CC0"])
            if not lisanslar or any(x not in izin for x in lisanslar):
                k["durum"] = f"LISANS_RED ({lisanslar})"
                kayit.append(k)
                continue
            linkler = sorted(set(re.findall(r'href="(https://opengameart\.org/sites/default/files/[^"]+)"', h)))
            desen = re.compile(it.get("dosya_deseni", ".*"), re.I)
            hedef = kok / it["kimlik"]
            hedef.mkdir(parents=True, exist_ok=True)
            for u in linkler:
                ad = urllib.parse.unquote(u.rsplit("/", 1)[1])
                # önizleme görselleri atlanır; doku paketlerinde (goruntu: true) görsel dosyanın kendisi varlıktır
                if not desen.search(ad) or (not it.get("goruntu") and re.search(r"\.(png|jpg|gif|jpeg)$", ad, re.I)):
                    continue
                veri = al(u)
                d = hedef / ad
                d.write_bytes(veri)
                g = {"dosya": f"{it['kimlik']}/{ad}", "url": u, "bayt": len(veri), "sha256": hashlib.sha256(veri).hexdigest()}
                if ad.lower().endswith(".zip"):
                    with zipfile.ZipFile(d) as z:
                        ic = [n for n in z.namelist() if re.search(it.get("zip_deseni", ".*"), n, re.I) and not n.endswith("/")]
                        for n in ic:
                            z.extract(n, hedef)
                        g["acilan"] = ic
                    d.unlink()
                k["dosyalar"].append(g)
            k["durum"] = "TAMAM" if k["dosyalar"] else "DOSYA_YOK"
        except Exception as e:  # noqa: BLE001
            k["hata"] = repr(e)[:300]
        kayit.append(k)
        print(json.dumps({x: k.get(x) for x in ("kimlik", "durum", "lisanslar_sayfada", "yazar")}, ensure_ascii=False))
    (kok / "lisans.json").write_text(json.dumps({"kaynak": "OpenGameArt.org", "varliklar": kayit}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
