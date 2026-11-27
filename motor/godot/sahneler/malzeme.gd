extends RefCounted
## Mekân kalite paketi — malzeme yükseltme. Stilize çevre parçalarının düz renkli malzemelerini ADINA göre gerçek PBR
## dokularla (Poly Haven CC0: albedo, normal, AO/pürüz/metal paketi) değiştirir. Dünya-uzayı üç yönlü (triplanar)
## eşleme: UV'siz/atlas modellerde de doku esnemez, modüller arasında dikiş olmaz. Kurallar is.json "malzeme".
## Kendi yazımımız. Malzeme ve dokular bir kez yüklenir, bütün kopyalarda paylaşılır.

static var _kurallar: Array = []
static var _onbellek := {}    # kural sırası → StandardMaterial3D
static var _dokular := {}     # yol → ImageTexture

static func kur(m: Dictionary) -> void:
	_kurallar = []
	if not m.get("acik", false):
		return
	for k in m.get("kurallar", []):
		var r := RegEx.new()
		r.compile(str(k["desen"]))
		_kurallar.append([r, k])

static func _doku(yol: String) -> ImageTexture:
	if not _dokular.has(yol):
		var img := Image.load_from_file(yol)
		img.generate_mipmaps()
		_dokular[yol] = ImageTexture.create_from_image(img)
	return _dokular[yol]

static func _malzeme(i: int) -> StandardMaterial3D:
	if not _onbellek.has(i):
		var k: Dictionary = _kurallar[i][1]
		var m := StandardMaterial3D.new()
		m.albedo_texture = _doku(k["diff"])
		var rk: Array = k.get("renk", [1.0, 1.0, 1.0])
		m.albedo_color = Color(rk[0], rk[1], rk[2])
		m.normal_enabled = true
		m.normal_texture = _doku(k["nor"])
		m.normal_scale = float(k.get("normal_guc", 1.0))
		var arm := _doku(k["arm"])   # R: ortam kapanması, G: pürüzlülük, B: metallik
		m.ao_enabled = true
		m.ao_texture = arm
		m.ao_texture_channel = BaseMaterial3D.TEXTURE_CHANNEL_RED
		m.roughness = 1.0
		m.roughness_texture = arm
		m.roughness_texture_channel = BaseMaterial3D.TEXTURE_CHANNEL_GREEN
		m.metallic = 0.0
		m.uv1_triplanar = true
		m.uv1_world_triplanar = true
		m.uv1_triplanar_sharpness = 4.0
		m.uv1_scale = Vector3.ONE / max(0.1, float(k.get("tekrar_m", 2.0)))
		m.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS_ANISOTROPIC
		_onbellek[i] = m
	return _onbellek[i]

static func _eslesen(ad: String) -> int:
	for i in _kurallar.size():
		if (_kurallar[i][0] as RegEx).search(ad) != null:
			return i
	return -1

## Düğüm ağacındaki her yüzeyi tarar; adı bir kurala uyan malzemeyi PBR karşılığıyla değiştirir. Değişen yüzey sayısı.
static func uygula(n: Node) -> int:
	if _kurallar.is_empty() or n == null:
		return 0
	var sayi := 0
	var liste: Array[Node] = [n]
	while liste.size() > 0:
		var x: Node = liste.pop_back()
		liste.append_array(x.get_children())
		if x is MeshInstance3D and (x as MeshInstance3D).mesh != null:
			var mi := x as MeshInstance3D
			for s in mi.mesh.get_surface_count():
				var mat := mi.get_active_material(s)
				if mat == null:
					continue
				var i := _eslesen(mat.resource_name)
				if i >= 0:
					mi.set_surface_override_material(s, _malzeme(i))
					sayi += 1
	return sayi

## Gerçekçi (fotogrametrik/PBR) varlıkların kendi malzemesi korunur; yalnız aynasal yansıma gücü sahne ışığına
## göre kısılır (açık gökyüzü ışığının yukarı bakan pürüzlü taşta "ıslak/mavi" görünmesini önler). Paylaşılan kopya.
static var _kisilmis := {}
static func gercek(n: Node, spekuler: float) -> void:
	var liste: Array[Node] = [n]
	while liste.size() > 0:
		var x: Node = liste.pop_back()
		liste.append_array(x.get_children())
		if x is MeshInstance3D and (x as MeshInstance3D).mesh != null:
			var mi := x as MeshInstance3D
			for s in mi.mesh.get_surface_count():
				var mat := mi.get_active_material(s)
				if mat is BaseMaterial3D:
					if not _kisilmis.has(mat):
						var y := (mat as BaseMaterial3D).duplicate() as BaseMaterial3D
						y.metallic_specular = spekuler
						y.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS_ANISOTROPIC
						_kisilmis[mat] = y
					mi.set_surface_override_material(s, _kisilmis[mat])

static func gercek_mm(mi: MultiMeshInstance3D, spekuler: float) -> void:   # MultiMesh: ağın yüzey malzemeleri
	var m := mi.multimesh.mesh
	for s in m.get_surface_count():
		var mat := m.surface_get_material(s)
		if mat is BaseMaterial3D:
			if not _kisilmis.has(mat):
				var y := (mat as BaseMaterial3D).duplicate() as BaseMaterial3D
				y.metallic_specular = spekuler
				y.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS_ANISOTROPIC
				_kisilmis[mat] = y
			mi.material_override = null
			m.surface_set_material(s, _kisilmis[mat])
