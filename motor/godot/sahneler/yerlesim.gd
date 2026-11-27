extends RefCounted
## Sinematik paket 2 — prosedürel yerleşim: ordugâh. Dönemin çadırları kameranın baktığı tarafta, oyuncuların arkasında
## sıra sıra (hafif yay ve sapmalarla) kurulur; aralarına yük arabaları ve kamp ateşleri (alev + kıvılcım + duman
## parçacığı, titreşen ışık) serpilir. Kendi yazımımız; dokular Kenney Particle Pack (CC0). Tohumlu, belirlenimci.
const V := preload("res://sahneler/vfx.gd")
const D := preload("res://sahneler/donatici.gd")
const Mz := preload("res://sahneler/malzeme.gd")

static var _atesler: Array = []   # [OmniLight3D, taban enerji, faz]
static var _salinan: Array = []
static var k_spek := 0.3   # gerçekçi varlıkların aynasal yansıma gücü (is.json malzeme.spekuler)   # [Node3D, taban konum, taban yön, faz, derece] — su üstündeki gemi/sandal

static func _yerlestir(kok: Node3D, glb: String, p: Vector3, yon: float, olcek: float) -> void:
	var n := D.ekipman(glb)
	kok.add_child(n)
	n.position = p
	n.rotation.y = yon
	n.scale = Vector3.ONE * olcek

static func _ates(kok: Node3D, p: Vector3, k: Dictionary, tohum: int, t: float) -> void:
	var alev := CPUParticles3D.new()
	V._ortak(alev, {"doku": k["alev_doku"], "adet": 22, "omur": 0.7, "boyut": [0.5, 1.0], "opaklik": 0.95, "renk": [1.0, 0.62, 0.25]}, tohum, t)
	(alev.mesh.material as StandardMaterial3D).blend_mode = BaseMaterial3D.BLEND_MODE_ADD
	alev.position = p + Vector3(0, 0.15, 0)
	alev.emission_shape = CPUParticles3D.EMISSION_SHAPE_SPHERE
	alev.emission_sphere_radius = 0.25
	alev.direction = Vector3.UP
	alev.spread = 12.0
	alev.initial_velocity_min = 0.6
	alev.initial_velocity_max = 1.3
	alev.gravity = Vector3(0, 0.8, 0)
	kok.add_child(alev)
	var duman := CPUParticles3D.new()
	V._ortak(duman, {"doku": k["duman_doku"], "adet": 10, "omur": 5.0, "boyut": [1.2, 3.0], "opaklik": 0.35, "renk": [0.5, 0.48, 0.46]}, tohum + 7, t)
	duman.position = p + Vector3(0, 1.2, 0)
	duman.direction = Vector3(0.2, 1, 0)
	duman.spread = 10.0
	duman.initial_velocity_min = 0.6
	duman.initial_velocity_max = 1.0
	duman.gravity = Vector3(0.25, 0.1, 0)
	kok.add_child(duman)
	var isik := OmniLight3D.new()
	isik.light_color = Color(1.0, 0.62, 0.3)
	isik.omni_range = float(k.get("isik_menzil_m", 7.0))
	isik.light_energy = float(k.get("isik_guc", 1.6))
	isik.position = p + Vector3(0, 0.8, 0)
	kok.add_child(isik)
	_atesler.append([isik, isik.light_energy, float(tohum % 97)])

## Her karede: ateş ışığı titrer (iki sinüs; sabit kare hızında belirlenimci).
static func guncelle(t: float) -> void:
	for sl in _salinan:   # su üstündekiler dalgayla salınır (yalpa + baş-kıç vurma + hafif dikey)
		var n: Node3D = sl[0]
		var f: float = sl[3]
		var d: float = deg_to_rad(float(sl[4]))
		n.position = (sl[1] as Vector3) + Vector3(0, sin(t * 0.9 + f) * 0.12, 0)
		n.rotation = (sl[2] as Vector3) + Vector3(sin(t * 0.7 + f * 1.3) * d * 0.6, 0, sin(t * 0.83 + f) * d)
	for a in _atesler:
		var l: OmniLight3D = a[0]
		l.light_energy = float(a[1]) * (0.85 + 0.1 * sin(t * 11.0 + a[2]) + 0.05 * sin(t * 23.0 + a[2] * 1.7))

