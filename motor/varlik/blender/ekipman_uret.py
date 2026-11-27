"""Sert ekipman üreticisi (Blender içinde): python3 ekipman_uret.py <is.json>

is.json: {"parcalar": [{"id", "uretici", "p": {...}, "cikti"}], "malzemeler": {ad: {tur, renk, metalik, tohum, ikinci_renk}}}
Her parça ayrı bir GLB'ye yazılır (bir kez üretilir, bütün karakterlerde paylaşılır) ve ölçülür.
Eksen sözleşmesi (giysi.py ile aynı): +Z yukarı, -Y ön, köken = bağlantı noktası. Ölçüler metre, gerçek boyut.
Başlıkların kökeni referans erkek kafasının tepesidir (baş genişliği 0,182 m, alın tepeden ~0,11 m aşağıda).
"""
from __future__ import annotations

import json
import math
import os
import sys

import bpy  # noqa: I001
import bmesh
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ortak  # noqa: E402

IS = json.load(open(sys.argv[-1]))
MALZ = IS.get("malzemeler", {})


def M(ad):
    s = MALZ[ad]
    return ortak.malzeme(ad, s["tur"], s["renk"], s.get("tohum", 1), s.get("metalik", 0.0), s.get("boyut", 512), s.get("ikinci_renk"))


def _don(o, mat: Matrix):
    o.data.transform(mat)


def _tasi(o, v):
    o.data.transform(Matrix.Translation(Vector(v)))


def _kalinlastir(o, k):
    m = o.modifiers.new("kal", "SOLIDIFY")
    m.thickness = k
    m.offset = 0
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.modifier_apply(modifier="kal")


def _yiv(o, adet, derinlik, burgu=0.0):
    """Radyal yiv (oluk): sarık miğfer ve kalkan için."""
    for v in o.data.vertices:
        a = math.atan2(v.co.y, v.co.x) + v.co.z * burgu
        r = math.hypot(v.co.x, v.co.y)
        if r > 1e-4:
            s = 1 + derinlik * math.sin(a * adet)
            v.co.x *= s
            v.co.y *= s


def _yuzu_one(o):
    """Z ekseninde modellenmiş diski -Y'ye bakar hale getirir (kalkan yüzü)."""
    o.data.transform(Matrix.Rotation(math.radians(90), 4, "X"))


def _duz_uv(o, olcek, eksen=("x", "z")):
    me = o.data
    uv = me.uv_layers.active or me.uv_layers.new()
    for p in me.polygons:
        for li in p.loop_indices:
            c = me.vertices[me.loops[li].vertex_index].co
            uv.data[li].uv = (getattr(c, eksen[0]) / olcek + 0.5, getattr(c, eksen[1]) / olcek + 0.5)


def _kumas(gen, yuk, mat, ad, kirlangic=False, nx=16, ny=10):
    """Bayrak kumaşı: direğe bağlı kenar x=0, +x yönünde uzanır. Godot'ta rüzgâr gölgelendiricisiyle dalgalanır."""
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UVMap")
    V = [[bm.verts.new((gen * i / nx, 0, -yuk * j / ny)) for i in range(nx + 1)] for j in range(ny + 1)]
    for j in range(ny):
        for i in range(nx):
            if kirlangic and i >= nx * 0.7:
                orta = ny / 2
                if abs(j + 0.5 - orta) < (i - nx * 0.7) / (nx * 0.3) * orta * 0.8:
                    continue
            f = bm.faces.new((V[j][i], V[j][i + 1], V[j + 1][i + 1], V[j + 1][i]))
            for lp, (a, b) in zip(f.loops, ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1))):
                lp[uv].uv = (a / nx, 1 - b / ny)
    o = ortak.nesne(ad, bm, mat)
    return o


def _direk(uz, r, mat, alt=0.0, ad="direk"):
    return ortak.nesne(ad, ortak.torna([(r, alt + uz), (r, alt)], 16, 1.0), mat)


def _bant(z, r, mat, ad="bant", h=0.05):
    """Sapa sarılı deri/metal bant (tutuş yeri, halka)."""
    return ortak.nesne(ad, ortak.torna([(r, z + h / 2), (r * 1.25, z + h / 2 - 0.006), (r * 1.25, z - h / 2 + 0.006), (r, z - h / 2)], 16, 2.0), mat)


def _cikinti(r, mat, ad="gobek"):
    """Kalkan göbeği/perçin başı: -Y'ye bakan küçük kubbe."""
    o = ortak.nesne(ad, ortak.torna([(0.0, r * 0.7), (r * 0.6, r * 0.55), (r, 0.0)], 16, 2.0), mat)
    _don(o, Matrix.Rotation(math.radians(90), 4, "X"))
    return o


# ---------------------------------------------------------------- başlıklar
def yeniceri_borku(p):
    gov = ortak.nesne("bork", ortak.torna([((0.012, 0.012), 0.215), ((0.07, 0.08), 0.20), ((0.095, 0.105), 0.10),
                                           ((0.104, 0.118), -0.02), ((0.106, 0.121), -0.105), ((0.100, 0.115), -0.112)], 36, 3.0), M(p["kece"]))
    # sırta düşen geniş kumaş (yatırma): tepeden arkaya kıvrılıp enseden aşağı iner
    bm = bmesh.new()
    yol = [(0.20, 0.02), (0.17, 0.10), (0.08, 0.15), (-0.05, 0.155), (-0.20, 0.16), (-0.34, 0.15)]  # +Y = arka
    satir = []
    for z, y in yol:
        g = 0.075 if z > 0 else 0.07 + (-z) * 0.06
        satir.append([bm.verts.new((-g, y, z)), bm.verts.new((g, y, z))])
    for a, b in zip(satir, satir[1:]):
        bm.faces.new((a[0], a[1], b[1], b[0]))
    ortak.kutu_uv(bm, 3.0)
    yat = ortak.nesne("yatirma", bm, M(p["kece"]))
    _kalinlastir(yat, 0.012)
    return [gov, yat]


