"""Mini Dünya 3D (Blender/bpy) deneme motoru.
Karakterler basit şekillerden oyuncak tarzında kurulur; her parça bir eklem boşluğuna (empty) bağlıdır,
animasyon Python'dan eklem dönüşleriyle verilir (iskelet/rig gerekmez). Arka plan şeffaf render edilir,
boyalı arka plan ve kamera hareketi 2D tarafta birleştirilir."""
import bpy, math, sys, time
from mathutils import Vector, Euler

MATS = {}


def srgb(h):
    h = h.lstrip('#'); c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(((x + 0.055) / 1.055) ** 2.4 if x > 0.04045 else x / 12.92 for x in c)


def mat(name, hexcol, rough=0.45, sss=0.0, metal=0.0, coat=0.0, emis=0.0):
    if name in MATS:
        return MATS[name]
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']
    col = srgb(hexcol) if isinstance(hexcol, str) else hexcol
    b.inputs['Base Color'].default_value = (*col, 1)
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
        b.inputs['Emission Color'].default_value = (*col, 1)
        b.inputs['Emission Strength'].default_value = emis
    MATS[name] = m
    return m


def empty(name, loc, parent=None):
    o = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(o)
    o.location = loc
    if parent:
        o.parent = parent
        o.location = Vector(loc) - parent.matrix_world.translation if False else loc
    return o


def _finish(o, m, sub, parent):
    if m:
        o.data.materials.append(m)
    if sub:
        md = o.modifiers.new('sub', 'SUBSURF'); md.levels = md.render_levels = sub
    bpy.ops.object.shade_smooth()
    if parent:
        mw = o.matrix_world.copy()
        o.parent = parent
        o.matrix_world = mw
    return o


def add(prim, loc, scale=(1, 1, 1), rot=(0, 0, 0), m=None, sub=2, parent=None, **kw):
    getattr(bpy.ops.mesh, 'primitive_' + prim + '_add')(location=loc, rotation=rot, **kw)
    o = bpy.context.object; o.scale = scale
    bpy.context.view_layer.update()
    return _finish(o, m, sub, parent)


def capsule(a, b, r, m, parent=None, r2=None):
    a, b = Vector(a), Vector(b); d = b - a
    bpy.ops.mesh.primitive_cone_add(location=(a + b) / 2, vertices=24, radius1=r, radius2=r2 or r, depth=d.length)
    o = bpy.context.object
    o.rotation_mode = 'QUATERNION'; o.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(d)
    bpy.context.view_layer.update()
    _finish(o, m, 0, parent)
    add('uv_sphere', a, (r, r, r), m=m, sub=0, parent=parent, segments=24, ring_count=12)
    add('uv_sphere', b, (r2 or r, r2 or r, r2 or r), m=m, sub=0, parent=parent, segments=24, ring_count=12)


def pivot(name, loc, parent):
    e = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(e)
    e.location = loc
    bpy.context.view_layer.update()
    if parent:
        mw = e.matrix_world.copy(); e.parent = parent; e.matrix_world = mw
    return e


class Char:
    """Eklemler: root (konum), hips, chest, head, arm_l/r, leg_l/r, mouth, lids."""

    def __init__(self, x=0.0, name='tuna'):
        self.name, self.x0 = name, x
        self.root = pivot(name + '_root', (x, 0, 0), None)
        self.hips = pivot(name + '_hips', (x, 0, 0.8), self.root)
        self.chest = pivot(name + '_chest', (x, 0, 1.0), self.hips)
        self.head = pivot(name + '_head', (x, 0, 1.62), self.chest)
        self.arm = {s: pivot(f'{name}_arm{s}', (x + s * 0.34, 0, 1.42), self.chest) for s in (-1, 1)}
        self.leg = {s: pivot(f'{name}_leg{s}', (x + s * 0.13, 0, 0.74), self.hips) for s in (-1, 1)}
        self.mouth = None
        self.lids = []

    # ------------------------------------------------------------------ poz
    def pose(self, t, walk=0.0, talk=0.0, blink=0.0, look=0.0, x=None, point=0.0):
        sw = math.sin(t * 2 * math.pi * 1.8) * walk
        self.root.location.x = self.x0 if x is None else x
        self.root.location.z = abs(math.sin(t * 2 * math.pi * 1.8)) * 0.06 * walk + 0.015 * math.sin(t * 2.1)
        for s in (-1, 1):
            self.leg[s].rotation_euler = Euler((s * sw * 0.55, 0, 0))
            base = math.radians(8) * s
            if s == 1 and point:
                self.arm[s].rotation_euler = Euler((math.radians(-80) * point, 0, base + math.radians(30) * point))
            else:
                self.arm[s].rotation_euler = Euler((-s * sw * 0.6 + 0.05 * math.sin(t * 1.7 + s), 0, base))
        self.chest.rotation_euler = Euler((0.03 * walk, 0, 0.04 * math.sin(t * 1.3) + 0.08 * sw))
        self.head.rotation_euler = Euler((0.06 * talk * math.sin(t * 9) - 0.03, 0.05 * math.sin(t * 1.1), look * 0.45))
        if self.mouth:
            self.mouth.scale.z = 0.25 + 1.6 * talk
        for lid in self.lids:
            lid.scale.z = max(0.02, blink)


