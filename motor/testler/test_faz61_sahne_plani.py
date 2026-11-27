"""Faz-61 — uzun mod süre bütçesi (360 sn) ve sahne planı / hedefli onarım istem kuralları (ağsız)."""
from __future__ import annotations

import json

import pytest

from motor.orkestrasyon import canli_dry_run as cdr
from motor.orkestrasyon import gemini as gm
from motor.orkestrasyon import senaryo_planlayici as sp

HAVUZ = {"kayitlar": [{"id": f"ark_{i:03d}", "iddia": f"iddia {i}", "yil": 1473, "durum": "dogrulanmis"}
                      for i in range(1, 6)]}
ANLATI = {"mod": "shorts", "birimler": [
    {"id": "birim_001", "bolum": "hook", "metin": "a", "dayanak_ids": ["ark_002"], "kesinlik": "kesin"},
    {"id": "birim_002", "bolum": "baglam", "metin": "b", "dayanak_ids": ["ark_003", "ark_999"], "kesinlik": "kesin"}]}


# ================================================================== 1. süre bütçesi

def test_uzun_mod_butcesi_360_shorts_90():
    assert cdr.SURE_BUTCESI == {"uzun": 360.0, "shorts": 90.0}


def test_uzun_saglayici_360_sn_istek_tavani_90_ve_yedek_rezervi_korunur():
    g = cdr._gemini("uzun", "AIzaTEST-faz61", "GEMINI_DRYRUN_KEY", lambda *a: None)
    assert g.sure_butcesi == 360.0 and g.zaman_asimi == 90.0          # tekil istek tavanı ≤ 90 sn
    assert g.yedek_rezerv_sn == 60.0 and g.zaman_asimi_yuk == 40.0    # min(60, 360 × 0,4); kısa zaman aşımı
    s = cdr._gemini("shorts", "AIzaTEST-faz61", "GEMINI_DRYRUN_KEY", lambda *a: None)
    assert s.sure_butcesi == 90.0 and s.yedek_rezerv_sn == 36.0


def test_360_sn_butcede_503_timeout_yedek_akisi_degismez():
    """Faz-58 deterministik aşırı yük yolu 360 sn bütçede de aynı: birincil 3, yedek 2 istek; üçüncü model yok."""
    saat, istek, uyku = [0.0], [], []
    sira = {gm.MODELLER[0]: [(503, "x"), "T", (503, "x")], gm.MODELLER[1]: ["T", (503, "x")]}
    sayac = {}

    def t(url, govde, bas, zaman):
        m = url.split("/models/")[1].split(":")[0]
        istek.append((m, zaman))
        i = sayac.get(m, 0)
        sayac[m] = i + 1
        r = sira.get(m, [(404, "x")])[min(i, len(sira.get(m, [0])) - 1)]
        if r == "T":
            saat[0] += zaman
            raise TimeoutError("timed out")
        saat[0] += 1
        return r

    def u(s):
        uyku.append(s)
        saat[0] += s
    g = gm.GeminiLLMProvider(tasiyici=t, uyku=u, saat=lambda: saat[0], anahtar="AIzaTEST-faz61", en_cok_tekrar=1,
                             sure_butcesi=cdr.SURE_BUTCESI["uzun"])
    with pytest.raises(gm.GercekUretimHatasi) as e:
        g.tamamla("x", "sahne_plani", {})
    assert e.value.sinif == "asiri_yuk" and e.value.asiri_yuk_baglami
    assert istek == [(gm.MODELLER[0], 90.0), (gm.MODELLER[0], 40.0), (gm.MODELLER[0], 40.0),
                     (gm.MODELLER[1], 40.0), (gm.MODELLER[1], 40.0)] and uyku == [15.0]


# ================================================================== 2. sahne planı istemi

