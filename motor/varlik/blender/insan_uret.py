"""Gerçekçi insan gövdesi üretici (Blender/bpy içinde): MPFB2 + MakeHuman CC0 taban ağ, hedefler ve varlıklar →
motorun evrensel iskeletine (UBC, 65 kemik) bağlı, giydirilmeye hazır gövde GLB'si. Çıktı CC0 türevidir.

python3 insan_uret.py <ubc_iskelet.usda> <cikti.glb> <kisi.json>

MPFB2 kodu GPL-3'tür: yalnız ARAÇ olarak çalıştırılır, depoya alınmaz, çıktıya kod girmez. MakeHuman taban ağı,
hedefleri ve system assets (ten, göz, kaş, kirpik, saç) CC0'dır (motor/varlik/makehuman/lisans.json).

kisi.json (motor/karakter/insan.py üretir; bütün alanlar belirlenimci tohumdan):
  tohum, makro{gender, age, muscle, weight, height, proportions, african, asian, caucasian},
  yuz{bolgeler{bolge: adet}, guc}, ten{doku?, renk[r,g,b]}, varliklar{gozler?, kaslar?, kirpikler?, sac?} (mhclo yolları),
  sakal{tur: yok|kirli|kisa|dolgun, renk[r,g,b], uzunluk_m}, sac_kabuk{acik, renk, uzunluk_m} (mhclo saç yoksa),
  doku_dizini (üretilen kıl dokularının yazılacağı yer)

Neden iskelet değiştiriliyor: motorun bütün animasyonları (UAL1/UAL2) UBC iskeletinin yerel kemik eksenlerine göre
yazılmış. MPFB 'game_engine' iskeleti aynı kemik adlarını taşır ama dinlenme pozu ve kemik eksenleri farklıdır:
(1) MPFB insanı kurulur, (2) her kemik UBC dinlenme yönüne döndürülür ve bütün ağlar bu pozda sabitlenir,
(3) UBC iskeletinin eklemleri MPFB eklemlerine taşınır (eksen/roll UBC'de kalır), (4) ağlar aynı adlı ağırlık
gruplarıyla bu iskelete bağlanır. Sonuç motorun giysi (giysi.py), yuva ve animasyon hattına UBC gövdesi gibi girer.
"""
import importlib
import json
import math
import os
import random
import sys

import bpy  # noqa: I001
import addon_utils
import bmesh
import mathutils
import numpy as np

