extends RefCounted
## Sinematik paket 2 — prosedürel serpme (ağaç, kaya...). Yöntem ProtonScatter (MIT, HungryProton) ve Bridson'un
## Poisson-disk örneklemesindeki "en az aralıklı rastgele nokta" fikrinin sade, kendi yazımımız uyarlamasıdır (kod
## kopyalanmadı). Her model bir kez yüklenir ve MultiMeshInstance3D ile çoğaltılır (çizim çağrısı az).
## Kurallar (konudan bağımsız): oyuncuların durduğu düz şerit ve kamera→hedef görüş çizgisi boş kalır; nesneler
## zeminin yüksekliğine (ortam.gd ZEMIN_SHADER'ın CPU kopyası, vfx.gd) oturur. Tohumlu: aynı plan → aynı orman.
const V := preload("res://sahneler/vfx.gd")
const D := preload("res://sahneler/donatici.gd")

static func _gorus_uzakligi(p: Vector3, kameralar: Array) -> float:
	var en := 1e9
	for k in kameralar:
		var a: Vector3 = k[0]
		var b: Vector3 = k[1]
		a.y = 0
		b.y = 0
		var q := Vector3(p.x, 0, p.z)
		var ab := b - a
		var u := clampf((q - a).dot(ab) / maxf(ab.length_squared(), 1e-6), 0.0, 1.0)
		en = minf(en, q.distance_to(a + ab * u))
	return en

static func serp(kok: Node3D, k: Dictionary, ar: Dictionary, merkez: Vector2, kameralar: Array, tohum: int) -> int:
	var r := RandomNumberGenerator.new()
	r.seed = tohum
	var yol_x := float(ar.get("yol_x", 0.0))
	var bos := float(ar.get("duz_yari", 6.0)) + float(k.get("serit_payi_m", 2.0))
	var gorus := float(k.get("gorus_payi_m", 4.0))
	var noktalar: Array = []
	var toplam := 0
	for kat in k.get("katmanlar", []):
		var sahne := D.ekipman(kat["glb"])   # önbellekli örnek: yalnız ağ ve malzeme okunur
		var parcalar: Array = []
		for m in sahne.find_children("*", "MeshInstance3D", true, false):
			parcalar.append([(m as MeshInstance3D).mesh, (m as Node3D).transform])
		var yer: Array = []
		var aralik := float(kat.get("en_az_aralik_m", 6.0))
		var yr: Array = kat.get("yaricap_m", [15.0, 120.0])
		var ol: Array = kat.get("olcek", [0.8, 1.2])
		for deneme in int(kat.get("adet", 20)) * 12:
			if yer.size() >= int(kat.get("adet", 20)):
				break
			var aci := r.randf() * TAU
			var d := sqrt(r.randf_range(float(yr[0]) ** 2, float(yr[1]) ** 2))   # alanca eşit dağılım
			var p := Vector3(merkez.x + cos(aci) * d, 0, merkez.y + sin(aci) * d)
			if absf(p.x - yol_x) < bos or _gorus_uzakligi(p, kameralar) < gorus:
				continue
			var iyi := true
			for q in noktalar:
				if p.distance_to(q[0]) < maxf(aralik, float(q[1])):
					iyi = false
					break
			if not iyi:
				continue
			if V.su_k(p.x, p.z, ar) > 0.02:   # suya ve kumsala ağaç/kaya dikilmez
				continue
			p.y = V.zemin_y(p.x, p.z, ar) - float(kat.get("gomme_m", 0.15))
			var t := Transform3D(Basis(Vector3.UP, r.randf() * TAU).scaled(Vector3.ONE * r.randf_range(float(ol[0]), float(ol[1]))), p)
			yer.append(t)
			noktalar.append([p, aralik])
		for pr in parcalar:
			var mm := MultiMesh.new()
			mm.transform_format = MultiMesh.TRANSFORM_3D
			mm.mesh = pr[0]
			mm.instance_count = yer.size()
			for i in yer.size():
				mm.set_instance_transform(i, yer[i] * (pr[1] as Transform3D))
			var mi := MultiMeshInstance3D.new()
			mi.multimesh = mm
			if kat.has("kaya_doku"):   # dokusuz kaya kütlesine üç yönlü (triplanar) gerçek kaya dokusu (Poly Haven CC0)
				var km := StandardMaterial3D.new()
				var img := Image.load_from_file(kat["kaya_doku"])
				img.generate_mipmaps()
				km.albedo_texture = ImageTexture.create_from_image(img)
				km.uv1_triplanar = true
				km.uv1_world_triplanar = true
				km.uv1_scale = Vector3.ONE * float(kat.get("kaya_olcek", 0.18))
				var kr: Array = kat.get("kaya_renk", [0.72, 0.70, 0.66])
				km.albedo_color = Color(kr[0], kr[1], kr[2])
				km.roughness = 0.95
				mi.material_override = km
			mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_ON if kat.get("golge", true) else GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
			kok.add_child(mi)
		sahne.free()
		toplam += yer.size()
	return toplam
