"""A1 teknik sahne: kendi ürettiğimiz sentetik görsel, YALNIZ bu deneye ait geçici kayıtla (üretim kaydına girmez)."""
import json, sys
from pathlib import Path
from motor.uretim import render
from motor.varlik import tarihi_gorsel as tg
K=Path('/tmp/mh/a1/sahne')
p=K/'sentetik_kale.png'
g={"gorsel_id":"a1_sentetik_kale","kaynak_url":"yerel: Claude tarafından üretilmiş sentetik deneme görseli","kaynak_kurum":"yok (deneme)",
   "eser_adi":"Sentetik kale (gravür benzeri)","tarih":"2026","bolge":"-","donem":"-","kultur":"-","taraf_faction":"-",
   "gorsel_turu":"gravur_benzeri_sentetik","uygun_sahne_turleri":["deneme"],"cozunurluk":[3000,2000],"ozne_bilgisi":"ön plan kale",
   "derinlik_uygunlugu":"yuksek","lisans_turu":"CC0-1.0","kamu_mali_gerekcesi":"kendi üretimimiz, deneme","lisans_dogrulandi":True,
   "onay":{"onaylayan":"DENEME KAYDI (üretim değil)","tarih":"2026-11-26"},"yerel_yol":str(p),"sha256":tg._sha(p)}
(K/'deneme_kaydi.json').write_text(json.dumps({"gorseller":[g]},ensure_ascii=False,indent=1))
tg.KAYIT=K/'deneme_kaydi.json'
cek={"id":"A1","cumleler":["C1"],"sure_sn":6.0,"tur":"gorsel25d","metin":"Kale surları","gorsel25d":{"gorsel_id":"a1_sentetik_kale",
     "hareket":"push_in","odak":[0.5,0.5],"ozne":[0.35,0.27,0.67,0.84],"parallax":1.0,"ufuk":0.45,
     "efektler":[{"tip":"toz","guc":0.6},{"tip":"sis","guc":0.5}],"ton":"sicak"}}
for ad,coz in (("uzun",[1920,1080]),("shorts",[1080,1920])):
    plan={"surum":1,"konu":"faz53a-a1-deneme","donem":"osmanli-15yy","donemler":["osmanli-15yy"],"fps":30,"cozunurluk":coz,"tohum":1,
          "cekimler":[cek],"eksikler":[],"ses":{"motor":"piper","cizelge":[],"toplam_sn":6.0},**({"format":"uzun"} if ad=="uzun" else {})}
    pp=K/f'plan_{ad}.json'; pp.write_text(json.dumps(plan,ensure_ascii=False))
    r=render.render(str(pp),"A1",onbellek=False)
    (K/f'sonuc_{ad}.json').write_text(json.dumps(r,ensure_ascii=False,indent=1))
    print(ad, r["durum"], json.dumps(r.get("olculen"),ensure_ascii=False))