def osmanli_sarik(p):
    kavuk = ortak.nesne("kavuk", ortak.torna([(0.01, 0.20), (0.06, 0.19), (0.09, 0.12), (0.10, 0.02), (0.10, -0.06)], 28, 3.0), M(p["kavuk"]))
    prof = []
    for i in range(13):
        a = math.pi * i / 12
        prof.append(((0.115 + 0.055 * math.sin(a), 0.13 + 0.055 * math.sin(a)), -0.10 + 0.13 * (1 - math.cos(a)) / 2))
    sar = ortak.nesne("sarik", ortak.torna(prof[::-1], 40, 3.0), M(p["sarik"]))
    _yiv(sar, 18, 0.025, burgu=14)
    return [kavuk, sar]


def sarik_migfer(p):
    # Müzedeki sarık miğferler başı geniş bir soğan gibi sarar: kubbe baştan belirgin biçimde geniş ve yüksek
    prof = [((0.004, 0.004), 0.34), ((0.010, 0.010), 0.28), ((0.05, 0.055), 0.22), ((0.120, 0.128), 0.13),
            ((0.162, 0.170), 0.04), ((0.160, 0.168), -0.02), ((0.128, 0.136), -0.07), ((0.112, 0.122), -0.09),
            ((0.108, 0.120), -0.105)]
    kubbe = ortak.nesne("kubbe", ortak.torna(prof, 48, 2.0), M(p["celik"]))
    _yiv(kubbe, 24, 0.035, burgu=10)
    bant = ortak.nesne("bant", ortak.torna([((0.113, 0.123), -0.075), ((0.114, 0.124), -0.105)], 48, 2.0), M(p["sus"]))
    burun = ortak.nesne("burun", ortak.kutu(0.012, 0.006, 0.10, (0, 0.128, -0.15)), M(p["celik"]))
    # zincir perde (aventail): arkada ve yanlarda, yüzün önü açık
    perde = ortak.nesne("perde", ortak.torna([((0.110, 0.122), -0.10), ((0.13, 0.14), -0.22), ((0.15, 0.15), -0.34)],
                                             36, 3.0, aci=math.radians(260), kapali=False), M(p["zincir"]))
    _don(perde, Matrix.Rotation(math.radians(-40), 4, "Z"))  # boşluk -Y'de (yüz açık)
    return [kubbe, bant, burun, perde]


def turkmen_tacli_sarik(p):
    """Geç 15. yy Türkmen (Akkoyunlu/Karakoyunlu) minyatürlerinde görülen biçim: sarığın ortasından yükselen
    ince, uzun keçe külah ("taç"). Siluette sarığın üstünde dik bir çubuk olarak okunur."""
    prof = []
    for i in range(13):
        a = math.pi * i / 12
        prof.append(((0.108 + 0.05 * math.sin(a), 0.122 + 0.05 * math.sin(a)), -0.10 + 0.12 * (1 - math.cos(a)) / 2))
    sar = ortak.nesne("sarik", ortak.torna(prof[::-1], 40, 3.0), M(p["sarik"]))
    _yiv(sar, 16, 0.02, burgu=18)
    kulah = ortak.nesne("kulah", ortak.torna([(0.004, 0.25), (0.022, 0.24), (0.03, 0.12), (0.045, 0.02), (0.05, -0.02)], 20, 3.0), M(p["kulah"]))
    return [sar, kulah]


def kece_kulah(p):
    """Uzun, tepesi yuvarlak keçe külah (Anadolu halkı ve dervişler); sarıksız giyilir."""
    return [ortak.nesne("kulah", ortak.torna([(0.01, 0.24), (0.05, 0.22), (0.085, 0.12), (0.102, 0.02), (0.104, -0.06)], 28, 3.0), M(p["kece"]))]


def turkmen_kalpak(p):
    k = ortak.nesne("kalpak", ortak.torna([(0.02, 0.17), (0.08, 0.15), (0.105, 0.06), (0.108, -0.06)], 32, 3.0), M(p["kece"]))
    kenar = ortak.nesne("kenar", ortak.torna([(0.108, -0.10), (0.135, -0.07), (0.135, -0.03), (0.108, -0.05)], 32, 3.0), M(p["kurk"]))
    return [k, kenar]


def konik_migfer(p):
    kon = ortak.nesne("konik", ortak.torna([(0.003, 0.19), (0.04, 0.14), (0.09, 0.05), (0.112, -0.04), (0.112, -0.10)], 40, 2.0), M(p["celik"]))
    perde = ortak.nesne("perde", ortak.torna([(0.112, -0.09), (0.13, -0.20), (0.15, -0.31)], 36, 3.0, aci=math.radians(250), kapali=False), M(p["zincir"]))
    _don(perde, Matrix.Rotation(math.radians(-35), 4, "Z"))  # boşluk -Y'de (yüz açık)
    return [kon, perde]


def sapel_migfer(p):
    tas = ortak.nesne("tas", ortak.torna([(0.004, 0.10), (0.06, 0.085), (0.105, 0.02), (0.112, -0.07)], 40, 2.0), M(p["celik"]))
    sirt = ortak.nesne("sirt", ortak.kutu(0.006, 0.22, 0.012, (0, 0, 0.085)), M(p["celik"]))
    kenar = ortak.nesne("kenar", ortak.torna([(0.112, -0.07), (0.17, -0.085), (0.235, -0.115)], 40, 2.0), M(p["celik"]))
    _kalinlastir(kenar, 0.004)
    return [tas, sirt, kenar]