def tuna(x=0.0):
    c = Char(x, 'tuna')
    skin = mat('ten', 'f2bd94', 0.5, sss=0.3)
    hair = mat('sac', '6e3a1e', 0.55)
    jacket = mat('ceket', 'ff7a00', 0.42, coat=0.35)
    pants = mat('pantolon', '24356e', 0.7)
    boots = mat('bot', '5e3219', 0.3, coat=0.7)
    scarf = mat('atki', '13b5a8', 0.55)
    belt = mat('kemer', '4a2a12', 0.4)
    white = mat('beyaz', (0.85, 0.85, 0.85), 0.12, coat=1.0)
    iris = mat('iris', '2f8a6e', 0.15, coat=1.0)
    dark = mat('koyu', (0.01, 0.006, 0.006), 0.25, coat=1.0)
    mouthm = mat('agiz', '5a1414', 0.5)
    glass = mat('cam', '8fe3f0', 0.04, metal=0.1, coat=1.0, emis=0.15)
    rim = mat('cerceve', 'd4a24c', 0.28, metal=0.95)
    blush = mat('yanak', 'ff7f73', 0.6)
    # bacaklar + botlar (bacak eklemine bağlı)
    for s in (-1, 1):
        L = c.leg[s]
        capsule((x + s * 0.13, 0, 0.2), (x + s * 0.13, 0, 0.7), 0.088, pants, L)
        add('uv_sphere', (x + s * 0.13, -0.05, 0.09), (0.13, 0.19, 0.09), m=boots, parent=L)
    # ceket: aşağı doğru genişleyen gövde
    bpy.ops.mesh.primitive_cone_add(location=(x, 0, 1.08), vertices=32, radius1=0.37, radius2=0.27, depth=0.78)
    o = bpy.context.object; o.scale = (1, 0.72, 1)
    o.modifiers.new('bev', 'BEVEL').width = 0.08
    o.modifiers['bev'].segments = 3
    bpy.context.view_layer.update()
    _finish(o, jacket, 1, c.chest)
    add('torus', (x, 0, 0.9), (1, 0.74, 1.3), m=belt, sub=1, parent=c.chest, major_radius=0.355, minor_radius=0.03)
    add('cube', (x, -0.27, 0.9), (0.06, 0.02, 0.05), m=rim, sub=0, parent=c.chest)  # toka
    # kollar (omuz eklemine bağlı) + eller
    for s in (-1, 1):
        A = c.arm[s]
        capsule((x + s * 0.34, 0, 1.42), (x + s * 0.44, -0.02, 1.0), 0.078, jacket, A, r2=0.07)
        add('uv_sphere', (x + s * 0.455, -0.03, 0.92), (0.075, 0.07, 0.08), m=skin, parent=A)
    # atkı
    add('torus', (x, 0, 1.5), (1.0, 0.82, 1.5), m=scarf, sub=2, parent=c.chest, major_radius=0.21, minor_radius=0.072)
    capsule((x - 0.1, -0.15, 1.47), (x - 0.38, 0.02, 1.25), 0.055, scarf, c.chest, r2=0.04)
    # baş (baş eklemine bağlı)
    H = c.head
    add('uv_sphere', (x, 0, 2.0), (0.42, 0.38, 0.43), m=skin, parent=H, segments=48, ring_count=24)
    add('uv_sphere', (x, 0.05, 2.2), (0.445, 0.41, 0.3), m=hair, parent=H)
    for dx, dz, ry in [(-0.27, 2.4, -0.55), (-0.09, 2.48, -0.18), (0.09, 2.48, 0.18), (0.27, 2.4, 0.55)]:
        add('cone', (x + dx, 0.06, dz), (0.1, 0.1, 0.17), rot=(0, ry, 0), m=hair, sub=1, parent=H)
    for s in (-1, 1):
        e = Vector((x + s * 0.15, -0.33, 2.0))
        add('uv_sphere', e, (0.105, 0.06, 0.125), m=white, parent=H)
        add('uv_sphere', e + Vector((0, -0.045, -0.012)), (0.064, 0.03, 0.074), m=iris, parent=H)
        add('uv_sphere', e + Vector((0, -0.066, -0.012)), (0.034, 0.015, 0.04), m=dark, parent=H)
        add('uv_sphere', e + Vector((0.026, -0.08, 0.03)), (0.015, 0.01, 0.015), m=white, sub=0, parent=H)
        lid = pivot(f'tuna_lid{s}', e + Vector((0, 0, 0.13)), H)
        add('uv_sphere', e + Vector((0, -0.005, 0.0)), (0.112, 0.068, 0.132), m=skin, parent=lid)
        lid.scale.z = 0.02
        c.lids.append(lid)
        capsule(e + Vector((-0.075, -0.03, 0.17)), e + Vector((0.07, -0.03, 0.19)), 0.02, hair, H)
    c.mouth = pivot('tuna_mouth', (x, -0.37, 1.82), H)
    add('uv_sphere', (x, -0.37, 1.82), (0.075, 0.03, 0.04), m=mouthm, parent=c.mouth)
    for s in (-1, 1):
        add('uv_sphere', (x + s * 0.27, -0.29, 1.87), (0.07, 0.02, 0.045), m=blush, parent=H)
    add('uv_sphere', (x, -0.4, 1.95), (0.055, 0.05, 0.06), m=skin, parent=H)
    # alın gözlüğü + kayış (saçın üstünde)
    for s in (-1, 1):
        add('torus', (x + s * 0.16, -0.33, 2.3), (1, 1, 1), rot=(math.radians(72), 0, 0), m=rim, sub=1, parent=H, major_radius=0.1, minor_radius=0.026)
        add('cylinder', (x + s * 0.16, -0.335, 2.3), (0.088, 0.088, 0.016), rot=(math.radians(72), 0, 0), m=glass, sub=0, parent=H)
    add('torus', (x, 0.04, 2.27), (1.0, 0.93, 1), rot=(math.radians(-12), 0, 0), m=mat('kayis', '2e2018', 0.5), sub=1, parent=H, major_radius=0.445, minor_radius=0.022)
    # lid'ler gözü kapatır: başlangıçta açık (scale.z küçük = kapalı değil): göz kapağı yukarıda dursun
    for lid in c.lids:
        for ch in lid.children:
            ch.hide_render = False
    return c


