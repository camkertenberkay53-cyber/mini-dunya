"""Blender (bpy) içinde çalışır: yer değiştiren döngü animasyonlarının (yerinde oynatılan) zemin hızını ÖLÇER.

python3 animasyon_hizi.py <govde.glb> <cikti.json>
Yöntem: her karede iki ayağın (ball_l/ball_r) dünya konumu alınır; o karede yere basan ayak (daha alçakta olan)
yerinde oynatılan döngüde geriye doğru kayar. Bu kayma hızının ortancası = karakterin sahnede ilerlemesi gereken hız.
Bu hızla ilerletilmeyen yürüyüşte ayak yerde kayar ("buz pateni"). Ayrıca kök kemiği hareket ediyor mu, ölçülür.
"""
import json
import statistics
import sys

import bpy

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=sys.argv[-2])
arm = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
fps = bpy.context.scene.render.fps / bpy.context.scene.render.fps_base
sahne = bpy.context.scene
sonuc = {}
for act in bpy.data.actions:
    arm.animation_data.action = act
    b, s = (int(x) for x in act.frame_range)
    ayak = {"ball_l": [], "ball_r": []}
    kok = []
    for f in range(b, s + 1):
        sahne.frame_set(f)
        for k in ayak:
            ayak[k].append((arm.matrix_world @ arm.pose.bones[k].head).copy())
        kok.append((arm.matrix_world @ arm.pose.bones["root"].head).copy())
    hizlar, yon = [], []
    for i in range(1, len(kok)):
        alt = min(ayak, key=lambda k: ayak[k][i].z)
        if ayak[alt][i].z > min(ayak[alt]).z + 0.04 if False else ayak[alt][i].z > min(p.z for p in ayak[alt]) + 0.04:
            continue  # bu karede iki ayak da havada (koşu)
        d = ayak[alt][i] - ayak[alt][i - 1]
        d.z = 0
        hizlar.append(d.length * fps)
        yon.append(d.normalized())
    sure = (s - b) / fps
    kok_kayma = (kok[-1] - kok[0]).length
    sonuc[act.name] = {
        "sure_sn": round(sure, 3),
        "kare": s - b + 1,
        "zemin_hizi_m_sn": round(statistics.median(hizlar), 3) if hizlar else 0.0,
        "olculen_kare": len(hizlar),
        "kok_kaymasi_m": round(kok_kayma, 3),
    }
json.dump({"fps": fps, "kaynak": sys.argv[-2], "animasyonlar": sonuc}, open(sys.argv[-1], "w"), indent=1)
print("HIZ OLCULDU", len(sonuc))
