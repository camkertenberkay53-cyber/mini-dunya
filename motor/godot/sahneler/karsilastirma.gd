extends Node3D
## Görsel karşılaştırma: her takım için ön, yan, arka, siluet (ön+yan), yakın çekim ve orta mesafe görüntüsü.
## godot --path motor/godot res://sahneler/karsilastirma.tscn -- <cikti> <takim.json> [...]
## godot ... -- <cikti> --dizi <takim.json> [...]   -> takımlar yan yana: orta, uzak ve siluet dizisi
## Karakterler +Z'ye bakar; burada 180° çevrilip -Z'deki kameraya döndürülür. Kamera ortografik görünümlerde boya göre ölçeklenir.

const D := preload("res://sahneler/donatici.gd")
var POZ_ANI := 0.35
var POZ_ADI := "Idle_Loop"   # --poz <animasyon> <saniye>: aynı çekimleri başka bir pozda (örn. yürüyüş adımı) almak için
var kamera: Camera3D
var ortam: WorldEnvironment
var zemin: MeshInstance3D
var _siyah: StandardMaterial3D

func _ready() -> void:
	var a := OS.get_cmdline_user_args()
	var cikti: String = a[0]
	var pi := a.find("--poz")
	if pi >= 0:
		POZ_ADI = a[pi + 1]
		POZ_ANI = float(a[pi + 2])
		a = a.slice(0, pi) + a.slice(pi + 3)
	DirAccess.make_dir_recursive_absolute(cikti)
	_isik_kur()
	if a.size() > 1 and a[1] == "--dizi":
		get_window().size = Vector2i(1600, 900)
		await _dizi(cikti, a.slice(2))
	else:
		get_window().size = Vector2i(400, 800)
		for i in range(1, a.size()):
			await _tekli(cikti, a[i])
	get_tree().quit(0)

func _isik_kur() -> void:
	var g := DirectionalLight3D.new()
	g.rotation_degrees = Vector3(-38, -30, 0)
	g.light_energy = 1.25
	g.shadow_enabled = true
	add_child(g)
	ortam = WorldEnvironment.new()
	var e := Environment.new()
	e.background_mode = Environment.BG_COLOR
	e.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	e.ambient_light_color = Color(0.72, 0.72, 0.76)
	e.ambient_light_energy = 0.75
	e.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	ortam.environment = e
	add_child(ortam)
	kamera = Camera3D.new()
	add_child(kamera)
	zemin = MeshInstance3D.new()
	var pm := PlaneMesh.new()
	pm.size = Vector2(80, 80)
	zemin.mesh = pm
	var zm := StandardMaterial3D.new()
	zm.albedo_color = Color(0.46, 0.41, 0.31)
	zm.roughness = 1.0
	zemin.material_override = zm
	add_child(zemin)
	_siyah = StandardMaterial3D.new()
	_siyah.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	_siyah.albedo_color = Color.BLACK
	_siyah.cull_mode = BaseMaterial3D.CULL_DISABLED

func _takim(yol: String) -> Dictionary:
	return JSON.parse_string(FileAccess.get_file_as_string(yol))

func _poz(kok: Node3D) -> void:
	kok.rotation.y = PI   # yüzü -Z'deki kameraya
	var ap := D.animasyon_oynatici(kok)
	if ap and ap.has_animation(POZ_ADI):
		ap.play(POZ_ADI)
		ap.seek(POZ_ANI, true)
		ap.pause()

func _siluet(n: Node, ac: bool) -> void:
	for c in n.get_children():
		if c is MeshInstance3D:
			(c as MeshInstance3D).material_override = _siyah if ac else null
		_siluet(c, ac)

func _kaydet(yol: String, kok: Node3D) -> void:
	D.guncelle(kok)
	await RenderingServer.frame_post_draw
	D.guncelle(kok)
	await RenderingServer.frame_post_draw
	get_viewport().get_texture().get_image().save_png(yol)

