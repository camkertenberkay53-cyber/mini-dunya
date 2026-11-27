"""Binek (at) GLB üretici — kaynak: Quaternius LowPoly Animated Farm Animal Pack (CC0, OGA; motor/varlik/oga2/lisans.json).

Kullanım: python3 motor/varlik/blender/binek_uret.py <kaynak.blend> <cikti.glb> <yukseklik_m>
- Model değiştirilmez; yalnız nesne ölçeği (gerçek boy) ve animasyon seçimi. Baş -Y (glTF'te +Z = karakterlerin ileri yönü).
- Her yürüyüş animasyonu için ZEMİN HIZI ölçülür (yere basan toynağın gövdeye göre kayma hızı): ayak kaymasın diye
  planlayıcı atı bu hızla ilerletir. Ölçüm <cikti>.olc.json'a yazılır.
"""
import json
import sys

import bpy

kaynak, cikti, boy = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:4]
boy = float(boy)
bpy.ops.wm.open_mainfile(filepath=kaynak)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
# Kaynak malzemeler köşe rengine bağlı (glTF'te taban rengi çıkmıyor): renk aynen korunarak düz Principled malzemeye
# çevrilir ve köşe rengi dışa aktarılmaz. Renkler motor tarafında don paletiyle değiştirilir (binek_kur).
for m in bpy.data.materials:
    renk = list(m.diffuse_color)
    if m.use_nodes and m.node_tree.nodes.get("Principled BSDF"):
        renk = list(m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = renk
    bsdf.inputs["Roughness"].default_value = 0.85
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(bsdf.outputs[0], out.inputs[0])
govde = next(o for o in bpy.data.objects if o.type == "MESH")
# Düz (faceted) gölgeleme low-poly "oyun" görünümü verir: yumuşak normal (geometri aynı).
for p in govde.data.polygons:
    p.use_smooth = True
yuk = max((govde.matrix_world @ v.co).z for v in govde.data.vertices)
olcek = boy / yuk
arm.scale = (olcek,) * 3
bpy.context.view_layer.update()
fps = bpy.context.scene.render.fps / bpy.context.scene.render.fps_base
olc = {"kaynak_yukseklik": round(yuk, 3), "olcek": round(olcek, 5), "fps": fps, "animasyonlar": {}}
TOYNAK = ["FrontFoot.R", "FrontFoot.L", "BackFoot.R", "BackFoot.L"]
for act in bpy.data.actions:
    arm.animation_data_create()
    arm.animation_data.action = act
    if hasattr(arm.animation_data, "action_slot") and act.slots:
        arm.animation_data.action_slot = act.slots[0]
    f0, f1 = int(act.frame_range[0]), int(act.frame_range[1])
    izler = {t: [] for t in TOYNAK}
    for f in range(f0, f1 + 1):
        bpy.context.scene.frame_set(f)
        for t in TOYNAK:
            p = arm.matrix_world @ arm.pose.bones[t].head
            izler[t].append((p.y, p.z))
    hizlar = []
    for t, iz in izler.items():
        zmin = min(z for _, z in iz)
        for i in range(len(iz) - 1):
            if iz[i][1] < zmin + 0.04 * boy and iz[i + 1][1] < zmin + 0.04 * boy:   # yere basıyor
                hizlar.append((iz[i + 1][0] - iz[i][0]) * fps)                     # +Y = geri (baş -Y'de)
    hizlar.sort()
    hiz = hizlar[len(hizlar) // 2] if hizlar else 0.0
    olc["animasyonlar"][act.name] = {"kare": f1 - f0 + 1, "sure_sn": round((f1 - f0) / fps, 3),
                                    "zemin_hizi_m_sn": round(max(0.0, hiz), 3), "ornek": len(hizlar)}
arm.animation_data.action = None
bpy.ops.export_scene.gltf(filepath=cikti, export_format="GLB", export_animations=True, export_animation_mode="ACTIONS",
                          export_force_sampling=True, export_apply=False,
                          export_vertex_color="NONE")
olc["bayt"] = __import__("os").path.getsize(cikti)
olc["ucgen"] = sum(len(p.vertices) - 2 for p in govde.data.polygons)
open(cikti.replace(".glb", ".olc.json"), "w").write(json.dumps(olc, indent=1))
print("BINEK", json.dumps(olc))
