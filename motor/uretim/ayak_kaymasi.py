"""Ayak kayması ÖLÇÜMÜ (Godot'ta, render motorunun kendi oynatıcısıyla): yer değiştiren animasyon, planın verdiği hızla
ilerletildiğinde yere basan ayak zemine göre ne kadar kayıyor?

python3 -m motor.uretim.ayak_kaymasi <takim> <animasyon> [hiz]   (hiz verilmezse ölçülmüş zemin hızı)
Sonuç: basan ayağın ortalama yatay kayma hızı (m/sn).

Kabul ölçütü (karşılaştırmalı, sabit bir eşik değil): planın kullandığı hız, ölçülen hızın %90-110'u arasındaki
taramada kaymayı en aza indiren hız olmalı (en iyi değerden en çok 0,01 m/sn kötü) ve kayma, karakter yerinde
oynatıldığındaki kaymanın %25'inden az olmalı. Kalan kayma animasyon varlığının kendi özelliğidir (basan ayağın hızı
döngü içinde sabit değil); ayrıca raporlanır, gizlenmez.
"""
from __future__ import annotations

import json
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

from motor import ayar
from motor.uretim import animasyon_izni, veri

FPS = 30
TEMAS_M = 0.012   # ayak tabanı en alçak konumundan en çok bu kadar yüksekteyse "yere basıyor" sayılır


def olc(takim: str, anim: str, hiz: float | None = None, sure: float = 4.0) -> dict:
    hiz = animasyon_izni.zemin_hizi(anim) if hiz is None else hiz
    with tempfile.TemporaryDirectory() as d:
        tj, cj = Path(d) / "t.json", Path(d) / "c.json"
        tj.write_text(json.dumps(veri.takimlar()[takim]))
        subprocess.run([ayar.GODOT, "--headless", "--path", str(ayar.GODOT_PROJE), "res://sahneler/ayak_olcum.tscn",
                        "--fixed-fps", str(FPS), "--quit-after", str(int(sure * FPS)), "--", str(tj), anim, str(hiz), str(cj)],
                       capture_output=True, text=True, timeout=300, check=True)
        k = json.loads(cj.read_text())
    taban = {a: min(x[a][1] for x in k) for a in ("ball_l", "ball_r")}
    kaymalar = []
    for i in range(1, len(k)):
        alt = min(("ball_l", "ball_r"), key=lambda a: k[i][a][1])
        if k[i][alt][1] > taban[alt] + TEMAS_M or k[i - 1][alt][1] > taban[alt] + TEMAS_M:
            continue  # bu ayak bu iki karede yere basmıyor
        dx = k[i][alt][0] - k[i - 1][alt][0]
        dz = k[i][alt][2] - k[i - 1][alt][2]
        kaymalar.append((dx * dx + dz * dz) ** 0.5 * FPS)
    ort = statistics.mean(kaymalar) if kaymalar else None
    return {"takim": takim, "animasyon": anim, "ilerleme_hizi_m_sn": hiz, "basan_ayak_kare": len(kaymalar),
            "basan_ayak_kaymasi_m_sn": round(ort, 4) if ort is not None else None}


def degerlendir(takim: str, anim: str) -> dict:
    """Ölçülen hızı, çevresindeki hızlarla ve yerinde oynatmayla karşılaştırır."""
    v = animasyon_izni.zemin_hizi(anim)
    tarama = {round(v * f, 3): olc(takim, anim, v * f)["basan_ayak_kaymasi_m_sn"] for f in (0.9, 0.95, 1.0, 1.05, 1.1)}
    yerinde = olc(takim, anim, 0.0)["basan_ayak_kaymasi_m_sn"]
    plan = tarama[round(v, 3)]
    en_iyi = min(tarama.values())
    return {"takim": takim, "animasyon": anim, "olculen_zemin_hizi": v, "tarama": tarama, "yerinde_kayma": yerinde,
            "plan_hizinda_kayma": plan, "ilerleme_hizina_orani": round(plan / v, 3),
            "gecti": plan <= en_iyi + 0.01 and plan < 0.25 * yerinde}


if __name__ == "__main__":
    if len(sys.argv) > 3:
        print(json.dumps(olc(sys.argv[1], sys.argv[2], float(sys.argv[3])), ensure_ascii=False, indent=1))
    else:
        print(json.dumps(degerlendir(sys.argv[1], sys.argv[2]), ensure_ascii=False, indent=1))
