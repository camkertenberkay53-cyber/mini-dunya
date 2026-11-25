"""Prosedürel gerçekçi ağaç üreteci (kendi kodumuz). Gövde/dallar: sivrilen, eğri, kabuk dokulu borular (Poly Haven
CC0 kabuk PBR'ı, UV gerçek ölçekte). Yaprak/iğne: çift yüzlü alfa kartlar (agac_doku.py'nin CC0 fotoğraflardan
türettiği salkım/dal dokuları); kart normalleri taç merkezinden dışa doğru (yumuşak, hacimli taç gölgesi).

Kullanım: python3 agac_uret.py <is.json>
is.json: {"parcalar": [{id, tur: yaprakli|igne|kuru, boy_m, tohum, kabuk: {diff,nor,arm}, kart: png, cikti}]}"""
import json
import math
import os
import random
import sys

import bpy  # noqa: I001
import bmesh
from mathutils import Matrix, Quaternion, Vector

IS = json.load(open(sys.argv[-1]))
UP = Vector((0, 0, 1))


def _img(yol, renkli=True):
    im = bpy.data.images.load(yol, check_existing=True)
    if not renkli:
        im.colorspace_settings.name = "Non-Color"
    return im


def kabuk_malzeme(k, ad):
    m = bpy.data.materials.new(ad)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    t = nt.nodes.new("ShaderNodeTexImage")
    t.image = _img(k["diff"])
    nt.links.new(t.outputs["Color"], b.inputs["Base Color"])
    n = nt.nodes.new("ShaderNodeTexImage")
    n.image = _img(k["nor"], False)
    nm = nt.nodes.new("ShaderNodeNormalMap")
    nt.links.new(n.outputs["Color"], nm.inputs["Color"])
    nt.links.new(nm.outputs["Normal"], b.inputs["Normal"])
    a = nt.nodes.new("ShaderNodeTexImage")
    a.image = _img(k["arm"], False)
    sep = nt.nodes.new("ShaderNodeSeparateColor")
    nt.links.new(a.outputs["Color"], sep.inputs["Color"])
    nt.links.new(sep.outputs["Green"], b.inputs["Roughness"])
    nt.links.new(sep.outputs["Blue"], b.inputs["Metallic"])
    return m


def kart_malzeme(png, ad):
    m = bpy.data.materials.new(ad)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    t = nt.nodes.new("ShaderNodeTexImage")
    t.image = _img(png)
    nt.links.new(t.outputs["Color"], b.inputs["Base Color"])
    r = nt.nodes.new("ShaderNodeMath")   # glTF dışa aktarıcı: Round → alphaMode MASK (kesme 0.5)
    r.operation = "ROUND"
    nt.links.new(t.outputs["Alpha"], r.inputs[0])
    nt.links.new(r.outputs[0], b.inputs["Alpha"])
    b.inputs["Roughness"].default_value = 0.75
    m.use_backface_culling = False
    return m


