# Evrensel Sinematik Tarih Shorts Motoru

Plan: Claude Docs'taki "Mimari Plan v2" belgesi. Bu klasör motorun kendisidir; videoya özel kod buraya girmez.

## Faz 2: temel altyapı ve varlık denetimi (bu dal: `motor-faz2`)

| Bileşen | Dosya | Komut |
| --- | --- | --- |
| Varlık kaynakları (lisans, commit) | `varlik/kaynaklar.yaml` | - |
| Paket → tür ve dönem kuralları | `varlik/kurallar.yaml` | - |
| Varlık kaydı (3989 dosya, sha256) | `varlik/katalog.py` → `varlik/kayit.json` | `python3 -m motor.varlik.katalog [--dogrula]` |
| Karakter tarifleri | `varlik/tarifler.yaml` | - |
| Tekrarlanabilir derleyici (Blender) | `varlik/derle.py`, `varlik/blender/*.py` | `python3 -m motor.varlik.derle [ad] [--zorla]` |
| Otomatik varlık denetimi | `varlik/denetim.py` → `varlik/denetim.json` | `python3 -m motor.varlik.denetim` |
| Dönem kitleri ve doğrulayıcı | `kit/*.yaml`, `kit/dogrula.py` | `python3 -m motor.kit.dogrula` |
| Yeterlilik raporu | `varlik/yeterlilik.py` → `varlik/YETERLILIK.md` | `python3 -m motor.varlik.yeterlilik` |
| Render ölçümü | `olcum/render_olc.py`, `godot/` | `python3 -m motor.olcum.render_olc <ortam> [kare]` |
| Kabul testleri | `testler/test_faz2.py` | `python3 -m pytest motor/testler -q` |

Önkoşullar: kaynak depoların klonları `MOTOR_KAYNAK` (varsayılan `/tmp/varlik`), Blender `bpy` modülü,
Godot 4.7.2 (`GODOT`), xvfb, ffmpeg. Büyük ara çıktılar repoya girmez (`MOTOR_ONBELLEK`).

## Kurallar

- Lisansı dosyadan doğrulanmamış hiçbir varlık kayda girmez. Bugün yalnızca CC0 var.
- Kaynak deposu kayıttaki commit'te değilse işlem durur.
- C seviyesi (stilize/chibi oran, iskelet uyumsuz, düşük poligon) karakter hiçbir kite giremez.
- Kıyafetin dönem etiketi kitin kabul ettiği dönemlerden biri değilse karakter o kite giremez.
- Kitler arası siluet ayrışma testi renkten bağımsızdır; renk kopyası her zaman yakalanır.
- Boş rol sessizce doldurulmaz; yeterlilik raporuna "YOK" olarak yazılır.
