"""Gerçekçi insan sistemi (kurallar/insan.yaml; MPFB2 araç + MakeHuman CC0): kişi çeşitliliği, belirlenimcilik,
dönem aralıkları, derleme çıktıları, yön/yuva uyumu ve tek anahtarla geri dönüş."""
import copy
import json
import struct
from pathlib import Path

import pytest

from motor import ayar
from motor.karakter import insan, takim
from motor.uretim import render, veri

GODOT = ayar.MOTOR / "godot/sahneler"
BLENDER = ayar.MOTOR / "varlik/blender"


def _yil(makro_yas):
    return 25 + (makro_yas - 0.5) / 0.5 * 65 if makro_yas >= 0.5 else 1 + makro_yas / 0.5 * 24


def test_kural_tek_anahtar_ve_dönem_aralıkları():
    k = veri.kural("insan")
    assert k["acik"] is True and k["kisi_sayisi"] >= 4
    assert set(k["kitler"]) == {p.stem for p in takim.KITLER.glob("*.yaml")}   # her kit için tanım
    for ad, kt in k["kitler"].items():
        assert abs(sum(kt["sakal"].values()) - 1) < 1e-6 and abs(sum(kt["sakalsiz"].values()) - 1) < 1e-6, ad
    assert 0.3 <= k["beden"]["muscle"][0] and k["beden"]["muscle"][1] <= 0.7   # süper kahraman kası değil


def test_kisi_belirlenimci_ve_farkli():
    a = [insan.kisi("osmanli_15yy", "erkek_x", i, ["kisa", "sakal"]) for i in range(4)]
    b = [insan.kisi("osmanli_15yy", "erkek_x", i, ["kisa", "sakal"]) for i in range(4)]
    assert a == b                                                     # aynı girdi → aynı kişi
    assert len({json.dumps(x["makro"], sort_keys=True) for x in a}) == 4
    assert len({x["tohum"] for x in a}) == 4
    yas = sorted(x["yas_yil"] for x in a)
    lo, hi = veri.kural("insan")["yas_yil"]
    assert lo <= yas[0] and yas[-1] <= hi and yas[-1] - yas[0] > 10   # takımda yaş yayılımı
    for x in a:
        assert abs(_yil(x["makro"]["age"]) - x["yas_yil"]) < 0.2
        assert x["makro"]["gender"] == 1.0 and x["boy_m"] == veri.kural("insan")["referans_boy_m"]


def test_sakal_ve_sac_kit_tanimini_izler():
    for i in range(20):
        x = insan.kisi("roma_cumhuriyet", "erkek_r", i, ["kisa"])
        assert x["sakal"]["tur"] in veri.kural("insan")["kitler"]["roma_cumhuriyet"]["sakalsiz"]
        assert x["sac_kabuk"]["acik"] is True
        y = insan.kisi("osmanli_15yy", "erkek_o", i, ["sakal"])
        assert y["sac_kabuk"]["acik"] is False                         # saçı tanımlanmamış (sarık/börk altı) kişi
        assert y["sakal"]["tur"] in veri.kural("insan")["kitler"]["osmanli_15yy"]["sakal"]


def _glb_dugumler(yol):
    b = Path(yol).read_bytes()
    n = struct.unpack("<I", b[12:16])[0]
    return json.loads(b[20:20 + n])


def test_derlenen_kisiler_var_ve_takima_bagli():
    t = veri.takimlar()
    ozet = json.loads(takim.OZET.read_text())
    n = veri.kural("insan")["kisi_sayisi"]
    sonuc = json.loads(insan.SONUC.read_text())["kisiler"]
    for ad, x in t.items():
        assert len(x["kisiler"]) <= n, ad
        for g in x["kisiler"]:
            assert Path(g).exists(), g
            i = int(Path(g).stem.rsplit("_k", 1)[1])
            assert sonuc[f"{ad}#k{i}"]["gecti"], (ad, i)                # yalnız montaj testinden geçen kişi
        for i in range(n):   # geçemeyen kişi listeye girmez (eşik gevşetilmedi: montaj.ESIK)
            if not sonuc[f"{ad}#k{i}"]["gecti"]:
                assert all(not g.endswith(f"_k{i}.glb") for g in x["kisiler"]), (ad, i)
    assert sum(1 for x in t.values() if x["kisiler"]) >= len(t) // 2
    kullanilan = {x["govde_id"] for x in t.values()}
    for gid, g in ozet["govdeler"].items():
        if gid not in kullanilan:   # hiçbir takımın kullanmadığı eski kayıt
            continue
        ks = g["kisiler"]
        assert len(ks) == n and len({k["sha256"] for k in ks}) == n, gid          # birbirinin kopyası değil
        for k in ks:
            assert k["olcum"] and k["yuvalar"]["bas"]["kemik"] == "Head"


