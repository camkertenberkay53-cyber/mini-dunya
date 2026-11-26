"""Gövdeden türetilen giysiler ve ekipman yuvaları (Blender içinde).

Giysi = gövde yüzeyinin seçili bölgesinin, normal boyunca dışarı itilmiş kopyası. Kopya gövdenin kemik
ağırlıklarını aynen taşır; animasyonda gövdeyle birlikte hareket eder (kopmaz, içe gömülmez).
Etek = kalçadan aşağı açılan koni; ağırlıkları leğen ve uyluklara dağıtılır.
Gövdenin giysi altında kalan yüzleri silinir (gizli poligon ve içten taşma olmasın).

Yuva = kemiğe bağlı boş düğüm. Sert ekipman (miğfer, kalkan, silah...) çalışma anında buna takılır.
Yuva ekseni sözleşmesi (bütün ekipman bu sözleşmeyle modellenir):  +Z = ekipmanın "yukarı"sı,
-Y = ekipmanın "önü" (kalkanın yüzü, miğferin alnı, kılıcın ağzı). Köken = bağlantı noktası.
"""
from __future__ import annotations

import math
import os
import sys

import bpy  # noqa: I001
import bmesh
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ortak  # noqa: E402

GOVDE_GRUPLARI = {
    "govde_ust": ["spine_01", "spine_02", "spine_03", "clavicle_l", "clavicle_r", "pelvis"],
    "boyun_alti": ["neck_01"],
    "kol_ust": ["upperarm_l", "upperarm_r"],
    "kol_alt": ["lowerarm_l", "lowerarm_r"],
    "uyluk": ["thigh_l", "thigh_r"],
    "baldir": ["calf_l", "calf_r"],
    "ayak": ["foot_l", "foot_r", "ball_l", "ball_r"],
}


def _baskin(o):
    g = {x.index: x.name for x in o.vertex_groups}
    return [g[max(v.groups, key=lambda q: q.weight).group] if v.groups else "" for v in o.data.vertices]


def bolge_sec(govde, bolgeler: list[str], zmin=-9.0, zmax=9.0, xmax=None, ymin=None) -> set[int]:
    gruplar = set()
    for b in bolgeler:
        gruplar.update(GOVDE_GRUPLARI.get(b, [b]))
    bas = _baskin(govde)
    mw = govde.matrix_world
    sec = set()
    for v, g in zip(govde.data.vertices, bas):
        p = mw @ v.co
        if g in gruplar and zmin <= p.z <= zmax and (xmax is None or abs(p.x) <= xmax) and (ymin is None or p.y >= ymin):
            sec.add(v.index)
    return sec


def _silindirik_uv(bm, eksen: str, olcek: float):
    uv = bm.loops.layers.uv.verify()
    for f in bm.faces:
        for lp in f.loops:
            c = lp.vert.co
            if eksen == "z":
                u = (math.atan2(c.x, -c.y) / (2 * math.pi) + 0.5) * olcek
                v = c.z * olcek
            else:  # kol: x ekseni boyunca
                u = (math.atan2(c.z - 1.45, c.y) / (2 * math.pi) + 0.5) * olcek * 0.4
                v = c.x * olcek
            lp[uv].uv = (u, v)


YUMUSATMA_SINIRI = 0.08   # m; yumuşatma bir köşeyi bundan fazla taşıdıysa ıraksamıştır


def _taubin(koseler, tur: int, lam: float = 0.5, mu: float = -0.53):
    for _ in range(tur):
        for f in (lam, mu):
            yeni = []
            for v in koseler:
                ks = [e.other_vert(v).co for e in v.link_edges]
                if ks:
                    yeni.append((v, v.co + (sum(ks, Vector()) / len(ks) - v.co) * f))
            for v, c in yeni:
                v.co = c


