"""Otonom araştırma, senaryo ve sahne planlayıcısı (docs/otonom_belgesel_mimarisi.md, Aşama 1).

Tek bir tarihî konu başlığından üretime hazır bir belgesel planı çıkarır. Katmanlar:

    1 Tarihsel Araştırma → 2 Kronoloji ve Bilgi Havuzu → 3 Dramatik Anlatı → 4 Sahne ve Görsel Planlama
    → 5 Validation Gate → 6 Üretime Hazır Belgesel Planı

LLM çıktısı doğrudan üretime gitmez. Her LLM adımı aşağıdaki kapıdan geçer:

    JSON Parse → Şema → Kronoloji & Dayanak → Süre & Ritim → Görsel Sorgu → Üretime Hazır Plan

Hatalı çıktı için en çok `kurallar.yaml: deneme.en_cok` (3) deneme yapılır. Onarım istemi senaryonun tamamını yeniden
yazdırmaz; yalnızca hatalı yolları bildirir ve yalnızca o yollara yama kabul eder. Yama başka bir alana dokunursa
reddedilir. JSON hiç çözümlenemezse tam yeniden üretim istenir. Bu da bir deneme sayılır.

Deneme hakkı bitince süreç güvenli şekilde durur (fail-safe): `uretime_gonder` çağrılmaz, render başlatılmaz ve
ayrıntılı hata raporu döner.

Tarihsel doğruluk kuralları:
- Anlatımdaki her sayı (yıl, mevcut, tarih) dayanak kayıtlarının metninde geçmelidir. Sayı uydurma kapıda yakalanır.
- Tartışmalı ya da belirsiz kayda dayanan anlatım `kesin` olamaz ve temkin ifadesi taşımalıdır.
- Her sahnenin `dayanak_ids` alanı havuzdaki kayıtlara işaret etmelidir.
- Sentetik (mock) kayıtlarla kurulan plan `guven_durumu: sentetik_mock` ve `yayin_icin_uygun: false` alır. Mock,
  gerçek kaynak varmış gibi gösterilemez.

python3 -m motor.orkestrasyon.senaryo_planlayici "<konu başlığı>" [uzun|shorts] [--mock] [--cikti klasor]
"""
from __future__ import annotations

import copy
import json
import re
import sys
import time
from functools import lru_cache
from pathlib import Path

import yaml

from motor.orkestrasyon.llm import LLMHatasi, LLMProvider, MockLLMProvider, _al, _parcala, _yollari_ac, yol_ayarla

KURALLAR = Path(__file__).with_name("kurallar.yaml")
ONARIM_TALIMATI = "Repair only the invalid fields. Preserve the chronology, narrative structure, and already valid scenes."
SURUM = "senaryo-planlayici-2"
CELISKI_IFADESI = "kaynaklar farklı rakamlar aktarmaktadır"
_URL = re.compile(r"https?://[^\s\"'<>)\]]+", re.I)


@lru_cache(None)
def kurallar() -> dict:
    return yaml.safe_load(KURALLAR.read_text())


@lru_cache(None)
def temkin_ifadeleri() -> tuple[str, ...]:
    from motor.uretim import veri   # yalnızca okunur (dil kuralları); üretim hattına dokunulmaz
    return tuple(veri.kural("dil_tr")["temkin_ifadeleri"])


def _h(asama: str, yol: str, kod: str, mesaj: str) -> dict:
    return {"asama": asama, "yol": yol, "kod": kod, "mesaj": mesaj}


_SAYI = re.compile(r"\d+(?:[.,]\d+)*")


def _sayilar(metin: str) -> set[str]:
    return {re.sub(r"[.,]", "", s) for s in _SAYI.findall(metin or "")}


def _norm(metin: str) -> str:
    return re.sub(r"\s+", " ", (metin or "").strip().lower())


# ================================================================== 1–2: araştırma, kronoloji, bilgi havuzu

def arastirma_dogrula(v: dict, sentetik: bool) -> list[dict]:
    K = kurallar()["enumlar"]
    E = []
    if not isinstance(v, dict) or not isinstance(v.get("kayitlar"), list) or not v["kayitlar"]:
        return [_h("sema", "kayitlar", "eksik", "kayitlar listesi yok ya da boş")]
    gor = set()
    for i, k in enumerate(v["kayitlar"]):
        y = f"kayitlar[{i}]"
        if not isinstance(k, dict):
            E.append(_h("sema", y, "tip", "kayıt nesne değil"))
            continue
        for a in ("id", "olay_id", "tur", "iddia", "durum"):
            if not isinstance(k.get(a), str) or not k[a].strip():
                E.append(_h("sema", f"{y}.{a}", "eksik", f"{a} boş"))
        if k.get("id") in gor:
            E.append(_h("sema", f"{y}.id", "tekrar", f"kimlik tekrar: {k.get('id')}"))
        gor.add(k.get("id"))
        if k.get("tur") not in K["arastirma_tur"]:
            E.append(_h("sema", f"{y}.tur", "enum", f"tur {K['arastirma_tur']} içinde olmalı"))
        if k.get("durum") not in K["arastirma_durum"]:
            E.append(_h("sema", f"{y}.durum", "enum", f"durum {K['arastirma_durum']} içinde olmalı"))
        if k.get("yil") is not None and not isinstance(k.get("yil"), int):
            E.append(_h("sema", f"{y}.yil", "tip", "yil tam sayı ya da null olmalı"))
        kay = k.get("kaynaklar") if isinstance(k.get("kaynaklar"), list) else None
        if kay is None:
            E.append(_h("sema", f"{y}.kaynaklar", "eksik", "kaynaklar listesi yok"))
            kay = []
        if k.get("durum") == "dogrulanmis" and not kay:
            E.append(_h("kronoloji_dayanak", f"{y}.kaynaklar", "kaynaksiz_dogrulanmis", "doğrulanmış kayıt kaynaksız olamaz"))
        if k.get("durum") == "tartismali" and len(kay) < 2 and not k.get("celiski_notu"):
            E.append(_h("kronoloji_dayanak", f"{y}.celiski_notu", "tartisma_belgesiz",
                        "tartışmalı kayıt ya iki kaynak ya da çelişki notu taşımalı"))
        if k.get("durum") == "dogrulanmis" and k.get("yil") is None and k.get("tur") == "tarih":
            E.append(_h("kronoloji_dayanak", f"{y}.durum", "tarihsiz_dogrulanmis", "yılı bilinmeyen tarih kaydı doğrulanmış olamaz"))
        # sentetik/gerçek ayrımı: mock gerçek kaynak gibi davranamaz; gerçek çıktı mock kimliği taşıyamaz
        kimlikler = [k.get("id", "")] + [str(c.get("id", "")) for c in kay if isinstance(c, dict)]
        if sentetik:
            if not all(str(x).startswith("mock_") for x in kimlikler) or k.get("sentetik_mock") is not True or \
                    not all(isinstance(c, dict) and c.get("sentetik_mock") is True for c in kay):
                E.append(_h("sema", y, "sentetik_isaretsiz", "sentetik kayıt ve kaynakları mock_ öneki + sentetik_mock:true taşımalı"))
        else:
            if any(str(x).startswith("mock_") for x in kimlikler) or k.get("sentetik_mock") or \
                    any(isinstance(c, dict) and c.get("sentetik_mock") for c in kay):
                E.append(_h("sema", y, "sentetik_gercek_gibi", "gerçek sağlayıcı çıktısında sentetik kimlik olamaz"))
            for j, c in enumerate(kay):
                if not isinstance(c, dict) or not (c.get("url") or c.get("eser")):
                    E.append(_h("kronoloji_dayanak", f"{y}.kaynaklar[{j}]", "kaynak_belirsiz", "kaynak url ya da eser taşımalı"))
                elif k.get("durum") == "dogrulanmis" and isinstance(c.get("dogrulama"), dict) and \
                        c["dogrulama"].get("verification_status") in ("unreachable", "unverified"):
                    E.append(_h("kronoloji_dayanak", f"{y}.kaynaklar[{j}]", "dogrulanmamis_kaynak",
                                "erişilemeyen/doğrulanamayan kaynak 'doğrulanmış' kaydı destekleyemez"))
        if k.get("tek_kaynak_uyarisi") and k.get("durum") == "dogrulanmis":
            E.append(_h("kronoloji_dayanak", f"{y}.durum", "tek_kaynak_kesin", "tek_kaynak_uyarisi taşıyan kayıt doğrulanmış olamaz"))
        if k.get("celiski"):
            dg = k["celiski"].get("degerler") if isinstance(k["celiski"], dict) else None
            if k.get("durum") != "tartismali" or not isinstance(dg, list) or len({x.get("deger") for x in dg if isinstance(x, dict)}) < 2:
                E.append(_h("kronoloji_dayanak", f"{y}.celiski", "celiski_tekillestirilmis",
                            "çelişkili rakamlar ayrı ayrı tutulmalı (ortalama/tek değer yok) ve kayıt tartışmalı olmalı"))
    return E


