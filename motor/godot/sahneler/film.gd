extends RefCounted
## Sinematik render iyileştirmesi — derinlik tabanlı film geçişi (Compatibility/CPU uyumlu; kendi yazımımız).
## Kameraya bağlı tam ekran dörtgen; sahne rengini (hint_screen_texture) ve derinliği (hint_depth_texture) okur:
##  - atmosferik perspektif: uzaklıkla artan, güneş yönünde ısınan hava pusu; ön plan, orta plan, dağ ve gök tek
##    hava kütlesinde birleşir (ayrı ayrı sislerin "kopuk katman" görünümünü giderir). Gök pikseline dokunmaz.
##  - temas gölgesi (hafif ekran-uzayı ortam perdelemesi): nesnelerin zemine/birbirine değdiği yerler koyulaşır.
##  - alan derinliği: odak (kamera hedefi) ötesi çok hafif yumuşar (lens hissi; arka plan ayrışır).
##  - film renk derecelendirmesi: yumuşak S eğrisi, siyahların hafif kaldırılması, doygunluk sıkıştırma.
## k: is.json "film" (kurallar/gorsel.yaml). acik: false → hiçbir düğüm eklenmez (önceki görüntü).

const SHADER := """
shader_type spatial;
render_mode unshaded, depth_test_disabled, depth_draw_never, cull_disabled, fog_disabled, shadows_disabled;
uniform sampler2D ekran : hint_screen_texture, filter_linear_mipmap;
uniform sampler2D derinlik : hint_depth_texture, filter_nearest;
uniform float hata_ayikla = 0.0;
uniform vec3 pus_renk = vec3(0.72, 0.74, 0.78);
uniform vec3 pus_gunes = vec3(1.0, 0.85, 0.65);
uniform vec3 gunes_yon = vec3(0.0, 1.0, 0.0);   // dünya uzayında güneşe doğru
uniform float pus_yogunluk = 0.004;
uniform float pus_bas = 20.0;
uniform float pus_max = 0.55;
uniform float pus_yukseklik = 0.012;            // yükseldikçe hava incelir (dağ tepeleri daha net)
uniform float ao_guc = 0.35;
uniform float ao_yaricap = 0.6;
uniform float odak = 20.0;
uniform float dof_guc = 0.0;
uniform float dof_max = 2.5;
uniform float dof_bas = 1.0;
uniform float egri = 0.12;
uniform float siyah = 0.012;
uniform float doygunluk = 0.92;
uniform vec3 siyah_ton = vec3(0.0);
varying mat4 inv_view;
void vertex(){
  POSITION = vec4(VERTEX.xy, 0.0, 1.0);
  inv_view = INV_VIEW_MATRIX;
}
vec3 vpos(vec2 uv, mat4 ip){
  float d = texture(derinlik, uv).r;
  vec4 v = ip * vec4(uv * 2.0 - 1.0, d * 2.0 - 1.0, 1.0);
  return v.xyz / v.w;
}
float hs(vec2 p){ return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }
void fragment(){
  vec2 uv = SCREEN_UV;
  float d0 = texture(derinlik, uv).r;
  bool gok = d0 >= 0.99999;
  vec3 vp = vpos(uv, INV_PROJECTION_MATRIX);
  float uz = length(vp);
  vec3 c = textureLod(ekran, uv, 0.0).rgb;
  vec2 px = 1.0 / VIEWPORT_SIZE;
  // --- alan derinliği (yalnız odak ötesi; dairesel 8 örnek, mip ile) ---
  if (dof_guc > 0.0 && !gok) {
    float r = clamp((uz - odak * dof_bas) / max(odak, 1.0) * dof_guc, 0.0, dof_max);   // odak ötesi ancak dof_bas katından sonra
    if (r > 0.15) {
      vec3 s = c; float w = 1.0;
      for (int i = 0; i < 8; i++) {
        float a = float(i) * 0.785398 + 0.39;
        vec2 o = vec2(cos(a), sin(a)) * r * px * 1.6;
        s += textureLod(ekran, uv + o, log2(max(r, 1.0)) * 0.5).rgb; w += 1.0;
      }
      c = s / w;
    }
  } else if (dof_guc > 0.0 && gok) {
    c = mix(c, textureLod(ekran, uv, 1.5).rgb, clamp(dof_guc * 0.4, 0.0, 1.0));
  }
  // --- temas gölgesi (8 örnekli ekran-uzayı perdeleme; uzakta söner) ---
  if (ao_guc > 0.0 && !gok && uz < 60.0) {
    vec3 n = normalize(cross(dFdx(vp), dFdy(vp)));
    float ao = 0.0;
    float rr = ao_yaricap / max(-vp.z, 0.5);   // ekranda yarıçap (dünya ölçüsünü korur)
    float j = hs(FRAGCOORD.xy) * 6.283;
    for (int i = 0; i < 8; i++) {
      float a = float(i) * 0.785398 + j;
      float t = (float(i) + 1.0) / 8.0;
      vec2 o = vec2(cos(a), sin(a)) * rr * t * 0.9;
      vec3 q = vpos(uv + o * vec2(VIEWPORT_SIZE.y / VIEWPORT_SIZE.x, 1.0), INV_PROJECTION_MATRIX) - vp;
      float l = length(q);
      ao += max(dot(n, q / max(l, 1e-4)) - 0.08, 0.0) * smoothstep(ao_yaricap * 2.5, 0.0, l);
    }
    ao = 1.0 - clamp(ao / 8.0 * 2.2, 0.0, 1.0) * ao_guc * (1.0 - smoothstep(25.0, 60.0, uz));
    c *= ao;
  }
  // --- atmosferik perspektif: tek hava kütlesi (yükseklikle incelen üstel pus + güneş yönünde ileri saçılma) ---
  vec3 wdir = normalize((inv_view * vec4(vp, 0.0)).xyz);
  float wy = (inv_view * vec4(vp, 1.0)).y;
  float sac = pow(max(dot(wdir, gunes_yon), 0.0), 8.0);
  vec3 hava = mix(pus_renk, pus_gunes, sac * 0.75);
  if (!gok) {
    float yog = pus_yogunluk * exp(-max(wy, 0.0) * pus_yukseklik);
    float f = (1.0 - exp(-max(uz - pus_bas, 0.0) * yog)) * pus_max;
    c = mix(c, hava, f);
  } else {
    c = mix(c, hava, clamp(1.0 - abs(wdir.y) * 6.0, 0.0, 1.0) * pus_max * 0.35);   // ufuk çizgisi havayla kaynaşır
  }
  // --- film derecelendirmesi ---
  float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
  c = mix(vec3(l), c, doygunluk);
  c = clamp(c, 0.0, 1.0);
  c = mix(c, c * c * (3.0 - 2.0 * c), egri);   // yumuşak S eğrisi
  c = siyah + siyah_ton + c * (1.0 - siyah);
  if (hata_ayikla > 0.5) { c = vec3(clamp(uz / 300.0, 0.0, 1.0)); }
  ALBEDO = c;
}
"""

