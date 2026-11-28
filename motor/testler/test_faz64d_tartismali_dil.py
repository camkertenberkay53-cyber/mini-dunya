"""Faz-64d — tartışmalı kartlar için ihtiyatlı dil ve hedefli cümle onarımı.

- Doğrulayıcı (sozlesme.senaryo_denetle, kurallar/dil_tr.yaml) DEĞİŞMEDİ: 'tartismali'/'belirsiz' karta dayanan cümle
  temkin ifadesi taşımalı; 'kesin'/'makul' (doğrulanmış) kartlar için böyle bir zorunluluk yok.
- Prompt: tartışmalı kartlar içerikleriyle vurgulanır; Shorts'ta doğrulanmış kartlar önceliklidir; doğrulayıcının
  eşleştirmediği türevler ('söyleniyor', cümle başında 'İddia edilir') açıkça uyarılır.
- Hedefli onarım: hataların TAMAMI tartışmalı-dil hatasıysa ve en çok 2 cümledeyse yalnız o cümlelerin metni yeniden
  yazdırılır; diğer cümleler, kartlar, niyetler (3D/harita/kamera) ve kanca bayt bayt korunur; sonuç tam kapıdan geçer.
Gerçek pilot senaryo ve araştırma (korunan sozlesme kapısı gerçek) kullanılır; yalnız TTS ölçümü sahte."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from motor.uretim import sozlesme, veri

KOK = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("otonom_uret_64d", KOK / "otonom_uret.py")
ou = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ou)
PILOT = KOK / "motor/uretim/pilotlar/otlukbeli-1473"
SEN = json.loads((PILOT / "senaryo.json").read_text())
ARA = json.loads((PILOT / "arastirma.json").read_text())


def _ara(*tartismali):
    a = copy.deepcopy(ARA)
    for c in a["kartlar"]:
        if c["id"] in tartismali:
            c["guven"] = "tartismali"
    return a


def _cumle(s, cid):
    return next(c for c in s["cumleler"] if c["id"] == cid)


def _olc(cs):
    return {c["id"]: {"sure_sn": 5.0, "harf_sn": 14, "motor": "s", "wav": "x"} for c in cs}


@pytest.fixture
def kapi(monkeypatch):
    """sozlesme GERÇEK; yalnız TTS'e bağlı anlatı ölçümü ve görsel sayısı yalıtılır."""
    from motor.uretim import anlati
    monkeypatch.setattr(anlati, "shorts_denetle", lambda s, sr: ([], {}))
    monkeypatch.setattr(ou, "EN_AZ_GORSEL", {"shorts": 0, "uzun": 0})
    return dict(ou.konu_kur(PILOT, "Otlukbeli Savaşı", "shorts"), hedef_sure_sn=[1, 200])


class Sahte:
    def __init__(self, yanitlar):
        self.yanitlar, self.cagrilar = list(yanitlar), []

    def tamamla(self, istem, adim, baglam):
        self.cagrilar.append((istem, baglam))
        return self.yanitlar.pop(0)


def _onarim(**metinler):
    return json.dumps({"cumleler": [{"id": k, "metin": v} for k, v in metinler.items()]})


S3_IHTIYATLI = "Bazı kaynaklara göre Osmanlı topları Akkoyunlu süvarisini dağıttı."
S5_IHTIYATLI = "Yeniçerilerin hattı tuttuğu rivayet edilir."


# ================================================================== doğrulanmış / tartışmalı dil ayrımı (gerçek kapı)

def test_pilot_senaryo_dogrulanmis_kartlarla_gecer_tartismali_kartla_takilir():
    assert sozlesme.senaryo_denetle(SEN, ARA) == []                      # kesin/makul: ihtiyat gerekmez
    h = sozlesme.senaryo_denetle(SEN, _ara("C1"))
    assert h == ["S3: 'tartismali' karta (C1) dayanıyor ama kesin dille anlatılmış"]


@pytest.mark.parametrize("metin,gecer", [
    ("Bazı kaynaklara göre ordu dağıldı.", True),
    ("Ordunun dağıldığı rivayet edilir.", True),
    ("Rivayete göre ordu dağıldı.", True),
    ("Ordunun dağıldığı iddia edilir.", True),
    ("Ordu dağıldı.", False),
    ("Ordunun dağıldığı söyleniyor.", False),        # türev: 'söylenir' ile eşleşmez
    ("İddia edilir ki ordu dağıldı.", False),        # 'İ'.lower() noktalı i: eşleşmez (promptta uyarılır)
])
def test_temkin_olcutu_dogrulayiciyla_ayni(metin, gecer):
    s = copy.deepcopy(SEN)
    _cumle(s, "S3")["metin"] = metin
    hata = any("kesin dille" in x for x in sozlesme.senaryo_denetle(s, _ara("C1")))
    assert hata is (not gecer) and ou.temkin_var(metin) is gecer


