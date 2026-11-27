extends Node3D
## Render ölçüm sahnesi (Faz 2): cinematic_test_2 sahnesinin motor varlıklarıyla birebir kopyası.
## gerçek iskelet animasyonu (Universal Animation Library CC0). Her şey koddan kurulur.

const SURE := 6.0
var AT_OLCEK := 0.42
var BINICI_Y := 1.52
var BINICI_Z := -0.15
var YAN_TEST := false
const HIZ := 1.25                 # Walk_Formal adım uzunluğuna uygun ilerleme (m/sn)
var t := 0.0
var askerler: Array = []
var ofsetler: Array = []
var at: Node3D
var at_iskelet: Skeleton3D
var at_dinlenme := {}
var binici: Node3D
var kamera: Camera3D
var toz: CPUParticles3D
var uzak_parcalar: Array = []
var uzak_konum: Array = []
var uzak_faz: Array = []
var MIZRAK := Transform3D(Basis.from_euler(Vector3(deg_to_rad(8), 0, 0)), Vector3(0, -0.55, 0.02))
var KALKAN := Transform3D(Basis.from_euler(Vector3(0, deg_to_rad(90), 0)), Vector3(0.1, -0.05, 0.05))

func _ready() -> void:
	seed(11)
	var a := OS.get_cmdline_user_args()
	if a.size() > 0:
		t = float(a[0])   # önizleme: belirli bir ana atla
	if a.size() >= 5:
		AT_OLCEK = float(a[1]); BINICI_Y = float(a[2]); BINICI_Z = float(a[3]); YAN_TEST = a[4] == 'yan'
	_ortam()
	_zemin()
	_daglar()
	_otlar()
	_kol()
	_at()
	_uzak_birlik()
	_toz()
	kamera = Camera3D.new()
	kamera.fov = 42.0
	kamera.near = 0.1
	kamera.far = 600.0
	add_child(kamera)

# ---------------------------------------------------------------- ışık, gök, sis, renk
func _ortam() -> void:
	var env := Environment.new()
	var sky := Sky.new()
	var sm := ProceduralSkyMaterial.new()
	sm.sky_top_color = Color(0.42, 0.5, 0.6)
	sm.sky_horizon_color = Color(0.86, 0.76, 0.64)
	sm.ground_horizon_color = Color(0.7, 0.62, 0.52)
	sm.ground_bottom_color = Color(0.3, 0.27, 0.22)
	sm.sun_angle_max = 25.0
	sm.sky_curve = 0.12
	sky.sky_material = sm
	env.background_mode = Environment.BG_SKY
	env.sky = sky
	env.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
	env.ambient_light_energy = 0.5
	env.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	env.tonemap_exposure = 1.05
	env.fog_enabled = true
	env.fog_light_color = Color(0.78, 0.72, 0.64)
	env.fog_density = 0.009
	env.fog_sky_affect = 0.35
	env.fog_height = 2.0
	env.fog_height_density = 0.06
	env.glow_enabled = true
	env.glow_intensity = 0.45
	env.glow_bloom = 0.05
	env.adjustment_enabled = true
	env.adjustment_contrast = 1.1
	env.adjustment_saturation = 0.82          # soluk, film benzeri renk
	var we := WorldEnvironment.new()
	we.environment = env
	add_child(we)
	var gunes := DirectionalLight3D.new()
	gunes.rotation_degrees = Vector3(-14, 118, 0)   # karşıdan alçak güneş: arka ışık, uzun gölge
	gunes.light_color = Color(1.0, 0.82, 0.62)
	gunes.light_energy = 1.6
	gunes.shadow_enabled = true
	gunes.directional_shadow_max_distance = 60.0
	add_child(gunes)
	var dolgu := DirectionalLight3D.new()                # gölgeli tarafa hafif soğuk dolgu ışığı
	dolgu.rotation_degrees = Vector3(-30, -60, 0)
	dolgu.light_color = Color(0.6, 0.68, 0.8)
	dolgu.light_energy = 0.35
	add_child(dolgu)

