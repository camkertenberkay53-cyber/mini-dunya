extends RefCounted
## Ortam kurucu (Faz 4): ışık, gök, sis, arazi, dağlar ve otlar VERİDEN kurulur.
## Görünüm Faz 2 ölçüm sahnesinden (olcum.gd) alındı; olcum.gd ölçüm tabanı olarak DEĞİŞMEDEN kalır.
## Bütün sayılar is.json'daki "arazi" ve "isik" hazır ayarlarından gelir (motor/uretim/kurallar/arazi.yaml).

static func _renk(a: Array) -> Color:
	return Color(a[0], a[1], a[2])

static func _v3(a: Array) -> Vector3:
	return Vector3(a[0], a[1], a[2])

## Faz 5.2 görsel iyileştirmeleri (üretim entegrasyonu): bütün iyileştirmeler is.json'daki "isik.gorsel" ve
## "arazi.gorsel" sözlükleriyle açılır (kurallar/gorsel.yaml → aktif profil; render.is_hazirla ekler).
## "gorsel" sözlüğü boşsa davranış Faz 5.2 öncesi üretimle aynıdır (geri dönüş: gorsel.yaml aktif: yok).
## Faz 5.2 öncesi dosya: deneyler/faz52_entegrasyon/ortam_v0_yedek.gd. tani_* anahtarları yalnız teşhis içindir.
static func _resim(yol: String, mip: bool) -> ImageTexture:
	var img := Image.load_from_file(yol)
	if img == null:
		push_error("DENEY: resim yüklenemedi " + yol)
		return null
	if mip:
		img.generate_mipmaps()
	return ImageTexture.create_from_image(img)

const BULUT_GOK_SHADER := """
shader_type sky;
uniform vec3 tepe; uniform vec3 ufuk; uniform float egri = 0.12;
uniform float miktar = 0.42; uniform float olcek = 1.4; uniform float yogunluk = 0.85; uniform vec2 kayma = vec2(0.0);
float h(vec2 p){ return fract(sin(dot(p, vec2(127.1,311.7)))*43758.5453); }
float n(vec2 p){ vec2 i=floor(p), f=fract(p); f=f*f*(3.0-2.0*f);
  return mix(mix(h(i),h(i+vec2(1,0)),f.x), mix(h(i+vec2(0,1)),h(i+vec2(1,1)),f.x), f.y); }
float fbm(vec2 p){ float s=0.0, a=0.5; for(int i=0;i<5;i++){ s+=a*n(p); p=p*2.02+vec2(1.7,9.2); a*=0.5; } return s; }
void sky(){
  vec3 d = EYEDIR;
  float va = acos(clamp(d.y, -1.0, 1.0));
  float c = 1.0 - va / (PI * 0.5);
  vec3 renk;
  vec3 gunes_yon = LIGHT0_ENABLED ? LIGHT0_DIRECTION : vec3(0.0, 1.0, 0.0);
  vec3 gunes_renk = LIGHT0_ENABLED ? LIGHT0_COLOR * LIGHT0_ENERGY : vec3(1.0);
  if (d.y >= 0.0) {
    renk = mix(ufuk, tepe, clamp(1.0 - pow(1.0 - c, 1.0 / egri), 0.0, 1.0));
    float ga = acos(clamp(dot(gunes_yon, d), -1.0, 1.0));
    renk = mix(renk, gunes_renk, (1.0 - smoothstep(0.004, 0.44, ga)) * 0.35);   // güneş çevresi parlama (25° içi)
    vec2 uv = d.xz / max(d.y, 0.06) * olcek + kayma;
    float b = fbm(uv);
    float kapsama = smoothstep(1.0 - miktar, 1.0 - miktar + 0.28, b) * smoothstep(0.015, 0.16, d.y) * yogunluk;
    float isik = 0.72 + 0.4 * (0.5 + 0.5 * dot(d, gunes_yon));          // güneşe bakan bulut kenarı daha parlak
    float golge = 0.86 + 0.14 * smoothstep(0.35, 0.9, fbm(uv * 1.9 + 3.1));
    vec3 bulut = mix(ufuk, vec3(1.0), 0.7) * mix(vec3(1.0), gunes_renk, 0.25) * isik * golge;
    renk = mix(renk, bulut, kapsama);
  } else {
    renk = mix(ufuk * 0.82, vec3(0.3, 0.27, 0.22), clamp(-d.y * 4.0, 0.0, 1.0));
  }
  COLOR = renk;
}
"""

