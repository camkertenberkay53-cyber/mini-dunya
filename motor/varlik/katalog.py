"""Varlık kaydı: kaynak depolardaki her dosyayı lisans, köken ve özetiyle kaydeder.

Kullanım:  python3 -m motor.varlik.katalog            (kayit.json yazar)
           python3 -m motor.varlik.katalog --dogrula  (kaydı kaynaklara karşı denetler)

Kayıt kuralları:
- Lisansı kaynaklar.yaml'da açıkça yazmayan ve lisans dosyası diskte bulunmayan kaynak kaydedilmez.
- Kaynak deposu kaynaklar.yaml'daki commit'te değilse işlem durur (sessiz sürüm kayması yok).
- Kurallarda adı geçmeyen paket "dislandi" olarak kaydedilir; hiçbir kite giremez.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import yaml

from motor import ayar

BURASI = Path(__file__).resolve().parent
ZORUNLU_ALANLAR = ("id", "kaynak", "yol", "lisans", "kaynak_commit", "sha256", "bayt", "tur", "donem", "durum", "kalite")


def _yaml(ad: str) -> dict:
    return yaml.safe_load((BURASI / ad).read_text(encoding="utf-8"))


def _sha(yol: Path) -> str:
    h = hashlib.sha256()
    with open(yol, "rb") as f:
        for parca in iter(lambda: f.read(1 << 20), b""):
            h.update(parca)
    return h.hexdigest()


def _commit(klasor: Path) -> str:
    return subprocess.run(["git", "-C", str(klasor), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()


def kaynak_klasoru(kaynak_adi: str) -> Path:
    return ayar.KAYNAK_KOK / _yaml("kaynaklar.yaml")[kaynak_adi]["klasor"]


def katalogla() -> dict:
    kaynaklar = _yaml("kaynaklar.yaml")
    kurallar = _yaml("kurallar.yaml")
    kayitlar, ozet = [], {}
    for ad, k in kaynaklar.items():
        klasor = ayar.KAYNAK_KOK / k["klasor"]
        if not klasor.is_dir():
            raise SystemExit(f"KAYNAK YOK: {ad} -> {klasor}. Önce klonlayın: git clone {k['url']}")
        lisans = klasor / k["lisans_dosyasi"]
        if not lisans.is_file():
            raise SystemExit(f"LİSANS DOSYASI YOK: {ad} ({lisans}). Kaynak kaydedilmez.")
        metin = lisans.read_text(errors="ignore")
        if k["lisans"] == "CC0-1.0" and "CC0" not in metin and "Creative Commons Zero" not in metin and "CC0 1.0" not in metin:
            raise SystemExit(f"LİSANS METNİ CC0 DEĞİL: {ad}")
        commit = _commit(klasor)
        if commit != k["commit"]:
            raise SystemExit(f"SÜRÜM KAYMASI: {ad} beklenen {k['commit'][:10]}, bulunan {commit[:10]}")
        kok = klasor / k["kok"]
        kural = kurallar.get(ad, {})
        for dosya in sorted(kok.rglob("*")):
            if not dosya.is_file() or dosya.suffix.lower() not in k["uzantilar"] or ".git" in dosya.parts:
                continue
            rel = dosya.relative_to(kok)
            paket = rel.parts[0] if len(rel.parts) > 1 else "*"
            r = kural.get(paket) or kural.get("*")
            durum = "aday" if r else "dislandi"
            r = r or {"tur": "ilgisiz", "donem": ["dislandi"]}
            kid = f"{ad}/{rel.as_posix()}"
            kayitlar.append({
                "id": kid,
                "kaynak": ad,
                "paket": paket,
                "yol": rel.as_posix(),
                "lisans": k["lisans"],
                "yazar": k["yazar"],
                "kaynak_url": k["url"],
                "kaynak_commit": commit,
                "sha256": _sha(dosya),
                "bayt": dosya.stat().st_size,
                "tur": r["tur"],
                "donem": r["donem"],
                "durum": durum,
                "kalite": "denetlenmedi",
                "not": r.get("not", ""),
            })
            ozet.setdefault(durum, 0)
            ozet[durum] += 1
    return {"surum": 1, "ozet": ozet, "varliklar": kayitlar}


def dogrula(kayit: dict) -> list[str]:
    """Kaydın kendi içinde tutarlı ve kaynaklarla aynı olduğunu denetler. Hata listesi döner."""
    hatalar = []
    gorulen = set()
    kaynaklar = _yaml("kaynaklar.yaml")
    for v in kayit["varliklar"]:
        for a in ZORUNLU_ALANLAR:
            if a not in v or v[a] in (None, "", []):
                hatalar.append(f"{v.get('id')}: eksik alan {a}")
        if v["id"] in gorulen:
            hatalar.append(f"{v['id']}: tekrar eden kimlik")
        gorulen.add(v["id"])
        if v["lisans"] not in ("CC0-1.0",):
            hatalar.append(f"{v['id']}: izin verilmeyen lisans {v['lisans']}")
        k = kaynaklar.get(v["kaynak"])
        if not k:
            hatalar.append(f"{v['id']}: bilinmeyen kaynak")
            continue
        dosya = ayar.KAYNAK_KOK / k["klasor"] / k["kok"] / v["yol"]
        if not dosya.is_file():
            hatalar.append(f"{v['id']}: dosya yok")
        elif dosya.stat().st_size != v["bayt"]:
            hatalar.append(f"{v['id']}: boyut değişmiş")
    return hatalar


def yukle() -> dict:
    return json.loads(ayar.KAYIT.read_text(encoding="utf-8"))


def bul(kayit: dict, kid: str) -> dict:
    for v in kayit["varliklar"]:
        if v["id"] == kid:
            return v
    raise KeyError(f"Kayıtta yok: {kid}")


def dosya_yolu(v: dict) -> Path:
    k = _yaml("kaynaklar.yaml")[v["kaynak"]]
    return ayar.KAYNAK_KOK / k["klasor"] / k["kok"] / v["yol"]


if __name__ == "__main__":
    if "--dogrula" in sys.argv:
        h = dogrula(yukle())
        print("KAYIT HATASI:", len(h))
        for x in h[:50]:
            print(" -", x)
        sys.exit(1 if h else 0)
    kayit = katalogla()
    # Varlık başına bir satır: git farkı okunur kalır
    satirlar = ",\n".join(json.dumps(v, ensure_ascii=False, separators=(",", ":")) for v in kayit["varliklar"])
    ayar.KAYIT.write_text('{"surum":1,"ozet":' + json.dumps(kayit["ozet"]) + ',"varliklar":[\n' + satirlar + "\n]}\n", encoding="utf-8")
    print("YAZILDI", ayar.KAYIT, kayit["ozet"], "toplam", len(kayit["varliklar"]))
