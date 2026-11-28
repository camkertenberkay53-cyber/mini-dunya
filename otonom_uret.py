"""Otonom üretim adaptörü (Faz-62b) — depo kökünde: motor/orkestrasyon katmanı üretim modüllerini (kurgu, harita,
planlayıcı) içe aktaramaz (Faz-54 mimari kuralı); bu adaptör ikisini birbirine bağlayan tek yerdir.

Akış: konu başlığı → doğrulanmış araştırma → Gemini senaryo + çekim planı →
Commons 2.5D görselleri + harita + 3D → (paralel) render → Piper TTS → FFmpeg kurgu → .mp4.

YouTube'a ya da başka bir yere YÜKLEME YAPMAZ. Mock'a geçmez: anahtar yoksa, Gemini başarısızsa, plan kapıdan geçmezse
açık hata koduyla durur. Korunan modüller (motor/uretim/*, kaos/*) yalnızca ÇAĞRILIR, değiştirilmez.

Akış (alt komutlar; CI'da ayrı işler):
  planla  1) Konu şablonu: motor/uretim/pilotlar/<kimlik>/konu.json (dönemler, harita evreleri). Şablonu olmayan
             konu reddedilir (harita koordinatları ve dönem kitleri olmadan çekim kurulamaz).
          2) Araştırma: Wikipedia TR/EN + OpenAlex keşfi, kaynak doğrulama, havuz (canli_dry_run ile aynı motor).
             Havuzdaki 'dogrulanmis' ve 'tartismali' kayıtlar arastirma.json kartlarına dönüşür (Gemini hafızası
             araştırma sayılmaz). Kart ↔ havuz kimlik eşlemesi kart_eslemesi.json'da tutulur.
          3) 2.5D görseller: Gemini konuya uygun Wikimedia Commons arama sorguları önerir; motor.varlik.
             commons_toplayici indirir (SHA-1 doğrulamalı). Yalnızca CC0 / PD lisanslı görseller kullanılır
             (tarihi_gorsel kapısı: IZINLI_LISANSLAR; insan onayı yok, 'otomatik_toplayici' olarak açıkça işaretli).
          4) Senaryo: motor.uretim.senaryo_uretici.istem (render'ın anladığı niyet sözlüğü) + görsel tür kuralları
             (harita evreleri, toplanan 2.5D görsel kimlikleri, hedef karışım) → GeminiLLMProvider (anahtar başlıkta,
             503 + zaman aşımı yedeği). Yanıt sozlesme.senaryo_denetle + anlati.shorts_denetle kapılarından geçer;
             hatalar geri beslenerek en çok 3 deneme.
          5) motor.uretim.uretim_hatti.planla → cekim_plani.json; 3D çekimler paralel parçalara bölünür (parcalar.json).
  render  Bir parçanın 3D çekimlerini render.render ile çizer (önbellek: ONBELLEK/uretim/<konu>/).
  kurgu   motor.uretim.kurgu.uret: önbellekteki 3D çekimler + harita + 2.5D → TTS → FFmpeg → kalite kontrol → .mp4.

Biçimler: 'shorts' (1080×1920) uçtan uca desteklenir. 'uzun' (16:9, 15–20 dk) bugün DESTEKLENMEZ ve açıkça reddedilir:
motor/uretim/anlati.py Shorts anlatı kurallarını (≤10 cümle) her senaryoya uygular, render.py 3D'yi yalnız
1080×1920 Godot projesinde çizer, uzun kurgu (.srt) bağlanmamıştır — üçü de korunan motor/uretim/ içindedir.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

KOK = Path(__file__).resolve().parent
sys.path.insert(0, str(KOK))
PILOTLAR = KOK / "motor" / "uretim" / "pilotlar"
GORSEL_KOK = KOK / "assets" / "tarihi_gorsel"
IZINLI = ("CC0-1.0", "PD-Old", "PD-Art")
DESTEKLENEN = ("shorts",)
UZUN_ENGELI = ("uzun biçim bugün desteklenmiyor (korunan motor/uretim/ gerektirir): anlati.shorts_denetle her senaryoya "
               "Shorts kurallarını uygular (≤10 cümle, ≤14 kelime); render.py 3D'yi yalnız 1080×1920 Godot projesinde "
               "çizer; uzun kurgu (.srt) bağlı değil. Faz-62c onayı gerekir.")
HEDEF_KARISIM = {"harita": 0.4, "gorsel25d": 0.4, "3d": 0.2}
EN_COK_GORSEL = 8


class UretimHatasi(Exception):
    def __init__(self, asama: str, mesaj: str, kod: int = 1):
        super().__init__(f"{asama}: {mesaj}")
        self.asama, self.kod = asama, kod


def log(asama: str, mesaj: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] [{asama}] {mesaj}", flush=True)


def kisa_ad(metin: str) -> str:
    a = unicodedata.normalize("NFKD", metin.replace("ı", "i").replace("İ", "I")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", a).strip("-")


# ------------------------------------------------------------------ 1) konu şablonu

def sablon_bul(konu: str, pilotlar: Path = PILOTLAR) -> Path:
    """Konu başlığının ilk anlamlı sözcüğü pilot kimliğinin ilk parçasıyla eşleşen şablon klasörü."""
    ilk = kisa_ad(konu).split("-")[0]
    adaylar = sorted(p for p in pilotlar.iterdir() if (p / "konu.json").exists() and p.name.split("-")[0] == ilk)
    if not adaylar:
        mevcut = ", ".join(sorted(p.name for p in pilotlar.iterdir() if (p / "konu.json").exists()))
        raise UretimHatasi("sablon", f"'{konu}' için konu şablonu yok (motor/uretim/pilotlar/<kimlik>/konu.json; "
                                     f"mevcut: {mevcut}). Harita ve dönem kitleri olmadan çekim kurulamaz.", 2)
    return adaylar[0]


def konu_kur(sablon: Path, konu: str, mod: str) -> dict:
    k = json.loads((sablon / "konu.json").read_text())
    k = dict(k, kimlik=f"{k['kimlik']}-oto", format=mod, baslik=konu, hedef_sure_sn=[45, 60])
    k["notlar"] = list(k.get("notlar", [])) + ["Faz-62b otonom üretim: senaryo Gemini, araştırma doğrulanmış havuz, "
                                               "2.5D görseller Commons (CC0/PD, insan onayı yok)."]
    return k


# ------------------------------------------------------------------ 2) araştırma havuzu → kartlar

_GUVEN = {"dogrulanmis": "kesin", "tartismali": "tartismali"}
_KAYNAK_TURU = {"ansiklopedi": "ansiklopedi"}


def kartlar_kur(havuz: dict, konu_kimlik: str, en_cok: int = 30) -> tuple[dict, dict]:
    """(arastirma.json, kart_eslemesi). Yalnızca doğrulanmış / tartışmalı kayıtlar; belirsizler senaryoya girmez."""
    secili = [k for k in havuz["kayitlar"] if k["durum"] in _GUVEN and k.get("kaynaklar")]
    secili.sort(key=lambda k: (k["durum"] != "dogrulanmis", -k.get("bagimsiz_kaynak_sayisi", 0), k["id"]))
    secili = secili[:en_cok]
    kaynak_no: dict[str, str] = {}
    kaynaklar, kartlar, esleme = [], [], {}
    for i, k in enumerate(secili, 1):
        kids = []
        for x in k["kaynaklar"]:
            if x["id"] not in kaynak_no:
                kaynak_no[x["id"]] = f"K{len(kaynak_no) + 1}"
                kaynaklar.append({"id": kaynak_no[x["id"]], "baslik": (x.get("eser") or x["id"])[:200],
                                  "url": x.get("url") or "", "tur": _KAYNAK_TURU.get(x.get("tur"), "ikincil")})
            if kaynak_no[x["id"]] not in kids:
                kids.append(kaynak_no[x["id"]])
        cid = f"C{i}"
        guven = _GUVEN[k["durum"]]
        if guven == "kesin" and len(kids) < 2:   # kurallar/arastirma.yaml: tek kaynaklı iddia en çok 'makul'
            guven = "makul"
        kart = {"id": cid, "iddia": k["iddia"], "guven": guven, "kaynaklar": kids}
        if k.get("tek_kaynak_uyarisi") or k.get("celiski"):
            kart["not"] = "tek kaynak" if k.get("tek_kaynak_uyarisi") else "kaynaklar arasında farklı değer"
        kartlar.append(kart)
        esleme[cid] = {"havuz_id": k["id"], "durum": k["durum"], "kaynak_idleri": [x["id"] for x in k["kaynaklar"]]}
    if not kartlar:
        raise UretimHatasi("arastirma", "havuzda doğrulanmış ya da tartışmalı kayıt yok; senaryo yazılamaz")
    return {"surum": 1, "konu": konu_kimlik, "kaynaklar": kaynaklar, "kartlar": kartlar}, esleme


def havuz_kur(konu: str) -> dict:
    from motor.orkestrasyon import canli_dry_run as cdr
    from motor.orkestrasyon.kaynak_kesif import havuz_olustur
    kesif = cdr._kesif()
    kaynaklar = kesif.kesfet(konu)
    ana = [k for k in kaynaklar if not k.get("aday")]
    if not ana:
        raise UretimHatasi("arastirma", f"'{konu}' için ana kaynak (Wikipedia) bulunamadı; log={kesif.log}")
    oa = cdr._openalex()
    kaynaklar += oa.kesfet(konu, [k["baslik"] for k in ana if k.get("dil") == "en"])
    log("arastirma", f"{len(ana)} ana madde, toplam {len(kaynaklar)} kaynak; doğrulama başlıyor")
    return havuz_olustur(konu, kaynaklar, cdr._dogrulayici(), ilerleme=log)


# ------------------------------------------------------------------ Gemini yardımcıları

def gemini(anahtar: str, sure_butcesi: float):
    from motor.orkestrasyon.gemini import GeminiLLMProvider
    return GeminiLLMProvider(zaman_asimi=90.0, en_cok_tekrar=1, sure_butcesi=sure_butcesi, ilerleme=log,
                             en_az_aralik=1.0, anahtar=anahtar, anahtar_kaynagi="GEMINI_API_KEY")


def json_ayikla(ham: str):
    ham = (ham or "").strip()
    ham = re.sub(r"^```(?:json)?\s*|\s*```$", "", ham)
    try:
        return json.loads(ham)
    except json.JSONDecodeError:
        m = re.search(r"(\{.*\}|\[.*\])", ham, re.S)
        if m:
            return json.loads(m.group(1))
        raise


# ------------------------------------------------------------------ 3) Commons 2.5D görselleri

def gorsel_sorgu_istemi(konu: str, ara: dict, adet: int = EN_COK_GORSEL) -> str:
    iddialar = "\n".join(f"- {c['iddia']}" for c in ara["kartlar"][:12])
    return f"""Konu: "{konu}". Bu belgesel için Wikimedia Commons'ta aranacak tarihî görsel sorguları öner.
