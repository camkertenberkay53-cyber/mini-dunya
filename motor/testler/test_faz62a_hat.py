"""Faz-62a — araclar/faz62a_hat.py ve faz62a_varlik_render.yml offline testleri (Blender/Godot/ağ yok)."""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

KOK = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("faz62a_hat", KOK / "araclar" / "faz62a_hat.py")
h = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(h)
WF = KOK / ".github" / "workflows" / "faz62a_varlik_render.yml"


# ---------------------------------------------------------------- iş akışı

def _wf():
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(WF.read_text())


def test_is_akisi_tetikleyicileri_elle_ve_yalniz_kendi_dali():
    wf = _wf()
    tetik = wf.get("on", wf.get(True))
    assert set(tetik) == {"workflow_dispatch", "push"}
    assert tetik["push"]["branches"] == ["faz62a-ci-varlik-render"]          # main'de push ile ÇALIŞMAZ
    assert "schedule" not in tetik and "pull_request" not in tetik
    assert wf["permissions"] == {"contents": "read"}


def test_is_akisi_secret_ve_yukleme_kullanmaz():
    metin = "\n".join(x for x in WF.read_text().splitlines() if not x.lstrip().startswith("#"))   # yorumlar hariç
    assert "secrets." not in metin                                           # Gemini / YouTube anahtarı yok
    for yasak in ("YT_", "youtube", "upload_video", "GEMINI_API_KEY", "git push"):
        assert yasak.lower() not in metin.lower(), yasak
    adimlar = _wf()["jobs"]["hat"]["steps"]
    yuklemeler = [a for a in adimlar if str(a.get("uses", "")).startswith("actions/upload-artifact")]
    assert len(yuklemeler) == 1 and "/tmp/faz62a_cikti/video/*.mp4" in yuklemeler[0]["with"]["path"]


def test_is_akisi_kurulum_ve_sure():
    wf = _wf()
    assert wf["jobs"]["hat"]["timeout-minutes"] >= 25
    metin = WF.read_text()
    assert "bpy==5.3.0" in metin and "sha512sum -c -" in metin and "Godot_v4.7.2-stable" in metin
    assert "vits-piper-tr_TR-fahrettin-medium" in metin and "sherpa-onnx-whisper-base" in metin
    mpfb = _wf()["env"]["MPFB_COMMIT"]
    assert len(mpfb) == 40 and "github.com/makehumancommunity/mpfb2" in metin   # MPFB sabit commit, GitHub'dan
    komutlar = " ".join(a.get("run", "") for a in wf["jobs"]["hat"]["steps"])
    for alt in ("anahtar", "kaynaklar", "varlik", "render"):
        assert f"araclar/faz62a_hat.py {alt}" in komutlar, alt
    anahtarlar = [a["with"]["key"] for a in wf["jobs"]["hat"]["steps"] if "cache" in str(a.get("uses", ""))]
    assert sum("faz62a-varlik-${{ steps.anahtar.outputs.anahtar }}" == k for k in anahtarlar) == 2   # restore + save


# ---------------------------------------------------------------- varlık anahtarı

def _sahte_kok(tmp_path: Path) -> Path:
    k = tmp_path / "kok"
    for g in h.ANAHTAR_GIRDILERI:
        p = k / g
        if Path(g).suffix:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"icerik {g}")
        else:
            p.mkdir(parents=True, exist_ok=True)
            (p / "betik.py").write_text(f"# {g}")
    return k


def test_varlik_anahtari_belirlenimci_ve_girdiye_duyarli(tmp_path):
    k = _sahte_kok(tmp_path)
    a1, a2 = h.varlik_anahtari(k), h.varlik_anahtari(k)
    assert a1 == a2 and len(a1) == 20
    (k / "motor/varlik/blender/betik.py").write_text("# değişti")
    assert h.varlik_anahtari(k) != a1                                    # derleme betiği değişince yeniden derlenir
    b = h.varlik_anahtari(k)
    (k / "ilgisiz.txt").write_text("x")
    (k / "motor/varlik/blender/__pycache__").mkdir()
    (k / "motor/varlik/blender/__pycache__/x.pyc").write_bytes(b"\0")
    assert h.varlik_anahtari(k) == b                                     # ilgisiz dosya / pyc anahtarı değiştirmez


def test_varlik_anahtari_mpfb_surumune_duyarli(tmp_path, monkeypatch):
    k = _sahte_kok(tmp_path)
    monkeypatch.setenv("MPFB_COMMIT", "a" * 40)
    a = h.varlik_anahtari(k)
    monkeypatch.setenv("MPFB_COMMIT", "b" * 40)
    assert h.varlik_anahtari(k) != a


def test_anahtar_girdileri_depoda_var():
    for g in h.ANAHTAR_GIRDILERI:
        assert (KOK / g).exists(), g


# ---------------------------------------------------------------- kaynak depoları (yerel git deposuyla)