def montefortino(p):
    prof = [(0.004, 0.115), (0.012, 0.115), (0.012, 0.09), (0.04, 0.085), (0.085, 0.05), (0.110, -0.01), (0.115, -0.08)]
    kubbe = ortak.nesne("kubbe", ortak.torna(prof, 44, 2.0), M(p["tunc"]))
    tepe = ortak.nesne("tepe", ortak.torna([(0.0, 0.135), (0.02, 0.125), (0.012, 0.11)], 16, 2.0), M(p["tunc"]))
    ense = ortak.nesne("ense", ortak.torna([(0.115, -0.08), (0.15, -0.09), (0.16, -0.095)], 24, 2.0, aci=math.radians(110), kapali=False), M(p["tunc"]))
    _don(ense, Matrix.Rotation(math.radians(35), 4, "Z"))  # ense siperi arkada (+Y)
    _kalinlastir(ense, 0.004)
    parcalar = [kubbe, tepe, ense]
    if p.get("sorguc"):  # enine sorguç (centurio): kulaktan kulağa yarım daire tüy
        sor = ortak.nesne("sorguc", ortak.kutu(0.26, 0.035, 0.11, (0, 0, 0.17)), M(p["tuy"]))
        parcalar.append(sor)
    for s in (-1, 1):  # yanak koruyucuları
        bm = bmesh.new()
        pts = [(0.03, -0.075), (-0.045, -0.075), (-0.05, -0.17), (-0.01, -0.215), (0.04, -0.17)]
        vs = [bm.verts.new((s * 0.118, y, z)) for y, z in pts]
        bm.faces.new(vs)
        ortak.kutu_uv(bm, 3.0)
        y = ortak.nesne(f"yanak_{s}", bm, M(p["tunc"]))
        _kalinlastir(y, 0.004)
        _don(y, Matrix.Rotation(math.radians(-6 * s), 4, "Y"))
        parcalar.append(y)
    return parcalar


# ---------------------------------------------------------------- kalkanlar (yüz -Y'ye bakar, köken = kavrama)
def _disk_kalkan(r, derinlik, yuz_mat, kenar_mat, umbo_mat, umbo_r, adet_yiv=0):
    prof = [(0.001, derinlik)]
    for i in range(1, 13):
        t = i / 12
        prof.append((r * t, derinlik * (1 - t ** 2)))
    yuz = ortak.nesne("yuz", ortak.torna(prof, 48, 1.0), yuz_mat)
    _duz_uv(yuz, 2 * r * 1.05, ("x", "y"))
    _kalinlastir(yuz, 0.008)
    kenar = ortak.nesne("kenar", ortak.torna([(r - 0.015, 0.006), (r + 0.006, 0.004), (r + 0.006, -0.008), (r - 0.015, -0.006)], 48, 2.0), kenar_mat)
    umbo = ortak.nesne("umbo", ortak.torna([(0.001, derinlik + umbo_r * 0.55), (umbo_r * 0.6, derinlik + umbo_r * 0.4),
                                            (umbo_r, derinlik + 0.004), (umbo_r * 1.08, derinlik - 0.004)], 24, 2.0), umbo_mat)
    o = [yuz, kenar, umbo]
    for x in o:
        _yuzu_one(x)
        _tasi(x, (0, -0.02, 0))
    return o


def hasir_kalkan(p):
    return _disk_kalkan(0.31, 0.09, M(p["hasir"]), M(p["demir"]), M(p["demir"]), 0.07)


def celik_kalkan(p):
    o = _disk_kalkan(0.23, 0.07, M(p["celik"]), M(p["sus"]), M(p["celik"]), 0.05)
    for i in range(4):  # dört perçin göbeği
        a = math.pi / 4 + i * math.pi / 2
        b = ortak.nesne(f"gobek{i}", ortak.torna([(0.001, 0.012), (0.018, 0.006), (0.02, 0.0)], 12, 2.0), M(p["sus"]))
        _yuzu_one(b)
        _tasi(b, (0.12 * math.cos(a), -0.02 - 0.07 * (1 - (0.12 / 0.23) ** 2), 0.12 * math.sin(a)))
        o.append(b)
    return o


def pavez(p):
    bm = ortak.kutu(0.56, 0.03, 1.10, (0, -0.03, 0.12))
    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=6, use_grid_fill=True)
    o = ortak.nesne("pavez", bm, M(p["yuz"]))
    for v in o.data.vertices:  # dikey sırt çıkıntısı
        v.co.y -= 0.035 * max(0.0, 1 - abs(v.co.x) / 0.14)
    _duz_uv(o, 1.15, ("x", "z"))
    kenar = ortak.nesne("kenar", ortak.kutu(0.58, 0.02, 0.03, (0, -0.03, 0.67)), M(p["demir"]))
    percin = []
    for x, z in ((-0.2, 0.55), (0.2, 0.55), (-0.2, -0.3), (0.2, -0.3)):
        c = _cikinti(0.018, M(p["demir"]), "percin")
        _tasi(c, (x, -0.05, z))
        percin.append(c)
    return [o, kenar] + percin


