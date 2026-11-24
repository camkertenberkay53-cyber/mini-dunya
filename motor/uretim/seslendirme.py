"""M10 (ön ölçüm) — Seslendirme süresi ÖLÇÜMÜ: senaryo cümleleri gerçekten seslendirilir, süreleri ölçülür.

Sahne süreleri tahminle değil, bu ölçümle belirlenir. Ses üretimi eski botun mevcut kodudur (kaos/audio/tts.py),
değiştirilmeden çağrılır. Bulut ortamında yalnızca yerel Piper çalışır; yayın sırası (Gemini -> Edge -> Piper)
farklı bir motor seçerse süreler değişir: o yüzden her ölçüm hangi motorla yapıldığını kaydeder.

python3 -m motor.uretim.seslendirme <senaryo.json>
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import soundfile as sf
import yaml

from motor import ayar

ONBELLEK = ayar.ONBELLEK / "seslendirme"


def okunus(c: dict) -> str:
    """Seslendirilecek metin: cümlenin 'okunus' alanı varsa o, yoksa metin (rakamlar yazıya çevrilir)."""
    from kaos.sinema.motor import okunus as rakam_yazi
    return rakam_yazi(c.get("okunus") or c["metin"])


def olc(cumleler: list[dict], konusan: str = "anlatici", motor: str = "piper") -> dict:
    """Dönüş: {cumle_id: {"sure_sn", "harf_sn", "motor", "wav"}}"""
    from kaos.audio import tts
    cfg = yaml.safe_load((ayar.REPO / "config.yaml").read_text())
    ONBELLEK.mkdir(parents=True, exist_ok=True)
    sonuc, eksik = {}, []
    for c in cumleler:
        metin = okunus(c)
        anahtar = hashlib.sha1(json.dumps([metin, konusan, cfg["voices"][konusan], motor], ensure_ascii=False).encode()).hexdigest()[:16]
        wav = ONBELLEK / f"{anahtar}.wav"
        if not wav.exists():
            eksik.append((c["id"], metin, wav))
        sonuc[c["id"]] = {"metin": metin, "wav": str(wav)}
    if eksik:
        if motor != "piper":
            raise SystemExit(f"{motor} bu ortamda ölçülemiyor")
        satirlar = [((i, 0), konusan, m, "normal") for i, (_, m, _) in enumerate(eksik)]
        cikti = tts.piper_tts(satirlar, cfg, str(ONBELLEK), str(ayar.REPO / "models"))
        for i, (_, _, wav) in enumerate(eksik):
            Path(cikti[(i, 0)]).replace(wav)
    for cid, r in sonuc.items():
        x, sr = sf.read(r["wav"])
        r["sure_sn"] = round(len(x) / sr, 3)
        r["harf_sn"] = round(len(r["metin"].replace(" ", "")) / max(r["sure_sn"], 0.1), 1)
        r["motor"] = motor
    return sonuc


if __name__ == "__main__":
    s = json.loads(Path(sys.argv[1]).read_text())
    r = olc(s["cumleler"])
    for cid, x in r.items():
        print(cid, x["sure_sn"], "sn", x["harf_sn"], "harf/sn", x["metin"])
    print("toplam", round(sum(x["sure_sn"] for x in r.values()), 2))
