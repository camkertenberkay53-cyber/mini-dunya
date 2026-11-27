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
	var y := _fbm(w * 0.02) * float(ar.get("tepe_yuksekligi", 14.0)) * uzak + _fbm(w * 0.25) * 0.35 * uzak
	return lerpf(y, -float(ar.get("su", {}).get("derin_m", 4.0)), su_k(x, z, ar))

## Su oyuğu katsayısı (ortam.gd ZEMIN_SHADER su_alcal kopyası): 0 kara, 1 su altı.
static func su_k(x: float, z: float, ar: Dictionary) -> float:
	var su: Dictionary = ar.get("su", {})
	if not su.get("tur", "") in ["deniz", "nehir"]:
		return 0.0
	var yon := Vector2(su["yon"][0], su["yon"][1]).normalized()
	var d := (Vector2(x, z) - Vector2(su["merkez"][0], su["merkez"][1])).dot(yon) - float(su.get("bas_m", 30.0))
	if su["tur"] == "deniz":
		return smoothstep(0.0, float(su.get("kiyi_m", 10.0)), d)
	var g := float(su.get("genislik_m", 14.0)) * 0.5
	return 1.0 - smoothstep(g, g + float(su.get("kiyi_m", 10.0)), absf(d))

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


## Top atışı: namlu ağzında kısa alev + kıvılcım (toplamalı karışım), kalın beyaz barut dumanı, anlık ışık. Atış anları
## tohumlu ve sabittir (kare hızında belirlenimci); önizleme anı t'den önceki son atışın dumanı ön işlemeyle görünür.
static func top_atisi(sahne: Node3D, top: Node3D, k: Dictionary, tohum: int, t: float) -> Dictionary:
	var r := RandomNumberGenerator.new()
	r.seed = tohum
	var agiz: Array = k.get("agiz_yerel", [0.0, 1.0, 1.7])
	var p := top.global_transform * Vector3(agiz[0], agiz[1], agiz[2])
	var yon := (top.global_transform.basis * Vector3(0, 0.15, 1)).normalized()
	var alev := CPUParticles3D.new()
	_ortak(alev, {"doku": k["alev_doku"], "adet": 16, "omur": 0.25, "boyut": [0.8, 1.8], "opaklik": 1.0, "renk": [1.0, 0.75, 0.4]}, tohum, 0.0)
	(alev.mesh.material as StandardMaterial3D).blend_mode = BaseMaterial3D.BLEND_MODE_ADD
	alev.one_shot = true
	alev.explosiveness = 0.95
	alev.preprocess = 0.0
	alev.emitting = false
	alev.position = p
	alev.direction = yon
	alev.spread = 18.0
	alev.initial_velocity_min = 4.0
	alev.initial_velocity_max = 9.0
	alev.gravity = Vector3.ZERO
	sahne.add_child(alev)
	var duman := CPUParticles3D.new()
	_ortak(duman, {"doku": k["duman_doku"], "adet": 30, "omur": 5.0, "boyut": [3.0, 6.5], "opaklik": 0.85, "renk": [0.88, 0.87, 0.84]}, tohum + 3, 0.0)
	duman.one_shot = true
	duman.explosiveness = 0.8
	duman.preprocess = 0.0
	duman.emitting = false
	duman.position = p
	duman.direction = yon
	duman.spread = 25.0
	duman.initial_velocity_min = 2.0
	duman.initial_velocity_max = 6.0
	duman.damping_min = 2.0
	duman.damping_max = 3.5
	duman.gravity = Vector3(0.2, 0.25, 0)
	sahne.add_child(duman)
	var isik := OmniLight3D.new()
	isik.light_color = Color(1.0, 0.7, 0.4)
	isik.omni_range = 9.0
	isik.light_energy = 0.0
	isik.position = p
	sahne.add_child(isik)
	var anlar: Array = []
	var s := r.randf_range(0.3, 1.2)
	while s < 60.0:
		anlar.append(s)
		s += r.randf_range(float(k.get("aralik_sn", [2.2, 3.4])[0]), float(k.get("aralik_sn", [2.2, 3.4])[1]))
	return {"alev": alev, "duman": duman, "isik": isik, "anlar": anlar, "son": -1.0, "guc": float(k.get("isik_guc", 6.0))}

