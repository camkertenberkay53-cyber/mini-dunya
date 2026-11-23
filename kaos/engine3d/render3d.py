"""3D karakter katmanı: 2D Renderer'ın hesapladığı karakter durumlarını (konum, yürüme, ağız, bakış, duygu...)
yakalar, Blender'da (Cycles, şeffaf arka plan, gölge yakalayıcı) saniyede 12 kare render eder.
Renderer bu katmanı kendi 2D kamerasıyla (yakın/geniş plan, sarsıntı) boyalı arka planın üstüne yerleştirir."""
import math
import os
import time
from functools import lru_cache

import cv2
import numpy as np

FPS3D = 10  # karakter animasyonu saniyede 10 poz (stilize animasyonda yaygın); kamera 30 fps akıcı
R = 0.95         # katman çözünürlüğü: dünya birimi başına piksel
MARGIN_X = 560   # sahne dışına doğru render payı (giriş/çıkış)
TOP = 600        # zeminden yukarı (zıplama + saç)
BOTTOM = 70      # zeminden aşağı (gölge)
C_W = {'tuna': 230, 'nil': 200, 'bulut': 250, 'pire': 180, 'benek': 260}  # yarım genişlik + kol payı
C_H = {'tuna': 470, 'nil': 400, 'bulut': 400, 'pire': 330, 'benek': 230}  # zeminden yükseklik + pay
TILT = 8         # kamera aşağı eğimi (derece): zemin gölgesi görünsün


def _scene_rect(r, si):
    from ..engine.render import GROUND_Y
    xs = [p[0] for p in r.layouts[si].values()]
    dx = [d for (sj, _), mv in r.moves.items() if sj == si for _, d in mv]
    span = sum(abs(d) for d in dx)
    x0 = min(xs) - MARGIN_X - span * 0.5
    x1 = max(xs) + MARGIN_X + span * 0.5
    return x0, GROUND_Y - TOP, x1, GROUND_Y + BOTTOM


class Layer3D:
    def __init__(self, frames):
        self.frames = frames  # {(si, i): (path, x0, y0)}

    @staticmethod
    @lru_cache(6)
    def _load(path):
        a = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if a is None:
            return None
        a = a[..., [2, 1, 0, 3]].astype(np.float32) / 255
        h, w = a.shape[:2]
        ry = np.clip(np.arange(h, dtype=np.float32)[::-1] / 28.0, 0, 1)          # alt kenar (zemin gölgesi) yumuşak biter
        rx = np.clip(np.minimum(np.arange(w), np.arange(w)[::-1]).astype(np.float32) / 10.0, 0, 1)
        a[..., 3] *= ry[:, None] * rx[None, :]
        a[..., :3] *= a[..., 3:4]  # önceden çarpılmış alfa (kenarlarda koyu hale olmaz)
        return a

    def composite(self, f, cam, si, t):
        i = int(t * FPS3D + 1e-6)
        key = (si, i)
        if key not in self.frames:
            ks = [k for k in self.frames if k[0] == si]
            if not ks:
                return f
            key = min(ks, key=lambda k: abs(k[1] - i))
        path, x0, y0 = self.frames[key]
        a = self._load(path)
        if a is None:
            return f
        W, H = cam.W, cam.H
        s = cam.z / R
        M = np.array([[s, 0, (x0 - cam.cx) * cam.z + W / 2 + cam.sx],
                      [0, s, (y0 - cam.cy) * cam.z + H / 2 + cam.sy]], np.float32)
        w = cv2.warpAffine(a, M, (W, H), flags=cv2.INTER_LINEAR if s < 1.3 else cv2.INTER_CUBIC,
                           borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
        al = np.clip(w[..., 3:4], 0, 1)
        return f * (1 - al) + np.clip(w[..., :3], 0, 1)


def _setup_blender(samples):
    import bpy
    from mathutils import Vector
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    sc.cycles.device = 'CPU'
    sc.cycles.samples = samples
    sc.cycles.use_adaptive_sampling = True
    sc.cycles.use_denoising = True
    sc.cycles.denoiser = 'OPENIMAGEDENOISE'
    sc.cycles.denoising_prefilter = 'FAST'   # gürültü gidericinin hızlı ayarı: ~3 kat hızlı, kalite farkı göze çarpmaz
    sc.cycles.denoising_quality = 'FAST'
    sc.cycles.max_bounces = 3
    sc.cycles.diffuse_bounces = 1
    sc.cycles.glossy_bounces = 1
    sc.cycles.transmission_bounces = 1
    sc.render.use_persistent_data = True
    sc.render.film_transparent = True
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_mode = 'RGBA'
    sc.render.image_settings.color_depth = '8'
    sc.view_settings.view_transform = 'Standard'
    sc.view_settings.look = 'None'
    bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 0, 0))
    bpy.context.object.is_shadow_catcher = True

    def light(loc, energy, col, size):
        bpy.ops.object.light_add(type='AREA', location=loc)
        lo = bpy.context.object
        lo.data.energy, lo.data.color, lo.data.size = energy, col, size
        lo.rotation_mode = 'QUATERNION'
        lo.rotation_quaternion = (Vector((loc[0] * 0.2, 0, 1.2)) - Vector(loc)).to_track_quat('-Z', 'Y')
        return lo
    lights = [light((3.0, -3.5, 4.5), 900, (1.0, 0.86, 0.68), 3.0),
              light((-4.0, -3.0, 2.0), 260, (0.62, 0.72, 1.0), 4.0),
              light((1.0, 3.0, 3.0), 800, (1.0, 0.62, 0.32), 2.0)]
    w = bpy.data.worlds.new('w')
    sc.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes['Background']
    bg.inputs['Color'].default_value = (0.30, 0.22, 0.15, 1)
    bg.inputs['Strength'].default_value = 0.5
    bpy.ops.object.camera_add(location=(0, -20, 1.5), rotation=(math.radians(90), 0, 0))
    cam = bpy.context.object
    cam.data.type = 'ORTHO'
    sc.camera = cam
    return cam, lights


