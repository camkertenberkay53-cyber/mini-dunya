"""M11 — Çekim render'ı: denetimden geçmiş çekim planındaki bir çekimi Godot'ta render eder ve ÖLÇER.

python3 -m motor.uretim.render <cekim_plani.json> <cekim_id> [cikti_klasoru]

Akış: plan denetimi (hata varsa render YOK) -> is.json (hazır ayarlar çözülmüş) -> Godot (Movie Maker, sabit fps)
-> H.264 -> kare sayısı ve çözünürlük doğrulaması -> ölçüm kaydı.
Önbellek: is.json + sahne betikleri + kullanılan GLB'lerin karması aynıysa çekim yeniden render edilmez.
"""
from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path

from motor import ayar
from motor.olcum.render_olc import _calistir
from motor.uretim import kadraj, plan_denetim, veri

BETIKLER = [ayar.GODOT_PROJE / "sahneler" / x for x in ("cekim.gd", "ortam.gd", "donatici.gd")]
KOK = ayar.ONBELLEK / "uretim"


def is_hazirla(plan: dict, c: dict) -> dict:
    ar = dict(veri.kural("arazi")["araziler"][c["ortam"]["arazi"]])
    isik = veri.kural("arazi")["isiklar"][c["ortam"]["isik"]]
    kurallar = veri.kural("animasyon")["animasyonlar"]
    takimlar = {k["takim"]: veri.takimlar()[k["takim"]] for k in c.get("karakterler", [])}
    # sahne merkezi ve ot alanı: karakterlerin (başta ve sonda) ve kamera hedeflerinin kapsadığı bölge
    noktalar = []
    for k in c.get("karakterler", []):
        for z in (0.0, c["sure_sn"]):
            p = kadraj.karakter_konumu(k, z)
            noktalar.append((p[0], p[2]))
    kam = c["kamera"]
    for an in (kam["bas"], kam["son"]):
        noktalar.append((an["hedef"][0], an["hedef"][2]))
        noktalar.append((an["konum"][0], an["konum"][2]))
    xs, zs = [p[0] for p in noktalar], [p[1] for p in noktalar]
    pay = 10.0
    # oyuncuların ve çevre varlıklarının durduğu şerit düz kalır (ayak ve taban zemine otursun); tepeler bunun dışında
    yatay = [abs(x) for x in xs] + [abs(cv["konum"][0]) + 4 for cv in c["ortam"].get("cevre", [])]
    ar["duz_yari"] = max(6.0, max(yatay) + 2.0)
    ileri = [kam["bas"]["hedef"][0] - kam["bas"]["konum"][0], kam["bas"]["hedef"][2] - kam["bas"]["konum"][2]]
    return {
        "surum": 1,
        "plan_konu": plan["konu"],
        "tohum": plan.get("tohum", 1),
        "fps": plan["fps"],
        "cozunurluk": plan["cozunurluk"],
        "cekim": c,
        "arazi": ar,
        "isik": isik,
        "takimlar": takimlar,
        "dongu": {a: k["tur"] != "tek_sefer" for a, k in kurallar.items()},
        "cevre": [dict(cv, glb=str(veri.ekipman_glb(cv["id"]))) for cv in c["ortam"].get("cevre", [])],
        "sahne_merkezi": [sum(xs) / len(xs), sum(zs) / len(zs)],
        "bakis_yonu_derece": math.degrees(math.atan2(ileri[0], ileri[1])),
        "ot_alani": [min(xs) - pay, max(xs) + pay, min(zs) - pay, max(zs) + pay],
    }


def _karma(is_: dict) -> str:
    h = hashlib.sha256(json.dumps(is_, sort_keys=True, ensure_ascii=False).encode())
    for b in BETIKLER:
        h.update(b.read_bytes())
    dosyalar = {t["glb"] for t in is_["takimlar"].values()} | {e["glb"] for t in is_["takimlar"].values() for e in t["takilanlar"]}
    dosyalar |= {cv["glb"] for cv in is_["cevre"]}
    for d in sorted(dosyalar):
        h.update(Path(d).read_bytes())
    return h.hexdigest()[:16]


