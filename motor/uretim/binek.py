"""Sinematik paket — binek (at) desteği: GLB üretimi (önbellek), ölçülen yürüyüş hızları, planlayıcı ve render bilgisi.

Binek yalnızca kurallar/binek.yaml'daki eylemlerde ve yalnızca "binek: <id>" taşıyan takımlarla kullanılır; GLB yoksa
üretilir, üretilemezse binek yok sayılır (planlayıcı eksik raporlar, uydurmaz)."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from motor import ayar
from motor.uretim import veri

BETIK = ayar.MOTOR / "varlik" / "blender" / "binek_uret.py"


def kural() -> dict:
    return veri.kural("binek")


def yurus(eylem: str | None) -> dict | None:
    return kural()["yuruyusler"].get(eylem) if eylem else None


def _anahtar(bid: str) -> str:
    b = kural()["binekler"][bid]
    h = hashlib.sha256(BETIK.read_bytes())
    h.update((ayar.MOTOR / b["kaynak"]).read_bytes())
    h.update(str(b["yukseklik_m"]).encode())
    return h.hexdigest()[:16]


def glb(bid: str) -> Path:
    return ayar.ONBELLEK / "binek" / f"{bid}.glb"


def hazir(bid: str, uret: bool = True) -> bool:
    """GLB güncel mi; değilse (uret=True) Blender betiğiyle üretir."""
    g = glb(bid)
    anahtar_yolu = g.with_suffix(".anahtar")
    a = _anahtar(bid)
    if g.exists() and anahtar_yolu.exists() and anahtar_yolu.read_text() == a:
        return True
    if not uret:
        return False
    b = kural()["binekler"][bid]
    g.parent.mkdir(parents=True, exist_ok=True)
    p = subprocess.run([sys.executable, str(BETIK), str(ayar.MOTOR / b["kaynak"]), str(g), str(b["yukseklik_m"])],
                       capture_output=True, text=True, timeout=600)
    if p.returncode != 0 or not g.exists():
        print(p.stdout[-2000:], p.stderr[-2000:])
        return False
    anahtar_yolu.write_text(a)
    return True


def olcum(bid: str) -> dict:
    return json.loads(glb(bid).with_suffix(".olc.json").read_text())


def hiz(bid: str, animasyon: str) -> float:
    return float(olcum(bid)["animasyonlar"][animasyon]["zemin_hizi_m_sn"])


def plan_bilgisi(eylem: str | None) -> dict | None:
    """Planda karaktere yazılacak binek bilgisi: {id, animasyon, hiz_m_sn}; binek yoksa None."""
    y = yurus(eylem)
    if not y or not hazir(y["binek"]):
        return None
    return {"id": y["binek"], "animasyon": y["animasyon"], "hiz_m_sn": round(hiz(y["binek"], y["animasyon"]), 4)}


def render_bilgisi(b: dict) -> dict:
    """is.json için: GLB yolu ve görünüm ayarları."""
    k = kural()["binekler"][b["id"]]
    return {"glb": str(glb(b["id"])), "animasyon": b["animasyon"], "donlar": k["donlar"], "eyer_kemik": k["eyer_kemik"],
            "eyer_ust_m": k["eyer_ust_m"], "eyer_z_m": k["eyer_z_m"], "uyluk_asagi_derece": k["uyluk_asagi_derece"],
            "uyluk_disa_derece": k["uyluk_disa_derece"]}
