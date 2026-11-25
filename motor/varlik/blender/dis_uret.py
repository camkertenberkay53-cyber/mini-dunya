"""Dış (lisansı kaynaklar.yaml'da doğrulanmış CC0) çevre modellerini motor GLB'sine çevirir.
ekipman_uret.py'den ayrıdır: kendi üretim betiklerinin özeti (ve dolayısıyla kendi parçalarımızın anahtarları) değişmez.
Kullanım: python3 dis_uret.py <is.json>   (is.json: {"parcalar": [{id, p: {kaynak, olcek, yon_derece}, cikti}]})"""
import json
import math
import os
import sys

import bpy  # noqa: I001
import bmesh

sys.path.insert(0, os.path.dirname(__file__))
import ortak  # noqa: E402

IS = json.load(open(sys.argv[-1]))


def dis_usd(p):
    """Lisansı kaynaklar.yaml'da doğrulanmış dış (CC0) modeli içe alır; yalnız ölçek/döndürme, geometri değişmez.
    p: {kaynak: <mutlak .usda>, olcek: float, yon_derece: float}. Taban y=0'a, merkez x/y=0'a oturtulur."""
    bpy.ops.wm.usd_import(filepath=p["kaynak"])
    mesh = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    for o in list(bpy.context.scene.objects):
        if o.type != "MESH":
            for c in o.children:
                mw = c.matrix_world.copy()
                c.parent = None
                c.matrix_world = mw
    bpy.context.view_layer.update()
    for o in mesh:
        bpy.context.view_layer.objects.active = o
        o.select_set(True)
    bpy.ops.object.select_all(action="DESELECT")
    for o in mesh:
        o.select_set(True)
    bpy.context.view_layer.objects.active = mesh[0]
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    olcek = float(p.get("olcek", 1.0))
    import mathutils
    don = mathutils.Matrix.Rotation(math.radians(float(p.get("yon_derece", 0.0))), 4, "Z")
    for o in mesh:
        o.data.transform(don @ mathutils.Matrix.Scale(olcek, 4))
    vs = [v.co for o in mesh for v in o.data.vertices]
    mn = mathutils.Vector((min(v.x for v in vs), min(v.y for v in vs), min(v.z for v in vs)))
    mx = mathutils.Vector((max(v.x for v in vs), max(v.y for v in vs), max(v.z for v in vs)))
    kay = mathutils.Matrix.Translation((-(mn.x + mx.x) / 2, -(mn.y + mx.y) / 2, -mn.z))
    for o in mesh:
        o.data.transform(kay)
    for o in [o for o in bpy.context.scene.objects if o.type != "MESH"]:
        bpy.data.objects.remove(o, do_unlink=True)
    return mesh


def olc(o):
    bm = bmesh.new()
    bm.from_mesh(o.data)
    xs = [v.co.x for v in bm.verts]
    ys = [v.co.y for v in bm.verts]
    zs = [v.co.z for v in bm.verts]
    sonuc = {"ucgen": sum(len(f.verts) - 2 for f in bm.faces), "kose": len(o.data.vertices),
             "yalniz_kose": sum(1 for v in bm.verts if not v.link_faces), "bozuk_yuz": sum(1 for f in bm.faces if f.calc_area() < 1e-9),
             "boyut_m": [round(max(xs) - min(xs), 3), round(max(ys) - min(ys), 3), round(max(zs) - min(zs), 3)],
             "min": [round(min(xs), 3), round(min(ys), 3), round(min(zs), 3)], "max": [round(max(xs), 3), round(max(ys), 3), round(max(zs), 3)],
             "malzeme": len(o.data.materials), "doku": sorted({max(i.size) for i in bpy.data.images if i.size[0] > 0})}
    bm.free()
    return sonuc


for parca in IS["parcalar"]:
    ortak.sifirla()
    o = ortak.birlestir(dis_usd(parca["p"]), parca["id"])
    bpy.data.orphans_purge(do_recursive=True)
    sonuc = olc(o)
    bpy.ops.export_scene.gltf(filepath=parca["cikti"], export_format="GLB", export_image_format="WEBP", export_yup=True, use_selection=False)
    sonuc["bayt"] = os.path.getsize(parca["cikti"])
    json.dump(sonuc, open(parca["cikti"].replace(".glb", ".olc.json"), "w"))
    print("URETILDI", parca["id"], sonuc["ucgen"], sonuc["bayt"])