def kabuk(govde, arm, secim: set[int], ofset: float, mat, ad: str, uv_ekseni="z", uv_olcek=2.5, yumusatma=10):
    """Gövdenin seçili köşelerinden dışarı itilmiş, aynı ağırlıklı giysi kabuğu.
    Kas hatları kumaşa geçmesin diye kabuk önce yumuşatılır (sınır köşeleri sabit), sonra gövdeye en az
    'ofset' kadar mesafe kalacak biçimde dışarı itilir (BVH ile; içe gömülme olmaz)."""
    from mathutils.bvhtree import BVHTree
    tam = bmesh.new()
    tam.from_mesh(govde.data)
    agac = BVHTree.FromBMesh(tam)
    tam.free()
    k = govde.copy()
    k.data = govde.data.copy()
    k.name = ad
    k.data.name = ad  # glTF düğüm adı korunur: testler ve Godot giysiyi adından tanır
    bpy.context.scene.collection.objects.link(k)
    bm = bmesh.new()
    bm.from_mesh(k.data)
    bm.verts.ensure_lookup_table()
    bm.normal_update()
    kaynak = bm.verts.layers.int.new("kaynak")  # gövdedeki asıl köşe numarası (türetilen katmanlar için)
    for v in bm.verts:
        v[kaynak] = v.index
    sil = [v for v in bm.verts if v.index not in secim]
    bmesh.ops.delete(bm, geom=sil, context="VERTS")
    bm.normal_update()
    ic = [v for v in bm.verts if not v.is_boundary]
    kenar = [v for v in bm.verts if v.is_boundary]
    # Hacmi koruyan Laplace yumuşatması: kas hatlarını siler ama kol ağzı/omuzda kabuğu gövdenin içine katlamaz
    ilk = [v.co.copy() for v in bm.verts]
    for _ in range(yumusatma):
        bmesh.ops.smooth_laplacian_vert(bm, verts=ic, lambda_factor=0.4, lambda_border=0.0,
                                        use_x=True, use_y=True, use_z=True, preserve_volume=True)
    # Hacim koruması bazı topolojilerde (gerçekçi MPFB gövdesi: dörtgen kökenli, ince üçgenler) ıraksar ve kabuğu
    # metrelerce şişirir. Iraksama görülürse yerine büzülmeyen Taubin (λ/μ) yumuşatması kullanılır. UBC'de değişiklik yok.
    if yumusatma and max((v.co - c).length for v, c in zip(bm.verts, ilk)) > YUMUSATMA_SINIRI:
        for v, c in zip(bm.verts, ilk):
            v.co = c
        _taubin(ic, yumusatma)
    # yaka/kol ağzı/etek ucu: seçim üçgenleri izlediği için dişli çıkar; kenar halkası kendi içinde düzleştirilir
    for _ in range(8):
        yeni = {}
        for v in kenar:
            ks = [e.other_vert(v) for e in v.link_edges if e.is_boundary]
            if len(ks) == 2:
                yeni[v] = v.co * 0.5 + (ks[0].co + ks[1].co) * 0.25
        for v, c in yeni.items():
            v.co = c
    for v in bm.verts:
        yakin, normal, _i, _d = agac.find_nearest(v.co)
        if yakin is None:
            v.co += v.normal * ofset
            continue
        uzak = (v.co - yakin).dot(normal)
        if uzak < ofset:
            v.co += normal * (ofset - uzak)
    bm.normal_update()
    _silindirik_uv(bm, uv_ekseni, uv_olcek)
    bm.to_mesh(k.data)
    bm.free()
    k.data.materials.clear()
    k.data.materials.append(mat)
    for p in k.data.polygons:
        p.use_smooth = True
    for m in k.modifiers:
        if m.type == "ARMATURE":
            m.object = arm
    return k