def bilgi_havuzu(v: dict) -> dict:
    """Katman 2: doğrulanmış / tartışmalı / belirsiz ayrımı, olay kronolojisi, çelişkiler (deterministik)."""
    kay = v["kayitlar"]
    olaylar: dict[str, dict] = {}
    celiski = []
    for k in kay:
        o = olaylar.setdefault(k["olay_id"], {"olay_id": k["olay_id"], "yillar": set(), "kayitlar": []})
        o["kayitlar"].append(k["id"])
        if k.get("yil") is not None and k["durum"] == "dogrulanmis":
            o["yillar"].add(k["yil"])
    for o in olaylar.values():
        if len(o["yillar"]) > 1 and max(o["yillar"]) - min(o["yillar"]) > 1:
            celiski.append({"olay_id": o["olay_id"], "yillar": sorted(o["yillar"]),
                            "not": "doğrulanmış kayıtlar farklı yıllar veriyor; kesin anlatılamaz"})
    kron = sorted(({"olay_id": o["olay_id"], "yil": min(o["yillar"]) if o["yillar"] else None,
                    "kayitlar": o["kayitlar"]} for o in olaylar.values()),
                  key=lambda x: (x["yil"] is None, x["yil"] or 0))
    celiskili = {c["olay_id"] for c in celiski}
    return {"kayitlar": kay,
            "dogrulanmis": [k["id"] for k in kay if k["durum"] == "dogrulanmis" and k["olay_id"] not in celiskili],
            "tartismali": [k["id"] for k in kay if k["durum"] == "tartismali" or (k["durum"] == "dogrulanmis" and k["olay_id"] in celiskili)],
            "belirsiz": [k["id"] for k in kay if k["durum"] == "belirsiz"],
            "kronoloji": kron, "celiskiler": celiski}


def _kesinlik_durumu(havuz: dict, ids: list[str]) -> str:
    if any(i in havuz["belirsiz"] for i in ids):
        return "belirsiz"
    if any(i in havuz["tartismali"] for i in ids):
        return "tartismali"
    return "kesin"


def guven_durumu(havuz: dict, ids: list[str]) -> str:
    kay = {k["id"]: k for k in havuz["kayitlar"]}
    if any(kay[i].get("sentetik_mock") for i in ids if i in kay):
        return "sentetik_mock"   # mock: "kaynaklarla destekleniyor" DENMEZ
    d = _kesinlik_durumu(havuz, ids)
    return {"kesin": "kaynaklarla_destekleniyor", "tartismali": "tartismali_temkinli_anlatim",
            "belirsiz": "belirsiz_temkinli_anlatim"}[d]


def _dayanak_kontrol(birim: dict, yol: str, havuz: dict, metin_alani: str) -> list[dict]:
    E = []
    kay = {k["id"]: k for k in havuz["kayitlar"]}
    ids = birim.get("dayanak_ids")
    if not isinstance(ids, list) or not ids:
        return [_h("kronoloji_dayanak", f"{yol}.dayanak_ids", "dayanaksiz", "her anlatımın araştırma havuzunda dayanağı olmalı")]
    yok = [i for i in ids if i not in kay]
    if yok:
        return [_h("kronoloji_dayanak", f"{yol}.dayanak_ids", "dayanak_yok", f"havuzda olmayan dayanak: {yok}")]
    metin = birim.get(metin_alani, "")
    kaynak_metin = " ".join(f"{kay[i]['iddia']} {kay[i].get('yil') or ''}" for i in ids)
    uydurma = sorted(_sayilar(metin) - _sayilar(kaynak_metin))
    if uydurma:
        E.append(_h("kronoloji_dayanak", f"{yol}.{metin_alani}", "dayanaksiz_sayi",
                    f"anlatımdaki sayılar dayanakta yok (uydurma olamaz): {uydurma}"))
    if any(kay[i].get("celiski") for i in ids) and "farklı rakam" not in _norm(metin):
        E.append(_h("kronoloji_dayanak", f"{yol}.{metin_alani}", "celiski_ifadesi_yok",
                    f"çelişkili rakamlara dayanan anlatım '{CELISKI_IFADESI}' yaklaşımını kullanmalı (ortalama/tek rakam yok)"))
    gerekli = _kesinlik_durumu(havuz, ids)
    if gerekli != "kesin":
        if birim.get("kesinlik") == "kesin":
            E.append(_h("kronoloji_dayanak", f"{yol}.kesinlik", "tartismali_kesin_sunulmus",
                        f"{gerekli} kayda dayanan anlatım 'kesin' olamaz"))
        if not any(t in _norm(metin) for t in temkin_ifadeleri()) and "farklı rakam" not in _norm(metin):
            E.append(_h("kronoloji_dayanak", f"{yol}.{metin_alani}", "temkin_yok",
                        f"{gerekli} kayda dayanan anlatım temkin ifadesi taşımalı ({', '.join(temkin_ifadeleri()[:4])}…)"))
    return E


