extends RefCounted
## Sinematik paket — parçacık efektleri (CPU; Compatibility/llvmpipe uyumlu). Doku: Kenney Particle Pack (CC0,
## motor/varlik/kenney_parcacik). Hepsi tohumlu ve sabit kare hızında belirlenimci.
## toz: hızlı ilerleyen (at, koşan asker) karakterin arkasında yerden kalkan toz.
## duman: çarpışma sahnelerinde arka planda yavaş süzülen savaş dumanı / pus öbekleri.

static var _doku := {}

static func _tex(yol: String) -> Texture2D:
	if not _doku.has(yol):
		var img := Image.load_from_file(yol)
		img.generate_mipmaps()
		_doku[yol] = ImageTexture.create_from_image(img)
	return _doku[yol]

static func _malzeme(k: Dictionary) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.albedo_texture = _tex(k["doku"])
	m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.billboard_mode = BaseMaterial3D.BILLBOARD_PARTICLES
	m.billboard_keep_scale = true   # parçacık ölçeği (boyut) korunur
	m.vertex_color_use_as_albedo = true
	m.disable_receive_shadows = true
	m.cull_mode = BaseMaterial3D.CULL_DISABLED
	return m

static func _renk_rampa(renk: Array, opak: float) -> Gradient:
	var g := Gradient.new()
	var c := Color(renk[0], renk[1], renk[2])
	g.set_color(0, Color(c, 0.0))
	g.set_color(1, Color(c, 0.0))
	g.add_point(0.15, Color(c, opak))
	g.add_point(0.55, Color(c, opak * 0.6))
	return g

static func _ortak(p: CPUParticles3D, k: Dictionary, tohum: int, t: float) -> void:
	var q := QuadMesh.new()
	q.size = Vector2.ONE
	q.material = _malzeme(k)
	p.mesh = q
	p.amount = int(k.get("adet", 24))
	p.lifetime = float(k.get("omur", 1.8))
	p.use_fixed_seed = true
	p.seed = tohum
	p.color_ramp = _renk_rampa(k.get("renk", [0.8, 0.72, 0.6]), float(k.get("opaklik", 0.5)))
	var b: Array = k.get("boyut", [1.0, 2.5])
	p.scale_amount_min = float(b[0])
	p.scale_amount_max = float(b[1])
	var sc := Curve.new()
	sc.add_point(Vector2(0, 0.45))
	sc.add_point(Vector2(1, 1.0))
	p.scale_amount_curve = sc
	p.angle_min = -180.0
	p.angle_max = 180.0
	p.angular_velocity_min = -12.0
	p.angular_velocity_max = 12.0
	p.preprocess = minf(t + p.lifetime, p.lifetime * 2.0)   # önizleme/ilk kare: toz zaten havada
	p.fixed_fps = 30
	p.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF

static func toz(kok: Node3D, k: Dictionary, tohum: int, t: float) -> CPUParticles3D:
	var p := CPUParticles3D.new()
	_ortak(p, k, tohum, t)
	p.local_coords = false            # toz havada kalır, karakter ilerler
	p.position = Vector3(0, 0.25, float(k.get("geri_m", -0.9)))
	p.emission_shape = CPUParticles3D.EMISSION_SHAPE_BOX
	p.emission_box_extents = Vector3(0.5, 0.1, 0.4)
	p.direction = Vector3(0, 0.6, -1)
	p.spread = 35.0
	p.initial_velocity_min = 0.8
	p.initial_velocity_max = 2.2
	p.gravity = Vector3(0, 0.15, 0)
	p.damping_min = 0.8
	p.damping_max = 1.6
	kok.add_child(p)
	return p

## Zemin yüksekliği (ortam.gd ZEMIN_SHADER ile aynı formül; CPU kopyası, yaklaşık): efektler tepeye gömülmesin.
static func _h(p: Vector2) -> float:
	var v := sin(p.dot(Vector2(127.1, 311.7))) * 43758.5453
	return v - floor(v)

static func _n(p: Vector2) -> float:
	var i := p.floor()
	var f := p - i
	f = f * f * (Vector2(3, 3) - 2.0 * f)
	return lerpf(lerpf(_h(i), _h(i + Vector2(1, 0)), f.x), lerpf(_h(i + Vector2(0, 1)), _h(i + Vector2(1, 1)), f.x), f.y)

static func _fbm(p: Vector2) -> float:
	var s := 0.0
	var a := 0.5
	for i in 5:
		s += a * _n(p)
		p *= 2.03
		a *= 0.5
	return s

static func zemin_y(x: float, z: float, ar: Dictionary) -> float:
	var duz := float(ar.get("duz_yari", 6.0))
	var uzak := smoothstep(duz, duz * 10.0, absf(x - float(ar.get("yol_x", 0.0))))
	var w := Vector2(x, z)
	return _fbm(w * 0.02) * float(ar.get("tepe_yuksekligi", 14.0)) * uzak + _fbm(w * 0.25) * 0.35 * uzak

static func duman(sahne: Node3D, merkez: Vector3, ileri: Vector3, k: Dictionary, tohum: int, t: float, ar: Dictionary) -> void:
	var r := RandomNumberGenerator.new()
	r.seed = tohum
	var yan := ileri.cross(Vector3.UP).normalized()
	var mesafe: Array = k.get("mesafe_m", [14.0, 30.0])
	for i in int(k.get("obek", 4)):
		var p := CPUParticles3D.new()
		_ortak(p, k, tohum + i * 31, t)
		p.local_coords = true
		var d := r.randf_range(float(mesafe[0]), float(mesafe[1]))
		var q := merkez + ileri * d + yan * r.randf_range(-1.0, 1.0) * float(k.get("yan_oran", 0.2)) * d
		q.y = zemin_y(q.x, q.z, ar) + 1.0
		p.position = q
		p.emission_shape = CPUParticles3D.EMISSION_SHAPE_SPHERE
		p.emission_sphere_radius = float(k.get("yaricap_m", 3.0))
		p.direction = Vector3(0.3, 1, 0)
		p.spread = 25.0
		p.initial_velocity_min = 0.4
		p.initial_velocity_max = 1.1
		p.gravity = Vector3(0.12, 0.1, 0)
		sahne.add_child(p)
