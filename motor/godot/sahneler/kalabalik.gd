extends RefCounted
## Sinematik paket 2 — arka plan ordusu (kalabalık). Yöntem: Godot belgelerindeki "binlerce nesneyi MultiMesh ile
## çizme" tekniği (docs.godotengine.org, animating_thousands_of_fish; MIT) — iskeletli karakter her takım için BİR kez
## kurulur, bekleme pozunda iskelet pozu statik ağa pişirilir (bake_mesh_from_current_skeleton_pose), sonra yüzlerce
## kopya MultiMeshInstance3D ile çizilir. Uzak planda (≥ 25 m) ordunun büyüklüğünü verir; yakın oyuncular yine tam
## animasyonlu kalır. Dizilim: bloklar halinde saflar, küçük tohumlu sapma (konum, yön, boy, poz anı).
const D := preload("res://sahneler/donatici.gd")
const V := preload("res://sahneler/vfx.gd")

## Uzak kalabalık için ağı sadeleştir: Godot'nun kendi LOD üreticisi (meshoptimizer, MIT; ImporterMesh.generate_lods)
## ile üretilen ayrıntı düzeylerinden hedef orana en yakın olanın indeksleri alınır. Geometri kaynağı aynı ağdır.
static func _sadelestir(m: Mesh, oran: float) -> Mesh:
	var im := ImporterMesh.new()
	for i in m.get_surface_count():
		im.add_surface(m.surface_get_primitive_type(i), m.surface_get_arrays(i), [], {}, m.surface_get_material(i))
	im.generate_lods(25.0, 60.0, [])
	var cikis := ArrayMesh.new()
	for i in im.get_surface_count():
		var dizi := im.get_surface_arrays(i)
		var asil: PackedInt32Array = dizi[Mesh.ARRAY_INDEX] if dizi[Mesh.ARRAY_INDEX] != null else PackedInt32Array()
		var hedef := int(asil.size() * oran)
		for j in im.get_surface_lod_count(i):
			var lod := im.get_surface_lod_indices(i, j)
			if lod.size() >= hedef and lod.size() >= 3:
				dizi[Mesh.ARRAY_INDEX] = lod
		cikis.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, dizi)
		cikis.surface_set_material(i, im.get_surface_material(i))
	return cikis

static func _pisir(sahne: Node3D, takim: Dictionary, anim: String, an: float, cesit: Dictionary, tohum: int, cesit_oran: float = 1.0) -> Array:
	var kok := D.kur(takim)
	var kap := Node3D.new()
	kap.add_child(kok)
	sahne.add_child(kap)   # AnimationPlayer ve iskelet pozu ağaçta güncellenir
	if cesit.get("acik", false):
		D.cesitle(kok, tohum, cesit)
	var ap := D.animasyon_oynatici(kok)
	var sk := D.iskelet(kok)
	if ap and sk and ap.has_animation(anim):   # pozu animasyondan DOĞRUDAN örnekle (AnimationPlayer işlemesini beklemeden)
		var a := ap.get_animation(anim)
		an = fmod(an, maxf(a.length, 0.001))
		for i in a.get_track_count():
			var kemik := sk.find_bone(a.track_get_path(i).get_concatenated_subnames())
			if kemik < 0:
				continue
			match a.track_get_type(i):
				Animation.TYPE_POSITION_3D:
					sk.set_bone_pose_position(kemik, a.position_track_interpolate(i, an))
				Animation.TYPE_ROTATION_3D:
					sk.set_bone_pose_rotation(kemik, a.rotation_track_interpolate(i, an))
				Animation.TYPE_SCALE_3D:
					sk.set_bone_pose_scale(kemik, a.scale_track_interpolate(i, an))
		sk.force_update_all_bone_transforms()
		sk.notification(Skeleton3D.NOTIFICATION_UPDATE_SKELETON)   # pozu RenderingServer iskeletine hemen yaz (pişirme oradan okur)
	D.guncelle(kok)
	var parcalar: Array = []
	var kok_ters := kok.global_transform.affine_inverse()
	for m in kok.find_children("*", "MeshInstance3D", true, false):
		var mi: MeshInstance3D = m
		if mi.mesh == null or str(mi.name).begins_with("Face"):   # göz/kaş: uzakta görünmez
			continue
		var mesh: Mesh = mi.mesh
		if mi.skin != null or mi.get_skeleton_path() != NodePath(""):
			var pis := mi.bake_mesh_from_current_skeleton_pose()
			if pis:
				mesh = pis
		for i in mi.mesh.get_surface_count():
			var mat := mi.get_active_material(i)
			if mat and i < mesh.get_surface_count():
				mesh.surface_set_material(i, mat)
		if float(cesit_oran) < 1.0:
			mesh = _sadelestir(mesh, float(cesit_oran))
		parcalar.append([mesh, kok_ters * mi.global_transform])
	sahne.remove_child(kap)
	kap.free()
	return parcalar

