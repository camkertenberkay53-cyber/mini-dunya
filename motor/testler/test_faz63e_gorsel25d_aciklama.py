"""Faz-63e — 2.5D niyetinde 'aciklama' (çekim metni) normalizasyonu. Alan NİYET düzeyindedir (şemada gorsel25d
nesnesi additionalProperties:false ve 'aciklama' içermez); planlayıcı onu çekim metni yapar, plan_denetim boşu reddeder.
Tamamlama yalnız mevcut veriden: yanlış yerdeki iç açıklama ya da indirilen görselin kaydı. Çevrimdışı."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from motor.uretim import sozlesme

KOK = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("otonom_uret_63e", KOK / "otonom_uret.py")
ou = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ou)
PILOT = KOK / "motor/uretim/pilotlar/otlukbeli-1473"
ARA = json.loads((PILOT / "arastirma.json").read_text())
G = [{"gorsel_id": "g-mehmed", "aciklama": "II. Mehmed portresi (Gentile Bellini, 1480)"},
     {"gorsel_id": "g-harita", "aciklama": "1730 tarihli Seutter Anadolu haritası"},
     {"gorsel_id": "g-bos", "aciklama": "   "}]
METIN = "Bir yanda Fatih Sultan Mehmed, öbür yanda Uzun Hasan."


def _cumle(i, niyet, metin=METIN):
    return {"id": f"S{i}", "metin": metin, "kartlar": ["C2"], "niyet": niyet}


def _g25(gid="g-mehmed", **ek):
    return {"tur": "gorsel25d", "gorsel25d": {"gorsel_id": gid}, **ek}


def _sen(*niyetler):
    return {"surum": 1, "konu": "k", "format": "shorts", "baslik": "B", "kanca": "S1", "final": f"S{len(niyetler)}",
            "ana_fikir": "Toplar savaşın kaderini belirledi.",
            "cumleler": [_cumle(i + 1, n) for i, n in enumerate(niyetler)]}


def _n(v, i=0):
    return v["cumleler"][i]["niyet"]


# ================================================================== tespit: alanın yeri

def test_aciklama_niyet_duzeyinde_gorsel25d_icinde_degil():
    sema = sozlesme.sema("senaryo")["$defs"]["niyet"]
    assert "aciklama" in sema["properties"] and "aciklama" not in sema["properties"]["gorsel25d"]["properties"]
    assert sema["properties"]["gorsel25d"]["additionalProperties"] is False
    yanlis = _sen(_g25(gorsel25d={"gorsel_id": "g-mehmed", "aciklama": "x"}))
    _n(yanlis)["gorsel25d"] = {"gorsel_id": "g-mehmed", "aciklama": "x"}
    assert any("aciklama" in h and "unexpected" in h for h in sozlesme.senaryo_denetle(yanlis, ARA))
    assert 'c["metin"] = n.get("metin") or n.get("aciklama", "")' in (KOK / "motor/uretim/planlayici.py").read_text()


# ================================================================== normalizasyon

def test_eksik_aciklama_gorsel_kaydindan_tamamlanir():
    v = ou.normalize_senaryo(_sen(_g25()), gorseller=G)
    assert _n(v)["aciklama"] == "II. Mehmed portresi (Gentile Bellini, 1480)"
    assert v["cumleler"][0]["metin"] == METIN                                     # anlatı metni değişmez
    assert sozlesme.senaryo_denetle(v, ARA) == []


@pytest.mark.parametrize("bos", ["", "   ", None])
def test_bos_aciklama_tamamlanir(bos):
    v = ou.normalize_senaryo(_sen(_g25(aciklama=bos)), gorseller=G)
    assert _n(v)["aciklama"] == G[0]["aciklama"]


def test_mevcut_aciklama_korunur():
    v = ou.normalize_senaryo(_sen(_g25(aciklama="Portreye yavaş yakınlaşma")), gorseller=G)
    assert _n(v)["aciklama"] == "Portreye yavaş yakınlaşma"


def test_metin_alani_varsa_aciklama_eklenmez():
    v = ou.normalize_senaryo(_sen(_g25(metin="Sultanın portresi")), gorseller=G)
    assert "aciklama" not in _n(v) and _n(v)["metin"] == "Sultanın portresi"


def test_yanlis_yerdeki_ic_aciklama_niyet_duzeyine_tasinir():
    n = _g25()
    n["gorsel25d"]["aciklama"] = "Portrenin yüzüne itme"
    n["gorsel25d"]["hareket"] = "push_in"
    v = ou.normalize_senaryo(_sen(n), gorseller=G)
    assert _n(v)["aciklama"] == "Portrenin yüzüne itme"
    assert _n(v)["gorsel25d"] == {"gorsel_id": "g-mehmed", "hareket": "push_in"}   # diğer iç alanlar kalır
    assert sozlesme.senaryo_denetle(v, ARA) == []


def test_ic_aciklama_varken_ust_aciklama_doluysa_dokunulmaz():
    n = _g25(aciklama="üst")
    n["gorsel25d"]["aciklama"] = "iç"
    v = ou.normalize_senaryo(_sen(n), gorseller=G)
    assert _n(v)["aciklama"] == "üst" and _n(v)["gorsel25d"]["aciklama"] == "iç"   # şema yine yakalar


@pytest.mark.parametrize("niyet, gorseller", [
    (_g25("g-yok"), G),                                     # görsel kaydı yok
    (_g25("g-bos"), G),                                     # kayıtta açıklama boş
    (_g25(), []),                                           # görsel listesi boş
    ({"tur": "gorsel25d", "gorsel25d": {}}, G),             # gorsel_id yok
    (_g25(aciklama=5), G),                                  # metin olmayan değer: dokunulmaz
])
def test_yetersiz_veride_uydurma_yok_dogrulayici_hata_verir(niyet, gorseller):
    k = ou.konu_kur(PILOT, "Otlukbeli Savaşı", "shorts")
    v = ou.normalize_senaryo(_sen(copy.deepcopy(niyet)), gorseller=gorseller)
    assert _n(v).get("aciklama") == niyet.get("aciklama")
    h = ou.senaryo_denetle(v, ARA, k, gorseller, lambda cs: {})
    assert any("aciklama" in x or "gorsel_id" in x or "is not of type" in x for x in h)


def test_cumle_metni_aciklama_kaynagi_olarak_kullanilmaz():
    v = ou.normalize_senaryo(_sen(_g25("g-yok")), gorseller=G)
    assert METIN not in json.dumps(_n(v), ensure_ascii=False)


def test_gorseller_verilmezse_davranis_onceki_gibi():
    s = _sen(_g25())
    assert "aciklama" not in _n(ou.normalize_senaryo(s))


def test_diger_turlere_dokunulmaz():
    v = ou.normalize_senaryo(_sen({"tur": "harita", "evre": "E1"}, {"tur": "3d", "aciklama": ""}), gorseller=G)
    assert _n(v, 0) == {"tur": "harita", "evre": "E1"} and _n(v, 1) == {"tur": "3d", "aciklama": ""}


@pytest.mark.parametrize("niyetler", [
    [_g25()], [_g25(aciklama="")], [_g25("g-yok")], [_g25(metin="m")],
    [{"tur": "gorsel25d", "gorsel25d": {"gorsel_id": "g-harita", "aciklama": "iç"}}, _g25()],
])
def test_idempotent_ve_bilinmeyen_alanlar_kalir(niyetler):
    s = _sen(*copy.deepcopy(niyetler))
    s["gemini_notu"] = {"x": 1}
    for c in s["cumleler"]:
        c["niyet"]["ozel"] = "k"
    kopya = copy.deepcopy(s)
    bir = ou.normalize_senaryo(s, gorseller=G)
    assert s == kopya                                                             # girdi değişmez
    assert ou.normalize_senaryo(copy.deepcopy(bir), gorseller=G) == bir
    assert bir["gemini_notu"] == {"x": 1} and all(c["niyet"]["ozel"] == "k" for c in bir["cumleler"])


# ================================================================== Shorts ve uzun uyumluluğu

def test_shorts_akisi_aciklamasiz_gemini_yaniti_ilk_denemede_gecer(monkeypatch):
    """Gerçek koşu hatası: 'S1: gorsel25d niyetinde 'aciklama' zorunlu (çekim metni)' (S1, S2, S3, S10)."""
    k = ou.konu_kur(PILOT, "Otlukbeli Savaşı", "shorts")
    g = [{"gorsel_id": f"{k['kimlik']}-g{i}", "aciklama": f"görsel {i} tarifi"} for i in range(3)]
    sen = _sen(*[{"tur": "gorsel25d", "gorsel25d": {"gorsel_id": x["gorsel_id"]}} for x in g])
    ham = copy.deepcopy(sen)
    assert sum("'aciklama' zorunlu" in h for h in ou.senaryo_denetle(ham, ARA, k, g, lambda cs: {})) == 3   # önce
    monkeypatch.setattr(ou, "senaryo_denetle", _gercek_shorts_denetimi)   # TTS süresi/anlatı yapısı burada sınanmaz
    class Sahte:
        cagri_sayisi = 0
        istem = ""

        def tamamla(self, istem, adim, baglam):
            self.cagri_sayisi += 1
            self.istem = istem
            return json.dumps(sen, ensure_ascii=False)
    s = Sahte()
    out, gecmis = ou.senaryo_uret(s, k, ARA, g)
    assert s.cagri_sayisi == 1 and gecmis[0]["hatalar"] == []
    assert [c["niyet"]["aciklama"] for c in out["cumleler"]] == [x["aciklama"] for x in g]
    assert "gorsel25d nesnesinin İÇİNE yazılmaz" in s.istem and "çekim tarifini" in s.istem


def _gercek_shorts_denetimi(s, ara, konu, gorseller, olc=None):
    """otonom senaryo_denetle'nin şema + kart + 2.5D + görsel kapısı kısmı (TTS süresi ve anlatı yapısı hariç)."""
    from motor.uretim import sozlesme as sz
    h = sz.senaryo_denetle(s, ara)
    gecerli = {g["gorsel_id"] for g in gorseller}
    for c in s["cumleler"]:
        n = c["niyet"]
        if n["tur"] == "gorsel25d" and (n.get("gorsel25d") or {}).get("gorsel_id") not in gecerli:
            h.append(f"{c['id']}: gorsel_id")
        elif n["tur"] == "gorsel25d" and not (n.get("aciklama") or n.get("metin")):
            h.append(f"{c['id']}: gorsel25d niyetinde 'aciklama' zorunlu (çekim metni)")
    return h + [x for x in ou.gorsel_kapisi("shorts", gorseller, s) if "indirildi" not in x]


