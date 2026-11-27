"""Faz-53B kanıt panosu: gerçek tarihî görsellerde ozne_tespit sonucu (kutu, yüzler, güven, durum, öneri).

python3 deneyler/faz53b/ozne_pano.py <cikti_kok>   → <cikti_kok>/<gorsel_id>/5_ozne_tespit.jpg + ozne_tespit.json
Kayıtlar assets/tarihi_gorsel/*.json'dan okunur (CI'da commons_toplayici yazar). Görseller depoya girmez.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from motor.testler.gorsel25d_kanit import gercek_gorseller
from motor.varlik import ozne_tespit as ot
from motor.varlik import tarihi_gorsel as tg


def pano(img, r, baslik: str, yukseklik: int = 900):
    k = yukseklik / img.shape[0]
    g = cv2.resize(img, (round(img.shape[1] * k), yukseklik), interpolation=cv2.INTER_AREA)
    h, w = g.shape[:2]

    def ciz(kutu, renk, kalin):
        cv2.rectangle(g, (round(kutu[0] * w), round(kutu[1] * h)), (round(kutu[2] * w) - 1, round(kutu[3] * h) - 1), renk, kalin)
    for y in r["olcumler"].get("yuzler", []):
        ciz(y["kutu"], (0, 0, 255) if y["kararli"] else (0, 165, 255), 2)
    if "olasi_kutu" in r:
        ciz(r["olasi_kutu"], (0, 255, 255), 2)
    ciz(r["ozne_bilgisi"]["kutu"], (0, 220, 0), 3)
    satirlar = [baslik, f"tur={r['gorsel_turu']} durum={r['tespit_durumu']} yontem={r['tespit_yontemi']}",
                f"guven={r['guven_skoru']} oneri={r['onerilen_seviye']} fallback={r['fallback_uygulandi']} neden={r.get('neden')}",
                "yesil=ozne kutusu  kirmizi=kararli yuz  turuncu=kararsiz yuz  sari=olasi (reddedilen) kutu"]
    ust = 26 * len(satirlar) + 8
    tuval = cv2.copyMakeBorder(g, ust, 0, 0, max(0, 900 - w), cv2.BORDER_CONSTANT, value=(20, 20, 20))
    for i, s in enumerate(satirlar):
        cv2.putText(tuval, s, (8, 22 + 26 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (240, 240, 240), 1, cv2.LINE_AA)
    return tuval


def main(kok: Path) -> int:
    kayitlar, notlar = gercek_gorseller()
    for n in notlar:
        print("NOT", n)
    for k in kayitlar:
        yol = tg.dosya_yolu(k)
        r = ot.tespit(yol)
        hedef = kok / k["gorsel_id"]
        hedef.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(hedef / "5_ozne_tespit.jpg"), pano(cv2.imread(str(yol)), r, k["gorsel_id"]), [cv2.IMWRITE_JPEG_QUALITY, 88])
        (hedef / "ozne_tespit.json").write_text(json.dumps(r, ensure_ascii=False, indent=1))
        print("OZNE_TESPIT", k["gorsel_id"], json.dumps({a: r[a] for a in ot.ZORUNLU_ALANLAR} | {
            "kutu": r["ozne_bilgisi"]["kutu"], "neden": r.get("neden"), "uyarilar": r["uyarilar"],
            "olcumler": {x: v for x, v in r["olcumler"].items() if x != "yuzler"}, "yuzler": r["olcumler"].get("yuzler")},
            ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else "deneyler/faz53a/gercek")))
