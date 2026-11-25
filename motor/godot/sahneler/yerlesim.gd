extends RefCounted
## Sinematik paket 2 — prosedürel yerleşim: ordugâh. Dönemin çadırları kameranın baktığı tarafta, oyuncuların arkasında
## sıra sıra (hafif yay ve sapmalarla) kurulur; aralarına yük arabaları ve kamp ateşleri (alev + kıvılcım + duman
## parçacığı, titreşen ışık) serpilir. Kendi yazımımız; dokular Kenney Particle Pack (CC0). Tohumlu, belirlenimci.
const V := preload("res://sahneler/vfx.gd")
const D := preload("res://sahneler/donatici.gd")

static var _atesler: Array = []   # [OmniLight3D, taban enerji, faz]

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