# ================================================================== 3: dramatik anlatı

def anlati_dogrula(v: dict, havuz: dict, mod: str) -> list[dict]:
    R = kurallar()[mod]
    E = []
    if not isinstance(v, dict) or not isinstance(v.get("birimler"), list) or not v["birimler"]:
        return [_h("sema", "birimler", "eksik", "anlatı birimleri yok")]
    sira = R["bolum_sirasi"]
    onceki = 0
    for i, b in enumerate(v["birimler"]):
        y = f"birimler[{i}]"
        if not isinstance(b, dict) or not isinstance(b.get("metin"), str) or not b["metin"].strip():
            E.append(_h("sema", f"{y}.metin", "eksik", "metin boş"))
            continue
        if b.get("bolum") not in sira:
            E.append(_h("sema", f"{y}.bolum", "enum", f"bölüm {sira} içinde olmalı"))
            continue
        if sira.index(b["bolum"]) < onceki:
            E.append(_h("kronoloji_dayanak", f"{y}.bolum", "yapi_sirasi", f"anlatı yapısı {' → '.join(sira)} sırasını izlemeli"))
        onceki = max(onceki, sira.index(b["bolum"]))
        E += _dayanak_kontrol(b, y, havuz, "metin")
    eksik = [s for s in sira if s not in {b.get("bolum") for b in v["birimler"] if isinstance(b, dict)}]
    if eksik:
        E.append(_h("kronoloji_dayanak", "birimler", "bolum_eksik", f"eksik bölüm: {eksik}"))
    return E


# ================================================================== 4–5: sahne planı + Validation Gate

def _olay_yili(havuz: dict, ids: list[str]):
    kay = {k["id"]: k for k in havuz["kayitlar"]}
    yillar = [kay[i]["yil"] for i in ids if i in kay and kay[i].get("yil") is not None]
    return max(yillar) if yillar else None