static func ordugah(kok: Node3D, k: Dictionary, ar: Dictionary, merkez: Vector3, ileri: Vector3, kameralar: Array,
		tohum: int, t: float) -> int:
	var r := RandomNumberGenerator.new()
	r.seed = tohum
	var yan := ileri.cross(Vector3.UP).normalized()
	var mesafe: Array = k.get("mesafe_m", [16.0, 60.0])
	var aralik := float(k.get("aralik_m", 9.0))
	var yer: Array = []
	var cadirlar: Array = k["cadirlar"]
	for deneme in int(k.get("adet", 14)) * 15:
		if yer.size() >= int(k.get("adet", 14)):
			break
		var d := r.randf_range(float(mesafe[0]), float(mesafe[1]))
		var p := merkez + ileri * d + yan * r.randf_range(-1.0, 1.0) * float(k.get("yan_oran", 0.5)) * d
		if Vector2(p.x - merkez.x, p.z - merkez.z).length() < float(k.get("oyuncu_payi_m", 10.0)):
			continue
		if preload("res://sahneler/serpme.gd")._gorus_uzakligi(p, kameralar) < float(k.get("gorus_payi_m", 4.0)):
			continue
		var iyi := true
		for q in yer:
			if p.distance_to(q) < aralik:
				iyi = false
				break
		if not iyi:
			continue
		yer.append(p)
	var n := 0
	for i in yer.size():
		var p: Vector3 = yer[i]
		p.y = V.zemin_y(p.x, p.z, ar)
		var yon := atan2(-ileri.x, -ileri.z) + r.randf_range(-0.5, 0.5)   # kapılar aşağı yukarı sahneye dönük
		if i % int(k.get("araba_her", 5)) == 4 and k.get("ekler", []).size() > 0:
			var ek: Array = k["ekler"]
			_yerlestir(kok, ek[r.randi() % ek.size()], p, yon + PI * 0.5, 1.0)
		else:
			_yerlestir(kok, cadirlar[r.randi() % cadirlar.size()], p, yon, r.randf_range(0.9, 1.1))
		n += 1
		if i % int(k.get("ates_her", 3)) == 1:
			var a := p + yan * r.randf_range(3.0, 4.5) * (1.0 if r.randf() < 0.5 else -1.0) + ileri * r.randf_range(-2.0, 2.0)
			a.y = V.zemin_y(a.x, a.z, ar)
			_ates(kok, a, k, tohum + i * 13, t)
	return n


## Mekân paketi — dizi yerleşimleri (kale, kasaba, liman, nehir iskelesi). Parçalar is.json "roller" altında dönem
## kataloğundan gelir; boş rol atlanır (uydurma yok). Yön: oyuncular kameraya bakıyor; yapılar onların arkasında.
static func _yon_aci(v: Vector3) -> float:
	return atan2(-v.z, v.x)   # model +X ekseni v'ye hizalanır (Y ekseni etrafında)

static func _sec(r: RandomNumberGenerator, liste: Array) -> String:
	return liste[r.randi() % liste.size()] if liste.size() > 0 else ""

static func _koy(kok: Node3D, glb: String, p: Vector3, yon: float, ar: Dictionary, olcek: float = 1.0, zemine := true) -> Node3D:
	if glb == "":
		return null
	var n := D.ekipman(glb)
	kok.add_child(n)
	if zemine:
		p.y = V.zemin_y(p.x, p.z, ar)
	n.position = p
	n.rotation.y = yon
	n.scale = Vector3.ONE * olcek
	Mz.uygula(n)   # mekân kalite paketi: düz renkli malzemelere PBR (kural yoksa etkisiz)
	if glb.contains("/mekan/"):
		Mz.gercek(n, float(k_spek))
	return n