ubc, cikti, par_yolu = sys.argv[-3:]
P = json.load(open(par_yolu))
addon_utils.enable("bl_ext.user_default.mpfb", default_set=True)
M = "bl_ext.user_default.mpfb"
HS = importlib.import_module(M + ".services.humanservice").HumanService
TS = importlib.import_module(M + ".services.targetservice").TargetService
OP = importlib.import_module(M + ".entities.objectproperties").HumanObjectProperties
HEDEF_KOK = os.path.join(os.path.dirname(importlib.import_module(M).__file__), "data", "targets")
r = random.Random(int(P.get("tohum", 1)))
DOKU = P.get("doku_dizini", os.path.dirname(cikti))
os.makedirs(DOKU, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
h = HS.create_human()
for k, v in P.get("makro", {}).items():
    OP.set_value(k, float(v), entity_reference=h)
TS.reapply_macro_details(h)
yz = P.get("yuz", {})
for bolge, adet in yz.get("bolgeler", {"nose": 3, "chin": 2, "eyebrows": 2, "cheek": 2, "mouth": 2, "ears": 1,
                                       "head": 2, "neck": 1, "eyes": 2, "forehead": 1}).items():
    klasor = os.path.join(HEDEF_KOK, bolge)
    if not os.path.isdir(klasor):
        continue
    hedefler = sorted(f for f in os.listdir(klasor) if f.endswith(".target.gz"))
    for f in r.sample(hedefler, min(adet, len(hedefler))):
        TS.load_target(h, os.path.join(klasor, f), weight=r.uniform(0.15, float(yz.get("guc", 0.8))))
# Boy, giysi/yuva/animasyon hattının referansına (UBC gövdesi, baş tepesi 1,81 m) eşitlenir: giysi kalıpları ve kalça
# yüksekliği mutlak ölçülerle tanımlı. Beden/yüz/oran çeşitliliği korunur; sahnedeki boy çeşitliliğini planlayıcının
# 'olcek' ve dönem insan boyu sistemi verir (kurallar/insan_olcek.yaml).
_dg = bpy.context.evaluated_depsgraph_get()
_ev = h.evaluated_get(_dg)
_zs = [v.co.z for v in _ev.to_mesh().vertices]
_boy = (max(_zs) - min(_zs)) * h.matrix_world.to_scale()[2]
_ev.to_mesh_clear()
if P.get("boy_m") and _boy > 0.5:
    _s = float(P["boy_m"]) / _boy
    h.scale = (h.scale[0] * _s, h.scale[1] * _s, h.scale[2] * _s)
    bpy.context.view_layer.objects.active = h
    h.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
# MakeHuman insanı -Y'ye bakar; motorun iskeleti (UBC) ve yuva sözleşmesi +Y'ye. İnsan baştan 180° çevrilir:
# böylece sol taraf -X'te kalır (UBC ile aynı) ve kemik hizalaması yalnız A→T kol farkını düzeltir.
h.rotation_euler = (0.0, 0.0, math.pi)
bpy.context.view_layer.objects.active = h
h.select_set(True)
bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
rig = HS.add_builtin_rig(h, "game_engine")

# MakeHuman varlıkları (göz, kaş, kirpik, saç): MPFB uydurur ve gövde ağırlıklarından ağırlık aktarır
ekler = {}
for tur, yol in (P.get("varliklar") or {}).items():
    if yol and os.path.exists(yol):
        at = {"gozler": "Eyes", "kaslar": "Eyebrows", "kirpikler": "Eyelashes", "sac": "Hair"}.get(tur, "Clothes")
        ekler[tur] = HS.add_mhclo_asset(yol, h, asset_type=at, subdiv_levels=0, material_type="MAKESKIN")
for b in rig.data.bones:
    b.name = {"Root": "root", "head": "Head"}.get(b.name, b.name)

bpy.context.view_layer.objects.active = h
if h.data.shape_keys:
    h.shape_key_add(name="__karisim", from_mix=True)
    cos = [p.co.copy() for p in h.data.shape_keys.key_blocks["__karisim"].data]
    h.shape_key_clear()
    for v, co in zip(h.data.vertices, cos):
        v.co = co

def _grup_koseleri(o, ad):
    g = o.vertex_groups.get(ad)
    if g is None:
        return set()
    return {v.index for v in o.data.vertices for x in v.groups if x.group == g.index and x.weight > 0.5}


# yüz işaret noktaları: MPFB 'joint-*' yardımcı küpleri maske uygulanınca silinir; önce ölçülür
ISARET = {}
for _ad in ("joint-head", "joint-head-2", "joint-mouth", "joint-jaw", "joint-r-eye", "joint-l-eye", "joint-neck"):
    _ks = _grup_koseleri(h, _ad)
    if _ks:
        ISARET[_ad] = sum((h.matrix_world @ h.data.vertices[i].co for i in _ks), mathutils.Vector()) / len(_ks)
GOZ_YARDIMCI = None
if "gozler" not in ekler:   # MakeHuman göz varlığı yoksa: taban ağın göz yardımcı küreleri + kendi iris dokumuz
    _ks = _grup_koseleri(h, "helper-l-eye") | _grup_koseleri(h, "helper-r-eye")
    if _ks:
        GOZ_YARDIMCI = h.copy()
        GOZ_YARDIMCI.data = h.data.copy()
        GOZ_YARDIMCI.name = "gozler"
        bpy.context.scene.collection.objects.link(GOZ_YARDIMCI)
        for _m in [m for m in GOZ_YARDIMCI.modifiers if m.type == "MASK"]:
            GOZ_YARDIMCI.modifiers.remove(_m)
        _bm = bmesh.new()
        _bm.from_mesh(GOZ_YARDIMCI.data)
        _bm.verts.ensure_lookup_table()
        bmesh.ops.delete(_bm, geom=[v for v in _bm.verts if v.index not in _ks], context="VERTS")
        _bm.to_mesh(GOZ_YARDIMCI.data)
        _bm.free()
for m in [m for m in h.modifiers if m.type == "MASK"]:
    bpy.ops.object.modifier_apply(modifier=m.name)
for o in ekler.values():   # uydurma şekil anahtarı/alt bölüm değiştiricileri sabitlenir (ARMATURE kalır)
    bpy.context.view_layer.objects.active = o
    if o.data.shape_keys:
        o.shape_key_add(name="__karisim", from_mix=True)
        cos = [p.co.copy() for p in o.data.shape_keys.key_blocks["__karisim"].data]
        o.shape_key_clear()
        for v, co in zip(o.data.vertices, cos):
            v.co = co
    for m in [m for m in o.modifiers if m.type not in ("ARMATURE",)]:
        bpy.ops.object.modifier_apply(modifier=m.name)


# ------------------------------------------------------------------ kıl kabukları (sakal / kısa saç), kendi üretimimiz
def kil_dokusu(ad: str, tohum: int, yogunluk: float, uzunluk: float, boyut: int = 512) -> str:
    """Dikey kıl telleri: RGB = tel parlaklığı (kök koyu, uç açık), A = yoğunluk. Renk malzemede verilir."""
    g = np.random.default_rng(tohum)
    rgb = np.zeros((boyut, boyut), np.float32)
    a = np.zeros((boyut, boyut), np.float32)
    n = int(boyut * boyut * yogunluk / 40)
    boy = max(4, int(boyut * uzunluk))
    xs, ys = g.integers(0, boyut, n), g.integers(0, boyut, n)
    egim = g.normal(0, 0.18, n)
    parl = g.uniform(0.55, 1.0, n)
    for i in range(n):
        t = np.arange(boy)
        x = (xs[i] + (t * egim[i]).astype(int)) % boyut
        y = (ys[i] + t) % boyut
        kat = (t / boy)
        a[y, x] = np.maximum(a[y, x], 1.0 - 0.35 * kat)
        rgb[y, x] = np.maximum(rgb[y, x], parl[i] * (0.45 + 0.4 * kat))
    # düşük frekanslı yoğunluk dalgası (tutam izlenimi)
    yy, xx = np.mgrid[0:boyut, 0:boyut] / boyut
    dal = 0.9 + 0.1 * np.sin(xx * 6.283 * 5 + np.sin(yy * 6.283 * 3) * 0.8)
    a = np.clip(a * dal, 0, 1)
    img = bpy.data.images.new(ad, boyut, boyut, alpha=True)
    px = np.stack([rgb, rgb, rgb, a], -1)[::-1].reshape(-1)
    img.pixels.foreach_set(px.astype(np.float32))
    yol = os.path.join(DOKU, ad + ".png")
    img.filepath_raw = yol
    img.file_format = "PNG"
    img.save()
    return yol


def kil_malzemesi(ad: str, doku: str, renk) -> bpy.types.Material:
    m = bpy.data.materials.new(ad)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    tx = nt.nodes.new("ShaderNodeTexImage")
    tx.image = bpy.data.images.load(doku, check_existing=True)
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "MULTIPLY"
    mix.inputs["Factor"].default_value = 1.0
    nt.links.new(tx.outputs["Color"], mix.inputs["A"])
    mix.inputs["B"].default_value = list(renk) + [1.0]
    nt.links.new(mix.outputs["Result"], b.inputs["Base Color"])
    nt.links.new(tx.outputs["Alpha"], b.inputs["Alpha"])
    b.inputs["Roughness"].default_value = 0.7
    m.blend_method = "CLIP" if hasattr(m, "blend_method") else None
    try:
        m.surface_render_method = "DITHERED"
    except Exception:  # noqa: BLE001
        pass
    return m


def _eklem(ad):
    """MPFB 'joint-*' köşe grubunun ağırlık merkezi (dünya); maske öncesi ölçüldü."""
    return ISARET.get(ad)


def kabuk(ad: str, secim: set, ofset: float, mat, eksen_merkez, kenar_halka: int = 3, yatay: bool = False):
    """Gövdenin seçili köşelerinin kopyası; normal boyunca dışarı, kenara doğru incelen ofsetle. Ağırlıklar aynen."""
    k = h.copy()
    k.data = h.data.copy()
    k.name = ad
    k.data.name = ad
    bpy.context.scene.collection.objects.link(k)
    bm = bmesh.new()
    bm.from_mesh(k.data)
    bm.verts.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.index not in secim], context="VERTS")
    bm.normal_update()
    # kenardan halka uzaklığı (BFS)
    uz = {v: 0 for v in bm.verts if v.is_boundary}
    sinir = list(uz)
    while sinir:
        yeni = []
        for v in sinir:
            for e in v.link_edges:
                o = e.other_vert(v)
                if o not in uz:
                    uz[o] = uz[v] + 1
                    yeni.append(o)
        sinir = yeni
    for v in bm.verts:
        f = min(1.0, (uz.get(v, kenar_halka) + 0.35) / kenar_halka)
        v.co += v.normal * (ofset * f + 0.0008)
    uv = bm.loops.layers.uv.verify()
    c = eksen_merkez
    for fc in bm.faces:
        for lp in fc.loops:
            p = lp.vert.co
            a_, z_ = math.atan2(p.x - c.x, p.y - c.y) / math.pi * 1.6, p.z * 6.0
            lp[uv].uv = (z_ * 2.5, a_ * 2.5) if yatay else (a_, z_)
    bm.to_mesh(k.data)
    bm.free()
    k.data.materials.clear()
    k.data.materials.append(mat)
    for p in k.data.polygons:
        p.use_smooth = True
    return k


