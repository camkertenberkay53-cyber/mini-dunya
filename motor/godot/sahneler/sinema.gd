extends RefCounted
## Sinematik paket — son işlem katmanı (ekran uzayı, tek geçiş; Compatibility uyumlu). Kendi yazımımız (dış kaynak yok).
## - vinyet: kenarları yumuşakça karartır (göz merkeze)
## - bölünmüş tonlama: gölgeler hafif soğuk, ışıklar hafif sıcak (belgesel/sinema renk derecelendirmesi)
## - film greni: çok hafif, kare başına tohumlu (sabit kare hızında belirlenimci)
## k: is.json "sinema" (kurallar/gorsel.yaml). acik: false → katman eklenmez.

const SHADER := """
shader_type canvas_item;
uniform sampler2D ekran : hint_screen_texture, filter_linear;
uniform float vinyet = 0.32;
uniform float vinyet_yumusak = 0.55;
uniform vec3 golge_ton = vec3(0.96, 1.0, 1.05);
uniform vec3 isik_ton = vec3(1.05, 1.0, 0.94);
uniform float ton_guc = 1.0;
uniform float gren = 0.025;
uniform float kare = 0.0;
float hs(vec2 p){ return fract(sin(dot(p, vec2(12.9898, 78.233)) + kare * 0.618) * 43758.5453); }
void fragment(){
  vec3 c = texture(ekran, SCREEN_UV).rgb;
  float l = dot(c, vec3(0.299, 0.587, 0.114));
  vec3 ton = mix(golge_ton, isik_ton, smoothstep(0.15, 0.85, l));
  c = mix(c, c * ton, ton_guc);
  vec2 d = SCREEN_UV - 0.5;
  d.x *= SCREEN_PIXEL_SIZE.y / SCREEN_PIXEL_SIZE.x;   // en-boy düzeltmesi (dikey kadrajda yuvarlak vinyet)
  float r = length(d) / length(vec2(0.5 * SCREEN_PIXEL_SIZE.y / SCREEN_PIXEL_SIZE.x, 0.5));
  c *= 1.0 - vinyet * smoothstep(1.0 - vinyet_yumusak, 1.15, r);
  c += (hs(FRAGCOORD.xy) - 0.5) * gren;
  COLOR = vec4(c, 1.0);
}
"""

static func kur(kok: Node, k: Dictionary) -> ShaderMaterial:
	var cl := CanvasLayer.new()
	cl.layer = 100
	var r := ColorRect.new()
	r.set_anchors_preset(Control.PRESET_FULL_RECT)
	r.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var sh := Shader.new()
	sh.code = SHADER
	var m := ShaderMaterial.new()
	m.shader = sh
	m.set_shader_parameter("vinyet", float(k.get("vinyet", 0.32)))
	m.set_shader_parameter("vinyet_yumusak", float(k.get("vinyet_yumusak", 0.55)))
	var g: Array = k.get("golge_ton", [0.96, 1.0, 1.05])
	var i: Array = k.get("isik_ton", [1.05, 1.0, 0.94])
	m.set_shader_parameter("golge_ton", Vector3(g[0], g[1], g[2]))
	m.set_shader_parameter("isik_ton", Vector3(i[0], i[1], i[2]))
	m.set_shader_parameter("ton_guc", float(k.get("ton_guc", 1.0)))
	m.set_shader_parameter("gren", float(k.get("gren", 0.025)))
	r.material = m
	cl.add_child(r)
	kok.add_child(cl)
	return m