def test_uzun_bolum_niyeti_ayni_ortak_kurali_kullanir():
    konu = ou.konu_kur(PILOT, "Otlukbeli Savaşı", "uzun")
    n, h = ou.niyet_normalle({"tur": "gorsel25d", "gorsel_id": "g-mehmed", "hareket": "pan_sol"}, G, [], konu)
    assert h is None and n == {"tur": "gorsel25d", "gorsel25d": {"gorsel_id": "g-mehmed", "hareket": "pan_sol"},
                               "aciklama": G[0]["aciklama"]}
    n, h = ou.niyet_normalle({"tur": "gorsel25d", "gorsel_id": "g-mehmed", "aciklama": "Profil yakın plan"}, G, [], konu)
    assert n["aciklama"] == "Profil yakın plan"                                  # mevcut korunur
    n, h = ou.niyet_normalle({"tur": "gorsel25d", "gorsel_id": "g-mehmed", "aciklama": " "}, G, [], konu)
    assert n["aciklama"] == G[0]["aciklama"]
    n, h = ou.niyet_normalle({"tur": "gorsel25d", "gorsel_id": "g-bos"}, G, [], konu)
    assert n is None and h == "gorsel25d: 'aciklama' zorunlu"                    # veri yok → açık hata


def test_uzun_bolum_istemi_kurali_icerir():
    konu = ou.konu_kur(PILOT, "Otlukbeli Savaşı", "uzun")
    i = ou.niyet_kurallari_uzun(konu, G, [], {})
    assert ou.ACIKLAMA_KURALI in i and "çekim tarifi" in i


def test_shorts_ve_uzun_sonrasi_ayni_kanonik_bicim():
    konu = ou.konu_kur(PILOT, "Otlukbeli Savaşı", "uzun")
    uz, _ = ou.niyet_normalle({"tur": "gorsel25d", "gorsel_id": "g-mehmed", "hareket": "zoom_in"}, G, [], konu)
    sh = _n(ou.normalize_senaryo(_sen({"tur": "gorsel25d", "gorsel25d": {"gorsel_id": "g-mehmed", "hareket": "zoom_in"}}),
                                 gorseller=G))
    assert uz == sh
