"""kaos/sinema/motor.sahne_render regresyon yardımcısı (Faz-53A A2).

Kodlayıcıya (ffmpeg) giden HAM BGR kareler SHA-256 ile özetlenir; böylece karşılaştırma kodlayıcıdan bağımsız, piksel
düzeyindedir (fark 0 = özet aynı). Sahneler: main dalındaki 45 sn Otlukbeli senaryosu + kapsamı genişleten bir ek sahne
(gren, giriş flaşı, darbe, dof, parlama, yağmur, kar, ışık hüzmesi, vinyet). Süre ve çözünürlük testin hızı için küçültülür;
kod yolları aynıdır.
python3 -m motor.testler.sinema_regresyon yaz   -> taban dosyasını (yalnızca kaos/sinema değişmeden önce) üretir
"""
import hashlib
import json
import os
import sys
from pathlib import Path

from motor import ayar

TABAN = Path(__file__).with_name("sinema_regresyon_taban.json")
SENARYO = ayar.REPO / "senaryolar" / "test_otlukbeli_45sn.json"
W, H, FPS, SURE = 540, 960, 30, 1.0


def sahneler() -> list[dict]:
    s = json.loads(SENARYO.read_text())["sahneler"]
    out = []
    for x in s:
        y = {k: v for k, v in x.items() if k not in ("anlatim", "gecis", "sesler", "sure")}
        y["gorsel"] = str(ayar.REPO / y["gorsel"])
        y["sure_render"] = SURE
        out.append(y)
    ek = dict(out[1], id="ek_kapsam", gren=0.8, giris_flas=True, darbeler=[0.3], vinyet=0.7, ton="teal_turuncu", ton_guc=0.8,
              efektler=[{"tip": "yagmur", "guc": 0.5}, {"tip": "kar", "guc": 0.5}, {"tip": "isik", "guc": 0.6},
                        {"tip": "parlama", "guc": 0.5}, {"tip": "dof", "guc": 0.6, "odak": [0.5, 0.4]}, {"tip": "duman", "guc": 0.4}])
    out.append(ek)
    return out


class _SahteKodlayici:
    def __init__(self, komut, stdin=None):
        self.yol = komut[-1]
        self.ozetler = []
        self.stdin = self

    def write(self, b):
        self.ozetler.append(hashlib.sha256(b).hexdigest())

    def close(self):
        Path(self.yol).write_bytes(b"")

    def wait(self):
        return 0


def ozetle(tmp: Path) -> dict:
    from kaos.sinema import motor
    sonuc = {}
    gercek = motor.subprocess.Popen
    son = {}

    def sahte(komut, stdin=None):
        son["k"] = _SahteKodlayici(komut, stdin)
        return son["k"]
    motor.subprocess.Popen = sahte
    try:
        for s in sahneler():
            motor.sahne_render(dict(s), str(tmp / f"{s['id']}.mp4"), W, H, FPS, log=lambda *_: None)
            sonuc[s["id"]] = son["k"].ozetler
    finally:
        motor.subprocess.Popen = gercek
    return sonuc


if __name__ == "__main__" and sys.argv[1:] == ["yaz"]:
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        o = ozetle(Path(d))
    TABAN.write_text(json.dumps({"aciklama": "kaos/sinema sahne_render ham kare SHA-256 tabanı (A2 öncesi, commit cabc8a5)",
                                 "W": W, "H": H, "fps": FPS, "sure": SURE, "sahneler": o}, indent=1))
    print({k: len(v) for k, v in o.items()})