def test_shorts_plan_istemi_dayanak_ve_sure_kurali():
    ist = sp._istem_plan("Örnekova Muharebesi", "shorts", HAVUZ, ANLATI)
    assert "ZORUNLU dayanak_ids KURALI" in ist and "ark_001, ark_002, ark_003, ark_004, ark_005" in ist
    assert "birim_001, birim_002" in ist and "asla yazma" in ist
    assert "ZORUNLU SÜRE KURALI" in ist and "52–58 sn" in ist and "50–60 sn" in ist
    assert sp.SHORTS_HEDEF_SN == (52, 58)
    lo, hi = sp.kurallar()["shorts"]["toplam_sn"]
    assert lo <= sp.SHORTS_HEDEF_SN[0] < sp.SHORTS_HEDEF_SN[1] <= hi   # hedef bant kapı sınırının içinde


def test_uzun_plan_istemi_dayanak_kurali_var_shorts_sure_kurali_yok():
    ist = sp._istem_plan("Örnekova Muharebesi", "uzun", HAVUZ, dict(ANLATI, mod="uzun"))
    assert "ZORUNLU dayanak_ids KURALI" in ist and "ark_005" in ist
    assert "ZORUNLU SÜRE KURALI" not in ist and "52–58" not in ist


def test_dayanak_listesi_yalniz_havuz_kayit_kimlikleri():
    assert sp.gecerli_dayanak_ids(HAVUZ) == [f"ark_{i:03d}" for i in range(1, 6)]
    assert sp.gecerli_dayanak_ids({}) == [] and sp.gecerli_dayanak_ids(None) == []
    buyuk = {"kayitlar": [{"id": f"ark_{i:03d}"} for i in range(1, 101)]}
    assert "(+20)" in sp._dayanak_kurali(buyuk)                    # istem sınırlı kalır


# ================================================================== 3. hedefli onarım istemi

def _plan(dayanaklar, sureler):
    return {"mod": "shorts", "sahneler": [{"id": f"s{i}", "dayanak_ids": d, "sure_sn": t}
                                          for i, (d, t) in enumerate(zip(dayanaklar, sureler))]}


def test_onarim_dayanak_yok_gecerli_kimlikler_ve_birim_eslemesi():
    mevcut = _plan([["birim_001"], ["birim_002"], ["ark_004"]], [10, 10, 10])
    hatalar = [sp._h("kronoloji_dayanak", "sahneler[0].dayanak_ids", "dayanak_yok", "havuzda olmayan dayanak: ['birim_001']"),
               sp._h("kronoloji_dayanak", "sahneler[1].dayanak_ids", "dayanak_yok", "havuzda olmayan dayanak: ['birim_002']")]
    ist = sp._istem_onarim("sahne_plani", hatalar, mevcut, HAVUZ, "shorts", ANLATI)
    assert "ZORUNLU dayanak_ids KURALI" in ist and "ark_001, ark_002, ark_003, ark_004, ark_005" in ist
    assert "sahneler[0]: birim_001 → ['ark_002']" in ist
    assert "sahneler[1]: birim_002 → ['ark_003']" in ist                 # havuzda olmayan ark_999 önerilmez
    assert sp.ONARIM_TALIMATI in ist and "duzeltmeler" in ist


def test_onarim_toplam_sure_mevcut_ve_hedef_aralik():
    mevcut = _plan([["ark_001"]] * 6, [8, 8, 8, 8, 8, 7])            # 47 sn
    h = [sp._h("sure_ritim", "sahneler[*].sure_sn", "toplam_sure", "toplam 47 sn; 50–60 sn olmalı")]
    ist = sp._istem_onarim("sahne_plani", h, mevcut, HAVUZ, "shorts", ANLATI)
    assert "mevcut toplam sure_sn = 47 sn" in ist and "hedef aralık 50–60 sn" in ist and "52–58 sn'yi hedefle" in ist
    ist_u = sp._istem_onarim("sahne_plani", h, dict(mevcut, mod="uzun"), HAVUZ, "uzun", None)
    lo, hi = sp.kurallar()["uzun"]["toplam_sn"]
    assert f"hedef aralık {lo}–{hi} sn" in ist_u and "52–58" not in ist_u