sk = P.get("sakal", {}) or {}
SAKAL_KOSELER = set()
bas_merkez = _eklem("joint-head-2") or _eklem("joint-head") or mathutils.Vector((0, 0, 1.6))
if sk.get("tur", "yok") != "yok":
    # Sakal çizgisi dudak grubundan ve göz/çene işaretlerinden: yanakta göze doğru yükselen hat, bıyık, çene altı
    dudak = _grup_koseleri(h, "lips")
    kulaklar = _grup_koseleri(h, "ears")
    dp = [h.matrix_world @ h.data.vertices[i].co for i in dudak]
    dz0, dz1 = min(p.z for p in dp), max(p.z for p in dp)
    dx = max(abs(p.x) for p in dp)
    dy = max(p.y for p in dp)   # dudakların en öndeki noktası (+Y ön)
    goz = _eklem("joint-r-eye")
    cene_z = _eklem("joint-jaw").z
    favori_x, favori_z = dx + 0.042, goz.z - 0.028
    egim = (favori_z - (dz1 + 0.004)) / max(favori_x - dx, 1e-3)
    on_sinir = goz.y - 0.085
    sec = set()
    for v in h.data.vertices:
        if v.index in dudak or v.index in kulaklar:
            continue
        p = h.matrix_world @ v.co
        ax = abs(p.x)
        ust = dz1 + 0.004 + max(0.0, ax - dx) * egim
        sakal = cene_z - 0.03 <= p.z <= min(ust, favori_z) and p.y > on_sinir
        gerdan = cene_z - 0.055 <= p.z < cene_z - 0.03 and p.y > goz.y - 0.05 and ax < 0.05
        biyik = dz1 < p.z <= dz1 + 0.013 and ax < dx + 0.005 and p.y > dy - 0.02
        if sk["tur"] == "biyik":   # yalnız bıyık (dudak köşelerinden hafif aşağı sarkar)
            biyik = biyik or (dz0 + 0.004 < p.z <= dz1 + 0.006 and dx - 0.004 < ax < dx + 0.008 and p.y > dy - 0.025)
            sakal = gerdan = False
        if sk["tur"] == "kirli":
            gerdan = gerdan and p.z > cene_z - 0.045
        if sakal or gerdan or biyik:
            sec.add(v.index)
    uzun = {"kirli": 0.002, "kisa": 0.006, "dolgun": 0.013, "biyik": 0.005}.get(sk["tur"], 0.006) * float(sk.get("uzunluk_carpan", 1.0))
    yog = {"kirli": 0.5, "kisa": 1.0, "dolgun": 1.35, "biyik": 1.3}.get(sk["tur"], 1.0)
    d = kil_dokusu(f"sakal_{P.get('tohum', 1)}", int(P.get("tohum", 1)) * 3 + 1, yog, 0.05 + uzun * 6)
    SAKAL_KOSELER = sec
    if sec:
        kabuk("sakal", sec, uzun, kil_malzemesi("mi_hair_sakal", d, sk.get("renk", [0.08, 0.06, 0.05])), bas_merkez)