def badem_kalkan(p):
    """Üstü düz, yanları aşağıda sivri uca kavuşan kalkan (yaklaşık 0,56 x 0,70 m)."""
    bm = bmesh.new()
    kont = [(-0.28, 0.24), (0.28, 0.24)]
    for i in range(1, 13):
        t = i / 12
        kont.append((0.28 * math.cos(t * math.pi / 2) ** 0.8, 0.24 - 0.70 * math.sin(t * math.pi / 2)))
    sag = kont[2:-1]
    kont += [(-x, z) for x, z in sag[::-1]]
    vs = [bm.verts.new((x, 0, z)) for x, z in kont]
    f = bm.faces.new(vs)
    bmesh.ops.inset_region(bm, faces=[f], thickness=0.03)       # kenar bandı
    bmesh.ops.inset_region(bm, faces=[f], thickness=0.08)       # iç halka (eğrilik için)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=1, use_grid_fill=True)
    o = ortak.nesne("badem", bm, M(p["yuz"]))
    for v in o.data.vertices:
        v.co.y = -0.06 * (1 - (v.co.x / 0.29) ** 2)
    _duz_uv(o, 0.95, ("x", "z"))
    _kalinlastir(o, 0.015)
    gobek = _cikinti(0.06, M(p.get("demir", p["yuz"])))
    _tasi(gobek, (0, -0.065, 0.02))
    return [o, gobek]


def scutum(p):
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UVMap")
    nx, nz = 16, 24
    V = []
    for j in range(nz + 1):
        z = -0.60 + 1.20 * j / nz
        w = 0.325 * math.sqrt(max(0.0, 1 - (z / 0.62) ** 2)) + 0.01
        row = []
        for i in range(nx + 1):
            x = -w + 2 * w * i / nx
            a = x / 0.42  # silindirik bükülme (kalkan gövdeyi sarar)
            row.append(bm.verts.new((0.42 * math.sin(a), -0.42 * (math.cos(a) - 1) - 0.06, z)))
        V.append(row)
    for j in range(nz):
        for i in range(nx):
            f = bm.faces.new((V[j][i], V[j][i + 1], V[j + 1][i + 1], V[j + 1][i]))
            for lp, (a, b) in zip(f.loops, ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1))):
                lp[uv].uv = (a / nx, b / nz)
    for v in bm.verts:
        v.co.y = -v.co.y
    o = ortak.nesne("scutum", bm, M(p["yuz"]))
    _kalinlastir(o, 0.015)
    spina = ortak.nesne("spina", ortak.kutu(0.04, 0.03, 1.10, (0, -0.075, 0)), M(p["yuz"]))
    umbo = ortak.nesne("umbo", ortak.kutu(0.22, 0.05, 0.13, (0, -0.09, 0)), M(p["demir"]))
    return [o, spina, umbo]


# ---------------------------------------------------------------- silahlar (bıçak +Z yönünde, köken = kabza ortası)
def _kabza(uz, r, mat, pommel_mat, pommel="top"):
    k = ortak.nesne("kabza", ortak.torna([(r, uz / 2), (r * 1.1, 0), (r, -uz / 2)], 12, 2.0), mat)
    if pommel == "top":
        pm = ortak.nesne("topuz", ortak.torna([(0.001, -uz / 2 - 0.045), (0.022, -uz / 2 - 0.03), (0.024, -uz / 2 - 0.018), (0.012, -uz / 2)], 14, 2.0), pommel_mat)
    else:  # disk (tekerlek topuz)
        pm = ortak.nesne("topuz", ortak.torna([(0.025, -uz / 2 - 0.01), (0.028, -uz / 2 - 0.03), (0.025, -uz / 2 - 0.05)], 16, 2.0), pommel_mat)
        _don(pm, Matrix.Translation((0, 0, -uz / 2 - 0.03)) @ Matrix.Rotation(math.radians(90), 4, "X") @ Matrix.Translation((0, 0, uz / 2 + 0.03)))
    return [k, pm]


def _bicak(uz, gen, kal, mat, egri=0.0, uc_kisa=0.12, bel=0.0, z0=0.0):
    bm = bmesh.new()
    n = 20
    ust, alt = [], []
    for i in range(n + 1):
        t = i / n
        z = z0 + uz * t
        w = gen * (1 - bel * math.sin(math.pi * t))
        if t > 1 - uc_kisa:
            w *= (1 - t) / uc_kisa
        y0 = egri * (t ** 2) * uz
        ust.append((bm.verts.new((0, y0 - w / 2, z)), bm.verts.new((kal / 2, y0, z)), bm.verts.new((0, y0 + w / 2, z)), bm.verts.new((-kal / 2, y0, z))))
    for a, b in zip(ust, ust[1:]):
        for k in range(4):
            bm.faces.new((a[k], a[(k + 1) % 4], b[(k + 1) % 4], b[k]))
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    ortak.kutu_uv(bm, 2.0)
    return ortak.nesne("bicak", bm, mat)


def osmanli_kilic(p):
    o = _kabza(0.11, 0.015, M(p["sap"]), M(p["sus"]))
    bal = ortak.nesne("balcak", ortak.kutu(0.025, 0.13, 0.018, (0, 0, 0.064)), M(p["sus"]))
    return o + [bal, _bicak(0.80, 0.035, 0.007, M(p["celik"]), egri=0.10, uc_kisa=0.10, z0=0.073)]


def duz_kilic(p):
    o = _kabza(0.12, 0.015, M(p["sap"]), M(p["celik"]), pommel="disk")
    bal = ortak.nesne("balcak", ortak.kutu(0.022, 0.20, 0.016, (0, 0, 0.068)), M(p["celik"]))
    return o + [bal, _bicak(0.80, 0.048, 0.006, M(p["celik"]), uc_kisa=0.12, z0=0.076)]


