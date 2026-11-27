"""Faz-56 canlı kontrol (bilgi; Gemini YOK): TDV İslam Ansiklopedisi PDF'lerinde normalizasyon öncesi/sonrası doğrulama.

python3 -u deneyler/faz56/tdv_pdf_kontrol.py
Run 45956710301'de bu PDF'ler okunduğu halde hiçbir iddiayı doğrulayamamıştı (satır satır pencere hatası).
Telif: loga yalnız kısa alıntılar (≤160 karakter) yazılır.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from motor.orkestrasyon import kaynak_dogrulayici as kd  # noqa: E402

PDFLER = ["https://cdn.islamansiklopedisi.org.tr/dosya/34/C34011006.pdf",
          "https://cdn2.islamansiklopedisi.org.tr/dosya/34/C34011007.pdf"]
OLAY = ["Otlukbeli"]
IDDIALAR = [
    "Otlukbeli Savaşı 11 Ağustos 1473 tarihinde Fatih Sultan Mehmed ile Uzun Hasan arasında yapıldı.",
    "Otlukbeli Savaşı 1473 yılında Osmanlılar ile Akkoyunlular arasında yapıldı.",
    "Uzun Hasan Otlukbeli Savaşı'nda yenildi.",
]


def main() -> int:
    d = kd.KaynakDogrulayici(kd.GuvenliIstemci(zaman_asimi=15.0, en_cok_bayt=kd.PDF_EN_COK_BAYT))
    ozet = []
    for url in PDFLER:
        sinif, kod, metin, neden = d.sayfa(url)
        e = d.erisim.get(url, {})
        print(f"=== {kd.url_gizle(url)}: durum={sinif} http={kod} neden_kodu={e.get('neden_kodu')} pdf={e.get('pdf')}", flush=True)
        if sinif != "ok":
            ozet.append({"url": kd.url_gizle(url), "erisim": e})
            continue
        ham = d.ham_metin.get(url, "")
        i = max(0, ham.find("1473") - 60)
        print("  HAM  (önce) :", repr(ham[i:i + 160]))
        j = max(0, metin.find("1473") - 60)
        print("  NORM (sonra):", repr(metin[j:j + 160]))
        for iddia in IDDIALAR:
            q = {"metin": iddia, "olay_terimleri": OLAY}
            eski = kd.icerik_dogrula(ham.replace("\f", "\n"), q)   # eski davranış: satır satır pencere
            yeni = kd.icerik_dogrula(metin, q)
            print(f"  · {iddia[:70]}…\n      önce: {eski['destek_sinifi']:<11} sonra: {yeni['destek_sinifi']:<11} "
                  f"atomlar={yeni['atomlar']} alıntı={yeni['supporting_excerpt'][:120]!r}")
            ozet.append({"url": kd.url_gizle(url), "iddia": iddia, "once": eski["destek_sinifi"], "sonra": yeni["destek_sinifi"]})
    print("OZET_JSON", json.dumps(ozet, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