sc = P.get("sac_kabuk", {}) or {}
if sc.get("acik") and "sac" not in ekler:
    sec = _grup_koseleri(h, "scalp")
    if sec:
        d = kil_dokusu(f"sac_{P.get('tohum', 1)}", int(P.get("tohum", 1)) * 5 + 2, 1.5, 0.08)
        kabuk("sac", sec, float(sc.get("uzunluk_m", 0.006)), kil_malzemesi("mi_hair_sac", d, sc.get("renk", [0.06, 0.05, 0.04])),
              bas_merkez, kenar_halka=6)

if "kaslar" not in ekler and P.get("kas", {}).get("acik", True):   # kaş yedeği: kaş kemeri üstünde ince kıl kabuğu
    goz = _eklem("joint-r-eye")
    kk = P.get("kas", {})
    sec = set()
    for v in h.data.vertices:
        p = h.matrix_world @ v.co
        ax = abs(p.x)
        ust = goz.z + 0.026 - max(0.0, ax - 0.03) * 0.25
        if 0.011 <= ax <= 0.058 and goz.z + 0.011 + max(0.0, ax - 0.045) * 0.3 <= p.z <= ust and p.y > goz.y - 0.012:
            sec.add(v.index)
    if sec:
        d = kil_dokusu(f"kas_{P.get('tohum', 1)}", int(P.get("tohum", 1)) * 11 + 3, float(kk.get("yogunluk", 1.1)), 0.05)
        kabuk("kas", sec, float(kk.get("kalinlik_m", 0.0018)), kil_malzemesi("mi_hair_kas", d, P.get("sac_renk", [0.06, 0.05, 0.04])),
              bas_merkez, kenar_halka=2, yatay=True)