static func kur(kamera: Camera3D, k: Dictionary, isik: Dictionary) -> ShaderMaterial:
	var mi := MeshInstance3D.new()
	var q := QuadMesh.new()
	q.size = Vector2(2, 2)
	mi.mesh = q
	mi.extra_cull_margin = 16384.0
	mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	var sh := Shader.new()
	sh.code = SHADER
	var m := ShaderMaterial.new()
	m.shader = sh
	m.render_priority = 127
	for ad in ["pus_yogunluk", "pus_bas", "pus_max", "pus_yukseklik", "ao_guc", "ao_yaricap", "dof_guc", "dof_max", "dof_bas", "egri",
			"siyah", "doygunluk", "hata_ayikla"]:
		if k.has(ad):
			m.set_shader_parameter(ad, float(k[ad]))
	var _v := func(a): return Vector3(a[0], a[1], a[2])
	m.set_shader_parameter("pus_renk", _v.call(k.get("pus_renk", isik["sis"]["renk"])))
	m.set_shader_parameter("pus_gunes", _v.call(k.get("pus_gunes", isik["gunes"]["renk"])))
	if k.has("siyah_ton"):
		m.set_shader_parameter("siyah_ton", _v.call(k["siyah_ton"]))
	mi.material_override = m
	kamera.add_child(mi)
	return m

## Güneş yönü (dünya uzayı, güneşe doğru) ve odak uzaklığı her karede güncellenir.
static func guncelle(m: ShaderMaterial, gunes_yon: Vector3, odak: float) -> void:
	m.set_shader_parameter("gunes_yon", gunes_yon)
	m.set_shader_parameter("odak", odak)