static func top_guncelle(d: Dictionary, t: float) -> void:
	var son := -1.0
	for a in d["anlar"]:
		if a <= t:
			son = a
	if son >= 0.0 and son != float(d["son"]):
		d["son"] = son
		(d["alev"] as CPUParticles3D).restart()
		(d["duman"] as CPUParticles3D).restart()
	var gecen := t - float(d["son"]) if float(d["son"]) >= 0.0 else 99.0
	(d["isik"] as OmniLight3D).light_energy = float(d["guc"]) * maxf(0.0, 1.0 - gecen / 0.15)


## --- Olaya bağlı savaş efektleri (kendi yazımımız) ---
## Ok yağmuru: arkadan atılan yaylım oklar parabolle uçar, iniş alanına saplanır. Oklar tek MultiMesh (ince gövde +
## koyu temren); her kare konum/yön analitik hesaplanır (kare hızından bağımsız, belirlenimci). Atış anları tohumlu.
static func _ok_agi() -> Mesh:
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var govde := BoxMesh.new()
	govde.size = Vector3(0.012, 0.012, 0.78)
	st.append_from(govde, 0, Transform3D())
	var ucu := BoxMesh.new()
	ucu.size = Vector3(0.022, 0.022, 0.07)
	st.append_from(ucu, 0, Transform3D(Basis(), Vector3(0, 0, 0.42)))
	var tuy := BoxMesh.new()
	tuy.size = Vector3(0.05, 0.003, 0.12)
	st.append_from(tuy, 0, Transform3D(Basis(), Vector3(0, 0, -0.33)))
	var m := st.commit()
	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color(0.22, 0.17, 0.12)
	mat.roughness = 0.8
	m.surface_set_material(0, mat)
	return m

static func ok_yagmuru(sahne: Node3D, merkez: Vector3, ileri: Vector3, k: Dictionary, tohum: int, ar: Dictionary) -> Dictionary:
	var r := RandomNumberGenerator.new()
	r.seed = tohum
	var yan := ileri.cross(Vector3.UP).normalized()
	var n := int(k.get("adet", 90))
	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	mm.mesh = _ok_agi()
	mm.instance_count = n
	var mi := MultiMeshInstance3D.new()
	mi.multimesh = mm
	mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	sahne.add_child(mi)
	var oklar: Array = []
	var yaylim: Array = k.get("yaylim_sn", [0.2, 1.9])
	var ucus := float(k.get("ucus_sn", 1.6))
	var alan := float(k.get("alan_m", 14.0))
	for i in n:
		var t0 := float(yaylim[i % yaylim.size()]) + r.randf_range(0.0, 0.35)
		var bitis := merkez + ileri * r.randf_range(-alan * 0.4, alan * 0.6) + yan * r.randf_range(-alan, alan)
		bitis.y = zemin_y(bitis.x, bitis.z, ar) + 0.05
		var bas := bitis + ileri * float(k.get("menzil_m", 70.0)) + yan * r.randf_range(-6.0, 6.0)   # sahnenin ardından gelir
		bas.y = bitis.y + 2.0
		var tepe := float(k.get("tepe_m", 22.0)) * r.randf_range(0.85, 1.15)
		oklar.append([t0, bas, bitis, tepe, ucus * r.randf_range(0.92, 1.08)])
	return {"mm": mm, "oklar": oklar}

static func ok_guncelle(d: Dictionary, t: float) -> void:
	var mm: MultiMesh = d["mm"]
	for i in d["oklar"].size():
		var o: Array = d["oklar"][i]
		var u := (t - float(o[0])) / float(o[4])
		if u < 0.0:
			mm.set_instance_transform(i, Transform3D(Basis().scaled(Vector3.ZERO), Vector3.ZERO))   # henüz atılmadı
			continue
		var uu := clampf(u, 0.0, 1.0)
		var p0: Vector3 = o[1]
		var p1: Vector3 = o[2]
		var p := p0.lerp(p1, uu) + Vector3.UP * float(o[3]) * 4.0 * uu * (1.0 - uu)
		var ileri := (p1 - p0) + Vector3.UP * float(o[3]) * 4.0 * (1.0 - 2.0 * uu)   # türev: hız yönü
		if u >= 1.0:   # saplanmış ok: son yönde, ucu toprağa gömülü
			ileri = (p1 - p0) + Vector3.UP * float(o[3]) * -4.0
			p = p1 + ileri.normalized() * 0.18
		var z := ileri.normalized()
		var x := Vector3.UP.cross(z).normalized()
		if x.length() < 0.01:
			x = Vector3.RIGHT
		mm.set_instance_transform(i, Transform3D(Basis(x, z.cross(x), z), p))

