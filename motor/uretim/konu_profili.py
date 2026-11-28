"""Faz-66 — Dinamik tarihî konu profili ve üretim hazırlık kapısı.

Pilot şablonu (motor/uretim/pilotlar/<kimlik>/konu.json) olmayan bir konu için araştırma havuzunun (kaynak_kesif.
havuz_olustur) DOĞRULANMIŞ ve TARTIŞMALI kayıtlarından konu profili kurar:
  konu.json            konu.schema.json'a uyar (dönemler = gerçekten var olan 3D kitleri; harita = şematik evreler)
  profil_meta.json     her alanın hangi kayıtlardan geldiği, kesinlik/belirsizlikler, kit eşleşmesi, girdi özeti
  uc_boyut_katalogu    planlayıcının GERÇEKTEN kurabildiği 3D niyetleri (uzun biçim 3D kataloğu; pilot senaryosunun yerine)

Deterministiktir: LLM yok, zaman/rastgelelik yok; aynı havuz → bayt bayt aynı profil (girdi_ozeti SHA-256).
Uydurmaz: kayıtlarda geçmeyen taraf, birlik, kişi, tarih ya da sonuç yazılmaz; kiti olmayan taraf haritada gösterilir
ama 3D'ye girmez; tartışmalı bilgi 'tartismali' olarak işaretlenir, kesin hükme çevrilmez (ör. sonuç evresi).
profil_denetle (üretim hazırlık kapısı) geçmeden profil üretime alınmaz. Render/kurgu ile bağı yoktur (yalnız veri).
Kurallar: kurallar/konu_profili.yaml.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter

from motor.uretim import veri

SURUM = "konu-profili-1"
GUVEN = ("dogrulanmis", "tartismali")
HARITA_TURLERI = ("piyade", "suvari", "top", "karargah")
OK_TURLERI = ("saldiri", "geri_cekilme", "kacis")
_UNVAN = {"sultan", "pasa", "pasha", "bey", "han", "khan", "sah", "shah", "mirza", "padisah", "hukumdar", "emir",
          "kral", "king", "kralice", "queen", "imparator", "emperor", "hakan", "kanuni", "vezir", "duke", "dukasi",
          "lord", "general", "komutan", "serasker", "beylerbeyi", "firavun", "pharaoh", "consul", "konsul", "caesar"}
_AYLAR_TR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
_AYLAR = {"ocak", "subat", "mart", "nisan", "mayis", "haziran", "temmuz", "agustos", "eylul", "ekim", "kasim", "aralik",
          "january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"}
_KAZANMA = ("zafer", "galip", "galeb", "kazan", "yendi", "yenmi", "victo", "won", "triump", "bozguna ugrat")
_KAYBETME = ("yenil", "maglu", "kaybet", "bozgun", "hezim", "routed", "lost")


class ProfilHatasi(Exception):
    pass


def kurallar() -> dict:
    return veri.kural("konu_profili")


def katla(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").replace("İ", "I").replace("ı", "i")).encode("ascii", "ignore").decode()
    return s.lower()


def sozcukler(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", katla((s or "").replace("’", " ").replace("'", " ")))


def _konumlar(sz: list[str], kok, tam) -> list[int]:
    kok, tam = tuple(kok or ()), set(tam or ())
    return [i for i, w in enumerate(sz) if w in tam or (kok and w.startswith(kok))]


def _eslesir(sz: list[str], kok, tam) -> int | None:
    """İlk eşleşen sözcüğün konumu (yoksa None)."""
    k = _konumlar(sz, kok, tam)
    return k[0] if k else None


def kisa_ad(metin: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", katla(metin)).strip("-")


def donem_etiketi(yil: int) -> str:
    yy = (abs(yil) - 1) // 100 + 1
    return f"{yy}yy" if yil > 0 else f"mo{yy}yy"


# ------------------------------------------------------------------ girdi

def kartlar(havuz: dict) -> list[dict]:
    """Profile girdi olan kayıtlar: yalnız doğrulanmış ve tartışmalı (belirsizler girmez), kimlik sırasıyla."""
    return sorted((k for k in havuz.get("kayitlar", []) if k.get("durum") in GUVEN), key=lambda k: k["id"])


def girdi_ozeti(konu: str, havuz: dict) -> str:
    ozet = [konu, havuz.get("konum"), [[k["id"], k["durum"], k["iddia"], k.get("yil"), k.get("iddia_atomlari"),
                                         k.get("bagimsiz_kaynak_sayisi")] for k in kartlar(havuz)]]
    return hashlib.sha256(json.dumps(ozet, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def yer_adi(konu: str) -> str:
    genel = set(kurallar()["genel_sozcukler"])
    kel = [w for w in re.findall(r"[^\W\d_][\w'’-]*", konu) if katla(re.split(r"['’]", w)[0]) not in genel]
    return " ".join(re.split(r"['’]", w)[0] for w in kel) or konu.strip()


# ------------------------------------------------------------------ çıkarım

def tarih_bul(ks: list[dict]) -> dict:
    """En çok DOĞRULANMIŞ kayıtta geçen yıl (eşitlikte küçük yıl); yoksa tartışmalı kayıtlardan (kesinlik tartışmalı).
    Gün/ay: o yılı taşıyan kayıtların gun_ay atomlarından en sık olan."""
    def yillar(k):
        return sorted({int(y) for y in ((k.get("iddia_atomlari") or {}).get("yil") or ([k["yil"]] if k.get("yil") is not None else []))})
    for durum in GUVEN:
        say = Counter(y for k in ks if k["durum"] == durum for y in yillar(k))
        if say:
            break
    else:
        return {"yil": None, "kesinlik": "yok", "kartlar": [], "alternatifler": []}
    (yil, n), *diger = sorted(say.items(), key=lambda x: (-x[1], x[0]))
    kart = sorted(k["id"] for k in ks if yil in yillar(k))
    gun = Counter(tuple(g) for k in ks if yil in yillar(k) for g in (k.get("iddia_atomlari") or {}).get("gun_ay") or [])
    gun_ay = list(sorted(gun.items(), key=lambda x: (-x[1], x[0]))[0][0]) if gun else None
    kesin = durum == "dogrulanmis" and not any(c == n for _, c in diger)
    metin = (f"{gun_ay[0]} {_AYLAR_TR[gun_ay[1] - 1]} " if gun_ay else "") + (f"{yil}" if yil > 0 else f"MÖ {-yil}")
    return {"yil": yil, "gun_ay": gun_ay, "metin": metin, "kesinlik": "kesin" if kesin else "tartismali", "kartlar": kart,
            "alternatifler": [{"yil": y, "kayit_sayisi": c} for y, c in diger]}


def taraflar_bul(ks: list[dict], yil: int | None) -> list[dict]:
    k = kurallar()
    out = []
    for ad, t in k["taraflar"].items():
        kart = [c["id"] for c in ks if _eslesir(sozcukler(c["iddia"]), t["kok"], t["tam"]) is not None]
        if len(kart) >= k["taraf_en_az_kart"]:
            out.append((ad, t, kart))
    out.sort(key=lambda x: (-len(x[2]), x[0]))
    secili = []
    for ad, t, kart in out[: k["en_cok_taraf"]]:
        kit, uyg, fark = kit_sec(t.get("kitler") or [], yil)
        durumlar = {c["durum"] for c in ks if c["id"] in kart}
        secili.append({"anahtar": kit or f"{ad}-{donem_etiketi(yil) if yil else 'donem'}", "sozluk": ad, "ad": t["ad"],
                       "renk": list(t["renk"]), "kit": kit, "kit_uygunlugu": uyg, "kit_farki_yil": fark,
                       "kesinlik": "kesin" if "dogrulanmis" in durumlar else "tartismali", "kartlar": kart})
    return secili


def kit_sec(adaylar: list[str], yil: int | None) -> tuple[str | None, str, int | None]:
    """(kit, 'tam' | 'yakin' | 'yok', aralık dışı yıl farkı). Kit aralığı kurallarda; tolerans dışı → kit yok."""
    if yil is None:
        return None, "yok", None
    k = kurallar()
    en = None
    for kit in adaylar:
        if kit not in k["kit_yillari"]:
            continue
        a, b = k["kit_yillari"][kit]
        fark = 0 if a <= yil <= b else min(abs(yil - a), abs(yil - b))
        if fark <= k["kit_tolerans_yil"] and (en is None or fark < en[1]):
            en = (kit, fark)
    if en is None:
        return None, "yok", None
    return en[0], "tam" if en[1] == 0 else "yakin", en[1]


def birlikler_bul(ks: list[dict], taraflar: list[dict]) -> dict[str, list[dict]]:
    """Taraf → birlik türleri. Kayıttaki her birlik sözcüğü, kendinden ÖNCEKİ en yakın taraf adına atanır (Türkçe ve
    İngilizcede taraf sıfatı birlikten önce gelir: "<taraf> topçuları", "<side> cavalry"); önünde taraf yoksa
    sonraki en yakın tarafa. İki tarafı birden anan cümlede birlik iki tarafa birden yazılmaz. Birliği geçmeyen tarafa
    tek temsilî 'Ordu' (piyade imi) bloğu."""
    k = kurallar()
    sozluk = k["taraflar"]
    bulunan: dict[str, dict[str, list]] = {t["anahtar"]: {} for t in taraflar}
    for c in ks:
        sz = sozcukler(c["iddia"])
        yer = [(i, j) for j, t in enumerate(taraflar)
               for i in _konumlar(sz, sozluk[t["sozluk"]]["kok"], sozluk[t["sozluk"]]["tam"])]
        if not yer:
            continue
        for tur, b in k["birlik_turleri"].items():
            for i in _konumlar(sz, b["kok"], b["tam"]):
                once = [x for x in yer if x[0] < i]
                j = (max(once, key=lambda x: (x[0], -x[1])) if once else min(yer, key=lambda x: (x[0], x[1])))[1]
                kart = bulunan[taraflar[j]["anahtar"]].setdefault(tur, [])
                if c["id"] not in kart:
                    kart.append(c["id"])
    out = {}
    for t in taraflar:
        b = [{"tur": tur, "harita": x["harita"], "rol": x["rol"], "ad": x["ad"], "kartlar": sorted(bulunan[t["anahtar"]][tur]),
              "temsili": False} for tur, x in k["birlik_turleri"].items() if tur in bulunan[t["anahtar"]]]
        out[t["anahtar"]] = b or [{"tur": "piyade", "harita": "piyade", "rol": "piyade", "ad": "Ordu", "kartlar": [],
                                   "temsili": True}]
    return out


# romen rakamı ("II.") büyük harfli sözcükten ÖNCE denenir: "Kral II. Lajos" bölünmez
_AD = re.compile(r"(?:(?:[IVX]{1,4})\.\s)?[A-ZÇĞİÖŞÜ][\wçğıöşüâîû-]+(?:\s+(?:[IVX]{1,4}\.(?=\s)|[A-ZÇĞİÖŞÜ][\wçğıöşüâîû-]+))*")


def adlar_bul(ks: list[dict], dislanan: set[str], genel: set[str] = frozenset()) -> tuple[list[dict], list[dict]]:
    """(kişiler, diğer adlar). Ad: ardışık büyük harfli sözcükler (romen rakamı önekiyle). Kişi: unvan taşıyan ya da
    romen rakamlı ad. Taraf/yer kökleriyle başlayan sözcük ya da genel/ay sözcüğü taşıyan adlar dışlanır. Bir adın içinde
    geçtiği daha uzun ad varsa ('Lajos' ⊂ 'Kral II. Lajos') kayıtları o en uzun ada birleşir. En az kisi_en_az_kart
    ayrı kayıtta geçen adlar."""
    k = kurallar()
    say: dict[str, set] = {}
    for c in ks:
        for m in _AD.finditer(c["iddia"]):
            ad = re.split(r"['’]", m.group(0))[0].strip().rstrip(".")
            sz = sozcukler(ad)
            if (not sz or any(w.startswith(tuple(dislanan)) or w in genel or w in _AYLAR for w in sz)
                    or set(sz) <= _UNVAN or all(re.fullmatch(r"[ivx]+", w) for w in sz)):
                continue
            if m.start() == 0 and len(sz) == 1 and sz[0] not in _UNVAN:
                continue   # cümle başındaki tek büyük harfli sözcük ad sayılmaz
            say.setdefault(ad, set()).add(c["id"])

    def icinde(a, b):
        return a != b and re.search(rf"(?<!\w){re.escape(a)}(?!\w)", b) is not None
    for a in sorted(say, key=len):
        hedef = sorted((b for b in say if icinde(a, b)), key=lambda b: (-len(b), b))
        if hedef:
            say[hedef[0]] |= say.pop(a)
    adlar = sorted(((a, sorted(v)) for a, v in say.items() if len(v) >= k["kisi_en_az_kart"]), key=lambda x: (-len(x[1]), x[0]))
    durum = {c["id"]: c["durum"] for c in ks}
    kisiler, diger = [], []
    for a, kart in adlar:
        kayit = {"ad": a, "kartlar": kart, "kesinlik": "kesin" if any(durum[i] == "dogrulanmis" for i in kart) else "tartismali"}
        sz = sozcukler(a)
        (kisiler if (set(sz) & _UNVAN or re.match(r"[IVX]{1,4}\.", a)) else diger).append(kayit)
    return kisiler[: k["en_cok_kisi"]], diger[: k["en_cok_kisi"]]


def sonuc_bul(ks: list[dict], taraflar: list[dict]) -> dict:
    """Kazanan: kazanma/kaybetme sözcüğü taşıyan (ikisini birden taşımayan) kayıtta cümlenin öznesi sayılan ilk taraf.
    'kesin' yalnız doğrulanmış kayıtlar tek tarafı gösteriyor ve karşı oy yoksa; aksi hâlde 'tartismali' ya da 'yok'."""
    if len(taraflar) < 2:
        return {"kesinlik": "yok", "kazanan": None, "oylar": {}}
    sozluk = kurallar()["taraflar"]
    oy = {d: Counter() for d in GUVEN}
    kart = {d: {} for d in GUVEN}
    for c in ks:
        m = katla(c["iddia"])
        kz, kb = any(r in m for r in _KAZANMA), any(r in m for r in _KAYBETME)
        if kz == kb:
            continue
        sz = sozcukler(c["iddia"])
        yer = sorted((i, t["anahtar"]) for t in taraflar
                     if (i := _eslesir(sz, sozluk[t["sozluk"]]["kok"], sozluk[t["sozluk"]]["tam"])) is not None)
        if not yer:
            continue
        ozne = yer[0][1]
        kazanan = ozne if kz else next((t["anahtar"] for t in taraflar if t["anahtar"] != ozne), None)
        if kazanan:
            oy[c["durum"]][kazanan] += 1
            kart[c["durum"]].setdefault(kazanan, []).append(c["id"])
    d, t = oy["dogrulanmis"], oy["tartismali"]
    if len(d) == 1 and not (set(t) - set(d)):
        kz = next(iter(d))
        return {"kesinlik": "kesin", "kazanan": kz, "oylar": {"dogrulanmis": dict(d), "tartismali": dict(t)},
                "kartlar": sorted(kart["dogrulanmis"][kz] + kart["tartismali"].get(kz, []))}
    toplam = d + t
    if toplam:
        aday = sorted(toplam.items(), key=lambda x: (-x[1], x[0]))[0][0]
        return {"kesinlik": "tartismali", "kazanan": None, "aday": aday,
                "oylar": {"dogrulanmis": dict(d), "tartismali": dict(t)},
                "kartlar": sorted({i for dd in kart.values() for v in dd.values() for i in v})}
    return {"kesinlik": "yok", "kazanan": None, "oylar": {}}


def olay_turu(ks: list[dict]) -> dict:
    k = kurallar()
    kart = [c["id"] for c in ks if any(r in " ".join(sozcukler(c["iddia"])) for r in k["deniz_kokleri"])]
    return {"tur": "deniz" if len(kart) >= k["deniz_en_az_kart"] else "kara", "deniz_kartlari": kart}


# ------------------------------------------------------------------ harita (şematik evreler)

_YAN = {0: {"cephe": 3.2, "arka": 1.9, "yon": 0, "isaret": 1}, 1: {"cephe": 6.8, "arka": 8.1, "yon": 180, "isaret": -1}}


def _birlik_dizisi(taraf: dict, i: int) -> list[dict]:
    y = _YAN[min(i, 1)]
    x_ofset = 0.0 if i < 2 else 1.5   # üçüncü taraf (müttefik) ikinci tarafın yanında
    out = [{"id": f"{kisa_ad(taraf['sozluk'])}_karargah", "taraf": taraf["anahtar"], "ad": f"{taraf['ad']} — Karargâh",
            "tur": "karargah", "konum": [round(5.0 + x_ofset, 2), y["arka"]], "yon_derece": y["yon"]}]
    yerler = {"suvari": [2.2, 7.8], "piyade": [5.0], "okcu": [3.6], "top": [6.4]}
    for b in taraf["birlikler"]:
        for j, x in enumerate(yerler[b["tur"]]):
            ad = b["ad"] if len(yerler[b["tur"]]) == 1 else f"{b['ad']} ({'sol' if j == 0 else 'sağ'} kanat)"
            out.append({"id": f"{kisa_ad(taraf['sozluk'])}_{b['tur']}{j + 1}", "taraf": taraf["anahtar"], "ad": ad,
                        "tur": b["harita"], "konum": [round(min(9.6, x + x_ofset), 2), y["cephe"]], "yon_derece": y["yon"],
                        **({"buyukluk": 0.8} if b["tur"] == "top" else {})})
    return out


def _ilerlet(birlikler: list[dict], taraflar: list[dict], km: float) -> list[dict]:
    yon = {t["anahtar"]: _YAN[min(i, 1)]["isaret"] for i, t in enumerate(taraflar)}
    return [dict(b, konum=[b["konum"][0], round(min(9.8, max(0.2, b["konum"][1] + yon[b["taraf"]] * km)), 2)])
            if b["tur"] != "karargah" and b["taraf"] in yon else dict(b) for b in birlikler]


def harita_kur(yer: str, tarih: dict, taraflar: list[dict], sonuc: dict, kart_ids: list[str]) -> dict:
    tr = {t["anahtar"]: {"ad": t["ad"], "renk": t["renk"]} for t in taraflar}
    dizi = [b for i, t in enumerate(taraflar) for b in _birlik_dizisi(t, i)]
    a, b = taraflar[0]["anahtar"], taraflar[1]["anahtar"]
    baslik = f"{yer} · {tarih['metin']}" + ("" if tarih.get("kesinlik") == "kesin" else " (tarih tartışmalı)")
    evreler = [{"id": "E1", "baslik": baslik, "alt_baslik": "Ordular karşı karşıya", "birlikler": dizi, "oklar": [],
                "odak_km": [5.0, 5.0]}]
    e2 = _ilerlet(dizi, taraflar, 0.9)
    evreler.append({"id": "E2", "baslik": "Muharebe başlıyor", "alt_baslik": "Cepheler çarpışıyor", "birlikler": e2,
                    "oklar": [{"taraf": a, "yol": [[5.0, 3.6], [5.0, 4.3], [5.0, 4.9]], "tur": "saldiri"},
                              {"taraf": b, "yol": [[5.0, 6.4], [5.0, 5.7], [5.0, 5.1]], "tur": "saldiri"}],
                    "odak_km": [5.0, 5.0]})
    if sonuc["kesinlik"] == "kesin":   # yalnız doğrulanmış sonuç gösterilir; tartışmalı sonuç evre olarak çizilmez
        kz = sonuc["kazanan"]
        kb = b if kz == a else a
        isaret = 1 if kz == a else -1
        e3 = [dict(x, dagildi=True) if x["taraf"] == kb else x for x in _ilerlet(e2, [t for t in taraflar if t["anahtar"] == kz], 0.6)]
        y0 = 5.4 if isaret == 1 else 4.6
        evreler.append({"id": "E3", "baslik": f"{tr[kz]['ad']} üstün geliyor", "alt_baslik": f"{tr[kb]['ad']} ordusu çekiliyor",
                        "birlikler": e3,
                        "oklar": [{"taraf": kz, "yol": [[5.0, y0 - isaret * 0.8], [5.0, y0], [5.0, y0 + isaret * 1.0]], "tur": "saldiri"},
                                  {"taraf": kb, "yol": [[5.0, y0 + isaret * 1.4], [5.0, y0 + isaret * 2.2], [5.0, y0 + isaret * 3.0]],
                                   "tur": "kacis"}],
                        "odak_km": [5.0, y0]})
    return {"kaynak": f"Otomatik konu profili ({SURUM}) — araştırma kayıtları {', '.join(kart_ids)}; konumlar ve "
                      "diziliş şematik (kaynak birlik konumu vermez), arazi gösterilmez",
            "alan_km": [10, 10], "taraflar": tr, "arazi": {}, "evreler": evreler}


# ------------------------------------------------------------------ 3D katalog (planlayıcının kurabildiği niyetler)

def uc_boyut_katalogu(taraflar: list[dict], oyuncu_sec=None) -> list[dict]:
    from motor.uretim import planlayici
    oyuncu_sec = oyuncu_sec or planlayici.oyuncu_sec
    k = kurallar()
    out = []
    for t in taraflar:
        if not t["kit"]:
            continue
        roller = [b["rol"] for b in t["birlikler"] if b["rol"]] + ["komutan"]
        for rol in dict.fromkeys(roller):
            mesafe = "orta" if rol == "komutan" else "uzak"
            for e in k["rol_eylemleri"].get(rol, []):
                n = {"tur": "3d", "eylem": e, "mesafe": mesafe,
                     "roller": [{"rol": rol, "donem": t["kit"], "adet": 1 if rol == "komutan" else 6, "odak": True}]}
                if oyuncu_sec(dict(n, roller=[dict(n["roller"][0], adet=1)]), t["kit"])[0]:
                    out.append({"katalog": f"3D-{kisa_ad(t['sozluk'])}-{rol}", "aciklama": f"{t['ad']}: {rol} ({e})",
                                "niyet": n})
                    break
    return out


# ------------------------------------------------------------------ profil

def olustur(konu: str, havuz: dict, oyuncu_sec=None) -> tuple[dict, dict, list[dict]]:
    """(konu.json, profil_meta, 3D katalog). Yeterli girdi yoksa ProfilHatasi (eksik alanlar açıkça)."""
    k = kurallar()
    ks = kartlar(havuz)
    if len(ks) < k["kart_en_az"]:
        raise ProfilHatasi(f"profil için en az {k['kart_en_az']} doğrulanmış/tartışmalı kayıt gerekir ({len(ks)} var)")
    tarih = tarih_bul(ks)
    yer = yer_adi(konu)
    taraflar = taraflar_bul(ks, tarih["yil"])
    bl = birlikler_bul(ks, taraflar)
    for t in taraflar:
        t["birlikler"] = bl[t["anahtar"]]
    sozluk = k["taraflar"]
    dislanan = ({katla(w) for w in yer.split()} | {r for t in taraflar for r in sozluk[t["sozluk"]]["kok"] + sozluk[t["sozluk"]]["tam"]})
    kisiler, diger_adlar = adlar_bul(ks, dislanan, set(k["genel_sozcukler"]))
    sonuc = sonuc_bul(ks, taraflar)
    olay = olay_turu(ks)
    kitler = list(dict.fromkeys(t["kit"] for t in taraflar if t["kit"]))
    kart_ids = sorted({i for t in taraflar for i in t["kartlar"]} | set(tarih["kartlar"]))
    belirsiz = []
    if tarih["kesinlik"] != "kesin":
        belirsiz.append({"alan": "tarih", "aciklama": "tarih yalnız tartışmalı kayıtlarda ya da kayıtlar arasında eşit "
                         "destekli farklı yıllar var", "kartlar": tarih["kartlar"]})
    if sonuc["kesinlik"] == "tartismali":
        belirsiz.append({"alan": "sonuc", "aciklama": f"sonuç kaynaklarda tartışmalı (aday: {sonuc['aday']}); harita "
                         "sonuç evresi çizilmedi", "kartlar": sonuc["kartlar"]})
    for t in taraflar:
        if t["kesinlik"] != "kesin":
            belirsiz.append({"alan": f"taraf:{t['anahtar']}", "aciklama": "taraf yalnız tartışmalı kayıtlarda",
                             "kartlar": t["kartlar"]})
    for x in kisiler:
        if x["kesinlik"] != "kesin":
            belirsiz.append({"alan": f"kisi:{x['ad']}", "aciklama": "kişi yalnız tartışmalı kayıtlarda", "kartlar": x["kartlar"]})
    notlar = [f"Faz-66 otomatik konu profili ({SURUM}); kaynak: araştırma kayıtları {', '.join(kart_ids)}.",
              "Harita konumları şematiktir; arazi ve kesin birlik yerleri kaynaklarda yoktur."]
    for t in taraflar:
        if not t["kit"]:
            notlar.append(f"{t['ad']} için 3D dönem kiti yok: 3D'de gösterilmez, harita ve tarihî görsellerle anlatılır.")
        elif t["kit_uygunlugu"] == "yakin":
            notlar.append(f"{t['ad']} için en yakın kit {t['kit']} (olay yılı kit aralığının {t['kit_farki_yil']} yıl "
                          "dışında): kıyafet/teçhizat yaklaşık, temsilîdir.")
    if kisiler:
        notlar.append("Belirli kişiler temsilî karakterle gösterilir: " + ", ".join(x["ad"] for x in kisiler) + ".")
    for b in belirsiz:
        notlar.append(f"Tartışmalı ({b['alan']}): {b['aciklama']}.")
    ad_listesi = " ile ".join(t["ad"] for t in taraflar[:2]) if len(taraflar) >= 2 else (taraflar[0]["ad"] if taraflar else "taraflar")
    yil = tarih["yil"]
    kimlik = f"{kisa_ad(yer) or 'konu'}-{yil if (yil or 0) >= 0 else f'mo{-yil}'}" if yil is not None else kisa_ad(yer) or "konu"
    konu_json = {"surum": 1, "kimlik": kimlik, "baslik": konu.strip()[:100], "format": "shorts",
                 "hedef_sure_sn": list(k["hedef_sure_sn"]), "donemler": kitler, "dil": "tr",
                 "ozet": f"{yer} ({tarih.get('metin') or 'tarih bilinmiyor'}): {ad_listesi} arasındaki muharebe. "
                         "Otomatik profil; ayrıntılar ve kaynaklar araştırma kartlarındadır.",
                 "notlar": notlar}
    if len(taraflar) >= 2 and tarih["yil"] is not None:
        konu_json["harita"] = harita_kur(yer, tarih, taraflar, sonuc, kart_ids)
    katalog = uc_boyut_katalogu(taraflar, oyuncu_sec) if kitler else []
    meta = {"surum": SURUM, "uretici": "motor.uretim.konu_profili", "girdi_ozeti": girdi_ozeti(konu, havuz),
            "konu_basligi": konu, "yer": yer, "konum": havuz.get("konum"), "tarih": tarih, "olay_turu": olay,
            "taraflar": [{x: t[x] for x in ("anahtar", "sozluk", "ad", "kit", "kit_uygunlugu", "kit_farki_yil",
                                             "kesinlik", "kartlar", "birlikler")} for t in taraflar],
            "kisiler": kisiler, "diger_adlar": diger_adlar, "sonuc": sonuc, "belirsizlikler": belirsiz,
            "kartlar": [{"id": c["id"], "durum": c["durum"]} for c in ks if c["id"] in set(kart_ids)
                        | {i for x in kisiler for i in x["kartlar"]} | set(sonuc.get("kartlar", []))],
            "uc_boyut": {"kitler": kitler, "katalog": [x["katalog"] for x in katalog]}}
    return konu_json, meta, katalog


# ------------------------------------------------------------------ üretim hazırlık kapısı

def _sayi_cifti(v, alan) -> bool:
    return (isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v)
            and 0 <= v[0] <= alan[0] and 0 <= v[1] <= alan[1])


def harita_denetle(h: dict) -> list[str]:
    """Harita motorunun (harita.py) çizebileceği yapı: taraf adı/rengi, birlik türü/konumu, ok yolu, odak."""
    e = []
    tr = h.get("taraflar") or {}
    if len(tr) < 2:
        e.append(f"harita: en az 2 taraf gerekir ({len(tr)} var)")
    for k, t in tr.items():
        if not isinstance(t.get("ad"), str) or not t["ad"]:
            e.append(f"harita taraf {k}: ad yok")
        r = t.get("renk")
        if not (isinstance(r, list) and len(r) == 3 and all(isinstance(x, (int, float)) and 0 <= x <= 1 for x in r)):
            e.append(f"harita taraf {k}: renk [r, g, b] (0–1) değil")
    alan = h.get("alan_km") or [10, 10]
    if not (isinstance(alan, list) and len(alan) == 2 and all(isinstance(x, (int, float)) and x > 0 for x in alan)):
        return e + ["harita: alan_km iki pozitif sayı değil"]
    ids = [x.get("id") for x in h.get("evreler") or []]
    if not ids:
        e.append("harita: evre yok")
    if len(set(ids)) != len(ids):
        e.append("harita: evre kimlikleri tekrar ediyor")
    for ev in h.get("evreler") or []:
        if not ev.get("baslik"):
            e.append(f"harita {ev.get('id')}: başlık yok")
        bid = [b.get("id") for b in ev.get("birlikler") or []]
        if not bid:
            e.append(f"harita {ev.get('id')}: birlik yok")
        if len(set(bid)) != len(bid):
            e.append(f"harita {ev.get('id')}: birlik kimlikleri tekrar ediyor")
        for b in ev.get("birlikler") or []:
            if b.get("taraf") not in tr:
                e.append(f"harita {ev['id']}/{b.get('id')}: tanımsız taraf '{b.get('taraf')}'")
            if b.get("tur", "piyade") not in HARITA_TURLERI:
                e.append(f"harita {ev['id']}/{b.get('id')}: harita motorunun çizemediği tür '{b.get('tur')}'")
            if not _sayi_cifti(b.get("konum"), alan):
                e.append(f"harita {ev['id']}/{b.get('id')}: konum alan dışında ya da geçersiz ({b.get('konum')})")
        for i, o in enumerate(ev.get("oklar") or []):
            if o.get("taraf") not in tr:
                e.append(f"harita {ev['id']} ok {i}: tanımsız taraf '{o.get('taraf')}'")
            if o.get("tur", "saldiri") not in OK_TURLERI:
                e.append(f"harita {ev['id']} ok {i}: tanımsız tür '{o.get('tur')}'")
            yol = o.get("yol") or []
            if len(yol) < 2 or not all(_sayi_cifti(p, alan) for p in yol):
                e.append(f"harita {ev['id']} ok {i}: yol en az 2 nokta ve alan içinde olmalı")
        if "odak_km" in ev and not _sayi_cifti(ev["odak_km"], alan):
            e.append(f"harita {ev['id']}: odak alan dışında")
    return e


def profil_denetle(konu: dict, meta: dict, katalog: list[dict], bicimler: tuple = ("shorts",),
                   oyuncu_sec=None, cekim_kur=None) -> dict:
    """Üretim hazırlık kapısı. Dönüş: {'gecti', 'hatalar', 'uyarilar'}. Hata varsa profil üretime ALINMAZ."""
    from motor.uretim import planlayici, sozlesme
    oyuncu_sec = oyuncu_sec or planlayici.oyuncu_sec
    cekim_kur = cekim_kur or planlayici.cekim_kur
    k = kurallar()
    h, u = [], []
    h += [f"şema/kit: {x}" for x in sozlesme.konu_denetle(konu)]   # JSON şeması + dönemlerin gerçek kit olması
    if not konu.get("donemler"):
        h.append("dönem: desteklenen 3D dönem kiti yok (konu şeması en az bir kit ister; kitsiz konu bu sürümde "
                 "üretilemez)")
    t = meta.get("tarih") or {}
    yil = t.get("yil")
    if not isinstance(yil, int) or not -3500 <= yil <= 2100:
        h.append(f"tarih: geçerli yıl yok ({yil!r})")
    elif t.get("kesinlik") != "kesin":
        u.append(f"tarih tartışmalı: {t.get('metin')} (kayıtlar {t.get('kartlar')}); anlatıda ihtiyatlı dil zorunlu")
    taraflar = meta.get("taraflar") or []
    if len(taraflar) < 2:
        h.append(f"taraf: en az 2 taraf tespit edilmeli ({len(taraflar)} tespit edildi; taraf sözlüğü "
                 "kurallar/konu_profili.yaml)")
    for tr in taraflar:
        if tr.get("kit"):
            a, b = k["kit_yillari"].get(tr["kit"], (None, None))
            if a is None or not isinstance(yil, int) or not (a - k["kit_tolerans_yil"] <= yil <= b + k["kit_tolerans_yil"]):
                h.append(f"dönem: {tr['ad']} için {tr['kit']} kiti {yil} yılına uygun değil")
            elif tr.get("kit_uygunlugu") == "yakin":
                u.append(f"{tr['ad']}: en yakın kit {tr['kit']} ({tr['kit_farki_yil']} yıl dışarıda; temsilî)")
        elif tr.get("anahtar") in (konu.get("donemler") or []):
            h.append(f"dönem: kitsiz taraf {tr['anahtar']} dönemlere yazılmış")
    if "harita" not in konu:
        h.append("harita: profil haritası yok (taraf ya da tarih eksik)")
    else:
        h += harita_denetle(konu["harita"])
        if set(konu.get("donemler") or []) - set(konu["harita"].get("taraflar") or {}):
            h.append("harita: her 3D dönemi haritada taraf olmalı")
    konum = meta.get("konum")
    if konum is None:
        u.append("coğrafi koordinat yok: harita şematik (konumlar temsilî)")
    elif not (isinstance(konum, dict) and isinstance(konum.get("enlem"), (int, float)) and isinstance(konum.get("boylam"), (int, float))
              and -90 <= konum["enlem"] <= 90 and -180 <= konum["boylam"] <= 180):
        h.append(f"koordinat: geçersiz {konum!r} (enlem −90…90, boylam −180…180)")
    if (meta.get("olay_turu") or {}).get("tur") == "deniz" and "shorts" in bicimler:
        h.append("olay türü deniz: 3D gemi varlığı yok; Shorts en az 4 3D çekim kuralı karşılanamaz")
    eylemler = {e for a in veri.kural("animasyon")["animasyonlar"].values() for e in a.get("eylemler", [])}
    try:
        roller = {x["rol"] for x in veri.takimlar().values()}
    except Exception:   # noqa: BLE001
        roller = set()
    kameralar = set(veri.kural("kamera")["cekimler"])
    for x in katalog:
        n = x["niyet"]
        ad = x["katalog"]
        if n.get("eylem") not in eylemler:
            h.append(f"planlayıcı {ad}: tanımsız eylem '{n.get('eylem')}'")
        if n.get("kamera") and n["kamera"] not in kameralar:
            h.append(f"planlayıcı {ad}: tanımsız kamera '{n['kamera']}'")
        for r in n.get("roller") or []:
            if r.get("rol") not in roller:
                h.append(f"planlayıcı {ad}: varlık havuzunda olmayan rol '{r.get('rol')}'")
            if r.get("donem") not in (konu.get("donemler") or []):
                h.append(f"planlayıcı {ad}: dönem '{r.get('donem')}' konunun kitlerinde yok")
        if not oyuncu_sec(n, (konu.get("donemler") or [None])[0])[0]:
            h.append(f"planlayıcı {ad}: niyet oyuncuya dönüşmüyor ({n.get('roller')}, {n.get('eylem')})")
            continue
        c, eks, _ = cekim_kur({"id": ad, "cumle": ad, "sure_sn": 4.0, "amac": "olay", "niyet": n},
                              (konu.get("donemler") or [None])[0], 9 / 16, [], 1)
        if eks or not isinstance(c.get("kamera"), dict):
            h.append(f"planlayıcı {ad}: çekim kurulamadı ({'; '.join(eks) or 'kamera yok'})")
    if "shorts" in bicimler and konu.get("donemler") and not katalog:
        h.append("planlayıcı: konunun kitlerinde oyuncuya dönüşen 3D rol/eylem yok; Shorts 3D kuralı karşılanamaz")
    if "uzun" in bicimler and not katalog:
        u.append("uzun: 3D katalog boş; uzun belgesel harita ve tarihî görsellerle anlatılır")
    return {"gecti": not h, "hatalar": h, "uyarilar": u}