# ---------------------------------------------------------------- arazi
func _zemin() -> void:
	var m := PlaneMesh.new()
	m.size = Vector2(500, 500)
	m.subdivide_width = 200
	m.subdivide_depth = 200
	var sh := Shader.new()
	sh.code = """
shader_type spatial;
render_mode diffuse_burley, specular_disabled;
float h(vec2 p){ return fract(sin(dot(p, vec2(127.1,311.7)))*43758.5453); }
float n(vec2 p){ vec2 i=floor(p), f=fract(p); f=f*f*(3.0-2.0*f);
  return mix(mix(h(i),h(i+vec2(1,0)),f.x), mix(h(i+vec2(0,1)),h(i+vec2(1,1)),f.x), f.y); }
float fbm(vec2 p){ float s=0.0, a=0.5; for(int i=0;i<5;i++){ s+=a*n(p); p*=2.03; a*=0.5; } return s; }
varying vec3 wp;
void vertex(){
  wp = (MODEL_MATRIX * vec4(VERTEX,1.0)).xyz;
  float uzak = smoothstep(6.0, 60.0, abs(wp.x - 0.0));
  VERTEX.y += fbm(wp.xz*0.02)*14.0*uzak + fbm(wp.xz*0.25)*0.35;
  wp.y = VERTEX.y;
}
void fragment(){
  float yol = 1.0 - smoothstep(1.8, 3.6, abs(wp.x + sin(wp.z*0.05)*1.2));
  float d = fbm(wp.xz*0.6);
  float iz = fbm(wp.xz*vec2(4.0,0.6));                         // yolda tekerlek/ayak izleri
  vec3 cimen = mix(vec3(0.24,0.27,0.13), vec3(0.42,0.4,0.22), d);
  cimen = mix(cimen, vec3(0.36,0.3,0.2), smoothstep(0.55,0.75,fbm(wp.xz*0.08)));   // kuru yamalar
  vec3 toprak = mix(vec3(0.33,0.27,0.2), vec3(0.46,0.39,0.29), d) * (0.85 + 0.25*iz);
  ALBEDO = mix(cimen, toprak, yol);
  ROUGHNESS = 1.0;
}
"""
	var mat := ShaderMaterial.new()
	mat.shader = sh
	var mi := MeshInstance3D.new()
	mi.mesh = m
	mi.material_override = mat
	mi.position = Vector3(0, 0, 60)
	add_child(mi)

func _daglar() -> void:
	# üç kat dağ: sis içinde katman katman soluklaşan uzak plan
	for kat in 3:
		var mat := StandardMaterial3D.new()
		mat.albedo_color = [Color(0.36, 0.34, 0.3), Color(0.45, 0.44, 0.42), Color(0.55, 0.56, 0.58)][kat]
		for i in 7:
			var s := SphereMesh.new()
			s.radial_segments = 14
			s.rings = 8
			var mi := MeshInstance3D.new()
			mi.mesh = s
			mi.material_override = mat
			mi.position = Vector3(-150 + i * 50 + randf_range(-15, 15), -8, -110 - kat * 70 - randf_range(0, 25))
			mi.scale = Vector3(randf_range(40, 70), randf_range(22, 45) + kat * 12, randf_range(25, 40))
			add_child(mi)