def test_onarim_ipucu_yalniz_ilgili_hatada_ve_geriye_donuk_uyumlu():
    mevcut = _plan([["ark_001"]], [5])
    h = [sp._h("gorsel", "sahneler[0].gorsel_tur", "gecersiz_enum", "x")]
    ist = sp._istem_onarim("sahne_plani", h, mevcut, HAVUZ, "shorts", ANLATI)
    assert "ZORUNLU" not in ist and "SÜRE:" not in ist
    eski = sp._istem_onarim("sahne_plani", h, mevcut)              # eski imza: havuz/mod/anlatı olmadan çalışır
    assert "sahneler[0].gorsel_tur" in eski
    h2 = [sp._h("kronoloji_dayanak", "sahneler[0].dayanak_ids", "dayanak_yok", "x")]
    assert "ZORUNLU" not in sp._istem_onarim("sahne_plani", h2, mevcut)   # havuz yoksa liste uydurulmaz


def test_adim_onarim_cagrisi_havuz_mod_anlatiyi_istemine_tasir():
    """_adim → hedefli onarım: dayanak_yok + toplam_sure hatasında onarım istemi havuz kimliklerini, birim eşlemesini
    ve mevcut toplam süreyi içerir; yama uygulanınca kapı geçer."""
    istemler = []
    ilk = _plan([["birim_001"], ["ark_004"]], [20, 27])                # 47 sn, birim kimliği

    class Kayit(sp.LLMProvider):
        def tamamla(self, istem, adim, baglam):
            istemler.append((adim, istem))
            if adim == "sahne_plani":
                return json.dumps(ilk)
            return json.dumps({"duzeltmeler": [{"yol": "sahneler[0].dayanak_ids", "deger": ["ark_002"]},
                                               {"yol": "sahneler[1].sure_sn", "deger": 34}]})

    def kapi(v):
        E = []
        for i, s in enumerate(v["sahneler"]):
            E += sp._dayanak_kontrol(s, f"sahneler[{i}]", HAVUZ, "yok")[:1] if any(
                d not in sp.gecerli_dayanak_ids(HAVUZ) for d in s["dayanak_ids"]) else []
        t = sum(s["sure_sn"] for s in v["sahneler"])
        if not 50 <= t <= 60:
            E.append(sp._h("sure_ritim", "sahneler[*].sure_sn", "toplam_sure", f"toplam {t} sn; 50–60 sn olmalı"))
        return E
    r = sp._adim(Kayit(), "sahne_plani", "plan istemi", {"konu": "k", "mod": "shorts", "havuz": HAVUZ, "anlati": ANLATI},
                 kapi, 3)
    assert r["veri"] is not None and r["veri"]["sahneler"][0]["dayanak_ids"] == ["ark_002"]
    onarim = [i for a, i in istemler if a == "onarim"]
    assert len(onarim) == 1
    assert "ark_001, ark_002" in onarim[0] and "sahneler[0]: birim_001 → ['ark_002']" in onarim[0]
    assert "mevcut toplam sure_sn = 47 sn" in onarim[0] and "52–58" in onarim[0]


def test_parcali_uzun_plan_istemleri_de_dayanak_kuralini_tasir():
    from motor.orkestrasyon.llm import MockLLMProvider
    istemler = []

    class Kayit(MockLLMProvider):
        def tamamla(self, istem, adim, baglam):
            istemler.append((adim, istem))
            return super().tamamla(istem, adim, baglam)
    sp.plan_uret("Örnekova Muharebesi", "uzun", Kayit(), parcali=True)
    plan = [i for a, i in istemler if a == "sahne_plani"]
    assert plan and all("ZORUNLU dayanak_ids KURALI" in i and "ZORUNLU SÜRE KURALI" not in i for i in plan)