# Faz 5.2 D14: isik() sahne atmosferini hesaplar, daglar() uzak pusu bundan türetir (aynı ortam).
static var _sis_etkin := Color(0.5, 0.52, 0.54)
static var _gunes_renk := Color(1, 1, 1)
static var _gunes_yon := Vector3(0, 1, 0)

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
	elif g.get("gok_bulut", false):
		# Faz 5.4: prosedürel gök + bulut (varlık yok). Renk geçişi ProceduralSkyMaterial ile aynı formül; güneş yönü
		# ve rengi sahnenin DirectionalLight'ından (LIGHT0) gelir, gölgelerle her zaman uyumlu. Bulutlar statik.
		var bs := Shader.new()
		bs.code = BULUT_GOK_SHADER
		var bm := ShaderMaterial.new()
		bm.shader = bs
		bm.set_shader_parameter("tepe", _v3(g.get("gok_tepe", i["gok"]["tepe"])))
		bm.set_shader_parameter("ufuk", _v3(g.get("gok_ufuk", i["gok"]["ufuk"])))
		bm.set_shader_parameter("egri", float(g.get("gok_egri", 0.12)))
		bm.set_shader_parameter("miktar", float(g.get("bulut_miktar", 0.42)))
		bm.set_shader_parameter("olcek", float(g.get("bulut_olcek", 1.4)))
		bm.set_shader_parameter("yogunluk", float(g.get("bulut_yogunluk", 0.85)))
		bm.set_shader_parameter("kayma", Vector2(float(g.get("bulut_tohum", 0.0)) * 7.31, float(g.get("bulut_tohum", 0.0)) * 3.17))
		sky.sky_material = bm
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
	_sis_etkin = env.fog_light_color
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
	# Sinematik paket 2: yalnız Forward+ (Vulkan; yazılımda lavapipe) işleyicide etkin özellikler. Compatibility'de
	# Godot bunları yok sayar; varsayılan profil değişmez.
	if g.get("ssao", false):   # ortam perdelemesi: karakterler/yapılar yere ve birbirine oturur
		env.ssao_enabled = true
		env.ssao_radius = float(g.get("ssao_yaricap", 1.2))
		env.ssao_intensity = float(g.get("ssao_guc", 2.0))
		env.ssao_power = 1.5
	if g.get("ssil", false):
		env.ssil_enabled = true
		env.ssil_intensity = float(g.get("ssil_guc", 0.8))
	if g.get("hacimsel_sis", false):   # hacimsel sis: güneş huzmeleri, derinlik, havadaki toz
		env.volumetric_fog_enabled = true
		env.volumetric_fog_density = float(g.get("hsis_yogunluk", 0.012))
		env.volumetric_fog_albedo = _renk(g.get("hsis_renk", [0.9, 0.85, 0.78]))
		env.volumetric_fog_anisotropy = float(g.get("hsis_anizotropi", 0.6))
		env.volumetric_fog_length = float(g.get("hsis_uzunluk", 90.0))
		env.volumetric_fog_sky_affect = float(g.get("hsis_gok", 0.15))
		env.volumetric_fog_gi_inject = 0.0
	var we := WorldEnvironment.new()
	we.environment = env
	kok.add_child(we)
	var gunes := DirectionalLight3D.new()
	gunes.rotation_degrees = _v3(i["gunes"]["aci"])
	gunes.light_color = _renk(i["gunes"]["renk"])
	gunes.light_energy = float(i["gunes"]["guc"]) * float(g.get("gunes_carpan", 1.0))
	if g.has("gunes_renk"):
		gunes.light_color = _renk(g["gunes_renk"])
	gunes.shadow_enabled = not bool(g.get("tani_golge_yok", false))
	gunes.shadow_blur = float(g.get("golge_yumusaklik", 1.0))
	gunes.directional_shadow_max_distance = 60.0
	if g.get("hacimsel_sis", false):
		gunes.light_volumetric_fog_energy = float(g.get("hsis_gunes", 1.5))
	kok.add_child(gunes)
	_gunes_yon = gunes.global_transform.basis.z.normalized()
	_gunes_renk = gunes.light_color
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
uniform float doku_renk = 1.0; uniform float doku_ort = 0.4; uniform float doku_normal = 1.0;   // Faz 5.4: 0 = yalnız ayrıntı (renk hazır ayardan)
uniform float batma_bas = 0.0;
uniform float iz_tekerlek = 0.0; uniform float teker_derinlik = 0.35; uniform float teker_genislik = 0.18;  // Faz 5.2 D15: yönlü çizgi gürültüsü yerine iki tekerlek izi + mesafeyle sönen ince doku
uniform float tani_iz_yok = 0.0; uniform float tani_ince_yok = 0.0;   // Faz 5.2 D15 teşhis anahtarları   // Faz 5.2 D13: >0 ise ana zemin bu yarıçaptan sonra uzak arazinin altına batar
float h(vec2 p){ return fract(sin(dot(p, vec2(127.1,311.7)))*43758.5453); }
float n(vec2 p){ vec2 i=floor(p), f=fract(p); f=f*f*(3.0-2.0*f);
  return mix(mix(h(i),h(i+vec2(1,0)),f.x), mix(h(i+vec2(0,1)),h(i+vec2(1,1)),f.x), f.y); }
