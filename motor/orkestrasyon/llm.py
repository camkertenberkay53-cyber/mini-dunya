"""LLM sağlayıcı arayüzü ve ağsız testler için deterministik MockLLMProvider.

Sağlayıcılar yalnızca METİN döndürür; JSON çözümleme ve doğrulama planlayıcının Validation Gate'inde yapılır.
LLM çıktısı hiçbir zaman doğrudan üretim motoruna verilmez.

MockLLMProvider gerçek bir kaynak ya da gerçek bir tarihî bilgi ÜRETMEZ:
- Bütün kayıt ve kaynak kimlikleri `mock_` önekiyle başlar.
- Her kayıt `"sentetik_mock": true` olarak işaretlidir.
- Metinler açıkça "sentetik" olarak etiketlenir.
Planlayıcı, sentetik veriyle üretilen planı `yayin_icin_uygun: false` olarak işaretler.
"""
from __future__ import annotations

import copy
import json
from abc import ABC, abstractmethod
from typing import Callable


class LLMHatasi(Exception):
    pass


class LLMProvider(ABC):
    """adim: 'arastirma' | 'anlati' | 'sahne_plani' | 'onarim'. baglam: yapılandırılmış ek bilgi (gerçek sağlayıcılar
    yalnızca istemi kullanır; istem bütün bilgiyi metin olarak taşır)."""
    ad: str = "soyut"
    sentetik: bool = False

    @abstractmethod
    def tamamla(self, istem: str, adim: str, baglam: dict) -> str:
        ...


# ------------------------------------------------------------------ deterministik mock

def _kod(i: int) -> str:
    """0 → 'A', 25 → 'Z', 26 → 'AA' … (anlatım metinlerinde rakam kullanmadan benzersiz etiket)."""
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


_OLAYLAR = [   # (olay_id, ad, yıl, ambiyans)
    ("mock_olay_1", "hazırlık", 1400, "saray"),
    ("mock_olay_2", "gerilim", 1402, "ruzgar"),
    ("mock_olay_3", "çatışma", 1403, "kusatma"),
    ("mock_olay_4", "dönüm", 1404, "kusatma"),
    ("mock_olay_5", "sonuç", 1405, "sessiz"),
]
_ACILAR = ["coğrafya", "lojistik", "liderlik", "diplomasi", "toplum", "ekonomi", "strateji", "moral", "teknik", "sonrası"]