# ---------------------------------------------------------------- ön plan otları (rüzgârda sallanır, kamerayla hızlı kayar)
func _otlar() -> void:
	var q := QuadMesh.new()
	q.size = Vector2(0.035, 0.36)
	q.center_offset = Vector3(0, 0.18, 0)
	var sh := Shader.new()
	sh.code = """
shader_type spatial;
render_mode cull_disabled, diffuse_burley;
void vertex(){
  vec3 w = (MODEL_MATRIX * vec4(0,0,0,1)).xyz;
  float s = UV.y < 0.5 ? 1.0 : 0.0;
  float tepe = 1.0 - UV.y;
  VERTEX.x += (sin(TIME*1.8 + w.x*0.7 + w.z*0.4)*0.07 + sin(TIME*4.1 + w.z)*0.02) * tepe * tepe;
  VERTEX.x *= mix(1.0, 0.15, tepe);
}
void fragment(){
  ALBEDO = mix(vec3(0.14,0.16,0.07), vec3(0.42,0.4,0.22), 1.0 - UV.y);
  ROUGHNESS = 1.0;
}
"""
	var mat := ShaderMaterial.new()
	mat.shader = sh
	q.material = mat
	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	mm.mesh = q
	mm.instance_count = 9000
	for i in mm.instance_count:
		var x := randf_range(-14.0, 14.0)
		if absf(x) < 2.6:
			x = signf(x + 0.001) * randf_range(2.6, 4.0)
		var z := randf_range(-26.0, 14.0)
		var b := Basis(Vector3.UP, randf() * TAU).rotated(Vector3(1, 0, 0), randf_range(-0.25, 0.25)).scaled(Vector3.ONE * randf_range(0.5, 1.3))
		mm.set_instance_transform(i, Transform3D(b, Vector3(x, 0.02, z)))
	var mmi := MultiMeshInstance3D.new()
	mmi.multimesh = mm
	add_child(mmi)

# ---------------------------------------------------------------- yürüyen kol (gerçek iskelet animasyonu)
func _kol() -> void:
	var mizrak: PackedScene = load("res://varlik/silah/S_Spear.glb")
	var kalkan: PackedScene = load("res://varlik/silah/S_ShieldRound.glb")
	var turler := ["korucu_erkek.glb", "koylu_erkek.glb"]
	var i := 0
	for sira in 5:                       # 5 sıra x 3 kişi
		for yan in 3:
			var k: Node3D = load("res://varlik/karakter/" + turler[(sira + yan) % 2]).instantiate()
			var ofs := Vector3(-1.15 + yan * 1.15 + randf_range(-0.12, 0.12), 0, -sira * 1.55 + randf_range(-0.15, 0.15))
			k.rotation.y = 0.0               # model +Z'ye bakar = yürüyüş yönü (+Z)
			add_child(k)
			askerler.append(k)
			ofsetler.append(ofs)
			var ap: AnimationPlayer = k.find_children("*", "AnimationPlayer", true, false)[0]
			var a := ap.get_animation("Walk_Formal")
			a.loop_mode = Animation.LOOP_LINEAR
			ap.play("Walk_Formal")
			ap.speed_scale = randf_range(0.96, 1.04)
			ap.seek(randf() * a.length, true)
			var sk: Skeleton3D = k.find_children("*", "Skeleton3D", true, false)[0]
			_migfer(sk, i)
			_ek(sk, "hand_r", mizrak, MIZRAK, 0.24)
			if i % 3 != 1:
				_ek(sk, "lowerarm_l", kalkan, KALKAN, 0.3)
			if i == 4 or i == 9:
				_sancak(k)
			i += 1

var ekler: Array = []   # [iskelet, kemik no, düğüm, ofset, sabit yön]
func _ek(sk: Skeleton3D, kemik: String, sahne: PackedScene, tr: Transform3D, olcek: float) -> void:
	# silah kemiğin KONUMUNU izler ama yönü sabit kalır (mızrak dik, kalkan dışa bakar): el sallandıkça devrilmez
	var n: Node3D = sahne.instantiate()
	add_child(n)
	if kemik == "lowerarm_l":
		var mat := StandardMaterial3D.new()
		mat.albedo_color = Color(0.36, 0.1, 0.07)
		mat.roughness = 0.75
		for m in n.find_children("*", "MeshInstance3D", true, false):
			m.material_override = mat
	ekler.append([sk, sk.find_bone(kemik), n, tr.origin, tr.basis.scaled(Vector3.ONE * olcek)])

func _ekleri_guncelle() -> void:
	for e in ekler:
		var sk: Skeleton3D = e[0]
		var g: Vector3 = (sk.global_transform * sk.get_bone_global_pose(e[1])).origin
		e[2].global_transform = Transform3D(e[4], g + e[3])

