extends RefCounted
## Ortam kurucu (Faz 4): ışık, gök, sis, arazi, dağlar ve otlar VERİDEN kurulur.
## Görünüm Faz 2 ölçüm sahnesinden (olcum.gd) alındı; olcum.gd ölçüm tabanı olarak DEĞİŞMEDEN kalır.
## Bütün sayılar is.json'daki "arazi" ve "isik" hazır ayarlarından gelir (motor/uretim/kurallar/arazi.yaml).

static func _renk(a: Array) -> Color:
	return Color(a[0], a[1], a[2])

static func _v3(a: Array) -> Vector3:
	return Vector3(a[0], a[1], a[2])

## DENEYSEL KOPYA (Faz 5.1 P2/P3): üretimdeki motor/godot/sahneler/ortam.gd'nin değiştirilmiş hali.
## Yalnızca is.json içindeki "gorsel" sözlüğü varsa davranış değişir; yoksa üretimle aynıdır.
static func _resim(yol: String, mip: bool) -> ImageTexture:
	var img := Image.load_from_file(yol)
	if img == null:
		push_error("DENEY: resim yüklenemedi " + yol)
		return null
	if mip:
		img.generate_mipmaps()
	return ImageTexture.create_from_image(img)

static func isik(kok: Node, i: Dictionary) -> void:
	var g: Dictionary = i.get("gorsel", {})
	var env := Environment.new()
	var sky := Sky.new()
	if g.has("hdri"):
		var ps := PanoramaSkyMaterial.new()
		ps.panorama = _resim(g["hdri"], false)
		ps.energy_multiplier = float(g.get("hdri_enerji", 1.0))
		sky.sky_material = ps
		env.sky_rotation = Vector3(0, deg_to_rad(float(g.get("hdri_donus", 0.0))), 0)
	else:
		var sm := ProceduralSkyMaterial.new()
		sm.sky_top_color = _renk(g.get("gok_tepe", i["gok"]["tepe"]))
		sm.sky_horizon_color = _renk(g.get("gok_ufuk", i["gok"]["ufuk"]))
		sm.ground_horizon_color = _renk(g.get("gok_ufuk", i["gok"]["ufuk"])).darkened(0.18)
		sm.ground_bottom_color = Color(0.3, 0.27, 0.22)
		sm.sun_angle_max = 25.0
		sm.sky_curve = float(g.get("gok_egri", 0.12))
		sky.sky_material = sm
	env.background_mode = Environment.BG_SKY
	env.sky = sky
	env.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
	env.ambient_light_energy = float(g.get("ortam_isik", 0.5))
	var tm := {"filmic": Environment.TONE_MAPPER_FILMIC, "aces": Environment.TONE_MAPPER_ACES, "agx": Environment.TONE_MAPPER_AGX}
	env.tonemap_mode = tm[g.get("tonemap", "filmic")]
	env.tonemap_exposure = float(g.get("pozlama", 1.05))
	env.tonemap_white = float(g.get("beyaz", 1.0))
	env.fog_enabled = true
	var sis_c := _renk(g.get("sis_renk", i["sis"]["renk"]))
	var sk := float(g.get("sis_renk_carpan", 1.0))
	env.fog_light_color = Color(sis_c.r * sk, sis_c.g * sk, sis_c.b * sk)
	env.fog_density = float(i["sis"]["yogunluk"]) * float(g.get("sis_carpan", 1.0))
	env.fog_sky_affect = float(g.get("sis_gok", 0.35))
	env.fog_height = 2.0
	env.fog_height_density = float(i["sis"].get("yukseklik_yogunlugu", 0.06)) * float(g.get("yer_sisi_carpan", 1.0))
	env.glow_enabled = float(g.get("glow", 0.45)) > 0.0
	env.glow_intensity = float(g.get("glow", 0.45))
	env.glow_bloom = 0.05
	env.adjustment_enabled = true
	env.adjustment_contrast = float(g.get("kontrast", 1.1))
	env.adjustment_saturation = float(g.get("doygunluk", 0.82))
	env.adjustment_brightness = float(g.get("parlaklik", 1.0))
	var we := WorldEnvironment.new()
	we.environment = env
	kok.add_child(we)
	var gunes := DirectionalLight3D.new()
	gunes.rotation_degrees = _v3(i["gunes"]["aci"])
	gunes.light_color = _renk(i["gunes"]["renk"])
	gunes.light_energy = float(i["gunes"]["guc"]) * float(g.get("gunes_carpan", 1.0))
	if g.has("gunes_renk"):
		gunes.light_color = _renk(g["gunes_renk"])
	gunes.shadow_enabled = true
	gunes.shadow_blur = float(g.get("golge_yumusaklik", 1.0))
	gunes.directional_shadow_max_distance = 60.0
	kok.add_child(gunes)
	var dolgu := DirectionalLight3D.new()
	dolgu.rotation_degrees = _v3(i["dolgu"]["aci"])
	dolgu.light_color = _renk(i["dolgu"]["renk"])
	dolgu.light_energy = float(i["dolgu"]["guc"]) * float(g.get("dolgu_carpan", 1.0))
	kok.add_child(dolgu)

