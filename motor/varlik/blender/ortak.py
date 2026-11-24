"""Blender içinde paylaşılan yardımcılar: prosedürel malzeme, UV, ağ kurma."""
from __future__ import annotations

import math
import os
import sys

import bpy  # noqa: I001
import bmesh
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import doku  # noqa: E402

_MALZEMELER: dict = {}


def _resim(ad: str, dizi: np.ndarray, renkli: bool) -> bpy.types.Image:
    n = dizi.shape[0]
    if dizi.ndim == 2:
        dizi = np.stack([dizi, dizi, dizi, np.ones_like(dizi)], -1)
    elif dizi.shape[2] == 3:
        dizi = np.concatenate([dizi, np.ones((n, n, 1), np.float32)], -1)
    img = bpy.data.images.new(ad, n, n, alpha=False, float_buffer=False)
    img.colorspace_settings.name = "sRGB" if renkli else "Non-Color"
    img.pixels.foreach_set(dizi[::-1].astype(np.float32).ravel())
    img.pack()
    return img


def malzeme(ad: str, tur: str, renk, tohum: int = 1, metalik: float = 0.0, boyut: int = 512, ikinci_renk=None) -> bpy.types.Material:
    """Prosedürel dokulu PBR malzeme. Aynı ad ikinci kez istenirse aynı malzeme döner (dosya içinde paylaşım)."""
    if ad in _MALZEMELER:
        return _MALZEMELER[ad]
    rgba, rough, nm = doku.uret(tur, renk, tohum, boyut, ikinci_renk)
    m = bpy.data.materials.new(ad)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    t1 = nt.nodes.new("ShaderNodeTexImage")
    t1.image = _resim(ad + "_renk", rgba, True)
    nt.links.new(t1.outputs["Color"], bsdf.inputs["Base Color"])
    # glTF: pürüzlülük G kanalında, metaliklik B kanalında
    mr = np.stack([np.zeros_like(rough), rough, np.full_like(rough, metalik)], -1)
    t2 = nt.nodes.new("ShaderNodeTexImage")
    t2.image = _resim(ad + "_pm", mr[::2, ::2] if boyut > 256 else mr, False)
    sep = nt.nodes.new("ShaderNodeSeparateColor")
    nt.links.new(t2.outputs["Color"], sep.inputs["Color"])
    nt.links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
    nt.links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])
    t3 = nt.nodes.new("ShaderNodeTexImage")
    t3.image = _resim(ad + "_n", nm[::2, ::2] if boyut > 256 else nm, False)
    nmap = nt.nodes.new("ShaderNodeNormalMap")
    nt.links.new(t3.outputs["Color"], nmap.inputs["Color"])
    nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    m.use_backface_culling = False
    _MALZEMELER[ad] = m
    return m


def nesne(ad: str, bm: bmesh.types.BMesh, mat=None) -> bpy.types.Object:
    me = bpy.data.meshes.new(ad)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(ad, me)
    bpy.context.scene.collection.objects.link(o)
    if mat is not None:
        me.materials.append(mat)
    for p in me.polygons:
        p.use_smooth = True
    return o


def torna(profil, dilim: int = 32, uv_olcek=1.0, aci=2 * math.pi, kapali=True) -> bmesh.types.BMesh:
    """Z ekseni etrafında döndürülmüş profil. profil: [(yaricap_x, z), ...] yukarıdan aşağıya.
    yaricap (rx, ry) ikilisi de olabilir (elips kesit). UV: u = açı, v = profil boyu."""
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UVMap")
    satirlar = []
    n = dilim if kapali else dilim + 1
    for r, z in profil:
        rx, ry = (r, r) if not isinstance(r, (tuple, list)) else r
        satir = []
        for i in range(n):
            a = aci * i / dilim
            satir.append(bm.verts.new((rx * math.cos(a), ry * math.sin(a), z)))
        satirlar.append(satir)
    # profil boyunca birikimli uzunluk (v)
    uzun = [0.0]
    for (r0, z0), (r1, z1) in zip(profil, profil[1:]):
        a0 = r0 if not isinstance(r0, (tuple, list)) else r0[0]
        a1 = r1 if not isinstance(r1, (tuple, list)) else r1[0]
        uzun.append(uzun[-1] + math.hypot(a1 - a0, z1 - z0))
    for j in range(len(satirlar) - 1):
        for i in range(dilim):
            i2 = (i + 1) % n if kapali else i + 1
            f = bm.faces.new((satirlar[j][i], satirlar[j][i2], satirlar[j + 1][i2], satirlar[j + 1][i]))
            for lp, (uu, vv) in zip(f.loops, ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1))):
                lp[uv].uv = (uu / dilim * uv_olcek * 2, uzun[vv] * uv_olcek)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def kutu(sx, sy, sz, konum=(0, 0, 0)) -> bmesh.types.BMesh:
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co.x = v.co.x * sx + konum[0]
        v.co.y = v.co.y * sy + konum[1]
        v.co.z = v.co.z * sz + konum[2]
    kutu_uv(bm, 1.0)
    return bm


def kutu_uv(bm, olcek=1.0):
    uv = bm.loops.layers.uv.verify()
    for f in bm.faces:
        n = f.normal
        ax = max(range(3), key=lambda k: abs(n[k]))
        for lp in f.loops:
            c = lp.vert.co
            a, b = [(c.y, c.z), (c.x, c.z), (c.x, c.y)][ax]
            lp[uv].uv = (a * olcek, b * olcek)


def birlestir(nesneler, ad: str) -> bpy.types.Object:
    bpy.ops.object.select_all(action="DESELECT")
    for o in nesneler:
        o.select_set(True)
    bpy.context.view_layer.objects.active = nesneler[0]
    if len(nesneler) > 1:
        bpy.ops.object.join()
    o = bpy.context.view_layer.objects.active
    o.name = ad
    o.data.name = ad
    return o


def sifirla():
    _MALZEMELER.clear()
    bpy.ops.wm.read_factory_settings(use_empty=True)