def gladius(p):
    o = _kabza(0.09, 0.016, M(p["sap"]), M(p["sap"]))
    kor = ortak.nesne("koruma", ortak.torna([(0.03, 0.065), (0.04, 0.055), (0.03, 0.045)], 16, 2.0), M(p["sap"]))
    return o + [kor, _bicak(0.62, 0.055, 0.007, M(p["celik"]), uc_kisa=0.16, bel=0.12, z0=0.068)]


def pilum(p):
    sap = _direk(1.30, 0.014, M(p["sap"]), alt=-0.55)
    sapma = ortak.nesne("baglanti", ortak.torna([(0.02, 0.80), (0.022, 0.75), (0.02, 0.70)], 12, 2.0), M(p["demir"]))
    demir = ortak.nesne("demir", ortak.torna([(0.0, 1.42), (0.012, 1.38), (0.005, 1.36), (0.005, 0.75)], 8, 2.0), M(p["demir"]))
    return [sap, sapma, demir, _bant(0.05, 0.014, M(p["demir"]), "tutus", 0.10)]


def mizrak(p):
    sap = _direk(2.45, 0.016, M(p["sap"]), alt=-1.0)
    uc = ortak.nesne("uc", ortak.torna([(0.0, 1.72), (0.012, 1.66), (0.022, 1.58), (0.026, 1.52), (0.018, 1.49), (0.01, 1.47),
                                        (0.018, 1.43), (0.018, 1.40)], 8, 2.0), M(p["celik"]))
    _don(uc, Matrix.Diagonal((1.0, 0.35, 1.0, 1.0)))
    dip = ortak.nesne("dip", ortak.torna([(0.016, -1.0), (0.012, -1.06), (0.0, -1.09)], 8, 2.0), M(p["demir"]))
    return [sap, uc, dip, _bant(0.0, 0.016, M(p["demir"]), "tutus", 0.12), _bant(1.37, 0.016, M(p["demir"]), "halka", 0.03)]


def kargi(p):
    """Uzun süvari mızrağı (kargı), ucun altında küçük çatallı flama. Mızrakla aynı sap ve uç; flama, uzak planda
    sopadan ayırt edilebilen bir siluet verir."""
    parcalar = mizrak(p)
    fl = _kumas(0.42, 0.16, M(p["flama"]), "flama", kirlangic=True, nx=10, ny=6)
    _tasi(fl, (0.02, 0, 1.40))
    return parcalar + [fl]


def gurz(p):
    sap = _direk(0.60, 0.015, M(p["sap"]), alt=-0.12)
    bas = ortak.nesne("bas", ortak.torna([(0.0, 0.58), (0.03, 0.56), (0.035, 0.50), (0.02, 0.46)], 16, 2.0), M(p["celik"]))
    o = [sap, bas]
    for i in range(8):
        a = i * math.pi / 4
        k = ortak.nesne(f"kanat{i}", ortak.kutu(0.05, 0.006, 0.10, (0.035, 0, 0.51)), M(p["celik"]))
        _don(k, Matrix.Rotation(a, 4, "Z"))
        o.append(k)
    return o


def turk_yayi(p):
    """Kompozit (refleks) yay: kabza kökende, kollar ±Z, uçlar öne (-Y) kıvrık. Kiriş düz."""
    bm = bmesh.new()
    pts = []
    for i in range(-12, 13):
        t = i / 12
        z = 0.55 * t
        y = 0.07 * (1 - t * t) - (0.05 * max(0, abs(t) - 0.8) / 0.2) ** 1.0
        pts.append((y, z))
    for (y0, z0), (y1, z1) in zip(pts, pts[1:]):
        r0 = 0.016 * (1 - 0.5 * abs(z0) / 0.55)
        r1 = 0.016 * (1 - 0.5 * abs(z1) / 0.55)
        a = [bm.verts.new((r0 * math.cos(k * math.pi / 3), y0 + r0 * math.sin(k * math.pi / 3), z0)) for k in range(6)]
        b = [bm.verts.new((r1 * math.cos(k * math.pi / 3), y1 + r1 * math.sin(k * math.pi / 3), z1)) for k in range(6)]
        for k in range(6):
            bm.faces.new((a[k], a[(k + 1) % 6], b[(k + 1) % 6], b[k]))
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    ortak.kutu_uv(bm, 2.0)
    yay = ortak.nesne("yay", bm, M(p["govde"]))
    kiris = ortak.nesne("kiris", ortak.torna([(0.0015, pts[-1][1]), (0.0015, pts[0][1])], 6, 1.0), M(p["kiris"]))
    _tasi(kiris, (0, pts[-1][0], 0))
    return [yay, kiris]


def arbalet(p):
    kundak = ortak.nesne("kundak", ortak.kutu(0.05, 0.06, 0.78, (0, 0, 0.18)), M(p["sap"]))
    ybm = ortak.kutu(0.70, 0.03, 0.025, (0, 0, 0.55))
    bmesh.ops.subdivide_edges(ybm, edges=[e for e in ybm.edges if abs(e.verts[0].co.x - e.verts[1].co.x) > 0.5], cuts=12)
    yay = ortak.nesne("yay", ybm, M(p["celik"]))
    for v in yay.data.vertices:
        v.co.z -= 0.08 * (v.co.x / 0.35) ** 2
    kiris = ortak.nesne("kiris", ortak.kutu(0.66, 0.004, 0.004, (0, 0.03, 0.47)), M(p["celik"]))
    tetik = ortak.nesne("tetik", ortak.kutu(0.012, 0.03, 0.10, (0, 0.05, 0.02)), M(p["celik"]))
    ceviz = _cikinti(0.02, M(p["celik"]), "ceviz")
    _tasi(ceviz, (0, 0.035, 0.30))
    uz = ortak.nesne("uzengi", ortak.torna([(0.06, 0.60), (0.065, 0.62)], 16, 1.0), M(p["celik"]))
    _don(uz, Matrix.Translation((0, 0, 0.61)) @ Matrix.Rotation(math.radians(90), 4, "X") @ Matrix.Translation((0, 0, -0.61)))
    return [kundak, yay, uz, kiris, tetik, ceviz]