static func _boy(k: Dictionary, glb: String, eksen: int = 0, varsayilan: float = 10.0) -> float:
	var b: Array = k.get("boylar", {}).get(glb, [])
	return float(b[eksen]) if b.size() > eksen else varsayilan

static func dizi(kok: Node3D, k: Dictionary, ar: Dictionary, merkez: Vector3, ileri: Vector3, kameralar: Array,
		tohum: int, t: float) -> int:
	var r := RandomNumberGenerator.new()
	r.seed = tohum
	var yan := ileri.cross(Vector3.UP).normalized()
	var rol: Dictionary = k["roller"]
	var n := 0
	match str(k["tur"]):
		"kale" when k.get("dose", false):   # gerçekçi modüler sur: kapı ortada, sur modülleri uç uca, uçlarda kule
			var d := float(k.get("mesafe_m", 34.0))
			var on := merkez + ileri * d
			var duz := _yon_aci(yan)
			var kapi := _sec(r, rol.get("kapi", []))
			if _koy(kok, kapi, on, duz, ar): n += 1
			var bind := float(k.get("bindirme_m", 0.4))
			for s in [-1.0, 1.0]:
				var x := _boy(k, kapi, 0, 7.0) * 0.5 - bind
				var son := float(k.get("sur_yari_m", 34.0))
				while x < son:
					var g := _sec(r, rol.get("sur", []))
					var L := _boy(k, g, 0, 14.0)
					if _koy(kok, g, on + yan * float(s) * (x + L * 0.5), duz + (PI if r.randf() < 0.5 else 0.0), ar): n += 1
					x += L - bind
				var kule := _sec(r, rol.get("kule", []))
				if _koy(kok, kule, on + yan * float(s) * (x + _boy(k, kule, 0, 8.0) * 0.3) + ileri * 1.0, duz, ar): n += 1
			if _koy(kok, _sec(r, rol.get("ic_kale", [])), on + ileri * 22.0, duz, ar, 1.3): n += 1
		"kale":
			var d := float(k.get("mesafe_m", 34.0))
			var on := merkez + ileri * d
			var duz := _yon_aci(yan)
			if _koy(kok, _sec(r, rol.get("kapi", [])), on, duz, ar): n += 1
			for s in [-1.0, 1.0]:
				if _koy(kok, _sec(r, rol.get("sur", [])), on + yan * float(s) * 21.5 + ileri * 1.5, duz + float(s) * 0.12, ar): n += 1
				if _koy(kok, _sec(r, rol.get("kule", [])), on + yan * float(s) * 36.0 + ileri * 6.0, duz, ar): n += 1
			if _koy(kok, _sec(r, rol.get("ic_kale", [])), on + ileri * 16.0, duz, ar, 1.3): n += 1
		"kasaba":
			var sy := float(k.get("sokak_yari_m", 7.5))
			var ar_: Array = k.get("aralik_m", [9.0, 12.0])
			for s in [-1.0, 1.0]:
				var d := float(k.get("bas_m", 12.0)) + r.randf_range(0.0, 4.0)
				while d < float(k.get("son_m", 70.0)):
					var p: Vector3 = merkez + ileri * d + yan * float(s) * (sy + r.randf_range(0.0, 1.5))
					var yuz: float = _yon_aci(ileri) + (PI * 0.5 if float(s) > 0 else -PI * 0.5)   # kapılar sokağa
					if r.randf() < 0.18 and rol.get("tezgah", []).size() > 0:
						_koy(kok, _sec(r, rol["tezgah"]), p - yan * float(s) * 3.0, yuz, ar)
						if rol.get("ayrinti", []).size() > 0:   # tezgâh yanında fıçı/sandık
							_koy(kok, _sec(r, rol["ayrinti"]), p - yan * float(s) * 4.6 + ileri * r.randf_range(1.5, 3.0), r.randf() * TAU, ar)
					elif _koy(kok, _sec(r, rol.get("ev", [])), p, yuz + r.randf_range(-0.08, 0.08), ar, r.randf_range(0.92, 1.08)):
						n += 1
					d += r.randf_range(float(ar_[0]), float(ar_[1]))
			if _koy(kok, _sec(r, rol.get("son", [])), merkez + ileri * (float(k.get("son_m", 70.0)) + 8.0), _yon_aci(yan), ar, 1.3): n += 1
		"liman", "nehir_iskelesi":
			var su: Dictionary = ar.get("su", {})
			var seviye := float(su.get("seviye_m", -0.4))
			var kiyi := float(su.get("bas_m", 16.0))
			var der := float(k.get("salinim_derece", 2.0))
			if su.get("tur", "") == "nehir":
				kiyi -= float(su.get("genislik_m", 14.0)) * 0.5
			var isk := merkez + ileri * (kiyi + 3.0) + yan * r.randf_range(-6.0, 6.0)
			isk.y = seviye + 0.35
			var iskele := _sec(r, rol.get("iskele", []))
			if str(k.get("iskele_yon", "yan")) == "ileri" and iskele != "":   # kıyıdan suya dik uzanan iskele
				var il_ := _boy(k, iskele, 0, 19.0)
				isk = merkez + ileri * (kiyi + il_ * 0.5 - 2.0) + yan * (r.randf_range(4.0, 9.0) * (1.0 if r.randf() < 0.5 else -1.0))
				isk.y = seviye - 1.2
				if _koy(kok, iskele, isk, _yon_aci(ileri), ar, 1.0, false): n += 1
				for j in rol.get("ayrinti", []).size() * 2:   # iskele dibinde, kıyıda fıçı/sandık
					var ap: Vector3 = isk - ileri * (il_ * 0.5 + r.randf_range(-1.0, 3.0)) + yan * r.randf_range(-4.0, 4.0)
					if V.su_k(ap.x, ap.z, ar) < 0.05 and _koy(kok, _sec(r, rol["ayrinti"]), ap, r.randf() * TAU, ar): n += 1
			elif _koy(kok, iskele, isk, _yon_aci(yan), ar, 1.0, false): n += 1
			var gm: Array = k.get("gemi_mesafe_m", [14.0, 60.0])
			var hedefler: Array = []
			for i in int(k.get("gemi_adet", 0)):
				var gy := float(k.get("gemi_yan_oran", 0.5))   # yanal yayılım (tele kadrajda gemiler görüş içinde kalsın)
				hedefler.append(["gemi", kiyi + float(su.get("kiyi_m", 8.0)) + r.randf_range(float(gm[0]), float(gm[1])), r.randf_range(-gy, gy)])
			for i in int(k.get("sandal_adet", 3)):
				var sy_ := float(k.get("sandal_yan_oran", 0.35))
				hedefler.append(["sandal", kiyi + r.randf_range(4.0, 12.0) + (float(su.get("genislik_m", 0.0)) * 0.3 if su.get("tur", "") == "nehir" else 0.0), r.randf_range(-sy_, sy_)])
			for h in hedefler:
				var dd: float = h[1]
				var p: Vector3 = merkez + ileri * dd + yan * float(h[2]) * dd
				if preload("res://sahneler/serpme.gd")._gorus_uzakligi(p, kameralar) < 3.0 and h[0] == "sandal":
					p += yan * 6.0
				if V.su_k(p.x, p.z, ar) < 0.9:   # yalnız açık suya
					continue
				p.y = seviye - (0.25 if h[0] == "gemi" else 0.05)
				var yon := _yon_aci(yan) + r.randf_range(-0.6, 0.6)
				var g := _koy(kok, _sec(r, rol.get(h[0], [])), p, yon, ar, 1.0, false)
				if g:
					_salinan.append([g, g.position, g.rotation, r.randf() * TAU, der * (1.0 if h[0] == "gemi" else 1.6)])
					n += 1
	return n
