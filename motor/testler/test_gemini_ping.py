"""Faz-59 — araclar/gemini_ping.py (Gemini Health Check) offline testleri. Ağ yok; sahte taşıyıcı."""
from __future__ import annotations

import importlib.util
import json
import socket
import subprocess
import sys
import time
import urllib.error
from pathlib import Path

import pytest

KOK = Path(__file__).resolve().parents[2]
BETIK = KOK / "araclar" / "gemini_ping.py"
_spec = importlib.util.spec_from_file_location("gemini_ping", BETIK)
gp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gp)

ANAHTAR = "AIzaPING-gizli-0123456789abcdef"
ORTAM = {"GEMINI_DRYRUN_KEY": ANAHTAR}


def _ok(metin="OK"):
    return 200, json.dumps({"candidates": [{"content": {"parts": [{"text": metin}]}}]})


def _hata(kod, durum):
    return kod, json.dumps({"error": {"code": kod, "status": durum, "message": f"x {ANAHTAR} y"}})


class Kayit:
    """Model başına davranış; her isteği (model, url, başlıklar, zaman) kaydeder."""

    def __init__(self, davranis):
        self.davranis, self.istekler = davranis, []

    def __call__(self, url, govde, basliklar, zaman):
        model = url.split("/models/")[1].split(":")[0]
        self.istekler.append({"model": model, "url": url, "basliklar": dict(basliklar), "zaman": zaman,
                              "govde": json.loads(govde)})
        d = self.davranis[model]
        if isinstance(d, BaseException):
            raise d
        if callable(d):
            return d()
        return d


def _calistir(davranis, ortam=ORTAM, **kw):
    t = Kayit(davranis)
    return gp.calistir(ortam=ortam, tasiyici=t, **kw), t


P, Y = gp.VARSAYILAN_MODELLER


# ---------------------------------------------------------------- sınıflandırma

def test_iki_model_ok_sure_olculur():
    r, t = _calistir({P: _ok(), Y: _ok("OK.")})
    assert [(s["rol"], s["model"], s["durum"]) for s in r["sonuclar"]] == [("birincil", P, "OK"), ("yedek", Y, "OK")]
    assert all(isinstance(s["sure_sn"], float) and s["sure_sn"] >= 0 for s in r["sonuclar"])
    assert r["cikis"] == 0 and r["anahtar_kaynagi"] == "GEMINI_DRYRUN_KEY"
    assert t.istekler[0]["govde"]["contents"][0]["parts"][0]["text"] == "Respond with OK only."
    assert len(gp.ISTEM.split()) <= 10


@pytest.mark.parametrize("yanit,durum", [(_hata(503, "UNAVAILABLE"), "503_overload"),
                                         (_hata(429, "RESOURCE_EXHAUSTED"), "429_quota"),
                                         (_hata(401, "UNAUTHENTICATED"), "auth_or_other_error"),
                                         (_hata(403, "PERMISSION_DENIED"), "auth_or_other_error"),
                                         (_hata(404, "NOT_FOUND"), "auth_or_other_error"),
                                         (_hata(400, "INVALID_ARGUMENT"), "auth_or_other_error"),
                                         (_hata(500, "INTERNAL"), "auth_or_other_error")])
def test_http_siniflari(yanit, durum):
    r, t = _calistir({P: yanit, Y: _ok()})
    assert r["sonuclar"][0]["durum"] == durum and r["sonuclar"][0]["http"] == yanit[0]
    assert r["sonuclar"][1]["durum"] == "OK" and r["cikis"] == 1


@pytest.mark.parametrize("istisna", [TimeoutError("timed out"), socket.timeout("timed out"),
                                     urllib.error.URLError(socket.timeout("timed out")),
                                     urllib.error.URLError(TimeoutError("_ssl.c:989: handshake operation"))])
def test_zaman_asimi_siniflari(istisna):
    r, _ = _calistir({P: istisna, Y: _ok()})
    assert r["sonuclar"][0]["durum"] == "timeout"


