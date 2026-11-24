"""Plan katmanının okuduğu bütün kabul edilmiş veriler (Faz 2-3b çıktıları) tek yerden, salt okunur yüklenir.
Bu modül hiçbir Faz 3b dosyasını değiştirmez."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import yaml

from motor import ayar

URETIM = Path(__file__).resolve().parent
KURALLAR = URETIM / "kurallar"
SEMALAR = URETIM / "semalar"
KARAKTER = ayar.MOTOR / "karakter"
TAKIM_KLASORU = ayar.ONBELLEK / "takim"


def _yaml(p: Path):
    return yaml.safe_load(p.read_text())


@lru_cache(None)
def kural(ad: str) -> dict:
    return _yaml(KURALLAR / f"{ad}.yaml")


@lru_cache(None)
def animasyon_olcum() -> dict:
    return json.loads((KURALLAR / "animasyon_olcum.json").read_text())["animasyonlar"]


@lru_cache(None)
def kitler() -> dict[str, dict]:
    return {p.stem: _yaml(p) for p in sorted((ayar.MOTOR / "kit" / "faz3").glob("*.yaml"))}


def kit_donemi(kit: str) -> str:
    return kitler()[kit]["etiket"]


@lru_cache(None)
def takimlar() -> dict[str, dict]:
    """Derlenmiş takım dosyaları (karakter = gövde + takılanlar). Faz 3b derlemesinin çıktısı."""
    t = {}
    for p in sorted(TAKIM_KLASORU.glob("*.json")):
        x = json.loads(p.read_text())
        t[x["ad"]] = x
    return t


@lru_cache(None)
def kalite() -> dict:
    return json.loads((KARAKTER / "kalite.json").read_text())


@lru_cache(None)
def montaj() -> dict:
    return json.loads((KARAKTER / "montaj_testi.json").read_text())


@lru_cache(None)
def animasyon_testi() -> dict:
    p = KARAKTER / "animasyon_testi.json"
    return json.loads(p.read_text()) if p.exists() else {"animasyonlar": [], "takimlar": {}}


@lru_cache(None)
def ekipman_katalogu() -> dict:
    return _yaml(ayar.MOTOR / "varlik" / "ekipman.yaml")


def parca(pid: str) -> dict | None:
    return ekipman_katalogu()["parcalar"].get(pid)


def ekipman_turu(pid: str) -> str | None:
    for tur, liste in kural("ekipman_turleri")["turler"].items():
        if pid in liste:
            return tur
    return None


@lru_cache(None)
def glb_yuksekligi(yol: str) -> float:
    """GLB'deki bütün POSITION erişimcilerinin dikey (Y) aralığı. Düğüm dönüşümleri yok sayılır (çevre varlıklarında
    kök dönüşümü birimdir); yalnızca kamera mesafe sınıfını hesaplamak için kullanılır."""
    import struct
    b = Path(yol).read_bytes()
    n = struct.unpack("<I", b[12:16])[0]
    j = json.loads(b[20:20 + n])
    lo, hi = [], []
    for m in j.get("meshes", []):
        for p in m["primitives"]:
            a = j["accessors"][p["attributes"]["POSITION"]]
            lo.append(a["min"][1])
            hi.append(a["max"][1])
    return max(hi) - min(lo) if hi else 0.0


@lru_cache(None)
def glb_yayilimi(yol: str) -> float:
    """GLB'nin yatay (XZ) yarı genişliği (m): çevre varlığının kapladığı alanın yarıçapı için."""
    import struct
    b = Path(yol).read_bytes()
    n = struct.unpack("<I", b[12:16])[0]
    j = json.loads(b[20:20 + n])
    r = 0.0
    for m in j.get("meshes", []):
        for p in m["primitives"]:
            a = j["accessors"][p["attributes"]["POSITION"]]
            r = max(r, abs(a["min"][0]), abs(a["max"][0]), abs(a["min"][2]), abs(a["max"][2]))
    return r


def ekipman_glb(pid: str) -> Path:
    return ayar.ONBELLEK / "ekipman" / f"{pid}.glb"