def turet(alt, secim: set[int], ofset_farki: float, mat, ad: str):
    """Dış kabuğu (zırh, levha, omuzluk) gövdeden değil, hemen altındaki kabuktan türetir: aynı köşeler, aynı kemik
    ağırlıkları, normal boyunca ofset_farki kadar dışarıda. İki katman her pozda birlikte deforme olur; kıvrımlarda
    (koltuk altı) ayrı ayrı türetilen kabukların birbirine girmesi böylece önlenir."""
    k = alt.copy()
    k.data = alt.data.copy()
    k.name = ad
    k.data.name = ad
    bpy.context.scene.collection.objects.link(k)
    bm = bmesh.new()
    bm.from_mesh(k.data)
    kaynak = bm.verts.layers.int.get("kaynak")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v[kaynak] not in secim], context="VERTS")
    bm.normal_update()
    # kenar halkasına (etek ucu, kol ağzı) yakın köşeler 2 cm'ye kadar daha açılır: alttaki katman kenarda dışarı çıkmasın
    from mathutils.kdtree import KDTree
    # türetilen kabuğun kenar halkası düzleştirilir (yaka ve kol ağzında dişli görünüm olmasın)
    for _ in range(8):
        yeni = {}
        for v in bm.verts:
            if not v.is_boundary:
                continue
            ks = [e.other_vert(v) for e in v.link_edges if e.is_boundary]
            if len(ks) == 2:
                yeni[v] = v.co * 0.5 + (ks[0].co + ks[1].co) * 0.25
        for v, c in yeni.items():
            v.co = c
    bm.normal_update()
    zort = sum((v.co.z for v in bm.verts), 0.0) / max(1, len(bm.verts))
    # yalnızca ALT kenar (etek ucu) açılır; yaka ve kol ağzı açılırsa fırfır gibi diken diken görünür
    kenar = [v.co.copy() for v in bm.verts if v.is_boundary and v.co.z < zort]
    kd = KDTree(max(1, len(kenar)))
    for i, c in enumerate(kenar):
        kd.insert(c, i)
    kd.balance()
    for v in bm.verts:
        d = kd.find(v.co)[2] if kenar else 1.0
        ek = 0.020 * max(0.0, 1.0 - d / 0.06)
        v.co += v.normal * (ofset_farki + ek)
    bm.normal_update()
    bm.to_mesh(k.data)
    bm.free()
    k.data.materials.clear()
    k.data.materials.append(mat)
    return k


def etek(govde, arm, ust_z: float, alt_z: float, acilma: float, ofset: float, mat, ad: str, dilim=40, satir=14,
         onde_yarik=False):
    """Kalçadan aşağı açılan etek. Kesit, gövdenin ust_z'deki kesitinden ölçülür."""
    mw = govde.matrix_world
    P = [mw @ v.co for v in govde.data.vertices]
    S = [p for p in P if abs(p.z - ust_z) < 0.015 and abs(p.x) < 0.3]
    rx = max(abs(p.x) for p in S) + ofset
    ymin, ymax = min(p.y for p in S), max(p.y for p in S)
    cy, ry = (ymin + ymax) / 2, (ymax - ymin) / 2 + ofset
    # Etek hiçbir yükseklikte bacakların dış sınırının içine girmemeli (yanlardan bacak taşmasın)
    bacak = set(GOVDE_GRUPLARI["uyluk"] + GOVDE_GRUPLARI["baldir"] + ["pelvis"])
    BP = [p for p, g in zip(P, _baskin(govde)) if g in bacak]
    profil = []
    for j in range(satir + 1):
        t = j / satir
        z = ust_z + (alt_z - ust_z) * t
        a = 1 + (acilma - 1) * (t ** 1.3)
        dilimde = [p for p in BP if abs(p.z - z) < 0.03]
        ex = (max(abs(p.x) for p in dilimde) + ofset) if dilimde else 0.0
        ey = (max(abs(p.y - cy) for p in dilimde) + ofset) if dilimde else 0.0
        profil.append(((max(rx * a, ex), max(ry * a, ey)), z))
    bm = ortak.torna(profil, dilim, uv_olcek=2.5)
    for v in bm.verts:
        v.co.y += cy
    if onde_yarik:  # kaftanın önden açık eteği: ön ortadaki dar şerit silinir
        sil = [f for f in bm.faces if f.calc_center_median().y > cy + ry * 0.9 and abs(f.calc_center_median().x) < rx * 0.08]
        bmesh.ops.delete(bm, geom=sil, context="FACES")
    o = ortak.nesne(ad, bm, mat)
    # ağırlıklar: her etek köşesi, gövdede ona en yakın bacak/leğen köşelerinin ağırlıklarını alır
    # (bacak açılınca etek de onunla açılır, bacak yandan taşmaz); üstte leğene, aşağı indikçe bacağa geçer.
    from mathutils.kdtree import KDTree
    gruplar = {x.index: x.name for x in govde.vertex_groups}
    bacak_gr = set(GOVDE_GRUPLARI["uyluk"] + GOVDE_GRUPLARI["baldir"] + ["pelvis"])
    adaylar = [(mw @ v.co, v) for v, g in zip(govde.data.vertices, _baskin(govde)) if g in bacak_gr]
    kd = KDTree(len(adaylar))
    for n_, (p_, _v) in enumerate(adaylar):
        kd.insert(p_, n_)
    kd.balance()
    agirlik = []
    for v in o.data.vertices:
        t = max(0.0, min(1.0, (1.03 - v.co.z) / (1.03 - 0.40)))  # mutlak yükseklik: bütün eteklerde aynı
        topla, tw = {}, 0.0
        for p_, n_, d_ in kd.find_n(v.co, 8):
            w0 = 1.0 / max(d_, 0.01)
            tw += w0
            for gx in adaylar[n_][1].groups:
                ad_g = gruplar.get(gx.group)
                if ad_g in bacak_gr or ad_g in ("spine_01",):
                    topla[ad_g] = topla.get(ad_g, 0.0) + gx.weight * w0
        a = t ** 0.45  # eteğin ucu bacağı daha sıkı izler (adımda pantolon etekten çıkmasın)
        son = {k_: (w_ / tw) * a for k_, w_ in topla.items()}
        son["pelvis"] = son.get("pelvis", 0.0) + (1 - a)
        agirlik.append(son)
    # ön/arka ortadaki ani sol-sağ geçişini yumuşat (yırtılma olmasın)
    komsu = {v.index: set() for v in o.data.vertices}
    for e_ in o.data.edges:
        a_, b_ = e_.vertices
        komsu[a_].add(b_)
        komsu[b_].add(a_)
    for _ in range(4):
        yeni_w = []
        for vi, w in enumerate(agirlik):
            karisim = dict(w)
            for nb in komsu[vi]:
                for k_, x_ in agirlik[nb].items():
                    karisim[k_] = karisim.get(k_, 0.0) + x_
            n_ = 1 + len(komsu[vi])
            yeni_w.append({k_: x_ / n_ for k_, x_ in karisim.items()})
        agirlik = yeni_w
    gl = {}
    for vi, w in enumerate(agirlik):
        top = sum(w.values()) or 1.0
        for k_, x_ in w.items():
            if x_ / top > 1e-3:
                if k_ not in gl:
                    gl[k_] = o.vertex_groups.new(name=k_)
                gl[k_].add([vi], x_ / top, "REPLACE")
    # dünya konumunu koruyarak bağla: iskeletin kendi dönüşü (USD'den gelen 180°) eteğe ikinci kez uygulanmasın
    o.parent = arm
    o.matrix_parent_inverse = arm.matrix_world.inverted()
    m = o.modifiers.new("Armature", "ARMATURE")
    m.object = arm
    return o