def hancer(p):
    kin = ortak.nesne("kin", ortak.torna([(0.018, 0.0), (0.02, -0.12), (0.012, -0.24), (0.0, -0.27)], 10, 2.0), M(p["kin"]))
    _don(kin, Matrix.Diagonal((1.0, 0.45, 1.0, 1.0)))
    sap = ortak.nesne("sap", ortak.torna([(0.012, 0.11), (0.016, 0.06), (0.013, 0.0)], 10, 2.0), M(p["sap"]))
    return [kin, sap]


def kese(p):
    k = ortak.nesne("kese", ortak.torna([(0.03, 0.02), (0.07, -0.03), (0.07, -0.10), (0.05, -0.15), (0.0, -0.16)], 16, 2.0), M(p["deri"]))
    _don(k, Matrix.Diagonal((1.0, 0.5, 1.0, 1.0)))
    return [k]


def sadak(p):
    tup = ortak.nesne("tup", ortak.torna([(0.055, 0.30), (0.06, 0.25), (0.05, -0.30), (0.0, -0.33)], 16, 2.0), M(p["deri"]))
    _don(tup, Matrix.Diagonal((1.0, 0.55, 1.0, 1.0)))
    o = [tup]
    for i in range(7):
        a = i * 2 * math.pi / 7
        ok = ortak.nesne(f"ok{i}", ortak.torna([(0.004, 0.40), (0.004, 0.10)], 6, 1.0), M(p["ok"]))
        tuy = ortak.nesne(f"tuy{i}", ortak.kutu(0.002, 0.025, 0.08, (0, 0, 0.38)), M(p["tuy"]))
        for x in (ok, tuy):
            _tasi(x, (0.028 * math.cos(a), 0.015 * math.sin(a), 0))
        o += [ok, tuy]
    return o


# ---------------------------------------------------------------- sancaklar (direk +Z, köken = kavrama)
def _alem(mat, z):
    return ortak.nesne("alem", ortak.torna([(0.0, z + 0.12), (0.035, z + 0.07), (0.038, z + 0.05), (0.02, z + 0.02), (0.012, z)], 16, 2.0), mat)


def sancak(p):
    direk = _direk(p.get("boy", 3.0), 0.02, M(p["direk"]), alt=-1.0)
    ust = -1.0 + p.get("boy", 3.0)
    o = [direk, _alem(M(p["alem"]), ust)]
    k = _kumas(p.get("gen", 1.1), p.get("yuk", 0.75), M(p["kumas"]), "kumas", kirlangic=p.get("kirlangic", False))
    _tasi(k, (0.02, 0, ust - 0.05))
    o.append(k)
    return o


def tug(p):
    direk = _direk(2.8, 0.02, M(p["direk"]), alt=-1.0)
    o = [direk, _alem(M(p["alem"]), 1.8)]
    sac = ortak.nesne("sac", ortak.torna([(0.03, 1.78), (0.07, 1.65), (0.11, 1.30), (0.09, 1.05)], 24, 3.0), M(p["sac"]))
    _yiv(sac, 30, 0.12)
    o.append(sac)
    return o


def vexillum(p):
    direk = _direk(2.6, 0.02, M(p["direk"]), alt=-1.0)
    capraz = ortak.nesne("capraz", ortak.torna([(0.012, 0.45), (0.012, -0.45)], 8, 1.0), M(p["direk"]))
    _don(capraz, Matrix.Translation((0, 0, 1.45)) @ Matrix.Rotation(math.radians(90), 4, "Y"))
    k = _kumas(0.80, 0.70, M(p["kumas"]), "kumas", nx=10, ny=10)
    _tasi(k, (-0.40, 0, 1.43))
    uc = ortak.nesne("uc", ortak.torna([(0.0, 1.78), (0.02, 1.65), (0.008, 1.6)], 6, 2.0), M(p["alem"]))
    return [direk, capraz, k, uc]


def aquila(p):
    direk = _direk(2.4, 0.02, M(p["direk"]), alt=-1.0)
    kaide = ortak.nesne("kaide", ortak.kutu(0.10, 0.06, 0.05, (0, 0, 1.42)), M(p["altin"]))
    govde = ortak.nesne("govde", ortak.torna([(0.0, 1.62), (0.035, 1.58), (0.045, 1.52), (0.03, 1.45)], 12, 2.0), M(p["altin"]))
    o = [direk, kaide, govde]
    for s in (-1, 1):
        bm = bmesh.new()
        vs = [bm.verts.new(c) for c in ((0.02 * s, 0, 1.56), (0.16 * s, 0.0, 1.66), (0.24 * s, -0.02, 1.70), (0.20 * s, 0, 1.58), (0.04 * s, 0, 1.50))]
        bm.faces.new(vs if s > 0 else vs[::-1])
        ortak.kutu_uv(bm, 3.0)
        k = ortak.nesne(f"kanat{s}", bm, M(p["altin"]))
        _kalinlastir(k, 0.01)
        o.append(k)
    bas = ortak.nesne("bas", ortak.torna([(0.0, 1.69), (0.022, 1.665), (0.02, 1.63)], 10, 2.0), M(p["altin"]))
    _tasi(bas, (0, -0.02, 0))
    return o + [bas]