func _migfer(sk: Skeleton3D, i: int) -> void:
	# basit konik miğfer + zincir zırh yakası (kafa kemiğine bağlı)
	var ek := BoneAttachment3D.new()
	ek.bone_name = "Head"
	sk.add_child(ek)
	var celik := StandardMaterial3D.new()
	celik.albedo_color = Color(0.5, 0.5, 0.52)
	celik.metallic = 0.85
	celik.roughness = 0.38
	var c := CylinderMesh.new()
	c.top_radius = 0.01
	c.bottom_radius = 0.118
	c.height = 0.17
	c.radial_segments = 12
	var mi := MeshInstance3D.new()
	mi.mesh = c
	mi.material_override = celik
	mi.position = Vector3(0, 0.235, 0.0)
	ek.add_child(mi)
	var y := CylinderMesh.new()
	y.top_radius = 0.118
	y.bottom_radius = 0.122
	y.height = 0.035
	y.radial_segments = 12
	var zincir := StandardMaterial3D.new()
	zincir.albedo_color = Color(0.3, 0.3, 0.31)
	zincir.metallic = 0.7
	zincir.roughness = 0.6
	var mi2 := MeshInstance3D.new()
	mi2.mesh = y
	mi2.material_override = zincir
	mi2.position = Vector3(0, 0.15, 0.0)   # miğfer kenarı (alın hizası, yüz açık)
	ek.add_child(mi2)

func _sancak(k: Node3D) -> void:
	var ek := Node3D.new()
	ek.position = Vector3(0.32, 0, 0.1)
	k.add_child(ek)
	var sap := MeshInstance3D.new()
	var c := CylinderMesh.new()
	c.top_radius = 0.025
	c.bottom_radius = 0.032
	c.height = 4.2
	sap.mesh = c
	var sm := StandardMaterial3D.new()
	sm.albedo_color = Color(0.3, 0.2, 0.12)
	sap.material_override = sm
	sap.position = Vector3(0, 2.1, 0)
	ek.add_child(sap)
	var p := PlaneMesh.new()
	p.size = Vector2(1.4, 0.9)
	p.subdivide_width = 28
	p.subdivide_depth = 18
	p.orientation = PlaneMesh.FACE_X
	var sh := Shader.new()
	sh.code = """
shader_type spatial;
render_mode cull_disabled, diffuse_burley;
uniform float faz = 0.0;
varying float kivrim;
void vertex(){
  float u = (VERTEX.z + 0.7) / 1.4;
  float a = TIME*5.2 - u*6.5 + faz;
  VERTEX.x += (sin(a)*0.2 + sin(TIME*8.7 - u*11.0 + VERTEX.y*4.0 + faz)*0.06) * u;
  VERTEX.y -= u*u*0.1;
  kivrim = cos(a) * u;
  NORMAL = normalize(vec3(1.0, 0.0, -cos(a)*1.2*u));
}
void fragment(){
  ALBEDO = vec3(0.3, 0.035, 0.03) * (0.7 + 0.35*kivrim);
  ROUGHNESS = 0.9;
}
"""
	var mat := ShaderMaterial.new()
	mat.shader = sh
	mat.set_shader_parameter("faz", randf() * 6.0)
	var b := MeshInstance3D.new()
	b.mesh = p
	b.material_override = mat
	b.position = Vector3(0, 3.75, -0.7)
	ek.add_child(b)

