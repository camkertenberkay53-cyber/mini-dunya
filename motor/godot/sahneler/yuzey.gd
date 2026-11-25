extends RefCounted
## Gerçekçi karakter yüzeyi — kıyafet, deri, zırh ve ekipman malzemelerine gerçek PBR ayrıntısı (CC0; kendi yazımımız).
## Malzeme ADI kural tablosuyla eşleşir (kurallar/yuzey.yaml). Kıyafetin tasarlanmış rengi ve kendi dokusu korunur;
## üstüne gerçek dokuma/deri/zincir/çelik ayrıntısı (parlaklık oranı), kabartma (normal), pürüzlülük ve ortam perdelemesi
## eklenir. UV tabanlıdır: iskeletli animasyonda doku kaymaz (dünya-uzayı üç yönlü eşleme kayardı).
## Gölgelendirici ve dokular bir kez kurulur; kişi başına yalnız renk/doku parametresi değişir.

const SHADER := """
shader_type spatial;
render_mode diffuse_burley, specular_schlick_ggx;
uniform vec4 renk : source_color = vec4(1.0);
uniform sampler2D taban : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform float taban_var = 0.0;
uniform sampler2D d_alb : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D d_nor : hint_normal, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D d_pur : filter_linear_mipmap_anisotropic, repeat_enable;   // pürüzlülük (arm.g ya da rough)
uniform float pur_kanal = 1.0;      // 1: arm (G kanalı), 0: tek kanallı rough
uniform float tekrar = 2.0;
uniform float d_ort = 0.4;
uniform float detay_guc = 0.6;
uniform float renk_karis = 0.0;     // >0: dokunun kendi rengi de karışır (zincir halkası, çelik)
uniform float normal_guc = 1.0;
uniform float metal = 0.0;
uniform float pur_carp = 1.0;
uniform float pur_taban = 0.0;
uniform float asinma = 0.0;          // düşük frekanslı kir/solma lekeleri (kullanılmış giysi)
uniform float kenar_koyu = 0.0;      // kumaşın kenara bakan yüzlerinde hafif koyulaşma (hacim, kat izlenimi)
float hs(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float gn(vec2 p){ vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(hs(i), hs(i + vec2(1, 0)), f.x), mix(hs(i + vec2(0, 1)), hs(i + vec2(1, 1)), f.x), f.y); }
void fragment(){
  vec3 b = renk.rgb;
  if (taban_var > 0.5) { b *= texture(taban, UV).rgb; }
  vec2 du = UV * tekrar;
  vec3 d = texture(d_alb, du).rgb;
  float l = dot(d, vec3(0.299, 0.587, 0.114)) / max(d_ort, 0.02);
  vec3 c = b * mix(1.0, clamp(l, 0.25, 1.9), detay_guc);
  c = mix(c, d * dot(b, vec3(0.333)) / max(d_ort, 0.02), renk_karis);
  if (asinma > 0.0) {
    float lk = gn(UV * 3.1) * 0.6 + gn(UV * 7.3 + 4.1) * 0.4;
    c *= 1.0 - asinma * smoothstep(0.45, 0.85, lk);                              // kir/is lekesi
    c = mix(c, vec3(dot(c, vec3(0.333))) * 1.08, asinma * 0.6 * smoothstep(0.2, 0.6, gn(UV * 1.7 + 9.0)));   // solma
  }
  if (kenar_koyu > 0.0) { c *= mix(1.0, 0.55 + 0.45 * clamp(dot(NORMAL, VIEW), 0.0, 1.0), kenar_koyu); }
  ALBEDO = c;
  NORMAL_MAP = texture(d_nor, du).rgb;
  NORMAL_MAP_DEPTH = normal_guc;
  vec4 pr = texture(d_pur, du);
  float r = mix(pr.r, pr.g, pur_kanal);
  ROUGHNESS = clamp(pur_taban + r * pur_carp, 0.08, 1.0);
  METALLIC = metal;
  if (pur_kanal > 0.5) { AO = pr.r; AO_LIGHT_AFFECT = 0.3; }
}
"""

static var _sh: Shader = null
static var _kurallar: Array = []
static var _dokular := {}

static func kur(k: Dictionary) -> void:
	_kurallar = []
	if not k.get("acik", false):
		return
	for x in k.get("kurallar", []):
		var r := RegEx.new()
		r.compile(str(x["desen"]))
		_kurallar.append([r, x])

static func _doku(yol: String) -> ImageTexture:
	if not _dokular.has(yol):
		var img := Image.load_from_file(yol)
		img.generate_mipmaps()
		var t := ImageTexture.create_from_image(img)
		var kc := img.duplicate() as Image   # ortalama parlaklık (ayrıntı oranı bununla normalize edilir)
		kc.clear_mipmaps()
		kc.resize(1, 1, Image.INTERPOLATE_BILINEAR)
		var o: Color = kc.get_pixel(0, 0)
		t.set_meta("ort", maxf(0.04, 0.299 * o.r + 0.587 * o.g + 0.114 * o.b))
		_dokular[yol] = t
	return _dokular[yol]

static func _malzeme(eski: BaseMaterial3D, x: Dictionary) -> ShaderMaterial:
	if _sh == null:
		_sh = Shader.new()
		_sh.code = SHADER
	var m := ShaderMaterial.new()
	m.shader = _sh
	m.set_shader_parameter("renk", eski.albedo_color)
	if eski.albedo_texture:
		m.set_shader_parameter("taban", eski.albedo_texture)
		m.set_shader_parameter("taban_var", 1.0)
	var alb := _doku(x["diff"])
	m.set_shader_parameter("d_alb", alb)
	m.set_shader_parameter("d_ort", float(alb.get_meta("ort")))
	m.set_shader_parameter("d_nor", _doku(x["nor"]))
	m.set_shader_parameter("d_pur", _doku(x["pur"]))
	m.set_shader_parameter("pur_kanal", 1.0 if x.get("pur_arm", true) else 0.0)
	for ad in ["tekrar", "detay_guc", "renk_karis", "normal_guc", "metal", "pur_carp", "pur_taban", "asinma", "kenar_koyu"]:
		if x.has(ad):
			m.set_shader_parameter(ad, float(x[ad]))
	return m

static func _eslesen(ad: String) -> Dictionary:
	for k in _kurallar:
		if (k[0] as RegEx).search(ad) != null:
			return k[1]
	return {}

## Karakterin (ve taktığı ekipmanın) yüzeylerini yükseltir. Kural yoksa ya da paket kapalıysa hiçbir şey yapmaz.
static func uygula(kok: Node) -> int:
	if _kurallar.is_empty():
		return 0
	var sayi := 0
	for m in kok.find_children("*", "MeshInstance3D", true, false):
		var mi: MeshInstance3D = m
		if mi.mesh == null:
			continue
		for i in mi.mesh.get_surface_count():
			var mat := mi.get_active_material(i)
			if not (mat is BaseMaterial3D):
				continue
			var x := _eslesen(str(mat.resource_name).to_lower())
			if x.is_empty():
				continue
			mi.set_surface_override_material(i, _malzeme(mat as BaseMaterial3D, x))
			sayi += 1
	return sayi