def iris_dokusu(ad: str, renk, boyut: int = 256) -> str:
    """Önden düzlemsel izdüşüm için göz dokusu: sklera, renkli iris (ışınsal desen), koyu limbus, gözbebeği."""
    yy, xx = (np.mgrid[0:boyut, 0:boyut] + 0.5) / boyut * 2 - 1
    rr = np.sqrt(xx ** 2 + yy ** 2)
    aci = np.arctan2(yy, xx)
    g = np.random.default_rng(abs(hash(ad)) % 2 ** 31)
    isin = 0.8 + 0.2 * np.sin(aci * 40 + g.uniform(0, 6)) * np.sin(aci * 13)
    c = np.zeros((boyut, boyut, 3), np.float32)
    c[:] = (0.78, 0.74, 0.70)   # sklera (hafif kırık beyaz)
    iris = rr < 0.42
    for i in range(3):
        c[..., i] = np.where(iris, renk[i] * isin * (0.6 + 0.6 * rr / 0.42), c[..., i])
    c = np.where((rr > 0.37)[..., None] & iris[..., None], c * 0.45, c)   # limbus
    c = np.where((rr < 0.15)[..., None], 0.02, c)                         # gözbebeği
    img = bpy.data.images.new(ad, boyut, boyut)
    img.pixels.foreach_set(np.concatenate([c, np.ones((boyut, boyut, 1), np.float32)], -1)[::-1].reshape(-1))
    yol = os.path.join(DOKU, ad + ".png")
    img.filepath_raw = yol
    img.file_format = "PNG"
    img.save()
    return yol


if GOZ_YARDIMCI is not None:
    bm = bmesh.new()
    bm.from_mesh(GOZ_YARDIMCI.data)
    uv = bm.loops.layers.uv.verify()
    for f in bm.faces:
        for lp in f.loops:
            p = lp.vert.co
            e = min((_eklem("joint-l-eye"), _eklem("joint-r-eye")), key=lambda q: (q - p).length)
            lp[uv].uv = ((p.x - e.x) / 0.0125 * 0.5 + 0.5, (p.z - e.z) / 0.0125 * 0.5 + 0.5)
    bm.to_mesh(GOZ_YARDIMCI.data)
    bm.free()
    GOZ_YARDIMCI.data.materials.clear()
    GOZ_YARDIMCI.data.materials.append(bpy.data.materials.new("_gecici"))
    ekler["gozler_yardimci"] = GOZ_YARDIMCI

