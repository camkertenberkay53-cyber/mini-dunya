"""M10 (ön ölçüm) — Seslendirme süresi ÖLÇÜMÜ: senaryo cümleleri gerçekten seslendirilir, süreleri ölçülür.

Sahne süreleri tahminle değil, bu ölçümle belirlenir. Ses üretimi eski botun mevcut kodudur (kaos/audio/tts.py),
değiştirilmeden çağrılır. Her ölçüm hangi motorla yapıldığını kaydeder (motor değişirse süreler değişir).

Faz-65: motor seçimi MOTOR_TTS ortam değişkeniyle: 'piper' (varsayılan; çevrimdışı testler) ya da 'edge'
(gerçek üretim: ücretsiz Microsoft sinirsel ses tr-TR-AhmetNeural, config.yaml voices.<konuşan>.edge). Edge ağ ya da
paket hatası verirse senaryonun TAMAMI Piper'la üretilir (bir videoda iki ses karışmaz) ve sonuçta 'yedek_nedeni'
yazar; sessiz taklit yoktur. Kurgu, planın kaydettiği motoru yedeksiz (yedek=False) ister: plan ile kurgu aynı
dosyaları kullanır (workflow ses önbelleğini plan job'undan kurgu job'una taşır).

python3 -m motor.uretim.seslendirme <senaryo.json>
"""
from __future__ import annotations

import hashlib
import json
import os
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


MOTORLAR = ("edge", "piper")
# Faz-65: süreç içinde yapışkan yedek — edge bir kez düştüyse aynı süreçteki sonraki ölçümler de Piper'la yapılır
# (senaryo kapısı, yeniden denemeler ve çekim planı aynı sesle ölçülür; düşen ağa her çağrıda yeniden gidilmez).
_DUSEN: dict[str, str] = {}


def tercih() -> str:
    """MOTOR_TTS ortam değişkeni (boş/yok → 'piper'). Tanınmayan değer açık hatadır."""
    m = (os.environ.get("MOTOR_TTS") or "piper").strip().lower()
    if m not in MOTORLAR:
        raise SystemExit(f"MOTOR_TTS='{m}' tanınmıyor (geçerli: {', '.join(MOTORLAR)})")
    return m


def _hedefler(cumleler: list[dict], konusan: str, cfg: dict, motor: str) -> dict:
    """{cumle_id: (okunuş metni, wav yolu)}. Anahtar Faz-65 öncesiyle aynı (piper önbelleği geçerli kalır)."""
    h = {}
    for c in cumleler:
        metin = okunus(c)
        anahtar = hashlib.sha1(json.dumps([metin, konusan, cfg["voices"][konusan], motor], ensure_ascii=False).encode()).hexdigest()[:16]
        h[c["id"]] = (metin, ONBELLEK / f"{anahtar}.wav")
    return h


def _uret(motor: str, eksik: list[tuple], cfg: dict, konusan: str) -> None:
    from kaos.audio import tts
    satirlar = [((i, 0), konusan, m, "normal") for i, (_, m, _) in enumerate(eksik)]
    if motor == "piper":
        cikti = tts.piper_tts(satirlar, cfg, str(ONBELLEK), str(ayar.REPO / "models"))
    else:
        cikti = tts.edge_tts(satirlar, cfg, str(ONBELLEK))
    for i, (_, _, wav) in enumerate(eksik):
        Path(cikti[(i, 0)]).replace(wav)
        Path(cikti[(i, 0)]).with_suffix(".mp3").unlink(missing_ok=True)   # edge ara dosyası


def olc(cumleler: list[dict], konusan: str = "anlatici", motor: str | None = None, yedek: bool = True) -> dict:
    """Dönüş: {cumle_id: {"sure_sn", "harf_sn", "motor", "wav", ("yedek_nedeni")}}.
    motor None → tercih() (MOTOR_TTS). yedek=True ve motor 'edge' ise edge hatasında bütün cümleler Piper'la üretilir."""
    motor = motor or tercih()
    if motor not in MOTORLAR:
        raise SystemExit(f"'{motor}' seslendirme motoru tanınmıyor (geçerli: {', '.join(MOTORLAR)})")
    cfg = yaml.safe_load((ayar.REPO / "config.yaml").read_text())
    ONBELLEK.mkdir(parents=True, exist_ok=True)
    sira = [motor] + (["piper"] if yedek and motor != "piper" else [])
    neden = None
    if yedek and motor in _DUSEN:
        sira, neden = sira[1:], _DUSEN[motor]
    for m in sira:
        hedef = _hedefler(cumleler, konusan, cfg, m)
        eksik = [(cid, metin, wav) for cid, (metin, wav) in hedef.items() if not wav.exists()]
        if eksik:
            try:
                _uret(m, eksik, cfg, konusan)
            except Exception as e:   # noqa: BLE001 — ağ/paket/ffmpeg: yedeğe düşülür, son motorda yükselir
                if m == sira[-1]:
                    raise
                neden = _DUSEN[m] = f"{m}: {type(e).__name__}: {str(e)[:200]}"
                print(f"seslendirme: {neden} — senaryonun tamamı {sira[-1]} ile üretiliyor", file=sys.stderr, flush=True)
                continue
        sonuc = {}
        for cid, (metin, wav) in hedef.items():
            x, sr = sf.read(str(wav))
            r = {"metin": metin, "wav": str(wav), "sure_sn": round(len(x) / sr, 3)}
            r["harf_sn"] = round(len(metin.replace(" ", "")) / max(r["sure_sn"], 0.1), 1)
            r["motor"] = m
            if neden:
                r["yedek_nedeni"] = neden
            sonuc[cid] = r
        return sonuc
    raise AssertionError("ulaşılamaz")


def plana_uygun(sureler: dict, cizelge: list[dict], tolerans_sn: float = 0.05) -> list[str]:
    """Kurgu kapısı: kurguda okunan ses dosyalarının süresi planın zaman çizelgesiyle aynı olmalı (aksi hâlde cümleler
    kayar ya da üst üste biner). Dönüş: uyuşmazlıklar."""
    h = []
    for z in cizelge:
        r = sureler.get(z["cumle"])
        if r is None:
            h.append(f"{z['cumle']}: seslendirme yok")
        elif abs(r["sure_sn"] - z["ses_sure_sn"]) > tolerans_sn:
            h.append(f"{z['cumle']}: seslendirme {r['sure_sn']} sn, plan {z['ses_sure_sn']} sn ({r['motor']})")
    return h


if __name__ == "__main__":
    s = json.loads(Path(sys.argv[1]).read_text())
    r = olc(s["cumleler"])
    for cid, x in r.items():
        print(cid, x["sure_sn"], "sn", x["harf_sn"], "harf/sn", x["metin"])
    print("toplam", round(sum(x["sure_sn"] for x in r.values()), 2))
