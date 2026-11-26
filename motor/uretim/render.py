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

BETIKLER = [ayar.GODOT_PROJE / "sahneler" / x for x in ("cekim.gd", "ortam.gd", "donatici.gd", "vfx.gd", "binici_bacak.gd", "sinema.gd", "serpme.gd", "yerlesim.gd", "kalabalik.gd")]
KOK = ayar.ONBELLEK / "uretim"


def gorsel_profili(g: dict, arazi: str, ad: str | None = None) -> dict:
    """Aktif görsel profil: 'taban' zinciri birleştirilir, arazi_ozel uygulanır, 'varlik/...' yolları motor/ köküne
    göre mutlak yapılır (Godot dosyayı is.json'daki yoldan okur)."""
    sr = g.get("sinematik_render", {})
    p = g["profiller"][ad or (sr["profil"] if sr.get("acik") and sr.get("profil") else g["aktif"])]
    sonuc = {"isik": {}, "arazi": {}}
    if p.get("taban"):
        t = gorsel_profili(g, arazi, p["taban"])
        sonuc = {"isik": dict(t["isik"]), "arazi": dict(t["arazi"])}
    sonuc["isik"].update(p.get("isik", {}))
    sonuc["arazi"].update(p.get("arazi", {}))
    sonuc["arazi"].update(p.get("arazi_ozel", {}).get(arazi, {}))
    for alan in sonuc.values():
        for k, v in alan.items():
            if isinstance(v, str) and v.startswith("varlik/"):
                alan[k] = str(ayar.REPO / "motor" / v)
    return sonuc


def is_hazirla(plan: dict, c: dict) -> dict:
    ar = dict(veri.kural("arazi")["araziler"][c["ortam"]["arazi"]])
    isik = veri.kural("arazi")["isiklar"][c["ortam"]["isik"]]
    kurallar = veri.kural("animasyon")["animasyonlar"]
    # Faz 5.2 görsel profili (kurallar/gorsel.yaml); hazır ayarların kendisi değişmez, kopyalarına eklenir
    gp = gorsel_profili(veri.kural("gorsel"), c["ortam"]["arazi"])
    isik = dict(isik, gorsel=dict(gp.get("isik", {})))
    ar["gorsel"] = dict(gp.get("arazi", {}))
    mk = veri.kural("gorsel").get("mekan_kalite", {})
    if mk.get("acik"):   # mekân kalite paketi: arazi doku eklemeleri (yamaç kayası vb.); kapalıyken eski görünüm
        ek = {**mk.get("arazi", {}), **mk.get("arazi_ozel", {}).get(c["ortam"]["arazi"], {})}
        ar["gorsel"].update({k: (str(ayar.REPO / "motor" / v) if isinstance(v, str) and v.startswith("varlik/") else v) for k, v in ek.items()})
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
    if ar.get("su"):   # mekân paketi: su kameranın baktığı yönde, sahnenin arkasında kalır
        su = dict(ar["su"])
        n = math.hypot(*ileri) or 1.0
        su["yon"] = [ileri[0] / n, ileri[1] / n]
        su["merkez"] = [sum(xs) / len(xs), sum(zs) / len(zs)]
        ar["su"] = su
    return {
        "surum": 1,
        "plan_konu": plan["konu"],
        "tohum": plan.get("tohum", 1),
        "fps": plan["fps"],
        "cozunurluk": plan["cozunurluk"],
        "cekim": _insan_olcekli(_binekli(c)),
        "arazi": ar,
        "isik": isik,
        "takimlar": takimlar,
        "dongu": {a: k["tur"] != "tek_sefer" for a, k in kurallar.items()},
        "cevre": [dict(cv, glb=str(veri.ekipman_glb(cv["id"]))) for cv in c["ortam"].get("cevre", [])],
        "karakter_cesit": veri.kural("gorsel").get("karakter_cesit", {"acik": False}),
        "yuzey": _yuzey(),
        "beden": _beden(),
        "insan": {"acik": _insan_acik()},
        "vfx": _vfx(c, ar),
        "serpme": _serpme(plan, c),
        "yerlesim": (yer := _yerlesim(plan, c)),
        "malzeme": _malzeme(yer, {}),
        "kalabalik": _kalabalik(c, c.get("donem") or plan.get("donem")),
        "sinema": _sinema(),
        "film": _film(c),
        "ek_animasyon_kutuphaneleri": {ad: str(ayar.REPO / "motor" / yol) for ad, yol in veri.kural("animasyon").get("kutuphaneler", {}).items()
                                       if any(k["animasyon"].startswith(ad + "/") for k in c.get("karakterler", []))},
        "sahne_merkezi": [sum(xs) / len(xs), sum(zs) / len(zs)],
        "bakis_yonu_derece": math.degrees(math.atan2(ileri[0], ileri[1])),
        "ot_alani": [min(xs) - pay, max(xs) + pay, min(zs) - pay, max(zs) + pay],
    }