def test_ag_hatasi_auth_or_other():
    r, _ = _calistir({P: ConnectionResetError("reset"), Y: _ok()})
    assert r["sonuclar"][0]["durum"] == "auth_or_other_error" and "ag_hatasi" in r["sonuclar"][0]["ayrinti"]


def test_kati_duvar_saati_zaman_asimi():
    """Taşıyıcı asılı kalsa bile (soket zaman aşımı devreye girmese de) sınırda kesilir."""
    def asili():
        time.sleep(5)
        return _ok()
    t0 = time.monotonic()
    sonuc = gp.ping(P, ANAHTAR, tasiyici=lambda *a: asili(), zaman=0.3)
    assert sonuc["durum"] == "timeout" and time.monotonic() - t0 < 2.0


# ---------------------------------------------------------------- sıfır tekrar, iki model de denenir

@pytest.mark.parametrize("birincil", [_hata(503, "UNAVAILABLE"), TimeoutError("timed out"), _hata(429, "R"),
                                      _hata(500, "INTERNAL"), ConnectionResetError("x")])
def test_retry_yok_ve_yedek_mutlaka_denenir(birincil):
    r, t = _calistir({P: birincil, Y: _hata(503, "UNAVAILABLE")})
    assert [i["model"] for i in t.istekler] == [P, Y]                # model başına tam 1 istek, yedek her zaman
    assert len(r["sonuclar"]) == 2 and r["sonuclar"][1]["durum"] == "503_overload"


def test_zaman_asimi_degeri_25_ve_aralik_disi_reddedilir():
    r, t = _calistir({P: _ok(), Y: _ok()})
    assert {i["zaman"] for i in t.istekler} == {25.0} and gp.ZAMAN_ASIMI == 25.0
    for z in (19.9, 30.1, 90):
        with pytest.raises(ValueError):
            gp.calistir(ortam=ORTAM, tasiyici=Kayit({}), zaman=z)


# ---------------------------------------------------------------- anahtar

def test_eksik_anahtar_hic_istek_gondermez():
    r, t = _calistir({}, ortam={})
    assert t.istekler == [] and r["cikis"] == 2 and r["anahtar_kaynagi"] is None
    assert all(s["durum"] == "auth_or_other_error" and "anahtar_yok" in s["ayrinti"] for s in r["sonuclar"])


def test_anahtar_onceligi_dryrun_sonra_api_key():
    assert gp.anahtar_sec({"GEMINI_DRYRUN_KEY": "a", "GEMINI_API_KEY": "b"}) == ("a", "GEMINI_DRYRUN_KEY")
    assert gp.anahtar_sec({"GEMINI_DRYRUN_KEY": "  ", "GEMINI_API_KEY": "b"}) == ("b", "GEMINI_API_KEY")


def test_anahtar_url_de_degil_baslikta():
    _, t = _calistir({P: _ok(), Y: _ok()})
    for i in t.istekler:
        assert ANAHTAR not in i["url"] and i["basliklar"]["x-goog-api-key"] == ANAHTAR


def test_anahtar_hicbir_ciktiya_sizmaz(tmp_path, capsys, monkeypatch):
    davranis = {P: _hata(503, "UNAVAILABLE"), Y: ConnectionResetError(f"baglanti {ANAHTAR} koptu")}
    r, _ = _calistir(davranis)
    assert ANAHTAR not in json.dumps(r, ensure_ascii=False) and ANAHTAR not in gp.markdown(r)
    assert "***" in r["sonuclar"][1]["ayrinti"]
    # main(): stdout + GITHUB_STEP_SUMMARY
    ozet = tmp_path / "ozet.md"
    monkeypatch.setenv("GEMINI_DRYRUN_KEY", ANAHTAR)
    monkeypatch.delenv("GEMINI_MODELLER", raising=False)
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(ozet))
    monkeypatch.setattr(gp, "urllib_tasiyici", Kayit(davranis))
    kod = gp.main(["--json"])
    cikti = capsys.readouterr()
    assert kod == 1 and ANAHTAR not in cikti.out + cikti.err and ANAHTAR not in ozet.read_text()
    assert "| birincil |" in ozet.read_text() and "503_overload" in ozet.read_text()


