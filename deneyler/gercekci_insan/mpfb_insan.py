"""Gerçekçi insan üretici (deneme) — MPFB2 (kod GPL-3, araç olarak çalıştırılır; depoya alınmaz) + MakeHuman CC0
taban ağ/hedefler. Çıktı CC0 türevidir.

Kullanım: python3 mpfb_insan.py <kaynak_ubc.glb> <cikti.glb> <parametre.json>
- İnsan makro (cinsiyet, yaş, kas, kilo, boy, oranlar, köken karışımı) ve tohumlu yüz hedefleri (burun, çene, kaş,
  yanak, ağız, kulak, kafa) ile üretilir; MPFB 'game_engine' iskeleti (UE adları) eklenir, Root→root, head→Head.
- Animasyon AKTARIMI: kaynak UBC karakterindeki animasyonlar (aynı kemik adları) her karede "dinlenme pozuna göre
  dünya dönüşü farkı" ile aktarılır: R_hedef = R_kaynak · R_kaynak_dinlenme⁻¹ · R_hedef_dinlenme; leğen yüksekliği
  bacak boyu oranıyla ölçeklenir. Böylece kemik eksen farkları sorun olmaz.
- Ten: düz Principled (parametreden ton); dışa aktarımda glTF'e çıkar.
"""
import importlib
import json
import math
import random
import sys

import bpy  # noqa: I001
import addon_utils
import mathutils

kaynak, cikti, par_yolu = sys.argv[-3:]
P = json.load(open(par_yolu))
addon_utils.enable("bl_ext.user_default.mpfb", default_set=True)
M = "bl_ext.user_default.mpfb"
HS = importlib.import_module(M + ".services.humanservice").HumanService
TS = importlib.import_module(M + ".services.targetservice").TargetService
OP = importlib.import_module(M + ".entities.objectproperties").HumanObjectProperties
import os
HEDEF_KOK = os.path.join(os.path.dirname(importlib.import_module(M).__file__), "data", "targets")

bpy.ops.wm.read_factory_settings(use_empty=True)
r = random.Random(P.get("tohum", 1))
h = HS.create_human()
for k, v in P.get("makro", {}).items():
    OP.set_value(k, float(v), entity_reference=h)
TS.reapply_macro_details(h)
# tohumlu yüz/vücut ayrıntıları: her bölgeden birkaç hedef, küçük ağırlıklarla
for bolge, adet in P.get("yuz_bolgeleri", {"nose": 3, "chin": 2, "eyebrows": 2, "cheek": 2, "mouth": 2, "ears": 1, "head": 2, "neck": 1}).items():
    klasor = os.path.join(HEDEF_KOK, bolge)
    hedefler = sorted(f for f in os.listdir(klasor) if f.endswith(".target.gz"))
    for f in r.sample(hedefler, min(adet, len(hedefler))):
        TS.load_target(h, os.path.join(klasor, f), weight=r.uniform(0.2, float(P.get("yuz_guc", 0.8))))
rig = HS.add_builtin_rig(h, "game_engine")
for b in rig.data.bones:
    if b.name == "Root":
        b.name = "root"
    elif b.name == "head":
        b.name = "Head"
# yardımcı ağları sil (göz kapakları dışındaki helper'lar), şekil anahtarlarını uygula
bpy.context.view_layer.objects.active = h
for v in [g for g in h.vertex_groups if g.name.startswith("HelperGeometry") or g.name.startswith("JointCubes")]:
    pass
mask = [m for m in h.modifiers if m.type == "MASK"]
if h.data.shape_keys:
    h.shape_key_add(name="__karisim", from_mix=True)
    kb = h.data.shape_keys.key_blocks
    son = kb["__karisim"]
    for v, co in zip(h.data.vertices, [p.co.copy() for p in son.data]):
        v.co = co
    h.shape_key_clear()
for m in mask:   # helper'ları gizleyen maske: uygula (yalnız gövde kalsın)
    bpy.ops.object.modifier_apply(modifier=m.name)

# ten
ten = bpy.data.materials.new("ten")
ten.use_nodes = True
bsdf = ten.node_tree.nodes["Principled BSDF"]
bsdf.inputs["Base Color"].default_value = list(P.get("ten_renk", [0.62, 0.42, 0.32])) + [1.0]
bsdf.inputs["Roughness"].default_value = 0.6
h.data.materials.clear()
h.data.materials.append(ten)

# --- kaynak animasyonlar
onceki = set(bpy.data.objects)
bpy.ops.import_scene.gltf(filepath=kaynak)
yeni = [o for o in bpy.data.objects if o not in onceki]
src = next(o for o in yeni if o.type == "ARMATURE")
for o in yeni:
    if o.type == "MESH":
        o.hide_render = True
