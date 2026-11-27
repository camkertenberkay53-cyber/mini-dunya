"""Faz-53B — Güven skorlu görsel türü ve özne kutusu tespiti (konudan bağımsız, deterministik, 0 TL).

Önceliği agresif özne ayrıştırma değildir. Önceliği, hatalı bir özne kutusunun 2.5D motorunda görsel bozulmaya yol
açmasını engellemektir. Bunun için iki soru BAĞIMSIZ olarak yanıtlanır:

1. Görsel türü (yalnızca ölçülebilir kompozisyon sınıfları):
   portre | cok_figurlu | mimari | yogun_kompozisyon | belirsiz
   "minyatür" ile "harita" ayrımı semantiktir ve bu modül bunu YAPMAZ. Yoğun ve dengeli dağılmış kenar dokusu yalnızca
   `yogun_kompozisyon` olarak etiketlenir.
2. Özne kutusu: 0..1 aralığında [x0, y0, x1, y1]. Çok figürlü görselde bütün figürleri kapsar; tek ve dar bir kutuya
   sıkıştırılmaz.

Semantik sınır: Yüz algılama (YuNet) bir yüzün VAR olduğunu ölçer, ama kim olduğunu ya da sahnenin ana karakterinin
hangisi olduğunu bilemez. Kontur, kenar ve kompozisyon ölçüleri geometrik birer tahmindir. `tespit_durumu` alanı bu
sınırı açıkça yazar:
- `kesin_yuz`: kararlı, yüksek skorlu tek yüz.
- `geometrik_tahmin`: ölçülmüş ama semantik olarak doğrulanmamış kutu.
- `belirsiz_fallback`: güven yetersiz; tam kadraj ve kenburns.

Güven skoru sabit bir değer değildir. Ölçülmüş terimlerden hesaplanır: yüz skoru, iki ölçekte tutarlılık, kenar
enerjisinin kutuda yoğunlaşması, kutu alanı, tür ölçülerinin eşiklerden ne kadar uzak olduğu. Bütün terimler
`olcumler` alanına yazılır.

Hata koruması: `tespit()` hiçbir durumda istisna fırlatmaz. Okunamayan görselde, model yoksa ya da beklenmeyen bir
hatada tam kadraj fallback'i döner ve nedeni `uyarilar` alanına yazılır. Tespitteki bir başarısızlık toplama ya da
üretim sürecini durdurmaz.

Yüz modeli: OpenCV Zoo YuNet face_detection_yunet_2023mar.onnx (MIT lisanslı). Depoya girmez; ilk kullanımda
indirilir, SHA-256'sı doğrulanır ve ONBELLEK/modeller altında tutulur.
"""
from __future__ import annotations

import hashlib
import shutil
import urllib.request
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from motor import ayar

SURUM = "ozne-tespit-2"

MODEL = {
    "ad": "face_detection_yunet_2023mar.onnx",
    "url": "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/"
           "face_detection_yunet_2023mar.onnx",
    "sha256": "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    "lisans": "MIT (opencv/opencv_zoo)",
}

AYAR = {
    "analiz_px": 640,              # tür ve kenar ölçüleri bu uzun kenarda hesaplanır
    "yuz_olcekler": [640, 960],    # yüz iki ölçekte aranır; ikisinde de bulunan yüz "kararlı" sayılır
    "yuz_skor_esigi": 0.6,         # YuNet ham skoru
    "yuz_kesin_skor": 0.80,        # kesin_yuz için en düşük YuNet skoru (tarihî portreler: boya dokusu skoru düşürür)
    "yuz_kesin_iou": 0.80,         # ... ve iki ölçek arasında yüz kutusu örtüşmesi (IoU) en az bu
    "yuz_en_kucuk_alan": 0.004,    # portre sayılmak için yüz alanı / görsel alanı
    "yuz_iou_kararlilik": 0.4,
    "yogun_kenar": 0.11,           # kenar piksel oranı ≥ bu ...
    "yogun_cv": 0.55,              # ... ve 6×6 ızgarada kenar yoğunluğunun değişim katsayısı ≤ bu → yogun_kompozisyon
    "mimari_cizgi": 0.18,          # yatay/dikey uzun doğru üzerindeki kenar piksel oranı ≥ bu → mimari
    "tam_kadraj_alan": 0.85,       # kutu bu alanı aşarsa özne ayrışmıyor demektir → fallback
    "seviye_tam": 0.70,            # yalnızca kesin_yuz ile birlikte
    "seviye_sinirli": 0.55,
}