class Agac:
    def __init__(self, p):
        self.p = p
        self.r = random.Random(int(p["tohum"]))
        self.bm = bmesh.new()
        self.uv = self.bm.loops.layers.uv.new("UVMap")
        self.kart_bm = bmesh.new()
        self.kuv = self.kart_bm.loops.layers.uv.new("UVMap")
        self.kart_normal = {}
        self.uclar = []       # (nokta, yön, yarıçap, seviye) — yaprak kartları için

    def boru(self, noktalar, yaricaplar, kenar):
        """Noktalar boyunca halkalar; UV: u = çevre (m), v = uzunluk (m) → kabuk gerçek ölçekte tekrar eder."""
        halkalar = []
        v_acc = 0.0
        onceki_n = None
        for i, (p, rr) in enumerate(zip(noktalar, yaricaplar)):
            d = (noktalar[min(i + 1, len(noktalar) - 1)] - noktalar[max(i - 1, 0)]).normalized()
            n = onceki_n if onceki_n is not None else d.orthogonal().normalized()
            n = (n - d * n.dot(d)).normalized()
            onceki_n = n
            bn = d.cross(n)
            if i > 0:
                v_acc += (p - noktalar[i - 1]).length
            halka = []
            for j in range(kenar + 1):
                a = 2 * math.pi * j / kenar
                halka.append((self.bm.verts.new(p + (n * math.cos(a) + bn * math.sin(a)) * rr), j / kenar * 2 * math.pi * rr, v_acc))
            halkalar.append(halka)
        for h0, h1 in zip(halkalar, halkalar[1:]):
            for j in range(kenar):
                f = self.bm.faces.new((h0[j][0], h0[j + 1][0], h1[j + 1][0], h1[j][0]))
                for lp, (v, u, w) in zip(f.loops, (h0[j], h0[j + 1], h1[j + 1], h1[j])):
                    lp[self.uv].uv = (u / 0.9, w / 0.9)   # kabuk dokusu ~0.9 m karo

    def dal(self, bas, yon, uzun, r0, seviye, egilim):
        r = self.r
        p = self.p
        seg = max(3, int(uzun / (0.45 if seviye == 0 else 0.6)))
        pts, rad = [bas], [r0]
        d = yon.normalized()
        for i in range(seg):
            g = Vector((r.uniform(-1, 1), r.uniform(-1, 1), r.uniform(-1, 1))) * (0.12 if seviye == 0 else 0.28)
            d = (d + g + UP * egilim).normalized()
            pts.append(pts[-1] + d * (uzun / seg))
            t = (i + 1) / seg
            rad.append(max(0.006, r0 * (1 - t * (0.75 if seviye < p["seviye"] else 0.9))))
        kenar = 9 if seviye == 0 else (6 if seviye == 1 else 4)
        self.boru(pts, rad, kenar)
        if seviye >= p["seviye"]:
            self.uclar.append((pts[-1], d, r0, seviye))
            for k in range(1, len(pts)):
                if r.random() < 0.55:
                    self.uclar.append((pts[k], (pts[k] - pts[k - 1]).normalized(), rad[k], seviye))
            return
        # çocuk dallar (filotaksi 137.5°)
        sayi = p["dal_sayisi"][seviye]
        az = r.uniform(0, 360)
        for k in range(sayi):
            t = p["dal_bas"][seviye] + (1 - p["dal_bas"][seviye]) * (k + r.random() * 0.6) / sayi
            idx = min(len(pts) - 2, int(t * (len(pts) - 1)))
            q = pts[idx].lerp(pts[idx + 1], t * (len(pts) - 1) - idx)
            ana = (pts[idx + 1] - pts[idx]).normalized()
            az += 137.5 + r.uniform(-15, 15)
            aci = math.radians(r.uniform(*p["dal_aci"][seviye]))
            dik = ana.orthogonal().normalized()
            dik.rotate(Quaternion(ana, math.radians(az)))
            yeni = (ana * math.cos(aci) + dik * math.sin(aci)).normalized()
            boy = uzun * r.uniform(*p["dal_oran"][seviye]) * (1.15 - 0.55 * t if seviye == 0 else 1.0)
            rr = max(0.012, rad[idx] * r.uniform(0.45, 0.65))
            self.dal(q, yeni, boy, rr, seviye + 1, p["egilim"][seviye + 1])

    def kart(self, merkez, yon, gen, boy, taç_merkez, dondur=0.0, uv=((0, 0), (1, 0), (1, 1), (0, 1))):
        """yon boyunca uzanan dikdörtgen kart; dönme yon ekseni etrafında."""
        yon = yon.normalized()
        yan = yon.orthogonal().normalized()
        yan.rotate(Quaternion(yon, dondur))
        a = merkez - yan * gen / 2
        b = merkez + yan * gen / 2
        ks = [a, b, b + yon * boy, a + yon * boy]
        vs = [self.kart_bm.verts.new(k) for k in ks]
        f = self.kart_bm.faces.new(vs)
        for lp, t in zip(f.loops, uv):
            lp[self.kuv].uv = t
        for v in vs:   # taç normali: dışa doğru (küresel) + biraz yüz normali
            dis = (v.co - taç_merkez)
            dis.z *= 0.6
            self.kart_normal[v] = dis.normalized()

    def yapraklar(self, kart_boy):
        r = self.r
        if not self.uclar:
            return
        tm = sum((u[0] for u in self.uclar), Vector()) / len(self.uclar)
        for p_, d, rr, sev in self.uclar:
            for _ in range(self.p.get("kart_basina", 2)):
                s = kart_boy * r.uniform(0.75, 1.2)
                yon = (d + Vector((r.uniform(-0.7, 0.7), r.uniform(-0.7, 0.7), r.uniform(-0.3, 0.6)))).normalized()
                self.kart(p_ - yon * s * 0.35, yon, s, s, tm, r.uniform(0, math.pi))

    def igne(self):
        """Kozalaklı: düz gövde, kat kat yatay dallar; her dala iki çapraz iğne kartı."""
        r = self.r
        H = self.p["boy_m"]
        self.boru([Vector((0, 0, z)) for z in [H * i / 12 for i in range(13)]],
                  [max(0.02, 0.22 * (1 - i / 12) ** 1.1) for i in range(13)], 9)
        tm = Vector((0, 0, H * 0.55))
        z = H * 0.18
        az = r.uniform(0, 360)
        while z < H * 0.97:
            t = (z - H * 0.18) / (H * 0.82)
            L = (1 - t) ** 0.9 * H * 0.33 + 0.35
            for k in range(r.randint(4, 6)):
                az += 137.5
                a = math.radians(az)
                yon = Vector((math.cos(a), math.sin(a), -math.radians(r.uniform(8, 25)))).normalized()
                bas = Vector((0, 0, z))
                rr = max(0.01, 0.05 * (1 - t))
                uc = bas + yon * L
                self.boru([bas, bas.lerp(uc, 0.5) + Vector((0, 0, -0.06 * L)), uc], [rr, rr * 0.6, 0.006], 4)
                for don in (0.0, math.pi / 2):
                    self.kart(bas + yon * 0.1, yon + Vector((0, 0, -0.08)), L * 0.62, L, tm, don,
                              uv=((0, 0.02), (0, 0.98), (1, 0.98), (1, 0.02)))
            z += r.uniform(0.32, 0.5)
        tepe = Vector((0, 0, H))
        for don in (0.0, math.pi / 2):
            self.kart(tepe - Vector((0, 0, 1.2)), UP, 0.9, 1.5, tm, don, uv=((0, 0.02), (0, 0.98), (1, 0.98), (1, 0.02)))

    def nesneler(self, kabuk, kart_m):
        me = bpy.data.meshes.new(self.p["id"] + "_govde")
        self.bm.to_mesh(me)
        ob = bpy.data.objects.new(self.p["id"] + "_govde", me)
        bpy.context.scene.collection.objects.link(ob)
        me.materials.append(kabuk)
        for f in me.polygons:
            f.use_smooth = True
        out = [ob]
        if kart_m and len(self.kart_bm.faces):
            km = bpy.data.meshes.new(self.p["id"] + "_yaprak")
            normaller = [self.kart_normal[v] for v in self.kart_bm.verts]
            self.kart_bm.to_mesh(km)
            km.normals_split_custom_set_from_vertices([tuple(n) for n in normaller])
            ko = bpy.data.objects.new(self.p["id"] + "_yaprak", km)
            bpy.context.scene.collection.objects.link(ko)
            km.materials.append(kart_m)
            out.append(ko)
        return out


