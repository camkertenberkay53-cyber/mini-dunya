extends "res://sahneler/olcum.gd"
## Faz 3 render ölçümü: aynı sahne yükü (15 tam animasyonlu asker, atlı, 420 uzak asker, ot, toz, sis),
## ama askerler Faz 3 dönem kitlerinden: derlenmiş gövde + yuvalara takılan ortak ekipman (donatıcı).
## Takım listesi: res://varlik/faz3/takimlar.json (repo içi kopya; yollar res://).

const D := preload("res://sahneler/donatici.gd")
var takim_kokleri: Array = []

func _kol() -> void:
	var liste: Array = JSON.parse_string(FileAccess.get_file_as_string("res://varlik/faz3/takimlar.json"))
	var i := 0
	for sira in 5:
		for yan in 3:
			var k: Node3D = D.kur(liste[i % liste.size()])
			var ofs := Vector3(-1.15 + yan * 1.15 + randf_range(-0.12, 0.12), 0, -sira * 1.55 + randf_range(-0.15, 0.15))
			add_child(k)
			askerler.append(k)
			ofsetler.append(ofs)
			takim_kokleri.append(k)
			var ap := D.animasyon_oynatici(k)
			var ad := "Walk_Formal_Loop" if ap.has_animation("Walk_Formal_Loop") else "Walk_Formal"
			var a := ap.get_animation(ad)
			a.loop_mode = Animation.LOOP_LINEAR
			ap.play(ad)
			ap.speed_scale = randf_range(0.96, 1.04)
			ap.seek(randf() * a.length, true)
			i += 1

func _process(delta: float) -> void:
	super._process(delta)
	for k in takim_kokleri:
		D.guncelle(k)