Yalnızca kamu malı olması muhtemel eserler: dönem minyatürleri, eski gravürler, tarihî portre resimleri, eski haritalar,
dönem mimarisinin eski fotoğrafları/çizimleri. Modern illüstrasyon, oyun görseli, film karesi İSTEME.
Doğrulanmış bilgiler:
{iddialar}
Yanıt YALNIZCA JSON dizi: en çok {adet} öğe, her öğe {{"gorsel_id": "kısa-kimlik", "sorgu": "İngilizce Commons araması",
"yedek_sorgular": ["…"], "tur": "insan_portre|mimari|cok_figurlu|genel", "aciklama": "Türkçe kısa açıklama (ne görünüyor)"}}.
gorsel_id yalnız küçük harf, rakam ve tire."""


def gorselleri_topla(konu_kimlik: str, sorgular: list[dict], hedef: Path = GORSEL_KOK, topla=None) -> list[dict]:
    """Sorguları indirir; yalnızca IZINLI (CC0/PD) lisanslı ve tarihi_gorsel kapısından geçenleri döndürür."""
    from motor.varlik import commons_toplayici, tarihi_gorsel
    topla = topla or commons_toplayici.topla
    hedef.mkdir(parents=True, exist_ok=True)
    alinan = []
    for i, s in enumerate(sorgular[:EN_COK_GORSEL], 1):
        gid = f"{konu_kimlik}-{kisa_ad(str(s.get('gorsel_id') or i))[:40] or i}"
        s2 = {"gorsel_id": gid, "sorgu": s.get("sorgu"), "yedek_sorgular": list(s.get("yedek_sorgular") or [])[:3],
              "tur": s.get("tur") if s.get("tur") in ("insan_portre", "mimari", "cok_figurlu") else None,
              "en_az_px": 1500, "eser_adi": s.get("aciklama")}
        try:
            k = topla(s2, hedef)
        except Exception as e:   # noqa: BLE001 — tek görselin bulunamaması üretimi durdurmaz; raporlanır
            log("gorsel", f"✗ {gid}: {type(e).__name__}: {str(e)[:160]}")
            continue
        if k.get("lisans_turu") not in IZINLI:
            log("gorsel", f"✗ {gid}: lisans {k.get('lisans_turu')} izinli değil (yalnız {', '.join(IZINLI)}); kullanılmaz")
            for uz in (".jpg", ".png", ".tif", ".json"):
                (hedef / f"{gid}{uz}").unlink(missing_ok=True)
            continue
        try:
            tarihi_gorsel.dogrulanmis_dosya(gid)
        except Exception as e:   # noqa: BLE001
            log("gorsel", f"✗ {gid}: lisans/dosya kapısı: {str(e)[:160]}")
            continue
        alinan.append({"gorsel_id": gid, "aciklama": s.get("aciklama") or k.get("eser_adi"), "lisans": k["lisans_turu"],
                       "kaynak_url": k.get("kaynak_url"), "tur": k.get("gorsel_turu")})
        log("gorsel", f"✓ {gid}: {k['lisans_turu']} {k.get('cozunurluk')} — {k.get('toplama', {}).get('baslik')}")
    return alinan


# ------------------------------------------------------------------ 4) senaryo

def gorsel_kurallari(konu: dict, gorseller: list[dict]) -> str:
    evreler = (konu.get("harita") or {}).get("evreler") or []
    satir = ["GÖRSEL TÜR KURALLARI (zorunlu): niyet.tur yalnızca '3d', 'harita' ya da 'gorsel25d' olabilir."]
    hedef = ", ".join(f"{t} ≈%{int(v * 100)}" for t, v in HEDEF_KARISIM.items())
    satir.append(f"Hedef karışım (cümle sayısına göre): {hedef}. Aynı tür üç cümleden fazla art arda gelmesin.")
    if evreler:
        satir.append("harita niyeti: {\"tur\": \"harita\", \"evre\": <evre kimliği>, \"metin_katmani\": <kısa yazı>} — evreler: "
                     + "; ".join(f"{e['id']} = {e.get('baslik', '')}" for e in evreler))
    else:
        satir.append("Bu konuda harita evresi yok: 'harita' niyeti KULLANMA.")
    if gorseller:
        satir.append("gorsel25d niyeti: {\"tur\": \"gorsel25d\", \"gorsel25d\": {\"gorsel_id\": <kimlik>}, \"aciklama\": "
                     "<görselde ne olduğu, kısa>} (aciklama ZORUNLU) — yalnızca şu "
                     "görseller (anlatılan cümleyle ilgili olanı seç; aynı görseli iki kez kullanma): "
                     + "; ".join(f"{g['gorsel_id']} = {g['aciklama']}" for g in gorseller))
    else:
        satir.append("Kullanılabilir tarihî görsel yok: 'gorsel25d' niyeti KULLANMA.")
    satir.append("3d niyeti yukarıdaki rol/eylem/arazi kurallarına uyar; belirli kişiler temsilî karakterle gösterilir.")
    a, b = konu["hedef_sure_sn"]
    satir.append(f"SÜRE: ölçülen seslendirme toplamı {a}–{b} sn olmalı; bunun için 9–10 cümle, cümle başına 10–14 kelime yaz "
                 f"(kanca hariç: kanca 4–6 kelime).")
    return "\n".join(satir)


def senaryo_denetle(s: dict, ara: dict, konu: dict, gorseller: list[dict], olc=None) -> list[str]:
    from motor.uretim import anlati, seslendirme, sozlesme
    h = sozlesme.senaryo_denetle(s, ara)
    if h:
        return h
    gecerli = {g["gorsel_id"] for g in gorseller}
    evreler = {e["id"] for e in (konu.get("harita") or {}).get("evreler") or []}
    for c in s["cumleler"]:
        n = c["niyet"]
        if n["tur"] == "gorsel25d" and (n.get("gorsel25d") or {}).get("gorsel_id") not in gecerli:
            h.append(f"{c['id']}: gorsel25d.gorsel_id listede yok (geçerli: {sorted(gecerli)})")
        elif n["tur"] == "gorsel25d" and not (n.get("aciklama") or n.get("metin")):
            h.append(f"{c['id']}: gorsel25d niyetinde 'aciklama' zorunlu (çekim metni)")
        if n["tur"] == "harita" and n.get("evre") not in evreler:
            h.append(f"{c['id']}: harita evresi geçersiz (geçerli: {sorted(evreler)})")
        if n["tur"] == "bilgi_karti":
            h.append(f"{c['id']}: bilgi_karti kullanılmaz; 3d, harita ya da gorsel25d seç")
    if h:
        return h
    sureler = (olc or seslendirme.olc)(s["cumleler"])
    hatalar, _ = anlati.shorts_denetle(s, sureler)
    if hatalar:
        return hatalar
    from motor.uretim import sahne_bolucu   # planla ile aynı ölçüm: ölçülen seslendirme + duraklamalar
    toplam = sahne_bolucu.toplam_sure(sahne_bolucu.zaman_cizelgesi(s, sureler))
    a, b = konu["hedef_sure_sn"]
    if not a <= toplam <= b:
        yon = "cümleleri uzat ya da cümle ekle (en çok 10 cümle, cümle başına en çok 14 kelime)" if toplam < a else \
              "cümleleri kısalt ya da cümle çıkar"
        return [f"ölçülen toplam süre {toplam:.1f} sn; hedef {a}–{b} sn: {yon}"]
    return []


def senaryo_uret(saglayici, konu: dict, ara: dict, gorseller: list[dict], deneme: int = 3, olc=None) -> tuple[dict, list[dict]]:
    from motor.uretim import senaryo_uretici
    hatalar: list[str] = []
    gecmis = []
    for d in range(1, deneme + 1):
        istem = senaryo_uretici.istem(konu, ara, hatalar) + "\n" + gorsel_kurallari(konu, gorseller)
        ham = saglayici.tamamla(istem, "senaryo", {"bolum": f"deneme{d}"})
        try:
            s = json_ayikla(ham)
        except (json.JSONDecodeError, TypeError) as e:
            hatalar = [f"yanıt JSON değil: {e}"]
            gecmis.append({"deneme": d, "hatalar": hatalar})
            continue
        if isinstance(s, dict):
            s.setdefault("surum", 1)
            s["konu"] = konu["kimlik"]
            s.setdefault("format", konu["format"])
        hatalar = senaryo_denetle(s, ara, konu, gorseller, olc) if isinstance(s, dict) else ["yanıt nesne değil"]
        gecmis.append({"deneme": d, "hatalar": hatalar[:20]})
        log("senaryo", f"deneme {d}: {len(hatalar)} hata" + (f" — {hatalar[:3]}" if hatalar else ""))
        if not hatalar:
            return s, gecmis
    raise UretimHatasi("senaryo", f"{deneme} denemede kapıdan geçen senaryo üretilemedi: {hatalar[:8]}")


# ------------------------------------------------------------------ 5) çekim planı ve paralel parçalar

def parcalara_bol(plan: dict, parca_sayisi: int) -> list[dict]:
    """3D çekimleri en çok `parca_sayisi` parçaya kare sayısına göre dengeli böler (en uzun işler önce)."""
    uc = sorted((c for c in plan["cekimler"] if c["tur"] == "3d"), key=lambda c: (-c["sure_sn"], c["id"]))
    n = max(1, min(parca_sayisi, len(uc)))
    parcalar = [{"parca": i, "cekimler": [], "sure_sn": 0.0} for i in range(n)]
    for c in uc:
        p = min(parcalar, key=lambda x: (x["sure_sn"], x["parca"]))
        p["cekimler"].append(c["id"])
        p["sure_sn"] = round(p["sure_sn"] + c["sure_sn"], 2)
    return parcalar


def planla(konu: str, mod: str, is_kok: Path, anahtar: str | None, parca_sayisi: int = 4,
           havuz_fn=None, saglayici_fn=None, topla=None, planla_fn=None, olc=None) -> dict:
    if mod not in DESTEKLENEN:
        raise UretimHatasi("bicim", UZUN_ENGELI if mod == "uzun" else f"bilinmeyen biçim: {mod}", 3)
    if not anahtar:
        raise UretimHatasi("anahtar", "GEMINI_API_KEY tanımlı değil; üretim yapılmadı (mock'a geçilmez)", 2)
    from motor.uretim import uretim_hatti
    t0 = time.time()
    sablon = sablon_bul(konu)
    k = konu_kur(sablon, konu, mod)
    is_ = is_kok / k["kimlik"]
    shutil.rmtree(is_, ignore_errors=True)
    is_.mkdir(parents=True)
    r: dict = {"konu": konu, "mod": mod, "kimlik": k["kimlik"], "sablon": sablon.name, "is": str(is_)}
    log("arastirma", f"şablon {sablon.name}; araştırma havuzu kuruluyor")
    havuz = (havuz_fn or havuz_kur)(konu)
    ara, esleme = kartlar_kur(havuz, k["kimlik"])
    r["arastirma"] = {"kayit": len(havuz["kayitlar"]), "kart": len(ara["kartlar"]), "kaynak": len(ara["kaynaklar"]),
                      "kesin": sum(c["guven"] == "kesin" for c in ara["kartlar"]),
                      "makul": sum(c["guven"] == "makul" for c in ara["kartlar"]),
                      "tartismali": sum(c["guven"] == "tartismali" for c in ara["kartlar"])}
    g = (saglayici_fn or (lambda: gemini(anahtar, 420.0)))()
    try:
        sorgular = json_ayikla(g.tamamla(gorsel_sorgu_istemi(konu, ara), "gorsel_sorgu", {}))
    except Exception as e:   # noqa: BLE001 — görsel önerisi alınamazsa 2.5D'siz devam edilir (raporlanır)
        if getattr(e, "sinif", None) == "kota":
            raise UretimHatasi("gemini", f"kota (429): {e}", 4) from e
        log("gorsel", f"görsel sorgusu alınamadı ({type(e).__name__}); 2.5D çekimsiz devam")
        sorgular = []
    gorseller = gorselleri_topla(k["kimlik"], sorgular if isinstance(sorgular, list) else [], topla=topla)
    r["gorseller"] = gorseller
    try:
        sen, gecmis = senaryo_uret(g, k, ara, gorseller, olc=olc)
    except Exception as e:
        if isinstance(e, UretimHatasi):
            raise
        raise UretimHatasi("gemini", f"{getattr(e, 'sinif', type(e).__name__)}: {str(e)[:300]}",
                           4 if getattr(e, "sinif", None) == "kota" else 1) from e
    r["senaryo"] = {"cumle": len(sen["cumleler"]), "denemeler": gecmis,
                    "turler": {t: sum(c["niyet"]["tur"] == t for c in sen["cumleler"]) for t in ("harita", "gorsel25d", "3d")},
                    "gemini_cagri": getattr(g, "cagri_sayisi", None), "model": getattr(g, "kullanilan_model", None)}
    for ad, v in (("konu.json", k), ("arastirma.json", ara), ("senaryo.json", sen), ("kart_eslemesi.json", esleme)):
        (is_ / ad).write_text(json.dumps(v, ensure_ascii=False, indent=1))
    p = (planla_fn or uretim_hatti.planla)(is_)
    r["plan"] = {"gecti": p["gecti"], "toplam_sure_sn": p.get("toplam_sure_sn"),
                 "hatalar": {a: b for a, b in p["hatalar"].items() if b}}
    if not p["gecti"]:
        raise UretimHatasi("plan", f"çekim planı kapıdan geçmedi: {r['plan']['hatalar']}")
    plan = json.loads((is_ / "cekim_plani.json").read_text())
    r["cekimler"] = {t: [c["id"] for c in plan["cekimler"] if c["tur"] == t] for t in ("3d", "harita", "gorsel25d")}
    r["parcalar"] = parcalara_bol(plan, parca_sayisi)
    (is_ / "parcalar.json").write_text(json.dumps(r["parcalar"], ensure_ascii=False))
    r["sure_sn"] = round(time.time() - t0, 1)
    return r


def dogrulama_plani(fikstur: Path, is_kok: Path, parca_sayisi: int = 4, topla=None, planla_fn=None) -> dict:
    """CI doğrulaması (Gemini YOK): pilot şablonun kendi araştırma + senaryosu, fikstürdeki niyet değişiklikleriyle
    (harita, Commons 2.5D) çekim planına dönüşür. Çıktı açıkça 'dogrulama_fiksturu' olarak işaretlenir; üretim değildir."""
    from motor.uretim import uretim_hatti
    f = json.loads(Path(fikstur).read_text())
    sablon = PILOTLAR / f["sablon"]
    k = json.loads((sablon / "konu.json").read_text())
    k = dict(k, kimlik=f"{k['kimlik']}-dogrulama")
    is_ = is_kok / k["kimlik"]
    shutil.rmtree(is_, ignore_errors=True)
    is_.mkdir(parents=True)
    ara = json.loads((sablon / "arastirma.json").read_text())
    sen = json.loads((sablon / "senaryo.json").read_text())
    ara["konu"] = sen["konu"] = k["kimlik"]
    gorseller = gorselleri_topla(k["kimlik"], f.get("gorseller", []), topla=topla)
    degisen = []
    for c in sen["cumleler"]:
        d = (f.get("niyet_degisiklikleri") or {}).get(c["id"])
        if not d:
            continue
        if d["tur"] == "gorsel25d":
            if d["gorsel_sira"] >= len(gorseller):
                log("dogrulama", f"{c['id']}: 2.5D görsel toplanamadı; cümle 3D kalır")
                continue
            g = gorseller[d["gorsel_sira"]]
            c["niyet"] = {"tur": "gorsel25d", "gorsel25d": {"gorsel_id": g["gorsel_id"]}, "aciklama": g["aciklama"]}
        else:
            c["niyet"] = {x: v for x, v in d.items()}
        degisen.append(c["id"])
    for ad, v in (("konu.json", k), ("arastirma.json", ara), ("senaryo.json", sen)):
        (is_ / ad).write_text(json.dumps(v, ensure_ascii=False, indent=1))
    p = (planla_fn or uretim_hatti.planla)(is_)
    r = {"dogrulama_fiksturu": True, "kimlik": k["kimlik"], "is": str(is_), "gorseller": gorseller, "degisen": degisen,
         "plan": {"gecti": p["gecti"], "toplam_sure_sn": p.get("toplam_sure_sn"),
                  "hatalar": {a: b for a, b in p["hatalar"].items() if b}}}
    if not p["gecti"]:
        raise UretimHatasi("plan", f"doğrulama planı kapıdan geçmedi: {r['plan']['hatalar']}")
    plan = json.loads((is_ / "cekim_plani.json").read_text())
    r["cekimler"] = {t: [c["id"] for c in plan["cekimler"] if c["tur"] == t] for t in ("3d", "harita", "gorsel25d")}
    r["parcalar"] = parcalara_bol(plan, parca_sayisi)
    (is_ / "parcalar.json").write_text(json.dumps(r["parcalar"], ensure_ascii=False))
    return r


# ------------------------------------------------------------------ render / kurgu

def parca_render(is_: Path, parca: int) -> dict:
    from motor.uretim import render
    parcalar = json.loads((is_ / "parcalar.json").read_text())
    ids = next((p["cekimler"] for p in parcalar if p["parca"] == parca), [])
    sonuc = {}
    for cid in ids:
        t = time.time()
        o = render.render(str(is_ / "cekim_plani.json"), cid)
        sonuc[cid] = {"durum": o.get("durum"), "sure_sn": round(time.time() - t, 1), "onbellekten": o.get("onbellekten", False)}
        log("render", f"{cid}: {o.get('durum')} ({sonuc[cid]['sure_sn']} sn)")
        if o.get("durum") != "TAMAM":
            raise UretimHatasi("render", f"{cid}: {o.get('durum')} {str(o.get('neden') or o.get('hatalar'))[:300]}")
    return {"parca": parca, "cekimler": sonuc, "gecti": True}


def ffprobe(yol: Path) -> dict:
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration,size:stream=codec_type,width,height",
                        "-of", "json", str(yol)], capture_output=True, text=True, check=True)
    d = json.loads(p.stdout)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), {})
    return {"sure_sn": round(float(d["format"]["duration"]), 2), "boyut_mb": round(int(d["format"]["size"]) / 1e6, 2),
            "cozunurluk": [v.get("width"), v.get("height")], "ses": any(s["codec_type"] == "audio" for s in d["streams"])}


def kurgu_yap(is_: Path, cikti: Path) -> dict:
    from motor import ayar
    from motor.uretim import kurgu
    t = time.time()
    k = kurgu.uret(is_)
    konu = json.loads((is_ / "konu.json").read_text())["kimlik"]
    r = {"durum": k.get("durum"), "sure_sn": round(time.time() - t, 1),
         "onbellekten_3d": sum(1 for c in k.get("cekimler", []) if c.get("onbellekten")),
         **{x: k[x] for x in ("hatalar", "cekim", "render", "olculen", "kalite_kontrol") if x in k}}
    mp4 = ayar.ONBELLEK / "kurgu" / konu / f"{konu}.mp4"
    if mp4.exists():
        cikti.mkdir(parents=True, exist_ok=True)
        hedef = cikti / f"{konu}.mp4"
        shutil.copy2(mp4, hedef)
        for ek in ("uretim_raporu.json", "altyazi.json"):
            if (mp4.parent / ek).exists():
                shutil.copy2(mp4.parent / ek, cikti / ek)
        r["mp4"] = {"yol": str(hedef), **ffprobe(hedef)}
    r["gecti"] = bool(r.get("mp4")) and k.get("durum") == "TAMAM"
    return r


# ------------------------------------------------------------------ CLI

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Faz-62b otonom üretim (yükleme yapmaz)")
    ap.add_argument("komut", choices=("planla", "dogrula", "render", "kurgu"))
    ap.add_argument("--fikstur", help="dogrula: CI doğrulama fikstürü (Gemini kullanılmaz)")
    ap.add_argument("--konu")
    ap.add_argument("--mod", default="shorts")
    ap.add_argument("--is", dest="is_kok", default="/tmp/otonom_is")
    ap.add_argument("--kimlik", help="render/kurgu: planla çıktısındaki konu kimliği")
    ap.add_argument("--parca", type=int, default=0)
    ap.add_argument("--parca-sayisi", type=int, default=4)
    ap.add_argument("--cikti", default="/tmp/otonom_cikti")
    a = ap.parse_args(argv)
    cikti = Path(a.cikti)
    cikti.mkdir(parents=True, exist_ok=True)
    rapor_yolu = cikti / f"otonom_{a.komut}{'_' + str(a.parca) if a.komut == 'render' else ''}.json"
    try:
        if a.komut in ("planla", "dogrula"):
            if a.komut == "planla":
                if not a.konu:
                    raise UretimHatasi("arguman", "--konu gerekli", 3)
                r = planla(a.konu, a.mod, Path(a.is_kok), (os.environ.get("GEMINI_API_KEY") or "").strip() or None,
                           a.parca_sayisi)
            else:
                r = dogrulama_plani(Path(a.fikstur), Path(a.is_kok), a.parca_sayisi)
            gh = os.environ.get("GITHUB_OUTPUT")
            if gh:
                with open(gh, "a") as f:
                    f.write(f"kimlik={r['kimlik']}\nparcalar={json.dumps([p['parca'] for p in r['parcalar']])}\n")
        elif a.komut == "render":
            r = parca_render(Path(a.is_kok) / a.kimlik, a.parca)
        else:
            r = kurgu_yap(Path(a.is_kok) / a.kimlik, cikti / "video")
        kod = 0 if r.get("gecti", True) else 1
    except UretimHatasi as e:
        r, kod = {"gecti": False, "asama": e.asama, "hata": str(e)}, e.kod
        log(e.asama, f"DURDU: {e}")
    rapor_yolu.write_text(json.dumps(r, ensure_ascii=False, indent=1))
    print(json.dumps(r, ensure_ascii=False, indent=1)[:8000])
    return kod


if __name__ == "__main__":
    sys.exit(main())