# ---------------------------------------------------------------- çevre (köken = zemin merkezi; +Z yukarı)
def osmanli_cadiri(p):
    duvar = ortak.nesne("duvar", ortak.torna([(2.0, 1.9), (2.0, 0.0)], 40, 0.6), M(p["kumas"]))
    cati = ortak.nesne("cati", ortak.torna([(0.05, 4.1), (0.9, 3.4), (2.15, 1.95), (2.2, 1.85)], 40, 0.6), M(p["kumas"]))
    sacak = ortak.nesne("sacak", ortak.torna([(2.21, 1.97), (2.21, 1.62)], 40, 0.6), M(p["bant"]))
    for v in sacak.data.vertices:  # dilimli saçak
        if v.co.z < 1.7:
            a = math.atan2(v.co.y, v.co.x)
            v.co.z += 0.12 * abs(math.sin(a * 20))
    direk = _direk(4.5, 0.05, M(p["direk"]))
    return [duvar, cati, sacak, direk, _alem(M(p["alem"]), 4.5)]


def topak_ev(p):
    duvar = ortak.nesne("duvar", ortak.torna([(2.5, 1.45), (2.5, 0.0)], 40, 0.5), M(p["kece"]))
    kubbe = ortak.nesne("kubbe", ortak.torna([(0.35, 2.85), (1.2, 2.6), (2.1, 2.0), (2.55, 1.45)], 40, 0.5), M(p["kece"]))
    tunluk = ortak.nesne("tunluk", ortak.torna([(0.36, 2.88), (0.42, 2.82)], 24, 1.0), M(p["ahsap"]))
    kapi = ortak.nesne("kapi", ortak.kutu(0.9, 0.08, 1.25, (0, -2.5, 0.63)), M(p["ahsap"]))
    ip = ortak.nesne("ip", ortak.torna([(2.52, 1.05), (2.52, 0.95)], 40, 1.0), M(p["ip"]))
    return [duvar, kubbe, tunluk, kapi, ip]


def roma_cadiri(p):
    bm = bmesh.new()
    a, b, h = 1.5, 1.6, 1.9
    v = [bm.verts.new(c) for c in ((-a, -b, 0), (a, -b, 0), (0, -b, h), (-a, b, 0), (a, b, 0), (0, b, h))]
    for f in ((v[0], v[2], v[5], v[3]), (v[1], v[4], v[5], v[2]), (v[0], v[1], v[2]), (v[3], v[5], v[4])):
        bm.faces.new(f)
    ortak.kutu_uv(bm, 0.7)
    o = ortak.nesne("cadir", bm, M(p["deri"]))
    mertek = ortak.nesne("mertek", ortak.kutu(0.05, 3.3, 0.05, (0, 0, h + 0.02)), M(p["ahsap"]))
    return [o, mertek]


def sur_kule(p):
    sur = ortak.nesne("sur", ortak.kutu(8.0, 2.5, 7.0, (0, 0, 3.5)), M(p["tas"]))
    _duz_uv(sur, 4.0, ("x", "z"))
    o = [sur]
    for i in range(9):  # mazgallar
        o.append(ortak.nesne(f"mazgal{i}", ortak.kutu(0.55, 2.5, 0.8, (-3.6 + i * 0.9, 0, 7.4)), M(p["tas"])))
    for z in (2.0, 4.5):  # tuğla hatıllar (Theodosius surlarındaki gibi)
        o.append(ortak.nesne(f"hatil{z}", ortak.kutu(8.02, 2.52, 0.35, (0, 0, z)), M(p["tugla"])))
    kule = ortak.nesne("kule", ortak.kutu(4.0, 4.0, 11.0, (5.5, 0.6, 5.5)), M(p["tas"]))
    _duz_uv(kule, 4.0, ("x", "z"))
    o.append(kule)
    for i in range(4):
        o.append(ortak.nesne(f"kmazgal{i}", ortak.kutu(0.6, 4.0, 0.8, (4.0 + i * 1.0, 0.6, 11.4)), M(p["tas"])))
    return o


# ---------------------------------------------------------------- Faz 5.6: genel savaş/ordugâh çevre varlıkları
def _teker(r, gen, mat, ad, konum, parmak=8):
    """Tahta tekerlek (jant + göbek + parmaklar); dingil X ekseninde."""
    jant = ortak.nesne(ad, ortak.torna([(r, gen / 2), (r, -gen / 2), (r * 0.86, -gen / 2), (r * 0.86, gen / 2)], 28, 0.5), mat)
    gobek = ortak.nesne(ad + "_gobek", ortak.torna([(r * 0.16, gen * 0.9), (r * 0.16, -gen * 0.9)], 14, 0.5), mat)
    o = [jant, gobek]
    for i in range(parmak):
        a = math.pi * i / parmak
        k = ortak.nesne(f"{ad}_parmak{i}", ortak.kutu(r * 1.74, gen * 0.45, gen * 0.45, (0, 0, 0)), mat)
        _don(k, Matrix.Rotation(a, 4, "Y"))
        o.append(k)
    for x in o:
        _don(x, Matrix.Rotation(math.pi / 2, 4, "Y"))   # tekerlek düzlemi YZ, dingil X
        _tasi(x, konum)
    return o


