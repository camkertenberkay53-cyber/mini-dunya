extends Node3D
## Ayak kayması ölçümü (Faz 4): bir takımı verilen animasyon ve ilerleme hızıyla oynatır, her karede iki ayağın
## (ball_l, ball_r) dünya konumunu kaydeder. Yere basan ayağın kayması motor/uretim/ayak_kaymasi.py'de hesaplanır.
## godot --headless --path motor/godot res://sahneler/ayak_olcum.tscn --fixed-fps 30 --quit-after N -- <takim.json> <anim> <hiz> <cikti.json>

const D := preload("res://sahneler/donatici.gd")
var kok: Node3D
var sk: Skeleton3D
var hiz := 0.0
var t := 0.0
var kayit := []
var cikti := ""

func _ready() -> void:
	var a := OS.get_cmdline_user_args()
	kok = D.kur(JSON.parse_string(FileAccess.get_file_as_string(a[0])))
	add_child(kok)
	hiz = float(a[2])
	cikti = a[3]
	sk = D.iskelet(kok)
	var ap := D.animasyon_oynatici(kok)
	ap.get_animation(a[1]).loop_mode = Animation.LOOP_LINEAR
	ap.play(a[1])
	ap.callback_mode_process = AnimationMixer.ANIMATION_CALLBACK_MODE_PROCESS_MANUAL

func _process(delta: float) -> void:
	var ap := D.animasyon_oynatici(kok)
	kok.position = Vector3(0, 0, hiz * t)
	ap.advance(0.0 if t == 0.0 else delta)
	var k := {"t": t}
	for ad in ["ball_l", "ball_r"]:
		var p := (sk.global_transform * sk.get_bone_global_pose(sk.find_bone(ad))).origin
		k[ad] = [p.x, p.y, p.z]
	kayit.append(k)
	t += delta
	var f := FileAccess.open(cikti, FileAccess.WRITE)
	f.store_string(JSON.stringify(kayit))