def uret(p):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    a = Agac(p)
    kabuk = kabuk_malzeme(p["kabuk"], p["id"] + "_kabuk")
    kart_m = kart_malzeme(p["kart"], p["id"] + "_yaprak") if p["tur"] != "kuru" else None
    if p["tur"] == "igne":
        a.igne()
    else:
        H = p["boy_m"]
        a.dal(Vector((0, 0, -0.2)), Vector((a.r.uniform(-0.05, 0.05), a.r.uniform(-0.05, 0.05), 1)), H * 0.62, H * 0.022, 0, 0.05)
        if p["tur"] == "yaprakli":
            a.yapraklar(p["kart_m"])
    obs = a.nesneler(kabuk, kart_m)
    bm = bmesh.new()
    for o in obs:   # ölçüm
        bm.from_mesh(o.data)
    xs, ys, zs = ([v.co[i] for v in bm.verts] for i in range(3))
    s = {"ucgen": sum(len(f.verts) - 2 for f in bm.faces), "kose": len(bm.verts), "yalniz_kose": 0, "bozuk_yuz": 0,
         "boyut_m": [round(max(xs) - min(xs), 3), round(max(ys) - min(ys), 3), round(max(zs) - min(zs), 3)],
         "malzeme": len(bpy.data.materials), "uv": 1, "doku": [],
         "kart": len(a.kart_bm.faces)}
    bm.free()
    for im in bpy.data.images:   # doku sınırı: kabuk 512, kart 1024 (dosya/bellek)
        sinir = 1024 if im.name.endswith(".png") else int(p.get("kabuk_max", 512))
        if im.size[0] > sinir:
            im.scale(sinir, int(im.size[1] * sinir / im.size[0]))
    bpy.ops.export_scene.gltf(filepath=p["cikti"], export_format="GLB", export_image_format="WEBP", export_yup=True,
                              use_selection=False)
    s["doku"] = sorted({max(i.size) for i in bpy.data.images if i.size[0] > 0})
    s["bayt"] = os.path.getsize(p["cikti"])
    json.dump(s, open(p["cikti"].replace(".glb", ".olc.json"), "w"))
    print("URETILDI", p["id"], s["ucgen"], s["bayt"], s["boyut_m"])


for p in IS["parcalar"]:
    uret(p)