def render(plan_yolu: str, cekim_id: str, cikti: Path | None = None, onbellek: bool = True) -> dict:
    plan = json.loads(Path(plan_yolu).read_text())
    t0 = time.time()
    denetim = plan_denetim.denetle(plan)
    denetim_sn = time.time() - t0
    if not denetim["gecti"]:
        return {"durum": "REDDEDİLDİ", "neden": "plan denetimi", "hatalar": denetim["hatalar"]}
    c = next(x for x in plan["cekimler"] if x["id"] == cekim_id)
    if c["tur"] != "3d":
        return {"durum": "ATLANDI", "neden": f"{c['tur']} çekimi 3D render'a girmez"}
    is_ = is_hazirla(plan, c)
    karma = _karma(is_)
    klasor = KOK / plan["konu"] / f"{cekim_id}_{karma}"
    mp4 = klasor / "cekim.mp4"
    olcum_yolu = klasor / "olcum.json"
    if onbellek and mp4.exists() and olcum_yolu.exists():
        o = json.loads(olcum_yolu.read_text())
        o["onbellekten"] = True
        return o
    shutil.rmtree(klasor, ignore_errors=True)
    klasor.mkdir(parents=True)
    is_yolu = klasor / "is.json"
    is_yolu.write_text(json.dumps(is_, ensure_ascii=False, indent=1))
    fps = plan["fps"]
    kare = round(c["sure_sn"] * fps)
    avi = klasor / "cekim.avi"
    komut = ["xvfb-run", "-a", "-s", "-screen 0 1280x1024x24", ayar.GODOT, "--path", str(ayar.GODOT_PROJE),
             "--rendering-driver", "opengl3", "res://sahneler/cekim.tscn", "--write-movie", str(avi),
             "--fixed-fps", str(fps), "--quit-after", str(kare), "--", str(is_yolu)]
    w, hgt = plan["cozunurluk"]
    proje = ayar.GODOT_PROJE / "project.godot"
    if f"viewport_width={w}" not in proje.read_text() or f"viewport_height={hgt}" not in proje.read_text():
        return {"durum": "HATA", "neden": f"Godot projesi {w}x{hgt} değil"}
    rnd_sn, rnd_kb, gunluk = _calistir(komut, 7200)
    hatalar = [s for s in gunluk.splitlines() if "ERROR" in s or "SCRIPT ERROR" in s]
    kod_sn, _, _ = _calistir(["ffmpeg", "-y", "-loglevel", "error", "-i", str(avi), "-c:v", "libx264", "-preset", "veryfast",
                              "-crf", "18", "-pix_fmt", "yuv420p", str(mp4)], 3600)
    pr = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries",
                         "stream=width,height,nb_read_frames", "-of", "json", str(mp4)], capture_output=True, text=True)
    akis = json.loads(pr.stdout)["streams"][0]
    avi_mb = avi.stat().st_size / 1e6
    avi.unlink()
    sonuc = {
        "durum": "TAMAM",
        "konu": plan["konu"],
        "cekim": cekim_id,
        "karma": karma,
        "video": str(mp4),
        "tarih": time.strftime("%Y-%m-%d %H:%M"),
        "makine": {"cpu": open("/proc/cpuinfo").read().split("model name")[1].split("\n")[0].strip(": \t"),
                   "cekirdek": __import__("os").cpu_count()},
        "olculen": {
            "plan_denetim_sn": round(denetim_sn, 2),
            "render_sn": round(rnd_sn, 1),
            "kare": kare,
            "uretilen_kare": int(akis.get("nb_read_frames", 0)),
            "cozunurluk": f"{akis['width']}x{akis['height']}",
            "kare_basina_sn_acilis_dahil": round(rnd_sn / max(1, kare), 2),
            "render_tepe_bellek_gb": round(rnd_kb / 1e6, 2),
            "kodlama_sn": round(kod_sn, 1),
            "ara_avi_mb": round(avi_mb, 1),
            "mp4_mb": round(mp4.stat().st_size / 1e6, 2),
            "karakter": len(c.get("karakterler", [])),
            "cevre_varligi": len(c["ortam"].get("cevre", [])),
        },
        "godot_hatalari": hatalar[:20],
        "denetim_uyarilari": denetim["uyarilar"],
    }
    if sonuc["olculen"]["uretilen_kare"] != kare or (akis["width"], akis["height"]) != (w, hgt) or hatalar:
        sonuc["durum"] = "HATA"
        sonuc["neden"] = "kare sayısı, çözünürlük ya da Godot hatası tutmadı"
    olcum_yolu.write_text(json.dumps(sonuc, ensure_ascii=False, indent=1))
    if cikti:
        Path(cikti).mkdir(parents=True, exist_ok=True)
        shutil.copy(mp4, Path(cikti) / f"{cekim_id}.mp4")
    return sonuc


def onizleme(plan_yolu: str, cekim_id: str, anlar: list[float], cikti: Path) -> list[Path]:
    """Denetimden geçen çekimin belirli anlarından tek kare (PNG). Kamera ve karakterler o anda; render ölçümü değildir."""
    plan = json.loads(Path(plan_yolu).read_text())
    d = plan_denetim.denetle(plan)
    if not d["gecti"]:
        raise SystemExit("PLAN DENETİMDEN GEÇMEDİ:\n" + "\n".join(d["hatalar"]))
    c = next(x for x in plan["cekimler"] if x["id"] == cekim_id)
    cikti.mkdir(parents=True, exist_ok=True)
    is_yolu = cikti / f"{cekim_id}.is.json"
    is_yolu.write_text(json.dumps(is_hazirla(plan, c), ensure_ascii=False))
    yollar = []
    for an in anlar:
        png = cikti / f"{cekim_id}_{an:05.2f}.png"
        komut = ["xvfb-run", "-a", "-s", "-screen 0 1280x1024x24", ayar.GODOT, "--path", str(ayar.GODOT_PROJE),
                 "--rendering-driver", "opengl3", "res://sahneler/cekim.tscn", "--write-movie", str(cikti / "k.png"),
                 "--fixed-fps", str(plan["fps"]), "--quit-after", "3", "--", str(is_yolu), str(an)]
        _calistir(komut, 600)
        son = sorted(cikti.glob("k*.png"))
        shutil.move(str(son[0]), png)   # ilk kare = istenen an
        for s in son[1:]:
            s.unlink()
        yollar.append(png)
    return yollar


if __name__ == "__main__":
    if "--onizleme" in sys.argv:
        i = sys.argv.index("--onizleme")
        print(onizleme(sys.argv[1], sys.argv[2], [float(x) for x in sys.argv[i + 1].split(",")], Path(sys.argv[i + 2])))
        sys.exit(0)
    arg = [a for a in sys.argv[1:] if not a.startswith("--")]
    r = render(arg[0], arg[1], Path(arg[2]) if len(arg) > 2 else None, onbellek="--yeniden" not in sys.argv)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    sys.exit(0 if r["durum"] in ("TAMAM", "ATLANDI") else 1)