float fbm(vec2 p){ float s=0.0, a=0.5; for(int i=0;i<5;i++){ s+=a*n(p); p*=2.03; a*=0.5; } return s; }
varying vec3 wp;
void vertex(){
  wp = (MODEL_MATRIX * vec4(VERTEX,1.0)).xyz;
  float uzak = smoothstep(duz_yari, duz_yari * 10.0, abs(wp.x - yol_x));
  VERTEX.y += fbm(wp.xz*0.02)*tepe*uzak + fbm(wp.xz*0.25)*0.35*uzak;
  if (batma_bas > 0.0) { VERTEX.y -= 40.0 * smoothstep(batma_bas, batma_bas + 30.0, length(VERTEX.xz)); }
  wp.y = VERTEX.y;
}
void fragment(){
  float yol = yol_acik * (1.0 - smoothstep(yol_gen*0.7, yol_gen*1.4, abs(wp.x - yol_x + sin(wp.z*0.05)*1.2)));
  float d = fbm(wp.xz*0.6);
  float iz = tani_iz_yok > 0.5 ? 0.5 : fbm(wp.xz*vec2(4.0,0.6));
  if (iz_tekerlek > 0.5) {
    float yx = wp.x - yol_x + sin(wp.z*0.05)*1.2;
    float teker = exp(-pow((abs(yx) - 0.75) / teker_genislik, 2.0));
    float ayak = length(fwidth(wp.xz));                 // piksel başına dünya birimi (uzaklık ölçüsü)
    float ince = mix(fbm(wp.xz*1.5), 0.5, smoothstep(0.08, 0.5, ayak));
    iz = 0.5 - teker * teker_derinlik + (ince - 0.5) * 0.3;
  }
  vec3 c = mix(cimen, cimen2, d);
  c = mix(c, kuru, smoothstep(0.55,0.75,fbm(wp.xz*0.08)));
  vec3 t = mix(toprak, toprak2, d) * (0.85 + 0.25*iz);
  c *= 0.9 + 0.2 * (tani_ince_yok > 0.5 ? 0.5 : fbm(wp.xz*2.3));   // ince ölçekli renk dalgalanması (düz renk alanları kırılsın)
  vec3 taban = mix(c, t, yol);
  if (doku_acik > 0.5) {
    vec2 uv = wp.xz * doku_olcek;
    vec3 d1 = texture(d_alb, uv).rgb;
    vec3 d2 = texture(d_alb, uv * 0.23 + vec2(0.37, 0.11)).rgb;   // ikinci ölçek: döşeme tekrarını kırar
    vec3 dk = mix(d1, d2, 0.35);
    float l = max(dot(dk, vec3(0.299, 0.587, 0.114)), 0.02);
    vec3 ayrinti = taban * clamp(l / doku_ort, 0.45, 1.7);                     // dokunun yalnız parlaklık ayrıntısı
    vec3 renkli = taban * (dk / l) * 0.5 + dk * 0.5;
    float uzak_k = 1.0 - smoothstep(25.0, 90.0, length(VERTEX));              // uzakta döşeme tekrarı görünmesin
    ALBEDO = mix(taban, mix(ayrinti, renkli, doku_renk), doku_karisim * uzak_k);
    NORMAL_MAP = texture(d_nor, uv).rgb;
    NORMAL_MAP_DEPTH = doku_normal * uzak_k;
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
	mat.set_shader_parameter("iz_tekerlek", 1.0 if g.get("zemin_iz", "") == "tekerlek" else 0.0)
	mat.set_shader_parameter("teker_derinlik", float(g.get("teker_derinlik", 0.35)))
	mat.set_shader_parameter("teker_genislik", float(g.get("teker_genislik", 0.18)))
	mat.set_shader_parameter("tani_iz_yok", 1.0 if g.get("tani_iz_yok", false) else 0.0)
	mat.set_shader_parameter("tani_ince_yok", 1.0 if g.get("tani_ince_yok", false) else 0.0)
	if g.get("dag_gecis", false):
		mat.set_shader_parameter("batma_bas", float(g.get("gecis_bas", 200.0)) + 5.0)
	if g.has("zemin_alb"):
		var dalb := _resim(g["zemin_alb"], true)
		mat.set_shader_parameter("d_alb", dalb)
		if dalb:   # dokunun ortalama parlaklığı (ayrıntı modu bununla normalize edilir)
			var ki: Image = dalb.get_image().duplicate()
			ki.clear_mipmaps()
			ki.resize(1, 1, Image.INTERPOLATE_BILINEAR)
			var o: Color = ki.get_pixel(0, 0)
			mat.set_shader_parameter("doku_ort", maxf(0.05, 0.299 * o.r + 0.587 * o.g + 0.114 * o.b))
		mat.set_shader_parameter("doku_renk", float(g.get("doku_renk", 1.0)))
		mat.set_shader_parameter("doku_normal", float(g.get("doku_normal", 1.0)))
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
uniform float gecis = 0.0; uniform float gecis_bas = 200.0;
uniform float tepe = 14.0; uniform float duz_yari = 6.0; uniform float yol_x = 0.0;
uniform vec3 cimen; uniform vec3 cimen2; uniform vec3 kuru;
float h(vec2 p){ return fract(sin(dot(p, vec2(127.1,311.7)))*43758.5453); }
float n(vec2 p){ vec2 i=floor(p), f=fract(p); f=f*f*(3.0-2.0*f);
  return mix(mix(h(i),h(i+vec2(1,0)),f.x), mix(h(i+vec2(0,1)),h(i+vec2(1,1)),f.x), f.y); }
float fbm(vec2 p){ float s=0.0, a=0.5; for(int i=0;i<6;i++){ s+=a*n(p); p*=2.07; a*=0.5; } return s; }
// Ana zeminin gürültüsü ve yükseklik fonksiyonu ile birebir aynı (sürekli yüzey için)
float zfbm(vec2 p){ float s=0.0, a=0.5; for(int i=0;i<5;i++){ s+=a*n(p); p*=2.03; a*=0.5; } return s; }
float zemin_h(vec2 w){
  float uzak = smoothstep(duz_yari, duz_yari * 10.0, abs(w.x - yol_x));
  return zfbm(w*0.02)*tepe*uzak + zfbm(w*0.25)*0.35*uzak;
}
float sirt(vec2 p){ float s=0.0, a=0.5; for(int i=0;i<5;i++){ s+=a*(1.0-abs(n(p)*2.0-1.0)); p*=2.11; a*=0.5; } return s; }
float yuk(vec2 w){
  float d = distance(w, merkez);
  float k = smoothstep(bas, tam, d);
  float dag = (fbm(w*0.004)*0.55 + sirt(w*0.009)*0.45) * yukseklik * k;
  if (gecis > 0.5) {
    float kg = smoothstep(gecis_bas, tam, d);
    float ic = smoothstep(gecis_bas - 10.0, gecis_bas, d);
    return zemin_h(w) + 0.15 + (fbm(w*0.004)*0.55 + sirt(w*0.009)*0.45) * yukseklik * kg - 6.0 * (1.0 - ic);
  }
  return -2.0 + dag;
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
  float kr = gecis > 0.5 ? smoothstep(gecis_bas, gecis_bas + 160.0, distance(wp.xz, merkez)) : 1.0;
  vec3 c = mix(r0, r1, smoothstep(0.1, 0.6, hv + (d-0.5)*0.3));
  c = mix(c, r2, smoothstep(0.65, 1.0, hv));
  c *= 0.82 + 0.3*fbm(wp.xz*0.4);
  if (gecis > 0.5) {
    // ana zeminin renk mantığı (yol hariç), uzaklaştıkça dağ paletine yumuşak geçiş
    float dz = zfbm(wp.xz*0.6);
    vec3 cz = mix(cimen, cimen2, dz);
    cz = mix(cz, kuru, smoothstep(0.55, 0.75, zfbm(wp.xz*0.08)));
    cz *= 0.9 + 0.2 * zfbm(wp.xz*2.3);
    c = mix(cz, c, kr);
  }
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
		m.subdivide_width = int(g.get("dag_bolum", 240))
		m.subdivide_depth = int(g.get("dag_bolum", 240))
		var sh := Shader.new()
		sh.code = UZAK_SHADER
		if g.get("dag_pus", "") == "dinamik":
			# Faz 5.2 D14: uzak pus = sahne sisiyle aynı ortam (preset sis rengi) + güneşe bakışta güneş rengine ileri saçılma
			sh.code = UZAK_SHADER.replace("ROUGHNESS = 1.0;", "ROUGHNESS = 1.0;\n  float uz = length(VERTEX);\n  vec3 bakis = normalize(wp - CAMERA_POSITION_WORLD);\n  float sac = pow(max(dot(bakis, gunes_yon), 0.0), 6.0);\n  vec3 pr = mix(pus_taban, gunes_renk * dot(pus_taban, vec3(0.333)) * 1.3, sac * 0.6);\n  FOG = vec4(pr, min(pus_max, 1.0 - exp(-uz * pus_yogunluk)));").replace("uniform float bas = 180.0;", "uniform vec3 pus_taban; uniform vec3 gunes_renk; uniform vec3 gunes_yon; uniform float pus_yogunluk = 0.0025; uniform float pus_max = 0.35; uniform float bas = 180.0;")
		elif g.has("dag_pus_renk"):
			# Faz 5.2 D8: uzak arazi sahnenin genel sisini değil kendi hava perspektifini kullanır (FOG çıkışı)
			sh.code = UZAK_SHADER.replace("ROUGHNESS = 1.0;", "ROUGHNESS = 1.0;\n  float uz = length(VERTEX);\n  FOG = vec4(pus_renk, min(pus_max, 1.0 - exp(-uz * pus_yogunluk)));").replace("uniform float bas = 180.0;", "uniform vec3 pus_renk; uniform float pus_yogunluk = 0.004; uniform float pus_max = 0.6; uniform float bas = 180.0;")
		if g.get("dag_tani", "") == "sabit_renk":
			sh.code = sh.code.replace("ALBEDO = c;", "ALBEDO = vec3(0.25, 0.1, 0.1);")
		elif g.get("dag_tani", "") == "normal_yukari":
			sh.code = sh.code.replace("  NORMAL = normalize(vec3(", "  vec3 _n = normalize(vec3(")
		var mat := ShaderMaterial.new()
		mat.shader = sh
		if g.get("dag_pus", "") == "dinamik":
			var pk := float(g.get("dag_pus_katsayi", 0.68))
			mat.set_shader_parameter("pus_taban", Vector3(_sis_etkin.r * pk, _sis_etkin.g * pk, _sis_etkin.b * pk))
			mat.set_shader_parameter("gunes_renk", Vector3(_gunes_renk.r, _gunes_renk.g, _gunes_renk.b))
			mat.set_shader_parameter("gunes_yon", _gunes_yon)
			mat.set_shader_parameter("pus_yogunluk", float(g.get("dag_pus_yogunluk", 0.0025)))
			mat.set_shader_parameter("pus_max", float(g.get("dag_pus_max", 0.35)))
		elif g.has("dag_pus_renk"):
			mat.set_shader_parameter("pus_renk", _v3(g["dag_pus_renk"]))
			mat.set_shader_parameter("pus_yogunluk", float(g.get("dag_pus_yogunluk", 0.004)))
			mat.set_shader_parameter("pus_max", float(g.get("dag_pus_max", 0.6)))
		var rk: Array = a["dag_renkleri"]
		var ton := float(g.get("dag_ton", 1.0))
		mat.set_shader_parameter("r0", _v3(rk[0]) * ton)
		mat.set_shader_parameter("r1", _v3(rk[min(1, rk.size() - 1)]) * ton)
		mat.set_shader_parameter("r2", _v3(rk[rk.size() - 1]) * ton)
		mat.set_shader_parameter("bas", float(g.get("dag_bas", 180.0)))
		if g.get("dag_gecis", false):
			mat.set_shader_parameter("gecis", 1.0)
			mat.set_shader_parameter("gecis_bas", float(g.get("gecis_bas", 200.0)))
			mat.set_shader_parameter("tepe", float(a["tepe_yuksekligi"]))
			mat.set_shader_parameter("duz_yari", float(a.get("duz_yari", 6.0)))
			mat.set_shader_parameter("yol_x", float(a.get("yol_x", 0.0)))
			for kz in ["cimen", "cimen2", "kuru"]:
				mat.set_shader_parameter(kz, _v3(a["zemin"][kz]))
		mat.set_shader_parameter("tam", float(g.get("dag_tam", 420.0)))
		mat.set_shader_parameter("merkez", merkez)
		mat.set_shader_parameter("yukseklik", float(g.get("dag_yukseklik", 45.0)))
		var mi := MeshInstance3D.new()
		mi.mesh = m
		mi.material_override = mat
		mi.position = Vector3(merkez.x, 0, merkez.y)
		mi.extra_cull_margin = 200.0
		if g.has("dag_oncelik"):   # Faz 5.2 D16: uzak arazi en son çizilir (önündeki zeminin altında boşuna gölgelenmez)
			mat.render_priority = int(g["dag_oncelik"])
		if g.get("dag_golge_al", "") == "yok":   # Faz 5.2 D16: uzak arazi gölge örneklemez (gölge mesafesinin ötesinde zaten gölgesiz)
			sh.code = sh.code.replace("render_mode diffuse_burley, specular_disabled;", "render_mode diffuse_burley, specular_disabled, shadows_disabled;")
		if g.get("tani_dag_isiksiz", false):
			sh.code = sh.code.replace("render_mode diffuse_burley, specular_disabled;", "render_mode unshaded;")
		if g.get("tani_dag_duz", false):
			sh.code = sh.code.replace("void fragment(){", "void fragment(){ ALBEDO = r0; ROUGHNESS = 1.0; }\nvoid _eski(){")
		if g.get("dag_golge", "") == "yok":   # Faz 5.2 D16: uzak arazi gölge geçişine girmez
			mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
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
// Faz 5.2 D16: mesafe LOD (kapalıyken hiçbir şey değişmez). kam her kare yardımcı düğümce yazılır.
uniform float lod = 0.0; uniform vec3 kam = vec3(0.0);
uniform float lod_bas = 6.0; uniform float lod_son = 16.0; uniform float lod_oran = 0.35;
uniform float lod_yaprak = 4.0; uniform float lod_telafi = 1.0;
uniform float golge_bas = 1000.0; uniform float golge_son = 1001.0;  // gölge geçişinde ot gölgesi yalnız yakında
// Faz 5.2 D17: aynı kartlarla bitki çeşitliliği (yeni geometri/örnek yok). 0 = kapalı.
uniform float cesit = 0.0; uniform float oran_basak = 0.12; uniform float oran_genis = 0.10;
varying float renk_payi;
varying float yaprak_n;
varying float tur;   // 0 ot tutamı, 1 başaklı uzun ot, 2 geniş yapraklı alçak bitki
void vertex(){
  vec3 m = (MODEL_MATRIX * vec4(0,0,0,1)).xyz;
  renk_payi = fract(sin(dot(m.xz, vec2(12.9898, 78.233))) * 43758.5453);
  vec3 w = (MODEL_MATRIX * vec4(0,0,0,1)).xyz;
  float tepe = 1.0 - UV.y;
  VERTEX.x += (sin(TIME*1.8 + w.x*0.7 + w.z*0.4)*0.07 + sin(TIME*4.1 + w.z)*0.02) * tepe * tepe;
  tur = 0.0;
  if (cesit > 0.5) {
    float ht = fract(sin(dot(m.xz, vec2(7.131, 157.17))) * 31871.37);
    if (ht < oran_basak) { tur = 1.0; VERTEX.y *= 1.45; }
    else if (ht < oran_basak + oran_genis) { tur = 2.0; VERTEX.y *= 0.55; VERTEX.x *= 1.3; }
  }
  VERTEX.x *= mix(1.0, mix(0.35, 1.0, tutam), tepe);
  yaprak_n = tur > 0.5 ? (tur < 1.5 ? 3.0 : 5.0) : 7.0;
  if (lod > 0.5) {
    float f = smoothstep(lod_bas, lod_son, distance(m.xz, kam.xz));
    float tut = mix(1.0, lod_oran, f);                       // uzakta kartların ancak bu kadarı kalır
    float h = fract(sin(dot(m.xz, vec2(3.171, 91.73))) * 23421.631);
    float olcek = clamp((tut - h) / 0.1, 0.0, 1.0);          // kaybolmadan önce küçülür (pop-in yok)
    VERTEX.x *= mix(1.0, inversesqrt(tut), lod_telafi);      // kalan kartlar örtüyü korumak için genişler
    VERTEX *= olcek;                                         // 0 → dejenere üçgen, piksel maliyeti yok
    yaprak_n = mix(yaprak_n, min(yaprak_n, lod_yaprak), f);
    if (IN_SHADOW_PASS) { VERTEX *= 1.0 - smoothstep(golge_bas, golge_son, distance(m.xz, kam.xz)); }
  }
}
void fragment(){
  float bas_k = 0.0;
  if (tutam > 0.5) {
    float t = 1.0 - UV.y;
    float ic = 0.0;
    int n = int(ceil(yaprak_n));
    float gen_k = tur > 1.5 ? 2.2 : (tur > 0.5 ? 0.8 : sqrt(7.0 / yaprak_n));
    for (int k = 0; k < 7; k++) {
      if (k >= n) { break; }
      float fk = float(k);
      float s = fract(sin(fk * 12.9898 + renk_payi * 78.233) * 43758.5453);
      float s2 = fract(sin(fk * 39.346 + renk_payi * 11.135) * 24634.6345);
      float boy = 0.5 + 0.5 * s2;
      float merkez = 0.12 + 0.76 * s + (s2 - 0.5) * 0.35 * t * t;
      float gen = 0.05 * gen_k * (1.0 - t / boy);
      if (t < boy && abs(UV.x - merkez) < gen) { ic = 1.0; }
      if (tur > 0.5 && tur < 1.5 && t < boy && t > boy * 0.72 && abs(UV.x - merkez) < 0.028) { ic = 1.0; bas_k = 1.0; }
    }
    if (ic < 0.5) { discard; }
  }
  if (yukari_normal > 0.5) { NORMAL = normalize((VIEW_MATRIX * vec4(0.0, 1.0, 0.0, 0.0)).xyz); }
  vec3 u = mix(ust, kuru, smoothstep(0.55, 1.0, renk_payi));
  vec3 c = mix(alt, u, 1.0 - UV.y) * (0.85 + 0.3 * renk_payi);
  if (tur > 1.5) { c = mix(alt, ust, 0.45) * vec3(0.78, 0.9, 0.82) * (0.85 + 0.3 * renk_payi); }
  if (tur > 0.5 && tur < 1.5) { c = mix(c, kuru * 1.15, 0.35 + 0.65 * bas_k); }
  ALBEDO = c;
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
	if g.get("ot_cesit", false):
		mat.set_shader_parameter("cesit", 1.0)
		for k in ["oran_basak", "oran_genis"]:
			if g.has(k):
				mat.set_shader_parameter(k, float(g[k]))
	if g.get("tani_ot_yok", false):
		mm.instance_count = 0
	if g.get("ot_lod", "") == "mesafe":
		mat.set_shader_parameter("lod", 1.0)
		for k in ["lod_bas", "lod_son", "lod_oran", "lod_yaprak", "lod_telafi", "golge_bas", "golge_son"]:
			if g.has(k):
				mat.set_shader_parameter(k, float(g[k]))
		var yard := Node.new()
		var gs := GDScript.new()
		gs.source_code = "extends Node\nvar mat: ShaderMaterial\nfunc _process(_d):\n\tvar c := get_viewport().get_camera_3d()\n\tif c:\n\t\tmat.set_shader_parameter(\"kam\", c.global_position)\n"
		gs.reload()
		yard.set_script(gs)
		yard.set("mat", mat)
		yard.process_priority = 1000
		kok.add_child(yard)
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
	var parca: float = float(g.get("ot_parca", 0.0))
	if parca <= 0.0:
		var mmi := MultiMeshInstance3D.new()
		mmi.multimesh = mm
		if g.get("ot_golge", "") == "yok":
			mmi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		kok.add_child(mmi)
		return
	# Faz 5.2 D16: aynı örnekler parça parça (ızgara) bölünür → görüş dışındaki parçalar motorca elenir.
	# Dönüşümler ve RNG sırası değişmez; görüntü birebir aynı kalır, yalnız çizilen örnek sayısı azalır.
	var kova := {}
	for i in mm.instance_count:
		var tr := mm.get_instance_transform(i)
		var anahtar := Vector2i(floori(tr.origin.x / parca), floori(tr.origin.z / parca))
		if not kova.has(anahtar):
			kova[anahtar] = []
		kova[anahtar].append(tr)
	for anahtar in kova:
		var liste: Array = kova[anahtar]
		var pm := MultiMesh.new()
		pm.transform_format = MultiMesh.TRANSFORM_3D
		pm.mesh = q
		pm.instance_count = liste.size()
		for j in liste.size():
			pm.set_instance_transform(j, liste[j])
		var pmi := MultiMeshInstance3D.new()
		pmi.multimesh = pm
		if g.get("ot_golge", "") == "yok":
			pmi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		kok.add_child(pmi)
