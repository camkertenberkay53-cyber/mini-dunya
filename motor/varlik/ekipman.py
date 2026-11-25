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
KAYIT = BURASI / "ekipman_kaydi.json"            # yalnız kendi üretimimiz (lisans: kendi-uretim)
KAYIT_DIS = BURASI / "dis_cevre_kaydi.json"      # dış CC0 modeller (uretici: dis_usd); lisans kaynak kaydından
KATALOG = BURASI / "ekipman.yaml"
KATALOG_EK = BURASI / "ekipman_ek.yaml"   # dondurulmuş katalogdan sonra eklenen parçalar
LISANS = {"lisans": "kendi-uretim", "yazar": "Mini Dünya motoru (Blender betikleri, bu repo)",
          "not": "Dış varlık içermez; kaynak kod ve parametrelerden yeniden üretilebilir."}
URETIM_BETIKLERI = ("ekipman_uret.py", "ortak.py", "doku.py")


def katalog() -> dict:
    k = yaml.safe_load(KATALOG.read_text(encoding="utf-8"))
    if KATALOG_EK.exists():
        ek = yaml.safe_load(KATALOG_EK.read_text(encoding="utf-8")) or {}
        cakisan = set(ek.get("parcalar", {})) & set(k["parcalar"])
        if cakisan:
            raise ValueError(f"ekipman_ek.yaml ana katalogla çakışıyor: {sorted(cakisan)}")
        k["parcalar"] = {**k["parcalar"], **ek.get("parcalar", {})}
    return k


def betik_ozeti(adlar=URETIM_BETIKLERI) -> str:
    h = hashlib.sha256()
    for b in adlar:
        h.update((BETIK / b).read_bytes())
    return h.hexdigest()[:16]


def _malzemeler_of(p: dict, malz: dict) -> dict:
    return {v: malz[v] for v in p.values() if isinstance(v, str) and v in malz}


def dis_kaynak(tanim: dict) -> tuple[Path, dict] | None:
    """'dis_usd' üreticisi: kaynak dosya (KAYNAK_KOK altında) ve kaynaklar.yaml lisans kaydı."""
    if tanim["uretici"] != "dis_usd":
        return None
    kaynak = tanim["p"]["kaynak"]
    kayitlar = yaml.safe_load((BURASI / "kaynaklar.yaml").read_text(encoding="utf-8"))
    kid = kaynak.split("/", 1)[0]
    k = next((v | {"id": a} for a, v in kayitlar.items() if v["klasor"] == kid), None)
    if k is None:
        raise ValueError(f"{kaynak}: kaynaklar.yaml'da lisansı doğrulanmış kaynak yok")
    return ayar.KAYNAK_KOK / kid / k["kok"] / kaynak.split("/", 1)[1], k


def anahtar(pid: str, tanim: dict, malz: dict) -> str:
    h = hashlib.sha256(json.dumps({"u": tanim["uretici"], "p": tanim.get("p", {}), "m": _malzemeler_of(tanim.get("p", {}), malz)},
                                  sort_keys=True).encode())
    dk = dis_kaynak(tanim)
    if dk:   # dış model: kaynak dosya + dönüştürme betiği (kendi üretim betikleri anahtara girmez)
        h.update(dk[0].read_bytes())
        h.update(betik_ozeti(("dis_uret.py", "ortak.py")).encode())
        return h.hexdigest()[:16]
    h.update(betik_ozeti().encode())
    return h.hexdigest()[:16]


def kayit_oku() -> dict:
    """Kendi üretim + dış model kayıtları birlikte (kalite sınıflandırması ve katalog için)."""
    k = json.loads(KAYIT.read_text()) if KAYIT.exists() else {}
    if KAYIT_DIS.exists():
        k |= json.loads(KAYIT_DIS.read_text())
    return k


def uret(idler: list[str] | None = None, zorla: bool = False) -> dict:
    CIKTI.mkdir(parents=True, exist_ok=True)
    k = katalog()
    malz = k["malzemeler"]
    kayit = kayit_oku()
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
        for betik, grup in (("ekipman_uret.py", [x for x in isler if not dis_kaynak(x[1])]),
                            ("dis_uret.py", [x for x in isler if dis_kaynak(x[1])])):
            if not grup:
                continue
            is_json = CIKTI / "_is.json"
            is_json.write_text(json.dumps({"parcalar": [{"id": pid, "uretici": t["uretici"],
                                                         "p": (dict(t["p"], kaynak=str(dis_kaynak(t)[0])) if dis_kaynak(t) else t.get("p", {})),
                                                         "cikti": str(glb)} for pid, t, a, glb in grup],
                                           "malzemeler": malz}))
            p = subprocess.run([sys.executable, str(BETIK / betik), str(is_json)], capture_output=True, text=True, timeout=1800)
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
        dk = dis_kaynak(t)
        if dk:   # dış CC0 model: lisans kaynak kaydından (kaynaklar.yaml; depo ve commit sabit)
            kk = dk[1]
            kayit[pid].update({"betik_ozeti": betik_ozeti(("dis_uret.py", "ortak.py")), "lisans": kk["lisans"], "yazar": kk["yazar"], "kaynak": {"id": kk["id"], "url": kk["url"], "commit": kk["commit"],
                               "dosya": t["p"]["kaynak"], "sha256": hashlib.sha256(dk[0].read_bytes()).hexdigest()},
                               "not": "Dış model; yalnız ölçek/yön ve tabana oturtma uygulandı."})
        print("URETILDI", pid, olc["ucgen"], "üçgen", round(olc["bayt"] / 1024), "KB")
    # katalogdan çıkarılmış parçalar kayıttan da düşer
    kayit = {pid: v for pid, v in kayit.items() if pid in k["parcalar"]}
    dis = {pid: v for pid, v in kayit.items() if v.get("uretici") == "dis_usd"}
    KAYIT.write_text(json.dumps({pid: v for pid, v in kayit.items() if pid not in dis}, ensure_ascii=False, indent=1))
    KAYIT_DIS.write_text(json.dumps(dis, ensure_ascii=False, indent=1))
    return kayit


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    uret(a or None, "--zorla" in sys.argv)