def _kalabalik(c: dict, donem: str | None = None) -> dict:
    """Arka plan ordusu: çekimdeki oyuncuların takımlarından (sancaksız, nesnesiz) en çok N tanesi."""
    ad = c["ortam"].get("kalabalik")
    if not ad:
        return {"acik": False}
    k = dict(veri.kural("kalabalik")["kalabaliklar"][ad])
    from motor.uretim import planlayici
    adaylar = []
    for x in c.get("karakterler", []):
        if x["takim"] not in adaylar and not planlayici._sancakli(x["takim"]) and not x.get("binek"):
            adaylar.append(x["takim"])
    k["takimlar"] = adaylar[: k.pop("en_cok_takim", 3)]
    cev = c["ortam"].get("cevre", [])
    if cev:   # çevre varlığı (sur, çadır) varsa ordu onun ÖNÜNDE kalır (arkasında görünmez)
        xs = [x["konum"][0] for x in c["karakterler"]]
        zs = [x["konum"][1] for x in c["karakterler"]]
        mx, mz = sum(xs) / len(xs), sum(zs) / len(zs)
        yakin = min(math.dist((mx, mz), cv["konum"]) for cv in cev) - 4.0
        if yakin > 14.0:
            k["mesafe_m"] = [max(8.0, yakin - 16.0), yakin]
    k["cesit"] = veri.kural("gorsel").get("karakter_cesit", {"acik": False})
    k["boy_orani"] = float(c.get("insan_boy_orani", 1.0))   # arka plan ordusu da oyuncularla aynı dönem boyunda
    k["acik"] = bool(k["takimlar"])
    return k


def _yerlesim(plan: dict, c: dict) -> dict:
    """Prosedürel yerleşim: dönemin çadırları/ekleri (katalogda dönemde kayıtlı, RED değil) ve doku yolları."""
    ad = c["ortam"].get("yerlesim")
    if not ad:
        return {"acik": False}
    k = dict(veri.kural("yerlesim")["yerlesimler"][ad])
    donem = c.get("donem") or plan.get("donem")

    hd = _mekan_kalite_acik()
    if hd and "hd" in k:   # mekân kalite paketi: gerçekçi varlıklara özgü yerleşim ayarları (kapalıyken eski davranış)
        k = {**{a: b for a, b in k.items() if a != "hd"}, **k["hd"]}
    k.pop("hd", None)

    def uygun(ids):
        return [str(g) for g in _cevre_glb(ids, donem, hd)]
    if "cadir_adaylari" in k:
        k["cadirlar"], k["ekler"] = uygun(k.pop("cadir_adaylari")), uygun(k.pop("ek_adaylari"))
    else:   # mekân paketi yerleşimleri: rol → glb listesi
        k["roller"] = {rol: uygun(ids) for rol, ids in k["roller"].items()}
        k["cadirlar"] = [g for v in k["roller"].values() for g in v]
    k.setdefault("alev_doku", "varlik/kenney_parcacik/flame_02.png")
    k.setdefault("duman_doku", "varlik/kenney_parcacik/smoke_04.png")
    for d in ("alev_doku", "duman_doku"):
        k[d] = str(ayar.MOTOR / k[d])
    k["tur"] = ad
    k["acik"] = bool(k["cadirlar"])
    if hd:
        k["boylar"] = _boylar(k["cadirlar"] + [g for v in k.get("roller", {}).values() for g in v])
    return k