func _orto(merkez: Vector3, boy: float, yon: Vector3) -> void:
	kamera.projection = Camera3D.PROJECTION_ORTHOGONAL
	kamera.size = boy
	kamera.position = merkez + yon * 20.0
	kamera.look_at(merkez, Vector3.UP)

func _perspektif(konum: Vector3, hedef: Vector3, fov: float) -> void:
	kamera.projection = Camera3D.PROJECTION_PERSPECTIVE
	kamera.fov = fov
	kamera.near = 0.05
	kamera.far = 400
	kamera.position = konum
	kamera.look_at(hedef, Vector3.UP)

func _tekli(cikti: String, yol: String) -> void:
	var t := _takim(yol)
	var kok := D.kur(t)
	add_child(kok)
	_poz(kok)
	var ad: String = t["ad"]
	var e := ortam.environment
	# ortografik görünümler (boy 2,4 m sabit: karakterler aynı ölçekte karşılaştırılır)
	zemin.visible = false
	var m := Vector3(0, 1.0, 0)
	e.background_color = Color(0.83, 0.83, 0.8)
	for g in [["on", Vector3(0, 0, -1)], ["yan", Vector3(1, 0, 0)], ["arka", Vector3(0, 0, 1)]]:
		_orto(m, 2.4, g[1])
		await _kaydet("%s/%s_%s.png" % [cikti, ad, g[0]], kok)
	e.background_color = Color.WHITE
	_siluet(kok, true)
	for g in [["siluet_on", Vector3(0, 0, -1)], ["siluet_yan", Vector3(1, 0, 0)]]:
		_orto(m, 2.4, g[1])
		await _kaydet("%s/%s_%s.png" % [cikti, ad, g[0]], kok)
	_siluet(kok, false)
	# yakın çekim (baş-omuz) ve orta mesafe (tam boy, zeminde)
	zemin.visible = true
	e.background_color = Color(0.66, 0.72, 0.78)
	_perspektif(Vector3(0.35, 1.62, -1.25), Vector3(0, 1.55, 0), 32)
	await _kaydet("%s/%s_yakin.png" % [cikti, ad], kok)
	_perspektif(Vector3(1.2, 1.3, -4.2), Vector3(0, 0.95, 0), 38)
	await _kaydet("%s/%s_orta.png" % [cikti, ad], kok)
	print("CEKILDI ", ad)
	kok.queue_free()
	await get_tree().process_frame

func _dizi(cikti: String, yollar: Array) -> void:
	var kokler := []
	var n := yollar.size()
	for i in n:
		var t := _takim(yollar[i])
		var kok := D.kur(t)
		add_child(kok)
		kok.position = Vector3(-(i - (n - 1) / 2.0) * 1.5, 0, 0)   # -Z kamerasından soldan sağa sıra
		_poz(kok)
		kokler.append(kok)
	var e := ortam.environment
	zemin.visible = true
	e.background_color = Color(0.66, 0.72, 0.78)
	var w := n * 1.5
	_perspektif(Vector3(0, 1.4, -w * 1.15 - 1.5), Vector3(0, 1.0, 0), 34)
	await _kaydet("%s/dizi_orta.png" % cikti, kokler[0])
	for k in kokler:
		D.guncelle(k)
	_perspektif(Vector3(0, 2.0, -38.0), Vector3(0, 1.0, 0), 34)
	await _kaydet("%s/dizi_uzak.png" % cikti, kokler[0])
	zemin.visible = false
	e.background_color = Color.WHITE
	for k in kokler:
		_siluet(k, true)
	_orto(Vector3(0, 1.0, 0), 2.6, Vector3(0, 0, -1))
	kamera.size = 2.6
	_perspektif(Vector3(0, 1.0, -60.0), Vector3(0, 1.0, 0), 2.6 * 57.3 / 60.0 * 1.0 + w * 0.9)
	_orto(Vector3(0, 1.0, 0), w * 0.6, Vector3(0, 0, -1))
	await _kaydet("%s/dizi_siluet.png" % cikti, kokler[0])
	print("DIZI ", n)