def _bake(bpy):
    """Yumuşatmayı bir kez uygula ve aynı ekleme bağlı parçaları tek nesnede birleştir (her karede yeniden hesaplanmasın)."""
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH' and o.parent is not None]
    bpy.ops.object.select_all(action='DESELECT')
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.object.convert(target='MESH')
    groups = {}
    for o in meshes:
        groups.setdefault(o.parent.name, []).append(o)
    for _, objs in groups.items():
        if len(objs) < 2:
            continue
        bpy.ops.object.select_all(action='DESELECT')
        for o in objs:
            o.select_set(True)
        bpy.context.view_layer.objects.active = objs[0]
        bpy.ops.object.join()
    bpy.ops.object.select_all(action='DESELECT')


def build(r, outdir, samples=6, log=print, max_frames=None):
    """Bölümün bütün 3D karelerini render eder; Layer3D döndürür."""
    import bpy
    from types import SimpleNamespace
    from ..engine.render import GROUND_Y
    from . import chars3d as C
    bpy.ops.wm.read_factory_settings(use_empty=True)
    C._MATS.clear()
    cam, lights = _setup_blender(samples)
    names = sorted({c for sc in r.ep['scenes'] for c in sc['characters'] if c in C.BUILDERS})
    figs = {}
    for n in names:
        fg = C.BUILDERS[n]()
        fg.root.scale = (C.SCALE.get(n, 1.0),) * 3
        figs[n] = fg
    _bake(bpy)
    os.makedirs(outdir, exist_ok=True)
    sc = bpy.context.scene
    frames = {}
    n_tot = int(r.tl['total'] * FPS3D) + 1
    if max_frames:
        n_tot = min(n_tot, max_frames)
    rects, t0, done = {}, time.time(), 0
    limit = float(os.environ.get('UCD_SURE_SINIRI_DK', '55')) * 60  # bu süreyi aşarsa 2D'ye dön (yayın gecikmesin)
    # karakter durumlarını yakalamak için Renderer'ı yakalama kipinde çalıştır
    r.texts = lambda *a, **k: []
    for i in range(n_tot):
        t = i / FPS3D
        r.cap = []
        r.frame(t)
        caps, si = r.cap, r.scene_at(t)
        r.cap = None
        if si not in rects:
            x0, y0, x1, y1 = _scene_rect(r, si)
            rects[si] = (x0, y0, x1, y1)
            cam.data.ortho_scale = (x1 - x0) / C.U
            cam.data.sensor_fit = 'HORIZONTAL'
            cz = (GROUND_Y - (y0 + y1) / 2) / C.U
            rx = math.radians(90 - TILT)
            d = (0.0, math.sin(rx), -math.cos(rx))
            cam.rotation_euler = (rx, 0, 0)
            cam.location = (((x0 + x1) / 2) / C.U - 20 * d[0], -20 * d[1], cz - 20 * d[2])
            sc.render.resolution_x = int((x1 - x0) * R)
            sc.render.resolution_y = int((y1 - y0) * R)
        present = {c for c, *_ in caps}
        for n, fg in figs.items():
            vis = n in present
            for ob in [fg.root] + list(fg.root.children_recursive):
                ob.hide_render = not vis
        for c, x, y, st in caps:
            if c in figs:
                z = (GROUND_Y - y) - getattr(st, 'dy', 0.0)
                figs[c].pose(x, z, st, t, C.U)
        # sadece karakterlerin kapladığı kutuyu render et (boş alan ve gürültü giderici zamanı harcanmasın)
        x0, y0, x1, y1 = rects[si]
        vis = [(x, y, c, st) for c, x, y, st in caps if c in figs]
        if not vis:
            continue
        bx0 = max(x0, min(x - C_W.get(c, 200) for x, y, c, st in vis))
        bx1 = min(x1, max(x + C_W.get(c, 200) for x, y, c, st in vis))
        by0 = max(y0, min(y - C_H.get(c, 450) + min(0.0, getattr(st, 'dy', 0.0)) for x, y, c, st in vis))
        by1 = y1
        # kameranın o an göstermediği kısmı çizme (yakın planda büyük kazanç); hareket/sarsıntı payı bırak
        cm = getattr(r, '_cam', None)
        if cm is not None:
            pad = 90 / max(cm.z, 0.3)
            hw, hh = cm.W / 2 / cm.z + pad, cm.H / 2 / cm.z + pad
            bx0, bx1 = max(bx0, cm.cx - hw), min(bx1, cm.cx + hw)
            by0, by1 = max(by0, cm.cy - hh), min(by1, cm.cy + hh)
        if bx1 - bx0 < 20 or by1 - by0 < 20:
            continue
        sc.render.use_border = True
        sc.render.use_crop_to_border = True
        sc.render.border_min_x = (bx0 - x0) / (x1 - x0)
        sc.render.border_max_x = (bx1 - x0) / (x1 - x0)
        sc.render.border_min_y = 1 - (by1 - y0) / (y1 - y0)
        sc.render.border_max_y = 1 - (by0 - y0) / (y1 - y0)
        path = os.path.join(outdir, f'{si}_{i:05d}.png')
        sc.render.filepath = path
        bpy.ops.render.render(write_still=True)
        px0 = int(sc.render.border_min_x * sc.render.resolution_x)
        py0 = sc.render.resolution_y - int(sc.render.border_max_y * sc.render.resolution_y)
        frames[(si, i)] = (path, x0 + px0 / R, y0 + py0 / R)
        done += 1
        el = time.time() - t0
        if done == 20 and el / done * n_tot > limit:
            raise RuntimeError(f'3D çok yavaş: kare başı {el / done:.1f} sn, tahmini toplam {el / done * n_tot / 60:.0f} dk')
        if el > limit:
            raise RuntimeError(f'3D süre sınırı aşıldı ({done}/{n_tot} kare)')
        if done % 24 == 0:
            el = time.time() - t0
            log(f'  3D: {done}/{n_tot} kare, kare başı {el / done:.1f} sn, kalan ~{(n_tot - done) * el / done / 60:.0f} dk')
    log(f'3D katman hazır: {done} kare, {(time.time() - t0) / 60:.1f} dk')
    return Layer3D(frames)