class MockLLMProvider(LLMProvider):
    """Deterministik sentetik çıktı. Testler için hata enjeksiyonu:

    bozulmalar: {adim: [fn(veri)->None, ...]}. Her fonksiyon o adımın İLK çıktısını yerinde bozar.
    onarim_kipi:
      'dogru': onarım istemindeki yolları mock'un bildiği doğru değerle düzeltir.
      'hicbir': boş düzeltme döndürür (fail-safe testi).
      'alan_disi': istenmeyen bir alanı da değiştirmeye çalışır (reddedilmeli).
    ham_bozuk: {adim: n}. O adımın ilk n çıktısı JSON olarak çözümlenemez.
    """
    ad = "mock"
    sentetik = True

    def __init__(self, bozulmalar: dict | None = None, onarim_kipi: str = "dogru", ham_bozuk: dict | None = None):
        self.bozulmalar = bozulmalar or {}
        self.onarim_kipi = onarim_kipi
        self.ham_bozuk = dict(ham_bozuk or {})
        self.cagrilar: list[dict] = []
        self._dogru: dict[str, dict] = {}

    # ---- arayüz
    def tamamla(self, istem: str, adim: str, baglam: dict) -> str:
        self.cagrilar.append({"adim": adim, "istem": istem, "hedef": baglam.get("hedef_adim")})
        if adim == "onarim":
            return json.dumps(self._onar(baglam), ensure_ascii=False)
        if self.ham_bozuk.get(adim, 0) > 0:
            self.ham_bozuk[adim] -= 1
            return "Elbette! İşte plan: {bozuk json"
        uret = {"arastirma": self._arastirma, "anlati": self._anlati, "sahne_plani": self._sahne_plani}[adim]
        veri = uret(baglam)
        self._dogru[adim] = copy.deepcopy(veri)
        if not any(c["adim"] == adim for c in self.cagrilar[:-1]):
            for fn in self.bozulmalar.get(adim, []):
                fn(veri)
        return json.dumps(veri, ensure_ascii=False)

    # ---- onarım: yalnızca istenen yollar
    def _onar(self, baglam: dict) -> dict:
        if self.onarim_kipi == "hicbir":
            return {"duzeltmeler": []}
        hedef = baglam["hedef_adim"]
        dogru = self._dogru.get(hedef, {})
        duz = []
        for yol in baglam.get("onarilacak_yollar", []):
            for somut in _yollari_ac(yol, baglam.get("mevcut", {})):
                try:
                    duz.append({"yol": somut, "deger": _al(dogru, somut)})
                except (KeyError, IndexError, TypeError):
                    pass
        if self.onarim_kipi == "alan_disi":
            duz.append({"yol": "baslik", "deger": "izinsiz değişiklik"})
        return {"duzeltmeler": duz}

    # ---- sentetik içerik
    def _arastirma(self, b: dict) -> dict:
        konu = b["konu"]
        kayitlar, i = [], 0
        for oid, ad, yil, _ in _OLAYLAR:
            for j in range(5):
                i += 1
                kid = f"mock_{i:03d}"
                k = {"id": kid, "olay_id": oid, "tur": ["olay", "kisi", "yer", "tarih", "baglam"][j], "yil": yil,
                     "iddia": f"[SENTETİK] {konu}: {ad} evresi {yil} yılında, {_ACILAR[(i + j) % len(_ACILAR)]} "
                              f"yönüyle anlatılır.",
                     "durum": "dogrulanmis",
                     "kaynaklar": [{"id": f"mock_kaynak_{(i % 4) + 1:02d}", "eser": "Sentetik test kaynağı (gerçek değil)",
                                    "sentetik_mock": True}],
                     "sentetik_mock": True}
                kayitlar.append(k)
        # tartışmalı sayı ve belirsiz tarih: doğrulanmış gibi sunulmaz
        kayitlar[12].update({"tur": "sayi", "durum": "tartismali",
                             "iddia": f"[SENTETİK] {konu}: kuvvet mevcudu 4000 ile 6000 arasında tahmin edilir.",
                             "celiski_notu": "iki sentetik kaynak farklı sayı verir",
                             "kaynaklar": [{"id": "mock_kaynak_01", "eser": "Sentetik test kaynağı A", "sentetik_mock": True},
                                           {"id": "mock_kaynak_02", "eser": "Sentetik test kaynağı B", "sentetik_mock": True}]})
        kayitlar[21].update({"tur": "tarih", "durum": "belirsiz", "yil": None,
                             "iddia": f"[SENTETİK] {konu}: sonuç antlaşmasının kesin tarihi bilinmiyor.",
                             "kaynaklar": []})
        return {"konu": konu, "kayitlar": kayitlar}

    def _anlati(self, b: dict) -> dict:
        havuz = {k["id"]: k for k in b["havuz"]["kayitlar"]}
        olay_kayit = {}
        for k in b["havuz"]["kayitlar"]:
            olay_kayit.setdefault(k["olay_id"], []).append(k["id"])
        if b["mod"] == "shorts":
            plan = [("hook", "mock_olay_3", 1), ("akis", "mock_olay_3", 8), ("kapanis", "mock_olay_3", 3)]
        else:
            plan = [("hook", "mock_olay_4", 4), ("baglam", "mock_olay_1", 12), ("baglam", "mock_olay_2", 13),
                    ("catisma", "mock_olay_3", 40), ("donum_noktasi", "mock_olay_4", 30), ("sonuc", "mock_olay_5", 19)]
        birimler, n = [], 0
        for bolum, oid, adet in plan:
            ids = olay_kayit[oid]
            for j in range(adet):
                kid = ids[j % len(ids)]
                k = havuz[kid]
                temkin = k["durum"] != "dogrulanmis"
                metin = (f"{'Bazı kaynaklara göre ' if temkin else ''}{k['iddia']} "
                         f"Bu sahne {_ACILAR[n % len(_ACILAR)]} yönünü öne çıkarır [{_kod(n)}].")
                birimler.append({"id": f"b{n + 1:03d}", "bolum": bolum, "metin": metin, "dayanak_ids": [kid],
                                 "kesinlik": "tartismali" if temkin else "kesin"})
                n += 1
        return {"mod": b["mod"], "birimler": birimler}

    def _sahne_plani(self, b: dict) -> dict:
        mod = b["mod"]
        birimler = b["anlati"]["birimler"]
        olay_amb = {o[0]: o[3] for o in _OLAYLAR}
        havuz = {k["id"]: k for k in b["havuz"]["kayitlar"]}
        sahneler = []
        if mod == "shorts":
            turler = ["gorsel25d", "harita", "gorsel25d", "sahne3d", "harita", "gorsel25d", "harita", "gorsel25d",
                      "sahne3d", "gorsel25d", "harita", "gorsel25d"]
            sureler = [3, 5, 4, 5, 4, 5, 4, 5, 5, 6, 5, 5]
        else:
            dongu = ["harita", "gorsel25d", "harita", "gorsel25d", "sahne3d"]
            turler = [dongu[i % 5] for i in range(len(birimler))]
            sureler = []
            for i, t in enumerate(turler):
                if t == "harita" and i % 20 == 0:
                    sureler.append(14)
                elif t == "gorsel25d" and i % 15 == 1:
                    sureler.append(5)
                elif t == "gorsel25d" and i % 2 == 1:
                    sureler.append(10)
                else:
                    sureler.append(8)
        for i, (bi, t, s) in enumerate(zip(birimler, turler, sureler)):
            k = havuz[bi["dayanak_ids"][0]]
            ritim = ("kritik_harita" if s > 12 else "vurgu" if s < 6 and mod == "uzun" else
                     "atmosfer" if s >= 10 else "normal")
            sh = {"id": f"s{i + 1:03d}", "bolum": bi["bolum"], "anlatim": bi["metin"], "dayanak_ids": list(bi["dayanak_ids"]),
                  "kesinlik": bi["kesinlik"], "sure_sn": s, "ritim": ritim, "gorsel_tur": t,
                  "hareketli": t != "harita", "katki": f"{_ACILAR[i % len(_ACILAR)]} bilgisi [{_kod(i)}]",
                  "ton": ["ciddi", "gerilimli", "epos"][i % 3], "gecis_efekti": "boom" if (i == 0 or (i > 0 and bi["bolum"] != birimler[i - 1]["bolum"])) else "yok",
                  "ambiyans": olay_amb[k["olay_id"]], "hook": i == 0}
            if t == "harita":
                sh["cografi_amac"] = f"[SENTETİK] kuvvetlerin {_ACILAR[i % len(_ACILAR)]} açısından konumu ve hareket yönü"
            elif t == "gorsel25d":
                sh["arama_sorgulari"] = [f"{b['konu']} {_ACILAR[i % len(_ACILAR)]}", f"{b['konu']} minyatür"]
            else:
                sh["uc_boyut_gerekcesi"] = "[SENTETİK] birliklerin dizilişi ancak üç boyutta anlaşılır"
            sahneler.append(sh)
        plan = {"mod": mod, "baslik": f"[SENTETİK] {b['konu']}", "uretim": "ayri", "sahneler": sahneler}
        if mod == "shorts":
            plan.update({"ana_fikir": f"[SENTETİK] {b['konu']}: çatışma evresinin tek kritik anı", "ana_olay_id": "mock_olay_3"})
        return plan


# ------------------------------------------------------------------ yol yardımcıları (planlayıcı da kullanır)

def _parcala(yol: str) -> list:
    out = []
    for p in yol.split("."):
        while "[" in p:
            ad, kalan = p.split("[", 1)
            if ad:
                out.append(ad)
            idx, p = kalan.split("]", 1)
            out.append("*" if idx == "*" else int(idx))
        if p:
            out.append(p)
    return out


def _al(veri, yol: str):
    for p in _parcala(yol):
        veri = veri[p]
    return veri


def _yollari_ac(yol: str, veri) -> list[str]:
    """'sahneler[*].sure_sn' → mevcut veride somut yollar."""
    if "[*]" not in yol:
        return [yol]
    on, arka = yol.split("[*]", 1)
    try:
        n = len(_al(veri, on))
    except (KeyError, IndexError, TypeError):
        return []
    return [y for i in range(n) for y in _yollari_ac(f"{on}[{i}]{arka}", veri)]


def yol_ayarla(veri, yol: str, deger) -> None:
    p = _parcala(yol)
    for x in p[:-1]:
        veri = veri[x]
    veri[p[-1]] = deger


Duzeltici = Callable[[dict], None]