const ZEMIN_SHADER := """
shader_type spatial;
render_mode diffuse_burley, specular_disabled;
uniform vec3 cimen; uniform vec3 cimen2; uniform vec3 kuru; uniform vec3 toprak; uniform vec3 toprak2;
uniform float tepe = 14.0; uniform float yol_acik = 1.0; uniform float yol_gen = 2.6; uniform float yol_x = 0.0;
uniform float duz_yari = 6.0;
uniform sampler2D d_alb : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D d_nor : hint_normal, filter_linear_mipmap, repeat_enable;
uniform float doku_acik = 0.0; uniform float doku_olcek = 0.5; uniform float doku_karisim = 0.8;
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
  vec3 taban = mix(c, t, yol);
  if (doku_acik > 0.5) {
    vec2 uv = wp.xz * doku_olcek;
    vec3 d1 = texture(d_alb, uv).rgb;
    vec3 d2 = texture(d_alb, uv * 0.23 + vec2(0.37, 0.11)).rgb;   // ikinci ölçek: döşeme tekrarını kırar
    vec3 dk = mix(d1, d2, 0.35);
    float l = max(dot(dk, vec3(0.299, 0.587, 0.114)), 0.02);
    ALBEDO = mix(taban, taban * (dk / l) * 0.5 + dk * 0.5, doku_karisim);
    NORMAL_MAP = texture(d_nor, uv).rgb;
    NORMAL_MAP_DEPTH = 1.0;
  } else {
    ALBEDO = taban;
  }
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
	var g: Dictionary = a.get("gorsel", {})
	if g.has("zemin_alb"):
		mat.set_shader_parameter("d_alb", _resim(g["zemin_alb"], true))
		mat.set_shader_parameter("d_nor", _resim(g["zemin_nor"], true))
		mat.set_shader_parameter("doku_acik", 1.0)
		mat.set_shader_parameter("doku_olcek", float(g.get("doku_olcek", 0.5)))
		mat.set_shader_parameter("doku_karisim", float(g.get("doku_karisim", 0.8)))
	var mi := MeshInstance3D.new()
	mi.mesh = m
	mi.material_override = mat
	mi.position = Vector3(merkez.x, 0, merkez.y)
	kok.add_child(mi)

const UZAK_SHADER := """
shader_type spatial;
render_mode diffuse_burley, specular_disabled;
uniform vec3 r0; uniform vec3 r1; uniform vec3 r2; uniform vec2 merkez; uniform float yukseklik = 45.0;
uniform float bas = 180.0; uniform float tam = 420.0;
float h(vec2 p){ return fract(sin(dot(p, vec2(127.1,311.7)))*43758.5453); }
float n(vec2 p){ vec2 i=floor(p), f=fract(p); f=f*f*(3.0-2.0*f);
  return mix(mix(h(i),h(i+vec2(1,0)),f.x), mix(h(i+vec2(0,1)),h(i+vec2(1,1)),f.x), f.y); }
