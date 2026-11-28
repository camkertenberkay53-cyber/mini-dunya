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
          3) 2.5D görseller (Faz-62d): Gemini sahne konularına göre (uzunda bölüm taslağından) alt konu sorguları
             üretir (kişiler, ordular, silahlar, mekân/harita, dönem sanatı); motor.varlik.commons_toplayici indirir
             (SHA-1 doğrulamalı; daha önce seçilen dosya hariç tutulur). Lisans: CC0 / PD ya da atıflı CC-BY / CC-BY-SA
             (yazar, lisans, kaynak metadata'da; insan onayı yok, 'otomatik_toplayici' olarak açıkça işaretli).
             Bir görsel bir videoda en çok bir kez; en az 3 (Shorts) / 12 (uzun) benzersiz görsel yoksa üretim durur.
          4) Senaryo: motor.uretim.senaryo_uretici.istem (render'ın anladığı niyet sözlüğü) + görsel tür kuralları
             (harita evreleri, toplanan 2.5D görsel kimlikleri, hedef karışım) → GeminiLLMProvider (anahtar başlıkta,
             503 + zaman aşımı yedeği). Yanıt sozlesme.senaryo_denetle + anlati.shorts_denetle kapılarından geçer;
             hatalar geri beslenerek en çok 3 deneme.
          5) motor.uretim.uretim_hatti.planla → cekim_plani.json; 3D çekimler paralel parçalara bölünür (parcalar.json).
  render  Bir parçanın 3D çekimlerini render.render ile çizer (önbellek: ONBELLEK/uretim/<konu>/).
  kurgu   motor.uretim.kurgu.uret: önbellekteki 3D çekimler + harita + 2.5D → TTS → FFmpeg → kalite kontrol → .mp4.

Biçimler (Faz-62c): 'shorts' (1080×1920, ≤10 cümle; davranışı Faz-62b ile aynı), 'uzun' (1920×1080, 15–20 dk,
6–8 bölüm, bölüm bölüm Gemini + gerçek TTS süre kapısı) ve 'her_ikisi' (aynı araştırma havuzu ve aynı Commons görselleri
iki senaryoya da girer; Gemini görsel sorgusu bir kez yapılır).
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
IZINLI = ("CC0-1.0", "PD-Old", "PD-Art")            # atıf istemeyen
# Faz-62d: CC-BY-x ve CC-BY-SA-x — atıf (yazar, lisans, kaynak) zorunlu; CC-BY-NC / CC-BY-ND kabul edilmez
EN_AZ_GORSEL = {"shorts": 3, "uzun": 12}         # Faz-62d: render'a geçmeden indirilmiş + kullanılmış benzersiz görsel
MODLAR = {"shorts": ("shorts",), "uzun": ("uzun",), "her_ikisi": ("shorts", "uzun")}
HEDEF_KARISIM = {"harita": 0.4, "gorsel25d": 0.4, "3d": 0.2}
EN_COK_GORSEL = 12
# Faz-62c uzun belgesel
UZUN_HEDEF_SN = [900, 1200]          # 15–20 dk (gerçek TTS zaman çizelgesi)
UZUN_PLAN_SN = 1050                  # bölüm hedeflerinin toplamı (aralığın ortası)
UZUN_KART = 80                       # uzun anlatı daha çok doğrulanmış bilgi ister (Shorts 30 kartla aynı kalır)
EN_COK_GORSEL_UZUN = 48
EN_COK_GEMINI_CAGRI = 32             # uzun senaryo için toplam çağrı tavanı (sonsuz yeniden deneme yok)
KELIME_HIZI = 2.3                    # ilk bölüm için kelime/sn tahmini; sonra ölçülen TTS'den güncellenir
HAREKETLER = ("zoom_in", "zoom_out", "push_in", "pull_back", "pan_sol", "pan_sag", "pan_yukari", "pan_asagi", "capraz", "sabit")
GORSEL_EN_COK_KULLANIM = 1          # Faz-62d: bir görsel dosyası bir videoda en çok bir kez


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
    if mod == "uzun":
        return dict(k, kimlik=f"{k['kimlik']}-oto-uzun", format="uzun", baslik=konu, hedef_sure_sn=list(UZUN_HEDEF_SN),
                    notlar=list(k.get("notlar", [])) + ["Faz-62c otonom uzun belgesel: bölüm bölüm Gemini senaryo, "
                                                        "doğrulanmış havuz, Commons CC0/PD görseller, sınırlı 3D."])
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


# ------------------------------------------------------------------ Faz-63: yapılandırılmış çıktı + normalizasyon

# Gemini responseJsonSchema'nın desteklediği JSON Schema anahtarları (REST GenerationConfig). Diğerleri (pattern,
# minLength, default, $schema, $defs...) gönderilmez; $ref'ler açılır, const → enum, oneOf → anyOf.
API_SEMA_ANAHTARLARI = {"type", "format", "title", "description", "enum", "items", "prefixItems", "minItems", "maxItems",
                        "minimum", "maximum", "anyOf", "properties", "additionalProperties", "required"}


def api_semasi(sema, tanimlar: dict | None = None):
    """Yerel JSON Schema → Gemini'nin kabul ettiği alt küme. Yerel şema değişmez (kopya döner); yerel doğrulama
    (sozlesme) tam şemayla yine çalışır — API şeması yalnız yapısal güvencedir."""
    if tanimlar is None:
        tanimlar = sema.get("$defs", {}) if isinstance(sema, dict) else {}
    if isinstance(sema, list):
        return [api_semasi(x, tanimlar) for x in sema]
    if not isinstance(sema, dict):
        return sema
    if "$ref" in sema:
        return api_semasi(tanimlar[sema["$ref"].rsplit("/", 1)[-1]], tanimlar)
    cikti = {}
    for k, v in sema.items():
        if k == "const":
            cikti["enum"] = [v]
            continue
        k = "anyOf" if k == "oneOf" else k
        if k not in API_SEMA_ANAHTARLARI:
            continue
        if k == "properties":
            cikti[k] = {ad: api_semasi(x, tanimlar) for ad, x in v.items()}
        elif k in ("items", "additionalProperties", "anyOf", "prefixItems"):
            cikti[k] = api_semasi(v, tanimlar)
        else:
            cikti[k] = v
    return cikti


def shorts_api_semasi() -> dict:
    """Shorts senaryo şeması (motor/uretim/semalar/senaryo.schema.json — yalnız OKUNUR) → API alt kümesi."""
    from motor.uretim import sozlesme
    return api_semasi(sozlesme.sema("senaryo"))


def _nesne(ozellik: dict, zorunlu: list[str]) -> dict:
    return {"type": "object", "properties": ozellik, "required": zorunlu, "additionalProperties": False}


_S = {"type": "string"}
TASLAK_API_SEMASI = _nesne({
    "baslik": _S,
    "bolumler": {"type": "array", "minItems": 1, "items": _nesne({
        "baslik": _S,
        "roller": {"type": "array", "minItems": 1, "items": {"type": "string", "enum": [
            "kanca", "baglam", "taraflar", "savas_oncesi", "savas", "sonuc", "etkiler", "kapanis"]}},
        "ozet": _S, "kartlar": {"type": "array", "items": _S}, "hedef_sn": {"type": "number"}},
        ["baslik", "roller", "ozet", "kartlar", "hedef_sn"])}}, ["baslik", "bolumler"])
BOLUM_API_SEMASI = _nesne({"cumleler": {"type": "array", "minItems": 1, "items": _nesne({
    "metin": _S, "kartlar": {"type": "array", "items": _S}, "olgusal": {"type": "boolean"}, "okunus": _S,
    "niyet": _nesne({"tur": {"type": "string", "enum": ["harita", "gorsel25d", "3d"]}, "evre": _S, "metin": _S,
                     "metin_katmani": _S, "gorsel_id": _S, "aciklama": _S,
                     "hareket": {"type": "string", "enum": list(HAREKETLER)}, "katalog": _S}, ["tur"])},
    ["metin", "kartlar", "olgusal", "niyet"])}}, ["cumleler"])

SARMALAYICI = "senaryo"
_ID_DESEN = re.compile(r"^S(\d+)$")   # senaryo.schema.json cumleler[].id deseni: ^S[0-9]+$


_GECERLI_ID = re.compile(r"^S[0-9]+$")            # senaryo.schema.json cumleler[].id deseni
_DONUSEBILIR_ID = re.compile(r"^[sScC]([0-9]+)$")   # Faz-63d: s1 / c1 / C1 → S1 (S1 zaten geçerli)
_RAKAM_ID = re.compile(r"^[0-9]+$")                 # "12" → S12


def id_adayi(i) -> str | None:
    """Tanımlı ve güvenli kimlik biçimlerinin S<n> karşılığı; bilinmeyen/bozuk biçim için None (dönüştürülmez).
    Kabul: s<n>, c<n>, C<n> (n rakam), rakamlı metin "<n>", negatif olmayan tam sayı <n>. Rakamlar aynen korunur
    (c08 → S08). Reddedilen örnekler: 'abc', 'S-1', '', ' s3', 's1a', 1.0, True, -1."""
    if isinstance(i, bool):
        return None
    if isinstance(i, int):
        return f"S{i}" if i >= 0 else None
    if not isinstance(i, str):
        return None
    m = _DONUSEBILIR_ID.match(i)
    if m:
        return f"S{m.group(1)}"
    return f"S{i}" if _RAKAM_ID.match(i) else None