def _belgesel(alt: str) -> bool:
    """Belgesel kalite paketi: ana anahtar ve alt özellik birlikte açık mı."""
    b = veri.kural("gorsel").get("belgesel_kalite", {})
    return bool(b.get("acik")) and bool(b.get(alt, True))


def _insan_acik() -> bool:
    """Gerçekçi insanlar (kurallar/insan.yaml acik): takımın 'kisiler' gövdeleri kullanılır."""
    return bool(veri.kural("insan").get("acik"))


def _beden() -> dict:
    """Vücut/yüz çeşitliliği (godot/sahneler/beden.gd): gorsel.yaml karakter_kalite.acik ve .beden iken."""
    k = veri.kural("gorsel").get("karakter_kalite", {})
    if not (k.get("acik") and k.get("beden", {}).get("acik", True)):
        return {"acik": False}
    return {"acik": True, **{a: b for a, b in k.get("beden", {}).items() if a != "acik"}}


def _yuzey() -> dict:
    """Gerçekçi karakter yüzeyi kuralları (kurallar/yuzey.yaml); gorsel.yaml gercekci_karakter.acik iken. Yollar mutlak."""
    if not _belgesel("karakter_yuzey"):
        return {"acik": False}
    kok = ayar.MOTOR / "varlik" / "cc0"
    kur = []
    kk = veri.kural("gorsel").get("karakter_kalite", {})
    ten = [kk["ten"]["kural"]] if kk.get("acik") and kk.get("ten", {}).get("acik") else []   # karakter kalite: ten
    for r in ten + list(veri.kural("yuzey")["kurallar"]):
        d = kok / r["doku"]
        arm = r.get("pur_arm", True)
        kur.append({**{k: v for k, v in r.items() if k != "doku"}, "diff": str(d / "diff.jpg"), "nor": str(d / "nor_gl.jpg"),
                    "pur": str(d / ("arm.jpg" if arm else "rough.jpg")), "pur_arm": arm})
    return {"acik": True, "kurallar": kur}


def _sinema() -> dict:
    """Son işlem katmanı (vinyet/ton/gren); sinematik render açıkken onun 'sinema' ekleri uygulanır."""
    g = veri.kural("gorsel")
    s = dict(g.get("sinema", {"acik": False}))
    sr = g.get("sinematik_render", {})
    if sr.get("acik") and s.get("acik"):
        s.update(sr.get("sinema", {}))
    return s


def _film(c: dict) -> dict:
    """Sinematik render geçişi (godot/sahneler/film.gd): gorsel.yaml 'film'; ışık hazır ayarına özel ek ayarlar 'isik_ozel'."""
    sr = veri.kural("gorsel").get("sinematik_render", {})
    if not sr.get("acik"):
        return {"acik": False}
    f = dict(sr.get("film", {}), acik=True)
    klasik = f.pop("dof_klasik", {})
    if not _belgesel("fiziksel_lens"):
        f.update(klasik)
    f.update(f.pop("isik_ozel", {}).get(c["ortam"]["isik"], {}))
    isik = veri.kural("arazi")["isiklar"][c["ortam"]["isik"]]
    gp = gorsel_profili(veri.kural("gorsel"), c["ortam"]["arazi"])["isik"]
    if "pus_renk" not in f:   # hava rengi: sahne sis rengi ile gök tepe rengi karışımı (uzak plan maviye/soğuğa kayar)
        k = float(f.get("pus_gok_karisim", 0.4))
        sis, tepe = isik["sis"]["renk"], gp.get("gok_tepe", isik["gok"]["tepe"])
        f["pus_renk"] = [sis[i] * (1 - k) + tepe[i] * k for i in range(3)]
    return f


def _mekan_kalite_acik() -> bool:
    return bool(veri.kural("gorsel").get("mekan_kalite", {}).get("acik", False))


