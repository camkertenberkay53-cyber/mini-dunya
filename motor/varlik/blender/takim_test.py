"""Blender (bpy) içinde çalışır: karakter + ekipman montajını animasyon boyunca ölçer.

python3 takim_test.py <is.json>
is.json: {"karakterler": [{ad, govde_glb, takilanlar: [{yuva, id, kategori, glb, kopuk?, ince_ayar?}]}],
          "animasyonlar": [...], "kare": 5, "giysi_testi": true, "cikti": "sonuc.json"}

Godot'taki donatıcının yaptığını taklit eder: ekipman, gövdedeki YUVA_<ad> boşluğuna yerel kimlik dönüşümüyle
bağlanır; "sag_el_dik" eli izler ama dünyada dik durur. Her örnek karede ölçülür:
- kayma: ekipmanın bağlı olduğu kemiğe göre konum/açı sapması (sert bağlantıda ~0 olmalı)
- tutus: ekipman kökünün yuvanın kemiğine uzaklığı (el silahı elden kopuk mu)
- baslik: baş köşelerinin başlığın dışına taşma oranı ve baş tepesi-başlık boşluğu
- gomulme: gövde/giysi köşelerinden kalkanın ya da silahın İÇİNE giren köşe sayısı
- giysi: alt katmanın (ten, iç giysi) dış giysiden dışarı taşma oranı
"""
import json
import math
import os
import sys

import bpy  # noqa: I001
import bmesh
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

IS = json.load(open(sys.argv[-1]))
ANIM = IS["animasyonlar"]
KARE = IS.get("kare", 5)


def temizle():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def al_glb(yol):
    once = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=yol)
    return [o for o in bpy.data.objects if o not in once]


def dunya_bm(o, dg):
    """Değerlendirilmiş (pozlanmış) nesnenin dünya koordinatlı bmesh'i."""
    e = o.evaluated_get(dg)
    me = e.to_mesh()
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.transform(e.matrix_world)
    e.to_mesh_clear()
    bm.normal_update()
    return bm


def kemik_dunya(arm, ad):
    return arm.matrix_world @ arm.pose.bones[ad].matrix


def yon_isareti(bm):
    """Yüz normallerinin dışa mı içe mi baktığı (dikey eksene göre ortalama)."""
    if not bm.faces:
        return 1.0
    c = sum((f.calc_center_median() for f in bm.faces), Vector()) / len(bm.faces)
    t = 0.0
    for f in bm.faces:
        r = f.calc_center_median() - c
        r.z = 0
        t += f.normal.dot(r)
    return 1.0 if t >= 0 else -1.0


def icinde_mi(agac, v, yon=1.0, tol=0.002, maks=0.05):
    """Kapalı ince katının içinde mi: en yakın yüzeye göre arka tarafta ve yakın."""
    p, n, _i, d = agac.find_nearest(v, maks)
    if p is None:
        return False
    return (v - p).dot(n) * yon < -tol


def dik_izdusum(v, p, n) -> bool:
    """Köşe, dış yüzeyin ÜSTÜNDE ya da ALTINDA mı (normal doğrultusunda)? En yakın nokta yüzeyin kenarındaysa ve köşe
    yana doğru uzaktaysa (örneğin zırh eteğinin altından sarkan kumaş) köşe örtülü sayılmaz: orada taşma olamaz."""
    d = v - p
    L = d.length
    if L < 0.002:
        return True
    dik = abs(d.dot(n))
    return dik >= 0.8 * L


def _kemik_parcalari(arm):
    return [(arm.matrix_world @ b.head_local, arm.matrix_world @ b.tail_local) for b in arm.data.bones]


def _en_yakin_eksen(p, parcalar):
    en, enp = 9e9, None
    for a, b in parcalar:
        ab = b - a
        t = max(0.0, min(1.0, (p - a).dot(ab) / max(ab.length_squared, 1e-9)))
        q = a + ab * t
        d = (p - q).length
        if d < en:
            en, enp = d, q
    return enp


