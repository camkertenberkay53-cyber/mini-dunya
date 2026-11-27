"""ASR kelimelerini karşılaştırma belirteçlerine çevirir (kalite.py ve kalite_v1.py ortak kullanır).

Düzeltme (QC1'de bulundu): faster-whisper kelime zaman damgalarında Türkçe kesme ekini ayrı kelime verir
("Roma" + "'nın") ve sayıları ayrı kelimeler olarak döner ("dört" "bir"). Kelime kelime normalleştirmek sahte
"araya giren kelime" hataları üretiyordu. Burada önce boşlukla başlamayan parçalar önceki kelimeye eklenir,
sonra tüm belirteçler üzerinde ardışık sayı sözcükleri birleştirilir (referans metinle aynı kural).
"""
from __future__ import annotations


def hip_olustur(kelimeler: list[dict], normal, sayi_re, sayi_ekli_re):
    birim: list[dict] = []
    for w in kelimeler:
        ham = w.get("ham", " " + w["kelime"])
        if birim and not ham.startswith(" ") and ham.strip():
            b = birim[-1]
            b["metin"] += ham
            b["son"] = w["son"]
            b["olasilik"] = min(b["olasilik"], w["olasilik"])
        else:
            birim.append({"metin": ham.strip(), "bas": w["bas"], "son": w["son"], "olasilik": w["olasilik"]})
    hip, zaman, olas = [], [], []
    for b in birim:
        for tok in normal(b["metin"]):
            if hip and sayi_re.match(hip[-1]) and sayi_ekli_re.match(tok):
                hip[-1] += tok
                zaman[-1] = (zaman[-1][0], b["son"])
            else:
                hip.append(tok)
                zaman.append((b["bas"], b["son"]))
                olas.append(b["olasilik"])
    return hip, zaman, olas