def normalize_senaryo(veri, kanca_final: bool = True):
    """Şema doğrulamasından hemen önce deterministik normalizasyon (kopya döner; girdi değişmez):
    - dict değilse aynen döner (doğrulayıcı açık hata verir).
    - Kökte YALNIZCA 'senaryo' anahtarı varsa ve değeri dict ise içi köke çıkar (iç içe sarmalayıcı da aynı kuralla);
      yanında başka kök anahtar varsa açılmaz.
    - 'cumleler' içinde dict olmayan ya da 'metin'i eksik/boş/metin-dışı bir öğe varsa HİÇBİR onarım yapılmaz
      (ID, kanca/final dahil); doğrulayıcı hangi öğe olduğunu açıkça söyler.
    - Faz-63d kimlik standardizasyonu: geçerli S<n> kimlikleri önceliklidir ve hiç değişmez. Tanımlı güvenli biçimler
      (s<n>, c<n>, C<n>, "<n>", tam sayı <n>; bkz. id_adayi) S<n> olur (rakamlar aynen). Bilinmeyen/bozuk biçimler
      ('abc', 'S-1', '' ...) dönüştürülmez; doğrulayıcı açık hata verir.
    - Hedefi dolu olan dönüşebilir kimlikler ve 'id' alanı olmayan (ya da None olan) öğeler, liste sırasıyla,
      mevcut ve dönüşen kimliklerle çakışmayan en küçük boş S<n> kimliğini alır (şema deseni ^S[0-9]+$).
    - Faz-63c: kanca_final=True ise 'kanca' = ilk cümlenin, 'final' = son cümlenin KİMLİĞİ (şemada ve anlati/kurgu'da
      bu alanlar cümle kimliğidir, metin değil). Cümle metni ve sırası değişmez; liste boşsa dokunulmaz.
    - Bilinmeyen alanlar silinmez; işlem idempotenttir."""
    import copy
    if not isinstance(veri, dict):
        return veri
    v = copy.deepcopy(veri)
    for _ in range(4):   # iç içe sarmalayıcı (tek anahtarlı) — sınırlı derinlik
        if set(v) == {SARMALAYICI} and isinstance(v[SARMALAYICI], dict):
            v = v[SARMALAYICI]
        else:
            break
    cs = v.get("cumleler")
    if not isinstance(cs, list):
        return v
    if any(not isinstance(c, dict) or not isinstance(c.get("metin"), str) or not c["metin"].strip() for c in cs):
        return v   # bozuk öğe: onarım yok, doğrulayıcı hangi öğe olduğunu açıkça söyler
    # Faz-63d kimlik standardizasyonu (deterministik, liste sırasıyla):
    # 1) geçerli S<n> kimlikleri ÖNCELİKLİ ve dokunulmaz (sonra gelseler bile ayrılır)
    kullanilan = {c["id"] for c in cs if isinstance(c.get("id"), str) and _GECERLI_ID.match(c["id"])}
    atanacak = []
    for c in cs:
        i = c.get("id")
        if i is None:                                     # 3) eksik kimlik → aşağıda en küçük boş S<n>
            atanacak.append(c)
            continue
        if isinstance(i, str) and _GECERLI_ID.match(i):
            continue
        aday = id_adayi(i)
        if aday is None:                                  # bilinmeyen/bozuk biçim: dönüştürülmez, doğrulayıcı yakalar
            continue
        if aday in kullanilan:                            # 2) çakışma → eksik kimlik gibi, çakışmasız S<n>
            atanacak.append(c)
            continue
        c["id"] = aday
        kullanilan.add(aday)
    n = 0
    for c in atanacak:                                    # liste sırasıyla en küçük boş S<n>
        n += 1
        while f"S{n}" in kullanilan:
            n += 1
        c["id"] = f"S{n}"
        kullanilan.add(c["id"])
    if kanca_final and cs:
        v["kanca"], v["final"] = cs[0]["id"], cs[-1]["id"]
    return v


def kaynak_ihtiyati_kurali(ara: dict) -> str:
    """Faz-63c: tartışmalı kartlara dayanan iddialar için anlatım disiplini. İfade listesi doğrulayıcının kullandığı
    kurallar/dil_tr.yaml temkin_ifadeleri'nden gelir (orada olmayan bir ifade sozlesme kapısından geçmez)."""
    from motor.uretim import veri
    temkin = veri.kural("dil_tr")["temkin_ifadeleri"]
    oncelikli = [x for x in ("bazı kaynaklara göre", "kaynaklara göre", "rivayet", "anlatılır", "iddia edilir") if x in temkin]
    tartismali = [c["id"] for c in ara.get("kartlar", []) if c.get("guven") in ("tartismali", "belirsiz")]
    satir = ["KAYNAK İHTİYATI (zorunlu):",
             "- 'tartismali' (ya da 'belirsiz') karta dayanan iddia için KESİN HÜKÜM KURMA; cümle şu ihtiyatlı "
             "ifadelerden birini AYNEN içersin: " + ", ".join(f'"{x}"' for x in oncelikli + [t for t in temkin if t not in oncelikli])
             + " (ör. \"Bazı kaynaklara göre…\", \"…rivayet edilir.\", \"Kaynaklara göre…\").",
             "- Kaynaklar farklı değer veriyorsa (kart notu: 'kaynaklar arasında farklı değer') farklılığı açıkça söyle.",
             "- 'kesin' ve 'makul' kartlara dayanan, güçlü kanıtlı iddiaları gereksiz yere belirsizleştirme: bu cümlelerde "
             "ihtiyat ifadesi KULLANMA."]
    satir.append(f"- Bu araştırmadaki tartışmalı kartlar: {', '.join(tartismali)}." if tartismali else
                 "- Bu araştırmada tartışmalı kart yok.")
    return "\n".join(satir)


# ------------------------------------------------------------------ 3) Commons 2.5D görselleri

def gorsel_sorgu_istemi(konu: str, ara: dict, adet: int = EN_COK_GORSEL, sahneler: list[str] | None = None) -> str:
    """Faz-62d: sorgular konu adından değil SAHNE KONULARINDAN türetilir (kişiler, ordular, silahlar, mekânlar, haritalar,
    dönem sanatı); her sorgu farklı bir dosyaya gider."""
    iddialar = "\n".join(f"- {c['iddia']}" for c in ara["kartlar"][:20])
    sahne = "\n".join(f"- {x}" for x in (sahneler or [])) or "(sahne listesi yok: doğrulanmış bilgilerden çıkar)"
    return f"""Konu: "{konu}". Bu belgeselin sahneleri için Wikimedia Commons'ta aranacak tarihî görsel sorguları üret.
SAHNE KONULARI:
{sahne}
Doğrulanmış bilgiler:
{iddialar}
KURALLAR:
- Sorguyu yalnızca konu/savaş adıyla ("{konu}") KURMA; o adla Commons'ta çok az dosya var. Her sahne için o sahnede
  görünmesi gereken ALT KONULARI ara: kişiler (ör. "Mehmed II", "Uzun Hasan", "Bayezid II portrait"), ordular
  (ör. "Janissaries", "Ottoman sipahi", "Turkoman cavalry"), silahlar (ör. "Ottoman artillery", "15th century cannon"),
  mekânlar ve haritalar (ör. "Anatolia historical map", "Tabriz", "Erzincan"), dönem sanatı (ör. "Ottoman miniature",
  "Tabriz miniature", "Persian miniature 15th century"), olay türü (ör. "15th century battle").
- Her öğe FARKLI bir görsel hedeflesin (aynı eseri iki sorguyla isteme); sorgular İngilizce, 2–5 kelime.
- Kaynak: dönem minyatürleri, gravürler, tarihî portre resimleri, eski haritalar, müze nesneleri, tarihî yapı fotoğrafları.
  Lisans: kamu malı ya da CC0 tercih; CC-BY / CC-BY-SA de olur (atıf kaydedilir). Modern illüstrasyon, oyun görseli,
  film karesi İSTEME.
Yanıt YALNIZCA JSON dizi: {adet} öğe, her öğe {{"gorsel_id": "kısa-kimlik", "sahne": "hangi sahne konusu",
"sorgu": "İngilizce Commons araması", "yedek_sorgular": ["…", "…"], "tur": "insan_portre|mimari|cok_figurlu|genel",
"aciklama": "Türkçe kısa açıklama (ne görünüyor)"}}. gorsel_id yalnız küçük harf, rakam ve tire; hepsi farklı."""


