"""Blender (bpy) içinde çalışır: tarif JSON'undan tek bir karakter GLB'si kurar.

python3 karakter_kur.py <tarif.json>
tarif: {kiyafet, govde?, ekler[], animasyon_fbx?, animasyonlar[], doku_siniri, renk?, cikti}
- kiyafet: iskeletli kıyafet (USD) ya da hazır GLB/GLTF. İskelet bundan alınır.
- govde: gerçek oranlı çıplak gövde; yalnızca baş/boyun/el ağırlıklı köşeleri tutulur
  (kıyafetin içinden gövde taşmasın).
- ekler: saç/sakal gibi iskeletli parçalar (kırpılmaz).
- animasyonlar: evrensel kütüphaneden aynı adlı klipler NLA izine eklenir.
- doku_siniri: hiçbir doku bu pikseli aşamaz (repo ve render bütçesi).
- renk: [r,g,b] çarpanı. Yalnızca test içindir (renk kopyası negatif örneği).
"""
import json
import os
import sys

import bpy  # noqa: I001 (bpy önce yüklenmeli)
import bmesh

t = json.load(open(sys.argv[-1]))
TUT = ("Head", "neck_01", "hand_", "index_", "middle_", "pinky_", "ring_", "thumb_")

bpy.ops.wm.read_factory_settings(use_empty=True)


def al(yol):
    once = set(bpy.data.objects)
    if yol.lower().endswith(".blend"):   # gerçekçi insan gövdesi (insan_uret.py): bütün nesneler eklenir
        with bpy.data.libraries.load(yol, link=False) as (kaynak, hedef):
            hedef.objects = list(kaynak.objects)
        for o in hedef.objects:
            if o is not None and o.name not in bpy.context.scene.collection.objects:
                bpy.context.scene.collection.objects.link(o)
        bpy.context.view_layer.update()   # dosyadan gelen ebeveyn/çocuk dünya matrisleri değerlendirilsin
    elif yol.lower().endswith((".glb", ".gltf")):
        # glTF köşeleri UV dikişlerinde böler; gerçekçi (MPFB) gövdede giysi türetimi kesintisiz yüzey ister
        bpy.ops.import_scene.gltf(filepath=yol, merge_vertices=bool(t.get("dikis_birlestir")))
    else:
        bpy.ops.wm.usd_import(filepath=yol, import_skeletons=True)
    return [o for o in bpy.data.objects if o not in once]


A = al(t["kiyafet"])
arm = [o for o in A if o.type == "ARMATURE"][0]

if t.get("giysiler") is not None:
    # Faz 3: dönem giysileri gövdenin kendisinden türetilir; kıyafet alanı burada çıplak gövdedir.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import giysi  # noqa: E402
    import ortak  # noqa: E402
    govde_m = max((o for o in A if o.type == "MESH"), key=lambda o: len(o.data.vertices))
    profil = giysi.yuvalari_kur(govde_m, arm)
    MZ = t.get("malzemeler", {})
    giysi.giydir(govde_m, arm, t["giysiler"],
                 lambda ad: ortak.malzeme(ad, MZ[ad]["tur"], MZ[ad]["renk"], MZ[ad].get("tohum", 1), MZ[ad].get("metalik", 0.0)))
    json.dump(profil, open(t["cikti"].replace(".glb", ".yuva.json"), "w"), indent=1)
    t["govde"] = None

parcalar = []
if t.get("govde"):
    parcalar.append((t["govde"], True))
parcalar += [(e, False) for e in t.get("ekler", [])]
for yol, kirp in parcalar:
    yeni = al(yol)
    for o in yeni:
        if o.type != "MESH":
            continue
        if kirp:
            gruplar = {g.index: g.name for g in o.vertex_groups}
            sil = []
            for v in o.data.vertices:
                if not v.groups:
                    sil.append(v.index)
                    continue
                en = max(v.groups, key=lambda g: g.weight)
                if not gruplar.get(en.group, "").startswith(TUT):
                    sil.append(v.index)
            bm = bmesh.new()
            bm.from_mesh(o.data)
            bm.verts.ensure_lookup_table()
            bmesh.ops.delete(bm, geom=[bm.verts[i] for i in sil], context="VERTS")
            bm.to_mesh(o.data)
            bm.free()
        mw = o.matrix_world.copy()
        o.parent = arm
        o.matrix_world = mw
        for m in o.modifiers:
            if m.type == "ARMATURE":
                m.object = arm
    for o in yeni:
        if o.type != "MESH" and o.name in bpy.data.objects:
            bpy.data.objects.remove(o, do_unlink=True)

# Kıyafetin kendi animasyonları (varsa) atılır; yalnızca evrensel kütüphaneden istenenler kalır.
istenen = set(t.get("animasyonlar", []))
if t.get("animasyon_fbx") and istenen:
    for a in list(bpy.data.actions):
        bpy.data.actions.remove(a)
    once = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=t["animasyon_fbx"], automatic_bone_orientation=False)
    yeni = [o for o in bpy.data.objects if o not in once]
    arm.animation_data_create()
    for a in sorted(bpy.data.actions, key=lambda a: a.name):
        ad = a.name.split("|")[-1]
        if ad in istenen:
            a.name = ad
            a.use_fake_user = True
            tr = arm.animation_data.nla_tracks.new()
            tr.name = ad
            tr.strips.new(ad, int(a.frame_range[0]), a)
        else:
            bpy.data.actions.remove(a)
    for o in yeni:
        bpy.data.objects.remove(o, do_unlink=True)

if t.get("renk"):
    r, g, b = t["renk"]
    for m in bpy.data.materials:
        if m.use_nodes:
            for n in m.node_tree.nodes:
                if n.type == "BSDF_PRINCIPLED":
                    girdi = n.inputs["Base Color"]
                    if girdi.is_linked:
                        kaynak = girdi.links[0].from_socket
                        carp = m.node_tree.nodes.new("ShaderNodeMix")
                        carp.data_type = "RGBA"
                        carp.blend_type = "MULTIPLY"
                        carp.inputs["Factor"].default_value = 1.0
                        m.node_tree.links.new(kaynak, carp.inputs["A"])
                        carp.inputs["B"].default_value = (r, g, b, 1)
                        m.node_tree.links.new(carp.outputs["Result"], girdi)
                    else:
                        c = girdi.default_value
                        girdi.default_value = (c[0] * r, c[1] * g, c[2] * b, c[3])

sinir = int(t.get("doku_siniri", 1024))
for img in bpy.data.images:
    if img.size[0] > sinir or img.size[1] > sinir:
        o = sinir / max(img.size)
        img.scale(max(1, int(img.size[0] * o)), max(1, int(img.size[1] * o)))
# Hiçbir malzemenin kullanmadığı dokular dışa aktarılmasın
bpy.data.orphans_purge(do_recursive=True)

bpy.ops.export_scene.gltf(
    filepath=t["cikti"], export_format="GLB", export_animations=bool(istenen),
    export_animation_mode="NLA_TRACKS", export_image_format=t.get("doku_bicimi", "WEBP"), export_yup=True,
)
print("YAZILDI", t["cikti"])
