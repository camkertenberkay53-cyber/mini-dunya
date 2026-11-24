extends RefCounted
## Ortam kurucu (Faz 4): ışık, gök, sis, arazi, dağlar ve otlar VERİDEN kurulur.
## Görünüm Faz 2 ölçüm sahnesinden (olcum.gd) alındı; olcum.gd ölçüm tabanı olarak DEĞİŞMEDEN kalır.
## Bütün sayılar is.json'daki "arazi" ve "isik" hazır ayarlarından gelir (motor/uretim/kurallar/arazi.yaml).

static func _renk(a: Array) -> Color:
	return Color(a[0], a[1], a[2])

static func _v3(a: Array) -> Vector3:
	return Vector3(a[0], a[1], a[2])

static func isik(kok: Node, i: Dictionary) -> void:
	var env := Environment.new()
	var sky := Sky.new()
	var sm := ProceduralSkyMaterial.new()
	sm.sky_top_color = _renk(i["gok"]["tepe"])
	sm.sky_horizon_color = _renk(i["gok"]["ufuk"])
	sm.ground_horizon_color = _renk(i["gok"]["ufuk"]).darkened(0.18)
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
	env.fog_light_color = _renk(i["sis"]["renk"])
	env.fog_density = i["sis"]["yogunluk"]
	env.fog_sky_affect = 0.35
	env.fog_height = 2.0
	env.fog_height_density = float(i["sis"].get("yukseklik_yogunlugu", 0.06))
	env.glow_enabled = true
	env.glow_intensity = 0.45
	env.glow_bloom = 0.05
	env.adjustment_enabled = true
	env.adjustment_contrast = 1.1
	env.adjustment_saturation = 0.82
	var we := WorldEnvironment.new()
	we.environment = env
	kok.add_child(we)
	var gunes := DirectionalLight3D.new()
	gunes.rotation_degrees = _v3(i["gunes"]["aci"])
	gunes.light_color = _renk(i["gunes"]["renk"])
	gunes.light_energy = i["gunes"]["guc"]
	gunes.shadow_enabled = true
	gunes.directional_shadow_max_distance = 60.0
	kok.add_child(gunes)
	var dolgu := DirectionalLight3D.new()
	dolgu.rotation_degrees = _v3(i["dolgu"]["aci"])
	dolgu.light_color = _renk(i["dolgu"]["renk"])
	dolgu.light_energy = i["dolgu"]["guc"]
	kok.add_child(dolgu)

const ZEMIN_SHADER := """
shader_type spatial;
render_mode diffuse_burley, specular_disabled;
uniform vec3 cimen; uniform vec3 cimen2; uniform vec3 kuru; uniform vec3 toprak; uniform vec3 toprak2;
uniform float tepe = 14.0; uniform float yol_acik = 1.0; uniform float yol_gen = 2.6; uniform float yol_x = 0.0;
uniform float duz_yari = 6.0;
float h(vec2 p){ return fract(sin(dot(p, vec2(127.1,311.7)))*43758.5453); }
float n(vec2 p){ vec2 i=floor(p), f=fract(p); f=f*f*(3.0-2.0*f);
  return mix(mix(h(i),h(i+vec2(1,0)),f.x), mix(h(i+vec2(0,1)),h(i+vec2(1,1)),f.x), f.y); }
float fbm(vec2 p){ float s=0.0, a=0.5; for(int i=0;i<5;i++){ s+=a*n(p); p*=2.03; a*=0.5; } return s; }
varying vec3 wp;
void vertex(){
  wp = (MODEL_MATRIX * vec4(VERTEX,1.0)).xyz;
  float uzak = smoothstep(duz_yari, duz_yari * 10.0, abs(wp.x - yol_x));
  VERTEX.y += fbm(wp.xz*0.02)*tepe*uzak + fbm(wp.xz*0.25)*0.35*uzak;
  wp.y = VERTEX.y;
}
void fragment(){
  float yol = yol_acik * (1.0 - smoothstep(yol_gen*0.7, yol_gen*1.4, abs(wp.x - yol_x + sin(wp.z*0.05)*1.2)));
  float d = fbm(wp.xz*0.6);
  float iz = fbm(wp.xz*vec2(4.0,0.6));
  vec3 c = mix(cimen, cimen2, d);
  c = mix(c, kuru, smoothstep(0.55,0.75,fbm(wp.xz*0.08)));
  vec3 t = mix(toprak, toprak2, d) * (0.85 + 0.25*iz);
  c *= 0.9 + 0.2 * fbm(wp.xz*2.3);   // ince ölçekli renk dalgalanması (düz renk alanları kırılsın)
  ALBEDO = mix(c, t, yol);
  ROUGHNESS = 1.0;
}
"""

