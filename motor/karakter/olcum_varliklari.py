"""Faz 3 render ölçümü için derlenmiş takımların küçük bir kopyasını Godot projesine koyar (GitHub'da kaynak depo yok).

python3 -m motor.karakter.olcum_varliklari -> motor/godot/varlik/faz3/{govde,ekipman}/*.glb + takimlar.json (res:// yolları)
"""
import json
import shutil
from pathlib import Path

from motor import ayar
from motor.karakter import takim

SECIM = ["osm_yeniceri_mizrak", "akk_zirhli_mizrak", "biz_piyade_mizrak", "rom_lejyoner_pilum", "osm_yeniceri_kilic", "rom_lejyoner_gladius"]
HEDEF = ayar.GODOT_PROJE / "varlik" / "faz3"


def kopyala() -> list[dict]:
    shutil.rmtree(HEDEF, ignore_errors=True)
    (HEDEF / "govde").mkdir(parents=True)
    (HEDEF / "ekipman").mkdir(parents=True)
    liste = []
    for ad in SECIM:
        t = json.loads((takim.TAKIM_CIKTI / f"{ad}.json").read_text())
        g = Path(t["glb"])
        shutil.copy(g, HEDEF / "govde" / g.name)
        t["glb"] = f"res://varlik/faz3/govde/{g.name}"
        for e in t["takilanlar"]:
            s = Path(e["glb"])
            shutil.copy(s, HEDEF / "ekipman" / s.name)
            e["glb"] = f"res://varlik/faz3/ekipman/{s.name}"
        liste.append(t)
    (HEDEF / "takimlar.json").write_text(json.dumps(liste, ensure_ascii=False, indent=1))
    return liste


if __name__ == "__main__":
    print(len(kopyala()), "takım kopyalandı;", sum(f.stat().st_size for f in HEDEF.rglob("*.glb")) // 1024, "KB")