bpy.context.view_layer.update()


def dunya_dinlenme(arm):
    return {b.name: (arm.matrix_world @ b.matrix_local).to_quaternion() for b in arm.data.bones}


Rs, Rt = dunya_dinlenme(src), dunya_dinlenme(rig)


def yon(arm, b):
    return ((arm.matrix_world @ b.tail_local) - (arm.matrix_world @ b.head_local)).normalized()


# Dinlenme pozları farklı (UBC T-poz, MPFB A-poz): hedefin dinlenme yönleri kaynağınkine hizalanır, aktarım bu hizalanmış
# referansa göre yapılır (aksi hâlde kollar dinlenme farkı kadar sapar).
for b in rig.data.bones:
    if b.name in src.data.bones:
        Rt[b.name] = yon(rig, b).rotation_difference(yon(src, src.data.bones[b.name])) @ Rt[b.name]
ortak = [b.name for b in rig.data.bones if b.name in Rs]
sira = [b.name for b in rig.data.bones]   # ebeveyn önce gelir (Blender bone sırası)
bacak_s = (src.data.bones["thigh_l"].head_local - src.data.bones["foot_l"].head_local).length
bacak_t = (rig.data.bones["thigh_l"].head_local - rig.data.bones["foot_l"].head_local).length
oran = bacak_t / bacak_s
pel_s0 = src.matrix_world @ src.data.bones["pelvis"].head_local
pel_t0 = rig.matrix_world @ rig.data.bones["pelvis"].head_local
istenen = P.get("animasyonlar", ["Idle_Loop", "Walk_Loop"])
rig.animation_data_create()
for pb in rig.pose.bones:   # MPFB kemikleri Euler; aktarım dördey (quaternion) anahtarı yazar
    pb.rotation_mode = "QUATERNION"
for act in [a for a in bpy.data.actions if a.name in istenen or a.name.split("|")[-1] in istenen]:
    src.animation_data.action = act
    if hasattr(src.animation_data, "action_slot") and act.slots:
        src.animation_data.action_slot = act.slots[0]
    ad = act.name.split("|")[-1]
    hedef = bpy.data.actions.new("__aktar__" + ad)
    rig.animation_data.action = hedef
    f0, f1 = int(act.frame_range[0]), int(act.frame_range[1])
    for f in range(f0, f1 + 1):
        bpy.context.scene.frame_set(f)
        for n in sira:
            if n not in Rs:
                continue
            pb = rig.pose.bones[n]
            sw = (src.matrix_world @ src.pose.bones[n].matrix).to_quaternion()
            q = sw @ Rs[n].inverted() @ Rt[n]
            mw = rig.matrix_world.inverted().to_quaternion() @ q
            konum = pb.matrix.to_translation()
            if n == "pelvis":
                ps = src.matrix_world @ src.pose.bones[n].head
                konum = rig.matrix_world.inverted() @ (pel_t0 + (ps - pel_s0) * oran)
            pb.matrix = mathutils.Matrix.LocRotScale(konum, mw, None)
            bpy.context.view_layer.update()
            pb.keyframe_insert("rotation_quaternion", frame=f)
            if n == "pelvis":
                pb.keyframe_insert("location", frame=f)
    bpy.context.scene.frame_set(f0 + 10)
    ds = ((src.matrix_world @ src.pose.bones["upperarm_l"].tail) - (src.matrix_world @ src.pose.bones["upperarm_l"].head)).normalized()
    dt = ((rig.matrix_world @ rig.pose.bones["upperarm_l"].tail) - (rig.matrix_world @ rig.pose.bones["upperarm_l"].head)).normalized()
    print("AKTARILDI", ad, f1 - f0 + 1, "kol_yon_farki_derece", round(math.degrees(ds.angle(dt)), 1), [round(x, 2) for x in ds], [round(x, 2) for x in dt])
for o in yeni:
    bpy.data.objects.remove(o, do_unlink=True)
rig.animation_data.action = None
for a in list(bpy.data.actions):   # kaynak animasyonlar dışa aktarılmaz; aktarılanlar asıl adını alır
    if not a.name.startswith("__aktar__"):
        bpy.data.actions.remove(a)
for a in bpy.data.actions:
    a.name = a.name[len("__aktar__"):]
    if hasattr(a, "slots"):
        for sl in a.slots:
            sl.name_display = a.name   # glTF dışa aktarımı animasyon adını yuvadan alıyor
bpy.ops.export_scene.gltf(filepath=cikti, export_format="GLB", export_animations=True, export_animation_mode="ACTIONS",
                          export_force_sampling=True, export_apply=True)
print("BITTI", cikti, len(h.data.polygons))
