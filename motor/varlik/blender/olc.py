"""Blender (bpy) içinde çalışır: bir GLB'nin ölçülebilir özelliklerini JSON olarak yazar.

python3 olc.py <girdi.glb> <cikti.json> <ual_kemikleri.json>
Ölçümler: boy (m), üçgen, kemikler ve evrensel iskelet eşleşmesi, animasyonlar, dokular,
baş oranı (başın tepesinden boyun tabanına uzunluk / boy). Gerçek insanda ~0,13-0,17; chibi 0,3+.
"""
import json
import sys

import bpy
from mathutils import Vector

girdi, cikti, ual_yol = sys.argv[-3], sys.argv[-2], sys.argv[-1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=girdi)

# Ölçüm dinlenme duruşunda yapılır (aktif animasyonun pozu boyu bozmasın)
for o in bpy.data.objects:
    if o.type == "ARMATURE":
        o.data.pose_position = "REST"
bpy.context.view_layer.update()
dg = bpy.context.evaluated_depsgraph_get()
zs, xs, ys, ucgen = [], [], [], 0
for o in bpy.data.objects:
    # glTF içe aktarıcı kemik şekli için görünmez bir "Icosphere" yaratır; ölçüme girmez
    if o.type != "MESH" or not o.visible_get():
        continue
    e = o.evaluated_get(dg)
    me = e.to_mesh()
    me.calc_loop_triangles()
    ucgen += len(me.loop_triangles)
    for v in me.vertices:
        w = e.matrix_world @ v.co
        xs.append(w.x); ys.append(w.y); zs.append(w.z)
    e.to_mesh_clear()

arm = [o for o in bpy.data.objects if o.type == "ARMATURE"]
kemikler = [b.name for b in arm[0].data.bones] if arm else []
ual = set(json.load(open(ual_yol)))
boy = (max(zs) - min(zs)) if zs else 0.0
bas_orani = None
if arm and zs:
    a = arm[0]
    boyun = [b for b in a.data.bones if "neck" in b.name.lower()]
    bas = [b for b in a.data.bones if b.name.lower() in ("head", "head_01") or b.name.lower().startswith("head")]
    ref = None
    if boyun:
        ref = min(boyun, key=lambda b: (a.matrix_world @ b.head_local).z)
        z = (a.matrix_world @ ref.head_local).z
    elif bas:
        z = (a.matrix_world @ bas[0].head_local).z
    else:
        z = None
    if z is not None and boy > 0:
        bas_orani = (max(zs) - z) / boy

dokular = [{"ad": i.name, "boyut": list(i.size)} for i in bpy.data.images if i.size[0] > 0]
sonuc = {
    "boy_m": round(boy, 3),
    "genislik_m": round(max(xs) - min(xs), 3) if xs else 0,
    "ucgen": ucgen,
    "kemik_sayisi": len(kemikler),
    "evrensel_iskelet_eslesen": len(ual & set(kemikler)),
    "evrensel_iskelet_toplam": len(ual),
    "animasyonlar": sorted(a.name for a in bpy.data.actions),
    "doku_sayisi": len(dokular),
    "en_buyuk_doku": max((max(d["boyut"]) for d in dokular), default=0),
    "bas_orani": round(bas_orani, 3) if bas_orani is not None else None,
}
json.dump(sonuc, open(cikti, "w"), ensure_ascii=False, indent=1)
print("OLCULDU", sonuc)
