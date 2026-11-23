import sys, time, math, os
sys.path.insert(0, '/home/claude/blender_poc')
import bpy, mini3d
bpy.ops.wm.read_factory_settings(use_empty=True)
c = mini3d.tuna(0.0)
mini3d.setup(540, 960, 8)
os.makedirs('/home/claude/blender_poc/kare', exist_ok=True)
FPS = 12; N = int(sys.argv[-1])
t0 = time.time()
for i in range(N):
    t = i / FPS
    walk = 1.0 if t < 1.0 else max(0.0, 1 - (t - 1.0) * 3)
    x = -0.6 + min(t, 1.0) * 0.9
    talk = 0.0 if t < 1.1 else abs(math.sin(t * 13)) * 0.9
    blink = 1.0 if 1.45 < t < 1.6 else 0.0
    c.pose(t, walk=walk, talk=talk, blink=blink, look=0.0, x=x, point=min(1.0, max(0.0, (t - 1.2) * 3)))
    bpy.context.scene.render.filepath = f'/home/claude/blender_poc/kare/{i:04d}.png'
    bpy.ops.render.render(write_still=True)
print('ORT_SN', round((time.time() - t0) / N, 1))