def top_arabasi(p):
    """15.-16. yy sahra topu: tunç namlu, iki tekerlekli kundak (temsilî, genel)."""
    namlu = ortak.nesne("namlu", ortak.torna([(0.09, 1.25), (0.11, 1.2), (0.12, 0.6), (0.15, -0.55), (0.17, -0.6), (0.13, -0.75), (0.05, -0.82)], 24, 0.6), M(p["namlu"]))
    _don(namlu, Matrix.Rotation(math.radians(80), 4, "X"))   # namlu öne (-Y) ve hafif yukarı
    _tasi(namlu, (0, -0.25, 0.82))
    agiz = ortak.nesne("agiz", ortak.torna([(0.06, 0.02), (0.06, -0.3)], 16, 0.6), M(p["demir"]))
    _don(agiz, Matrix.Rotation(math.radians(80), 4, "X"))
    _tasi(agiz, (0, -1.43, 1.03))
    kundak = ortak.nesne("kundak", ortak.kutu(0.34, 2.4, 0.18, (0, 0.55, 0.55)), M(p["ahsap"]))
    _don(kundak, Matrix.Rotation(math.radians(-12), 4, "X"))
    dingil = ortak.nesne("dingil", ortak.kutu(1.25, 0.12, 0.12, (0, -0.1, 0.55)), M(p["ahsap"]))
    o = [namlu, agiz, kundak, dingil]
    for sx in (-0.58, 0.58):
        o += _teker(0.55, 0.09, M(p["ahsap"]), f"teker{'s' if sx < 0 else 'd'}", (sx, -0.1, 0.55))
    return o


def yuk_arabasi(p):
    """Dört tekerlekli ahşap yük/ordu arabası (genel; ordugâh, ikmal, tabur)."""
    kasa = ortak.nesne("kasa", ortak.kutu(1.4, 3.0, 0.1, (0, 0, 0.85)), M(p["ahsap"]))
    _duz_uv(kasa, 1.0, ("x", "y"))
    o = [kasa]
    for sx in (-0.7, 0.7):
        o.append(ortak.nesne(f"yan{sx}", ortak.kutu(0.06, 3.0, 0.45, (sx, 0, 1.12)), M(p["ahsap"])))
    for sy in (-1.5, 1.5):
        o.append(ortak.nesne(f"on{sy}", ortak.kutu(1.4, 0.06, 0.45, (0, sy, 1.12)), M(p["ahsap"])))
    for sy in (-1.05, 1.05):
        o.append(ortak.nesne(f"dingil{sy}", ortak.kutu(1.75, 0.1, 0.1, (0, sy, 0.48)), M(p["ahsap"])))
        for sx in (-0.82, 0.82):
            o += _teker(0.48, 0.08, M(p["ahsap"]), f"teker{sx}{sy}", (sx, sy, 0.48))
    oku = ortak.nesne("oku", ortak.kutu(0.08, 1.6, 0.08, (0, -2.3, 0.55)), M(p["ahsap"]))
    o.append(oku)
    yuk = ortak.nesne("yuk", ortak.torna([(0.62, 1.55), (0.66, 1.2), (0.6, 0.9)], 20, 0.6), M(p["ortu"]))
    _don(yuk, Matrix.Diagonal((1.0, 2.0, 1.0, 1.0)))
    o.append(yuk)
    return o


URETICILER = {f.__name__: f for f in [yeniceri_borku, osmanli_sarik, sarik_migfer, turkmen_tacli_sarik, kece_kulah, turkmen_kalpak, konik_migfer, sapel_migfer, montefortino,
                                      hasir_kalkan, celik_kalkan, pavez, badem_kalkan, scutum, osmanli_kilic, duz_kilic, gladius, pilum, mizrak,
                                      gurz, kargi, turk_yayi, arbalet, hancer, kese, sadak, sancak, tug, vexillum, aquila, osmanli_cadiri, topak_ev,
                                      roma_cadiri, sur_kule, top_arabasi, yuk_arabasi]}


def olc(o) -> dict:
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bm.normal_update()
    yalniz = sum(1 for v in bm.verts if not v.link_faces)
    bozuk = sum(1 for f in bm.faces if f.calc_area() < 1e-9)
    xs = [v.co.x for v in bm.verts]
    ys = [v.co.y for v in bm.verts]
    zs = [v.co.z for v in bm.verts]
    ucgen = sum(len(f.verts) - 2 for f in bm.faces)
    bm.free()
    return {"ucgen": ucgen, "kose": len(o.data.vertices), "yalniz_kose": yalniz, "bozuk_yuz": bozuk,
            "boyut_m": [round(max(xs) - min(xs), 3), round(max(ys) - min(ys), 3), round(max(zs) - min(zs), 3)],
            "min": [round(min(xs), 3), round(min(ys), 3), round(min(zs), 3)], "max": [round(max(xs), 3), round(max(ys), 3), round(max(zs), 3)],
            "malzeme": len(o.data.materials), "doku": sorted({max(i.size) for i in bpy.data.images if i.size[0] > 0})}


for parca in IS["parcalar"]:
    ortak.sifirla()
    nesneler = URETICILER[parca["uretici"]](parca.get("p", {}))
    for o in nesneler:
        for m in o.modifiers:
            bpy.context.view_layer.objects.active = o
            bpy.ops.object.modifier_apply(modifier=m.name)
    o = ortak.birlestir(nesneler, parca["id"])
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    # hiçbir yüze bağlı olmayan köşe (üretim artığı) model bütünlüğünü bozar: silinir
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bm.to_mesh(o.data)
    bm.free()
    bpy.data.orphans_purge(do_recursive=True)
    sonuc = olc(o)
    bpy.ops.export_scene.gltf(filepath=parca["cikti"], export_format="GLB", export_image_format="WEBP", export_yup=True, use_selection=False)
    sonuc["bayt"] = os.path.getsize(parca["cikti"])
    json.dump(sonuc, open(parca["cikti"].replace(".glb", ".olc.json"), "w"))
    print("URETILDI", parca["id"], sonuc["ucgen"], sonuc["bayt"])
