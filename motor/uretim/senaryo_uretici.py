"""Senaryo üretimi (M3a, Shorts): araştırma kartlarından, kurallara uyan senaryo isteyen istem (prompt) kurar,
yanıtı aynı denetimlerden geçirir, hataları geri besleyerek en çok 3 kez yeniden ister.

Model: eski botun ücretsiz Gemini çağrısı (kaos/writer.gemini_json). GEMINI_API_KEY yoksa çalışmaz ve bunu açıkça
söyler; sessizce şablon metin üretmez. Üretilen senaryo kullanıcı onayına gider (ilk 20 video kuralı).
"""
from __future__ import annotations

import json
import os

from motor.uretim import anlati, sozlesme, veri


def istem(konu: dict, arastirma: dict, hatalar: list[str] | None = None) -> str:
    k = veri.kural("shorts")
    kartlar = "\n".join(f"- {c['id']} [{c['guven']}]: {c['iddia']}" for c in arastirma["kartlar"])
    roller = sorted({t["rol"] for t in veri.takimlar().values()})
    eylemler = sorted({e for a in veri.kural("animasyon")["animasyonlar"].values() for e in a.get("eylemler", [])})
    araziler = sorted(veri.kural("arazi")["araziler"])
    metin = f"""Türkçe bir YouTube Shorts tarih senaryosu yaz. Konu: {konu['baslik']} — {konu['ozet']}
Hedef süre: {konu['hedef_sure_sn'][0]}-{konu['hedef_sure_sn'][1]} saniye. Tek bir ana fikir. Gereksiz bilgi yok.
Kurallar:
- İlk cümle KANCA: en çok {k['kanca']['en_cok_sure_sn']} saniyede okunur (4-6 kelime); sayı, soru ya da sıradışılık taşır.
- Cümle amaçları bu sırayı izler: {', '.join(k['amac_sirasi'])}. Son cümle 'final'.
- En çok {k['cumle']['en_cok']} cümle, cümle başına en çok {k['cumle']['en_cok_kelime']} kelime.
- Her olgusal cümle yalnızca aşağıdaki kartlara dayanır (kartlar alanına kimliklerini yaz). Kartta olmayan bilgi YAZMA.
- 'belirsiz' ya da 'tartismali' karta dayanan cümle temkinli dille yazılır ({', '.join(veri.kural('dil_tr')['temkin_ifadeleri'][:5])}...).
- Her cümleye bir görsel niyet ver. Yalnızca şunları kullan: roller {roller}; eylemler {eylemler}; araziler {araziler};
  mesafe yalnızca 'orta' ya da 'uzak' (yakın plan yasak). Gösterilemeyecek şey (eldeki varlıklarda olmayan) için 3D niyet yazma.
Kartlar:
{kartlar}
Yanıt yalnızca senaryo.schema.json biçiminde JSON olsun."""
    if hatalar:
        metin += "\nÖnceki denemenin hataları (düzelt):\n" + "\n".join(f"- {h}" for h in hatalar[:20])
    return metin


def uret(konu: dict, arastirma: dict, cfg: dict, deneme: int = 3) -> tuple[dict | None, list[str]]:
    if not os.environ.get("GEMINI_API_KEY"):
        return None, ["GEMINI_API_KEY tanımlı değil: otomatik senaryo üretimi bu ortamda çalıştırılamaz"]
    from kaos.writer import gemini_json
    hatalar: list[str] = []
    for _ in range(deneme):
        s = gemini_json(istem(konu, arastirma, hatalar), cfg, temperature=0.8)
        hatalar = sozlesme.senaryo_denetle(s, arastirma)
        if not hatalar:
            from motor.uretim import seslendirme
            hatalar, _ = anlati.shorts_denetle(s, seslendirme.olc(s["cumleler"]))
        if not hatalar:
            return s, []
    return None, hatalar


if __name__ == "__main__":
    import sys
    from pathlib import Path
    k = Path(sys.argv[1])
    print(istem(json.loads((k / "konu.json").read_text()), json.loads((k / "arastirma.json").read_text())))