# ================================================================== prompt

def test_prompt_tartismali_kartlari_vurgular_shorts_dogrulanmisi_onceler():
    k = ou.kaynak_ihtiyati_kurali(_ara("C1"), "shorts")
    c1 = next(c for c in ARA["kartlar"] if c["id"] == "C1")
    assert f"⚠ C1 [TARTISMALI] — ihtiyatlı anlat: {c1['iddia']}" in k
    assert "⚠ C2" not in k and "tartışmalı kartlar: C1." in k
    assert "SHORTS: önce doğrulanmış ('kesin'/'makul') kartlara dayan" in k
    assert "'söyleniyor'" in k and "TÜREVLER sayılmaz" in k and "\"…olduğu iddia edilir.\"" in k
    assert "SHORTS:" not in ou.kaynak_ihtiyati_kurali(_ara("C1"))      # uzun istemi Shorts önceliğini almaz


def test_shorts_senaryo_istemi_shorts_ihtiyat_kuralini_tasir(kapi):
    sg = Sahte([json.dumps(SEN)])
    ou.senaryo_uret(sg, kapi, ARA, [], olc=_olc)
    assert ou.kaynak_ihtiyati_kurali(ARA, "shorts") in sg.cagrilar[0][0]


# ================================================================== hata ayrıştırma

def test_temkin_hatali_cumleler_yalniz_saf_temkin_hatalarinda():
    h = sozlesme.senaryo_denetle(SEN, _ara("C1", "C3"))
    assert ou.temkin_hatali_cumleler(h) == {"S3": ["C1"], "S5": ["C3"]}
    assert ou.temkin_hatali_cumleler(["S1: 'belirsiz' karta (C9) dayanıyor ama kesin dille anlatılmış"]) == {"S1": ["C9"]}
    assert ou.temkin_hatali_cumleler(h + ["S2: tanımsız kart C99"]) is None
    assert ou.temkin_hatali_cumleler([]) is None


# ================================================================== hedefli onarım

def test_hedefli_onarim_yalniz_hedef_metni_degistirir():
    s = copy.deepcopy(SEN)
    _cumle(s, "S3")["okunus"] = "eski okunuş"
    sg = Sahte([_onarim(S3=S3_IHTIYATLI)])
    o, neden = ou.hedefli_onar(sg, s, {"S3": ["C1"]}, _ara("C1"), 1)
    assert neden == [] and _cumle(o, "S3")["metin"] == S3_IHTIYATLI and "okunus" not in _cumle(o, "S3")
    beklenen = copy.deepcopy(s)
    _cumle(beklenen, "S3")["metin"] = S3_IHTIYATLI
    _cumle(beklenen, "S3").pop("okunus")
    assert o == beklenen and s["cumleler"][2]["okunus"] == "eski okunuş"   # girdi değişmez; başka hiçbir alan değişmez
    istem, baglam = sg.cagrilar[0]
    assert baglam["yanit_semasi"] is ou.ONARIM_API_SEMASI and baglam["bolum"] == "deneme1-onarim"
    assert "- S3:" in istem and "- S4:" not in istem and "mekanik olarak başa yapıştırma" in istem


@pytest.mark.parametrize("yanit,parca", [
    ("JSON değil", "JSON değil"),
    (_onarim(S3="Osmanlı topları süvariyi dağıttı."), "hâlâ ihtiyat ifadesi yok"),
    (_onarim(S3=S3_IHTIYATLI, S4="Bazı kaynaklara göre x."), "cümle kümesi uymuyor"),
    (_onarim(S4="Bazı kaynaklara göre x."), "cümle kümesi uymuyor"),
    (_onarim(S3="bazı kaynaklara göre " + "çok " * 20), "kelime"),
])
def test_hedefli_onarim_gecersiz_yaniti_reddeder(yanit, parca):
    o, neden = ou.hedefli_onar(Sahte([yanit]), SEN, {"S3": ["C1"]}, _ara("C1"), 1)
    assert o is None and any(parca in x for x in neden)


