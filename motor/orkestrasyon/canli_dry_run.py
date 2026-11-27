"""Canlı uçtan uca dry-run: Kaynak Keşfi → Canlı Kaynak Doğrulama → Gemini Senaryo/Sahne Planı → Validation Gate.

python3 -u -m motor.orkestrasyon.canli_dry_run "<konu>" [--mod uzun,shorts] [--cikti klasor]

- Her alt aşama (`kaynak_kesif`, `kaynak_dogrulama`, `gemini_cagri`, `onay_kapisi`) zaman damgalı ilerleme satırı
  yazar. `-u` ile tamponsuz çalıştırıldığında adımın nerede beklediği canlı görünür.
- Keşif ve doğrulama bir kez yapılır; uzun ve Shorts aynı doğrulanmış havuzu kullanır.
- Süre korumaları:
  - Sayfa isteği başına 8 sn, sayfalar paralel getirilir.
  - Gemini isteği başına en çok 90 sn, düşünme bütçesi sınırlı.
  - Moda göre toplam Gemini süre bütçesi var.
  - Uzun mod bölüm bölüm paralel üretilir.
- Ağ yoksa ya da keşif sonuç vermezse bunu açıkça raporlar (çıkış 3).
- Anahtar seçimi (YALNIZCA bu dry-run'da): önce `GEMINI_DRYRUN_KEY` (bot.yml'nin kotasından ayrı), yoksa
  `GEMINI_API_KEY`. İkisi de yoksa Gemini adımı ATLANIR ve rapor bunu açıkça söyler; mock'a GEÇİLMEZ.
  Raporda yalnızca anahtarın KAYNAK ADI yazılır; değeri hiçbir loga ya da çıktıya yazılmaz.
- 429 (kota) alınırsa üretim kontrollü durur ve kalan modlar için Gemini çağrılmaz (gereksiz istek yok).
- Render başlatılmaz (dry-run). Anahtar hiçbir çıktıya yazılmaz.
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

from motor.orkestrasyon.gemini import GercekUretimHatasi, GeminiLLMProvider
from motor.orkestrasyon.kaynak_dogrulayici import GuvenliIstemci, KaynakDogrulayici, url_gizle
from motor.orkestrasyon.kaynak_kesif import OpenAlexKesif, WikipediaKesif, havuz_olustur
from motor.orkestrasyon.senaryo_planlayici import plan_uret

SURE_BUTCESI = {"uzun": 150.0, "shorts": 75.0}
ANAHTAR_SIRASI = ("GEMINI_DRYRUN_KEY", "GEMINI_API_KEY")


def dryrun_anahtari_sec(ortam=None) -> tuple[str | None, str | None]:
    """(anahtar, kaynak_adi). Önce GEMINI_DRYRUN_KEY, yoksa GEMINI_API_KEY. Boş/yalnız boşluk değer yok sayılır."""
    ortam = os.environ if ortam is None else ortam
    for ad in ANAHTAR_SIRASI:
        deger = (ortam.get(ad) or "").strip()
        if deger:
            return deger, ad
    return None, None


def _maskele(metin: str, ortam=None) -> str:
    """Çıktıya yazılmadan önce son güvence: ortamdaki bütün gizli anahtar değerleri maskelenir."""
    ortam = os.environ if ortam is None else ortam
    for ad in ANAHTAR_SIRASI + ("OPENALEX_API_KEY",):
        d = (ortam.get(ad) or "").strip()
        if len(d) >= 8:
            metin = metin.replace(d, "***")
    return metin   # Gemini duvar saati (sn); aşılırsa açık hata, asılı kalma yok
_T0 = time.monotonic()


def log(asama: str, mesaj: str) -> None:
    print(_maskele(f"[{time.strftime('%H:%M:%S')} +{time.monotonic() - _T0:6.1f}s] {asama}: {mesaj}"), flush=True)


def _kesif():
    return WikipediaKesif(GuvenliIstemci(zaman_asimi=8.0))


def _openalex():
    return OpenAlexKesif(GuvenliIstemci(zaman_asimi=10.0))


def _dogrulayici():
    return KaynakDogrulayici(GuvenliIstemci(zaman_asimi=8.0, en_cok_bayt=3 * 1024 * 1024), bekleme_tavani=4.0)


def calistir(konu: str, mod: str | list[str] = "uzun") -> dict:
    modlar = [mod] if isinstance(mod, str) else list(mod)
    t0 = time.time()
    r = {"konu": konu, "modlar": modlar, "asamalar": {}, "planlar": {}}
    log("kaynak_kesif", f"'{konu}' için Wikipedia TR/EN keşfi başlıyor")
    kesif = _kesif()
    kaynaklar = kesif.kesfet(konu)
    ana = [k for k in kaynaklar if not k.get("aday")]
    log("kaynak_kesif", f"{len(ana)} ana madde, {sum(1 for k in kaynaklar if k.get('aday'))} aday dış kaynak; log={kesif.log}")
    # bağımsız ikinci küme: OpenAlex (EN madde başlığı ipucu olarak)
    oa = _openalex()
    ipucu = [k["baslik"] for k in ana if k.get("dil") == "en"]
    oa_k = oa.kesfet(konu, ipucu)
    kaynaklar += oa_k
    log("kaynak_kesif", f"OpenAlex: {sum(1 for k in oa_k if k.get('api_metni'))} özetli yayın, "
                        f"{sum(1 for k in oa_k if not k.get('api_metni'))} diğer/PDF aday; log={oa.log}; "
                        f"anahtar={'var' if os.environ.get('OPENALEX_API_KEY') else 'yok (anahtarsız bütçe küçük)'}")
    r["asamalar"]["1_kesif"] = {"ana_madde": [{"id": k["id"], "url": url_gizle(k["url"]), "baslik": k["baslik"],
                                                "bolum_sayisi": len(k.get("bolumler", [])), "metin_karakter": len(k.get("metin") or "")}
                                               for k in ana],
                                "aday_dis_kaynak": Counter(k["tur"] for k in kaynaklar if k.get("aday")), "log": kesif.log,
                                "openalex": [{"id": k["id"], "baslik": k["baslik"][:120], "yayinci": k["yayinci"],
                                              "ozet": bool(k.get("api_metni"))} for k in oa_k]}
    if not ana:
        r["durum"] = "kesif_basarisiz"
        r["sure_sn"] = round(time.time() - t0, 1)
        return r
    havuz = havuz_olustur(konu, kaynaklar, _dogrulayici(), ilerleme=log)
    kay = havuz["kayitlar"]
    r["asamalar"]["2_dogrulama"] = {
        "kaynak_raporu": havuz["kaynak_raporu"], "bagimsiz_kume_sayisi": havuz["kume_sayisi"],
        "kayit_sayisi": len(kay), "durumlar": Counter(k["durum"] for k in kay), "turler": Counter(k["tur"] for k in kay),
        "tek_kaynak_uyarisi": sum(k["tek_kaynak_uyarisi"] for k in kay),
        "celiskiler": [{"id": k["id"], "celiski": k["celiski"], "iddia": k["iddia"][:200]} for k in kay if k.get("celiski")],
        "ornek_dogrulanmis": [{"id": k["id"], "iddia": k["iddia"][:200], "kaynaklar": [x["id"] for x in k["kaynaklar"]],
                               "excerpt": k["kaynaklar"][0]["dogrulama"]["supporting_excerpt"][:200]}
                              for k in kay if k["durum"] == "dogrulanmis"][:6]}
    anahtar, kaynak = dryrun_anahtari_sec()
    r["gemini_anahtar_kaynagi"] = kaynak
    if not anahtar:
        log("gemini_cagri", "GEMINI_DRYRUN_KEY ve GEMINI_API_KEY yok: Gemini adımı atlandı (mock'a geçilmedi)")
        r["asamalar"]["3_gemini"] = {"durum": "atlandi",
                                     "neden": "GEMINI_DRYRUN_KEY / GEMINI_API_KEY tanımlı değil (mock'a geçilmedi)"}
        r["durum"] = "gemini_atlandi"
        r["sure_sn"] = round(time.time() - t0, 1)
        return r
    log("gemini_cagri", f"anahtar kaynağı: {kaynak}" + ("" if kaynak == "GEMINI_DRYRUN_KEY" else
                                                       " (bot.yml ile aynı kota paylaşılıyor)"))
    durumlar, kota_doldu = [], False
    for m in modlar:
        if kota_doldu:   # 429 sonrası gereksiz Gemini çağrısı yapılmaz
            r["asamalar"][f"3_gemini_{m}"] = {"durum": "atlandi_kota", "neden": "önceki modda Gemini kotası aşıldı (429)"}
            durumlar.append("gemini_kota")
            log("onay_kapisi", f"--- mod={m} atlandı: kota (429) önceki modda doldu")
            continue
        log("gemini_cagri", f"--- mod={m} başlıyor (süre bütçesi {SURE_BUTCESI[m]:.0f} sn, istek başı ≤90 sn"
                            f"{', bölüm bölüm paralel' if m == 'uzun' else ''})")
        tm = time.time()
        try:
            # kota dostu: uzun mod 3 parça (anlatı 3 + plan 3 istek), istek başlangıçları arası ≥3 sn
            g = GeminiLLMProvider(zaman_asimi=90.0, en_cok_tekrar=1, sure_butcesi=SURE_BUTCESI[m], ilerleme=log,
                                  en_az_aralik=3.0, anahtar=anahtar, anahtar_kaynagi=kaynak)
            p = plan_uret(konu, m, g, arastirma=havuz, parcali=(m == "uzun"), ilerleme=log, paralel=3)
            ozet = {"durum": p["durum"], "model": g.kullanilan_model, "gemini_cagri": g.cagri_sayisi,
                    "sure_sn": round(time.time() - tm, 1),
                    "katmanlar": {k: [{"deneme": d["deneme"], "tur": d["tur"], "hata_sayisi": len(d["hatalar"]),
                                       "hata_kodlari": dict(Counter(h["kod"] for h in d["hatalar"]))} for d in v.get("denemeler", [])]
                                  for k, v in p["katmanlar"].items() if isinstance(v, dict) and "denemeler" in v},
                    "ozet": p.get("ozet"), "uyarilar": p.get("uyarilar"), "ozet_hata": p.get("ozet_hata"),
                    "hatalar_ilk20": (p.get("hatalar") or [])[:20], "render_baslatildi": p["render_baslatildi"]}
            if p["durum"] == "uretime_hazir":
                r["planlar"][m] = p["plan"]
                ozet["ilk_sahneler"] = p["plan"]["sahneler"][:4]
                ozet["guven_durumlari"] = Counter(s["guven_durumu"] for s in p["plan"]["sahneler"])
            ozet["gemini_hatalari"] = g.hatalar[-20:]
            sinif = next((h.get("sinif") for h in (p.get("hatalar") or []) if h.get("kod") == "saglayici_hatasi"), None)
            if sinif == "kota":
                kota_doldu = True
                ozet["durum"] = p["durum"] = "gemini_kota"
            durumlar.append(p["durum"])
        except GercekUretimHatasi as e:
            ozet = {"durum": "gemini_kota" if e.sinif == "kota" else "gemini_basarisiz", "sinif": e.sinif,
                    "hata": str(e)[:600], "gemini_hatalari": e.hatalar[-20:], "sure_sn": round(time.time() - tm, 1)}
            kota_doldu = kota_doldu or e.sinif == "kota"
            durumlar.append(ozet["durum"])
        log("onay_kapisi", f"--- mod={m} bitti: {ozet['durum']} ({ozet['sure_sn']} sn)"
                           f"{' — ' + ozet['ozet_hata'] if ozet.get('ozet_hata') else ''}")
        r["asamalar"][f"3_gemini_{m}"] = ozet
    r["durum"] = ("uretime_hazir" if all(d == "uretime_hazir" for d in durumlar) else
                  "gemini_kota" if "gemini_kota" in durumlar else
                  "gemini_basarisiz" if "gemini_basarisiz" in durumlar else "durduruldu")
    r["sure_sn"] = round(time.time() - t0, 1)
    return r


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    konu = argv[0]
    modlar = (argv[argv.index("--mod") + 1] if "--mod" in argv else "uzun").split(",")
    r = calistir(konu, modlar)
    if "--cikti" in argv:
        k = Path(argv[argv.index("--cikti") + 1])
        k.mkdir(parents=True, exist_ok=True)
        (k / "dry_run.json").write_text(_maskele(json.dumps(r, ensure_ascii=False, indent=1, default=list)))
    ozet = {k: v for k, v in r.items() if k != "planlar"}
    print(_maskele(json.dumps(ozet, ensure_ascii=False, indent=1, default=dict))[:60000], flush=True)
    log("ozet", f"durum={r['durum']} toplam {r['sure_sn']} sn")
    if r["durum"] == "gemini_kota":
        log("ozet", "KOTA: Gemini 429 döndü; tekrar denenmedi. Kota sıfırlandıktan sonra elle yeniden tetikleyin "
                    "(ayrı GEMINI_DRYRUN_KEY bot.yml kotasından bağımsızdır).")
    return {"uretime_hazir": 0, "gemini_atlandi": 0, "durduruldu": 1, "gemini_basarisiz": 1, "gemini_kota": 4}.get(r["durum"], 3)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
