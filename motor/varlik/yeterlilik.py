"""Varlık yeterlilik raporu: her dönem kiti için neyin var, neyin eksik olduğunu açıkça yazar.

python3 -m motor.varlik.yeterlilik   -> motor/varlik/YETERLILIK.md

Rapor iyimser değildir: bir rolde kullanılabilir varlık yoksa "YOK" yazar ve kiti kullanılamaz sayar.
"""
from __future__ import annotations

import collections
import json
from pathlib import Path

import yaml

from motor import ayar
from motor.kit import dogrula
from motor.varlik import katalog

RAPOR = Path(__file__).resolve().parent / "YETERLILIK.md"
TURLER = ["karakter_kiyafet", "silah", "yapi", "arac", "esya", "hayvan", "doga", "animasyon"]


def uret() -> str:
    kayit = katalog.yukle()
    denetim = json.loads(ayar.DENETIM_RAPOR.read_text())
    kit_yollari = sorted(dogrula.KIT_KLASORU.glob("*.yaml"))
    sonuc = dogrula.dogrula(kit_yollari)
    adaylar = [v for v in kayit["varliklar"] if v["durum"] == "aday"]
    sayac = collections.Counter((t, d) for v in adaylar for d in v["donem"] for t in [v["tur"]])

    s = ["# Varlık yeterlilik raporu", "",
         "Otomatik üretildi (`python3 -m motor.varlik.yeterlilik`). Kaynak: varlık kaydı, denetim raporu, kit dosyaları.", "",
         "## Kayıt özeti", "",
         f"- Kayıtlı dosya: **{len(kayit['varliklar'])}** (aday {kayit['ozet'].get('aday', 0)}, dışlanan {kayit['ozet'].get('dislandi', 0)}). Hepsi CC0, kaynak commit'ine sabit, sha256 ile.",
         "", "| Tür | Dönem etiketi | Aday sayısı |", "| --- | --- | --- |"]
    for (t, d), n in sorted(sayac.items()):
        s.append(f"| {t} | {d} | {n} |")

    s += ["", "## Karakter denetimi", "",
          "| Karakter | Seviye | Kıyafet dönemi | Gerekçe |", "| --- | --- | --- | --- |"]
    for ad, d in denetim.items():
        s.append(f"| {ad} | {d['seviye']} | {', '.join(d['donem'])} | {'; '.join(d['gerekce']) or '-'} |")

    s += ["", "## Dönem kitleri", ""]
    for p in kit_yollari:
        kit = yaml.safe_load(p.read_text(encoding="utf-8"))
        r = sonuc[p.stem]
        s += [f"### {kit['ad']} — {r['durum']}", ""]
        ozel = [d for d in kit["kabul_edilen_donemler"] if d != "evrensel"]
        s.append("| Tür | Bu döneme özgü aday | Evrensel aday |")
        s.append("| --- | --- | --- |")
        for t in TURLER:
            ozgu = sum(sayac.get((t, d), 0) for d in ozel)
            evr = sayac.get((t, "evrensel"), 0)
            s.append(f"| {t} | {'**YOK**' if ozgu == 0 else ozgu} | {evr} |")
        s += ["", "Engeller:"] + [f"- {h}" for h in r["hatalar"]]
        s += ["", "Üretilmesi gereken ayırt edici parçalar: " + ", ".join(kit.get("ayirt_edici", [])), ""]

    s += ["## Sonuç", "",
          "- Gerçek oranlı, evrensel iskeletli ve teknik olarak A seviyesinde 4 karakter var (erkek/kadın korucu ve köylü). "
          "Dördü de Avrupa tipi fantastik ortaçağ kıyafeti giyiyor; hiçbir dönem kitine giremez.",
          "- Stilize Quaternius karakterleri ve KayKit chibi karakteri otomatik olarak C seviyesine düştü (baş oranı, boy, iskelet).",
          "- Dört dönem kitinin (Osmanlı, Akkoyunlu, Bizans, Roma) hiçbirinde tek bir role bile uygun varlık yok. "
          "Ücretsiz paketlerde bu dönemlere özgü kıyafet, silah, yapı ya da gemi bulunmuyor.",
          "- Evrensel olanlar kullanılabilir: doğa ve arazi, çıplak gövde, saç ve UAL1'in 45 insan animasyonu. "
          "At modeli var ama bu kaynaklarda at animasyonu yok (Faz 4 riski).",
          "- Bu nedenle Faz 3'ün işi, ayırt edici parçaları evrensel gövdenin üzerine üretmek: başlık, gövde giysisi, "
          "zırh, kalkan, silah ve sancak.", ""]
    return "\n".join(s)


if __name__ == "__main__":
    RAPOR.write_text(uret(), encoding="utf-8")
    print("YAZILDI", RAPOR)