def _yon_isareti(bm, govde_agaci) -> float:
    """Yüz sarımı tutarlı kabuğun normallerinin dışa mı içe mi baktığı: bütün yüzlerin gövdeye göre çoğunluk oyu.
    Noktasal karar (en yakın gövde noktası) koltuk altı gibi kıvrımlarda karşı uzva düşüp yanılır; oy yanılmaz."""
    oy = 0
    for f in bm.faces:
        c = f.calc_center_median()
        q = govde_agaci.find_nearest(c)[0]
        if q is not None:
            oy += 1 if f.normal.dot(c - q) >= 0 else -1
    return 1.0 if oy >= 0 else -1.0


# İç içe giyim sırası: küçük sayı içte. Her katman, kendinden içteki bütün katmanların en az KATMAN_BOSLUGU dışında kalır.
KATMAN = {"cizme": 0, "caligae": 0, "salvar": 1, "pantolon": 1, "govde": 2, "etek": 3, "zirh": 4, "lamel": 4,
          "levha": 5, "omuzluk": 5, "zirh_etek": 5, "lamel_etek": 5, "kusak": 6, "kemer": 6}
KATMAN_BOSLUGU = 0.008


def ic_ice_yerlestir(govde, nesneler: list, adlar: list[str]):
    """Giysileri katman sırasına göre iç içe yerleştirir: dıştaki katmanın her köşesi, içteki katmanların yüzeyinin
    en az KATMAN_BOSLUGU dışına itilir. Yön, gövdeye göre belirlenir (normal yönünden bağımsız)."""
    from mathutils.bvhtree import BVHTree
    tam = bmesh.new()
    tam.from_mesh(govde.data)
    tam.transform(govde.matrix_world)
    govde_agaci = BVHTree.FromBMesh(tam)
    tam.free()
    sira = sorted(range(len(nesneler)), key=lambda i: KATMAN.get(adlar[i], 3))
    icteki = []  # (katman, ağaç)
    for i in sira:
        o, k = nesneler[i], KATMAN.get(adlar[i], 3)
        mw, mwi = o.matrix_world.copy(), o.matrix_world.inverted()
        agaclar = [a for kk, a in icteki if kk < k]
        if agaclar:
            for v in o.data.vertices:
                w = mw @ v.co
                for a, isaret in agaclar:
                    p, n, _f, _d = a.find_nearest(w, 0.06)
                    if p is None:
                        continue
                    n = n * isaret
                    sm = (w - p).dot(n)
                    if sm < KATMAN_BOSLUGU:
                        w = w + n * (KATMAN_BOSLUGU - sm)
                v.co = mwi @ w
            o.data.update()
        bm = bmesh.new()
        bm.from_mesh(o.data)
        bm.transform(mw)
        bm.normal_update()
        icteki.append((k, (BVHTree.FromBMesh(bm), _yon_isareti(bm, govde_agaci))))
        bm.free()
    # İkinci yön: dış katmanın normal doğrultusunda örttüğü iç köşeler dış yüzeyin en az KATMAN_BOSLUGU altına çekilir
    # (köşeler arası yüzeyde iç katman dışa çıkmasın). Dıştan içe sırayla, iki tur.
    _say = {}
    for _tur in range(6):
        agaclar_tum = []
        for i in range(len(nesneler)):
            bm = bmesh.new()
            bm.from_mesh(nesneler[i].data)
            bm.transform(nesneler[i].matrix_world)
            bm.normal_update()
            agaclar_tum.append((KATMAN.get(adlar[i], 3), (BVHTree.FromBMesh(bm), _yon_isareti(bm, govde_agaci))))
            bm.free()
        for i in sorted(range(len(nesneler)), key=lambda i: -KATMAN.get(adlar[i], 3)):
            o, k = nesneler[i], KATMAN.get(adlar[i], 3)
            dislar = [a for kk, a in agaclar_tum if kk > k]
            if not dislar:
                continue
            mw, mwi = o.matrix_world.copy(), o.matrix_world.inverted()
            for v in o.data.vertices:
                w = mw @ v.co
                for a, isaret in dislar:
                    p, n, _f, _d = a.find_nearest(w, 0.06)
                    if p is None:
                        continue
                    dv = w - p
                    if dv.length > 0.002 and abs(dv.dot(n)) < 0.8 * dv.length:
                        continue  # dış katmanın kenarının yanında: örtülü değil
                    n = n * isaret
                    sm = dv.dot(n)
                    if sm > -KATMAN_BOSLUGU:
                        w = w - n * (sm + KATMAN_BOSLUGU)
                        _say[adlar[i]] = _say.get(adlar[i], 0) + 1
                v.co = mwi @ w
            o.data.update()
    if os.environ.get("GIYSI_HATA_AYIKLA"):
        print("ICE_CEKILEN", _say)