def test_senaryo_uret_hedefli_onarimla_ayni_denemede_gecer(kapi):
    ara = _ara("C1", "C3")
    sg = Sahte([json.dumps(SEN), _onarim(S3=S3_IHTIYATLI, S5=S5_IHTIYATLI)])
    sen, gecmis = ou.senaryo_uret(sg, kapi, ara, [], olc=_olc)
    assert len(sg.cagrilar) == 2 and len(gecmis) == 1                  # tüm senaryo yeniden üretilmedi
    assert gecmis[0]["hedefli_onarim"] == {"cumleler": ["S3", "S5"], "hatalar": []}
    for a, b in zip(SEN["cumleler"], sen["cumleler"]):
        assert (a["id"], a["kartlar"], a["niyet"], a.get("amac")) == (b["id"], b["kartlar"], b["niyet"], b.get("amac"))
        assert b["metin"] == {"S3": S3_IHTIYATLI, "S5": S5_IHTIYATLI}.get(a["id"], a["metin"])
    assert (sen["kanca"], sen["final"]) == (SEN["kanca"], SEN["final"])
    assert sozlesme.senaryo_denetle(sen, ara) == []


def test_ikiden_fazla_cumle_hedefli_onarilmaz_tam_yeniden_uretilir(kapi):
    ara = _ara("C1", "C3", "C5")
    iyi = copy.deepcopy(SEN)
    for cid, m in (("S3", S3_IHTIYATLI), ("S5", S5_IHTIYATLI), ("S7", "Bazı kaynaklara göre savaş kısa sürdü.")):
        _cumle(iyi, cid)["metin"] = m
    sg = Sahte([json.dumps(SEN), json.dumps(iyi)])
    sen, gecmis = ou.senaryo_uret(sg, kapi, ara, [], olc=_olc)
    assert len(gecmis) == 2 and "hedefli_onarim" not in gecmis[0]
    assert sg.cagrilar[1][1]["bolum"] == "deneme2" and "S7: 'tartismali'" in sg.cagrilar[1][0]


def test_basarisiz_onarim_normal_yeniden_denemeye_duser(kapi):
    ara = _ara("C1")
    iyi = copy.deepcopy(SEN)
    _cumle(iyi, "S3")["metin"] = S3_IHTIYATLI
    sg = Sahte([json.dumps(SEN), _onarim(S3="Osmanlı topları süvariyi dağıttı."), json.dumps(iyi)])
    sen, gecmis = ou.senaryo_uret(sg, kapi, ara, [], olc=_olc)
    assert len(gecmis) == 2 and "hâlâ ihtiyat ifadesi yok" in gecmis[0]["hedefli_onarim"]["hatalar"][0]
    assert "S3: 'tartismali' karta (C1)" in sg.cagrilar[2][0] and _cumle(sen, "S3")["metin"] == S3_IHTIYATLI


def test_baska_hata_varsa_hedefli_onarim_denenmez(kapi):
    ara = _ara("C1")
    kotu = copy.deepcopy(SEN)
    _cumle(kotu, "S4")["kartlar"] = ["C99"]
    iyi = copy.deepcopy(SEN)
    _cumle(iyi, "S3")["metin"] = S3_IHTIYATLI
    sg = Sahte([json.dumps(kotu), json.dumps(iyi)])
    _, gecmis = ou.senaryo_uret(sg, kapi, ara, [], olc=_olc)
    assert len(sg.cagrilar) == 2 and "hedefli_onarim" not in gecmis[0]


def test_onarim_sonrasi_tam_kapi_yeniden_calisir(kapi, monkeypatch):
    """Onarılan senaryo kısa yoldan kabul edilmez: tam kapı (TTS/anlatı dâhil) yeniden koşar."""
    from motor.uretim import anlati
    monkeypatch.setattr(anlati, "shorts_denetle",
                        lambda s, sr: (["kanca seslendirmesi 2.1 sn"] if "Bazı kaynaklara" in _cumle(s, "S3")["metin"]
                                       else [], {}))
    sg = Sahte([json.dumps(SEN), _onarim(S3=S3_IHTIYATLI), json.dumps(SEN)])
    with pytest.raises(ou.UretimHatasi):
        ou.senaryo_uret(sg, kapi, _ara("C1"), [], deneme=1, olc=_olc)
    assert len(sg.cagrilar) == 2