## Yangın: alev (toplamalı), duman sütunu ve titreşen sıcak ışık. Konum: sahnedeki çevre varlıkları (çadır/ev)
## varsa onların üstü, yoksa sahnenin ardında tohumlu noktalar.
static func yangin(sahne: Node3D, noktalar: Array, k: Dictionary, tohum: int, t: float) -> Array:
	var isiklar: Array = []
	for i in noktalar.size():
		var p: Vector3 = noktalar[i]
		var alev := CPUParticles3D.new()
		_ortak(alev, {"doku": k["alev_doku"], "adet": 26, "omur": 0.9, "boyut": [0.9, 2.2], "opaklik": 0.95, "renk": [1.0, 0.62, 0.25]}, tohum + i * 13, t)
		(alev.mesh.material as StandardMaterial3D).blend_mode = BaseMaterial3D.BLEND_MODE_ADD
		alev.position = p
		alev.emission_shape = CPUParticles3D.EMISSION_SHAPE_SPHERE
		alev.emission_sphere_radius = float(k.get("yaricap_m", 1.2))
		alev.direction = Vector3.UP
		alev.spread = 12.0
		alev.initial_velocity_min = 1.2
		alev.initial_velocity_max = 2.6
		alev.gravity = Vector3(0, 0.6, 0)
		sahne.add_child(alev)
		var duman := CPUParticles3D.new()
		_ortak(duman, {"doku": k["duman_doku"], "adet": 18, "omur": 6.0, "boyut": [3.0, 8.0], "opaklik": 0.7, "renk": [0.16, 0.15, 0.14]}, tohum + i * 17, t)
		duman.position = p + Vector3.UP * 2.0
		duman.direction = Vector3(0.15, 1, 0)
		duman.spread = 10.0
		duman.initial_velocity_min = 1.5
		duman.initial_velocity_max = 2.8
		duman.gravity = Vector3(0.35, 0.2, 0)
		sahne.add_child(duman)
		var isik := OmniLight3D.new()
		isik.light_color = Color(1.0, 0.55, 0.25)
		isik.omni_range = float(k.get("isik_menzil_m", 10.0))
		isik.position = p + Vector3.UP * 1.0
		sahne.add_child(isik)
		isiklar.append([isik, float(k.get("isik_guc", 3.0)), float(i) * 1.7])
	return isiklar

static func yangin_guncelle(isiklar: Array, t: float) -> void:
	for x in isiklar:
		var f := 0.75 + 0.15 * sin(t * 11.0 + float(x[2])) + 0.1 * sin(t * 23.0 + float(x[2]) * 2.0)
		(x[0] as OmniLight3D).light_energy = float(x[1]) * f

## Kılıç kıvılcımı: düello çiftlerinin arasında, el hizasında, vuruş ritminde kısa toplamalı patlama.
static func kivilcim(sahne: Node3D, noktalar: Array, k: Dictionary, tohum: int) -> Array:
	var r := RandomNumberGenerator.new()
	r.seed = tohum
	var liste: Array = []
	for i in noktalar.size():
		var p := CPUParticles3D.new()
		_ortak(p, {"doku": k["doku"], "adet": 14, "omur": 0.22, "boyut": [0.03, 0.08], "opaklik": 1.0, "renk": [1.0, 0.85, 0.5]}, tohum + i * 7, 0.0)
		(p.mesh.material as StandardMaterial3D).blend_mode = BaseMaterial3D.BLEND_MODE_ADD
		p.one_shot = true
		p.explosiveness = 1.0
		p.preprocess = 0.0
		p.emitting = false
		p.position = noktalar[i]
		p.spread = 180.0
		p.initial_velocity_min = 2.0
		p.initial_velocity_max = 5.0
		p.gravity = Vector3(0, -9.8, 0)
		sahne.add_child(p)
		var anlar: Array = []
		var s := r.randf_range(0.2, 0.9)
		while s < 60.0:
			anlar.append(s)
			s += r.randf_range(float(k.get("aralik_sn", [0.9, 1.6])[0]), float(k.get("aralik_sn", [0.9, 1.6])[1]))
		liste.append({"p": p, "anlar": anlar, "son": -1.0})
	return liste

static func kivilcim_guncelle(liste: Array, t: float) -> void:
	for d in liste:
		var son := -1.0
		for a in d["anlar"]:
			if a <= t:
				son = a
		if son >= 0.0 and son != float(d["son"]):
			d["son"] = son
			(d["p"] as CPUParticles3D).restart()
