extends Node3D
## Varlık denetimi: her GLB'yi çalışma anında yükler, 3 açıdan ışıklı ve siluet görüntü kaydeder.
## godot --path motor/godot -- <cikti_klasoru> <a.glb> [b.glb ...]
## Kamera ortografik ve modelin boyuna göre ölçeklenir: siluetler boydan bağımsız karşılaştırılabilir.

const ACILAR := [0.0, 90.0, 180.0]
const POZ_ANI := 0.35
var kamera: Camera3D
var isik: DirectionalLight3D
var ortam: WorldEnvironment

func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() < 2:
		push_error("kullanim: -- <cikti> <glb...>")
		get_tree().quit(2)
		return
	get_window().size = Vector2i(400, 800)   # proje 1080x1920 (render); denetim küçük çeker
	var cikti: String = args[0]
	DirAccess.make_dir_recursive_absolute(cikti)
	kamera = Camera3D.new()
	kamera.projection = Camera3D.PROJECTION_ORTHOGONAL
	add_child(kamera)
	isik = DirectionalLight3D.new()
	isik.rotation_degrees = Vector3(-40, 35, 0)
	isik.light_energy = 1.3
	add_child(isik)
	ortam = WorldEnvironment.new()
	ortam.environment = Environment.new()
	ortam.environment.background_mode = Environment.BG_COLOR
	ortam.environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	ortam.environment.ambient_light_color = Color(0.75, 0.75, 0.78)
	ortam.environment.ambient_light_energy = 0.8
	add_child(ortam)
	for i in range(1, args.size()):
		await _denetle(args[i], cikti)
	get_tree().quit(0)

func _denetle(yol: String, cikti: String) -> void:
	var doc := GLTFDocument.new()
	var st := GLTFState.new()
	if doc.append_from_file(yol, st) != OK:
		print("YUKLENEMEDI ", yol)
		return
	var kok: Node3D = doc.generate_scene(st)
	add_child(kok)
	var ap := _bul_ap(kok)
	if ap:
		var ad := "Idle_Loop" if ap.has_animation("Idle_Loop") else ""
		if ad == "" and ap.get_animation_list().size() > 0:
			for a in ap.get_animation_list():
				if "idle" in a.to_lower():
					ad = a
					break
		if ad != "":
			ap.play(ad)
			ap.seek(POZ_ANI, true)
			ap.pause()
	await RenderingServer.frame_post_draw
	var kutu := _kutu(kok)
	var merkez := kutu.get_center()
	var boy := kutu.size.y
	kamera.size = boy * 1.08
	var ad_kok := yol.get_file().get_basename()
	for ac in ACILAR:
		var r := deg_to_rad(ac)
		kamera.position = merkez + Vector3(sin(r), 0, cos(r)) * (boy * 3.0 + 2.0)
		kamera.look_at(merkez, Vector3.UP)
		_siluet(kok, false)
		ortam.environment.background_color = Color(0.82, 0.82, 0.8)
		await _kaydet("%s/%s_isik_%d.png" % [cikti, ad_kok, int(ac)])
		_siluet(kok, true)
		ortam.environment.background_color = Color.WHITE
		await _kaydet("%s/%s_siluet_%d.png" % [cikti, ad_kok, int(ac)])
	_siluet(kok, false)
	print("DENETLENDI ", ad_kok, " boy=", boy)
	kok.queue_free()
	await get_tree().process_frame

func _kaydet(yol: String) -> void:
	await RenderingServer.frame_post_draw
	await RenderingServer.frame_post_draw
	get_viewport().get_texture().get_image().save_png(yol)

var _siyah: StandardMaterial3D
func _siluet(n: Node, ac: bool) -> void:
	if _siyah == null:
		_siyah = StandardMaterial3D.new()
		_siyah.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
		_siyah.albedo_color = Color.BLACK
		_siyah.cull_mode = BaseMaterial3D.CULL_DISABLED
	for c in n.get_children():
		if c is MeshInstance3D:
			(c as MeshInstance3D).material_override = _siyah if ac else null
		_siluet(c, ac)

func _bul_ap(n: Node) -> AnimationPlayer:
	if n is AnimationPlayer:
		return n
	for c in n.get_children():
		var r := _bul_ap(c)
		if r:
			return r
	return null

func _kutu(n: Node) -> AABB:
	var sonuc := AABB()
	var ilk := true
	var liste: Array[Node] = [n]
	while liste.size() > 0:
		var x: Node = liste.pop_back()
		liste.append_array(x.get_children())
		if x is MeshInstance3D:
			var m := x as MeshInstance3D
			var b := m.global_transform * m.get_aabb()
			if ilk:
				sonuc = b
				ilk = false
			else:
				sonuc = sonuc.merge(b)
	return sonuc