def plan_dogrula(v: dict, havuz: dict, mod: str) -> tuple[list[dict], list[str], dict]:
    """Validation Gate (şema → kronoloji & dayanak → süre & ritim → görsel sorgu). Dönüş: (hatalar, uyarılar, özet)."""
    K, R = kurallar()["enumlar"], kurallar()[mod]
    E, U = [], []
    if not isinstance(v, dict) or not isinstance(v.get("sahneler"), list) or not v["sahneler"]:
        return [_h("sema", "sahneler", "eksik", "sahneler listesi yok ya da boş")], U, {}
    if v.get("mod") != mod:
        E.append(_h("sema", "mod", "mod", f"mod '{mod}' olmalı"))
    if v.get("uretim") != "ayri":
        E.append(_h("sema", "uretim", "ayri_uretim", "plan bu mod için ayrı üretilmeli (başka videodan kesit değil)"))
    if mod == "shorts":
        for a in ("ana_fikir", "ana_olay_id"):
            if not isinstance(v.get(a), str) or not v[a].strip():
                E.append(_h("sema", a, "eksik", f"Shorts {a} boş olamaz"))
    zorunlu = {"id": str, "bolum": str, "anlatim": str, "sure_sn": (int, float), "ritim": str, "gorsel_tur": str,
               "hareketli": bool, "katki": str, "ton": str, "gecis_efekti": str, "ambiyans": str, "kesinlik": str}
    sahneler = v["sahneler"]
    sema_tamam = True
    for i, s in enumerate(sahneler):
        y = f"sahneler[{i}]"
        if not isinstance(s, dict):
            E.append(_h("sema", y, "tip", "sahne nesne değil"))
            sema_tamam = False
            continue
        if any(k in s for k in ("uzun_kesit_ref", "kaynak_sahne_id")):
            E.append(_h("sema", y, "kesit", "Shorts/uzun sahne başka videodan kesit olamaz"))
        for a, t in zorunlu.items():
            if not isinstance(s.get(a), t) or (t is str and not s[a].strip()) or (a == "sure_sn" and isinstance(s.get(a), bool)):
                E.append(_h("sema", f"{y}.{a}", "eksik", f"{a} eksik ya da tipi yanlış"))
                sema_tamam = False
        for a, enum in (("gorsel_tur", "gorsel_tur"), ("ritim", "ritim"), ("ton", "ton"), ("gecis_efekti", "gecis_efekti"),
                        ("ambiyans", "ambiyans"), ("kesinlik", "kesinlik")):
            if isinstance(s.get(a), str) and s[a] not in K[enum]:
                E.append(_h("sema", f"{y}.{a}", "enum", f"{a} {K[enum]} içinde olmalı"))
                sema_tamam = False
        if s.get("bolum") not in R["bolum_sirasi"]:
            E.append(_h("sema", f"{y}.bolum", "enum", f"bölüm {R['bolum_sirasi']} içinde olmalı"))
            sema_tamam = False
    if not sema_tamam:
        return E, U, {}

    # ---- kronoloji & dayanak
    sira = R["bolum_sirasi"]
    onceki_bolum, onceki_yil = 0, None
    gor_anlatim, gor_katki = {}, {}
    kay = {k["id"]: k for k in havuz["kayitlar"]}
    for i, s in enumerate(sahneler):
        y = f"sahneler[{i}]"
        E += _dayanak_kontrol(s, y, havuz, "anlatim")
        bi = sira.index(s["bolum"])
        if bi < onceki_bolum:
            E.append(_h("kronoloji_dayanak", f"{y}.bolum", "yapi_sirasi", f"yapı {' → '.join(sira)} sırasını izlemeli"))
        onceki_bolum = max(onceki_bolum, bi)
        if mod == "uzun" and s["bolum"] not in ("hook", "sonuc") and not s.get("geri_donus"):
            yil = _olay_yili(havuz, s.get("dayanak_ids") or [])
            if yil is not None and onceki_yil is not None and yil < onceki_yil:
                E.append(_h("kronoloji_dayanak", f"{y}.dayanak_ids", "kronoloji_geri",
                            f"olay yılı {yil}, önceki sahnenin {onceki_yil} yılından önce (geri dönüşse geri_donus:true)"))
            onceki_yil = yil if yil is not None else onceki_yil
        n = _norm(s["anlatim"])
        if n in gor_anlatim:
            E.append(_h("kronoloji_dayanak", f"{y}.anlatim", "tekrar_sahne",
                        f"anlatım sahneler[{gor_anlatim[n]}] ile aynı: süre doldurmak için sahne çoğaltılamaz"))
        gor_anlatim.setdefault(n, i)
        kk = _norm(s["katki"])
        if kk in gor_katki:
            E.append(_h("kronoloji_dayanak", f"{y}.katki", "tekrar_katki",
                        f"katkı sahneler[{gor_katki[kk]}] ile aynı: her sahne yeni bilgi/dramatik katkı sunmalı"))
        gor_katki.setdefault(kk, i)
    if mod == "shorts":
        olaylar = {kay[d]["olay_id"] for s in sahneler for d in (s.get("dayanak_ids") or []) if d in kay}
        if olaylar - {v.get("ana_olay_id")}:
            E.append(_h("kronoloji_dayanak", "sahneler[*].dayanak_ids", "tek_fikir",
                        f"Shorts tek ana olay etrafında kalmalı ({v.get('ana_olay_id')}); başka olaylar: {sorted(olaylar - {v.get('ana_olay_id')})}"))
    eksik = [b for b in sira if b not in {s["bolum"] for s in sahneler}]
    if eksik:
        E.append(_h("kronoloji_dayanak", "sahneler", "bolum_eksik", f"eksik bölüm: {eksik}"))

    # ---- süre & ritim
    t = 0.0
    baslangic = []
    for s in sahneler:
        baslangic.append(t)
        t += float(s["sure_sn"])
    toplam = t
    lo, hi = R["toplam_sn"]
    if not lo <= toplam <= hi:
        E.append(_h("sure_ritim", "sahneler[*].sure_sn", "toplam_sure", f"toplam {toplam:.0f} sn; {lo}–{hi} sn olmalı"))
    for i, s in enumerate(sahneler):
        y = f"sahneler[{i}]"
        d = float(s["sure_sn"])
        if mod == "uzun":
            S = R["sure"]
            if d < S["varsayilan"][0]:
                if s["ritim"] != "vurgu" or d < S["kisa_vurgu"][0]:
                    E.append(_h("sure_ritim", f"{y}.sure_sn", "kisa_sahne",
                                f"{d} sn: 6 sn altı yalnızca bilinçli vurgu (ritim=vurgu, ≥{S['kisa_vurgu'][0]} sn)"))
            elif d > S["varsayilan"][1]:
                if not (s["gorsel_tur"] == "harita" and s["ritim"] == "kritik_harita" and d <= S["kritik_harita_en_cok"]):
                    E.append(_h("sure_ritim", f"{y}.sure_sn", "uzun_sahne",
                                f"{d} sn: 12 sn üstü yalnızca kritik harita/savaş planı (≤{S['kritik_harita_en_cok']} sn)"))
            if s["ritim"] == "atmosfer" and d < S["atmosfer_en_az"]:
                E.append(_h("sure_ritim", f"{y}.ritim", "atmosfer_kisa", f"atmosfer sahnesi en az {S['atmosfer_en_az']} sn"))
            if s["ritim"] == "kritik_harita" and s["gorsel_tur"] != "harita":
                E.append(_h("sure_ritim", f"{y}.ritim", "kritik_harita_tur", "kritik_harita ritmi yalnızca harita sahnesinde"))
        else:
            a, b = R["sure"]
            if not a <= d <= b:
                E.append(_h("sure_ritim", f"{y}.sure_sn", "shorts_sure", f"Shorts sahnesi {a}–{b} sn olmalı"))
        if i >= kurallar()["ardisik_ayni_tur_en_cok"] and all(
                sahneler[i - j]["gorsel_tur"] == s["gorsel_tur"] for j in range(1, kurallar()["ardisik_ayni_tur_en_cok"] + 1)):
            E.append(_h("sure_ritim", f"{y}.gorsel_tur", "ardisik_tekrar",
                        f"aynı görsel türü ({s['gorsel_tur']}) en fazla {kurallar()['ardisik_ayni_tur_en_cok']} sahne üst üste"))
    if mod == "uzun":
        hook = sum(float(s["sure_sn"]) for s in sahneler if s["bolum"] == "hook")
        if hook > R["hook_en_cok_sn"]:
            E.append(_h("sure_ritim", "sahneler[*].sure_sn", "hook_uzun", f"hook {hook:.0f} sn; en çok {R['hook_en_cok_sn']} sn"))
    else:
        s0 = sahneler[0]
        if not s0.get("hook") or s0["bolum"] != "hook":
            E.append(_h("sure_ritim", "sahneler[0].hook", "hook_yok", "Shorts ilk sahnesi hook işaretli olmalı (bolum=hook, hook=true)"))
        for i, s in enumerate(sahneler):
            if baslangic[i] < R["ilk_hareketli_sn"] and (s["gorsel_tur"] not in R["hareketli_turler"] or not s["hareketli"]):
                E.append(_h("sure_ritim", f"sahneler[{i}].gorsel_tur", "ilk_3sn_duragan",
                            f"ilk {R['ilk_hareketli_sn']} sn hareketli olmalı ({R['hareketli_turler']}, hareketli=true)"))
        hook = sum(float(s["sure_sn"]) for s in sahneler if s["bolum"] == "hook")
        if not R["hook_sn"][0] <= hook <= R["hook_sn"][1]:
            E.append(_h("sure_ritim", "sahneler[0].sure_sn", "hook_sure", f"hook {hook:.0f} sn; {R['hook_sn'][0]}–{R['hook_sn'][1]} sn olmalı"))
        kap = [baslangic[i] for i, s in enumerate(sahneler) if s["bolum"] == "kapanis"]
        if kap and not R["kapanis_baslangic_sn"][0] <= kap[0] <= R["kapanis_baslangic_sn"][1]:
            E.append(_h("sure_ritim", "sahneler[*].sure_sn", "kapanis_zamani",
                        f"kapanış {kap[0]:.0f}. sn'de başlıyor; {R['kapanis_baslangic_sn'][0]}–{R['kapanis_baslangic_sn'][1]} olmalı"))

    # ---- görsel sorgu ve tür gerekleri
    for i, s in enumerate(sahneler):
        y = f"sahneler[{i}]"
        if s["gorsel_tur"] == "harita" and (not isinstance(s.get("cografi_amac"), str) or len(s["cografi_amac"].strip()) < 10):
            E.append(_h("gorsel_sorgu", f"{y}.cografi_amac", "cografi_amac_yok", "harita sahnesinde coğrafi anlatım amacı zorunlu"))
        if s["gorsel_tur"] == "sahne3d" and (not isinstance(s.get("uc_boyut_gerekcesi"), str) or not s["uc_boyut_gerekcesi"].strip()):
            E.append(_h("gorsel_sorgu", f"{y}.uc_boyut_gerekcesi", "3d_gerekcesiz", "3D yalnızca anlatıya gerçek katkıyla (gerekçe zorunlu)"))
        if s["gorsel_tur"] == "gorsel25d":
            q = s.get("arama_sorgulari")
            if not isinstance(q, list) or not q or not all(isinstance(x, str) and 2 < len(x.strip()) <= 120 for x in q):
                E.append(_h("gorsel_sorgu", f"{y}.arama_sorgulari", "sorgu_yok",
                            "gorsel25d sahnesinde commons_toplayici uyumlu arama_sorgulari (boş olmayan metinler) zorunlu"))

    # ---- uydurma kaynak kilidi: plandaki her URL ve kaynak kimliği havuzda doğrulanmış olmalı
    gecerli_url = {c.get("url") for k in havuz["kayitlar"] for c in (k.get("kaynaklar") or [])
                   if isinstance(c, dict) and c.get("url") and (c.get("dogrulama") or {}).get("verification_status", "verified")
                   in ("verified", "content_mismatch")}
    gecerli_kid = {c.get("id") for k in havuz["kayitlar"] for c in (k.get("kaynaklar") or []) if isinstance(c, dict)}

    def _metinler(o):
        if isinstance(o, str):
            yield o
        elif isinstance(o, dict):
            for x in o.values():
                yield from _metinler(x)
        elif isinstance(o, list):
            for x in o:
                yield from _metinler(x)
    for yol_, o in [("baslik", v.get("baslik"))] + [(f"sahneler[{i}]", s) for i, s in enumerate(sahneler)]:
        for m in (u for t in _metinler(o) for u in _URL.findall(t)):
            if m.rstrip(".,;") not in gecerli_url:
                E.append(_h("kronoloji_dayanak", yol_, "dogrulanmamis_url", f"havuzda doğrulanmamış URL (LLM uydurması olabilir): {m[:80]}"))
    for i, s in enumerate(sahneler):
        if "kaynak_ids" in s:
            uyd = [x for x in (s["kaynak_ids"] or []) if x not in gecerli_kid]
            if uyd or not isinstance(s["kaynak_ids"], list):
                E.append(_h("kronoloji_dayanak", f"sahneler[{i}].kaynak_ids", "uydurma_kaynak_id", f"havuzda olmayan kaynak kimliği: {uyd}"))

    # ---- dinamik dağılım (uyarı; kota değil)
    ozet = {"toplam_sn": round(toplam, 1), "sahne_sayisi": len(sahneler)}
    if toplam > 0:
        dag = {tt: round(sum(float(s["sure_sn"]) for s in sahneler if s["gorsel_tur"] == tt) / toplam, 3)
               for tt in K["gorsel_tur"]}
        ozet["dagilim"] = dag
        if mod == "uzun":
            for tt, h in R["dagilim_hedefi"].items():
                if abs(dag[tt] - h) > R["dagilim_uyari_sapma"]:
                    U.append(f"dağılım: {tt} %{dag[tt] * 100:.0f} (dinamik hedef ~%{h * 100:.0f}); konu gerektiriyorsa kabul")
    return E, U, ozet


