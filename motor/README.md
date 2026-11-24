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

## Faz 3: tarihsel varlık üretimi ve dönem kitleri (dal: `motor-faz3`)

| Bileşen | Dosya | Komut |
| --- | --- | --- |
| Ekipman ve giysi kataloğu (malzeme, dönem, tarih güveni, kaynak) | `varlik/ekipman.yaml` | - |
| Sert ekipman üreticisi (Blender, prosedürel) | `varlik/ekipman.py`, `varlik/blender/ekipman_uret.py`, `doku.py`, `ortak.py` | `python3 -m motor.varlik.ekipman [id] [--zorla]` |
| Gövdeden türetilen giysiler + ekipman yuvaları | `varlik/blender/giysi.py` | (karakter derlemesinin parçası) |
| Dönem kitleri (8 kategori, roller, karakterler) | `kit/faz3/*.yaml` | - |
| Karakter sistemi: kural denetimi, gövde derleme, takım dosyaları | `karakter/takim.py` | `python3 -m motor.karakter.takim [--zorla]` |
| Montaj ve animasyon kararlılığı testi | `karakter/montaj.py`, `varlik/blender/takim_test.py` | `python3 -m motor.karakter.montaj [--hizli]` |
| Görsel karşılaştırma raporu | `karakter/karsilastir.py`, `godot/sahneler/karsilastirma.gd` | `python3 -m motor.karakter.karsilastir` |
| Siluet ayrışması (kitler arası, yanlış atama, uzaktan tanıma) | `karakter/siluet.py` | (kalite içinde) |
| Kalite sınıfları A/B/C/RED + görsel inceleme kaydı | `karakter/kalite.py`, `karakter/gorsel_inceleme.yaml` | `python3 -m motor.karakter.kalite` |
| Çalışma anında donatıcı (Godot) | `godot/sahneler/donatici.gd` | - |
| Kabul testleri | `testler/test_faz3.py` | `python3 -m pytest motor/testler -q` |

Karakter = gövde (çıplak evrensel gövde + gövdeden türetilen giysiler, tek GLB) + yuvalara takılan ortak ekipman GLB'leri.
Aynı giysi birleşimini kullanan karakterler tek gövdeyi paylaşır; ekipman her karakterde aynı dosyadır.
Rastgele birleşim yoktur: dönem, yuva ve çakışma kuralını bozan karakter derlenmez.

## Faz 4: üretim hattı (dal: `motor-faz3`) — kontrol noktası 1

Katmanlar yalnızca `uretim/semalar/` altındaki JSON sözleşmeleriyle bağlanır: konu → araştırma → senaryo → çekim planı.
Konuya özel kod yoktur; konu, araştırma, senaryo ve çekim planı veri dosyasıdır.

| Bileşen | Dosya | Komut |
| --- | --- | --- |
| Sözleşmeler (şema + çapraz başvuru) | `uretim/semalar/*.schema.json`, `uretim/sozlesme.py` | `python3 -m motor.uretim.sozlesme <tur> <dosya>` |
| M6 karakter ve dönem seçici | `uretim/secici.py` | - |
| M7 ortam seçici, arazi/ışık hazır ayarları | `uretim/ortam_secici.py`, `uretim/kurallar/arazi.yaml` | - |
| M8 animasyon izni (beyaz liste) | `uretim/animasyon_izni.py`, `uretim/kurallar/animasyon.yaml` | - |
| Ek animasyon testi (9 animasyon, Faz 3b eşikleri) | `karakter/animasyon_testi.py` → `karakter/animasyon_testi.json` | `python3 -m motor.karakter.animasyon_testi` |
| Animasyon zemin hızı ölçümü (Blender) | `varlik/blender/animasyon_hizi.py` → `uretim/kurallar/animasyon_olcum.json` | - |
| Ayak kayması ölçümü (Godot) | `uretim/ayak_kaymasi.py`, `godot/sahneler/ayak_olcum.gd` | `python3 -m motor.uretim.ayak_kaymasi <takim> <anim>` |
| Kamera mesafesi (ekran oranı) | `uretim/kadraj.py`, `uretim/kurallar/mesafe.yaml` | - |
| Çekim planı denetimi | `uretim/plan_denetim.py` | `python3 -m motor.uretim.plan_denetim <plan.json>` |
| Veri güdümlü çekim sahnesi + render ölçümü | `godot/sahneler/cekim.gd`, `ortam.gd`, `uretim/render.py` | `python3 -m motor.uretim.render <plan.json> <cekim> [klasör]` |
| Kabul testleri | `testler/test_faz4.py` | `python3 -m pytest motor/testler -q` |

Kurallar: denetimden geçmeyen plan render edilmez. Ölçülmemiş animasyon kullanılamaz. Yer değiştiren animasyon yalnızca
ölçülmüş zemin hızıyla ilerletilir. Yakın plan (karakter kareye sığmıyor) A sınıfı karakter olmadan reddedilir.
Eksik karakter, ekipman, binek, nesne ya da alet uydurulmaz; denetim raporunda eksik olarak çıkar.
Not: Faz 2 testleri `varlik/derlenmis.json` içindeki `derleme_sn` alanını yeniden yazar (Faz 2'den gelen yan etki); commit edilmez.
