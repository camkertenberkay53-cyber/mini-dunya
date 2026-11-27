extends SkeletonModifier3D
## Vücut ve yüz çeşitliliği (kendi yazımımız). Animasyon işlendikten SONRA her karede kemik pozlarına kişiye özgü
## ölçek ve küçük duruş farkı uygular. Giysi/zırh aynı iskelete bağlı olduğundan gövdeyle birlikte deforme olur
## (katman sırası korunur, taşma oluşmaz). Kemik uzunluk ekseni yerel +Y; X/Z kalınlıktır.
##  - taban: "süper kahraman" gövdesini dönemin sıradan insanına çeker (dar göğüs/omuz, ince kol/boyun).
##  - kişi: yapı (zayıf…iri), göbek, omuz genişliği, kol/bacak kalınlığı, boyun, baş boyutu/oranı, duruş (öne eğiklik).
## Belirlenimci: aynı tohum aynı kişiyi verir. Parametreler is.json "beden" (kurallar/gorsel.yaml karakter_kalite).

var olcekler := {}      # kemik indeksi -> Vector3 (yerel ölçek çarpanı)
var donmeler := {}      # kemik indeksi -> Quaternion (animasyon dönmesine eklenen küçük duruş farkı)

func _process_modification() -> void:
	var s := get_skeleton()
	if s == null:
		return
	for i in olcekler:
		s.set_bone_pose_scale(i, s.get_bone_pose_scale(i) * (olcekler[i] as Vector3))
	for i in donmeler:
		s.set_bone_pose_rotation(i, s.get_bone_pose_rotation(i) * (donmeler[i] as Quaternion))

static func _ar(r: RandomNumberGenerator, a: Array) -> float:
	return r.randf_range(float(a[0]), float(a[1]))

## Karakterin iskeletine değiştiriciyi ekler. k: {taban: {kemik: [x,y,z]}, kisi: {...aralıklar}}
static func kur(kok: Node, tohum: int, k: Dictionary) -> Node:
	var sk: Skeleton3D = null
	for n in kok.find_children("*", "Skeleton3D", true, false):
		sk = n
		break
	if sk == null or not k.get("acik", false):
		return null
	var b = load("res://sahneler/beden.gd").new()
	var r := RandomNumberGenerator.new()
	r.seed = tohum
	# Yerel ölçekler AÇIKÇA kurulur: eşit olmayan (X/Z) ölçek yalnız eksenleri hizalı zincirlerde (omurga içi, üst kol→ön kol,
	# uyluk→baldır, boyun→baş) kullanılır ve bir alt kemikte telafi edilir. Dallanma noktasında (göğüs→köprücük/boyun) yalnız
	# EŞİT ölçek vardır ve çocuklarda tam telafi edilir (eşit ölçek dönmeyle yer değiştirir; kollara/takılı kalkana sızmaz).
	var t: Dictionary = k.get("taban", {})
	var p: Dictionary = k.get("kisi", {})
	var yapi := _ar(r, p.get("yapi", [0.92, 1.06]))
	var gobek := maxf(0.0, _ar(r, p.get("gobek", [-0.6, 1.0]))) * float(p.get("gobek_guc", 0.14))
	var gogus := float(t.get("gogus", 0.94)) * yapi                       # göğüs kafesi (eşit)
	var bel_x := float(t.get("bel", 0.96)) * yapi + gobek * 0.5           # bel/göbek
	var bel_z := float(t.get("bel", 0.96)) * yapi + gobek
	var kol := float(t.get("kol", 0.9)) * _ar(r, p.get("kol", [0.92, 1.06])) * yapi
	var bacak := float(t.get("bacak", 0.97)) * _ar(r, p.get("bacak", [0.94, 1.06])) * sqrt(yapi)
	var boyun := float(t.get("boyun", 0.92)) * _ar(r, p.get("boyun", [0.92, 1.08])) * sqrt(yapi)
	var bas := _ar(r, p.get("bas", [0.95, 1.04]))
	var bas_en := _ar(r, p.get("bas_en", [0.96, 1.04]))
	var ol := {}
	var koy := func(ad: String, v: Vector3) -> void:
		var i := sk.find_bone(ad)
		if i >= 0 and not v.is_equal_approx(Vector3.ONE):
			ol[i] = v
	koy.call("spine_01", Vector3(bel_x, 1.0, bel_z))
	var g2 := (gogus + (bel_x + bel_z) * 0.5) * 0.5                       # bel ile göğüs arası geçiş
	koy.call("spine_02", Vector3(g2 / bel_x, 1.0, g2 / bel_z))
	koy.call("spine_03", Vector3(gogus / g2, gogus, gogus / g2))           # dünyada eşit: gogus
	for y in ["l", "r"]:
		koy.call("clavicle_" + y, Vector3.ONE / gogus)                      # kollar normal ölçeğe döner
		koy.call("upperarm_" + y, Vector3(kol, 1.0, kol))
		koy.call("lowerarm_" + y, Vector3(sqrt(kol) / kol, 1.0, sqrt(kol) / kol))
		koy.call("hand_" + y, Vector3(1.0 / sqrt(kol), 1.0, 1.0 / sqrt(kol)))   # el ve tutulan silah normal
		koy.call("thigh_" + y, Vector3(bacak, 1.0, bacak))
		koy.call("calf_" + y, Vector3(sqrt(bacak) / bacak, 1.0, sqrt(bacak) / bacak))
		koy.call("foot_" + y, Vector3(1.0 / sqrt(bacak), 1.0, 1.0 / sqrt(bacak)))
	koy.call("neck_01", Vector3(boyun / gogus, 1.0 / gogus, boyun / gogus))
	koy.call("Head", Vector3(bas * bas_en / boyun, bas, bas / boyun))     # dünyada: baş boyutu × en oranı (miğfer başa oturur)
	b.olcekler = ol
	var don := {}
	var egik := _ar(r, p.get("durus_derece", [-2.0, 6.0]))      # + öne eğik (yaş/yorgunluk), - dik
	var i3 := sk.find_bone("spine_03")
	if i3 >= 0:
		don[i3] = Quaternion(Vector3.RIGHT, deg_to_rad(egik))
	var ih := sk.find_bone("Head")
	if ih >= 0:   # baş: gövde eğikliğini kısmen dengeler + hafif yan eğim (kişisel duruş)
		don[ih] = Quaternion(Vector3.RIGHT, deg_to_rad(-egik * 0.6)) * Quaternion(Vector3.FORWARD, deg_to_rad(_ar(r, [-4.0, 4.0])))
	b.donmeler = don
	b.name = "Beden"
	sk.add_child(b)
	return b
