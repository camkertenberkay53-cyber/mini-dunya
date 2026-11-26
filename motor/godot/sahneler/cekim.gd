extends Node3D
## Veri güdümlü çekim sahnesi (Faz 4, M11): tek bir çekimi is.json'dan kurar ve oynatır. Konuya özel kod yoktur.
## godot --path motor/godot res://sahneler/cekim.tscn --write-movie x.avi --fixed-fps 30 --quit-after N -- <is.json> [önizleme_anı_sn]
## is.json motor/uretim/render.py tarafından denetlenmiş çekim planından üretilir (hazır ayarlar çözülmüş olarak).
##
## Koordinatlar: plan [x, z] = Godot (x, 0, z). yon_derece 0 = +Z'ye bakar (karakter modelinin ön yönü).
## Yer değiştiren animasyonlarda karakter, planın verdiği (ölçülmüş zemin hızına eşit) hızla ilerletilir.

const D := preload("res://sahneler/donatici.gd")
const O := preload("res://sahneler/ortam.gd")
const V := preload("res://sahneler/vfx.gd")
const S := preload("res://sahneler/sinema.gd")
const Serp := preload("res://sahneler/serpme.gd")
const Y := preload("res://sahneler/yerlesim.gd")
const Mz := preload("res://sahneler/malzeme.gd")
const F := preload("res://sahneler/film.gd")
const Yz := preload("res://sahneler/yuzey.gd")
const Bd := preload("res://sahneler/beden.gd")
var _film: ShaderMaterial = null
const K := preload("res://sahneler/kalabalik.gd")
var _sinema: ShaderMaterial