TAM_KADRAJ = [0.0, 0.0, 1.0, 1.0]
_DEDEKTOR: dict = {}


# ------------------------------------------------------------------ yüz modeli

def model_yolu(indir: bool = True) -> Path | None:
    """YuNet modelinin yerel yolu (SHA-256 doğrulanmış). Yoksa ve indirilemiyorsa None."""
    yol = ayar.ONBELLEK / "modeller" / MODEL["ad"]
    if yol.is_file() and _sha256(yol) == MODEL["sha256"]:
        return yol
    if not indir:
        return None
    yol.parent.mkdir(parents=True, exist_ok=True)
    gecici = yol.with_suffix(".indiriliyor")
    try:
        istek = urllib.request.Request(MODEL["url"], headers={"User-Agent": "mini-dunya/ozne_tespit (egitim amacli)"})
        with urllib.request.urlopen(istek, timeout=60) as y, open(gecici, "wb") as f:
            shutil.copyfileobj(y, f)
        if _sha256(gecici) != MODEL["sha256"]:
            gecici.unlink(missing_ok=True)
            return None
        gecici.replace(yol)
        return yol
    except Exception:   # ağ yok / erişim reddi: yüz algılama kullanılamaz, çağıran bunu raporlar
        gecici.unlink(missing_ok=True)
        return None


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def yunet_bulucu(img: np.ndarray, uzun_kenar: int, esik: float) -> list[dict]:
    """YuNet ile yüzler: [{'kutu': [x0,y0,x1,y1] (0..1), 'skor': float}]. Model yoksa RuntimeError."""
    yol = model_yolu()
    if yol is None:
        raise RuntimeError("yuz_modeli_yok")
    if "yunet" not in _DEDEKTOR:
        _DEDEKTOR["yunet"] = cv2.FaceDetectorYN.create(str(yol), "", (320, 320), esik, 0.3, 50)
    d = _DEDEKTOR["yunet"]
    d.setScoreThreshold(esik)
    h, w = img.shape[:2]
    k = min(1.0, uzun_kenar / max(h, w))
    g = cv2.resize(img, (max(1, round(w * k)), max(1, round(h * k))), interpolation=cv2.INTER_AREA) if k < 1 else img
    gh, gw = g.shape[:2]
    d.setInputSize((gw, gh))
    _, f = d.detect(g)
    if f is None:
        return []
    return [{"kutu": [max(0.0, float(r[0]) / gw), max(0.0, float(r[1]) / gh), min(1.0, float(r[0] + r[2]) / gw),
                      min(1.0, float(r[1] + r[3]) / gh)], "skor": float(r[14])} for r in f]


# ------------------------------------------------------------------ ölçüler

def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    i = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i
    return i / u if u > 0 else 0.0


def _alan(k) -> float:
    return max(0.0, k[2] - k[0]) * max(0.0, k[3] - k[1])


