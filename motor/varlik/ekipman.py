"""Sert ekipmanı üretir ve kaydeder.

python3 -m motor.varlik.ekipman [id ...] [--zorla]

- ekipman.yaml'daki her parça Blender betiğiyle bir kez üretilir: ONBELLEK/ekipman/<id>.glb
- Kayıt: motor/varlik/ekipman_kaydi.json — kaynak (kendi üretimimiz), betik ve parametre özeti, çıktı sha256,
  ölçümler, dönem etiketleri, tarih notu ve güven düzeyi.
- Girdi anahtarı değişmediyse yeniden üretilmez; aynı anahtar aynı baytları verir (testte doğrulanır).
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
BETIK = BURASI / "blender"
CIKTI = ayar.ONBELLEK / "ekipman"
KAYIT = BURASI / "ekipman_kaydi.json"
KATALOG = BURASI / "ekipman.yaml"
LISANS = {"lisans": "kendi-uretim", "yazar": "Mini Dünya motoru (Blender betikleri, bu repo)",
          "not": "Dış varlık içermez; kaynak kod ve parametrelerden yeniden üretilebilir."}
URETIM_BETIKLERI = ("ekipman_uret.py", "ortak.py", "doku.py")


def katalog() -> dict:
    return yaml.safe_load(KATALOG.read_text(encoding="utf-8"))


def betik_ozeti(adlar=URETIM_BETIKLERI) -> str:
    h = hashlib.sha256()
    for b in adlar:
        h.update((BETIK / b).read_bytes())
    return h.hexdigest()[:16]


def _malzemeler_of(p: dict, malz: dict) -> dict:
    return {v: malz[v] for v in p.values() if isinstance(v, str) and v in malz}


def anahtar(pid: str, tanim: dict, malz: dict) -> str:
    h = hashlib.sha256(json.dumps({"u": tanim["uretici"], "p": tanim.get("p", {}), "m": _malzemeler_of(tanim.get("p", {}), malz)},
                                  sort_keys=True).encode())
    h.update(betik_ozeti().encode())
    return h.hexdigest()[:16]


def uret(idler: list[str] | None = None, zorla: bool = False) -> dict:
    CIKTI.mkdir(parents=True, exist_ok=True)
    k = katalog()
    malz = k["malzemeler"]
    kayit = json.loads(KAYIT.read_text()) if KAYIT.exists() else {}
    isler = []
    for pid, t in k["parcalar"].items():
        if idler and pid not in idler:
            continue
        a = anahtar(pid, t, malz)
        glb = CIKTI / f"{pid}.glb"
        if not zorla and kayit.get(pid, {}).get("anahtar") == a and glb.exists():
            continue
        isler.append((pid, t, a, glb))
    if isler:
        is_json = CIKTI / "_is.json"
        is_json.write_text(json.dumps({"parcalar": [{"id": pid, "uretici": t["uretici"], "p": t.get("p", {}), "cikti": str(glb)} for pid, t, a, glb in isler],
                                       "malzemeler": malz}))
        p = subprocess.run([sys.executable, str(BETIK / "ekipman_uret.py"), str(is_json)], capture_output=True, text=True, timeout=1800)
        if p.returncode != 0:
            print(p.stdout[-3000:], p.stderr[-4000:])
            raise SystemExit("EKİPMAN ÜRETİMİ BAŞARISIZ")
    for pid, t, a, glb in isler:
        olc = json.loads(glb.with_suffix(".olc.json").read_text())
        kayit[pid] = {
            "id": pid, "anahtar": a, "kategori": t["kategori"], "yuva": t["yuva"], "donem": t["donem"],
            "tarih": t["tarih"], "uretici": t["uretici"], "parametreler": t.get("p", {}),
            "betik_ozeti": betik_ozeti(), "sha256": hashlib.sha256(glb.read_bytes()).hexdigest(),
            "olcum": olc, **LISANS,
        }
        print("URETILDI", pid, olc["ucgen"], "üçgen", round(olc["bayt"] / 1024), "KB")
    # katalogdan çıkarılmış parçalar kayıttan da düşer
    kayit = {pid: v for pid, v in kayit.items() if pid in k["parcalar"]}
    KAYIT.write_text(json.dumps(kayit, ensure_ascii=False, indent=1))
    return kayit


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    uret(a or None, "--zorla" in sys.argv)