def agirlik_aktar(govde, o, karisim=None):
    """Giysi köşesinin kemik ağırlığını, gövdede ona EN YAKIN YÜZEYDEN aktarır (yüz köşelerinin uzaklık ağırlıklı
    karışımı). Aynı yerdeki iki katman aynı ağırlığı alır; bu yüzden pozda iç içe kalırlar."""
    from mathutils.bvhtree import BVHTree
    tam = bmesh.new()
    tam.from_mesh(govde.data)
    tam.transform(govde.matrix_world)
    tam.faces.ensure_lookup_table()
    agac = BVHTree.FromBMesh(tam)
    yuz_koseleri = [[v.index for v in f.verts] for f in tam.faces]
    kose_konum = [v.co.copy() for v in tam.verts]
    tam.free()
    gad = {x.index: x.name for x in govde.vertex_groups}
    kose_agirlik = [{gad[g.group]: g.weight for g in v.groups if g.weight > 1e-4} for v in govde.data.vertices]
    mw = o.matrix_world
    hedef = {}
    for v in o.data.vertices:
        w = mw @ v.co
        p, _n, fi, _d = agac.find_nearest(w)
        if fi is None:
            continue
        top, tw = {}, 0.0
        for ki in yuz_koseleri[fi]:
            u = 1.0 / max((kose_konum[ki] - p).length, 1e-4)
            tw += u
            for g, x in kose_agirlik[ki].items():
                top[g] = top.get(g, 0.0) + x * u
        en = sorted(top.items(), key=lambda t: (-t[1], t[0]))[:4]  # eşitlikte ada göre: bayt bayt tekrarlanabilir
        toplam = sum(x for _g, x in en) or 1.0
        hedef[v.index] = [(g, x / toplam) for g, x in en]
    if karisim is not None:  # etek: belde gövde ağırlığı, aşağı indikçe eteğin kendi (bacak izleyen) ağırlığı
        eski_ad = {x.index: x.name for x in o.vertex_groups}
        for v in o.data.vertices:
            b = karisim((mw @ v.co).z)
            eski = {eski_ad[g.group]: g.weight for g in v.groups}
            yeni = dict(hedef.get(v.index, []))
            harman = {g: b * yeni.get(g, 0.0) + (1 - b) * eski.get(g, 0.0) for g in sorted(set(eski) | set(yeni))}
            en = sorted(harman.items(), key=lambda t: (-t[1], t[0]))[:4]
            toplam = sum(x for _g, x in en) or 1.0
            hedef[v.index] = [(g, x / toplam) for g, x in en]
    for g in list(o.vertex_groups):
        o.vertex_groups.remove(g)
    gruplar = {}
    for vi, liste in hedef.items():
        for g, x in liste:
            if g not in gruplar:
                gruplar[g] = o.vertex_groups.new(name=g)
            gruplar[g].add([vi], x, "REPLACE")