static func kur(sahne: Node3D, k: Dictionary, takimlar: Dictionary, ar: Dictionary, merkez: Vector3, ileri: Vector3,
		tohum: int) -> int:
	if not sahne.is_inside_tree():
		return 0
	var r := RandomNumberGenerator.new()
	r.seed = tohum
	var adlar: Array = k["takimlar"]
	var turler: Array = []
	var gercekci: bool = k.get("gercekci", false)
	var cesit_say := int(k.get("poz_cesidi", 2)) * (int(k.get("kisi_carpani", 2)) if gercekci else 1)
	for i in adlar.size() * cesit_say:   # her takımdan birkaç farklı poz anı (eşzamanlı robot görünmesin)
		var tk: Dictionary = takimlar[adlar[i % adlar.size()]]
		var ks: Array = tk.get("kisiler", [])
		if gercekci and ks.size() > 0:   # gerçekçi insanlar: her pişirilmiş tür başka bir kişi (yüz, beden, sakal)
			tk = tk.duplicate()
			tk["glb"] = ks[(i / adlar.size()) % ks.size()]
		turler.append(_pisir(sahne, tk, k.get("animasyon", "Idle_Loop"), r.randf_range(0.0, 3.0),
			k.get("cesit", {}), tohum + i * 7, float(k.get("sadelestir_oran", 1.0))))
	var yan := ileri.cross(Vector3.UP).normalized()
	var konumlar: Array = []
	for t in turler.size():
		konumlar.append([])
	var blok_sayi := int(k.get("blok", 3))
	var her_blok := int(ceil(float(k.get("adet", 150)) / blok_sayi))
	var mes: Array = k.get("mesafe_m", [30.0, 70.0])
	for b in blok_sayi:
		var d := lerpf(float(mes[0]), float(mes[1]), (b + 0.5) / blok_sayi) + r.randf_range(-4.0, 4.0)
		var yan_kay := r.randf_range(-1.0, 1.0) * float(k.get("yan_oran", 0.35)) * d
		var bas := merkez + ileri * d + yan * yan_kay
		var genislik := int(k.get("saf_genislik", 14))
		var yon := atan2(-ileri.x, -ileri.z) + float(k.get("yon_sapma", 0.0))   # saflar kameraya/sahneye dönük
		for i in her_blok:
			var sira := i / genislik
			var sut := i % genislik
			var p := bas + yan * ((sut - (genislik - 1) * 0.5) * float(k.get("yan_aralik_m", 1.25)) + r.randf_range(-0.18, 0.18)) \
				+ ileri * (sira * float(k.get("sira_aralik_m", 1.6)) + r.randf_range(-0.2, 0.2))
			p.y = V.zemin_y(p.x, p.z, ar)
			var bz := Basis(Vector3.UP, yon + deg_to_rad(r.randf_range(-7.0, 7.0))).scaled(Vector3.ONE * r.randf_range(0.95, 1.05) * float(k.get("boy_orani", 1.0)))   # dönemin insan boyu
			konumlar[r.randi() % turler.size()].append(Transform3D(bz, p))
	var n := 0
	for t in turler.size():
		for pr in turler[t]:
			var mm := MultiMesh.new()
			mm.transform_format = MultiMesh.TRANSFORM_3D
			mm.mesh = pr[0]
			mm.instance_count = konumlar[t].size()
			for i in konumlar[t].size():
				mm.set_instance_transform(i, konumlar[t][i] * (pr[1] as Transform3D))
			var mi := MultiMeshInstance3D.new()
			mi.multimesh = mm
			mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_ON if k.get("golge", false) else GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
			sahne.add_child(mi)
		n += konumlar[t].size()
	return n