float fbm(vec2 p){ float s=0.0, a=0.5; for(int i=0;i<6;i++){ s+=a*n(p); p*=2.07; a*=0.5; } return s; }
float sirt(vec2 p){ float s=0.0, a=0.5; for(int i=0;i<5;i++){ s+=a*(1.0-abs(n(p)*2.0-1.0)); p*=2.11; a*=0.5; } return s; }
float yuk(vec2 w){
  float k = smoothstep(bas, tam, distance(w, merkez));
  return -2.0 + (fbm(w*0.004)*0.55 + sirt(w*0.009)*0.45) * yukseklik * k;
}
varying float hv; varying vec3 wp;
void vertex(){
  vec3 w = (MODEL_MATRIX * vec4(VERTEX,1.0)).xyz;
  float y = yuk(w.xz);
  VERTEX.y += y;
  float e = 3.0;
  NORMAL = normalize(vec3(yuk(w.xz - vec2(e,0)) - yuk(w.xz + vec2(e,0)), 2.0*e, yuk(w.xz - vec2(0,e)) - yuk(w.xz + vec2(0,e))));
  hv = clamp(y / max(yukseklik, 1.0), 0.0, 1.0);
  wp = w;
}
void fragment(){
  float d = fbm(wp.xz*0.05);
  vec3 c = mix(r0, r1, smoothstep(0.1, 0.6, hv + (d-0.5)*0.3));
  c = mix(c, r2, smoothstep(0.65, 1.0, hv));
  c *= 0.82 + 0.3*fbm(wp.xz*0.4);
  ALBEDO = c;
  ROUGHNESS = 1.0;
}
"""

static func daglar(kok: Node, a: Dictionary, rng: RandomNumberGenerator, merkez: Vector2, yon: float) -> void:
	var g: Dictionary = a.get("gorsel", {})
	var bicim: String = g.get("dag_bicim", "kure")
	if bicim == "yok":
		return
	if bicim == "arazi":
		# Faz 5.2 D4: küre tepeler yerine yükseklik alanı (sırt gürültüsü); ana zeminin (500 m) dışında yükselir
		var m := PlaneMesh.new()
		m.size = Vector2(1800, 1800)
		m.subdivide_width = 240
		m.subdivide_depth = 240
		var sh := Shader.new()
		sh.code = UZAK_SHADER
		if g.has("dag_pus_renk"):
			# Faz 5.2 D8: uzak arazi sahnenin genel sisini değil kendi hava perspektifini kullanır (FOG çıkışı)
			sh.code = UZAK_SHADER.replace("ROUGHNESS = 1.0;", "ROUGHNESS = 1.0;\n  float uz = length(VERTEX);\n  FOG = vec4(pus_renk, min(pus_max, 1.0 - exp(-uz * pus_yogunluk)));").replace("uniform float bas = 180.0;", "uniform vec3 pus_renk; uniform float pus_yogunluk = 0.004; uniform float pus_max = 0.6; uniform float bas = 180.0;")
		if g.get("dag_tani", "") == "sabit_renk":
			sh.code = sh.code.replace("ALBEDO = c;", "ALBEDO = vec3(0.25, 0.1, 0.1);")
		elif g.get("dag_tani", "") == "normal_yukari":
			sh.code = sh.code.replace("  NORMAL = normalize(vec3(", "  vec3 _n = normalize(vec3(")
		var mat := ShaderMaterial.new()
		mat.shader = sh
		if g.has("dag_pus_renk"):
			mat.set_shader_parameter("pus_renk", _v3(g["dag_pus_renk"]))
			mat.set_shader_parameter("pus_yogunluk", float(g.get("dag_pus_yogunluk", 0.004)))
			mat.set_shader_parameter("pus_max", float(g.get("dag_pus_max", 0.6)))
		var rk: Array = a["dag_renkleri"]
		var ton := float(g.get("dag_ton", 1.0))
		mat.set_shader_parameter("r0", _v3(rk[0]) * ton)
		mat.set_shader_parameter("r1", _v3(rk[min(1, rk.size() - 1)]) * ton)
		mat.set_shader_parameter("r2", _v3(rk[rk.size() - 1]) * ton)
		mat.set_shader_parameter("bas", float(g.get("dag_bas", 180.0)))
		mat.set_shader_parameter("tam", float(g.get("dag_tam", 420.0)))
		mat.set_shader_parameter("merkez", merkez)
		mat.set_shader_parameter("yukseklik", float(g.get("dag_yukseklik", 45.0)))
		var mi := MeshInstance3D.new()
		mi.mesh = m
		mi.material_override = mat
		mi.position = Vector3(merkez.x, 0, merkez.y)
		mi.extra_cull_margin = 200.0
		kok.add_child(mi)
		return
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
uniform float yukari_normal = 0.0;  // Faz 5.2 D1: aydınlatma normali yukarı (arka yüz siyahlığı biter)
uniform float tutam = 0.0;          // Faz 5.2 D2: kart başına 7 ince yaprak (opak kama yerine)
varying float renk_payi;
void vertex(){
  vec3 m = (MODEL_MATRIX * vec4(0,0,0,1)).xyz;
  renk_payi = fract(sin(dot(m.xz, vec2(12.9898, 78.233))) * 43758.5453);
  vec3 w = (MODEL_MATRIX * vec4(0,0,0,1)).xyz;
  float tepe = 1.0 - UV.y;
  VERTEX.x += (sin(TIME*1.8 + w.x*0.7 + w.z*0.4)*0.07 + sin(TIME*4.1 + w.z)*0.02) * tepe * tepe;
  VERTEX.x *= mix(1.0, mix(0.35, 1.0, tutam), tepe);
}
void fragment(){
  if (tutam > 0.5) {
    float t = 1.0 - UV.y;
    float ic = 0.0;
    for (int k = 0; k < 7; k++) {
      float fk = float(k);
      float s = fract(sin(fk * 12.9898 + renk_payi * 78.233) * 43758.5453);
      float s2 = fract(sin(fk * 39.346 + renk_payi * 11.135) * 24634.6345);
      float boy = 0.5 + 0.5 * s2;
      float merkez = 0.12 + 0.76 * s + (s2 - 0.5) * 0.35 * t * t;
      float gen = 0.05 * (1.0 - t / boy);
      if (t < boy && abs(UV.x - merkez) < gen) { ic = 1.0; }
    }
    if (ic < 0.5) { discard; }
  }
  if (yukari_normal > 0.5) { NORMAL = normalize((VIEW_MATRIX * vec4(0.0, 1.0, 0.0, 0.0)).xyz); }
  vec3 u = mix(ust, kuru, smoothstep(0.55, 1.0, renk_payi));
  ALBEDO = mix(alt, u, 1.0 - UV.y) * (0.85 + 0.3 * renk_payi);
  ROUGHNESS = 1.0;
}
"""

