"""Kalite kontrolün güvenilirlik ölçümü (deneysel, Faz 5.1 P0).

Kullanım: python3 guvenilirlik.py <onceki_ses_klasoru> <cikti_klasoru>
  onceki_ses_klasoru: SES1 koşusunun ham çıktıları (chatterbox_*.wav, piper_*_*.wav, uretim_*.json)
Ölçülenler:
  A) Hata enjeksiyonu: Chatterbox test kliplerine bilinen 8 hata türü eklenir; QC'nin yakalama oranı (duyarlılık).
  B) Yanlış alarm: Piper (yalnız test amaçlı) ve ham Chatterbox test klipleri olduğu gibi denetlenir; KRİTİK alarm oranı.
     Not: bu klipler insan tarafından etiketlenmedi; içlerinde gerçek hata olabilir (alarm her zaman yanlış değildir).
  C) Gerçek vaka: SES1'deki ham Chatterbox pilot çıktıları (rakamlı metin + bilinen halüsinasyon, pilot 7) denetlenir.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

BURASI = Path(__file__).resolve().parent
sys.path.insert(0, str(BURASI))
from kalite import denetle, harf_hizi  # noqa: E402
import kalite_v1  # noqa: E402  (önceki kural sürümü; aynı veriyle karşılaştırma için)
from metin import hazirla  # noqa: E402
from uret_qc import ASR  # noqa: E402

YANLIS_ISIM = {"Harran": "Hasankeyf", "Roma": "Bizans", "Semerkant": "Kudüs", "Kleopatra": "Nefertiti",
               "İstanbul": "Edirne", "Cengiz Han": "Timur Han"}
YANLIS_SAYI = {"elli üç": "elli dört", "otuz üç": "kırk üç", "bin dört yüz elli üç": "bin dört yüz kırk üç"}


def oku(p: Path):
    x, sr = sf.read(str(p), dtype="float32")
    return (x if x.ndim == 1 else x.mean(1)), sr


def main() -> int:
    kaynak, cikti = Path(sys.argv[1]), Path(sys.argv[2])
    cikti.mkdir(parents=True, exist_ok=True)
    cum = json.loads((BURASI.parent / "cumleler.json").read_text())
    asr = ASR()
    rng = random.Random(51)
    sonuc = {"enjeksiyon": [], "yanlis_alarm": [], "gercek_vaka": []}

    def qc(x, sr, metin, ozel=None, hiz=None, ad="g"):
        yol = cikti / f"{ad}.wav"
        sf.write(str(yol), x, sr)
        if ozel is None:
            metin, _, ozel = hazirla(metin)
        a = asr(yol)
        r = denetle(x, sr, metin, ozel, a, hiz)
        r["durum_v1"] = kalite_v1.denetle(x, sr, metin, ozel, a, hiz)["durum"]
        yol.unlink()
        return r

    # B) yanlış alarm (olduğu gibi)
    for motor in ("chatterbox", "piper_fahrettin", "piper_fettah", "piper_dfki"):
        klip = [oku(kaynak / f"{motor}_test_{i:02d}.wav") for i in range(len(cum["test"]))]
        hizlar = [h for h in (harf_hizi(x, sr, cum["test"][i]) for i, (x, sr) in enumerate(klip)) if h]
        hiz = float(np.median(hizlar))
        for i, (x, sr) in enumerate(klip):
            r = qc(x, sr, cum["test"][i], hiz=hiz, ad=f"ya_{motor}_{i}")
            sonuc["yanlis_alarm"].append({"motor": motor, "no": i, "durum": r["durum"], "durum_v1": r["durum_v1"], "kritik": r["kritik"],
                                          "uyari": r["uyari"], "dokum": r["olcum"]["dokum"]})
            print("YA", motor, i, r["durum"], r["kritik"], flush=True)
    # A) enjeksiyon (Chatterbox test klipleri)
    klip = [oku(kaynak / f"chatterbox_test_{i:02d}.wav") for i in range(len(cum["test"]))]
    hiz = float(np.median([h for h in (harf_hizi(x, sr, cum["test"][i]) for i, (x, sr) in enumerate(klip)) if h]))
    for i, (x, sr) in enumerate(klip):
        metin = cum["test"][i]
        diger = klip[(i + 3) % len(klip)][0]
        n = len(x)
        bas, son = int(0.05 * n), int(0.95 * n)
        orta = n // 2
        hatalar = {
            "kuyruk_anlamsiz": np.concatenate([x, diger[: int(3.0 * sr)][::-1]]),
            "kuyruk_konusma": np.concatenate([x, diger[: int(2.5 * sr)]]),
            "son_kesik": x[: int(bas + 0.65 * (son - bas))],
            "orta_kesik": np.concatenate([x[:orta], x[orta + int(0.8 * sr):]]),
            "uzun_sessizlik": np.concatenate([x[:orta], np.zeros(int(2.0 * sr), np.float32), x[orta:]]),
            "araya_ekleme": np.concatenate([x[:orta], diger[int(0.5 * sr): int(1.7 * sr)], x[orta:]]),
        }
        for tur, y in hatalar.items():
            r = qc(y.astype(np.float32), sr, metin, hiz=hiz, ad=f"e_{i}_{tur}")
            sonuc["enjeksiyon"].append({"no": i, "tur": tur, "durum": r["durum"], "durum_v1": r["durum_v1"], "kritik": r["kritik"], "uyari": r["uyari"]})
            print("EN", i, tur, r["durum"], r["kritik"][:1], flush=True)
        for dogru, yanlis in YANLIS_SAYI.items():
            if dogru in metin and (dogru != "elli üç" or "bin dört yüz" not in metin):
                k = metin.replace(dogru, yanlis)
                r = qc(x, sr, k, ozel=[{"tur": "sayi", "yazim": yanlis, "okunus": yanlis}], hiz=hiz, ad=f"e_{i}_sayi")
                sonuc["enjeksiyon"].append({"no": i, "tur": "yanlis_sayi", "durum": r["durum"], "durum_v1": r["durum_v1"], "kritik": r["kritik"],
                                            "uyari": r["uyari"]})
                print("EN", i, "yanlis_sayi", r["durum"], flush=True)
                break
        for dogru, yanlis in YANLIS_ISIM.items():
            if dogru in metin:
                k = metin.replace(dogru, yanlis)
                r = qc(x, sr, k, ozel=[{"tur": "isim", "yazim": yanlis, "okunus": yanlis}], hiz=hiz, ad=f"e_{i}_isim")
                sonuc["enjeksiyon"].append({"no": i, "tur": "yanlis_isim", "durum": r["durum"], "durum_v1": r["durum_v1"], "kritik": r["kritik"],
                                            "uyari": r["uyari"]})
                print("EN", i, "yanlis_isim", r["durum"], flush=True)
                break
    # C) gerçek vaka: ham Chatterbox pilot (rakamlı metin olduğu gibi okutulmuştu)
    pk = [oku(kaynak / f"chatterbox_pilot_{i:02d}.wav") for i in range(len(cum["pilot"]))]
    hiz = float(np.median([h for h in (harf_hizi(x, sr, hazirla(cum["pilot"][i])[0]) for i, (x, sr) in enumerate(pk)) if h]))
    for i, (x, sr) in enumerate(pk):
        r = qc(x, sr, cum["pilot"][i], hiz=hiz, ad=f"gv_{i}")
        sonuc["gercek_vaka"].append({"no": i, "metin": cum["pilot"][i], "durum": r["durum"], "durum_v1": r["durum_v1"], "kritik": r["kritik"],
                                     "uyari": r["uyari"], "dokum": r["olcum"]["dokum"], "olcum": {
                                         k: r["olcum"][k] for k in ("kuyruk_ses_sn", "kuyruk_kelime", "sure_orani", "wer")}})
        print("GV", i, r["durum"], r["kritik"], flush=True)
    # Özet
    en = sonuc["enjeksiyon"]
    turler = sorted({e["tur"] for e in en})
    ozet = {"enjeksiyon": {t: {"toplam": sum(e["tur"] == t for e in en),
                               "yakalanan_herhangi": sum(e["tur"] == t and e["durum"] != "GECTI" for e in en),
                               "yakalanan_kritik": sum(e["tur"] == t and e["durum"] == "KRITIK" for e in en)} for t in turler}}
    ozet["enjeksiyon_toplam"] = {"toplam": len(en), "yakalanan_herhangi": sum(e["durum"] != "GECTI" for e in en),
                                 "yakalanan_kritik": sum(e["durum"] == "KRITIK" for e in en)}
    ozet["yanlis_alarm"] = {m: {"klip": sum(y["motor"] == m for y in sonuc["yanlis_alarm"]),
                                "kritik": sum(y["motor"] == m and y["durum"] == "KRITIK" for y in sonuc["yanlis_alarm"]),
                                "uyari": sum(y["motor"] == m and y["durum"] == "UYARI" for y in sonuc["yanlis_alarm"])}
                            for m in ("chatterbox", "piper_fahrettin", "piper_fettah", "piper_dfki")}
    ozet["gercek_vaka"] = {d: sum(g["durum"] == d for g in sonuc["gercek_vaka"]) for d in ("GECTI", "UYARI", "KRITIK")}
    for s_ in ("v1",):
        k = "durum_" + s_
        ozet[f"enjeksiyon_toplam_{s_}"] = {"yakalanan_herhangi": sum(e[k] != "GECTI" for e in en),
                                          "yakalanan_kritik": sum(e[k] == "KRITIK" for e in en)}
        ozet[f"enjeksiyon_{s_}"] = {t: {"yakalanan_herhangi": sum(e["tur"] == t and e[k] != "GECTI" for e in en),
                                        "yakalanan_kritik": sum(e["tur"] == t and e[k] == "KRITIK" for e in en)} for t in turler}
        ozet[f"yanlis_alarm_{s_}"] = {m: {"kritik": sum(y["motor"] == m and y[k] == "KRITIK" for y in sonuc["yanlis_alarm"]),
                                          "uyari": sum(y["motor"] == m and y[k] == "UYARI" for y in sonuc["yanlis_alarm"])}
                                      for m in ("chatterbox", "piper_fahrettin", "piper_fettah", "piper_dfki")}
        ozet[f"gercek_vaka_{s_}"] = {d: sum(g[k] == d for g in sonuc["gercek_vaka"]) for d in ("GECTI", "UYARI", "KRITIK")}
    sonuc["ozet"] = ozet
    (cikti / "qc_guvenilirlik.json").write_text(json.dumps(sonuc, ensure_ascii=False, indent=1))
    print(json.dumps(ozet, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