GIZLI_KENAR_PAYI = 0.02   # dış katmanın kenarına (yaka, etek ucu, yırtmaç) bu kadar yakın iç yüzler silinmez
GIZLI_DERINLIK = 0.06     # iç yüz dış katmanın en çok bu kadar altında olmalı (uzaktaki ilgisiz yüzler değil)


def gizli_yuzleri_sil(govde, nesneler: list, adlar: list[str]) -> dict:
    """Dış katmanın tamamen örttüğü iç katman yüzlerini siler (oyunlarda standart "hidden surface removal").
    Bir yüz, bütün köşeleri bir dış katmanın İÇİNDE, o katmana GIZLI_DERINLIK'ten yakın ve dış katmanın kenarından
    GIZLI_KENAR_PAYI'ndan uzaksa silinir. Görünmeyen yüz animasyonda dışarı taşamaz; kenara yakın yüzler kaldığı için
    yakadan, etek ucundan ve yırtmaçtan bakınca delik oluşmaz. Silinen yüz sayısı döner."""
    from mathutils.bvhtree import BVHTree
    from mathutils.kdtree import KDTree
    tam = bmesh.new()
    tam.from_mesh(govde.data)
    tam.transform(govde.matrix_world)
    govde_agaci = BVHTree.FromBMesh(tam)
    tam.free()
    dislar = []
    for o, ad in zip(nesneler, adlar):
        bm = bmesh.new()
        bm.from_mesh(o.data)
        bm.transform(o.matrix_world)
        bm.normal_update()
        kenar = [v.co.copy() for v in bm.verts if v.is_boundary]
        isaret = _yon_isareti(bm, govde_agaci)
        kd = KDTree(max(1, len(kenar)))
        for i, c in enumerate(kenar):
            kd.insert(c, i)
        kd.balance()
        dislar.append((KATMAN.get(ad, 3), BVHTree.FromBMesh(bm), kd, bool(kenar), isaret))
        bm.free()
    silinen = {}
    for i, (o, ad) in enumerate(zip(nesneler, adlar)):
        k_i = KATMAN.get(ad, 3)
        ust = [d for j, d in enumerate(dislar) if j != i and d[0] > k_i]
        if not ust:
            continue
        mw = o.matrix_world
        bm = bmesh.new()
        bm.from_mesh(o.data)
        bm.verts.ensure_lookup_table()
        ortulu = []
        for v in bm.verts:
            w = mw @ v.co
            ok = False
            for _k, agac, kd, var, isaret in ust:
                p, n, _f, d = agac.find_nearest(w, GIZLI_DERINLIK)
                if p is None:
                    continue
                n = n * isaret
                if (w - p).dot(n) > 0:
                    continue  # dış katmanın dışında
                if var and kd.find(p)[2] < GIZLI_KENAR_PAYI:
                    continue  # kenara yakın: görünebilir
                ok = True
                break
            ortulu.append(ok)
        sil = [f for f in bm.faces if all(ortulu[v.index] for v in f.verts)]
        if sil:
            bmesh.ops.delete(bm, geom=sil, context="FACES_ONLY")
            bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
            bm.to_mesh(o.data)
        bm.free()
        silinen[ad] = len(sil)
    return silinen


