"""Tariflerden karakter GLB'lerini derler ve ölçer.

python3 -m motor.varlik.derle [ad ...] [--zorla]

- Her tarif kayıttaki kimliklere çözülür; kayıtta olmayan ya da "dislandi" bir parça tarifi durdurur.
- Girdi anahtarı = tarif + kaynak dosyaların sha256'sı + betiklerin sha256'sı. Anahtar değişmediyse
  yeniden derlenmez (önbellek). Aynı anahtar her zaman aynı çıktıyı üretmeli (testte doğrulanır).
- Çıktı: ONBELLEK/karakter/<ad>.glb ve <ad>.olc.json; özet: motor/varlik/derlenmis.json
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import yaml

from motor import ayar
from motor.varlik import katalog

BURASI = Path(__file__).resolve().parent
BETIK = BURASI / "blender"
CIKTI = ayar.ONBELLEK / "karakter"
OZET = BURASI / "derlenmis.json"


def _sha_dosya(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def tarifleri_yukle() -> dict:
    t = yaml.safe_load(ayar.TARIFLER.read_text(encoding="utf-8"))
    ortak, kar = t["ortak"], t["karakterler"]
    cozulmus = {}
    for ad, r in kar.items():
        if "temel" in r:
            r = {**kar[r["temel"]], **{k: v for k, v in r.items() if k != "temel"}}
        cozulmus[ad] = {**ortak, **r}
    return cozulmus


def coz(ad: str, r: dict, kayit: dict) -> tuple[dict, list[dict]]:
    """Tarifi dosya yollarına çevirir; kullanılan kayıt girdilerini döner."""
    kullanilan = []

    def yol(kid):
        v = katalog.bul(kayit, kid)
        if v["durum"] == "dislandi":
            raise SystemExit(f"{ad}: dışlanmış varlık kullanılamaz: {kid}")
        kullanilan.append(v)
        return str(katalog.dosya_yolu(v))

    j = {
        "kiyafet": yol(r["kiyafet"]),
        "govde": yol(r["govde"]) if r.get("govde") else None,
        "ekler": [yol(e) for e in r.get("ekler", [])],
        "animasyonlar": r.get("animasyonlar", []),
        "animasyon_fbx": yol(r["animasyon_fbx"]) if r.get("animasyonlar") else None,
        "doku_siniri": r.get("doku_siniri", 1024),
        "renk": r.get("renk"),
        "cikti": str(CIKTI / f"{ad}.glb"),
    }
    return j, kullanilan


def anahtar(j: dict, kullanilan: list[dict]) -> str:
    h = hashlib.sha256()
    h.update(json.dumps({k: v for k, v in j.items() if k not in ("cikti",)}, sort_keys=True).encode())
    for v in kullanilan:
        h.update(v["sha256"].encode())
    for b in ("karakter_kur.py", "olc.py"):
        h.update(_sha_dosya(BETIK / b).encode())
    return h.hexdigest()[:16]


def derle(adlar: list[str] | None = None, zorla: bool = False) -> dict:
    CIKTI.mkdir(parents=True, exist_ok=True)
    kayit = katalog.yukle()
    tarifler = tarifleri_yukle()
    ozet = json.loads(OZET.read_text()) if OZET.exists() else {}
    for ad, r in tarifler.items():
        if adlar and ad not in adlar:
            continue
        j, kullanilan = coz(ad, r, kayit)
        k = anahtar(j, kullanilan)
        glb = Path(j["cikti"])
        olc = glb.with_suffix(".olc.json")
        if not zorla and ozet.get(ad, {}).get("anahtar") == k and glb.exists() and olc.exists():
            print("ONBELLEKTE", ad)
            continue
        tj = CIKTI / f"{ad}.tarif.json"
        tj.write_text(json.dumps(j, ensure_ascii=False, indent=1))
        t0 = time.time()
        p = subprocess.run([sys.executable, str(BETIK / "karakter_kur.py"), str(tj)], capture_output=True, text=True, timeout=1200)
        if p.returncode != 0 or not glb.exists():
            print(p.stdout[-2000:], p.stderr[-3000:])
            raise SystemExit(f"DERLEME HATASI: {ad}")
        sure = time.time() - t0
        p = subprocess.run([sys.executable, str(BETIK / "olc.py"), str(glb), str(olc), str(BURASI / "evrensel_iskelet.json")],
                           capture_output=True, text=True, timeout=600)
        if p.returncode != 0:
            print(p.stderr[-3000:])
            raise SystemExit(f"ÖLÇÜM HATASI: {ad}")
        ozet[ad] = {
            "anahtar": k,
            "glb_sha256": _sha_dosya(glb),
            "bayt": glb.stat().st_size,
            "derleme_sn": round(sure, 1),
            "kaynaklar": [v["id"] for v in kullanilan],
            "lisanslar": sorted({v["lisans"] for v in kullanilan}),
            "olcum": json.loads(olc.read_text()),
        }
        print("DERLENDI", ad, f"{glb.stat().st_size/1e6:.1f} MB", f"{sure:.0f} sn")
        OZET.write_text(json.dumps(ozet, ensure_ascii=False, indent=1))
    return ozet


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    derle(a or None, "--zorla" in sys.argv)