def ten_koseleri():
    """Ten için köşe rengi (kendi üretimimiz): girinti gölgesi (göz çukuru, burun kanadı, kulak, dudak köşesi),
    bölgesel kızarıklık (yanak, burun, kulak, dudak) ve sakal bölgesinde tıraş gölgesi. Doku olsa da olmasa da çarpan."""
    me = h.data
    n = len(me.vertices)
    co = np.array([v.co[:] for v in me.vertices])
    me.calc_normals_split() if hasattr(me, "calc_normals_split") else None
    nr = np.array([v.normal[:] for v in me.vertices])
    ed = np.array([e.vertices[:] for e in me.edges])
    a, b = ed[:, 0], ed[:, 1]
    d = co[b] - co[a]
    d /= np.linalg.norm(d, axis=1, keepdims=True) + 1e-9
    girinti = np.zeros(n)
    say = np.zeros(n)
    np.add.at(girinti, a, (d * nr[a]).sum(1))
    np.add.at(girinti, b, (-d * nr[b]).sum(1))
    np.add.at(say, a, 1)
    np.add.at(say, b, 1)
    girinti /= np.maximum(say, 1)
    for _ in range(4):   # bulanıklaştır
        t = np.zeros(n)
        np.add.at(t, a, girinti[b])
        np.add.at(t, b, girinti[a])
        girinti = 0.5 * girinti + 0.5 * t / np.maximum(say, 1)
    ao = np.clip(1.0 - np.clip(girinti, 0, None) * 2.2, 0.55, 1.0)
    renk = np.ones((n, 3)) * ao[:, None]
    mw = np.array(h.matrix_world)
    dun = co @ mw[:3, :3].T + mw[:3, 3]
    goz = _eklem("joint-r-eye")
    cene = _eklem("joint-jaw")

    def bolge(merkez, yaricap):
        return np.clip(1 - np.linalg.norm(dun - np.array(merkez), axis=1) / yaricap, 0, 1) ** 1.5

    if goz is not None and cene is not None:
        on = 1 if (sum((dun[i] for i in _grup_koseleri(h, "lips")), np.zeros(3))[1] > goz.y * len(_grup_koseleri(h, "lips"))) else -1
        kiz = np.zeros(n)
        for sx in (-1, 1):
            kiz += 0.8 * bolge((sx * 0.045, goz.y + on * 0.01, goz.z - 0.035), 0.035)   # yanak
        kiz += bolge((0, goz.y + on * 0.035, goz.z - 0.03), 0.022)                        # burun ucu
        for i in _grup_koseleri(h, "ears"):
            kiz[i] += 0.6
        for i in _grup_koseleri(h, "lips"):
            kiz[i] += 1.2
        kiz = np.clip(kiz, 0, 1.4) * float(P.get("kizariklik", 0.22))
        renk[:, 1] *= 1 - kiz * 0.55
        renk[:, 2] *= 1 - kiz * 0.6
        gozalti = 0
        for sx in (-1, 1):
            gozalti = gozalti + bolge((sx * 0.032, goz.y + on * 0.005, goz.z - 0.012), 0.02)
        renk *= (1 - 0.18 * np.clip(gozalti, 0, 1))[:, None]
    if P.get("sakal", {}).get("tur", "yok") != "yok":   # tıraş gölgesi: sakal kabuğunun altındaki ten koyulaşır
        for i in SAKAL_KOSELER:
            renk[i] *= np.array([0.78, 0.76, 0.76])
    ca = me.color_attributes.new("ten_renk", "FLOAT_COLOR", "POINT")
    ca.data.foreach_set("color", np.concatenate([renk, np.ones((n, 1))], 1).astype(np.float32).reshape(-1))
    me.color_attributes.active_color = ca


ten_koseleri()

# ------------------------------------------------------------------ UBC iskeleti
once = set(bpy.data.objects)
bpy.ops.wm.usd_import(filepath=ubc, import_skeletons=True)
yeni = [o for o in bpy.data.objects if o not in once]
ua = next(o for o in yeni if o.type == "ARMATURE")
# USD'nin kök düğümleri (eksen dönüşümü taşıyan boşluklar) korunur: UBC gövdesiyle aynı hiyerarşi
# (Godot glTF içe aktarımı iskelet düğümünün kendi dönüşümünü farklı ele alır; dönüş üst boşlukta kalmalı).
for o in yeni:
    if o.type == "MESH":
        bpy.data.objects.remove(o, do_unlink=True)
bpy.context.view_layer.update()


def yon(arm, ad):
    b = arm.data.bones[ad]
    return ((arm.matrix_world @ b.tail_local) - (arm.matrix_world @ b.head_local)).normalized()


for pb in rig.pose.bones:
    pb.rotation_mode = "QUATERNION"
for b in rig.data.bones:
    if b.name not in ua.data.bones or b.name in ("root",):
        continue
    pb = rig.pose.bones[b.name]
    bpy.context.view_layer.update()
    mw = rig.matrix_world @ pb.matrix
    simdi = (mw.to_3x3() @ mathutils.Vector((0, 1, 0))).normalized()
    q = simdi.rotation_difference(yon(ua, b.name))
    pb.matrix = rig.matrix_world.inverted() @ mathutils.Matrix.LocRotScale(mw.to_translation(), q @ mw.to_quaternion(), None)
bpy.context.view_layer.update()
agler = [o for o in bpy.data.objects if o.type == "MESH" and any(m.type == "ARMATURE" and m.object == rig for m in o.modifiers)]
for o in agler:   # bütün ağlar (gövde, göz, kaş, kirpik, saç, kıl kabukları) aynı pozda sabitlenir
    bpy.context.view_layer.objects.active = o
    mod = next(m for m in o.modifiers if m.type == "ARMATURE")
    bpy.ops.object.modifier_apply(modifier=mod.name)
eklem = {b.name: (rig.matrix_world @ rig.pose.bones[b.name].head, rig.matrix_world @ rig.pose.bones[b.name].tail)
         for b in rig.data.bones}
bpy.context.view_layer.objects.active = ua
bpy.ops.object.mode_set(mode="EDIT")
ters = ua.matrix_world.inverted()
for eb in ua.data.edit_bones:
    if eb.name not in eklem or eb.name == "root":
        continue
    bas, kuyruk = eklem[eb.name]
    boy = (kuyruk - bas).length
    roll = eb.roll
    dv = eb.tail - eb.head   # UBC kemik vektörü (yön VE boy korunur): kemiğe bağlı yuvalar (Blender'da kemik ucuna
    eb.head = ters @ bas     # göre) dışa aktarımda UBC'deki gibi yorumlanır; eklem konumu MPFB'den gelir
    eb.tail = eb.head + dv
    eb.roll = roll