def govdeyi_kirp(govde, silinecek: set[int]):
    bm = bmesh.new()
    bm.from_mesh(govde.data)
    bm.verts.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.verts[i] for i in sorted(silinecek)], context="VERTS")
    bm.to_mesh(govde.data)
    bm.free()


def giydir(govde, arm, giysiler: list[dict], malzeme_al) -> list:
    """giysiler: [{tur: kabuk|etek, ...}] -> eklenen nesneler. Kabukların altındaki gövde silinir."""
    eklenen, gizli = [], set()
    kabuklar = []  # (katman, seçim, nesne, ofset)
    for i, g in enumerate(giysiler):
        mat = malzeme_al(g["malzeme"])
        ad = f"giysi_{i}_{g['ad']}"
        if g["tur"] == "kabuk":
            sec = bolge_sec(govde, g["bolgeler"], g.get("zmin", -9), g.get("zmax", 9), g.get("xmax"), g.get("ymin"))
            if not sec:
                raise RuntimeError(f"boş giysi bölgesi: {g['ad']}")
            k_g = KATMAN.get(g["ad"], 3)
            # Bölgesinin en az %90'ını kapsayan, daha içteki bir kabuk varsa ondan türet
            taban = None
            for kk, ss, oo, of in sorted(kabuklar, key=lambda t: -t[0]):
                if kk < k_g and len(sec & ss) >= 0.9 * len(sec) and g["ofset"] > of:
                    taban = (oo, ss, of)
                    break
            if taban:
                yeni = turet(taban[0], sec & taban[1], g["ofset"] - taban[2], mat, ad)
            else:
                yeni = kabuk(govde, arm, sec, g["ofset"], mat, ad, g.get("uv", "z"), yumusatma=g.get("yumusatma", 10))
            eklenen.append(yeni)
            kabuklar.append((k_g, sec, yeni, g["ofset"]))
            if g.get("gizle", True):
                gizli |= sec
        elif g["tur"] == "etek":
            eklenen.append(etek(govde, arm, g["ust_z"], g["alt_z"], g.get("acilma", 1.2), g["ofset"], mat, ad,
                                onde_yarik=g.get("onde_yarik", False)))
        else:
            raise ValueError(g["tur"])
    ic_ice_yerlestir(govde, eklenen, [g["ad"] for g in giysiler])
    for o, g in zip(eklenen, giysiler):
        if g["tur"] == "kabuk":
            pass  # gövdeden kopyalanan özgün ağırlık: aynı kaynak köşe her katmanda aynı ağırlık
        else:  # etek: 0,95 m üstü tamamen gövde, 0,80 m altı tamamen bacak izleyen ağırlık
            agirlik_aktar(govde, o, karisim=lambda z: max(0.0, min(1.0, (z - 0.80) / 0.15)))
    gizli_yuzleri_sil(govde, eklenen, [g["ad"] for g in giysiler])
    if os.environ.get("GIYSI_HATA_AYIKLA"):
        from mathutils.bvhtree import BVHTree
        ad2 = {g["ad"]: o for o, g in zip(eklenen, giysiler)}
        if "zirh" in ad2 and "govde" in ad2:
            def _bm(o):
                b = bmesh.new(); b.from_mesh(o.data); b.transform(o.matrix_world); b.normal_update(); return b
            zb, gb = _bm(ad2["zirh"]), _bm(ad2["govde"])
            t = BVHTree.FromBMesh(zb)
            tas = 0
            for v in gb.verts:
                p_, n_, f_, d_ = t.find_nearest(v.co, 0.03)
                if p_ is None:
                    continue
                dv = v.co - p_
                if dv.length > 0.002 and abs(dv.dot(n_)) < 0.8 * dv.length:
                    continue
                if dv.dot(n_) > 0.004:
                    tas += 1
            print("DERLEMEDE_TASAN", tas, "zirh mw", [round(x, 2) for x in ad2["zirh"].matrix_world.translation], ad2["zirh"].matrix_world.to_euler())
    govdeyi_kirp(govde, gizli)
    return eklenen


# ------------------------------------------------------------------ yuvalar
def _cerceve(konum, yukari, on):
    """Z = yukarı, -Y = ön olacak dünya matrisi."""
    z = Vector(yukari).normalized()
    y = -Vector(on)
    y = (y - z * y.dot(z)).normalized()
    x = y.cross(z).normalized()
    m = Matrix((x, y, z)).transposed().to_4x4()
    m.translation = Vector(konum)
    return m