def test_kisi_glb_ubc_iskelet_ve_hiyerarsisiyle_ayni():
    """Godot glTF içe aktarımı kök/iskelet düğüm dönüşümünü UBC'deki gibi görmeli (yön ve yuva doğruluğu)."""
    ozet = json.loads(takim.OZET.read_text())
    gid, g = next((a, b) for a, b in ozet["govdeler"].items() if b.get("kisiler"))
    ubc = _glb_dugumler(takim.GOVDE_CIKTI / f"{gid}.glb")
    for k in g["kisiler"][:2]:
        d = _glb_dugumler(k["glb"])
        ad_u = {x.get("name"): x for x in ubc["nodes"]}
        ad_d = {x.get("name"): x for x in d["nodes"]}
        kemikler = [ubc["nodes"][j]["name"] for j in ubc["skins"][0]["joints"]]
        assert sorted(kemikler) == sorted(d["nodes"][j]["name"] for j in d["skins"][0]["joints"])
        for kok in ("Armature", "Armature.001"):
            assert ad_u[kok].get("rotation") == ad_d[kok].get("rotation"), kok


def test_yuva_yon_algisi_ve_yumusatma_korumasi_kodda():
    g = (BLENDER / "giysi.py").read_text()
    assert "YUMUSATMA_SINIRI" in g and "_taubin" in g                     # MPFB topolojisinde ıraksama koruması
    assert "Matrix.Rotation(math.pi, 4, \"Z\") if _on < -0.02" in g       # -Y'ye bakan gövdede yuvalar çevrilir
    u = (BLENDER / "insan_uret.py").read_text()
    assert "MPFB2 kodu GPL-3" in u and "boy_m" in u and "kil_dokusu" in u


def test_ubc_govdeleri_degismedi():
    """Gerçekçi insan eklemesi UBC gövdelerinin derleme çıktısını bozmamalı (geri dönüş yolu)."""
    import subprocess
    p = subprocess.run(["git", "show", "7bbd27b:motor/karakter/derlenmis3.json"], cwd=ayar.REPO, capture_output=True, text=True)
    if p.returncode != 0:
        pytest.skip("karşılaştırma sürümü yok")
    once = json.loads(p.stdout)["govdeler"]
    simdi = json.loads(takim.OZET.read_text())["govdeler"]
    for gid, g in once.items():
        assert simdi[gid]["olcum"] == g["olcum"], gid
        assert simdi[gid]["yuvalar"] == g["yuvalar"], gid


def test_montaj_esikleri_ayni():
    from motor.karakter import montaj
    assert json.loads(insan.SONUC.read_text())["esikler"] == montaj.ESIK
    assert json.loads(insan.SONUC.read_text())["hizli"] is False


def test_tek_anahtarla_kapanir(monkeypatch):
    assert render._insan_acik() is True
    k = dict(veri.kural("insan"), acik=False)
    gercek = veri.kural
    monkeypatch.setattr(veri, "kural", lambda ad: k if ad == "insan" else gercek(ad))
    assert render._insan_acik() is False and insan.acik() is False


def test_godot_kisi_secimi_ve_beden_atlama():
    s = (GODOT / "cekim.gd").read_text()
    assert '_kisi_sayac' in s and 'takim["glb"] = ks[' in s
    assert "if not gercekci:" in s                                         # kemik ölçeği yalnız UBC gövdesine
    y = (GODOT / "yuzey.gd").read_text()
    assert "kose_renk" in y and "COLOR.rgb" in y