# ================================================================== istemler

def _istem_arastirma(konu: str, mod: str) -> str:
    return f"""Tarihî konu: "{konu}". Kaynaklı bir araştırma havuzu çıkar.
Kurallar: Tarih, kişi, sayı ya da olay UYDURMA. Her kayıt tek bir iddia taşır ve kaynak gösterir (url ya da eser).
Kayıtları ayır: durum = dogrulanmis | tartismali (çelişki notu ya da en az iki kaynak) | belirsiz (bilinmiyor).
Bilinmeyen yıl null olur. Her kaydın olay_id'si kronolojide hangi olaya ait olduğunu gösterir.
Yalnızca JSON: {{"konu": str, "kayitlar": [{{"id","olay_id","tur":{kurallar()['enumlar']['arastirma_tur']},"yil":int|null,
"iddia","durum","kaynaklar":[{{"id","eser"|"url"}}],"celiski_notu"?}}]}}"""


def _istem_anlati(konu: str, mod: str, havuz: dict) -> str:
    R = kurallar()[mod]
    def _st(k):
        parca = [k["durum"]]
        if k.get("tek_kaynak_uyarisi"):
            parca.append("tek_kaynak_uyarisi")
        if k.get("celiski"):
            parca.append("CELISKI: " + ", ".join(str(x.get("deger")) for x in k["celiski"].get("degerler", [])))
        dg = [f"{c.get('id')}={(c.get('dogrulama') or {}).get('verification_status', '-')}" for c in k.get("kaynaklar", [])
              if isinstance(c, dict)]
        if dg:
            parca.append("kaynaklar: " + " ".join(dg))
        return "; ".join(parca)
    kart = "\n".join(f"- {k['id']} [{_st(k)}] ({k.get('yil')}): {k['iddia']}" for k in havuz["kayitlar"])
    return f"""Konu: "{konu}". Mod: {mod}. Dramatik anlatı yapısı: {' → '.join(R['bolum_sirasi'])}.
Her anlatı birimi yalnızca aşağıdaki kayıtlara dayanır (dayanak_ids). Kayıtta olmayan sayı/tarih/kişi yazma.
Kendi hafızanı kaynak olarak KULLANMA; havuzda olmayan kaynak, kaynak kimliği ya da URL UYDURMA.
Doğrulama statüleri: verified / content_mismatch / unverified / unreachable. Doğrulanmamış ya da tek_kaynak_uyarisi
taşıyan kaydı kesin anlatma. CELISKI işaretli rakamlarda kesin hüküm verme, ortalama alma; "{CELISKI_IFADESI}" de ve
değerleri ayrı ayrı aktar.
Tartışmalı ya da belirsiz kayda dayanan birim temkinli yazılır ({', '.join(temkin_ifadeleri()[:5])}) ve kesinlik 'kesin' olmaz.
{'Shorts: uzun videodan kesit DEĞİL; tek ana olay, 0–3 sn hook, 3–40 sn hızlı akış, 40–60 sn şaşırtıcı kapanış.' if mod == 'shorts' else 'Uzun belgesel: 15–20 dk.'}
Kayıtlar:
{kart}
Yalnızca JSON: {{"mod": "{mod}", "birimler": [{{"id","bolum","metin","dayanak_ids":[...],"kesinlik"}}]}}"""


