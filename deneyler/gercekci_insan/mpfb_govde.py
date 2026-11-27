"""Gerçekçi gövde üretici: MPFB2 (GPL-3 kod, yalnız araç olarak çalıştırılır; depoya alınmaz) + MakeHuman CC0 taban
ağ ve hedefler → motorun evrensel iskeletine (UBC, 65 kemik) bağlı çıplak gövde GLB'si. Çıktı CC0 türevidir.

python3 mpfb_govde.py <ubc_iskelet.usda> <cikti.glb> <parametre.json>

Neden iskelet değiştiriliyor: motorun bütün animasyonları (UAL1/UAL2) UBC iskeletinin YEREL kemik eksenlerine göre
yazılmış. MPFB'nin 'game_engine' iskeleti aynı kemik adlarını taşır ama dinlenme pozu (A) ve kemik eksenleri farklıdır.
Bu yüzden: (1) MPFB insanı kurulur (makro + tohumlu yüz/vücut hedefleri), (2) her kemik UBC dinlenme yönüne
döndürülerek gövde T-pozuna getirilir ve ağ bu pozda sabitlenir, (3) UBC iskeleti kopyalanır, eklem konumları
MPFB'ninkilere taşınır (eksen/roll UBC'de kalır), (4) gövde aynı adlı ağırlık gruplarıyla bu iskelete bağlanır.
Sonuç, motorun giysi türetme (giysi.py), yuva ve animasyon hattına mevcut gövdeler gibi girer.
"""
import importlib
import json
import os
import random
import sys

import bpy  # noqa: I001
import addon_utils
import mathutils

ubc, cikti, par_yolu = sys.argv[-3:]
P = json.load(open(par_yolu))
addon_utils.enable("bl_ext.user_default.mpfb", default_set=True)
M = "bl_ext.user_default.mpfb"
HS = importlib.import_module(M + ".services.humanservice").HumanService
TS = importlib.import_module(M + ".services.targetservice").TargetService
OP = importlib.import_module(M + ".entities.objectproperties").HumanObjectProperties
HEDEF_KOK = os.path.join(os.path.dirname(importlib.import_module(M).__file__), "data", "targets")

bpy.ops.wm.read_factory_settings(use_empty=True)
r = random.Random(P.get("tohum", 1))
h = HS.create_human()
for k, v in P.get("makro", {}).items():
    OP.set_value(k, float(v), entity_reference=h)
TS.reapply_macro_details(h)
for bolge, adet in P.get("yuz_bolgeleri", {"nose": 3, "chin": 2, "eyebrows": 2, "cheek": 2, "mouth": 2, "ears": 1,
                                             "head": 2, "neck": 1, "eyes": 2, "forehead": 1}).items():
    klasor = os.path.join(HEDEF_KOK, bolge)
    hedefler = sorted(f for f in os.listdir(klasor) if f.endswith(".target.gz"))
    for f in r.sample(hedefler, min(adet, len(hedefler))):
        TS.load_target(h, os.path.join(klasor, f), weight=r.uniform(0.15, float(P.get("yuz_guc", 0.8))))
rig = HS.add_builtin_rig(h, "game_engine")
for b in rig.data.bones:
    b.name = {"Root": "root", "head": "Head"}.get(b.name, b.name)
# şekil anahtarlarını ve yardımcı-gizleme maskesini uygula (yalnız gövde kalsın)
bpy.context.view_layer.objects.active = h
if h.data.shape_keys:
    h.shape_key_add(name="__karisim", from_mix=True)
    cos = [p.co.copy() for p in h.data.shape_keys.key_blocks["__karisim"].data]
    h.shape_key_clear()
    for v, co in zip(h.data.vertices, cos):
        v.co = co
for m in [m for m in h.modifiers if m.type == "MASK"]:
    bpy.ops.object.modifier_apply(modifier=m.name)