def _cevre_glb(ids: list, donem: str | None, hd: bool) -> list[Path]:
    """Rol/katman aday kimliklerinden kullanılabilir GLB'ler. Mekân kalite paketi açıkken stilize parçanın yerine geçen
    gerçekçi varlık (mekan_varliklari.yaml 'yerine') kullanılır; doğrudan gerçekçi kimlik de yazılabilir. Gerçekçi varlık
    yoksa/RED ise eski parça kalır (kırılmaz). Sıra korunur, tekrar yok."""
    from motor.varlik import mekan_varlik as mv
    katalog = mv.katalog()["varliklar"]
    out: list[Path] = []
    agac_acik = _belgesel("agac")
    for pid in ids:
        if pid in katalog:
            adaylar = [g] if hd and (g := mv.kullanilabilir(pid, donem)) else []
        else:
            adaylar = [g for g in mv.yerine_gecen(pid, donem) if agac_acik or katalog.get(g.stem, {}).get("uretici") != "agac"] if hd else []
            if not adaylar and (pr := veri.parca(pid)) and donem in pr.get("donem", []) \
                    and veri.kalite()["ekipman"].get(pid, {}).get("sinif") not in (None, "RED") and veri.ekipman_glb(pid).exists():
                adaylar = [veri.ekipman_glb(pid)]
        out += [g for g in adaylar if g not in out]
    return out


def _boylar(glbler: list[str]) -> dict:
    """GLB yolu → [x, y, z] boyut (m; Blender ekseninde) — dizi yerleşimi modülleri uç uca dizebilsin."""
    from motor.varlik import ekipman, mekan_varlik as mv
    kayit = {**{str(veri.ekipman_glb(p)): v["olcum"]["boyut_m"] for p, v in ekipman.kayit_oku().items()},
             **{str(mv.CIKTI / f"{p}.glb"): v["olcum"]["boyut_m"] for p, v in mv.kayit_oku().items()}}
    return {g: kayit[g] for g in glbler if g in kayit}


def _malzeme(yerlesim: dict, serpme: dict) -> dict:
    """Malzeme yükseltme kuralları (kurallar/malzeme.yaml): stilize parçaların düz renkli malzemeleri adına göre gerçek
    PBR dokulara (CC0) çevrilir. Yalnız mekân kalite paketi açıkken; doku yolları mutlak."""
    m = veri.kural("malzeme")
    if not (_mekan_kalite_acik() and m.get("acik")):
        return {"acik": False}
    kur = []
    for r in m["kurallar"]:
        d = ayar.MOTOR / "varlik" / "cc0" / r["doku"]
        kur.append({"desen": r["desen"], "diff": str(d / "diff.jpg"), "nor": str(d / "nor_gl.jpg"), "arm": str(d / "arm.jpg"),
                    "tekrar_m": r.get("tekrar_m", 2.0), "renk": r.get("renk", [1.0, 1.0, 1.0]), "normal_guc": r.get("normal_guc", 1.0)})
    return {"acik": True, "kurallar": kur, "spekuler": m.get("spekuler_gercek", 0.3)}


def _serpme(plan: dict, c: dict) -> dict:
    """Prosedürel doğa serpmesi: araziye göre katmanlar; yalnız çekimin döneminde kayıtlı, RED olmayan parçalar."""
    k = veri.kural("dogal")
    if not k.get("acik"):
        return {"acik": False}
    donem = c.get("donem") or plan.get("donem")
    katlar = []
    for kural in k["araziler"].get(c["ortam"]["arazi"], []):
        hd = _mekan_kalite_acik()
        uygun = _cevre_glb(kural["parcalar"], donem, hd)
        gercek = hd and any(str(g).startswith(str(ayar.ONBELLEK / "mekan")) for g in uygun)
        for g in uygun:
            katlar.append({"glb": str(g), "adet": max(1, round(kural["adet"] / len(uygun))),
                           "yaricap_m": kural["yaricap_m"], "en_az_aralik_m": kural["en_az_aralik_m"],
                           "olcek": kural.get("olcek_hd", kural["olcek"]) if gercek else kural["olcek"],
                           "golge": kural.get("golge", True),
                           **({"gomme_oran": kural["gomme_oran_hd"]} if gercek and "gomme_oran_hd" in kural else {}),
                           **({"on_yay_derece": kural["on_yay_derece_hd"]} if gercek and "on_yay_derece_hd" in kural else {}),
                           **({"gercek": True, "on_yuz": bool(kural.get("on_yuz_hd", False)),
                               "spekuler": veri.kural("malzeme").get("spekuler_gercek", 0.25)} if gercek else {}),
                           **({"kaya_doku": str(ayar.MOTOR / kural["kaya_doku"]), "kaya_olcek": kural.get("kaya_olcek", 0.18)}
                              if kural.get("kaya_doku") and not gercek else {})})
    return {"acik": bool(katlar), "serit_payi_m": k["serit_payi_m"], "gorus_payi_m": k["gorus_payi_m"], "katmanlar": katlar}