def _kenar_olculeri(gri: np.ndarray) -> dict:
    """Kenar yoğunluğu, ızgaraya dağılım, uzun yatay/dikey doğru oranı, enerji kutusu ve yoğunlaşma."""
    v = float(np.median(gri))
    kenar = cv2.Canny(gri, int(max(0, 0.66 * v)), int(min(255, 1.33 * v + 20)))
    h, w = kenar.shape
    yog = float((kenar > 0).mean())
    izgara = np.array([[(kenar[i * h // 6:(i + 1) * h // 6, j * w // 6:(j + 1) * w // 6] > 0).mean()
                        for j in range(6)] for i in range(6)])
    cv = float(izgara.std() / izgara.mean()) if izgara.mean() > 0 else 0.0
    cizgiler = cv2.HoughLinesP(kenar, 1, np.pi / 180, 60, minLineLength=int(0.12 * min(h, w)), maxLineGap=4)
    dogru = np.zeros_like(kenar)
    if cizgiler is not None:
        for x0, y0, x1, y1 in np.asarray(cizgiler).reshape(-1, 4):
            aci = abs(np.degrees(np.arctan2(y1 - y0, x1 - x0))) % 180
            if min(aci, abs(aci - 90), abs(180 - aci)) <= 5:
                cv2.line(dogru, (int(x0), int(y0)), (int(x1), int(y1)), 255, 2)
    cizgi_orani = float(((dogru > 0) & (kenar > 0)).sum() / max(1, (kenar > 0).sum()))
    g = gri.astype(np.float32)
    e = np.hypot(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))

    def aralik(profil):
        c = np.cumsum(profil) / max(1e-6, float(profil.sum()))
        return float(np.searchsorted(c, 0.04)) / len(profil), float(np.searchsorted(c, 0.96)) / len(profil)
    x0, x1 = aralik(e.sum(0))
    y0, y1 = aralik(e.sum(1))
    ek = [max(0.0, x0 - 0.04), max(0.0, y0 - 0.04), min(1.0, x1 + 0.04), min(1.0, y1 + 0.04)]   # özne kırpılmasın
    return {"kenar_yogunlugu": round(yog, 4), "kenar_dagilim_cv": round(cv, 3), "dogru_cizgi_orani": round(cizgi_orani, 3),
            "enerji_kutusu": [round(v_, 3) for v_ in ek], "_enerji": e}


def _yogunlasma(e: np.ndarray, kutu) -> float:
    """Kutudaki kenar enerjisi payı / kutunun alan payı (1 = tekdüze; yüksek = özne kutuda toplanmış)."""
    h, w = e.shape
    x0, y0, x1, y1 = int(kutu[0] * w), int(kutu[1] * h), max(int(kutu[0] * w) + 1, int(kutu[2] * w)), max(int(kutu[1] * h) + 1, int(kutu[3] * h))
    pay = float(e[y0:y1, x0:x1].sum() / max(1e-6, e.sum()))
    return pay / max(1e-6, _alan(kutu))


def _saf(o):
    """numpy sayı/dizi tiplerini JSON'a yazılabilir Python tiplerine çevirir (metadata'ya yazılacak)."""
    if isinstance(o, dict):
        return {k: _saf(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_saf(v) for v in o]
    if isinstance(o, np.ndarray):
        return _saf(o.tolist())
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    return o


def _sinirla(x: float) -> float:
    return float(min(1.0, max(0.0, x)))


# ------------------------------------------------------------------ tespit

def _fallback(neden: str, olcumler: dict | None = None, uyarilar: list | None = None, tur: str = "belirsiz",
              guven: float = 0.0) -> dict:
    return {"surum": SURUM, "gorsel_turu": tur, "tur_guveni": 0.0,
            "ozne_bilgisi": {"kutu": list(TAM_KADRAJ), "figur_sayisi": None, "ana_karakter": "belirlenemez"},
            "guven_skoru": round(_sinirla(guven), 3), "tespit_yontemi": "tam_kadraj_fallback",
            "tespit_durumu": "belirsiz_fallback", "fallback_uygulandi": True, "onerilen_seviye": "kenburns",
            "neden": neden, "olcumler": olcumler or {}, "uyarilar": list(uyarilar or [])}


def tespit(kaynak: str | Path | np.ndarray, ayarlar: dict | None = None,
           yuz_bulucu: Callable[[np.ndarray, int, float], list[dict]] | None = None) -> dict:
    """Görsel → tür + özne kutusu + gerçek ölçüme dayalı güven + önerilen 2.5D seviyesi. İstisna fırlatmaz.
    Dönüş yalnızca JSON'a yazılabilir Python tipleri içerir."""
    return _saf(_tespit(kaynak, ayarlar, yuz_bulucu))


def _tespit(kaynak, ayarlar, yuz_bulucu) -> dict:
    a = dict(AYAR, **(ayarlar or {}))
    uyarilar: list[str] = []
    try:
        img = cv2.imread(str(kaynak), cv2.IMREAD_COLOR) if not isinstance(kaynak, np.ndarray) else kaynak
        if img is None or img.size == 0:
            return _fallback("gorsel_okunamadi", uyarilar=["gorsel_okunamadi"])
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        img = img[:, :, :3]
        h, w = img.shape[:2]
        k = min(1.0, a["analiz_px"] / max(h, w))
        kucuk = cv2.resize(img, (max(1, round(w * k)), max(1, round(h * k))), interpolation=cv2.INTER_AREA) if k < 1 else img
        gri = cv2.cvtColor(kucuk, cv2.COLOR_BGR2GRAY)
        ko = _kenar_olculeri(gri)
        e = ko.pop("_enerji")
        olc = dict(ko, kaynak_px=[int(w), int(h)])

        # --- yüzler: iki ölçekte; ikisinde de (IoU ≥ eşik) bulunan yüz kararlıdır
        bul = yuz_bulucu or yunet_bulucu
        yuzler, yuz_hatasi = [], None
        try:
            olcekler = [bul(img, int(s), float(a["yuz_skor_esigi"])) for s in a["yuz_olcekler"]]
            ana, diger = olcekler[0], olcekler[1:]
            for y in ana:
                kar = [max([_iou(y["kutu"], z["kutu"]) for z in d] or [0.0]) for d in diger]
                kararli = all(i >= a["yuz_iou_kararlilik"] for i in kar)
                yuzler.append(dict(y, kararli=kararli, iou=round(min(kar) if kar else 1.0, 3)))
        except Exception as hata:   # model yoksa / dedektör hatası → yüz algılama kullanılamadı (açıkça yazılır)
            yuz_hatasi = str(hata) or type(hata).__name__
            uyarilar.append(f"yuz_algilama_kullanilamadi: {yuz_hatasi}")
        anlamli = [y for y in yuzler if _alan(y["kutu"]) >= a["yuz_en_kucuk_alan"] * 0.25]
        kararli = [y for y in anlamli if y["kararli"]]
        olc.update({"yuz_algilama": "kullanilamadi" if yuz_hatasi else "calisti", "yuz_sayisi": len(anlamli),
                    "kararli_yuz_sayisi": len(kararli),
                    "yuzler": [{"kutu": [round(v, 3) for v in y["kutu"]], "skor": round(y["skor"], 3),
                                "kararli": y["kararli"], "iou": y["iou"]} for y in anlamli]})

        # --- 1) TÜR (özne kutusundan bağımsız)
        yogun_payi = min(ko["kenar_yogunlugu"] / a["yogun_kenar"], a["yogun_cv"] / max(1e-6, ko["kenar_dagilim_cv"]))
        cizgi_payi = ko["dogru_cizgi_orani"] / a["mimari_cizgi"]
        buyuk = [y for y in kararli if _alan(y["kutu"]) >= a["yuz_en_kucuk_alan"]]
        if len(kararli) >= 2:
            tur, tur_g = "cok_figurlu", float(np.mean([y["skor"] for y in kararli]))
        elif len(buyuk) == 1:
            tur, tur_g = "portre", buyuk[0]["skor"]
        elif yogun_payi >= 1.0:
            tur, tur_g = "yogun_kompozisyon", _sinirla(yogun_payi - 1.0) * 0.5 + 0.5
        elif cizgi_payi >= 1.0:
            tur, tur_g = "mimari", _sinirla(cizgi_payi - 1.0) * 0.5 + 0.5
        else:
            tur, tur_g = "belirsiz", 0.0
        olc.update({"yogun_payi": round(float(yogun_payi), 3), "cizgi_payi": round(float(cizgi_payi), 3)})

        # --- 2) ÖZNE KUTUSU + GÜVEN (türden bağımsız ölçüler; tür yalnızca hangi kanıtın kullanılacağını seçer)
        sonuc = {"surum": SURUM, "gorsel_turu": tur, "tur_guveni": round(tur_g, 3), "olcumler": olc, "uyarilar": uyarilar}
        if tur == "yogun_kompozisyon":
            return dict(_fallback("yogun_kompozisyon_tek_ozne_yok", olc, uyarilar, tur, guven=0.0),
                        tur_guveni=round(tur_g, 3))
        if tur == "belirsiz":
            return dict(_fallback("tur_belirsiz", olc, uyarilar, tur), tur_guveni=0.0)

        if tur in ("portre", "cok_figurlu"):
            kaynak_yuz = buyuk if tur == "portre" else kararli
            ux0, uy0 = min(y["kutu"][0] for y in kaynak_yuz), min(y["kutu"][1] for y in kaynak_yuz)
            ux1, uy1 = max(y["kutu"][2] for y in kaynak_yuz), max(y["kutu"][3] for y in kaynak_yuz)
            fw = max(y["kutu"][2] - y["kutu"][0] for y in kaynak_yuz)
            fh = max(y["kutu"][3] - y["kutu"][1] for y in kaynak_yuz)
            # baş + omuz + gövde: yüzün 1,3 katı yana, 0,8 katı yukarı (başlık/sarık), görselin altına kadar
            kutu = [max(0.0, ux0 - 1.3 * fw), max(0.0, uy0 - 0.8 * fh), min(1.0, ux1 + 1.3 * fw), 1.0]
            skor = float(np.mean([y["skor"] for y in kaynak_yuz]))
            kararlilik = float(np.mean([y["iou"] for y in kaynak_yuz]))
            yz = _yogunlasma(e, kutu)
            guven = 0.5 * skor + 0.25 * _sinirla(kararlilik) + 0.25 * _sinirla(yz - 1.0)
            yontem = "yuz_algilama"
            if (tur == "portre" and skor >= a["yuz_kesin_skor"] and all(y["kararli"] for y in kaynak_yuz)
                    and min(y["iou"] for y in kaynak_yuz) >= a["yuz_kesin_iou"]):
                durum = "kesin_yuz"
            else:
                durum = "geometrik_tahmin"
            fig, ana = len(kaynak_yuz), ("tek_figur" if tur == "portre" else "belirlenemez")
        else:   # mimari: kenar enerjisi kutusu ve kompozisyon
            kutu = ko["enerji_kutusu"]
            yz = _yogunlasma(e, kutu)
            # Semantik doğrulama yok: geometrik kanıt en çok 0,8 ağırlıkla güvene girer (tek başına "tam" seviyesine çıkamaz)
            guven = 0.8 * (0.5 * _sinirla((yz - 1.0) / 0.6) + 0.3 * _sinirla((1.0 - _alan(kutu)) / 0.5) + 0.2 * tur_g)
            yontem, durum, fig, ana = "kontur_kompozisyon", "geometrik_tahmin", None, "belirlenemez"
        olc.update({"yogunlasma": round(float(yz), 3), "kutu_alani": round(_alan(kutu), 3)})
        guven = _sinirla(guven)

        if _alan(kutu) >= a["tam_kadraj_alan"] or guven < a["seviye_sinirli"]:
            neden = "ozne_ayrismiyor" if _alan(kutu) >= a["tam_kadraj_alan"] else "dusuk_guven"
            return dict(_fallback(neden, olc, uyarilar, tur, guven), tur_guveni=round(tur_g, 3),
                        olasi_kutu=[round(v, 3) for v in kutu], tespit_yontemi_denenen=yontem)
        if tur == "cok_figurlu":
            seviye = "kenburns"   # birden çok figür: tek özneli parallax figürleri keser; kutu yine hepsini kapsar
        elif durum == "kesin_yuz" and guven >= a["seviye_tam"]:
            seviye = "tam"
        else:
            seviye = "sinirli"
        sonuc.update({"ozne_bilgisi": {"kutu": [round(v, 3) for v in kutu], "figur_sayisi": fig, "ana_karakter": ana},
                      "guven_skoru": round(guven, 3), "tespit_yontemi": yontem, "tespit_durumu": durum,
                      "fallback_uygulandi": False, "onerilen_seviye": seviye,
                      "neden": "cok_figur_tek_ozne_parallax_yok" if tur == "cok_figurlu" else "olculdu"})
        return sonuc
    except Exception as hata:   # beklenmeyen her hata: güvenli tam kadraj (süreç durmaz)
        return _fallback("beklenmeyen_hata", uyarilar=uyarilar + [f"hata: {type(hata).__name__}: {hata}"])


ZORUNLU_ALANLAR = ("gorsel_turu", "guven_skoru", "tespit_yontemi", "tespit_durumu", "fallback_uygulandi", "onerilen_seviye")