# --- UBC iskeleti
once = set(bpy.data.objects)
bpy.ops.wm.usd_import(filepath=ubc, import_skeletons=True)
yeni = [o for o in bpy.data.objects if o not in once]
ua = next(o for o in yeni if o.type == "ARMATURE")
for o in yeni:
    if o is not ua:
        bpy.data.objects.remove(o, do_unlink=True)
bpy.context.view_layer.update()


def yon(arm, ad):
    b = arm.data.bones[ad]
    return ((arm.matrix_world @ b.tail_local) - (arm.matrix_world @ b.head_local)).normalized()


# (2) MPFB gövdesini UBC dinlenme yönlerine pozla (ebeveyn önce), ağı bu pozda sabitle
for pb in rig.pose.bones:
    pb.rotation_mode = "QUATERNION"
for b in rig.data.bones:
    if b.name not in ua.data.bones or b.name in ("root",):
        continue
    pb = rig.pose.bones[b.name]
    bpy.context.view_layer.update()
    mw = rig.matrix_world @ pb.matrix
    simdi = (mw.to_3x3() @ mathutils.Vector((0, 1, 0))).normalized()
    hedef = yon(ua, b.name)
    q = simdi.rotation_difference(hedef)
    yeni_mw = mathutils.Matrix.LocRotScale(mw.to_translation(), q @ mw.to_quaternion(), None)
    pb.matrix = rig.matrix_world.inverted() @ yeni_mw
bpy.context.view_layer.update()
mod = next(m for m in h.modifiers if m.type == "ARMATURE")
bpy.context.view_layer.objects.active = h
bpy.ops.object.modifier_apply(modifier=mod.name)
eklem = {b.name: (rig.matrix_world @ rig.pose.bones[b.name].head, rig.matrix_world @ rig.pose.bones[b.name].tail)
         for b in rig.data.bones}

# (3) UBC iskeletinin eklemlerini MPFB eklemlerine taşı (yön/roll UBC'de kalsın: kuyruk = yeni baş + UBC yönü * boy)
bpy.context.view_layer.objects.active = ua
bpy.ops.object.mode_set(mode="EDIT")
ters = ua.matrix_world.inverted()
for eb in ua.data.edit_bones:
    if eb.name not in eklem or eb.name == "root":
        continue
    bas, kuyruk = eklem[eb.name]
    boy = (kuyruk - bas).length
    roll = eb.roll
    d = (eb.tail - eb.head).normalized()
    eb.head = ters @ bas
    eb.tail = eb.head + d * max(boy * (ters.to_scale()[0]), 1e-3)
    eb.roll = roll
# yaprak kemikler (…_leaf) ebeveynlerinin ucuna taşınır
for eb in ua.data.edit_bones:
    if eb.name not in eklem and eb.parent is not None and eb.name != "root":
        d = (eb.tail - eb.head)
        eb.head = eb.parent.tail
        eb.tail = eb.head + d
bpy.ops.object.mode_set(mode="OBJECT")

# (4) gövdeyi UBC iskeletine bağla (aynı adlı ağırlık grupları), MPFB iskeletini sil
mw = h.matrix_world.copy()
h.parent = ua
h.matrix_world = mw
m = h.modifiers.new("Armature", "ARMATURE")
m.object = ua
bpy.data.objects.remove(rig, do_unlink=True)
ten = bpy.data.materials.new("ten")
ten.use_nodes = True
ten.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = list(P.get("ten_renk", [0.36, 0.21, 0.14])) + [1.0]
ten.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.6
h.data.materials.clear()
h.data.materials.append(ten)
h.name = "govde"
bpy.data.orphans_purge(do_recursive=True)
bpy.ops.export_scene.gltf(filepath=cikti, export_format="GLB", export_animations=False, export_yup=True)
olc = {"kose": len(h.data.vertices), "ucgen": sum(len(p.vertices) - 2 for p in h.data.polygons),
       "boy_m": round(max(v.co.z for v in h.data.vertices) - min(v.co.z for v in h.data.vertices), 3), "parametre": P}
json.dump(olc, open(cikti.replace(".glb", ".olc.json"), "w"), indent=1)
print("GOVDE", json.dumps(olc)[:300])