def lisans_uygun(k: dict) -> tuple[bool, str]:
    """CC0 / PD; ya da CC-BY* (CC-BY-SA dahil) + tam atıf (yazar bilinmeli, lisans ve kaynak URL'si)."""
    lis = str(k.get("lisans_turu") or "")
    if lis in IZINLI:
        return True, "serbest"
    if re.fullmatch(r"CC-BY(-SA)?(-[\d.]+)?", lis.upper()):   # NC / ND ekli lisanslar burada da reddedilir
        atif = k.get("atif") or {}
        eksik = [a for a in ("yazar", "lisans", "kaynak") if not str(atif.get(a) or "").strip()]
        if str(atif.get("yazar") or "").strip().lower() in ("bilinmiyor", "unknown", ""):
            eksik.append("yazar bilinmiyor")
        return (not eksik), ("atıflı" if not eksik else f"atıf eksik ({', '.join(eksik)})")
    return False, f"lisans {lis or '?'} kabul edilmiyor (CC0, PD, CC-BY, CC-BY-SA; NC/ND hayır)"


def gorselleri_topla(konu_kimlik: str, sorgular: list[dict], hedef: Path = GORSEL_KOK, topla=None,
                    en_cok: int = EN_COK_GORSEL) -> list[dict]:
    """Sorguları indirir. Kabul: CC0/PD ya da atıflı CC-BY/CC-BY-SA (lisans_uygun) + tarihi_gorsel kapısı.
    Aynı Commons dosyası (başlık ya da SHA-256) ikinci kez alınmaz: sonraki sorgular önceki seçimleri hariç tutar."""
    from motor.varlik import commons_toplayici, tarihi_gorsel
    topla = topla or commons_toplayici.topla
    hedef.mkdir(parents=True, exist_ok=True)
    alinan, basliklar, shalar, kimlikler = [], set(), set(), set()

    def sil(gid):
        for uz in (".jpg", ".jpeg", ".png", ".tif", ".json"):
            (hedef / f"{gid}{uz}").unlink(missing_ok=True)

    for i, s in enumerate(sorgular[:en_cok], 1):
        if not isinstance(s, dict) or not s.get("sorgu"):
            continue
        gid = f"{konu_kimlik}-{kisa_ad(str(s.get('gorsel_id') or i))[:40] or i}"
        if gid in kimlikler:
            gid = f"{gid}-{i}"
        s2 = {"gorsel_id": gid, "sorgu": s.get("sorgu"), "yedek_sorgular": list(s.get("yedek_sorgular") or [])[:3],
              "tur": s.get("tur") if s.get("tur") in ("insan_portre", "mimari", "cok_figurlu") else None,
              "en_az_px": 1500, "eser_adi": s.get("aciklama"), "haric": sorted(basliklar)}
        try:
            k = topla(s2, hedef)
        except Exception as e:   # noqa: BLE001 — tek görselin bulunamaması üretimi durdurmaz; raporlanır
            log("gorsel", f"✗ {gid}: {type(e).__name__}: {str(e)[:160]}")
            continue
        uygun, neden = lisans_uygun(k)
        if not uygun:
            log("gorsel", f"✗ {gid}: {neden}; kullanılmaz")
            sil(gid)
            continue
        baslik, sha = (k.get("toplama") or {}).get("baslik"), k.get("sha256")
        if (baslik and baslik in basliklar) or (sha and sha in shalar):
            log("gorsel", f"✗ {gid}: aynı dosya daha önce alındı ({baslik}); tekrar kullanılmaz")
            sil(gid)
            continue
        try:
            tarihi_gorsel.dogrulanmis_dosya(gid)
        except Exception as e:   # noqa: BLE001
            log("gorsel", f"✗ {gid}: lisans/dosya kapısı: {str(e)[:160]}")
            continue
        basliklar.update([baslik] if baslik else [])
        shalar.update([sha] if sha else [])
        kimlikler.add(gid)
        alinan.append({"gorsel_id": gid, "aciklama": s.get("aciklama") or k.get("eser_adi"), "lisans": k["lisans_turu"],
                       "kaynak_url": k.get("kaynak_url"), "tur": k.get("gorsel_turu"), "sahne": s.get("sahne"),
                       "commons_baslik": baslik, **({"atif": k["atif"]} if k.get("atif") else {})})
        log("gorsel", f"✓ {gid}: {k['lisans_turu']} ({neden}) {k.get('cozunurluk')} — {baslik}")
    return alinan


def gorsel_kapisi(bicim: str, gorseller: list[dict], senaryo: dict | None = None) -> list[str]:
    """Faz-62d: render'a geçmeden önce (1) en az EN_AZ_GORSEL[bicim] benzersiz görsel indirilmiş, (2) senaryo bunları
    benzersiz kullanıyor (bir görsel bir kez) ve en az o kadar farklı görsel içeriyor olmalı."""
    en_az = EN_AZ_GORSEL[bicim]
    h = []
    ids = {g["gorsel_id"] for g in gorseller}
    if len(ids) < en_az:
        h.append(f"{bicim}: {len(ids)} benzersiz tarihî görsel indirildi; en az {en_az} gerekli (render'a geçilmez)")
    if senaryo is not None:
        kul = [(c["niyet"].get("gorsel25d") or {}).get("gorsel_id") for c in senaryo["cumleler"]
               if c["niyet"]["tur"] == "gorsel25d"]
        tekrar = sorted({x for x in kul if kul.count(x) > 1})
        if tekrar:
            h.append(f"{bicim}: aynı görsel birden fazla cümlede: {tekrar}")
        if len(set(kul)) < en_az:
            h.append(f"{bicim}: senaryoda {len(set(kul))} farklı tarihî görsel; en az {en_az} gerekli")
    return h


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
                     f"görseller (anlatılan cümleyle ilgili olanı seç; HER GÖRSEL EN ÇOK BİR KEZ; en az "
                     f"{EN_AZ_GORSEL['shorts']} farklı görsel kullan): "
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
    h += [x for x in gorsel_kapisi(s.get("format") or "shorts", gorseller, s) if "indirildi" not in x]
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
        istem = (senaryo_uretici.istem(konu, ara, hatalar) + "\n" + gorsel_kurallari(konu, gorseller) + "\n"
                 + kaynak_ihtiyati_kurali(ara))
        ham = saglayici.tamamla(istem, "senaryo", {"bolum": f"deneme{d}", "yanit_semasi": shorts_api_semasi()})
        try:
            s = json_ayikla(ham)
        except (json.JSONDecodeError, TypeError) as e:
            hatalar = [f"yanıt JSON değil: {e}"]
            gecmis.append({"deneme": d, "hatalar": hatalar})
            continue
        s = normalize_senaryo(s)   # Faz-63: şema doğrulamasından ÖNCE (ve surum/konu eklenmeden önce: wrapper açılabilsin)
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

RENDER_MALIYETI = {"3d": 60.0, "harita": 7.0, "gorsel25d": 5.0}   # duvar sn / video sn (ölçülen yaklaşık oranlar)


def parcalara_bol(plan: dict, parca_sayisi: int) -> list[dict]:
    """Çekimleri en çok `parca_sayisi` paralel parçaya dengeli böler (en pahalı işler önce).
    Shorts: yalnız 3D (Faz-62b ile aynı; harita/2.5D kurguda çizilir). Uzun: bütün türler maliyet ağırlığıyla
    (15–20 dk'lık harita + 2.5D çizimi de paralel yürür)."""
    uzun = plan.get("format") == "uzun"
    secili = [c for c in plan["cekimler"] if uzun or c["tur"] == "3d"]
    maliyet = {c["id"]: c["sure_sn"] * (RENDER_MALIYETI.get(c["tur"], 5.0) if uzun else 1.0) for c in secili}
    secili.sort(key=lambda c: (-maliyet[c["id"]], c["id"]))
    n = max(1, min(parca_sayisi, len(secili)))
    parcalar = [{"parca": i, "cekimler": [], "sure_sn": 0.0, "maliyet": 0.0} for i in range(n)]
    for c in secili:
        p = min(parcalar, key=lambda x: (x["maliyet"], x["parca"]))
        p["cekimler"].append(c["id"])
        p["sure_sn"] = round(p["sure_sn"] + c["sure_sn"], 2)
        p["maliyet"] = round(p["maliyet"] + maliyet[c["id"]], 1)
    if not uzun:
        for p in parcalar:
            p.pop("maliyet")
    return parcalar


def _sablon_katalog(sablon: Path) -> list[dict]:
    """Uzun formatta 3D yalnızca sınırlı ve DENETLENMİŞ sahnelerle: pilot senaryonun render'da kanıtlanmış 3D niyetleri."""
    sen = json.loads((sablon / "senaryo.json").read_text())
    return [{"katalog": f"3D-{c['id']}", "aciklama": c["metin"], "niyet": c["niyet"]}
            for c in sen["cumleler"] if c["niyet"]["tur"] == "3d"]