for eb in ua.data.edit_bones:
    if eb.name not in eklem and eb.parent is not None and eb.name != "root":
        dv = (eb.tail - eb.head)
        eb.head = eb.parent.tail
        eb.tail = eb.head + dv
bpy.ops.object.mode_set(mode="OBJECT")
for o in agler:
    mw = o.matrix_world.copy()
    o.parent = ua
    o.matrix_world = mw
    m = o.modifiers.new("Armature", "ARMATURE")
    m.object = ua
    # UBC'de olmayan MPFB kemiklerinin (ör. burgu/twist kemikleri) ağırlıkları, iskelette var olan en yakın
    # atasına eklenir; yoksa o köşeler ağırlıksız kalıp dinlenme pozunda donar (omuzda yırtık şerit).
    gid = {g.index: g.name for g in o.vertex_groups}
    for v in o.data.vertices:
        tasi = {}
        for x in v.groups:
            ad = gid[x.group]
            if ad in ua.data.bones or ad not in rig.data.bones:
                continue
            b = rig.data.bones[ad].parent
            while b is not None and b.name not in ua.data.bones:
                b = b.parent
            if b is not None:
                tasi[b.name] = tasi.get(b.name, 0.0) + x.weight
        for ad, w in tasi.items():
            g = o.vertex_groups.get(ad) or o.vertex_groups.new(name=ad)
            g.add([v.index], w, "ADD")
    for g in list(o.vertex_groups):   # yalnız iskelet kemiği adlı gruplar kalsın (MPFB yardımcı grupları atılır)
        if g.name not in ua.data.bones:
            o.vertex_groups.remove(g)
bpy.data.objects.remove(rig, do_unlink=True)
# Yerleşim UBC'nin USD içe aktarımıyla birebir aynıdır (kök boşluklar, iskelet dünya dönüşümü, +Y'ye bakan gövde);
# giydirme ve yuva hattı (karakter_kur.py) iki gövdeyi aynı biçimde işler.


# ------------------------------------------------------------------ malzemeler (glTF'e temiz çıkan Principled)
def _mhmat_doku(o) -> str | None:
    """MPFB'nin yüklediği malzemedeki ilk renk dokusu (MakeHuman mhmat 'diffuseTexture')."""
    for ms in o.material_slots:
        if ms.material and ms.material.use_nodes:
            for n in ms.material.node_tree.nodes:
                if n.type == "TEX_IMAGE" and n.image and ("diffuse" in n.image.name.lower() or n.label.lower().startswith("diffuse")
                                                           or "color" in n.name.lower()):
                    return bpy.path.abspath(n.image.filepath)
            for n in ms.material.node_tree.nodes:
                if n.type == "TEX_IMAGE" and n.image:
                    return bpy.path.abspath(n.image.filepath)
    return None


def principled(ad, doku=None, renk=(1, 1, 1), alfa=False, puruz=0.55):
    m = bpy.data.materials.new(ad)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = list(renk) + [1.0]
    b.inputs["Roughness"].default_value = puruz
    if doku and os.path.exists(doku):
        tx = m.node_tree.nodes.new("ShaderNodeTexImage")
        tx.image = bpy.data.images.load(doku, check_existing=True)
        if renk != (1, 1, 1):
            mix = m.node_tree.nodes.new("ShaderNodeMix")
            mix.data_type = "RGBA"
            mix.blend_type = "MULTIPLY"
            mix.inputs["Factor"].default_value = 1.0
            m.node_tree.links.new(tx.outputs["Color"], mix.inputs["A"])
            mix.inputs["B"].default_value = list(renk) + [1.0]
            m.node_tree.links.new(mix.outputs["Result"], b.inputs["Base Color"])
        else:
            m.node_tree.links.new(tx.outputs["Color"], b.inputs["Base Color"])
        if alfa:
            m.node_tree.links.new(tx.outputs["Alpha"], b.inputs["Alpha"])
    return m


ten = P.get("ten", {})