# Örtü ilişkisi yarıçapı (üretim değeri 0,03 m). Yalnız tanı için TEST_ORTU_YARICAP ile büyütülebilir; eşik değildir.
ORTU_YARICAP = float(os.environ.get("TEST_ORTU_YARICAP", "0.03"))


def _maskeli_koseler(o) -> set:
    """Yalnız '__maske' malzemeli yüzlere ait köşeler (Godot'da zırh maskesi açıkken çizilmez)."""
    maskeli = {i for i, ms in enumerate(o.material_slots) if ms.material and ms.material.name.split(".")[0].endswith("__maske")}
    if not maskeli:
        return set()
    acik = set()
    kapali = set()
    for p in o.data.polygons:
        (kapali if p.material_index in maskeli else acik).update(p.vertices)
    return kapali - acik


def katman_belirle(arm, ten, giysiler):
    """Dinlenme duruşunda: (1) her giysinin normal yönü (iskelete göre dışa = +1), (2) hangi katmanların o giysinin
    içinde kaldığı. Animasyonda yalnızca bu iç katmanların dışarı taşması ölçülür."""
    arm.data.pose_position = "REST"
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    parcalar = _kemik_parcalari(arm)
    bms = {o.name: dunya_bm(o, dg) for o in [ten] + giysiler}
    yon, ic = {}, {}
    for g in giysiler:
        gbm = bms[g.name]
        top = 0.0
        for f in list(gbm.faces)[:: max(1, len(gbm.faces) // 300)]:
            c = f.calc_center_median()
            q = _en_yakin_eksen(c, parcalar)
            top += f.normal.dot(c - q)
        yon[g.name] = 1.0 if top >= 0 else -1.0
    ortu = {}
    for g in giysiler:
        agac = BVHTree.FromBMesh(bms[g.name])
        bms[g.name].faces.ensure_lookup_table()
        sinir = {f.index for f in bms[g.name].faces if any(e.is_boundary for e in f.edges)}
        ic[g.name] = []
        ortu[g.name] = {}
        for m in [ten] + giysiler:
            if m is g:
                continue
            ortulu = disarda = 0
            altta = []
            gizli = _maskeli_koseler(m) if IS.get("maske") else set()   # Faz 5.2: çizilmeyen (maskeli) yüzler
            for v in bms[m.name].verts:
                if v.index in gizli:
                    continue
                p, n, fi, d = agac.find_nearest(v.co, ORTU_YARICAP)
                if p is None or fi in sinir or not dik_izdusum(v.co, p, n):
                    continue
                ortulu += 1
                if (v.co - p).dot(n) * yon[g.name] > 0.0:
                    disarda += 1
                else:
                    altta.append(v.index)
            if ortulu >= 20 and disarda / ortulu < 0.5:
                ic[g.name].append(m.name)
                ortu[g.name][m.name] = set(altta)  # dinlenmede GERÇEKTEN bu giysinin altında olan köşeler
    for b in bms.values():
        b.free()
    arm.data.pose_position = "POSE"
    bpy.context.view_layer.update()
    if os.environ.get("TEST_AYRINTI"):
        print("KATMAN_ICI", {g: {m: len(k) for m, k in d.items()} for g, d in ortu.items()})
    return {"yon": yon, "ic": ic, "ortu": ortu}


def karakter_olc(k):
    temizle()
    govde = al_glb(k["govde_glb"])
    arm = [o for o in govde if o.type == "ARMATURE"][0]
    yuvalar = {o.name[5:]: o for o in govde if o.name.startswith("YUVA_")}
    meshler = [o for o in govde if o.type == "MESH" and o.visible_get()]
    ten = max((o for o in meshler if not o.name.startswith("giysi_")), key=lambda o: len(o.data.vertices))
    giysiler = sorted([o for o in meshler if o.name.startswith("giysi_")], key=lambda o: int(o.name.split("_")[1]))
    # ekipmanı tak
    ekler = []
    for t in k["takilanlar"]:
        yeni = al_glb(t["glb"])
        kok = bpy.data.objects.new("EK_" + t["id"], None)
        bpy.context.scene.collection.objects.link(kok)
        for o in yeni:
            if o.parent is None:
                o.parent = kok
        yuva_ad = "sag_el" if t["yuva"] == "sag_el_dik" else t["yuva"]
        y = yuvalar[yuva_ad]
        if t.get("kopuk"):
            kok.matrix_world = y.matrix_world.copy()   # yuvaya bağlanmaz: ilk konumda kalır
        else:
            kok.parent = y
            kok.matrix_parent_inverse = Matrix.Identity(4)
            kok.matrix_basis = Matrix.Identity(4)
        if t.get("yuva_payi"):   # Faz 5.2: yuvadan gövdenin dışına (yerel -Y); Godot donatıcısı aynısını yapar
            kok.matrix_basis = Matrix.Translation(Vector((0.0, -float(t["yuva_payi"]), 0.0))) @ kok.matrix_basis
        if t.get("ince_ayar"):
            kok.matrix_basis = Matrix.Translation(Vector(t["ince_ayar"])) @ kok.matrix_basis
        ekler.append({"t": t, "kok": kok, "yuva": y, "kemik": y.parent_bone,
                      "mesh": [o for o in yeni if o.type == "MESH"]})
    ad_ = arm.animation_data or arm.animation_data_create()
    for tr in ad_.nla_tracks:
        tr.mute = True
    sonuc = {"ad": k["ad"], "ekipman": {}, "giysi": {}, "ornek_kare": 0, "katman": None}
    for e in ekler:
        sonuc["ekipman"][e["t"]["id"]] = {"yuva": e["t"]["yuva"], "kategori": e["t"]["kategori"], "kayma_mm": 0.0, "kayma_derece": 0.0,
                                         "tutus_cm": 0.0, "gomulme_koseleri": 0, "gomulme_kare_orani": 0.0,
                                         "bas_tasma_orani": None, "bas_bosluk_cm": None}
    for g in giysiler:
        sonuc["giysi"][g.name] = {"tasma_orani": 0.0, "tasma_kare": None}
    UZUV = ("hand_", "index_", "middle_", "pinky_", "ring_", "thumb_", "lowerarm_")

    def _uzuv(o):
        g = {x.index: x.name for x in o.vertex_groups}
        return [bool(v.groups) and g.get(max(v.groups, key=lambda q: q.weight).group, "").startswith(UZUV) for v in o.data.vertices]
    uzuv_maskesi = _uzuv(ten) + [m for gx in giysiler for m in _uzuv(gx)]
    katman_ici = katman_belirle(arm, ten, giysiler) if IS.get("giysi_testi", True) else {"yon": {}, "ic": {}, "ortu": {}}
    ilk = {}
    sahne = bpy.context.scene
    gomulen_kare = {e["t"]["id"]: 0 for e in ekler}
    # Ek animasyon kütüphaneleri (Faz 5.5): {"ual2": "<glb>"}; "ual2/Ad" adlı animasyon o glb'deki "Ad" eylemidir.
    # Aynı evrensel iskelet (kemik adları aynı) olduğundan eylem doğrudan bu armatüre atanır. Verilmezse davranış aynıdır.
    ek_eylem = {}
    for kut, yol in (IS.get("ek_glb") or {}).items():
        once_act = set(bpy.data.actions)
        for o in al_glb(yol):
            bpy.data.objects.remove(o, do_unlink=True)
        for a in set(bpy.data.actions) - once_act:
            a.use_fake_user = True
            ek_eylem[f"{kut}/{a.name}"] = a
    for anim in ANIM:
        act = bpy.data.actions.get(anim) or ek_eylem.get(anim)
        if act is None:
            continue
        ad_.action = act
        if hasattr(ad_, "action_slot") and getattr(act, "slots", None):
            ad_.action_slot = act.slots[0]
        b, s = act.frame_range
        for i in range(KARE):
            f = b + (s - b) * i / max(1, KARE - 1) * 0.999
            sahne.frame_set(int(f), subframe=f - int(f))
            for e in ekler:  # dik taşınan: eli izler, dünyada dik (Godot donatıcısıyla aynı)
                if e["t"]["yuva"] == "sag_el_dik" and not e["t"].get("kopuk"):
                    bpy.context.view_layer.update()
                    konum = e["yuva"].matrix_world.translation.copy()
                    e["kok"].matrix_world = Matrix.Translation(konum) @ (arm.matrix_world.to_3x3() @ Matrix.Rotation(math.pi, 3, "Z")).to_4x4()
            bpy.context.view_layer.update()
            dg = bpy.context.evaluated_depsgraph_get()
            sonuc["ornek_kare"] += 1
            ten_bm = dunya_bm(ten, dg)
            ten_bm.verts.ensure_lookup_table()
            g_bm = [dunya_bm(g, dg) for g in giysiler]
            govde_koseleri = [v.co.copy() for v in ten_bm.verts] + [v.co.copy() for bm in g_bm for v in bm.verts]
            tutan_uzuv = uzuv_maskesi
            bas_grup = ten.vertex_groups.get("Head")
            bas_koseleri = []
            if bas_grup:
                gi = bas_grup.index
                agirlik = [max((x.weight for x in v.groups if x.group == gi), default=0.0) for v in ten.data.vertices]
                bas_koseleri = [ten_bm.verts[j].co.copy() for j in range(len(agirlik)) if agirlik[j] > 0.5] if len(agirlik) == len(ten_bm.verts) else []
            for e in ekler:
                r = sonuc["ekipman"][e["t"]["id"]]
                kem = kemik_dunya(arm, e["kemik"])
                eq = e["kok"].matrix_world
                if e["t"]["yuva"] == "sag_el_dik":
                    goreli = Matrix.Translation(kem.inverted() @ eq.translation)
                else:
                    goreli = kem.inverted() @ eq
                if e["t"]["id"] not in ilk:
                    ilk[e["t"]["id"]] = goreli.copy()
                g0 = ilk[e["t"]["id"]]
                r["kayma_mm"] = max(r["kayma_mm"], (goreli.translation - g0.translation).length * 1000)
                if e["t"]["yuva"] != "sag_el_dik":
                    q = goreli.to_quaternion().rotation_difference(g0.to_quaternion())
                    r["kayma_derece"] = max(r["kayma_derece"], math.degrees(abs(q.angle)) if q.angle <= math.pi else 360 - math.degrees(q.angle))
                r["tutus_cm"] = max(r["tutus_cm"], (eq.translation - kem.translation).length * 100)
                if not e["mesh"]:
                    continue
                ebm = bmesh.new()
                for o in e["mesh"]:
                    b2 = dunya_bm(o, dg)
                    me = bpy.data.meshes.new("gecici")
                    b2.to_mesh(me)
                    ebm.from_mesh(me)
                    bpy.data.meshes.remove(me)
                    b2.free()
                ebm.normal_update()
                agac = BVHTree.FromBMesh(ebm)
                if e["t"]["kategori"] == "baslik" and bas_koseleri:
                    # Başın merkezinden her baş köşesine ışın: ışın başlığa köşeden ÖNCE çarpıyorsa o köşe başlığın
                    # altında kalmalı; köşe başlık yüzeyinin ötesindeyse baş başlıktan dışarı taşmış demektir.
                    # Başlığın örtmediği yönler (yüz, kulak altı, siperin altı) ölçüme girmez.
                    hb = kemik_dunya(arm, "Head").translation
                    c = (hb + e["yuva"].matrix_world.translation) * 0.5
                    ortu = tasan = 0
                    for v in bas_koseleri:
                        dv = v - c
                        uz = dv.length
                        if uz < 1e-4:
                            continue
                        hit = agac.ray_cast(c, dv / uz, 0.5)
                        if hit[0] is None:
                            continue
                        ortu += 1
                        if uz > hit[3] + 0.004:
                            tasan += 1
                    oran = tasan / max(1, ortu)
                    r["bas_tasma_orani"] = max(r["bas_tasma_orani"] or 0.0, round(oran, 4))
                    # başa oturma: başlığın baş/saç köşelerine en yakın mesafesi (havada duruyorsa büyür)
                    bosluk = 99.0
                    for v in bas_koseleri:
                        p_, _n, _i, d_ = agac.find_nearest(v, 0.2)
                        if p_ is not None:
                            bosluk = min(bosluk, d_ * 100)
                    r["bas_bosluk_cm"] = round(min(r["bas_bosluk_cm"] if r["bas_bosluk_cm"] is not None else 99.0, bosluk), 2)
                elif e["t"]["kategori"] in ("kalkan", "silah"):
                    # tutan uzuv (el, parmak, ön kol) kabzayı/kayışı doğal olarak sarar: sayılmaz
                    giren = sum(1 for v, uzuv in zip(govde_koseleri, tutan_uzuv) if not uzuv and icinde_mi(agac, v))
                    r["gomulme_koseleri"] = max(r["gomulme_koseleri"], giren)
                    if giren > 25:
                        gomulen_kare[e["t"]["id"]] += 1
                ebm.free()
            if IS.get("giysi_testi", True):
                tum = [(ten, ten_bm)] + list(zip(giysiler, g_bm))
                for g, gbm in zip(giysiler, g_bm):
                    if "kusak" in g.name or "kemer" in g.name:
                        continue  # dar şerit: örtme değil süs
                    yon = katman_ici["yon"][g.name]
                    agac = BVHTree.FromBMesh(gbm)
                    gbm.faces.ensure_lookup_table()
                    sinir = {f.index for f in gbm.faces if any(ed.is_boundary for ed in f.edges)}
                    ortulu = tasan = 0
                    for m, mbm in tum:
                        if m is g or m.name not in katman_ici["ic"][g.name]:
                            continue  # yalnızca bu giysinin İÇİNDE kalması gereken katmanlar
                        mbm.verts.ensure_lookup_table()
                        for vi in katman_ici["ortu"][g.name].get(m.name, ()):
                            v = mbm.verts[vi]
                            p, n, fi, d = agac.find_nearest(v.co, ORTU_YARICAP)
                            if p is None or fi in sinir or not dik_izdusum(v.co, p, n):
                                continue
                            ortulu += 1
                            if (v.co - p).dot(n) * yon > 0.004:
                                tasan += 1
                                if os.environ.get("TEST_AYRINTI"):
                                    print("TASAN", anim, g.name, m.name, round(v.co.z, 2), round(v.co.x, 2), round(v.co.y, 2))
                    oran = tasan / max(ortulu, 50)  # az örtülü köşede bile taşan sayısı gizlenmez
                    rg = sonuc["giysi"][g.name]
                    rg["en_cok_tasan_kose"] = max(rg.get("en_cok_tasan_kose", 0), tasan)
                    rg.setdefault("animasyon", {})
                    rg["animasyon"][anim] = max(rg["animasyon"].get(anim, 0.0), round(oran, 4))
                    if oran > rg["tasma_orani"]:
                        rg["tasma_orani"] = round(oran, 4)
                        rg["tasma_kare"] = f"{anim}@{f:.0f}"
                        rg["ortulu_kose"] = ortulu
            ten_bm.free()
            for bm in g_bm:
                bm.free()
    sonuc["katman"] = katman_ici["ic"] if IS.get("giysi_testi", True) else None
    for e in ekler:
        sonuc["ekipman"][e["t"]["id"]]["gomulme_kare_orani"] = round(gomulen_kare[e["t"]["id"]] / max(1, sonuc["ornek_kare"]), 3)
        sonuc["ekipman"][e["t"]["id"]]["kayma_mm"] = round(sonuc["ekipman"][e["t"]["id"]]["kayma_mm"], 2)
        sonuc["ekipman"][e["t"]["id"]]["kayma_derece"] = round(sonuc["ekipman"][e["t"]["id"]]["kayma_derece"], 2)
        sonuc["ekipman"][e["t"]["id"]]["tutus_cm"] = round(sonuc["ekipman"][e["t"]["id"]]["tutus_cm"], 2)
    return sonuc


tum = [karakter_olc(k) for k in IS["karakterler"]]
json.dump(tum, open(IS["cikti"], "w"), ensure_ascii=False, indent=1)
print("TEST BITTI", len(tum))