def planla(konu: str, mod: str, is_kok: Path, anahtar: str | None, parca_sayisi: int = 4,
           havuz_fn=None, saglayici_fn=None, topla=None, planla_fn=None, olc=None) -> dict:
    """mod: shorts | uzun | her_ikisi. Araştırma ve görseller bir kez; her biçim kendi senaryosu ve planı.
    Dönüş: {'isler': [{biçim raporu}...], 'kimlik'(ilk), 'parcalar' (hepsi, kimlik etiketli)}."""
    if mod not in MODLAR:
        raise UretimHatasi("bicim", f"bilinmeyen biçim: {mod} (geçerli: {', '.join(MODLAR)})", 3)
    if not anahtar:
        raise UretimHatasi("anahtar", "GEMINI_API_KEY tanımlı değil; üretim yapılmadı (mock'a geçilmez)", 2)
    t0 = time.time()
    bicimler = MODLAR[mod]
    sablon = sablon_bul(konu)
    log("arastirma", f"şablon {sablon.name}; araştırma havuzu kuruluyor (biçimler: {', '.join(bicimler)})")
    havuz = (havuz_fn or havuz_kur)(konu)
    uzun_var = "uzun" in bicimler
    ara_tam, esleme_tam = kartlar_kur(havuz, "gecici", UZUN_KART if uzun_var else 30)
    g = (saglayici_fn or (lambda: gemini(anahtar, 2400.0 if uzun_var else 420.0)))()
    adet = EN_COK_GORSEL_UZUN if uzun_var else EN_COK_GORSEL
    taslak, taslak_gecmis = None, []
    if uzun_var:   # Faz-62d: önce bölüm taslağı → görsel sorguları sahne (bölüm) konularından türetilir
        try:
            taslak, taslak_gecmis = uzun_taslak_uret(g, konu_kur(sablon, konu, "uzun"), ara_tam)
        except Exception as e:
            if isinstance(e, UretimHatasi):
                raise
            raise UretimHatasi("gemini", f"{getattr(e, 'sinif', type(e).__name__)}: {str(e)[:300]}",
                               4 if getattr(e, "sinif", None) == "kota" else 1) from e
        sahneler = [f"{b['baslik']} ({', '.join(b['roller'])}): {b.get('ozet', '')}" for b in taslak["bolumler"]]
    else:
        sahneler = [c["iddia"] for c in ara_tam["kartlar"][:10]]
    try:
        sorgular = json_ayikla(g.tamamla(gorsel_sorgu_istemi(konu, ara_tam, adet, sahneler), "gorsel_sorgu", {}))
    except Exception as e:   # noqa: BLE001 — görsel önerisi alınamazsa 2.5D'siz devam edilir (raporlanır)
        if getattr(e, "sinif", None) == "kota":
            raise UretimHatasi("gemini", f"kota (429): {e}", 4) from e
        log("gorsel", f"görsel sorgusu alınamadı ({type(e).__name__}); 2.5D çekimsiz devam")
        sorgular = []
    gorsel_on = konu_kur(sablon, konu, bicimler[0])["kimlik"].rsplit("-oto", 1)[0] + "-oto"
    gorseller = gorselleri_topla(gorsel_on, sorgular if isinstance(sorgular, list) else [], topla=topla, en_cok=adet)
    eksik = [x for b in bicimler for x in gorsel_kapisi(b, gorseller)]
    if eksik:   # Faz-62d: yeterli benzersiz görsel yoksa senaryo/render'a hiç geçilmez
        raise UretimHatasi("gorsel", "; ".join(eksik) + f" — {len(sorgular) if isinstance(sorgular, list) else 0} "
                                     "sorgu denendi", 5)
    r: dict = {"konu": konu, "mod": mod, "sablon": sablon.name, "gorseller": gorseller,
               "arastirma": {"kayit": len(havuz["kayitlar"]), "kart": len(ara_tam["kartlar"]), "kaynak": len(ara_tam["kaynaklar"]),
                             "kesin": sum(c["guven"] == "kesin" for c in ara_tam["kartlar"]),
                             "makul": sum(c["guven"] == "makul" for c in ara_tam["kartlar"]),
                             "tartismali": sum(c["guven"] == "tartismali" for c in ara_tam["kartlar"])}, "isler": []}
    for bicim in bicimler:
        k = konu_kur(sablon, konu, bicim)
        is_ = is_kok / k["kimlik"]
        shutil.rmtree(is_, ignore_errors=True)
        is_.mkdir(parents=True)
        # Shorts: Faz-62b ile aynı (ilk 30 kart; sıralama belirlenimci olduğundan aynı kartlar)
        ara, esleme = kartlar_kur(havuz, k["kimlik"], UZUN_KART if bicim == "uzun" else 30)
        try:
            if bicim == "uzun":
                sen, gecmis = uzun_senaryo_uret(g, k, ara, gorseller, _sablon_katalog(sablon), olc=olc, taslak=taslak)
                gecmis = taslak_gecmis + gecmis
            else:
                sen, gecmis = senaryo_uret(g, k, ara, gorseller, olc=olc)
        except Exception as e:
            if isinstance(e, UretimHatasi):
                raise
            raise UretimHatasi("gemini", f"{getattr(e, 'sinif', type(e).__name__)}: {str(e)[:300]}",
                               4 if getattr(e, "sinif", None) == "kota" else 1) from e
        ri = {"bicim": bicim, "kimlik": k["kimlik"], "is": str(is_),
              "senaryo": {"cumle": len(sen["cumleler"]), "bolum": len(sen.get("bolumler", [])), "denemeler": gecmis,
                          "turler": {t: sum(c["niyet"]["tur"] == t for c in sen["cumleler"]) for t in ("harita", "gorsel25d", "3d")}}}
        kapi = gorsel_kapisi(bicim, gorseller, sen)
        if kapi:
            raise UretimHatasi("gorsel", "; ".join(kapi), 5)
        kullanilan = sorted({c["niyet"]["gorsel25d"]["gorsel_id"] for c in sen["cumleler"] if c["niyet"]["tur"] == "gorsel25d"})
        ri["gorseller"] = kullanilan
        for ad, v in (("konu.json", k), ("arastirma.json", ara), ("senaryo.json", sen), ("kart_eslemesi.json", esleme),
                      ("gorsel_kapisi.json", {"bicim": bicim, "en_az": EN_AZ_GORSEL[bicim], "indirilen": len(gorseller),
                                              "kullanilan": kullanilan}),
                      ("gorsel_atiflari.json", [g_ for g_ in gorseller if g_["gorsel_id"] in kullanilan])):
            (is_ / ad).write_text(json.dumps(v, ensure_ascii=False, indent=1))
        p = (planla_fn or uretim_hatti_planla)(is_)
        ri["plan"] = {"gecti": p["gecti"], "toplam_sure_sn": p.get("toplam_sure_sn"),
                      "hatalar": {a: b for a, b in p["hatalar"].items() if b}}
        if not p["gecti"]:
            raise UretimHatasi("plan", f"{bicim} çekim planı kapıdan geçmedi: {ri['plan']['hatalar']}")
        plan = json.loads((is_ / "cekim_plani.json").read_text())
        ri["cekimler"] = {t: [c["id"] for c in plan["cekimler"] if c["tur"] == t] for t in ("3d", "harita", "gorsel25d")}
        ri["parcalar"] = parcalara_bol(plan, max(parca_sayisi, 8) if bicim == "uzun" else parca_sayisi)
        (is_ / "parcalar.json").write_text(json.dumps(ri["parcalar"], ensure_ascii=False))
        r["isler"].append(ri)
    r["gemini_cagri"] = getattr(g, "cagri_sayisi", None)
    r["model"] = getattr(g, "kullanilan_model", None)
    r["kimlik"] = r["isler"][0]["kimlik"]
    r["parcalar"] = [dict(p, kimlik=i["kimlik"]) for i in r["isler"] for p in i["parcalar"]]
    r["sure_sn"] = round(time.time() - t0, 1)
    return r


def uretim_hatti_planla(is_: Path) -> dict:
    from motor.uretim import uretim_hatti
    return uretim_hatti.planla(is_)


# ------------------------------------------------------------------ 4b) uzun senaryo (Faz-62c)

def _uzun_kural() -> dict:
    from motor.uretim import veri
    return veri.kural("uzun")


def taslak_istemi(konu: dict, ara: dict, hatalar: list[str]) -> str:
    k = _uzun_kural()["bolum"]
    kartlar = "\n".join(f"{c['id']} [{c['guven']}] {c['iddia']}" for c in ara["kartlar"])
    return f"""Sen titiz bir tarih belgeseli yazarısın. Konu: "{konu['baslik']}". 15–20 dakikalık (yaklaşık {UZUN_PLAN_SN} sn)
yatay bir tarih belgeseli için BÖLÜM TASLAĞI çıkar. Yalnızca aşağıdaki DOĞRULANMIŞ kartlardaki bilgiler kullanılabilir.
KARTLAR:
{kartlar}
KURALLAR:
- {k['en_az']}–{k['en_cok']} ana bölüm (tercihen 7). Bölüm rolleri şu kronolojik sırayla, HER BİRİ en az bir bölümde:
  {', '.join(k['roller'])}. Bir bölüm ardışık birkaç rol taşıyabilir. İlk bölüm 'kanca' ile başlar, son bölüm 'kapanis' içerir.
- Her bölüm için hedef_sn ver; toplam ≈ {UZUN_PLAN_SN}. Bilgi az olan bölüme yapay süre verme.
- Aynı bilgiyi iki bölüme koyma; her bölümün kendi kartları olsun.
{"ÖNCEKİ DENEMENİN HATALARI (düzelt): " + "; ".join(hatalar) if hatalar else ""}
Yanıt YALNIZCA JSON: {{"baslik": "...", "bolumler": [{{"id": "B1", "baslik": "kısa bölüm başlığı", "roller": ["kanca", "baglam"],
"ozet": "2 cümle", "kartlar": ["C1"], "hedef_sn": 150}}]}}"""


