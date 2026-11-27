#!/usr/bin/env python3
"""Faz-62a — CI'da 3D varlık derleme + Godot render hattı (Gemini YOK, YouTube YOK).

Bu betik yalnızca mevcut motor modüllerini ÇAĞIRIR; hiçbirini değiştirmez. Üç alt komut:

  kaynaklar   motor/varlik/kaynaklar.yaml'daki CC0 depolarını SABİT commit'lerinden sığ (depth=1) klonlar
              (MOTOR_KAYNAK, vars. /tmp/varlik). Doğru commit'te olan klon yeniden indirilmez.
  varlik      3D varlıkları derler (MOTOR_ONBELLEK, vars. /tmp/motor_onbellek):
                motor.karakter.takim.derle()   → ekipman/, karakter3/, insan/ (gerçekçi kişiler), takim/
                motor.karakter.insan.montaj_testi(hizli) → montajı geçemeyen kişileri eler
                motor.varlik.mekan_varlik.uret() → mekan/
              (binek/ render sırasında motor.uretim.binek.hazir ile istek üzerine üretilir.)
  render      Otlukbeli pilot girdileriyle (motor/uretim/pilotlar/otlukbeli-1473) uçtan uca doğrulama:
                motor.uretim.uretim_hatti.planla → motor.uretim.kurgu.uret (Godot render + Piper TTS + FFmpeg kurgu
                + Whisper/teknik kalite kontrol) → .mp4; ffprobe ile süre/çözünürlük/boyut ölçülür.

Her alt komut ölçüm özetini <cikti>/faz62a_<komut>.json'a yazar ve başarısızlıkta sıfırdan farklı kodla çıkar
(sessiz geri dönüş yok). Varlık anahtarı (`anahtar` alt komutu) CI önbelleği için derleme girdilerinin karmasıdır.

Kullanım:
  python3 araclar/faz62a_hat.py anahtar
  python3 araclar/faz62a_hat.py kaynaklar [--cikti DIR]
  python3 araclar/faz62a_hat.py varlik    [--cikti DIR] [--hizli-montaj]
  python3 araclar/faz62a_hat.py render    [--cikti DIR] [--pilot otlukbeli-1473]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

KOK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KOK))

# Varlık önbelleği anahtarına giren derleme girdileri (betikler, tarifler, kitler, kataloglar, kaynak kayıtları)
ANAHTAR_GIRDILERI = ("motor/varlik/kaynaklar.yaml", "motor/varlik/kayit.json", "motor/varlik/ekipman.yaml",
                     "motor/varlik/ekipman_ek.yaml", "motor/varlik/mekan_varliklari.yaml", "motor/varlik/blender",
                     "motor/varlik/cc0/lisans.json", "motor/varlik/makehuman", "motor/varlik/oga3/lisans.json",
                     "motor/karakter", "motor/kit", "motor/uretim/kurallar/insan.yaml")
ONBELLEK_KLASORLERI = ("ekipman", "karakter3", "insan", "takim", "mekan", "binek")


def _yaz(cikti: Path, ad: str, veri: dict) -> Path:
    cikti.mkdir(parents=True, exist_ok=True)
    p = cikti / f"faz62a_{ad}.json"
    p.write_text(json.dumps(veri, ensure_ascii=False, indent=1))
    return p


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


# ------------------------------------------------------------------ anahtar

def varlik_anahtari(kok: Path = KOK) -> str:
    """Derleme girdilerinin (dosya yolu + içerik) karması; girdiler değişmedikçe CI önbelleği yeniden kullanılır."""
    h = hashlib.sha256()
    for g in ANAHTAR_GIRDILERI:
        p = kok / g
        dosyalar = sorted(x for x in p.rglob("*") if x.is_file() and "__pycache__" not in x.parts) if p.is_dir() else (
            [p] if p.is_file() else [])
        for f in dosyalar:
            h.update(str(f.relative_to(kok)).encode())
            h.update(hashlib.sha256(f.read_bytes()).digest())
    h.update(f"python{sys.version_info.major}.{sys.version_info.minor}".encode())
    h.update(os.environ.get("MPFB_COMMIT", "").encode())   # insan derlemesindeki MPFB2 sürümü
    return h.hexdigest()[:20]


# ------------------------------------------------------------------ kaynaklar

def kaynaklari_getir(hedef: Path | None = None) -> dict:
    import yaml
    from motor import ayar
    hedef = Path(hedef or ayar.KAYNAK_KOK)
    hedef.mkdir(parents=True, exist_ok=True)
    k = yaml.safe_load((KOK / "motor/varlik/kaynaklar.yaml").read_text(encoding="utf-8"))
    sonuc = {}
    for ad, v in k.items():
        v = dict(v, commit=str(v["commit"]))   # YAML yalnız rakamlı SHA'yı tamsayı okuyabilir
        d = hedef / v["klasor"]
        t0 = time.time()
        try:
            if (d / ".git").exists() and _git(["rev-parse", "HEAD"], d) == v["commit"]:
                sonuc[ad] = {"durum": "hazir", "commit": v["commit"]}
                continue
        except subprocess.CalledProcessError:
            pass
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        _git(["init", "-q"], d)
        _git(["remote", "add", "origin", v["url"]], d)
        _git(["fetch", "-q", "--depth", "1", "origin", v["commit"]], d)
        _git(["checkout", "-q", "FETCH_HEAD"], d)
        bas = _git(["rev-parse", "HEAD"], d)
        if bas != v["commit"]:
            raise SystemExit(f"{ad}: commit uyuşmuyor ({bas} ≠ {v['commit']})")
        if not (d / v["lisans_dosyasi"]).exists():
            raise SystemExit(f"{ad}: lisans dosyası yok: {v['lisans_dosyasi']}")
        sonuc[ad] = {"durum": "indirildi", "commit": bas, "sure_sn": round(time.time() - t0, 1)}
    return sonuc


# ------------------------------------------------------------------ varlık derleme

def _boyut(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0


def varliklari_derle(hizli_montaj: bool = True) -> dict:
    from motor import ayar
    from motor.karakter import insan, takim
    from motor.varlik import mekan_varlik
    r: dict = {"onbellek": str(ayar.ONBELLEK), "adimlar": {}}
    t = time.time()
    o = takim.derle(False)
    r["adimlar"]["takim"] = {"sure_sn": round(time.time() - t, 1),
                             "ozet": {k: (len(v) if isinstance(v, (list, dict)) else v) for k, v in (o or {}).items()}}
    if insan.acik():
        t = time.time()
        c = insan.montaj_testi(hizli_montaj)
        r["adimlar"]["insan_montaj"] = {"sure_sn": round(time.time() - t, 1), "kisi": len(c),
                                         "gecen": sum(1 for x in c.values() if x["gecti"])}
    t = time.time()
    m = mekan_varlik.uret(None, False)
    r["adimlar"]["mekan"] = {"sure_sn": round(time.time() - t, 1), "varlik": len(m or {})}
    r["klasorler"] = {k: {"dosya": sum(1 for _ in (ayar.ONBELLEK / k).rglob("*.glb")),
                          "mb": round(_boyut(ayar.ONBELLEK / k) / 1e6, 1)} for k in ONBELLEK_KLASORLERI}
    eksik = [k for k in ("ekipman", "karakter3", "insan", "takim", "mekan") if r["klasorler"][k]["dosya"] == 0 and k != "takim"]
    if not any((ayar.ONBELLEK / "takim").glob("*.json")):
        eksik.append("takim")
    r["eksik"] = eksik
    r["gecti"] = not eksik
    return r


# ------------------------------------------------------------------ render doğrulaması

def ffprobe(yol: Path) -> dict:
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration,size:stream=codec_type,width,height,r_frame_rate",
                        "-of", "json", str(yol)], capture_output=True, text=True, check=True)
    d = json.loads(p.stdout)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), {})
    return {"sure_sn": round(float(d["format"]["duration"]), 2), "boyut_mb": round(int(d["format"]["size"]) / 1e6, 2),
            "cozunurluk": [v.get("width"), v.get("height")], "fps": v.get("r_frame_rate"),
            "ses": any(s["codec_type"] == "audio" for s in d["streams"])}


def pilot_render(pilot: str, cikti: Path) -> dict:
    from motor.uretim import kurgu, uretim_hatti
    kaynak = KOK / "motor/uretim/pilotlar" / pilot
    is_ = cikti / "is" / pilot
    if is_.exists():
        shutil.rmtree(is_)
    is_.mkdir(parents=True)
    for ad in ("konu.json", "arastirma.json", "senaryo.json"):   # pilot klasörü DEĞİŞMEZ; çalışma kopyası
        shutil.copy2(kaynak / ad, is_ / ad)
    r: dict = {"pilot": pilot}
    t = time.time()
    plan = uretim_hatti.planla(is_)
    r["plan"] = {"gecti": plan["gecti"], "toplam_sure_sn": plan.get("toplam_sure_sn"), "sure_sn": round(time.time() - t, 1),
                 "hatalar": {k: v for k, v in plan["hatalar"].items() if v}}
    if not plan["gecti"]:
        r["gecti"] = False
        return r
    t = time.time()
    k = kurgu.uret(is_)
    r["kurgu"] = {"durum": k.get("durum"), "sure_sn": round(time.time() - t, 1),
                  **{x: k[x] for x in ("hatalar", "cekim", "render", "olculen", "kalite_kontrol", "seslendirme_motoru")
                     if x in k}}
    if k.get("dinleme"):
        b = [v["benzerlik"] for v in k["dinleme"].values()]
        r["kurgu"]["dinleme"] = {"cumle": len(b), "en_dusuk_benzerlik": min(b), "ortalama": round(sum(b) / len(b), 3)}
    konu = json.loads((is_ / "konu.json").read_text())["kimlik"]
    from motor import ayar
    mp4 = ayar.ONBELLEK / "kurgu" / konu / f"{konu}.mp4"
    if mp4.exists():
        hedef = cikti / "video" / f"{konu}.mp4"
        hedef.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(mp4, hedef)
        r["mp4"] = {"yol": str(hedef), **ffprobe(hedef)}
    r["gecti"] = bool(r.get("mp4")) and k.get("durum") == "TAMAM"   # kalite kontrolden kalan video da başarısız
    return r


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Faz-62a CI varlık + render hattı")
    ap.add_argument("komut", choices=("anahtar", "kaynaklar", "varlik", "render"))
    ap.add_argument("--cikti", default="/tmp/faz62a_cikti")
    ap.add_argument("--pilot", default="otlukbeli-1473")
    ap.add_argument("--hizli-montaj", action="store_true", default=True)
    a = ap.parse_args(argv)
    cikti = Path(a.cikti)
    if a.komut == "anahtar":
        print(varlik_anahtari())
        return 0
    t0 = time.time()
    if a.komut == "kaynaklar":
        r = {"kaynaklar": kaynaklari_getir(), "gecti": True}
    elif a.komut == "varlik":
        r = varliklari_derle(a.hizli_montaj)
    else:
        r = pilot_render(a.pilot, cikti)
    r["toplam_sn"] = round(time.time() - t0, 1)
    p = _yaz(cikti, a.komut, r)
    print(json.dumps(r, ensure_ascii=False, indent=1)[:6000])
    print(f"özet: {p}")
    return 0 if r.get("gecti") else 1


if __name__ == "__main__":
    sys.exit(main())