# ---------------------------------------------------------------- at + süvari (prosedürel dört zamanlı yürüyüş)
func _at() -> void:
	at = load("res://varlik/hayvan/horse.glb").instantiate()
	at.scale = Vector3.ONE * AT_OLCEK
	add_child(at)
	var don := StandardMaterial3D.new()
	don.albedo_color = Color(0.22, 0.14, 0.09)
	don.roughness = 0.7
	for m in at.find_children("*", "MeshInstance3D", true, false):
		m.material_override = don
	at_iskelet = at.find_children("*", "Skeleton3D", true, false)[0]
	for i in at_iskelet.get_bone_count():
		at_dinlenme[at_iskelet.get_bone_name(i)] = at_iskelet.get_bone_rest(i).basis.get_rotation_quaternion()
	binici = load("res://varlik/karakter/korucu_erkek.glb").instantiate()
	binici.scale = Vector3.ONE / AT_OLCEK
	binici.position = Vector3(0, BINICI_Y, BINICI_Z)
	at.add_child(binici)
	var ap: AnimationPlayer = binici.find_children("*", "AnimationPlayer", true, false)[0]
	var a := ap.get_animation("Driving")
	a.loop_mode = Animation.LOOP_LINEAR
	ap.play("Driving")
	_migfer(binici.find_children("*", "Skeleton3D", true, false)[0], 0)

func _kemik(ad: String, eksen: Vector3, aci: float) -> void:
	var i := at_iskelet.find_bone(ad)
	if i >= 0:
		at_iskelet.set_bone_pose_rotation(i, at_dinlenme[ad] * Quaternion(eksen.normalized(), aci))

func _at_yuru(yol: float) -> void:
	var f := yol * TAU * 0.62
	var X := Vector3(1, 0, 0)
	var b := {"BackUpperLeg_L": 0.0, "FrontUpperLeg_L": 0.25, "BackUpperLeg_R": 0.5, "FrontUpperLeg_R": 0.75}
	for k in b:
		var p: float = f + b[k] * TAU
		_kemik(k, X, sin(p) * 0.36)
		_kemik(String(k).replace("Upper", "Lower"), X, maxf(0.0, -cos(p)) * 0.7 * (1.0 if String(k).begins_with("Front") else -1.0))
	_kemik("Neck1", X, sin(f * 2.0) * 0.05)
	_kemik("Head", X, sin(f * 2.0 + 1.0) * 0.07)
	_kemik("Tail2", Vector3(0, 0, 1), sin(t * 2.1) * 0.15)
	_kemik("Tail4", Vector3(0, 0, 1), sin(t * 2.1 - 0.8) * 0.2)

# ---------------------------------------------------------------- arkadaki büyük ordu (uzakta, sis içinde)
func _uzak_birlik() -> void:
	var govde := CapsuleMesh.new()
	govde.radius = 0.22
	govde.height = 1.25
	var bas := SphereMesh.new()
	bas.radius = 0.13
	bas.height = 0.26
	var mizrak := CylinderMesh.new()
	mizrak.top_radius = 0.012
	mizrak.bottom_radius = 0.012
	mizrak.height = 2.6
	var parcalar := [[govde, Vector3(0, 0.65, 0), Color(0.32, 0.26, 0.2)], [bas, Vector3(0, 1.38, 0), Color(0.45, 0.45, 0.47)], [mizrak, Vector3(0.25, 1.3, 0), Color(0.3, 0.24, 0.17)]]
	for p in parcalar:
		var mm := MultiMesh.new()
		mm.transform_format = MultiMesh.TRANSFORM_3D
		mm.mesh = p[0]
		mm.instance_count = 420
		var mmi := MultiMeshInstance3D.new()
		mmi.multimesh = mm
		var mat := StandardMaterial3D.new()
		mat.albedo_color = p[2]
		mmi.material_override = mat
		mmi.set_meta("ofs", p[1])
		uzak_parcalar.append(mmi)
		add_child(mmi)
	for i in 420:
		uzak_konum.append(Vector3(-2.4 + (i % 6) * 0.95 + randf_range(-0.15, 0.15), 0, -10.0 - (i / 6) * 1.5))
		uzak_faz.append(randf() * TAU)

func _uzak_guncelle(z: float) -> void:
	for mmi in uzak_parcalar:
		var ofs: Vector3 = mmi.get_meta("ofs")
		for i in uzak_konum.size():
			var adim: float = absf(sin(t * 5.2 + uzak_faz[i])) * 0.05
			var sal: float = sin(t * 2.6 + uzak_faz[i]) * 0.035
			mmi.multimesh.set_instance_transform(i, Transform3D(Basis(Vector3(0, 0, 1), sal), uzak_konum[i] + Vector3(0, adim, z) + ofs))