def taslak_denetle(t, ara: dict) -> list[str]:
    k = _uzun_kural()["bolum"]
    if not isinstance(t, dict) or not isinstance(t.get("bolumler"), list):
        return ["yanıt {'bolumler': [...]} biçiminde değil"]
    h = []
    bs = t["bolumler"]
    if not k["en_az"] <= len(bs) <= k["en_cok"]:
        h.append(f"{len(bs)} bölüm; {k['en_az']}–{k['en_cok']} olmalı")
    gecerli = {c["id"] for c in ara["kartlar"]}
    onceki, kapsanan = -1, set()
    for i, b in enumerate(bs, 1):
        if not isinstance(b, dict) or not b.get("baslik") or not b.get("roller"):
            h.append(f"bölüm {i}: baslik/roller eksik")
            continue
        for r in b["roller"]:
            if r not in k["roller"]:
                h.append(f"bölüm {i}: bilinmeyen rol {r}")
            elif k["roller"].index(r) < onceki:
                h.append(f"bölüm {i}: '{r}' kronolojik sırayı bozuyor")
            else:
                onceki = k["roller"].index(r)
                kapsanan.add(r)
        bilinmeyen = [x for x in b.get("kartlar") or [] if x not in gecerli]
        if bilinmeyen:
            h.append(f"bölüm {i}: tanımsız kart {bilinmeyen}")
    eksik = [r for r in k["roller"] if r not in kapsanan]
    if eksik:
        h.append(f"eksik roller: {eksik}")
    if bs and "kanca" not in (bs[0].get("roller") or []):
        h.append("ilk bölüm 'kanca' içermeli")
    if bs and "kapanis" not in (bs[-1].get("roller") or []):
        h.append("son bölüm 'kapanis' içermeli")
    return h


def niyet_kurallari_uzun(konu: dict, gorseller: list[dict], katalog: list[dict], kullanim: dict) -> str:
    evreler = (konu.get("harita") or {}).get("evreler") or []
    kg = _uzun_kural()["gorsel"]
    satir = ["GÖRSEL NİYET (her cümle bir tane; görsel anlatılan olayla İLGİLİ olmalı, dekor değil). Öncelik: harita, "
             "tarihî görsel (2.5D), en son ve az sayıda 3D."]
    if evreler:
        satir.append('harita: {"tur": "harita", "evre": <evre>, "metin": "<haritanın üstüne yazılacak BENZERSİZ kısa başlık>", '
                     '"metin_katmani": "<isteğe bağlı tarih/yer>"} — evreler: '
                     + "; ".join(f"{e['id']} = {e.get('baslik', '')}" for e in evreler)
                     + ". Aynı evre başka cümlede ancak FARKLI 'metin' ile kullanılabilir.")
    bos = [g for g in gorseller if kullanim.get(g["gorsel_id"], 0) < GORSEL_EN_COK_KULLANIM]
    if bos:
        satir.append('gorsel25d: {"tur": "gorsel25d", "gorsel_id": <kimlik>, "aciklama": "<bu cümlede görselin ne '
                     'gösterdiği, BENZERSİZ>", "hareket": <' + "|".join(HAREKETLER) + '>} — HER GÖRSEL BELGESEL BOYUNCA '
                     'EN ÇOK BİR KEZ; henüz kullanılmamış görseller: '
                     + "; ".join(f"{g['gorsel_id']} = {g['aciklama']}" + (f" [sahne: {g['sahne']}]" if g.get("sahne") else "")
                                 for g in bos))
    else:
        satir.append("Kullanılmamış tarihî görsel kalmadı: 'gorsel25d' kullanma.")
    kalan = [x for x in katalog if x["katalog"] not in kullanim]
    if kalan:
        satir.append('3d (yalnızca savaş sahneleri, belgesel boyunca en çok ' + str(kg["en_cok_3d_cumle"]) +
                     ' ve %' + str(int(kg["en_cok_3d_payi"] * 100)) + '): {"tur": "3d", "katalog": <kimlik>} — kalan sahneler: '
                     + "; ".join(f"{x['katalog']} = {x['aciklama']}" for x in kalan) + ". Her sahne bir kez.")
    else:
        satir.append("3d sahnesi kalmadı: '3d' kullanma.")
    satir.append("bilgi_karti KULLANMA.")
    return "\n".join(satir)


def bolum_istemi(konu: dict, ara: dict, taslak: dict, b: dict, onceki: list[dict], gorseller: list[dict],
                 katalog: list[dict], kullanim: dict, hedef_kelime: int, hatalar: list[str], ilk: bool, son: bool,
                 en_az_yeni: int = 0) -> str:
    from motor.uretim import veri
    kc = _uzun_kural()["cumle"]
    kartlar = "\n".join(f"{c['id']} [{c['guven']}]{' (' + c['not'] + ')' if c.get('not') else ''} {c['iddia']}"
                        for c in ara["kartlar"])
    anlatilan = "\n".join(f"- {c['metin']}" for c in onceki[-120:]) or "(henüz yok)"
    plan = "\n".join(f"{x['id']} {x['baslik']} ({', '.join(x['roller'])}): {x.get('ozet', '')}" for x in taslak["bolumler"])
    ek = []
    if ilk:
        ek.append("İLK CÜMLE açılış kancasıdır: en çok 12 sn (≈20 kelime), bir sayı, soru ya da şaşırtıcı bir karşıtlık içerir.")
    if son:
        ek.append("SON CÜMLE belgeseli kapatır (anlamını özetler, yeni bilgi eklemez).")
    if en_az_yeni:
        ek.append(f"Bu bölümde EN AZ {en_az_yeni} farklı, daha önce kullanılmamış tarihî görsel (gorsel25d) kullan; "
                  "her biri anlatılan cümleyle ilgili olsun.")
    return f"""Sen titiz bir tarih belgeseli anlatıcısısın. Belgesel: "{konu['baslik']}" (Türkçe, 16:9, 15–20 dk).
BÖLÜM PLANI:
{plan}
ŞİMDİ YAZILACAK BÖLÜM: {b['id']} — {b['baslik']} (roller: {', '.join(b['roller'])}). Özet: {b.get('ozet', '')}
UZUNLUK: yaklaşık {hedef_kelime} kelime (cümle başına 12–28, en çok {kc['en_cok_kelime']} kelime). Yapay uzatma YASAK.
DOĞRULANMIŞ KARTLAR (yalnızca bunlardaki bilgiler anlatılır; tarih, kişi, sayı uydurma):
{kartlar}
KURALLAR:
- Her olgusal cümle dayandığı kart kimliklerini 'kartlar' alanında verir. Kartta olmayan bilgi kesin gerçek gibi anlatılmaz.
{kaynak_ihtiyati_kurali(ara)}
- Geçiş/yorum cümlesi (yeni bilgi içermeyen) "olgusal": false ile işaretlenir; bunlar bölümün %20'sini aşmaz.
- Daha önce anlatılanları TEKRAR ETME (aynı bilgiyi başka sözcüklerle söylemek de yasak). Önceki bölümlerde anlatılanlar:
{anlatilan}
- Yabancı ad/kısaltma/yıl okunuşu gerekiyorsa "okunus" alanı ekle (seslendirme metni).
{chr(10).join('- ' + x for x in ek)}
{niyet_kurallari_uzun(konu, gorseller, katalog, kullanim)}
{"ÖNCEKİ DENEMENİN HATALARI (hepsini düzelt): " + "; ".join(hatalar[:15]) if hatalar else ""}
Yanıt YALNIZCA JSON: {{"cumleler": [{{"metin": "...", "kartlar": ["C1"], "olgusal": true, "niyet": {{...}}}}]}}"""


def niyet_normalle(n, gorseller: list[dict], katalog: list[dict], konu: dict) -> tuple[dict | None, str | None]:
    """Gemini'nin sade niyetini şemaya çevirir; geçersizse (None, hata)."""
    if not isinstance(n, dict):
        return None, "niyet nesne değil"
    tur = n.get("tur")
    if tur == "harita":
        evreler = {e["id"] for e in (konu.get("harita") or {}).get("evreler") or []}
        if n.get("evre") not in evreler or not str(n.get("metin") or "").strip():
            return None, f"harita: geçerli evre ({sorted(evreler)}) ve benzersiz 'metin' gerekli"
        return {"tur": "harita", "evre": n["evre"], "metin": str(n["metin"]).strip()[:80],
                **({"metin_katmani": str(n["metin_katmani"])[:60]} if n.get("metin_katmani") else {})}, None
    if tur == "gorsel25d":
        gid = n.get("gorsel_id") or (n.get("gorsel25d") or {}).get("gorsel_id")
        if gid not in {g["gorsel_id"] for g in gorseller}:
            return None, f"gorsel25d: gorsel_id listede yok ({gid})"
        if not str(n.get("aciklama") or "").strip():
            return None, "gorsel25d: 'aciklama' zorunlu"
        hareket = n.get("hareket") if n.get("hareket") in HAREKETLER else "zoom_in"
        return {"tur": "gorsel25d", "gorsel25d": {"gorsel_id": gid, "hareket": hareket},
                "aciklama": str(n["aciklama"]).strip()[:120]}, None
    if tur == "3d":
        x = next((x for x in katalog if x["katalog"] == n.get("katalog")), None)
        if not x:
            return None, f"3d: katalog kimliği geçersiz ({n.get('katalog')})"
        return json.loads(json.dumps(x["niyet"])), None
    return None, f"niyet türü '{tur}' kullanılamaz (harita, gorsel25d, 3d)"