## Otlar yalnızca kameranın gördüğü bölgeye (alan = [xmin, xmax, zmin, zmax]) ekilir; yol şeridi boş kalır.
static func otlar(kok: Node, a: Dictionary, rng: RandomNumberGenerator, alan: Array) -> void:
	var q := QuadMesh.new()
	var g: Dictionary = a.get("gorsel", {})
	var boy: float = a.get("ot_boy", 0.36) * float(g.get("ot_boy_carpan", 1.0))
	q.size = Vector2(a.get("ot_genislik", 0.035) * float(g.get("ot_genislik_carpan", 1.0)), boy)
	q.center_offset = Vector3(0, boy * 0.5, 0)
	var sh := Shader.new()
	sh.code = OT_SHADER
	var mat := ShaderMaterial.new()
	mat.shader = sh
	mat.set_shader_parameter("alt", _v3(a["zemin"]["cimen"]) * float(g.get("ot_alt_parlaklik", 0.85)))
	mat.set_shader_parameter("ust", _v3(a["zemin"]["cimen2"]) * float(g.get("ot_ust_carpan", 1.0)))
	mat.set_shader_parameter("kuru", _v3(a["zemin"]["kuru"]) * float(g.get("ot_ust_carpan", 1.0)))
	mat.set_shader_parameter("yukari_normal", 1.0 if g.get("ot_normal", "") == "yukari" else 0.0)
	mat.set_shader_parameter("tutam", 1.0 if g.get("ot_bicim", "") == "tutam" else 0.0)
	q.material = mat
	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	mm.mesh = q
	mm.instance_count = int(float(a["ot_sayisi"]) * float(g.get("ot_sayi_carpan", 1.0)))
	var yx: float = a.get("yol_x", 0.0)
	var yg: float = a["yol"]["genislik"] if a["yol"]["acik"] else 0.0
	# Faz 5.2 D3: kümelenmiş dağılım (aynı toplam sayı; doğada ot öbek öbek büyür)
	var kume: bool = g.get("ot_dagilim", "") == "kume"
	var merkezler: Array = []
	if kume:
		for c in maxi(1, int(mm.instance_count / 10)):
			merkezler.append(Vector2(rng.randf_range(alan[0], alan[1]), rng.randf_range(alan[2], alan[3])))
	for i in mm.instance_count:
		var x := rng.randf_range(alan[0], alan[1])
		var z := rng.randf_range(alan[2], alan[3])
		if kume:
			var c: Vector2 = merkezler[rng.randi() % merkezler.size()]
			var r := absf(rng.randfn(0.0, float(g.get("kume_yaricap", 0.45))))
			var aci := rng.randf() * TAU
			x = c.x + cos(aci) * r
			z = c.y + sin(aci) * r
		if absf(x - yx) < yg:
			x = yx + signf(x - yx + 0.001) * rng.randf_range(yg, yg + 1.4)
		var b := Basis(Vector3.UP, rng.randf() * TAU).rotated(Vector3(1, 0, 0), rng.randf_range(-0.25, 0.25)).scaled(Vector3.ONE * rng.randf_range(0.5, 1.3))
		mm.set_instance_transform(i, Transform3D(b, Vector3(x, 0.02, z)))
	var mmi := MultiMeshInstance3D.new()
	mmi.multimesh = mm
	kok.add_child(mmi)