def yuvalari_kur(govde_kaynak, arm) -> dict:
    """Ölçülen gövdeye göre yuvaları kurar. govde_kaynak: kırpılmamış gövde (ölçüm için)."""
    mw = govde_kaynak.matrix_world
    bas = _baskin(govde_kaynak)
    A = arm.matrix_world
    B = arm.data.bones
    # Yuvalar +Y'ye bakan gövde için tanımlıdır. Gövde -Y'ye bakıyorsa (ör. glTF'ten gelen gerçekçi MPFB gövdesi)
    # ölçüm 180° çevrilmiş çerçevede yapılır, yuvalar dünyaya geri çevrilir. Yön: baş köşelerinin baş kemiğine göre yeri.
    _bk = A @ B["Head"].head_local
    _yuz = [mw @ v.co for v, g in zip(govde_kaynak.data.vertices, bas) if g == "Head"]
    _on = sum(p.y for p in _yuz) / max(len(_yuz), 1) - _bk.y
    R = Matrix.Rotation(math.pi, 4, "Z") if _on < -0.02 else Matrix.Identity(4)
    Ri = R.inverted()
    P = [(Ri @ (mw @ v.co), g) for v, g in zip(govde_kaynak.data.vertices, bas)]

    def k(ad, uc="head"):
        return Ri @ (A @ (B[ad].head_local if uc == "head" else B[ad].tail_local))

    basP = [p for p, g in P if g == "Head"]
    bas_tepe = max(p.z for p in basP)
    bas_y = (min(p.y for p in basP) + max(p.y for p in basP)) / 2 - 0.01
    bas_gen = max(p.x for p in basP) - min(p.x for p in basP)
    sirtP = [p for p, g in P if g == "spine_03"]
    sirt_y = min(p.y for p in sirtP)
    pelP = [p for p, g in P if g == "pelvis"]
    kalca_x = max(abs(p.x) for p in pelP)
    olcek = bas_gen / 0.182   # referans: erkek gövdenin baş genişliği
    ileri = (0, 1, 0)
    yuvalar = {
        "bas": ("Head", _cerceve((0, bas_y, bas_tepe), (0, 0, 1), ileri), olcek),
        "sag_el": ("hand_r", _cerceve(k("hand_r") + Vector((0.085 * olcek, 0.0, -0.022)), (0, 1, 0), (0, 0, -1)), 1.0),
        "sol_el": ("hand_l", _cerceve(k("hand_l") + Vector((-0.085 * olcek, 0.0, -0.022)), (0, 1, 0), (0, 0, -1)), 1.0),
        "sol_kol": ("lowerarm_l", _cerceve((k("lowerarm_l") + k("hand_l")) / 2 + Vector((0, 0, 0.075)), (1, 0, 0), (0, 0, 1)), 1.0),
        "sirt": ("spine_03", _cerceve((0, sirt_y - 0.03, 1.30 * olcek), (math.sin(math.radians(-22)), 0, math.cos(math.radians(-22))), (0, -1, 0)), 1.0),
        "bel_sol": ("pelvis", _cerceve((-kalca_x - 0.02, 0.0, 0.99 * olcek), (0, math.sin(math.radians(-25)), math.cos(math.radians(-25))), (-1, 0, 0)), 1.0),
        "bel_sag": ("pelvis", _cerceve((kalca_x + 0.02, 0.0, 0.99 * olcek), (0, math.sin(math.radians(-25)), math.cos(math.radians(-25))), (1, 0, 0)), 1.0),
    }
    profil = {}
    for ad, (kemik, m, s) in yuvalar.items():
        e = bpy.data.objects.new("YUVA_" + ad, None)
        bpy.context.scene.collection.objects.link(e)
        e.parent = arm
        e.parent_type = "BONE"
        e.parent_bone = kemik
        m = R @ m
        e.matrix_world = m @ Matrix.Diagonal((s, s, s, 1))
        profil[ad] = {"kemik": kemik, "konum": [round(x, 4) for x in m.translation], "olcek": round(s, 3)}
    profil["_govde"] = {"bas_tepe": round(bas_tepe, 3), "bas_genislik": round(bas_gen, 3), "olcek": round(olcek, 3)}
    return profil