def bolum_cumleleri(yanit, ara: dict, konu: dict, gorseller: list[dict], katalog: list[dict], kullanim: dict,
                    bolum_id: str, bas_no: int, onceki: list[dict], en_az_yeni: int = 0) -> tuple[list[dict], list[str]]:
    """Gemini bölüm yanıtı → şemaya uygun cümleler + yerel kapı hataları (kart, dil, uzunluk, niyet, tekrar)."""
    from motor.uretim import anlati, veri
    from motor.uretim.sozlesme import TEMKINLI_GUVEN
    kc = _uzun_kural()["cumle"]
    if not isinstance(yanit, dict) or not isinstance(yanit.get("cumleler"), list) or not yanit["cumleler"]:
        return [], ["yanıt {'cumleler': [...]} biçiminde değil"]
    kartlar = {c["id"]: c for c in ara["kartlar"]}
    temkin = veri.kural("dil_tr")["temkin_ifadeleri"]
    h, cs = [], []
    kul = dict(kullanim)
    onceki_g = (onceki[-1]["niyet"].get("gorsel25d") or {}).get("gorsel_id") if onceki else None
    imzalar = {(c["niyet"]["tur"], c["niyet"].get("evre") or (c["niyet"].get("gorsel25d") or {}).get("gorsel_id"),
                c["niyet"].get("metin") or c["niyet"].get("aciklama")) for c in onceki}
    for i, x in enumerate(yanit["cumleler"]):
        cid = f"S{bas_no + i}"
        if not isinstance(x, dict) or not str(x.get("metin") or "").strip():
            h.append(f"{cid}: metin yok")
            continue
        metin = " ".join(str(x["metin"]).split())
        olgusal = x.get("olgusal", True) is not False
        ks = [k for k in (x.get("kartlar") or []) if isinstance(k, str)]
        for k in ks:
            if k not in kartlar:
                h.append(f"{cid}: tanımsız kart {k}")
            elif kartlar[k]["guven"] in TEMKINLI_GUVEN and not any(t in metin.lower() for t in temkin):
                h.append(f"{cid}: '{kartlar[k]['guven']}' kart ({k}) kesin dille anlatılmış; temkin ifadesi kullan")
        if olgusal and not ks:
            h.append(f"{cid}: olgusal cümle karta dayanmıyor")
        n_k = len(re.findall(r"\w+", metin))
        if not kc["en_az_kelime"] <= n_k <= kc["en_cok_kelime"]:
            h.append(f"{cid}: {n_k} kelime ({kc['en_az_kelime']}–{kc['en_cok_kelime']})")
        niyet, hata = niyet_normalle(x.get("niyet"), gorseller, katalog, konu)
        if hata:
            h.append(f"{cid}: {hata}")
            niyet = None
        if niyet:
            if niyet["tur"] == "gorsel25d":
                gid = niyet["gorsel25d"]["gorsel_id"]
                kul[gid] = kul.get(gid, 0) + 1
                if kul[gid] > GORSEL_EN_COK_KULLANIM:
                    h.append(f"{cid}: {gid} görseli {GORSEL_EN_COK_KULLANIM} kereden fazla kullanıldı")
                if gid == onceki_g:
                    h.append(f"{cid}: {gid} görseli art arda kullanıldı")
                onceki_g = gid
            else:
                onceki_g = None
            if niyet["tur"] == "3d":
                kat = x["niyet"]["katalog"]
                if kat in kul:
                    h.append(f"{cid}: 3D sahnesi {kat} ikinci kez kullanıldı")
                kul[kat] = 1
            imza = (niyet["tur"], niyet.get("evre") or (niyet.get("gorsel25d") or {}).get("gorsel_id"),
                    niyet.get("metin") or niyet.get("aciklama"))
            if niyet["tur"] != "3d" and imza in imzalar:
                h.append(f"{cid}: aynı görsel aynı başlık/açıklamayla tekrar (metin/aciklama benzersiz olmalı)")
            imzalar.add(imza)
        c = {"id": cid, "metin": metin, "kartlar": ks, "olgusal": olgusal, "bolum": bolum_id,
             "niyet": niyet or {"tur": "harita"}}
        if x.get("okunus"):
            c["okunus"] = str(x["okunus"])
        cs.append(c)
    ids = {c["id"] for c in cs}
    yeni = {c["niyet"]["gorsel25d"]["gorsel_id"] for c in cs if c["niyet"]["tur"] == "gorsel25d"}
    if len(yeni) < en_az_yeni:
        h.append(f"bu bölümde {len(yeni)} farklı tarihî görsel kullanıldı; en az {en_az_yeni} farklı, daha önce "
                 "kullanılmamış görsel kullan (gorsel25d)")
    h += [e for e in anlati.tekrar_denetle(onceki + cs, _uzun_kural()["tekrar"]) if e.split(":")[0] in ids]
    kullanim.clear()
    kullanim.update(kul)
    return cs, h


def uzun_taslak_uret(saglayici, konu: dict, ara: dict, deneme: int = 3) -> tuple[dict, list[dict]]:
    """6–8 bölümlük taslak (kronolojik roller). planla bunu görsel sorgusundan ÖNCE çağırır (sahne konuları)."""
    hatalar: list[str] = []
    gecmis: list[dict] = []
    for d in range(1, deneme + 1):
        try:
            t = normalize_senaryo(json_ayikla(saglayici.tamamla(taslak_istemi(konu, ara, hatalar), "uzun_taslak",
                                                                {"bolum": "uzun_taslak", "yanit_semasi": TASLAK_API_SEMASI})))
        except (json.JSONDecodeError, TypeError) as e:
            hatalar = [f"yanıt JSON değil: {e}"]
            continue
        hatalar = taslak_denetle(t, ara)
        gecmis.append({"adim": "taslak", "deneme": d, "hatalar": hatalar[:10]})
        log("senaryo", f"taslak deneme {d}: {len(hatalar)} hata" + (f" — {hatalar[:3]}" if hatalar else ""))
        if not hatalar:
            for i, b in enumerate(t["bolumler"], 1):
                b["id"] = f"B{i}"
            return t, gecmis
    raise UretimHatasi("senaryo", f"bölüm taslağı kapıdan geçmedi: {hatalar[:6]}")


