"""Montaj ve animasyon kararlılığı testi: bütün takımları Blender'da animasyon boyunca ölçer, eşiklerle karar verir.

python3 -m motor.karakter.montaj            -> motor/karakter/montaj_testi.json
python3 -m motor.karakter.montaj --hizli    -> her animasyonda 3 kare

Giysi katman testi her derlenmiş gövde için bir kez yapılır (aynı gövdeyi paylaşan takımlar aynı giysiyi taşır).
"""
from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from motor import ayar

BURASI = Path(__file__).resolve().parent
BETIK = BURASI.parent / "varlik" / "blender" / "takim_test.py"
SONUC = BURASI / "montaj_testi.json"
TAKIM = ayar.ONBELLEK / "takim"
IS_KLASORU = ayar.ONBELLEK / "montaj"
ANIMASYONLAR = ["Idle_Loop", "Walk_Loop", "Jog_Fwd_Loop", "Sword_Attack"]
ANIMASYON_SUVARI = ["Driving_Loop"]
TEMEL_ANIMASYON = {"Idle_Loop", "Walk_Loop"}  # bunlarda kusur = karakter kullanılamaz (RED)

# Eşikler (geçemeyen takım üretime alınmaz)
ESIK = {
    "kayma_mm": 2.0,          # sert bağlantı: kemiğe göre en çok 2 mm oynayabilir
    "kayma_derece": 0.5,
    "tutus_cm": 25.0,         # ekipman kökü bağlı olduğu kemikten en çok 25 cm (el silahı elde)
    "bas_tasma_orani": 0.02,  # başın en çok %2'si başlığın dışına taşabilir
    "bas_bosluk_cm": 6.0,     # başlık başa otursun (havada durmasın)
    "kalkan_gomulme_kare_orani": 0.25,  # kalkanın kola gömüldüğü kare oranı
    "giysi_tasma_orani": 0.03,  # alt katmanın dış giysiden taşma oranı
}


def isler_hazirla(takimlar: list[dict], hizli: bool) -> list[Path]:
    IS_KLASORU.mkdir(parents=True, exist_ok=True)
    gorulen_govde = set()
    paketler = [[], []]
    for i, t in enumerate(takimlar):
        k = {"ad": t["ad"], "govde_glb": t["glb"], "takilanlar": t["takilanlar"]}
        k["_giysi"] = t["govde_id"] not in gorulen_govde
        gorulen_govde.add(t["govde_id"])
        paketler[i % 2].append((k, t.get("binek")))
    yollar = []
    for j, paket in enumerate(paketler):
        for giysi in (True, False):
            kl = [k for k, b in paket if k["_giysi"] == giysi]
            if not kl:
                continue
            anim = ANIMASYONLAR + (ANIMASYON_SUVARI if any(b for k, b in paket if k in kl) else [])
            yol = IS_KLASORU / f"is_{j}_{int(giysi)}.json"
            yol.write_text(json.dumps({"karakterler": kl, "animasyonlar": anim, "kare": 3 if hizli else 5,
                                       "giysi_testi": giysi, "cikti": str(yol.with_suffix(".sonuc.json"))}, ensure_ascii=False))
            yollar.append(yol)
    return yollar


def calistir(yol: Path) -> list[dict]:
    p = subprocess.run([sys.executable, str(BETIK), str(yol)], capture_output=True, text=True, timeout=7200)
    if p.returncode != 0:
        print(p.stdout[-2000:], p.stderr[-3000:])
        raise SystemExit(f"MONTAJ TESTİ ÇALIŞMADI: {yol.name}")
    return json.loads(yol.with_suffix(".sonuc.json").read_text())


