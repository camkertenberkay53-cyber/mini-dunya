extends Node3D
## Veri güdümlü çekim sahnesi (Faz 4, M11): tek bir çekimi is.json'dan kurar ve oynatır. Konuya özel kod yoktur.
## godot --path motor/godot res://sahneler/cekim.tscn --write-movie x.avi --fixed-fps 30 --quit-after N -- <is.json> [önizleme_anı_sn]
## is.json motor/uretim/render.py tarafından denetlenmiş çekim planından üretilir (hazır ayarlar çözülmüş olarak).
##
## Koordinatlar: plan [x, z] = Godot (x, 0, z). yon_derece 0 = +Z'ye bakar (karakter modelinin ön yönü).
## Yer değiştiren animasyonlarda karakter, planın verdiği (ölçülmüş zemin hızına eşit) hızla ilerletilir.

const D := preload("res://sahneler/donatici.gd")
const O := preload("res://sahneler/ortam.gd")

var is_: Dictionary
var t := 0.0
var kamera: Camera3D
var oyuncular: Array = []     # [{kok, bas, ileri, hiz}]
var kam: Dictionary

func _ready() -> void:
	var a := OS.get_cmdline_user_args()
	is_ = JSON.parse_string(FileAccess.get_file_as_string(a[0]))
	if a.size() > 1:
		t = float(a[1])   # önizleme: çekimin belirli bir anından başla (render'da kullanılmaz)
	var c: Dictionary = is_["cekim"]
	var rng := RandomNumberGenerator.new()
	rng.seed = int(is_.get("tohum", 1))
	O.isik(self, is_["isik"])
	var m: Array = is_["sahne_merkezi"]
	O.arazi(self, is_["arazi"], Vector2(m[0], m[1]))
	O.daglar(self, is_["arazi"], rng, Vector2(m[0], m[1]), deg_to_rad(float(is_["bakis_yonu_derece"])))
	O.otlar(self, is_["arazi"], rng, is_["ot_alani"])
	for cv in is_.get("cevre", []):
		var n := D.glb_yukle(cv["glb"])
		n.position = Vector3(cv["konum"][0], 0, cv["konum"][1])
		n.rotation.y = deg_to_rad(float(cv.get("yon_derece", 0.0)))
		n.scale = Vector3.ONE * float(cv.get("olcek", 1.0))
		add_child(n)
	for k in c.get("karakterler", []):
		var takim: Dictionary = is_["takimlar"][k["takim"]]
		var kok := D.kur(takim)
		add_child(kok)
		var yon := deg_to_rad(float(k.get("yon_derece", 0.0)))
		kok.rotation.y = yon
		kok.scale = Vector3.ONE * float(k.get("olcek", 1.0))
		var bas := Vector3(k["konum"][0], 0, k["konum"][1])
		kok.position = bas
		var ap := D.animasyon_oynatici(kok)
		var anim: String = k["animasyon"]
		if ap == null or not ap.has_animation(anim):
			push_error("animasyon yok: " + anim)
			get_tree().quit(3)
			return
		var an := ap.get_animation(anim)
		an.loop_mode = Animation.LOOP_LINEAR if is_["dongu"].get(anim, true) else Animation.LOOP_NONE
		ap.play(anim)
		var gecikme := float(k.get("gecikme_sn", 0.0))
		ap.seek(float(k.get("faz_sn", 0.0)) + maxf(0.0, t - gecikme), true)
		if gecikme > t:
			ap.pause()   # tek seferlik animasyon gecikme anına kadar ilk karesinde bekler
		oyuncular.append({"kok": kok, "bas": bas, "ileri": Vector3(sin(yon), 0, cos(yon)), "hiz": float(k.get("hiz_m_sn", 0.0)),
			"ap": ap, "gecikme": gecikme, "basladi": gecikme <= t})
	kam = c["kamera"]
	kamera = Camera3D.new()
	kamera.near = 0.1
	kamera.far = 800.0
	add_child(kamera)
	_guncelle()

func _kolay(u: float, tip: String) -> float:
	match tip:
		"giris": return u * u
		"cikis": return 1.0 - (1.0 - u) * (1.0 - u)
		"giris_cikis": return u * u * (3.0 - 2.0 * u)
	return u

func _vec(a: Array) -> Vector3:
	return Vector3(a[0], a[1], a[2])

func _guncelle() -> void:
	var sure: float = is_["cekim"]["sure_sn"]
	for o in oyuncular:
		(o["kok"] as Node3D).position = o["bas"] + o["ileri"] * o["hiz"] * t
		var ap: AnimationPlayer = o["ap"]
		if not o["basladi"] and t >= o["gecikme"]:
			ap.play()
			o["basladi"] = true
		D.guncelle(o["kok"])
	var u := _kolay(clampf(t / sure, 0.0, 1.0), kam.get("yumusatma", "giris_cikis"))
	var b: Dictionary = kam["bas"]
	var s: Dictionary = kam["son"]
	kamera.fov = lerpf(b["fov"], s["fov"], u)
	kamera.position = _vec(b["konum"]).lerp(_vec(s["konum"]), u)
	kamera.look_at(_vec(b["hedef"]).lerp(_vec(s["hedef"]), u), Vector3.UP)

func _process(delta: float) -> void:
	_guncelle()   # kare n, t = n / fps anını gösterir
	t += delta