# ---------------------------------------------------------------- tablo, modeller, bağımsızlık

def test_markdown_tablosu():
    r, _ = _calistir({P: _ok(), Y: TimeoutError("timed out")})
    md = gp.markdown(r)
    assert "| Rol | Model | Durum | Süre | Hata sınıfı / ayrıntı |" in md
    assert f"`{P}`" in md and f"`{Y}`" in md and "✅ OK" in md and "⚠️ timeout" in md
    assert md.count("\n|") == 4                                      # başlık + ayraç + 2 model


def test_varsayilan_modeller_uretim_sirasiyla_ayni():
    from motor.orkestrasyon import gemini as uretim   # yalnız sabit karşılaştırması (betik bunu import ETMEZ)
    assert gp.VARSAYILAN_MODELLER == tuple(uretim.MODELLER[:2])
    assert gp.modeller({}) == (P, Y)
    assert gp.modeller({"GEMINI_MODELLER": "a-flash, b-flash, c"}) == ("a-flash", "b-flash")
    assert gp.modeller({"GEMINI_MODELLER": Y})[0] == Y and gp.modeller({"GEMINI_MODELLER": Y})[1] != Y


def test_betik_uretim_modulu_import_etmez_ve_dosya_yazmaz(tmp_path):
    kaynak = BETIK.read_text()
    assert "import motor" not in kaynak and "from motor" not in kaynak and "kaos" not in kaynak
    # anahtarsız gerçek süreç: ağsız çıkış 2, çalışma dizininde dosya oluşmaz, motor modülü yüklenmez
    betik = (f"import sys; sys.path.insert(0, {str(BETIK.parent)!r}); import gemini_ping as g; "
             "r = g.main([]); import json; "
             "print('MOTOR_YUKLU=' + str(any(m.startswith('motor') for m in sys.modules))); sys.exit(r)")
    p = subprocess.run([sys.executable, "-I", "-c", betik], cwd=tmp_path, capture_output=True, text=True, timeout=60,
                       env={"PATH": "/usr/bin:/bin"})
    assert p.returncode == 2 and "MOTOR_YUKLU=False" in p.stdout and "anahtar_yok" in p.stdout
    assert list(tmp_path.iterdir()) == []


def test_gecersiz_zaman_asimi_cikis_3_ve_istek_yok(monkeypatch, capsys):
    kayit = Kayit({})
    monkeypatch.setenv("GEMINI_DRYRUN_KEY", ANAHTAR)
    monkeypatch.setattr(gp, "urllib_tasiyici", kayit)
    assert gp.main(["--zaman-asimi", "90"]) == 3 and kayit.istekler == []
    assert ANAHTAR not in capsys.readouterr().err


def test_is_akisi_yalniz_elle_tetiklenir_ve_secretlari_alir():
    yaml = pytest.importorskip("yaml")
    wf = yaml.safe_load((KOK / ".github" / "workflows" / "gemini_health_check.yml").read_text())
    tetik = wf.get("on", wf.get(True))
    assert list(tetik) == ["workflow_dispatch"]                      # schedule / push YOK
    adim = next(a for a in wf["jobs"]["ping"]["steps"] if "gemini_ping.py" in a.get("run", ""))
    assert adim["env"]["GEMINI_DRYRUN_KEY"] == "${{ secrets.GEMINI_DRYRUN_KEY }}"
    assert adim["env"]["GEMINI_API_KEY"] == "${{ secrets.GEMINI_API_KEY }}"
    assert wf["permissions"] == {"contents": "read"}