def _vfx(c: dict, ar) -> dict:
    """Parçacık efekti ayarı: doku yolları mutlak, toz rengi araziye göre; çarpışma çekimi mi (savaş dumanı)."""
    v = json.loads(json.dumps(veri.kural("gorsel").get("vfx", {"acik": False})))
    if not v.get("acik"):
        return {"acik": False}
    arazi_adi = c["ortam"]["arazi"]
    for ad in ("toz", "duman"):
        v[ad]["doku"] = str(ayar.MOTOR / v[ad]["doku"])
    if "top" in v:
        for d in ("alev_doku", "duman_doku"):
            v["top"][d] = str(ayar.MOTOR / v["top"][d])
    v["toz"]["renk"] = v["toz"].get("renk_arazi", {}).get(arazi_adi, v["toz"]["renk"])
    v["savas"] = any(k["animasyon"] in v.get("savas_animasyonlari", []) for k in c.get("karakterler", []))
    return v


def _insan_olcekli(c: dict) -> dict:
    """Godot'ya giden çekim kopyasında yaya karakterin kök ölçeği = boy çeşitliliği × dönem insan boyu oranı."""
    oran = float(c.get("insan_boy_orani", 1.0))
    if oran == 1.0:
        return c
    c = json.loads(json.dumps(c))
    for k in c["karakterler"]:
        if not k.get("binek"):
            k["olcek"] = round(float(k.get("olcek", 1.0)) * oran, 4)
    return c


def _binekli(c: dict) -> dict:
    """Atlı karakterlere render bilgisi (GLB yolu, don paleti, eyer ayarı) eklenmiş çekim kopyası."""
    if not any(k.get("binek") for k in c.get("karakterler", [])):
        return c
    from motor.uretim import binek
    c = json.loads(json.dumps(c))
    for k in c["karakterler"]:
        if k.get("binek"):
            binek.hazir(k["binek"]["id"])
            k["binek"] = binek.render_bilgisi(k["binek"])
    return c


def _karma(is_: dict) -> str:
    h = hashlib.sha256(json.dumps(is_, sort_keys=True, ensure_ascii=False).encode())
    for b in BETIKLER:
        h.update(b.read_bytes())
    dosyalar = {t["glb"] for t in is_["takimlar"].values()} | {e["glb"] for t in is_["takimlar"].values() for e in t["takilanlar"]}
    if is_.get("insan", {}).get("acik"):
        dosyalar |= {g for t in is_["takimlar"].values() for g in t.get("kisiler", [])}
    dosyalar |= {cv["glb"] for cv in is_["cevre"]}
    dosyalar |= {kt["glb"] for kt in is_.get("serpme", {}).get("katmanlar", [])}
    dosyalar |= set(is_.get("yerlesim", {}).get("cadirlar", [])) | set(is_.get("yerlesim", {}).get("ekler", []))
    dosyalar |= {is_["vfx"][a]["doku"] for a in ("toz", "duman") if is_.get("vfx", {}).get("acik")}
    dosyalar |= {k["binek"]["glb"] for k in is_["cekim"].get("karakterler", []) if k.get("binek")}
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
                              "-crf", "18", "-pix_fmt", "yuv420p", "-an", str(mp4)], 3600)
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