def _istem_plan(konu: str, mod: str, havuz: dict, anlati: dict) -> str:
    R, K = kurallar()[mod], kurallar()["enumlar"]
    return f"""Konu: "{konu}". Mod: {mod} ({R['format']['en_boy']}). Anlatı birimlerinden sahne planı çıkar.
Toplam {R['toplam_sn'][0]}–{R['toplam_sn'][1]} sn. Sahne süresi: {'6–12 sn (6 vurgu, 8 normal, 10–12 atmosfer; <6 yalnızca ritim=vurgu; >12 yalnızca harita+kritik_harita ≤20)' if mod == 'uzun' else '2–10 sn'}.
Süre doldurmak için sahne çoğaltma; her sahne yeni bilgi ya da dramatik katkı (katki) sunar.
Görsel türleri {K['gorsel_tur']}: dinamik hedef ~%40 harita, ~%40 gorsel25d, ~%20 sahne3d; aynı tür en fazla 2 sahne üst üste.
harita → cografi_amac zorunlu; sahne3d → uc_boyut_gerekcesi zorunlu; gorsel25d → arama_sorgulari (Wikimedia Commons arama metinleri) boş olamaz.
Her sahne: ton {K['ton']}, gecis_efekti {K['gecis_efekti']}, ambiyans {K['ambiyans']}, hareketli (bool), kesinlik, dayanak_ids.
{'Shorts: ilk sahne hook=true ve ilk 3 sn hareketli (gorsel25d/sahne3d); tek ana fikir (ana_fikir, ana_olay_id); kapanış 35–45. sn arasında başlar.' if mod == 'shorts' else 'Bölüm sırası: ' + ' → '.join(R['bolum_sirasi'])}
Anlatı birimleri:
{json.dumps(anlati['birimler'], ensure_ascii=False)[:150000]}
Yalnızca JSON: {{"mod":"{mod}","baslik","uretim":"ayri",{'"ana_fikir","ana_olay_id",' if mod == 'shorts' else ''}"sahneler":[{{"id","bolum","anlatim","dayanak_ids","kesinlik","sure_sn","ritim","gorsel_tur","hareketli","katki","ton","gecis_efekti","ambiyans","hook",...}}]}}"""


def _onarim_baglami(hatalar: list[dict], mevcut: dict, sinir: int = 30000) -> str:
    """Gerçek LLM'in düzeltebilmesi için hatalı alanların içinde bulunduğu nesnelerin GÜNCEL hali (yalnızca onlar)."""
    parcalar, gor = [], set()
    for h in hatalar:
        yol = h.get("yol") or ""
        if not yol:
            continue
        if "[*]" in yol:   # genel hata (toplam süre vb.): ilgili alanın bütün sahnelerdeki değeri
            on, arka = yol.split("[*]", 1)
            if yol in gor:
                continue
            gor.add(yol)
            try:
                liste = _al(mevcut, on)
                alan = arka.lstrip(".")
                ozet = [{"i": i, "id": x.get("id"), alan or "deger": (x.get(alan) if alan else None)}
                        for i, x in enumerate(liste) if isinstance(x, dict)]
                parcalar.append(f"{yol} (güncel): {json.dumps(ozet, ensure_ascii=False)}")
            except (KeyError, IndexError, TypeError):
                pass
            continue
        p = _parcala(yol)
        ust = p[:2] if len(p) >= 2 and isinstance(p[1], int) else p[:1]
        anahtar = json.dumps(ust)
        if anahtar in gor:
            continue
        gor.add(anahtar)
        try:
            nesne = mevcut
            for x in ust:
                nesne = nesne[x]
            ad = ust[0] + (f"[{ust[1]}]" if len(ust) > 1 else "")
            parcalar.append(f"{ad} (güncel): {json.dumps(nesne, ensure_ascii=False)}")
        except (KeyError, IndexError, TypeError):
            pass
    metin = "\n".join(parcalar)
    return metin[:sinir]


def _istem_onarim(adim: str, hatalar: list[dict], mevcut: dict) -> str:
    satir = "\n".join(f"- {h['yol']}: {h['mesaj']}" for h in hatalar[:60])
    return f"""{ONARIM_TALIMATI}
Adım: {adim}. Yalnızca şu yollardaki geçersiz alanları düzelt; başka hiçbir alanı değiştirme:
{satir}
Hatalı alanları içeren nesnelerin güncel hali (yalnızca bağlam için; listelenmeyen alanları değiştirme):
{_onarim_baglami(hatalar, mevcut)}
Yanıt yalnızca JSON yaması: {{"duzeltmeler": [{{"yol": "<yukarıdaki yollardan biri ya da altı>", "deger": <yeni değer>}}]}}"""


# ================================================================== üret–doğrula–onar döngüsü

def _yol_izinli(yol: str, izinli: list[str]) -> bool:
    p = _parcala(yol)
    for iz in izinli:
        q = _parcala(iz)
        if len(p) >= len(q) and all(a == "*" and isinstance(b, int) or a == b for a, b in zip(q, p)):
            return True
    return False


def _cozumle(ham: str):
    try:
        return json.loads(ham), None
    except (json.JSONDecodeError, TypeError) as e:
        m = re.search(r"\{.*\}", ham or "", re.S)   # metin içine gömülü tek JSON nesnesi
        if m:
            try:
                return json.loads(m.group(0)), None
            except json.JSONDecodeError:
                pass
        return None, str(e)


def _adim(saglayici: LLMProvider, adim: str, istem: str, baglam: dict, dogrula, en_cok: int,
          ilk_uretim=None, ilerleme=None) -> dict:
    """Bir LLM adımını en çok `en_cok` denemeyle doğrulanmış veriye çevirir. Dönüş: {veri|None, denemeler, hatalar}.
    ilk_uretim(deneme) → ham metin: tam üretim için özel yol (ör. bölüm bölüm paralel üretim); onarım her zaman hedefli."""
    denemeler = []
    try:
        return _adim_ic(saglayici, adim, istem, baglam, dogrula, en_cok, denemeler, ilk_uretim, ilerleme or (lambda *a: None))
    except LLMHatasi as e:   # gerçek sağlayıcı başarısız: DUR (mock'a sessiz geçiş YOK)
        h = [_h("saglayici", "", "saglayici_hatasi", str(e)[:400])]
        denemeler.append({"deneme": len(denemeler) + 1, "tur": "saglayici_hatasi", "hatalar": h})
        return {"veri": None, "denemeler": denemeler, "hatalar": h}


