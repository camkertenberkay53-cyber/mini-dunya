extends SkeletonModifier3D
## Sinematik paket: binici oturuşu. Oturma animasyonundaki (Driving_Loop) uyluklar at gövdesine girmesin diye
## animasyondan SONRA uyluk kemiklerini iskelet uzayında aşağı (pitch) ve dışa (splay) çevirir; diz/ayak alt kemikler
## olduğu için birlikte gelir. Animasyon dosyası değişmez.
var asagi_derece := 40.0
var disa_derece := 24.0
var _sol := -1
var _sag := -1

func _process_modification_with_delta(_delta: float) -> void:
	var sk := get_skeleton()
	if sk == null:
		return
	if _sol < 0:
		_sol = sk.find_bone("thigh_l")
		_sag = sk.find_bone("thigh_r")
	for i in [_sol, _sag]:
		if i < 0:
			continue
		var isaret := 1.0 if i == _sol else -1.0
		var g := sk.get_bone_global_pose(i)
		var don := Basis(Vector3.UP, deg_to_rad(disa_derece) * isaret) * Basis(Vector3.RIGHT, deg_to_rad(asagi_derece))
		g.basis = don * g.basis
		sk.set_bone_global_pose(i, g)