def _git(*a, cwd):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def yerel_kaynak(tmp_path, monkeypatch):
    if not shutil.which("git"):
        pytest.skip("git yok")
    depo = tmp_path / "uzak"
    depo.mkdir()
    _git("init", "-q", cwd=depo)
    _git("config", "uploadpack.allowAnySHA1InWant", "true", cwd=depo)
    (depo / "LICENSE").write_text("CC0")
    (depo / "models").mkdir()
    (depo / "models" / "a.usda").write_text("x")
    _git("add", ".", cwd=depo)
    _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "ilk", cwd=depo)
    commit = _git("rev-parse", "HEAD", cwd=depo)
    kok = tmp_path / "kok"
    (kok / "motor/varlik").mkdir(parents=True)

    def yaml_yaz(c=commit, lisans="LICENSE"):
        (kok / "motor/varlik/kaynaklar.yaml").write_text(
            f"deneme:\n  klasor: deneme\n  url: file://{depo}\n  commit: {c}\n  lisans: CC0-1.0\n"
            f"  lisans_dosyasi: {lisans}\n  kok: models\n")
    yaml_yaz()
    monkeypatch.setattr(h, "KOK", kok)
    return {"commit": commit, "yaml_yaz": yaml_yaz, "hedef": tmp_path / "varlik"}


def test_kaynak_sabit_committen_klonlanir_ve_ikinci_kez_indirilmez(yerel_kaynak):
    r = h.kaynaklari_getir(yerel_kaynak["hedef"])
    assert r["deneme"]["durum"] == "indirildi" and r["deneme"]["commit"] == yerel_kaynak["commit"]
    assert (yerel_kaynak["hedef"] / "deneme/models/a.usda").exists()
    assert h.kaynaklari_getir(yerel_kaynak["hedef"])["deneme"]["durum"] == "hazir"


def test_kaynak_yanlis_commit_ya_da_lisanssiz_ise_durur(yerel_kaynak):
    yerel_kaynak["yaml_yaz"](lisans="YOK.txt")
    with pytest.raises(SystemExit, match="lisans"):
        h.kaynaklari_getir(yerel_kaynak["hedef"])
    yerel_kaynak["yaml_yaz"](c="0" * 40)   # YAML'da tamsayıya dönen SHA da çökmeden reddedilir
    with pytest.raises(subprocess.CalledProcessError):
        h.kaynaklari_getir(yerel_kaynak["hedef"])


def test_gercek_kaynaklar_commit_sabitli_ve_cc0():
    yaml = pytest.importorskip("yaml")
    k = yaml.safe_load((KOK / "motor/varlik/kaynaklar.yaml").read_text())
    for ad, v in k.items():
        assert len(v["commit"]) == 40 and v["lisans"] == "CC0-1.0" and v["url"].startswith("https://github.com/"), ad


# ---------------------------------------------------------------- render doğrulaması

def test_ffprobe_olcumu(tmp_path):
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("ffmpeg yok")
    v = tmp_path / "t.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=320x180:d=1.5:r=30", "-f", "lavfi",
                    "-i", "sine=f=440:d=1.5", "-shortest", "-c:v", "libx264", "-c:a", "aac", str(v)], check=True)
    o = h.ffprobe(v)
    assert o["cozunurluk"] == [320, 180] and o["ses"] is True and 1.4 <= o["sure_sn"] <= 1.6 and o["fps"] == "30/1"


def test_plan_kapidan_gecmezse_render_yapilmaz(tmp_path, monkeypatch):
    from motor.uretim import kurgu, uretim_hatti
    monkeypatch.setattr(uretim_hatti, "planla", lambda k: {"gecti": False, "hatalar": {"senaryo": ["x"]}})
    monkeypatch.setattr(kurgu, "uret", lambda k: pytest.fail("plan geçmeden render çağrıldı"))
    r = h.pilot_render("otlukbeli-1473", tmp_path)
    assert r["gecti"] is False and r["plan"]["hatalar"] == {"senaryo": ["x"]} and "kurgu" not in r
    assert (tmp_path / "is/otlukbeli-1473/senaryo.json").exists()     # çalışma kopyası; pilot klasörü değişmez


def test_kalite_kontrolden_kalan_video_basarisiz_sayilir(tmp_path, monkeypatch):
    from motor import ayar
    from motor.uretim import kurgu, uretim_hatti
    monkeypatch.setattr(ayar, "ONBELLEK", tmp_path / "onb")
    mp4 = tmp_path / "onb/kurgu/otlukbeli-1473/otlukbeli-1473.mp4"
    mp4.parent.mkdir(parents=True)
    mp4.write_bytes(b"x")
    monkeypatch.setattr(uretim_hatti, "planla", lambda k: {"gecti": True, "hatalar": {}, "toplam_sure_sn": 32.0})
    monkeypatch.setattr(h, "ffprobe", lambda p: {"sure_sn": 32.0, "boyut_mb": 1.0, "cozunurluk": [1080, 1920],
                                                 "fps": "30/1", "ses": True})
    for durum, beklenen in (("KALİTE KONTROLDEN KALDI", False), ("TAMAM", True)):
        monkeypatch.setattr(kurgu, "uret", lambda k, d=durum: {"durum": d, "dinleme": {"S1": {"benzerlik": 0.9}}})
        r = h.pilot_render("otlukbeli-1473", tmp_path / durum[:3])
        assert r["gecti"] is beklenen and r["mp4"]["sure_sn"] == 32.0 and r["kurgu"]["dinleme"]["cumle"] == 1


def test_betik_depoya_yazmaz_yalniz_cikti_klasorune():
    """Betikteki her dosya yazımı _yaz (çıktı klasörü) ya da çalışma kopyasıdır; pilot/korunan dosyalar yazılmaz."""
    kaynak = (KOK / "araclar" / "faz62a_hat.py").read_text()
    assert kaynak.count(".write_text(") == 1 and "def _yaz" in kaynak
    for yasak in ("import kaos", "from kaos", "bot.yml", "otonom_uret", "upload", "YT_"):
        assert yasak not in kaynak