var is_: Dictionary
var t := 0.0
var kamera: Camera3D
var oyuncular: Array = []     # [{kok, bas, ileri, hiz}]
var kam: Dictionary
var _sira := 0
var _kisi_sayac := {}   # takım → bu çekimde kaçıncı örnek (gerçekçi kişi seçimi)
var _toplar: Array = []
var _oklar: Array = []      # ok yağmuru (vfx.ok_yagmuru)
var _ates: Array = []       # yangın ışıkları (titreşim)
var _kivilcim: Array = []   # düello kıvılcımları

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
	O.su(self, is_["arazi"], is_["isik"]["gok"]["ufuk"])   # mekân paketi: deniz/nehir yüzeyi (arazide su yoksa hiçbir şey)
	var sp: Dictionary = is_.get("serpme", {})
	if sp.get("acik", false):   # sinematik paket 2: prosedürel ağaç/kaya serpmesi (görüş çizgisi ve oyuncu şeridi boş)
		var kk: Dictionary = c["kamera"]
		var kameralar := [[_vec(kk["bas"]["konum"]), _vec(kk["bas"]["hedef"])], [_vec(kk["son"]["konum"]), _vec(kk["son"]["hedef"])]]
		Serp.serp(self, sp, is_["arazi"], Vector2(m[0], m[1]), kameralar, int(is_.get("tohum", 1)) * 131 + str(c["id"]).hash() % 1000)
	Mz.kur(is_.get("malzeme", {}))
	Y.k_spek = float(is_.get("malzeme", {}).get("spekuler", 0.3))   # mekân kalite paketi: stilize parçalara PBR malzeme (kapalıysa etkisiz)
	var yl: Dictionary = is_.get("yerlesim", {})
	if yl.get("acik", false):   # sinematik paket 2: prosedürel ordugâh
		var kb2: Dictionary = c["kamera"]["bas"]
		var il := _vec(kb2["hedef"]) - _vec(kb2["konum"])
		il.y = 0
		var kk2: Dictionary = c["kamera"]
		var kam2 := [[_vec(kk2["bas"]["konum"]), _vec(kk2["bas"]["hedef"])], [_vec(kk2["son"]["konum"]), _vec(kk2["son"]["hedef"])]]
		if str(yl.get("tur", "ordugah")) == "ordugah":
			Y.ordugah(self, yl, is_["arazi"], Vector3(m[0], 0, m[1]), il.normalized(), kam2, int(is_.get("tohum", 1)) * 173 + str(c["id"]).hash() % 1000, t)
		else:   # mekân paketi: kale, kasaba, liman, nehir iskelesi
			Y.dizi(self, yl, is_["arazi"], Vector3(m[0], 0, m[1]), il.normalized(), kam2, int(is_.get("tohum", 1)) * 173 + str(c["id"]).hash() % 1000, t)
	for cv in is_.get("cevre", []):
		var n := D.glb_yukle(cv["glb"])
		n.position = Vector3(cv["konum"][0], 0, cv["konum"][1])
		n.rotation.y = deg_to_rad(float(cv.get("yon_derece", 0.0)))
		n.scale = Vector3.ONE * float(cv.get("olcek", 1.0))
		if is_.get("vfx", {}).get("zemine_otur", false):   # tepeye düşen çevre varlığı gömülmesin/havada kalmasın
			n.position.y = V.zemin_y(n.position.x, n.position.z, is_["arazi"])
		add_child(n)
		var vt: Dictionary = is_.get("vfx", {})
		if vt.get("acik", false) and str(cv["id"]) in vt.get("top", {}).get("parcalar", []):   # top atışı: ağız alevi + duman
			_toplar.append(V.top_atisi(self, n, vt["top"], int(is_.get("tohum", 1)) * 59 + _toplar.size() * 17, t))
	Yz.kur(is_.get("yuzey", {}))   # gerçekçi karakter yüzeyi (kapalıysa etkisiz)
	for k in c.get("karakterler", []):
		var takim: Dictionary = is_["takimlar"][k["takim"]]
		var ks: Array = takim.get("kisiler", [])
		var gercekci: bool = is_.get("insan", {}).get("acik", false) and ks.size() > 0
		if gercekci:   # gerçekçi insanlar: aynı takımın her örneği başka bir kişi (tohumlu başlangıç + sıra)
			var say: int = _kisi_sayac.get(k["takim"], 0)
			_kisi_sayac[k["takim"]] = say + 1
			takim = takim.duplicate()
			takim["glb"] = ks[(absi(str(k["takim"]).hash() + int(is_.get("tohum", 1)) * 31) + say) % ks.size()]
			takim = D.insan_paylari(takim)
		var kok := D.kur(takim)
		if gercekci and is_.get("insan", {}).get("zirh_maskesi", false):
			D.maske_uygula(kok)
		add_child(kok)
		_sira += 1
		var yon := deg_to_rad(float(k.get("yon_derece", 0.0)))
		kok.rotation.y = yon
		kok.scale = Vector3.ONE * float(k.get("olcek", 1.0))
		var kc: Dictionary = is_.get("karakter_cesit", {})
		if kc.get("acik", false):   # Faz 5.6: kişi başına tohumlu görünüm çeşitliliği
			D.cesitle(kok, int(is_.get("tohum", 1)) * 7919 + _sira * 104729, kc)
		Yz.uygula(kok)
		if not gercekci:   # gerçekçi kişilerin bedeni zaten farklı; kemik ölçeği yalnız UBC gövdesine
			Bd.kur(kok, int(is_.get("tohum", 1)) * 7919 + _sira * 104729 + 17, is_.get("beden", {}))   # vücut/yüz çeşitliliği
		var bas := Vector3(k["konum"][0], 0, k["konum"][1])
		kok.position = bas
		var ap := D.animasyon_oynatici(kok)
		var anim: String = k["animasyon"]
		if anim.contains("/") and ap:   # Faz 5.5: ek kütüphane animasyonu ("ual2/...")
			var kut := anim.get_slice("/", 0)
			var kutler: Dictionary = is_.get("ek_animasyon_kutuphaneleri", {})
			if kutler.has(kut):
				D.ek_kutuphane_ekle(kok, ap, kut, kutler[kut])
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
		var o := {"kok": kok, "bas": bas, "ileri": Vector3(sin(yon), 0, cos(yon)), "hiz": float(k.get("hiz_m_sn", 0.0)),
			"ap": ap, "gecikme": gecikme, "basladi": gecikme <= t}
		if k.has("binek"):   # sinematik paket: binici atın üstünde; at ilerler, binici atla birlikte gelir
			var b: Dictionary = k["binek"]
			var at := D.binek_kur(kok, b, int(is_.get("tohum", 1)) * 7919 + _sira * 104729 + 17)
			add_child(at)
			at.rotation.y = yon
			at.position = bas
			at.scale = Vector3.ONE * float(b.get("olcek", 1.0))
			var aap := D.animasyon_oynatici(at)
			var aan := aap.get_animation(b["animasyon"])
			aan.loop_mode = Animation.LOOP_LINEAR
			aap.play(b["animasyon"])
			aap.seek(float(k.get("faz_sn", 0.0)) * 1.7 + t, true)
			var legen := D.iskelet_kemik_y(kok, "pelvis") - kok.global_position.y
			var eyer_kemik: String = b.get("eyer_kemik", "Torso")
			var govde_y := D.iskelet_kemik_y(at, eyer_kemik) - at.global_position.y
			remove_child(kok)
			at.add_child(kok)
			kok.rotation = Vector3.ZERO
			var taban := (govde_y + float(b.get("eyer_ust_m", 0.18)) - legen) / at.scale.y
			kok.position = Vector3(0, taban, float(b.get("eyer_z_m", 0.0)))
			o["kok"] = at
			o["binici"] = kok
			o["eyer_kemik"] = eyer_kemik
			o["govde_y0"] = govde_y
			o["taban"] = taban
		var vx: Dictionary = is_.get("vfx", {})
		if vx.get("acik", false) and float(k.get("hiz_m_sn", 0.0)) >= float(vx["toz"].get("esik_hiz", 2.5)):
			var tk: Dictionary = vx["toz"].duplicate()
			tk["geri_m"] = float(tk.get("geri_binek_m", -1.3)) if o.has("binici") else float(tk.get("geri_m", -0.4))
			(o["kok"] as Node3D).position = o["bas"] + o["ileri"] * o["hiz"] * t   # ön işleme tozu şimdiki konumda başlasın
			V.toz(o["kok"], tk, int(is_.get("tohum", 1)) * 31 + _sira, t)   # sinematik paket: hızlı ilerleyenin tozu
		oyuncular.append(o)
	var vx2: Dictionary = is_.get("vfx", {})
	if vx2.get("acik", false) and vx2.get("savas", false):   # çarpışma sahnesi: arka planda savaş dumanı
		var kb: Dictionary = c["kamera"]["bas"]
		var ks: Dictionary = c["kamera"]["son"]
		var kh := (_vec(kb["hedef"]) + _vec(ks["hedef"])) * 0.5   # kamera hareketinin ortası: duman çekim boyunca kadrajda
		var ileri := kh - (_vec(kb["konum"]) + _vec(ks["konum"])) * 0.5
		ileri.y = 0
		V.duman(self, kh * Vector3(1, 0, 1), ileri.normalized(), vx2["duman"], int(is_.get("tohum", 1)) * 97, t, is_["arazi"])
	var vx3: Dictionary = is_.get("vfx", {})
	if vx3.get("acik", false):   # olaya bağlı efektler: ok yağmuru, yangın (senaryo niyeti) ve düello kıvılcımı
		var kb4: Dictionary = c["kamera"]["bas"]
		var kh4 := _vec(kb4["hedef"]) * Vector3(1, 0, 1)
		var il4 := _vec(kb4["hedef"]) - _vec(kb4["konum"])
		il4.y = 0
		il4 = il4.normalized()
		var ef: Array = c["ortam"].get("efekt", [])
		var tohum4 := int(is_.get("tohum", 1)) * 131 + str(c["id"]).hash() % 997
		if "ok_yagmuru" in ef and vx3.has("ok"):
			_oklar.append(V.ok_yagmuru(self, kh4, -il4, vx3["ok"], tohum4, is_["arazi"]))
		if "yangin" in ef and vx3.has("yangin"):
			var nk: Array = []
			for cv in c["ortam"].get("cevre", []):
				nk.append(Vector3(cv["konum"][0], V.zemin_y(cv["konum"][0], cv["konum"][1], is_["arazi"]) + 0.8, cv["konum"][1]))
			if nk.is_empty():
				var yn := il4.cross(Vector3.UP).normalized()
				for j in 3:
					var q := kh4 + il4 * (18.0 + 6.0 * j) + yn * (j - 1) * 9.0
					nk.append(Vector3(q.x, V.zemin_y(q.x, q.z, is_["arazi"]) + 0.5, q.z))
			_ates = V.yangin(self, nk, vx3["yangin"], tohum4, t)
		var cf: Array = c.get("meta", {}).get("koreografi", {}).get("ciftler", [])
		if vx3.has("kivilcim") and cf.size() > 0:
			var nk2: Array = []
			for cp in cf:
				nk2.append(Vector3(cp[0], V.zemin_y(cp[0], cp[1], is_["arazi"]) + 1.25 * float(c.get("insan_boy_orani", 1.0)), cp[1]))
			_kivilcim = V.kivilcim(self, nk2, vx3["kivilcim"], tohum4 + 5)
	var kl: Dictionary = is_.get("kalabalik", {})
	if kl.get("acik", false):   # sinematik paket 2: arka plan ordusu (pişirilmiş poz + MultiMesh)
		var kb3: Dictionary = c["kamera"]["bas"]
		var il3 := _vec(kb3["hedef"]) - _vec(kb3["konum"])
		il3.y = 0
		var mm3: Array = is_["sahne_merkezi"]
		K.kur(self, kl, is_["takimlar"], is_["arazi"], Vector3(mm3[0], 0, mm3[1]), il3.normalized(), int(is_.get("tohum", 1)) * 211 + str(c["id"]).hash() % 1000)
	if is_.get("sinema", {}).get("acik", false):   # sinematik paket: vinyet + bölünmüş tonlama + gren
		_sinema = S.kur(self, is_["sinema"])
	kam = c["kamera"]
	kamera = Camera3D.new()
	kamera.near = 0.1
	kamera.far = 800.0
	add_child(kamera)
	if is_.get("film", {}).get("acik", false):   # sinematik render: derinlik tabanlı hava, temas gölgesi, alan derinliği, renk
		_film = F.kur(kamera, is_["film"], is_["isik"])
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
		if o.has("binici"):   # atın gövde kemiği inip kalktıkça binici de inip kalkar
			var at: Node3D = o["kok"]
			var dy := D.iskelet_kemik_y(at, o["eyer_kemik"]) - at.global_position.y - float(o["govde_y0"])
			(o["binici"] as Node3D).position.y = float(o["taban"]) + dy / at.scale.y
		var ap: AnimationPlayer = o["ap"]
		if not o["basladi"] and t >= o["gecikme"]:
			ap.play()
			o["basladi"] = true
		D.guncelle(o.get("binici", o["kok"]))
	var u := _kolay(clampf(t / sure, 0.0, 1.0), kam.get("yumusatma", "giris_cikis"))
	var b: Dictionary = kam["bas"]
	var s: Dictionary = kam["son"]
	kamera.fov = lerpf(b["fov"], s["fov"], u)
	kamera.position = _vec(b["konum"]).lerp(_vec(s["konum"]), u)
	kamera.look_at(_vec(b["hedef"]).lerp(_vec(s["hedef"]), u), Vector3.UP)
	var sr: Dictionary = kam.get("sarsinti", {})
	if not sr.is_empty():   # el kamerası: deterministik, çok frekanslı (nefes + adım + titreme) açısal sarsıntı
		var a := deg_to_rad(float(sr.get("derece", 0.8)))
		kamera.rotate_object_local(Vector3.RIGHT, a * (0.6 * sin(t * 1.7 + 0.3) + 0.3 * sin(t * 4.1 + 1.1) + 0.1 * sin(t * 9.3)))
		kamera.rotate_object_local(Vector3.UP, a * (0.6 * sin(t * 1.3 + 2.0) + 0.3 * sin(t * 3.7 + 0.5) + 0.1 * sin(t * 8.1 + 1.7)))
		kamera.rotate_object_local(Vector3.FORWARD, a * 0.4 * (sin(t * 1.1 + 4.0) + 0.3 * sin(t * 5.3)))
	if _film:
		F.guncelle(_film, O._gunes_yon, kamera.position.distance_to(_vec(b["hedef"]).lerp(_vec(s["hedef"]), u)), kamera.fov)

func _process(delta: float) -> void:
	_guncelle()   # kare n, t = n / fps anını gösterir
	if _sinema:
		_sinema.set_shader_parameter("kare", roundf(t * 30.0))
	Y.guncelle(t)
	O.su_guncelle(t)
	for tp in _toplar:
		V.top_guncelle(tp, t)
	for od in _oklar:
		V.ok_guncelle(od, t)
	V.yangin_guncelle(_ates, t)
	V.kivilcim_guncelle(_kivilcim, t)
	t += delta
