"""Mini Dünya 3D karakterleri (Blender/bpy). Oyuncak figür tarzı: basit şekiller + yumuşatma + parlak vernik.
Her karakter yerel orijinde (0,0,0) kurulur; kök (root) boşluğu taşınır/ölçeklenir. Eklemler: hips, chest, head,
arm[-1/1], leg[-1/1], mouth, lids, brows. Renkler 2D karakterlerle aynıdır."""
import math

import bpy
from mathutils import Euler, Vector

_MATS = {}


def _lin(c):
    return tuple(((x + 0.055) / 1.055) ** 2.4 if x > 0.04045 else x / 12.92 for x in c)


def _hex(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def mat(name, col, rough=0.45, sss=0.0, metal=0.0, coat=0.0, emis=0.0):
    """col: ekranda görünen (sRGB) renk, 0-1 üçlü ya da hex."""
    if name in _MATS:
        return _MATS[name]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']
    lc = _lin(_hex(col) if isinstance(col, str) else col)
    b.inputs['Base Color'].default_value = (*lc, 1)
    b.inputs['Roughness'].default_value = rough
    b.inputs['Metallic'].default_value = metal
    if sss:
        b.inputs['Subsurface Weight'].default_value = sss
        b.inputs['Subsurface Radius'].default_value = (1.0, 0.45, 0.3)
        b.inputs['Subsurface Scale'].default_value = 0.04
    if coat:
        b.inputs['Coat Weight'].default_value = coat
        b.inputs['Coat Roughness'].default_value = 0.08
    if emis:
        b.inputs['Emission Color'].default_value = (*lc, 1)
        b.inputs['Emission Strength'].default_value = emis
    _MATS[name] = m
    return m


def _finish(o, m, sub, parent):
    if m:
        o.data.materials.append(m)
    if sub:
        md = o.modifiers.new('sub', 'SUBSURF')
        md.levels = md.render_levels = sub
    bpy.ops.object.shade_smooth()
    if parent:
        bpy.context.view_layer.update()
        mw = o.matrix_world.copy()
        o.parent = parent
        o.matrix_world = mw
    return o


def add(prim, loc, scale=(1, 1, 1), rot=(0, 0, 0), m=None, sub=2, parent=None, **kw):
    getattr(bpy.ops.mesh, 'primitive_' + prim + '_add')(location=loc, rotation=rot, **kw)
    o = bpy.context.object
    o.scale = scale
    return _finish(o, m, sub, parent)


def capsule(a, b, r, m, parent=None, r2=None):
    a, b = Vector(a), Vector(b)
    d = b - a
    r2 = r2 or r
    bpy.ops.mesh.primitive_cone_add(location=(a + b) / 2, vertices=24, radius1=r, radius2=r2, depth=d.length)
    o = bpy.context.object
    o.rotation_mode = 'QUATERNION'
    o.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(d)
    _finish(o, m, 0, parent)
    add('uv_sphere', a, (r, r, r), m=m, sub=0, parent=parent, segments=24, ring_count=12)
    add('uv_sphere', b, (r2, r2, r2), m=m, sub=0, parent=parent, segments=24, ring_count=12)


def pivot(name, loc, parent):
    e = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(e)
    e.location = loc
    if parent:
        bpy.context.view_layer.update()
        mw = e.matrix_world.copy()
        e.parent = parent
        e.matrix_world = mw
    return e


SKIN = (0.95, 0.76, 0.60)
DARK = (0.05, 0.03, 0.03)
WHITE = (0.93, 0.93, 0.93)


class Figure:
    """Ortak insan figürü. P: oran sözlüğü."""

    def __init__(self, name, P):
        self.name, self.P = name, P
        self.root = pivot(name + '_root', (0, 0, 0), None)
        self.hips = pivot(name + '_hips', (0, 0, P['hip']), self.root)
        self.chest = pivot(name + '_chest', (0, 0, P['hip'] + 0.2), self.hips)
        self.head = pivot(name + '_head', (0, 0, P['neck']), self.chest)
        self.arm = {s: pivot(f'{name}_arm{s}', (s * P['sh_x'], 0, P['sh_z']), self.chest) for s in (-1, 1)}
        self.leg = {s: pivot(f'{name}_leg{s}', (s * P['leg_x'], 0, P['hip'] - 0.06), self.hips) for s in (-1, 1)}
        self.lids, self.brows = [], []
        self.mouth = None
        self.base_rz = 0.0

    # ------------------------------------------------------------------ ortak parçalar
    def legs(self, pants, boots, r=0.085):
        P = self.P
        for s in (-1, 1):
            L = self.leg[s]
            capsule((s * P['leg_x'], 0, 0.2), (s * P['leg_x'], 0, P['hip'] - 0.08), r, mat(self.name + 'pnt', pants, 0.7), L)
            add('uv_sphere', (s * P['leg_x'], -0.05, 0.085), (r * 1.5, r * 2.2, r * 1.05), m=mat(self.name + 'bot', boots, 0.3, coat=0.7), parent=L)

    def arms(self, sleeve, r=0.075, length=0.44):
        P = self.P
        skin = mat('ten', SKIN, 0.5, sss=0.3)
        for s in (-1, 1):
            A = self.arm[s]
            a = Vector((s * P['sh_x'], 0, P['sh_z']))
            b = a + Vector((s * 0.1, -0.02, -length))
            capsule(a, b, r, mat(self.name + 'kol', sleeve, 0.45, coat=0.3), A, r2=r * 0.9)
            add('uv_sphere', b + Vector((s * 0.01, -0.01, -0.07)), (r * 1.0, r * 0.95, r * 1.05), m=skin, parent=A)

    def face(self, hz, hr, iris, eye_gap=0.15, eye_s=1.0, lashes=False, brow_col=(0.2, 0.12, 0.08)):
        H = self.head
        skin = mat('ten', SKIN, 0.5, sss=0.3)
        white = mat('beyaz', WHITE, 0.12, coat=1.0)
        iri = mat(self.name + 'iris', iris, 0.15, coat=1.0)
        dark = mat('koyu', DARK, 0.25, coat=1.0)
        fy = -hr[1] * 0.88
        for s in (-1, 1):
            e = Vector((s * eye_gap, fy, hz))
            k = eye_s
            add('uv_sphere', e, (0.1 * k, 0.06 * k, 0.12 * k), m=white, parent=H)
            add('uv_sphere', e + Vector((0, -0.045 * k, -0.012)), (0.062 * k, 0.03 * k, 0.072 * k), m=iri, parent=H)
            add('uv_sphere', e + Vector((0, -0.066 * k, -0.012)), (0.033 * k, 0.015 * k, 0.04 * k), m=dark, parent=H)
            add('uv_sphere', e + Vector((0.025 * k, -0.08 * k, 0.03 * k)), (0.015 * k, 0.01, 0.015 * k), m=white, sub=0, parent=H)
            lid = pivot(f'{self.name}_lid{s}', e + Vector((0, 0, 0.125 * k)), H)
            add('uv_sphere', e + Vector((0, -0.006, 0)), (0.108 * k, 0.068 * k, 0.128 * k), m=skin, parent=lid)
            lid.scale.z = 0.02
            self.lids.append(lid)
            bw = pivot(f'{self.name}_brow{s}', e + Vector((0, -0.03, 0.17 * k)), H)
            capsule(e + Vector((-0.07 * k, -0.03, 0.17 * k)), e + Vector((0.07 * k, -0.03, 0.185 * k)), 0.019, mat(self.name + 'kas', brow_col, 0.5), bw)
            self.brows.append((s, bw))
            if lashes:
                capsule(e + Vector((s * 0.09 * k, -0.03, 0.08 * k)), e + Vector((s * 0.13 * k, -0.03, 0.11 * k)), 0.012, dark, H)
        mz = hz - hr[2] * 0.5
        self.mouth = pivot(self.name + '_mouth', (0, fy - 0.02, mz), H)
        add('uv_sphere', (0, fy - 0.02, mz), (0.07, 0.03, 0.04), m=mat('agiz', (0.40, 0.10, 0.10), 0.5), parent=self.mouth)
        add('uv_sphere', (0, fy - 0.045, hz - 0.06), (0.05, 0.045, 0.055), m=skin, parent=H)  # burun
        bl = mat('yanak', (1.0, 0.60, 0.55), 0.6)
        for s in (-1, 1):
            add('uv_sphere', (s * hr[0] * 0.64, fy + 0.06, mz + 0.05), (0.065, 0.02, 0.04), m=bl, parent=H)

    # ------------------------------------------------------------------ poz
    def pose(self, x, z, st, t, U):
        P = self.P
        self.root.location = (x / U, 0, z / U)
        walk = getattr(st, 'walk', 0.0)
        cyc = math.sin(t * 2 * math.pi * 1.9)
        shake = getattr(st, 'shake', 0.0)
        crouch = getattr(st, 'crouch', 0.0)
        self.root.location.x += 0.02 * shake * math.sin(t * 70)
        self.root.location.z += abs(cyc) * 0.05 * walk
        self.root.rotation_euler = Euler((0, 0, self.base_rz + math.radians(18) * getattr(st, 'face_dir', 1.0) * (0.4 + 0.6 * walk)))
        sq = getattr(st, 'sq', 1.0)
        self.hips.scale = (1 / math.sqrt(sq), 1 / math.sqrt(sq), sq)
        self.hips.location.z = P['hip'] - 0.18 * crouch
        for s in (-1, 1):
            self.leg[s].rotation_euler = Euler((s * cyc * 0.55 * walk + (0.5 * crouch if s else 0), 0, 0))
            point = getattr(st, 'point', 0.0) if s == (1 if getattr(st, 'face_dir', 1.0) >= 0 else -1) else 0.0
            talking = getattr(st, 'talking', False)
            mo_ = getattr(st, 'mo', 0.0)
            gest = (0.55 * math.sin(t * 4.2 + s * 1.3) + 0.25) * (1 if talking else 0) * min(1.0, 0.4 + mo_)
            if point:
                self.arm[s].rotation_euler = Euler((math.radians(-85) * point, 0, s * math.radians(25) * point))
            else:
                self.arm[s].rotation_euler = Euler((-s * cyc * 0.6 * walk + 0.05 * math.sin(t * 1.7 + s) - gest, 0,
                                                    s * (math.radians(8) + 0.3 * shake + 0.35 * abs(gest))))
        talking = getattr(st, 'talking', False)
        tk = 1.0 if talking else 0.0
        self.chest.rotation_euler = Euler((0.06 * walk + 0.25 * crouch + 0.08 * tk, 0.05 * tk * math.sin(t * 2.3),
                                           0.05 * math.sin(t * 1.3) + 0.08 * cyc * walk + 0.1 * tk * math.sin(t * 1.9)))
        lx, ly = getattr(st, 'look', (0.0, 0.0))
        mo = getattr(st, 'mo', 0.0)
        self.head.rotation_euler = Euler((-0.1 * ly + 0.12 * tk * math.sin(t * 6.5) - 0.03,
                                          0.04 * math.sin(t * 1.1) + 0.08 * tk * math.sin(t * 3.1), lx * 0.5))
        emo = getattr(st, 'emotion', 'normal')
        if self.mouth:
            wide = 1.25 if emo in ('panik', 'saskin') else 1.0
            self.mouth.scale = (wide * (1.0 + 0.2 * mo), 1, 0.3 + 1.8 * mo + (0.5 if emo in ('panik', 'saskin') and mo > 0.05 else 0))
        bl = getattr(st, 'blink', 0.0)
        for lid in self.lids:
            lid.scale.z = max(0.02, bl)
        for s, bw in self.brows:
            up = {'saskin': 0.05, 'panik': 0.045, 'uzgun': 0.0, 'sinirli': -0.02}.get(emo, 0.0)
            ang = {'sinirli': -0.35, 'uzgun': 0.35, 'panik': 0.25}.get(emo, 0.0)
            bw.location.z = bw.get('z0', bw.location.z) if 'z0' in bw else bw.location.z
            if 'z0' not in bw:
                bw['z0'] = bw.location.z
            bw.location.z = bw['z0'] + up
            bw.rotation_euler = Euler((0, -s * ang, 0))


# ---------------------------------------------------------------------- karakterler
def tuna():
    P = dict(hip=0.8, neck=1.62, sh_x=0.34, sh_z=1.42, leg_x=0.13)
    f = Figure('tuna', P)
    f.legs((0.16, 0.22, 0.42), (0.40, 0.22, 0.12))
    jacket = mat('tuna_ceket', (1.0, 0.55, 0.12), 0.42, coat=0.35)
    bpy.ops.mesh.primitive_cone_add(location=(0, 0, 1.08), vertices=32, radius1=0.37, radius2=0.27, depth=0.78)
    o = bpy.context.object
    o.scale = (1, 0.72, 1)
    o.modifiers.new('bev', 'BEVEL').width = 0.08
    o.modifiers['bev'].segments = 3
    _finish(o, jacket, 1, f.chest)
    gold = mat('altin', (0.85, 0.65, 0.30), 0.28, metal=0.95)
    add('torus', (0, 0, 0.9), (1, 0.74, 1.3), m=mat('kemer', (0.30, 0.17, 0.08), 0.4), sub=1, parent=f.chest, major_radius=0.355, minor_radius=0.03)
    add('cube', (0, -0.27, 0.9), (0.06, 0.02, 0.05), m=gold, sub=0, parent=f.chest)
    f.arms((1.0, 0.55, 0.12))
    scarf = mat('tuna_atki', (0.10, 0.70, 0.66), 0.55)
    add('torus', (0, 0, 1.5), (1.0, 0.82, 1.5), m=scarf, sub=2, parent=f.chest, major_radius=0.21, minor_radius=0.072)
    capsule((-0.1, -0.15, 1.47), (-0.38, 0.02, 1.25), 0.055, scarf, f.chest, r2=0.04)
    H = f.head
    add('uv_sphere', (0, 0, 2.0), (0.42, 0.38, 0.43), m=mat('ten', SKIN, 0.5, sss=0.3), parent=H, segments=48, ring_count=24)
    hair = mat('tuna_sac', (0.42, 0.24, 0.13), 0.55)
    add('uv_sphere', (0, 0.05, 2.2), (0.445, 0.41, 0.3), m=hair, parent=H)
    for dx, dz, ry in [(-0.27, 2.4, -0.55), (-0.09, 2.48, -0.18), (0.09, 2.48, 0.18), (0.27, 2.4, 0.55)]:
        add('cone', (dx, 0.06, dz), (0.1, 0.1, 0.17), rot=(0, ry, 0), m=hair, sub=1, parent=H)
    f.face(2.0, (0.42, 0.38, 0.43), (0.18, 0.55, 0.43), brow_col=(0.42, 0.24, 0.13))
    glass = mat('cam', (0.56, 0.89, 0.94), 0.04, metal=0.1, coat=1.0, emis=0.15)
    for s in (-1, 1):
        add('torus', (s * 0.16, -0.33, 2.3), (1, 1, 1), rot=(math.radians(72), 0, 0), m=gold, sub=1, parent=H, major_radius=0.1, minor_radius=0.026)
        add('cylinder', (s * 0.16, -0.335, 2.3), (0.088, 0.088, 0.016), rot=(math.radians(72), 0, 0), m=glass, sub=0, parent=H)
    add('torus', (0, 0.04, 2.27), (1.0, 0.93, 1), rot=(math.radians(-12), 0, 0), m=mat('kayis', (0.18, 0.12, 0.09), 0.5), sub=1, parent=H, major_radius=0.445, minor_radius=0.022)
    return f


def nil():
    P = dict(hip=0.72, neck=1.5, sh_x=0.29, sh_z=1.3, leg_x=0.11)
    f = Figure('nil', P)
    f.legs((0.30, 0.22, 0.18), (0.20, 0.14, 0.10), r=0.075)
    shirt = (0.90, 0.70, 0.22)
    add('cube', (0, 0, 1.0), (0.29, 0.2, 0.36), m=mat('nil_yelek', (0.16, 0.24, 0.45), 0.45, coat=0.3), sub=3, parent=f.chest)
    for k in range(3):
        add('uv_sphere', (0.07, -0.205, 1.18 - k * 0.15), (0.03, 0.015, 0.03), m=mat('nil_dugme', (0.85, 0.70, 0.30), 0.3, metal=0.6), sub=0, parent=f.chest)
    capsule((0, -0.21, 1.33), (0, -0.21, 0.7), 0.035, mat('nil_gomlek', shirt, 0.5), f.chest)
    f.arms(shirt, r=0.068, length=0.4)
    H = f.head
    add('uv_sphere', (0, 0, 1.85), (0.38, 0.35, 0.4), m=mat('ten', SKIN, 0.5, sss=0.3), parent=H, segments=48, ring_count=24)
    hair = mat('nil_sac', (0.12, 0.08, 0.10), 0.45, coat=0.2)
    add('uv_sphere', (0, 0.06, 1.95), (0.43, 0.38, 0.44), m=hair, parent=H)  # küt saç (arka + yanlar)
    add('cube', (0, -0.22, 2.12), (0.36, 0.12, 0.1), m=hair, sub=2, parent=H)  # kahkül
    add('uv_sphere', (0, 0.32, 1.72), (0.13, 0.11, 0.13), m=hair, parent=H)  # topuz
    f.face(1.86, (0.38, 0.35, 0.4), (0.20, 0.30, 0.55), eye_gap=0.14, eye_s=0.92, lashes=True, brow_col=(0.12, 0.08, 0.10))
    rimc = mat('nil_gozluk', (0.25, 0.16, 0.10), 0.3, metal=0.4)
    for s in (-1, 1):
        add('torus', (s * 0.14, -0.37, 1.85), (1, 1, 1), rot=(math.radians(90), 0, 0), m=rimc, sub=1, parent=H, major_radius=0.11, minor_radius=0.014)
    capsule((-0.03, -0.38, 1.86), (0.03, -0.38, 1.86), 0.012, rimc, H)
    return f


def bulut():
    P = dict(hip=0.7, neck=1.48, sh_x=0.4, sh_z=1.28, leg_x=0.16)
    f = Figure('bulut', P)
    f.legs((0.30, 0.26, 0.22), (0.25, 0.16, 0.10), r=0.1)
    add('uv_sphere', (0, 0, 1.0), (0.44, 0.34, 0.46), m=mat('bulut_gomlek', (0.48, 0.32, 0.20), 0.6), parent=f.chest)
    add('cube', (0, -0.27, 0.92), (0.32, 0.12, 0.34), m=mat('bulut_onluk', (0.38, 0.52, 0.28), 0.6), sub=3, parent=f.chest)
    add('cube', (0.1, -0.4, 0.84), (0.1, 0.02, 0.07), m=mat('bulut_cep', (0.30, 0.44, 0.22), 0.6), sub=1, parent=f.chest)
    capsule((0.13, -0.42, 0.86), (0.15, -0.42, 1.0), 0.018, mat('kalem', (0.75, 0.76, 0.80), 0.3, metal=0.7), f.chest)
    f.arms((0.48, 0.32, 0.20), r=0.095, length=0.44)
    H = f.head
    add('uv_sphere', (0, 0, 1.83), (0.43, 0.39, 0.4), m=mat('ten', SKIN, 0.5, sss=0.3), parent=H, segments=48, ring_count=24)
    cap = mat('bulut_bere', (0.82, 0.16, 0.14), 0.7)
    add('uv_sphere', (0, 0.02, 2.04), (0.45, 0.42, 0.27), m=cap, parent=H)
    add('torus', (0, 0.0, 1.98), (1.0, 0.93, 1.6), m=mat('bulut_bere2', (0.65, 0.10, 0.10), 0.7), sub=1, parent=H, major_radius=0.43, minor_radius=0.05)
    f.face(1.82, (0.43, 0.39, 0.4), (0.35, 0.22, 0.10), eye_gap=0.16, brow_col=(0.35, 0.22, 0.12))
    return f


def pire():
    P = dict(hip=0.55, neck=1.12, sh_x=0.25, sh_z=1.0, leg_x=0.1)
    f = Figure('pire', P)
    f.legs((0.20, 0.36, 0.55), (0.80, 0.20, 0.15), r=0.07)
    bpy.ops.mesh.primitive_cone_add(location=(0, 0, 0.8), vertices=32, radius1=0.27, radius2=0.21, depth=0.52)
    o = bpy.context.object
    o.scale = (1, 0.75, 1)
    o.modifiers.new('bev', 'BEVEL').width = 0.06
    o.modifiers['bev'].segments = 3
    _finish(o, mat('pire_ceket', (0.95, 0.80, 0.30), 0.5, coat=0.3), 1, f.chest)
    add('cube', (0, 0.22, 0.85), (0.17, 0.09, 0.2), m=mat('pire_canta', (0.45, 0.30, 0.55), 0.6), sub=2, parent=f.chest)
    f.arms((0.95, 0.80, 0.30), r=0.06, length=0.32)
    H = f.head
    add('uv_sphere', (0, 0, 1.44), (0.37, 0.34, 0.38), m=mat('ten', SKIN, 0.5, sss=0.3), parent=H, segments=48, ring_count=24)
    hair = mat('pire_sac', (0.90, 0.45, 0.15), 0.55)
    add('uv_sphere', (0, 0.05, 1.56), (0.39, 0.36, 0.3), m=hair, parent=H)
    add('uv_sphere', (0.05, 0.0, 1.76), (0.42, 0.38, 0.12), rot=(0, -0.15, 0), m=mat('pire_bere', (0.85, 0.12, 0.12), 0.6), parent=H)
    add('cone', (0.08, 0.0, 1.88), (0.04, 0.04, 0.08), m=mat('pire_bere2', (0.70, 0.08, 0.08), 0.6), sub=1, parent=H)
    f.face(1.45, (0.37, 0.34, 0.38), (0.15, 0.40, 0.25), eye_gap=0.135, eye_s=1.05, brow_col=(0.75, 0.40, 0.15))
    freck = mat('cil', (0.75, 0.45, 0.30), 0.6)
    for s in (-1, 1):
        for k in range(3):
            add('uv_sphere', (s * (0.18 + k * 0.03), -0.32, 1.36 - (k % 2) * 0.02), (0.011, 0.006, 0.011), m=freck, sub=0, parent=H)
    return f


class Benek:
    """Uğur böceği binek: konuşmaz; bacakları yürürken kıpırdar."""

    def __init__(self):
        self.name = 'benek'
        self.root = pivot('benek_root', (0, 0, 0), None)
        self.body = pivot('benek_body', (0, 0, 0.0), self.root)
        red = mat('benek_kirmizi', (0.85, 0.12, 0.10), 0.25, coat=1.0)
        blk = mat('benek_siyah', (0.08, 0.06, 0.07), 0.3, coat=0.8)
        add('uv_sphere', (-0.06, 0, 0.62), (0.78, 0.55, 0.45), m=red, parent=self.body, segments=48, ring_count=24)
        capsule((-0.06, -0.35, 0.98), (-0.06, -0.35, 0.1), 0.012, blk, self.body)
        for sx, sz, r in [(-0.4, 0.75, 0.11), (0.25, 0.8, 0.1), (-0.15, 0.55, 0.09), (0.45, 0.5, 0.09), (-0.55, 0.42, 0.08), (0.05, 0.92, 0.07)]:
            add('uv_sphere', (sx, -0.5, sz), (r, 0.05, r), m=blk, sub=1, parent=self.body)
        self.head = pivot('benek_head', (0.72, 0, 0.42), self.body)
        add('uv_sphere', (0.82, -0.05, 0.42), (0.3, 0.27, 0.27), m=blk, parent=self.head)
        white = mat('beyaz', WHITE, 0.12, coat=1.0)
        dark = mat('koyu', DARK, 0.25, coat=1.0)
        for s in (-1, 1):
            add('uv_sphere', (0.95, -0.2 + s * 0.12, 0.48), (0.08, 0.06, 0.09), m=white, parent=self.head)
            add('uv_sphere', (1.0, -0.25 + s * 0.12, 0.47), (0.04, 0.03, 0.045), m=dark, parent=self.head)
            capsule((0.85, -0.05 + s * 0.1, 0.62), (1.0, -0.1 + s * 0.16, 0.95), 0.014, blk, self.head)
            add('uv_sphere', (1.0, -0.1 + s * 0.16, 0.97), (0.04, 0.04, 0.04), m=blk, parent=self.head)
        self.legs = []
        for k, lx in enumerate((-0.4, 0.0, 0.4)):
            for s in (-1, 1):
                L = pivot(f'benek_leg{k}{s}', (lx, s * 0.3, 0.42), self.body)
                capsule((lx, s * 0.3, 0.42), (lx + 0.1, s * 0.5, 0.02), 0.035, blk, L)
                self.legs.append((k, s, L))
        self.mouth, self.lids = None, []

    def pose(self, x, z, st, t, U):
        self.root.location = (x / U, 0, z / U)
        walk = getattr(st, 'walk', 0.0)
        self.root.rotation_euler = Euler((0, 0, 0 if getattr(st, 'face_dir', 1.0) >= 0 else math.pi))
        self.body.location.z = 0.02 * math.sin(t * 3) + 0.03 * abs(math.sin(t * 12)) * walk
        for k, s, L in self.legs:
            L.rotation_euler = Euler((0, 0.35 * math.sin(t * 12 + k * 2 + (s > 0) * math.pi) * walk, 0))
        lx = getattr(st, 'look', (0.0, 0.0))[0]
        self.head.rotation_euler = Euler((0, 0.05 * math.sin(t * 2), 0.3 * lx))


BUILDERS = {'tuna': tuna, 'nil': nil, 'bulut': bulut, 'pire': pire, 'benek': Benek}
# 2D dünya ile ölçek: 2D yüz yüksekliği / 3D yüz yüksekliği (Tuna: 320 birim ↔ 2.0) → 1 Blender birimi = 160 dünya birimi
U = 160.0
# 2D yüz yüksekliğine eşitlemek için kök ölçeği
SCALE = {'tuna': 1.0, 'nil': 0.88, 'bulut': 0.89, 'pire': 0.85, 'benek': 0.9}