## Zemin: oyuncuların durduğu "duz_yari" genişliğindeki şerit düzdür (ayaklar yere değsin); dışı tepelenir.
static func arazi(kok: Node, a: Dictionary, merkez: Vector2) -> void:
	var m := PlaneMesh.new()
	m.size = Vector2(500, 500)
	m.subdivide_width = 200
	m.subdivide_depth = 200
	var sh := Shader.new()
	sh.code = ZEMIN_SHADER
	var mat := ShaderMaterial.new()
	mat.shader = sh
	var z: Dictionary = a["zemin"]
	for k in ["cimen", "cimen2", "kuru", "toprak", "toprak2"]:
		mat.set_shader_parameter(k, _v3(z[k]))
	mat.set_shader_parameter("tepe", a["tepe_yuksekligi"])
	mat.set_shader_parameter("yol_acik", 1.0 if a["yol"]["acik"] else 0.0)
	mat.set_shader_parameter("yol_gen", a["yol"]["genislik"])
	mat.set_shader_parameter("yol_x", a.get("yol_x", 0.0))
	mat.set_shader_parameter("duz_yari", a.get("duz_yari", 6.0))
	var mi := MeshInstance3D.new()
	mi.mesh = m
	mi.material_override = mat
	mi.position = Vector3(merkez.x, 0, merkez.y)
	kok.add_child(mi)

static func daglar(kok: Node, a: Dictionary, rng: RandomNumberGenerator, merkez: Vector2, yon: float) -> void:
	## Dağ sıraları kameranın baktığı yönde, sahne merkezinin ötesine dizilir.
	var ileri := Vector2(sin(yon), cos(yon))
	var yan := Vector2(ileri.y, -ileri.x)
	for kat in int(a["dag_katmani"]):
		var mat := StandardMaterial3D.new()
		mat.albedo_color = _renk(a["dag_renkleri"][kat])
		mat.roughness = 1.0
		for i in 7:
			var s := SphereMesh.new()
			s.radial_segments = 40
			s.rings = 20
			var mi := MeshInstance3D.new()
			mi.mesh = s
			mi.material_override = mat
			var p := merkez + ileri * (110.0 + kat * 70.0 + rng.randf_range(0, 25)) + yan * (-150.0 + i * 50.0 + rng.randf_range(-15, 15))
			mi.position = Vector3(p.x, -8, p.y)
			mi.scale = Vector3(rng.randf_range(55, 90), rng.randf_range(16, 34) + kat * 10, rng.randf_range(30, 45))
			mi.rotation.y = yon
			kok.add_child(mi)

const OT_SHADER := """
shader_type spatial;
render_mode cull_disabled, diffuse_burley;
uniform vec3 alt; uniform vec3 ust; uniform vec3 kuru;
varying float renk_payi;
void vertex(){
  vec3 m = (MODEL_MATRIX * vec4(0,0,0,1)).xyz;
  renk_payi = fract(sin(dot(m.xz, vec2(12.9898, 78.233))) * 43758.5453);
  vec3 w = (MODEL_MATRIX * vec4(0,0,0,1)).xyz;
  float tepe = 1.0 - UV.y;
  VERTEX.x += (sin(TIME*1.8 + w.x*0.7 + w.z*0.4)*0.07 + sin(TIME*4.1 + w.z)*0.02) * tepe * tepe;
  VERTEX.x *= mix(1.0, 0.35, tepe);
}
void fragment(){
  vec3 u = mix(ust, kuru, smoothstep(0.55, 1.0, renk_payi));
  ALBEDO = mix(alt, u, 1.0 - UV.y) * (0.85 + 0.3 * renk_payi);
  ROUGHNESS = 1.0;
}
"""

## Otlar yalnızca kameranın gördüğü bölgeye (alan = [xmin, xmax, zmin, zmax]) ekilir; yol şeridi boş kalır.
static func otlar(kok: Node, a: Dictionary, rng: RandomNumberGenerator, alan: Array) -> void:
	var q := QuadMesh.new()
	var boy: float = a.get("ot_boy", 0.36)
	q.size = Vector2(a.get("ot_genislik", 0.035), boy)
	q.center_offset = Vector3(0, boy * 0.5, 0)
	var sh := Shader.new()
	sh.code = OT_SHADER
	var mat := ShaderMaterial.new()
	mat.shader = sh
	mat.set_shader_parameter("alt", _v3(a["zemin"]["cimen"]) * 0.85)
	mat.set_shader_parameter("ust", _v3(a["zemin"]["cimen2"]))
	mat.set_shader_parameter("kuru", _v3(a["zemin"]["kuru"]))
	q.material = mat
	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	mm.mesh = q
	mm.instance_count = int(a["ot_sayisi"])
	var yx: float = a.get("yol_x", 0.0)
	var yg: float = a["yol"]["genislik"] if a["yol"]["acik"] else 0.0
	for i in mm.instance_count:
		var x := rng.randf_range(alan[0], alan[1])
		var z := rng.randf_range(alan[2], alan[3])
		if absf(x - yx) < yg:
			x = yx + signf(x - yx + 0.001) * rng.randf_range(yg, yg + 1.4)
		var b := Basis(Vector3.UP, rng.randf() * TAU).rotated(Vector3(1, 0, 0), rng.randf_range(-0.25, 0.25)).scaled(Vector3.ONE * rng.randf_range(0.5, 1.3))
		mm.set_instance_transform(i, Transform3D(b, Vector3(x, 0.02, z)))
	var mmi := MultiMeshInstance3D.new()
	mmi.multimesh = mm
	kok.add_child(mmi)