def ten_boya(kaynak: str, hedef, boyut: int = 1024) -> str:
    """CC0 MakeHuman ten dokusunu kişinin dönem tenine çevirir (doğrusal uzayda kanal oranı, yüz bölgesi referans).
    Doku ayrıntısı (gözenek, damar, kızarıklık) korunur; yalnız ton değişir. Kendi türev dokumuz (CC0)."""
    from PIL import Image
    im = Image.open(kaynak).convert("RGB").resize((boyut, boyut), Image.LANCZOS)
    a = np.asarray(im).astype(np.float32) / 255.0
    lin = np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)
    y0, y1, x0, x1 = int(boyut * 0.35), int(boyut * 0.64), int(boyut * 0.645), int(boyut * 0.92)
    ort = lin[y0:y1, x0:x1].reshape(-1, 3).mean(0)
    gri = lin.mean(-1, keepdims=True)
    lin = gri + (lin - gri) * 0.9   # fotoğraf dokusunun turuncu doygunluğu biraz alınır
    ort = gri[y0:y1, x0:x1].mean() + (ort - gri[y0:y1, x0:x1].mean()) * 0.9
    lin = np.clip(lin * (np.array(hedef, np.float32) / np.maximum(ort, 1e-3)), 0, 1)
    s = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1 / 2.4) - 0.055)
    yol = os.path.join(DOKU, f"ten_{P.get('tohum', 1)}.png")
    Image.fromarray((np.clip(s, 0, 1) * 255).astype(np.uint8)).save(yol)
    return yol


if ten.get("doku") and ten.get("hedef"):
    ten["doku"] = ten_boya(ten["doku"], ten["hedef"])
    ten["carpan"] = [1, 1, 1]
h.data.materials.clear()
tm = principled("mi_skin_mh", ten.get("doku"), tuple(ten.get("renk", [0.36, 0.21, 0.14])) if not ten.get("doku")
                else tuple(ten.get("carpan", [1, 1, 1])), puruz=0.5)
_b = tm.node_tree.nodes["Principled BSDF"]
_ca = tm.node_tree.nodes.new("ShaderNodeVertexColor")
_ca.layer_name = "ten_renk"
_mx = tm.node_tree.nodes.new("ShaderNodeMix")
_mx.data_type = "RGBA"
_mx.blend_type = "MULTIPLY"
_mx.inputs["Factor"].default_value = 1.0
if _b.inputs["Base Color"].is_linked:
    tm.node_tree.links.new(_b.inputs["Base Color"].links[0].from_socket, _mx.inputs["A"])
else:
    _mx.inputs["A"].default_value = _b.inputs["Base Color"].default_value
tm.node_tree.links.new(_ca.outputs["Color"], _mx.inputs["B"])
tm.node_tree.links.new(_mx.outputs["Result"], _b.inputs["Base Color"])
h.data.materials.append(tm)
ADLAR = {"gozler": "mi_eyes_mh", "kaslar": "mi_hair_kas", "kirpikler": "mi_hair_kirpik", "sac": "mi_hair_sac"}
for tur, o in ekler.items():
    if tur == "gozler_yardimci":
        o.data.materials.clear()
        o.data.materials.append(principled("mi_eyes_mh", iris_dokusu(f"iris_{P.get('tohum', 1)}", P.get("goz_renk", [0.25, 0.15, 0.07])), puruz=0.15))
        o.name = "gozler"
        continue
    d = P.get("goz_doku") if tur == "gozler" and P.get("goz_doku") else _mhmat_doku(o)
    renk = tuple(P.get("sac_renk", [0.07, 0.055, 0.045])) if tur in ("kaslar", "sac") else (1, 1, 1)
    o.data.materials.clear()
    o.data.materials.append(principled(ADLAR.get(tur, "mi_ek_" + tur), d, renk, alfa=tur != "gozler", puruz=0.12 if tur == "gozler" else 0.7))
    o.name = tur
h.name = "govde"
bpy.data.orphans_purge(do_recursive=True)
if cikti.endswith(".blend"):   # giydirme hattına kayıpsız aktarım (glTF dikiş bölmesi ve kemik ekseni sezgisi yok)
    for img in bpy.data.images:
        if img.source == "FILE" and img.filepath:
            img.filepath = bpy.path.abspath(img.filepath)
    bpy.ops.wm.save_as_mainfile(filepath=cikti, compress=True)
else:
    bpy.ops.export_scene.gltf(filepath=cikti, export_format="GLB", export_animations=False, export_yup=True)
olc = {"kose": len(h.data.vertices), "boy_m": round(max(v.co.z for v in h.data.vertices) - min(v.co.z for v in h.data.vertices), 3),
       "ekler": sorted(ekler), "kabuklar": [o.name for o in bpy.data.objects if o.name in ("sakal", "sac", "kas")]}
json.dump(olc, open(cikti.rsplit(".", 1)[0] + ".olc.json", "w"), indent=1)
print("INSAN", json.dumps(olc))