def karar(r: dict) -> list[str]:
    h = []
    for eid, e in r["ekipman"].items():
        if e["kayma_mm"] > ESIK["kayma_mm"] or e["kayma_derece"] > ESIK["kayma_derece"]:
            h.append(f"{eid}: animasyonda kayıyor ({e['kayma_mm']} mm, {e['kayma_derece']}°)")
        if e["tutus_cm"] > ESIK["tutus_cm"]:
            h.append(f"{eid}: bağlı kemikten kopuk ({e['tutus_cm']} cm)")
        if e["kategori"] == "baslik":
            if e["bas_tasma_orani"] is not None and e["bas_tasma_orani"] > ESIK["bas_tasma_orani"]:
                h.append(f"{eid}: baş başlığın dışına taşıyor (%{e['bas_tasma_orani'] * 100:.1f})")
            if e["bas_bosluk_cm"] is not None and e["bas_bosluk_cm"] > ESIK["bas_bosluk_cm"]:
                h.append(f"{eid}: başlık havada ({e['bas_bosluk_cm']} cm)")
        if e["kategori"] == "kalkan" and e["gomulme_kare_orani"] > ESIK["kalkan_gomulme_kare_orani"]:
            h.append(f"{eid}: kalkan karelerin %{e['gomulme_kare_orani'] * 100:.0f}'inde gövdeye gömülüyor")
    for g, x in r.get("giysi", {}).items():
        for anim, oran in (x.get("animasyon") or {}).items():
            if anim in TEMEL_ANIMASYON and oran > ESIK["giysi_tasma_orani"]:
                h.append(f"{g}: {anim} sırasında alt katman dışarı taşıyor (%{oran * 100:.1f})")
    return h


def yasak_animasyonlar(r: dict) -> dict[str, list[str]]:
    """Temel olmayan bir animasyonda giysi taşıyorsa o animasyon bu gövdede kullanılmaz (motor seçmez)."""
    y = {}
    for g, x in r.get("giysi", {}).items():
        for anim, oran in (x.get("animasyon") or {}).items():
            if anim not in TEMEL_ANIMASYON and oran > ESIK["giysi_tasma_orani"]:
                y.setdefault(anim, []).append(f"{g} %{oran * 100:.1f}")
    return y


def uyarilar(r: dict) -> list[str]:
    """Hata sayılmayan ama raporlanan durumlar: animasyon kütüphanesi silaha özel değil."""
    u = []
    for eid, e in r["ekipman"].items():
        if e["kategori"] == "silah" and e["gomulme_kare_orani"] > 0.25:
            u.append(f"{eid}: bazı karelerde gövdeden geçiyor (%{e['gomulme_kare_orani'] * 100:.0f} kare); silaha özel animasyon gerekir")
    return u


def test_et(adlar: list[str] | None = None, hizli: bool = False, ek: list[dict] | None = None) -> dict:
    takimlar = [json.loads(p.read_text()) for p in sorted(TAKIM.glob("*.json"))]
    if adlar:
        takimlar = [t for t in takimlar if t["ad"] in adlar]
    takimlar += ek or []
    yollar = isler_hazirla(takimlar, hizli)
    with ThreadPoolExecutor(2) as ex:
        sonuclar = [r for liste in ex.map(calistir, yollar) for r in liste]
    # Giysi katman testi gövde başına bir kez yapılır; sonucu aynı gövdeyi paylaşan BÜTÜN takımlara uygulanır
    gid = {t["ad"]: t["govde_id"] for t in takimlar}
    govde_giysi = {gid[r["ad"]]: r["giysi"] for r in sonuclar if r.get("katman") is not None}
    cikti = {}
    for r in sonuclar:
        r["giysi"] = govde_giysi.get(gid[r["ad"]], r["giysi"])
        h = karar(r)
        cikti[r["ad"]] = {"gecti": not h, "hatalar": h, "uyarilar": uyarilar(r), "yasak_animasyon": yasak_animasyonlar(r), "olcum": r}
    return cikti


if __name__ == "__main__":
    c = test_et(hizli="--hizli" in sys.argv)
    SONUC.write_text(json.dumps({"esikler": ESIK, "takimlar": c}, ensure_ascii=False, indent=1))
    gecen = sum(1 for x in c.values() if x["gecti"])
    print(f"MONTAJ: {gecen}/{len(c)} geçti")
    for a, x in c.items():
        for h in x["hatalar"]:
            print("  KALDI", a, h)
