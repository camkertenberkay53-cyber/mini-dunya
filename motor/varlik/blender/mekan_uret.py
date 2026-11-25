"""Gerçekçi mekân varlıkları (CC0 glTF, ör. Poly Haven) → motor GLB'si.

Kullanım: python3 mekan_uret.py <is.json>
is.json: {"parcalar": [{"id", "gltf": <mutlak yol>, "nesneler": [ad, ...] | null, "olcek", "yon_derece",
                        "ucgen_hedef", "doku_max", "cikti"}]}
Yapılan: yalnız seçili nesneler tutulur (modüler setlerden tek modül), dönüşümler uygulanır, döndürme/ölçek,
taban z=0 ve x/y merkez, gerekirse üçgen azaltma (collapse; UV ve malzeme korunur), doku sınırı. Modelin kendi
PBR malzemesi ve UV'leri korunur; malzeme uydurulmaz. Çıktı: GLB (WEBP doku) + .olc.json ölçümü."""
import json
import math
import os
import sys

import bpy  # noqa: I001
import bmesh
import mathutils

IS = json.load(open(sys.argv[-1]))


def hazirla(p):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=p["gltf"])
    tut = set(p.get("nesneler") or [])
    for o in list(bpy.context.scene.objects):
        if o.type == "MESH" and (not tut or o.name in tut):
            continue
        if o.type == "MESH":
            bpy.data.objects.remove(o, do_unlink=True)
    for o in list(bpy.context.scene.objects):   # boş/ebeveyn düğümleri: dünya dönüşümü çocuklara aktarılır
        if o.type != "MESH":
            for c in o.children:
                mw = c.matrix_world.copy()
                c.parent = None
                c.matrix_world = mw
            bpy.data.objects.remove(o, do_unlink=True)
    mesh = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not mesh:
        raise SystemExit(f"{p['id']}: seçili nesne yok {sorted(tut)}")
    bpy.ops.object.select_all(action="DESELECT")
    for o in mesh:
        o.select_set(True)
    bpy.context.view_layer.objects.active = mesh[0]
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    if len(mesh) > 1:
        bpy.ops.object.join()
    o = bpy.context.view_layer.objects.active
    o.name = p["id"]
    bm = bmesh.new()   # UV dikişlerinde ayrık kalan çakışık köşeler kaynaştırılır (UV köşe-başına korunur); azaltma ancak böyle işler
    bm.from_mesh(o.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0005)
    bm.to_mesh(o.data)
    bm.free()
    hedef = int(p.get("ucgen_hedef", 0))
    ucgen = sum(len(f.vertices) - 2 for f in o.data.polygons)
    if hedef and ucgen > hedef:   # silüeti koruyan kenar çöktürme; UV dikişleri korunur
        m = o.modifiers.new("azalt", "DECIMATE")
        m.decimate_type = "COLLAPSE"
        m.ratio = hedef / ucgen
        m.use_collapse_triangulate = True
        bpy.ops.object.modifier_apply(modifier=m.name)
    bm = bmesh.new()   # temizlik: yüzü olmayan (görünmez) yalnız köşeler silinir; yüzey değişmez
    bm.from_mesh(o.data)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bm.to_mesh(o.data)
    bm.free()
    don = mathutils.Matrix.Rotation(math.radians(float(p.get("yon_derece", 0.0))), 4, "Z")
    o.data.transform(don @ mathutils.Matrix.Scale(float(p.get("olcek", 1.0)), 4))
    vs = [v.co for v in o.data.vertices]
    mn = mathutils.Vector((min(v.x for v in vs), min(v.y for v in vs), min(v.z for v in vs)))
    mx = mathutils.Vector((max(v.x for v in vs), max(v.y for v in vs), max(v.z for v in vs)))
    o.data.transform(mathutils.Matrix.Translation((-(mn.x + mx.x) / 2, -(mn.y + mx.y) / 2, -mn.z)))
    o.data.update()
    dm = int(p.get("doku_max", 1024))
    for im in bpy.data.images:
        if im.size[0] > dm or im.size[1] > dm:
            k = dm / max(im.size[0], im.size[1])
            im.scale(max(1, int(im.size[0] * k)), max(1, int(im.size[1] * k)))
    return o


def olc(o):
    bm = bmesh.new()
    bm.from_mesh(o.data)
    xs, ys, zs = ([v.co[i] for v in bm.verts] for i in range(3))
    s = {"ucgen": sum(len(f.verts) - 2 for f in bm.faces), "kose": len(bm.verts),
         "yalniz_kose": sum(1 for v in bm.verts if not v.link_faces), "bozuk_yuz": sum(1 for f in bm.faces if f.calc_area() < 1e-10),
         "boyut_m": [round(max(xs) - min(xs), 3), round(max(ys) - min(ys), 3), round(max(zs) - min(zs), 3)],
         "malzeme": len(o.data.materials), "uv": len(o.data.uv_layers),
         "doku": sorted({max(i.size) for i in bpy.data.images if i.size[0] > 0}),
         "pbr_harita": sorted({ln.to_socket.name for m in o.data.materials if m and m.node_tree
                               for ln in m.node_tree.links if ln.from_node.type in ("TEX_IMAGE", "NORMAL_MAP", "SEPARATE_COLOR")
                               and ln.to_node.type in ("BSDF_PRINCIPLED", "NORMAL_MAP")})}
    bm.free()
    return s


for p in IS["parcalar"]:
    o = hazirla(p)
    bpy.data.orphans_purge(do_recursive=True)
    s = olc(o)
    bpy.ops.export_scene.gltf(filepath=p["cikti"], export_format="GLB", export_image_format="WEBP", export_yup=True,
                              use_selection=False)
    s["bayt"] = os.path.getsize(p["cikti"])
    json.dump(s, open(p["cikti"].replace(".glb", ".olc.json"), "w"))
    print("URETILDI", p["id"], s["ucgen"], s["bayt"])