def uzun_senaryo_uret(saglayici, konu: dict, ara: dict, gorseller: list[dict], katalog: list[dict],
                      olc=None, deneme: int = 3, onarim: int = 2, taslak: dict | None = None) -> tuple[dict, list[dict]]:
    """Taslak (6–8 bölüm) → bölüm bölüm yazım (her bölüm yerel kapılar + gerçek TTS süresi) → bütün senaryo kapıları
    (sozlesme, anlati.uzun_denetle, 15–20 dk zaman çizelgesi). Süre tutmazsa en sapan bölüm yeniden yazılır (en çok
    `onarim` kez); yine tutmazsa AÇIK HATA. Çağrı tavanı: EN_COK_GEMINI_CAGRI."""
    from motor.uretim import anlati, sahne_bolucu, seslendirme, sozlesme
    olc = olc or seslendirme.olc
    cagri = {"n": 0}
    gecmis: list[dict] = []

    def iste(istem: str, adim: str) -> object:
        if cagri["n"] >= EN_COK_GEMINI_CAGRI:
            raise UretimHatasi("senaryo", f"Gemini çağrı tavanı ({EN_COK_GEMINI_CAGRI}) aşıldı; üretim durdu")
        cagri["n"] += 1
        return normalize_senaryo(json_ayikla(saglayici.tamamla(istem, adim, {"bolum": adim, "yanit_semasi": BOLUM_API_SEMASI})),
                                 kanca_final=False)   # bölüm parçası: kanca/final bütün senaryoda (kur) belirlenir

    if taslak is None:
        taslak, g0 = uzun_taslak_uret(saglayici, konu, ara, deneme)
        cagri["n"] += len(g0)
        gecmis += g0
    bs = taslak["bolumler"]
    for i, b in enumerate(bs, 1):
        b["id"] = f"B{i}"
    toplam_h = sum(max(30.0, float(b.get("hedef_sn") or 0)) for b in bs) or 1.0
    for b in bs:   # hedefler toplamı UZUN_PLAN_SN'ye ölçeklenir (yerel, ek çağrı yok)
        b["hedef_sn"] = round(max(30.0, float(b.get("hedef_sn") or 0)) * UZUN_PLAN_SN / toplam_h, 1)
    hiz = {"kelime": 0, "sn": 0.0}

    def kelime_hizi() -> float:
        return hiz["kelime"] / hiz["sn"] if hiz["sn"] > 30 else KELIME_HIZI

    def bolum_yaz(bi: int, onceki: list[dict], kullanim: dict, hedef_sn: float,
                  ilk_hatalar: list[str] | None = None) -> tuple[list[dict], float]:
        b = bs[bi]
        en_iyi, en_iyi_fark, en_iyi_sure, en_iyi_kul = None, None, 0.0, None
        hh: list[str] = list(ilk_hatalar or [])
        bas_no = 1 + max((int(c["id"][1:]) for c in onceki), default=0)   # geçici kimlikler çakışmaz
        hedef_konusma = hedef_sn * 0.9    # ≈%10 duraklama payı (zaman çizelgesi)
        # Faz-62d görsel kotası: belgesel toplamında en az EN_AZ_GORSEL['uzun'] farklı görsel → kalan ihtiyaç bölümlere
        onceki_g = {c["niyet"]["gorsel25d"]["gorsel_id"] for c in onceki if c["niyet"]["tur"] == "gorsel25d"}
        sonrakiler = {x["id"] for x in bs[bi + 1:]}
        kalan = 1 if any(c.get("bolum") in sonrakiler for c in onceki) else len(bs) - bi
        gerek = max(0, EN_AZ_GORSEL["uzun"] - len(onceki_g))
        en_az_yeni = min(len(gorseller) - len(onceki_g), -(-gerek // kalan))
        for d in range(1, deneme + 1):
            kul = dict(kullanim)
            hedef_kelime = int(hedef_sn * 0.9 * kelime_hizi())
            try:
                y = iste(bolum_istemi(konu, ara, taslak, b, onceki, gorseller, katalog, kul, hedef_kelime, hh,
                                      bi == 0, bi == len(bs) - 1, en_az_yeni), f"uzun_{b['id']}")
            except (json.JSONDecodeError, TypeError) as e:
                hh = [f"yanıt JSON değil: {e}"]
                continue
            cs, hh = bolum_cumleleri(y, ara, konu, gorseller, katalog, kul, b["id"], bas_no, onceki, en_az_yeni)
            if hh:
                gecmis.append({"adim": b["id"], "deneme": d, "hatalar": hh[:10]})
                log("senaryo", f"{b['id']} deneme {d}: {len(hh)} hata — {hh[:3]}")
                continue
            sureler = olc(cs)
            sure = sum(v["sure_sn"] for v in sureler.values())
            hiz["kelime"] += sum(len(re.findall(r"\w+", c["metin"])) for c in cs)
            hiz["sn"] += sure
            fark = sure / hedef_konusma
            gecmis.append({"adim": b["id"], "deneme": d, "hatalar": [], "konusma_sn": round(sure, 1), "hedef_sn": hedef_sn})
            log("senaryo", f"{b['id']} deneme {d}: {len(cs)} cümle, konuşma {sure:.0f} sn (hedef {hedef_sn:.0f})")
            if en_iyi is None or abs(1 - fark) < abs(1 - en_iyi_fark):
                en_iyi, en_iyi_fark, en_iyi_sure, en_iyi_kul = cs, fark, sure, kul
            if 0.8 <= fark <= 1.25:
                break
            eksik = int((hedef_konusma - sure) * kelime_hizi())
            hh = [f"ölçülen konuşma {sure:.0f} sn, hedef {hedef_konusma:.0f} sn: " +
                  (f"yaklaşık {eksik} kelime daha yaz (yeni doğrulanmış bilgiyle, tekrar etmeden)" if eksik > 0 else
                   f"yaklaşık {-eksik} kelime kısalt")]
        if en_iyi is None:
            raise UretimHatasi("senaryo", f"{b['id']} bölümü kapıdan geçmedi: {hh[:6]}")
        kullanim.clear()
        kullanim.update(en_iyi_kul)
        return en_iyi, en_iyi_sure

    def kur(bolum_cs: list[list[dict]]) -> dict:
        cs, no = [], 1
        for grup in bolum_cs:
            for c in grup:
                cs.append(dict(c, id=f"S{no}"))
                no += 1
        return {"surum": 1, "konu": konu["kimlik"], "format": "uzun", "baslik": taslak.get("baslik") or konu["baslik"],
                "bolumler": [{"id": b["id"], "baslik": str(b["baslik"])[:60], "roller": list(b["roller"])} for b in bs],
                "cumleler": cs, "kanca": cs[0]["id"], "final": cs[-1]["id"]}

    bolum_cs: list[list[dict]] = []
    kullanim: dict = {}
    for bi in range(len(bs)):
        onceki = [c for g in bolum_cs for c in g]
        cs, _ = bolum_yaz(bi, onceki, kullanim, bs[bi]["hedef_sn"])
        bolum_cs.append(cs)
    a, b_ = konu["hedef_sure_sn"]
    for tur in range(onarim + 1):
        s = normalize_senaryo(kur(bolum_cs))   # Shorts ile ortak adaptör (kanca/final = ilk/son cümle kimliği)
        h = sozlesme.senaryo_denetle(s, ara)
        sureler = olc(s["cumleler"])
        if not h:
            h, _ = anlati.uzun_denetle(s, sureler)
        toplam = sahne_bolucu.toplam_sure(sahne_bolucu.zaman_cizelgesi(s, sureler))
        if not a <= toplam <= b_:
            h.append(f"ölçülen toplam süre {toplam:.0f} sn ({toplam / 60:.1f} dk); hedef {a}–{b_} sn")
        gecmis.append({"adim": "butun", "tur": tur, "toplam_sn": toplam, "hatalar": h[:10]})
        log("senaryo", f"bütün senaryo (tur {tur}): {len(s['cumleler'])} cümle, {toplam / 60:.1f} dk, {len(h)} hata")
        if not h:
            return s, gecmis
        if tur == onarim:
            break
        yapisal = [e for e in h if not e.startswith("ölçülen toplam süre")]
        gerek = UZUN_PLAN_SN - toplam if not a <= toplam <= b_ else 0.0
        bolum_of = {c["id"]: c["bolum"] for c in s["cumleler"]}
        konusma = {x["id"]: sum(sureler[c["id"]]["sure_sn"] for c in s["cumleler"] if c["bolum"] == x["id"]) for x in bs}
        if yapisal:   # hatanın geçtiği ilk bölüm, hatalar geri beslenerek yeniden yazılır
            adlar = [bolum_of[i] for e in yapisal for i in re.findall(r"\bS\d+\b", e) if i in bolum_of]
            if not adlar and any("kanca" in e for e in yapisal):
                adlar = [bs[0]["id"]]
            if not adlar:
                break   # bölüme bağlanamayan yapısal hata (ör. bölüm sayısı) → açık hata
            bi = next(i for i, x in enumerate(bs) if x["id"] == adlar[0])
            geri = [e for e in yapisal if any(i in e for i, bb in bolum_of.items() if bb == bs[bi]["id"])] or yapisal
        else:         # süre onarımı: hedefinden en çok sapan bölüm
            bi = max(range(len(bs)), key=lambda i: (bs[i]["hedef_sn"] * 0.9 - konusma[bs[i]["id"]]) * (1 if gerek > 0 else -1))
            geri = []
        hedef = max(30.0, (konusma[bs[bi]["id"]] + gerek) / 0.9) if gerek else bs[bi]["hedef_sn"]
        onceki = [c for j, g in enumerate(bolum_cs) if j != bi for c in g]
        kullanim = {}
        for c in onceki:
            n = c["niyet"]
            if n["tur"] == "gorsel25d":
                kullanim[n["gorsel25d"]["gorsel_id"]] = kullanim.get(n["gorsel25d"]["gorsel_id"], 0) + 1
        kullanim.update({x["katalog"]: 1 for x in katalog if any(c["niyet"] == x["niyet"] for c in onceki)})
        log("senaryo", f"onarım: {bs[bi]['id']} yeniden yazılıyor (hedef {hedef:.0f} sn; {len(geri)} hata geri beslendi)")
        bolum_cs[bi], _ = bolum_yaz(bi, onceki, kullanim, hedef, geri)
    raise UretimHatasi("senaryo", f"uzun senaryo kapılardan geçmedi: {h[:8]}")


def dogrulama_plani(fikstur: Path, is_kok: Path, parca_sayisi: int = 4, topla=None, planla_fn=None) -> dict:
    """CI doğrulaması (Gemini YOK). Çıktılar açıkça 'dogrulama_fiksturu' olarak işaretlenir; üretim değildir.
    - shorts: pilot şablonun kendi araştırma + senaryosu, fikstürdeki niyet değişiklikleriyle (harita, Commons 2.5D).
    - uzun (fikstürde 'uzun' varsa): aynı pilot cümleleri 16:9 bölümlü plana döner; YALNIZCA MOTOR doğrulanır
      (16:9 harita / 2.5D / 3D render, paralel parçalar, uzun kurgu, SRT, loudnorm, QA). 15–20 dk anlatı kapısı
      (anlati) bu fikstürde ölçülür ama atlanır ve raporda açıkça yazılır; hedef süre fikstürün kendi aralığıdır."""
    f = json.loads(Path(fikstur).read_text())
    sablon = PILOTLAR / f["sablon"]
    gorseller = gorselleri_topla(json.loads((sablon / "konu.json").read_text())["kimlik"] + "-dogrulama",
                                 f.get("gorseller", []), topla=topla)
    r: dict = {"dogrulama_fiksturu": True, "gorseller": gorseller, "isler": []}
    for bicim in ["shorts"] + (["uzun"] if f.get("uzun") else []):
        k = json.loads((sablon / "konu.json").read_text())
        ek = f.get("uzun") if bicim == "uzun" else {}
        k = dict(k, kimlik=f"{k['kimlik']}-dogrulama" + ("-uzun" if bicim == "uzun" else ""))
        if bicim == "uzun":
            k.update(format="uzun", hedef_sure_sn=ek["hedef_sure_sn"])
        is_ = is_kok / k["kimlik"]
        shutil.rmtree(is_, ignore_errors=True)
        is_.mkdir(parents=True)
        ara = json.loads((sablon / "arastirma.json").read_text())
        sen = json.loads((sablon / "senaryo.json").read_text())
        ara["konu"] = sen["konu"] = k["kimlik"]
        degisiklik = (ek.get("niyet_degisiklikleri") if bicim == "uzun" else f.get("niyet_degisiklikleri")) or {}
        degisen = []
        for c in sen["cumleler"]:
            d = degisiklik.get(c["id"])
            if bicim == "uzun":
                c["bolum"] = ek["cumle_bolumleri"][c["id"]]
            if not d:
                continue
            if d["tur"] == "gorsel25d":
                if d["gorsel_sira"] >= len(gorseller):
                    log("dogrulama", f"{c['id']}: 2.5D görsel toplanamadı; cümle 3D kalır")
                    continue
                g = gorseller[d["gorsel_sira"]]
                c["niyet"] = {"tur": "gorsel25d", "gorsel25d": {"gorsel_id": g["gorsel_id"], **({"hareket": d["hareket"]}
                              if d.get("hareket") else {})}, "aciklama": d.get("aciklama") or g["aciklama"]}
            else:
                c["niyet"] = {x: v for x, v in d.items()}
            degisen.append(c["id"])
        if bicim == "uzun":
            sen.update(format="uzun", bolumler=ek["bolumler"])
            sen.pop("ana_fikir", None)
        kullanilan = sorted({c["niyet"]["gorsel25d"]["gorsel_id"] for c in sen["cumleler"] if c["niyet"]["tur"] == "gorsel25d"})
        for ad, v in (("konu.json", k), ("arastirma.json", ara), ("senaryo.json", sen),
                      ("gorsel_kapisi.json", {"bicim": bicim, "dogrulama": True, "en_az": EN_AZ_GORSEL[bicim],
                                              "kullanilan": kullanilan,
                                              "not": "doğrulama fikstürü: en az görsel kapısı uygulanmaz; tekrar yasağı uygulanır"}),
                      ("gorsel_atiflari.json", [g_ for g_ in gorseller if g_["gorsel_id"] in kullanilan])):
            (is_ / ad).write_text(json.dumps(v, ensure_ascii=False, indent=1))
        p = (planla_fn or uretim_hatti_planla)(is_)
        hatalar = {a: b for a, b in p["hatalar"].items() if b}
        atlanan = {"anlati": hatalar.pop("anlati")} if bicim == "uzun" and "anlati" in hatalar else {}
        ri = {"bicim": bicim, "kimlik": k["kimlik"], "is": str(is_), "degisen": degisen,
              "plan": {"gecti": not hatalar, "toplam_sure_sn": p.get("toplam_sure_sn"), "hatalar": hatalar}}
        if atlanan:
            ri["anlati_kapisi_atlandi"] = "yalnızca motor doğrulaması (fikstür 15–20 dk anlatı değildir)"
            ri["atlanan_hatalar"] = atlanan
        if hatalar:
            raise UretimHatasi("plan", f"doğrulama planı ({bicim}) kapıdan geçmedi: {hatalar}")
        plan = json.loads((is_ / "cekim_plani.json").read_text())
        ri["cekimler"] = {t: [c["id"] for c in plan["cekimler"] if c["tur"] == t] for t in ("3d", "harita", "gorsel25d")}
        ri["parcalar"] = parcalara_bol(plan, parca_sayisi)
        (is_ / "parcalar.json").write_text(json.dumps(ri["parcalar"], ensure_ascii=False))
        r["isler"].append(ri)
    r["kimlik"] = r["isler"][0]["kimlik"]
    r["parcalar"] = [dict(p, kimlik=i["kimlik"]) for i in r["isler"] for p in i["parcalar"]]
    return r


# ------------------------------------------------------------------ render / kurgu

def render_kapisi(is_: Path) -> dict:
    """Faz-62d: render/kurgu, planla'nın yazdığı görsel kapısı kaydı ve çekim planı tutarlı değilse başlamaz:
    her tarihî görsel en çok bir çekimde, en az EN_AZ_GORSEL[biçim] farklı görsel. Doğrulama fikstürü açıkça muaf."""
    f = is_ / "gorsel_kapisi.json"
    if not f.exists():
        raise UretimHatasi("gorsel", "gorsel_kapisi.json yok: plan görsel kapısından geçmemiş; render yapılmaz", 5)
    k = json.loads(f.read_text())
    if k.get("dogrulama"):
        log("gorsel", "doğrulama fikstürü: en az görsel kapısı uygulanmaz (üretim değildir)")
        return k
    plan = json.loads((is_ / "cekim_plani.json").read_text())
    ids = [c["gorsel25d"]["gorsel_id"] for c in plan["cekimler"] if c["tur"] == "gorsel25d" and c.get("gorsel25d")]
    tekrar = sorted({x for x in ids if ids.count(x) > 1})
    if tekrar or len(set(ids)) < k["en_az"]:
        raise UretimHatasi("gorsel", f"çekim planında {len(set(ids))} farklı tarihî görsel (en az {k['en_az']})"
                                     + (f"; tekrar eden: {tekrar}" if tekrar else "") + "; render yapılmaz", 5)
    return k


def parca_render(is_: Path, parca: int) -> dict:
    from motor.uretim import render
    render_kapisi(is_)
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
    render_kapisi(is_)
    t = time.time()
    k = kurgu.uret(is_)
    konu = json.loads((is_ / "konu.json").read_text())["kimlik"]
    atif = is_ / "gorsel_atiflari.json"
    if atif.exists():   # Faz-62d: kullanılan her görselin kaynağı; CC-BY/CC-BY-SA için yazar + lisans (yayında zorunlu)
        cikti.mkdir(parents=True, exist_ok=True)
        satir = []
        for g in json.loads(atif.read_text()):
            a = g.get("atif") or {}
            satir.append(f"- {g.get('commons_baslik') or g['gorsel_id']} — lisans: {g.get('lisans')}"
                         + (f" — yazar: {a.get('yazar')} — {a.get('lisans')}" if a else "") + f" — {g.get('kaynak_url')}")
        (cikti / f"{konu}_gorsel_atiflari.txt").write_text(
            "Tarihî görseller (Wikimedia Commons). CC-BY / CC-BY-SA görseller yayında atıf ister.\n" + "\n".join(satir) + "\n",
            encoding="utf-8")
    r = {"durum": k.get("durum"), "format": k.get("format", "shorts"), "sure_sn": round(time.time() - t, 1),
         "onbellekten_3d": sum(1 for c in k.get("cekimler", []) if c.get("onbellekten")),
         **{x: k[x] for x in ("hatalar", "neden", "eksik", "cekim", "render", "olculen", "kalite_kontrol", "bolumler", "srt",
                        "altyazi_gomulu") if x in k}}
    mp4 = ayar.ONBELLEK / "kurgu" / konu / f"{konu}.mp4"
    if mp4.exists():
        cikti.mkdir(parents=True, exist_ok=True)
        hedef = cikti / f"{konu}.mp4"
        shutil.copy2(mp4, hedef)
        for ek in ("uretim_raporu.json", "altyazi.json", f"{konu}.srt"):
            if (mp4.parent / ek).exists():
                shutil.copy2(mp4.parent / ek, cikti / (f"{konu}_{ek}" if not ek.endswith(".srt") else ek))
        r["mp4"] = {"yol": str(hedef), **ffprobe(hedef)}
    srt = cikti / f"{konu}.srt"
    if r.get("format") == "uzun":
        r["srt_dosyasi"] = str(srt) if srt.exists() else None
    r["gecti"] = bool(r.get("mp4")) and k.get("durum") == "TAMAM" and (r.get("format") != "uzun" or srt.exists())
    return r


# ------------------------------------------------------------------ CLI

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Faz-62b/62c otonom üretim — shorts | uzun | her_ikisi (yükleme yapmaz)")
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
    ek = (f"_{a.kimlik}" if a.kimlik else "") + (f"_{a.parca}" if a.komut == "render" else "")
    rapor_yolu = cikti / f"otonom_{a.komut}{ek if a.komut in ('render', 'kurgu') else ''}.json"
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
                matris = [{"kimlik": p["kimlik"], "parca": p["parca"]} for p in r["parcalar"]]
                with open(gh, "a") as f:
                    f.write(f"kimlik={r['kimlik']}\nkimlikler={json.dumps([i['kimlik'] for i in r['isler']])}\n"
                            f"matris={json.dumps(matris)}\n")
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