def _adim_ic(saglayici, adim, istem, baglam, dogrula, en_cok, denemeler, ilk_uretim, ilerleme) -> dict:
    veri, hatalar = None, []
    for d in range(1, en_cok + 1):
        if veri is None:   # ilk deneme ya da JSON çözülemedi → tam üretim istemi
            if ilk_uretim is not None:
                ham = ilk_uretim(d)
            else:
                ham = saglayici.tamamla(istem if d == 1 else istem + "\n\nÖnceki yanıt geçerli JSON değildi. Yalnızca JSON döndür.",
                                        adim, dict(baglam, deneme=d))
            yeni, perr = _cozumle(ham)
            if yeni is None:
                hatalar = [_h("json", "", "json_parse", f"JSON çözümlenemedi: {perr}")]
                ilerleme("onay_kapisi", f"{adim} deneme {d}/{en_cok}: JSON çözümlenemedi")
                denemeler.append({"deneme": d, "tur": "tam_uretim", "hatalar": hatalar})
                continue
            veri = yeni
            tur = "tam_uretim"
        else:              # hedefli onarım: yalnızca hatalı yollar
            izinli = sorted({h["yol"] for h in hatalar if h["yol"]})
            ham = saglayici.tamamla(_istem_onarim(adim, hatalar, veri), "onarim",
                                    dict(baglam, deneme=d, hedef_adim=adim, onarilacak_yollar=izinli, mevcut=veri, hatalar=hatalar))
            yama, perr = _cozumle(ham)
            red = []
            if yama is None or not isinstance(yama.get("duzeltmeler"), list):
                red.append(_h("json", "", "yama_parse", f"onarım yaması çözümlenemedi: {perr}"))
            else:
                aday = copy.deepcopy(veri)
                for z in yama["duzeltmeler"]:
                    yol = z.get("yol") if isinstance(z, dict) else None
                    if not isinstance(yol, str) or not _yol_izinli(yol, izinli):
                        red.append(_h("sema", str(yol), "izinsiz_yama", "onarım yalnızca geçersiz alanlara dokunabilir"))
                        continue
                    try:
                        yol_ayarla(aday, yol, z.get("deger"))
                    except (KeyError, IndexError, TypeError):
                        red.append(_h("sema", yol, "yama_yolu", "yama yolu veride yok"))
                if not red:
                    veri = aday
            tur = "hedefli_onarim"
            if red:   # yama reddedildi: veri değişmez, bu deneme harcanır
                hatalar = red + hatalar
                denemeler.append({"deneme": d, "tur": tur, "hatalar": hatalar[:80], "yama_reddedildi": True})
                hatalar = [h for h in hatalar if h["kod"] not in ("izinsiz_yama", "yama_parse", "yama_yolu")]
                continue
        hatalar = dogrula(veri)
        denemeler.append({"deneme": d, "tur": tur, "hatalar": hatalar[:80], "hata_sayisi": len(hatalar)})
        kodlar = {}
        for h in hatalar:
            kodlar[h["kod"]] = kodlar.get(h["kod"], 0) + 1
        ilerleme("onay_kapisi", f"{adim} deneme {d}/{en_cok} ({tur}): {'GEÇTİ' if not hatalar else f'{len(hatalar)} hata {kodlar}'}")
        if not hatalar:
            return {"veri": veri, "denemeler": denemeler, "hatalar": []}
    return {"veri": None, "denemeler": denemeler, "hatalar": hatalar}


PARCA_SURE_SN = {"hook": 45, "baglam": 200, "catisma": 320, "donum_noktasi": 280, "sonuc": 205}   # ≈ 17,5 dk


def _paralel(fn, ogeler, en_cok_is: int = 5) -> list:
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max(1, min(en_cok_is, len(ogeler)))) as ex:
        return list(ex.map(fn, ogeler))   # bir parçadaki LLMHatasi burada yükselir → adım durur (fallback yok)


def _parcali_anlati(saglayici, konu, mod, havuz, ilerleme, paralel=5):
    sira = kurallar()[mod]["bolum_sirasi"]

    def tek(bolum):
        sn = PARCA_SURE_SN[bolum]
        ist = _istem_anlati(konu, mod, havuz) + (
            f"\nBU İSTEKTE YALNIZCA '{bolum}' bölümünü yaz (her birimde bolum='{bolum}'). Hedef: yaklaşık {sn} sn anlatım, "
            f"yaklaşık {max(3, round(sn / 8.5))} birim. Diğer bölümleri yazma.")
        ilerleme("gemini_cagri", f"anlati/{bolum} başlıyor")
        return bolum, saglayici.tamamla(ist, "anlati", {"konu": konu, "mod": mod, "havuz": havuz, "bolum": bolum})

    def uret(deneme):
        birimler = []
        for bolum, ham in _paralel(tek, sira, paralel):
            v, _ = _cozumle(ham)
            if not isinstance(v, dict) or not isinstance(v.get("birimler"), list):
                ilerleme("onay_kapisi", f"anlati/{bolum}: JSON çözümlenemedi")
                return f"PARCA_JSON_HATASI anlati/{bolum}"
            birimler += [dict(b, bolum=bolum) if isinstance(b, dict) else b for b in v["birimler"]]
        return json.dumps({"mod": mod, "birimler": birimler}, ensure_ascii=False)
    return uret


def _parcali_plan(saglayici, konu, mod, havuz, anlati, ilerleme, paralel=5):
    sira = kurallar()[mod]["bolum_sirasi"]

    def tek(bolum):
        alt = {"mod": mod, "birimler": [b for b in anlati["birimler"] if b.get("bolum") == bolum]}
        ist = _istem_plan(konu, mod, havuz, alt) + (
            f"\nBU İSTEKTE YALNIZCA '{bolum}' bölümünün sahnelerini üret (bütün plan değil). Bu bölümün toplamı yaklaşık "
            f"{PARCA_SURE_SN[bolum]} sn olsun. Bölüm geçişinde aynı görsel türünün 3. kez üst üste gelmemesi için ilk ve son "
            f"sahnelerde tür çeşitliliğine dikkat et.")
        ilerleme("gemini_cagri", f"sahne_plani/{bolum} başlıyor ({len(alt['birimler'])} birim)")
        return bolum, saglayici.tamamla(ist, "sahne_plani", {"konu": konu, "mod": mod, "havuz": havuz, "anlati": alt, "bolum": bolum})

    def uret(deneme):
        sahneler, baslik = [], None
        for bolum, ham in _paralel(tek, sira, paralel):
            v, _ = _cozumle(ham)
            if not isinstance(v, dict) or not isinstance(v.get("sahneler"), list):
                ilerleme("onay_kapisi", f"sahne_plani/{bolum}: JSON çözümlenemedi")
                return f"PARCA_JSON_HATASI sahne_plani/{bolum}"
            baslik = baslik or v.get("baslik")
            sahneler += [dict(x, bolum=bolum) if isinstance(x, dict) else x for x in v["sahneler"]]
        for i, x in enumerate(sahneler):   # parçalardaki kimlikler çakışabilir: birleşik planda yeniden numaralanır
            if isinstance(x, dict):
                x["id"] = f"s{i + 1:03d}"
                x["hook"] = bool(x.get("hook")) if i == 0 else False   # hook yalnızca ilk sahnede
        return json.dumps({"mod": mod, "baslik": baslik or konu, "uretim": "ayri", "sahneler": sahneler}, ensure_ascii=False)
    return uret