def setup(W, H, samples=8):
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'; sc.cycles.device = 'CPU'
    sc.cycles.samples = samples; sc.cycles.use_denoising = True; sc.cycles.denoiser = 'OPENIMAGEDENOISE'
    sc.cycles.max_bounces = 3; sc.cycles.diffuse_bounces = 1; sc.cycles.glossy_bounces = 1
    sc.render.use_persistent_data = True
    sc.render.resolution_x, sc.render.resolution_y = W, H
    sc.render.film_transparent = True
    sc.view_settings.view_transform = 'Standard'; sc.view_settings.look = 'None'
    bpy.ops.mesh.primitive_plane_add(size=30, location=(0, 0, 0)); bpy.context.object.is_shadow_catcher = True

    def light(kind, loc, energy, col, size=1.0):
        bpy.ops.object.light_add(type=kind, location=loc); l = bpy.context.object
        l.data.energy = energy; l.data.color = col
        if kind == 'AREA':
            l.data.size = size
        l.rotation_mode = 'QUATERNION'; l.rotation_quaternion = (Vector((0, 0, 1.2)) - Vector(loc)).to_track_quat('-Z', 'Y')
    light('AREA', (2.5, -3.0, 4.0), 650, (1.0, 0.86, 0.68), 2.5)
    light('AREA', (-3.0, -2.5, 2.0), 160, (0.62, 0.72, 1.0), 3.0)
    light('AREA', (0.8, 3.0, 3.0), 700, (1.0, 0.62, 0.32), 1.5)
    w = bpy.data.worlds.new('w'); sc.world = w; w.use_nodes = True
    bg = w.node_tree.nodes['Background']; bg.inputs['Color'].default_value = (0.32, 0.22, 0.15, 1); bg.inputs['Strength'].default_value = 0.5
    bpy.ops.object.camera_add(location=(0.4, -7.5, 1.6)); cam = bpy.context.object; sc.camera = cam
    cam.data.lens = 50
    cam.rotation_mode = 'QUATERNION'; cam.rotation_quaternion = (Vector((0.4, 0, 1.25)) - cam.location).to_track_quat('-Z', 'Y')
    return cam