# ---------------------------------------------------------------- toz
func _toz() -> void:
	toz = CPUParticles3D.new()
	toz.amount = 220
	toz.lifetime = 3.2
	toz.preprocess = 3.2
	toz.emission_shape = CPUParticles3D.EMISSION_SHAPE_BOX
	toz.emission_box_extents = Vector3(2.6, 0.05, 5.0)
	toz.direction = Vector3(-0.4, 1, -0.3)
	toz.spread = 35.0
	toz.initial_velocity_min = 0.2
	toz.initial_velocity_max = 0.55
	toz.gravity = Vector3(-0.25, 0.06, -0.1)
	toz.scale_amount_min = 0.7
	toz.scale_amount_max = 2.2
	var eg := Curve.new()
	eg.add_point(Vector2(0, 0.3))
	eg.add_point(Vector2(1, 1.8))
	toz.scale_amount_curve = eg
	var renk := Gradient.new()
	renk.set_color(0, Color(0.66, 0.58, 0.46, 0.0))
	renk.add_point(0.25, Color(0.66, 0.58, 0.46, 0.22))
	renk.set_color(renk.get_point_count() - 1, Color(0.7, 0.62, 0.5, 0.0))
	toz.color_ramp = renk
	var q := QuadMesh.new()
	q.size = Vector2(1.3, 1.3)
	var tm := StandardMaterial3D.new()
	tm.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	tm.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	tm.billboard_mode = BaseMaterial3D.BILLBOARD_PARTICLES
	tm.vertex_color_use_as_albedo = true
	var gt := GradientTexture2D.new()
	gt.fill = GradientTexture2D.FILL_RADIAL
	gt.fill_from = Vector2(0.5, 0.5)
	gt.fill_to = Vector2(1.0, 0.5)
	var g2 := Gradient.new()
	g2.set_color(0, Color(1, 1, 1, 1))
	g2.set_color(1, Color(1, 1, 1, 0))
	gt.gradient = g2
	tm.albedo_texture = gt
	q.material = tm
	toz.mesh = q
	toz.local_coords = false
	add_child(toz)

# ---------------------------------------------------------------- her kare
func _process(delta: float) -> void:
	t += delta
	var z := HIZ * t
	for i in askerler.size():
		askerler[i].position = ofsetler[i] + Vector3(0, 0, z)
	at.position = Vector3(-2.9, 0, -2.2 + z)
	_at_yuru(z)
	binici.position = Vector3(0, BINICI_Y, BINICI_Z) + Vector3(0, absf(sin(z * TAU * 0.62 * 2.0 + 0.4)) * 0.12, 0)
	toz.position = Vector3(-0.3, 0.05, -3.0 + z)
	_uzak_guncelle(z)
	_ekleri_guncelle()
	# kamera: kolun sağ önünde, alçaktan; onlarla birlikte ilerlerken yavaşça yanlarına doğru süzülür
	var u := clampf(t / SURE, 0.0, 1.0)
	var s := u * u * (3.0 - 2.0 * u)
	var hedef := Vector3(-0.4, 1.45, -2.6 + z)
	var aci := lerpf(0.42, 1.05, s)                 # önden yana doğru yay
	var uzak := lerpf(9.0, 7.2, s)
	var poz := hedef + Vector3(sin(aci) * uzak, lerpf(0.35, 0.15, s), cos(aci) * uzak)
	poz += Vector3(sin(t * 1.3) * 0.025, sin(t * 1.9) * 0.02, sin(t * 0.9) * 0.02)   # el kamerası nefesi
	kamera.position = poz
	kamera.look_at(hedef + Vector3(0, 0, 1.2), Vector3.UP)
	if YAN_TEST:
		kamera.position = at.position + Vector3(-6.5, 1.4, 0.0)
		kamera.look_at(at.position + Vector3(0, 1.1, 0), Vector3.UP)
