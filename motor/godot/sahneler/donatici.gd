extends RefCounted
## Takım donatıcısı: derlenmiş gövde GLB'sini yükler, yuvalarına (YUVA_*) ortak ekipman GLB'lerini takar.
## Ekipman bir kez yüklenir, her karakterde paylaşılır (önbellek). "sag_el_dik" yuvası eli izler ama dik durur.
## Test bayrakları (yalnızca negatif testler için): "kopuk" = ekipmanı yuvaya değil köke bağla (animasyonu izlemez),
## "ince_ayar" = ekipmanı yuva ekseninde kaydır (gömülme testi).

const DIK := "sag_el_dik"
static var _sablon := {}

static func glb_yukle(yol: String) -> Node3D:
	var doc := GLTFDocument.new()
	var st := GLTFState.new()
	if doc.append_from_file(yol, st) != OK:
		push_error("yüklenemedi: " + yol)
		return null
	return doc.generate_scene(st)

static func ekipman(yol: String) -> Node3D:
	if not _sablon.has(yol):
		var n := glb_yukle(yol)
		var ps := PackedScene.new()
		_sahipleri_ayarla(n, n)
		ps.pack(n)
		_sablon[yol] = ps
		n.free()
	return _sablon[yol].instantiate()

static func _sahipleri_ayarla(n: Node, kok: Node) -> void:
	for c in n.get_children():
		c.owner = kok
		_sahipleri_ayarla(c, kok)

static func yuvalar(kok: Node) -> Dictionary:
	var s := {}
	var liste: Array[Node] = [kok]
	while liste.size() > 0:
		var x: Node = liste.pop_back()
		liste.append_array(x.get_children())
		if String(x.name).begins_with("YUVA_"):
			s[String(x.name).substr(5)] = x
	return s

static func kur(takim: Dictionary) -> Node3D:
	var kok := glb_yukle(takim["glb"])
	kok.name = takim.get("ad", "karakter")
	var y := yuvalar(kok)
	var ekler := []
	for t in takim["takilanlar"]:
		var ad: String = "sag_el" if t["yuva"] == DIK else t["yuva"]
		if not y.has(ad):
			push_error("yuva yok: " + ad)
			continue
		var e := ekipman(t["glb"])
		e.name = "EK_" + t["id"]
		e.set_meta("yuva", t["yuva"])
		e.set_meta("yuva_dugumu", y[ad])
		e.set_meta("dik", t["yuva"] == DIK)
		if t.get("kopuk", false):
			kok.add_child(e)
			e.set_meta("kopuk", true)
		else:
			y[ad].add_child(e)
		if t.has("ince_ayar"):
			var k: Array = t["ince_ayar"]
			e.position += Vector3(k[0], k[1], k[2])
		ekler.append(e)
	kok.set_meta("ekler", ekler)
	kok.set_meta("yuvalar", y)
	return kok

## Her karede çağrılır: dik taşınan ekipmanı dikleştirir; "kopuk" test ekipmanını yuvanın İLK konumunda bırakır.
static func guncelle(kok: Node3D) -> void:
	for e in kok.get_meta("ekler", []):
		var en := e as Node3D
		if en.get_meta("kopuk", false):
			if not en.has_meta("sabit"):
				en.global_transform = (en.get_meta("yuva_dugumu") as Node3D).global_transform
				en.set_meta("sabit", true)
			continue
		if en.get_meta("dik", false):
			en.global_basis = kok.global_basis * Basis(Vector3.UP, PI)

## Faz 5.5: ek animasyon kütüphanesi (aynı evrensel iskelet). Kütüphane glb'si bir kez okunur; iz yolları bu karakterin
## iskelet yoluna çevrilir ve AnimationPlayer'a "<ad>" kütüphanesi olarak eklenir ("ad/Animasyon" ile oynatılır).
static var _ek_kutuphane := {}

static func ek_kutuphane_ekle(kok: Node, ap: AnimationPlayer, ad: String, yol: String) -> void:
	if ap.has_animation_library(ad):
		return
	if not _ek_kutuphane.has(yol):
		var n := glb_yukle(yol)
		var kap: AnimationPlayer = animasyon_oynatici(n)
		var ham := {}
		if kap:
			for a in kap.get_animation_list():
				ham[a] = kap.get_animation(a).duplicate(true)
		n.free()
		_ek_kutuphane[yol] = ham
	var sk := iskelet(kok)
	var kok_ap: Node = ap.get_node(ap.root_node)
	var sk_yol := str(kok_ap.get_path_to(sk))
	var lib := AnimationLibrary.new()
	var ham: Dictionary = _ek_kutuphane[yol]
	for a in ham:
		var an: Animation = ham[a].duplicate(true)
		for i in an.get_track_count():
			var p := an.track_get_path(i)
			if p.get_subname_count() > 0:
				an.track_set_path(i, NodePath(sk_yol + ":" + p.get_concatenated_subnames()))
				# kök hareketi yerinde tutulur (planlayıcı yerinde animasyonu sabit konumda varsayar): root x/z ilk karede
				if p.get_concatenated_subnames() == "root" and an.track_get_type(i) == Animation.TYPE_POSITION_3D and an.track_get_key_count(i) > 0:
					var ilk: Vector3 = an.track_get_key_value(i, 0)
					for kk in an.track_get_key_count(i):
						var v: Vector3 = an.track_get_key_value(i, kk)
						an.track_set_key_value(i, kk, Vector3(ilk.x, v.y, ilk.z))
		lib.add_animation(a, an)
	ap.add_animation_library(ad, lib)

static func animasyon_oynatici(n: Node) -> AnimationPlayer:
	if n is AnimationPlayer:
		return n
	for c in n.get_children():
		var r := animasyon_oynatici(c)
		if r:
			return r
	return null

static func iskelet(n: Node) -> Skeleton3D:
	if n is Skeleton3D:
		return n
	for c in n.get_children():
		var r := iskelet(c)
		if r:
			return r
	return null