def plan_uret(konu: str, mod: str, saglayici: LLMProvider, en_cok_deneme: int | None = None,
              uretime_gonder=None, arastirma: dict | None = None, parcali: bool = False, ilerleme=None,
              paralel: int = 5) -> dict:
    """parcali=True (yalnızca uzun mod): anlatı ve sahne planı bölüm bölüm PARALEL üretilir, birleştirilir ve
    birleşik plan aynı Validation Gate'ten geçer; onarım birleşik planda hedefli yapılır. ilerleme(asama, mesaj)."""
    ilerleme = ilerleme or (lambda *a: None)
    parcali = parcali and mod == "uzun"
    """Katman 1–6. Dönüş: rapor. `uretime_gonder(plan)` YALNIZCA plan bütün kapılardan geçerse çağrılır."""
    if mod not in ("uzun", "shorts"):
        raise ValueError("mod 'uzun' ya da 'shorts'")
    t0 = time.time()
    en_cok = int(en_cok_deneme or kurallar()["deneme"]["en_cok"])
    sent = bool(saglayici.sentetik)
    rapor = {"surum": SURUM, "konu": konu, "mod": mod, "saglayici": saglayici.ad, "sentetik_mock": sent,
             "katmanlar": {}, "durum": None, "render_baslatildi": False}

    def dur(katman: str, sonuc: dict) -> dict:
        rapor.update({"durum": "durduruldu", "durdugu_katman": katman, "hatalar": sonuc["hatalar"],
                      "ozet_hata": f"{katman}: {len(sonuc['hatalar'])} hata, {len(sonuc['denemeler'])} deneme sonunda geçersiz; "
                                   f"render başlatılmadı (fail-safe)", "sure_sn": round(time.time() - t0, 2)})
        return rapor

    # 1 araştırma. Gerçek sağlayıcıda LLM hafızası araştırma kabul EDİLMEZ: havuz dış kaynak keşfi + canlı
    #   doğrulamadan (kaynak_kesif.havuz_olustur) gelmeli. Mock testlerinde LLM adımı sentetik havuz üretir.
    if arastirma is not None:
        e = arastirma_dogrula(arastirma, sent)
        a = {"veri": None if e else arastirma, "denemeler": [{"deneme": 1, "tur": "dis_kaynak_havuzu", "hatalar": e[:80]}], "hatalar": e}
    elif not sent:
        e = [_h("kronoloji_dayanak", "arastirma", "llm_hafizasi_arastirma_degil",
                "gerçek üretimde araştırma havuzu dış kaynak keşfi ve doğrulamasından gelmeli (LLM hafızası kabul edilmez)")]
        a = {"veri": None, "denemeler": [], "hatalar": e}
    else:
        a = _adim(saglayici, "arastirma", _istem_arastirma(konu, mod), {"konu": konu, "mod": mod},
                  lambda v: arastirma_dogrula(v, sent), en_cok)
    rapor["katmanlar"]["1_arastirma"] = {"denemeler": a["denemeler"]}
    if a["veri"] is None:
        return dur("1_arastirma", a)
    # 2 kronoloji + bilgi havuzu (deterministik)
    havuz = bilgi_havuzu(a["veri"])
    rapor["katmanlar"]["2_bilgi_havuzu"] = {k: (len(havuz[k]) if isinstance(havuz[k], list) else havuz[k])
                                            for k in ("dogrulanmis", "tartismali", "belirsiz")} | {
        "kronoloji": havuz["kronoloji"], "celiskiler": havuz["celiskiler"]}
    # 3 dramatik anlatı
    ilerleme("onay_kapisi", f"araştırma havuzu kapıdan geçti: {len(havuz['kayitlar'])} kayıt")
    n = _adim(saglayici, "anlati", _istem_anlati(konu, mod, havuz), {"konu": konu, "mod": mod, "havuz": havuz},
              lambda v: anlati_dogrula(v, havuz, mod), en_cok,
              ilk_uretim=_parcali_anlati(saglayici, konu, mod, havuz, ilerleme, paralel) if parcali else None, ilerleme=ilerleme)
    rapor["katmanlar"]["3_anlati"] = {"denemeler": n["denemeler"]}
    if n["veri"] is None:
        return dur("3_anlati", n)
    # 4 sahne/görsel planı + 5 Validation Gate
    uyarilar, ozet = [], {}

    def kapi(v):
        nonlocal uyarilar, ozet
        e, uyarilar, ozet = plan_dogrula(v, havuz, mod)
        return e
    p = _adim(saglayici, "sahne_plani", _istem_plan(konu, mod, havuz, n["veri"]),
              {"konu": konu, "mod": mod, "havuz": havuz, "anlati": n["veri"]}, kapi, en_cok,
              ilk_uretim=_parcali_plan(saglayici, konu, mod, havuz, n["veri"], ilerleme, paralel) if parcali else None, ilerleme=ilerleme)
    rapor["katmanlar"]["4_5_sahne_plani_ve_kapi"] = {"denemeler": p["denemeler"]}
    if p["veri"] is None:
        return dur("4_5_sahne_plani_ve_kapi", p)
    # 6 üretime hazır plan
    plan = p["veri"]
    for s in plan["sahneler"]:
        s["guven_durumu"] = guven_durumu(havuz, s["dayanak_ids"])
    plan.update({"format": kurallar()[mod]["format"], "sentetik_mock": sent, "yayin_icin_uygun": not sent,
                 "ozet": ozet, "uyarilar": uyarilar,
                 "kaynakca": sorted({c.get("eser") or c.get("url") for k in havuz["kayitlar"] for c in k.get("kaynaklar", [])
                                     if isinstance(c, dict)})})
    rapor.update({"durum": "uretime_hazir", "plan": plan, "havuz": havuz, "anlati": n["veri"], "uyarilar": uyarilar,
                  "ozet": ozet, "sure_sn": round(time.time() - t0, 2)})
    if uretime_gonder is not None:
        uretime_gonder(plan)
        rapor["render_baslatildi"] = True
    return rapor


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    konu = argv[0]
    mod = argv[1] if len(argv) > 1 and argv[1] in ("uzun", "shorts") else "uzun"
    if "--mock" not in argv:
        print("Gerçek LLM sağlayıcısı henüz bağlı değil (0 TL kuralı: ücretsiz sağlayıcı ayrı adımda eklenecek). --mock kullan.")
        return 2
    r = plan_uret(konu, mod, MockLLMProvider())
    cikti = Path(argv[argv.index("--cikti") + 1]) if "--cikti" in argv else None
    if cikti:
        cikti.mkdir(parents=True, exist_ok=True)
        (cikti / f"plan_{mod}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1))
    print(json.dumps({k: r.get(k) for k in ("durum", "mod", "sentetik_mock", "ozet", "uyarilar", "durdugu_katman", "ozet_hata")},
                     ensure_ascii=False, indent=1))
    return 0 if r["durum"] == "uretime_hazir" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
