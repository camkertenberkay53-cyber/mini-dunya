"""Faz-62b — otonom_uret.py (depo kökü) ve belgesel_uret.yml offline testleri (ağ, Gemini, Godot yok)."""
from __future__ import annotations

import json
from pathlib import Path

import importlib.util

import pytest

KOK = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("otonom_uret", KOK / "otonom_uret.py")
ou = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ou)
WF = KOK / ".github" / "workflows" / "belgesel_uret.yml"
EYLEM = KOK / ".github" / "actions" / "motor-ortami" / "action.yml"
PILOT = KOK / "motor/uretim/pilotlar/otlukbeli-1473"


def _kayit(i, durum="dogrulanmis", kaynak=("wp_tr_1", "tdv_1"), **ek):
    return {"id": f"ark_{i:03d}", "iddia": f"İddia numarası {i} ayrıntılı metin.", "durum": durum,
            "bagimsiz_kaynak_sayisi": len(kaynak),
            "kaynaklar": [{"id": k, "url": f"https://ornek.org/{k}", "eser": f"Eser {k}",
                           "tur": "ansiklopedi" if k.startswith(("wp", "tdv")) else "akademik"} for k in kaynak], **ek}


# ================================================================== şablon, kartlar

def test_sablon_konunun_ilk_sozcuguyle_bulunur_bilinmeyen_konu_reddedilir(tmp_path):
    assert ou.sablon_bul("Otlukbeli Savaşı").name == "otlukbeli-1473"
    with pytest.raises(ou.UretimHatasi) as e:
        ou.sablon_bul("Hayali Bir Muharebe")
    assert e.value.kod == 2 and "şablonu yok" in str(e.value)


def test_konu_kur_kimlik_bicim_ve_hedef_sure():
    k = ou.konu_kur(PILOT, "Otlukbeli Savaşı", "shorts")
    pilot = json.loads((PILOT / "konu.json").read_text())
    assert k["kimlik"] == pilot["kimlik"] + "-oto" and k["format"] == "shorts" and k["hedef_sure_sn"] == [45, 60]
    assert k["harita"] == pilot["harita"] and k["donemler"] == pilot["donemler"]   # şablonun harita ve kitleri korunur


def test_kartlar_guven_eslemesi_ve_kaynak_tablosu():
    h = {"kayitlar": [_kayit(1), _kayit(2, kaynak=("oa_9",)), _kayit(3, "tartismali", tek_kaynak_uyarisi=True),
                      _kayit(4, "belirsiz"), _kayit(5, kaynak=())]}
    ara, es = ou.kartlar_kur(h, "k")
    g = {c["iddia"].split()[2]: c["guven"] for c in ara["kartlar"]}
    assert g == {"1": "kesin", "2": "makul", "3": "tartismali"}          # tek kaynaklı doğrulanmış → makul; belirsiz yok
    assert [c["id"] for c in ara["kartlar"]] == ["C1", "C2", "C3"]
    assert {k["id"] for k in ara["kaynaklar"]} == {"K1", "K2", "K3"} and len(ara["kaynaklar"]) == 3   # tekrar yok
    assert next(k for k in ara["kaynaklar"] if k["baslik"] == "Eser oa_9")["tur"] == "ikincil"
    assert es["C3"]["havuz_id"] == "ark_003" and next(c for c in ara["kartlar"] if c["id"] == "C3")["not"] == "tek kaynak"
    with pytest.raises(ou.UretimHatasi):
        ou.kartlar_kur({"kayitlar": [_kayit(1, "belirsiz")]}, "k")


def test_kartlar_arastirma_semasina_uyar():
    js = pytest.importorskip("jsonschema")
    sema = json.loads((KOK / "motor/uretim/semalar/arastirma.schema.json").read_text())
    ara, _ = ou.kartlar_kur({"kayitlar": [_kayit(i) for i in range(1, 6)]}, "k")
    js.validate(ara, sema)


# ================================================================== JSON, görsel kuralları

def test_json_ayikla():
    assert ou.json_ayikla('```json\n{"a": 1}\n```') == {"a": 1}
    assert ou.json_ayikla('İşte yanıt: [{"b": 2}] tamam') == [{"b": 2}]
    with pytest.raises(json.JSONDecodeError):
        ou.json_ayikla("json yok")


def test_gorsel_kurallari_evre_ve_gorsel_listesi():
    k = ou.konu_kur(PILOT, "Otlukbeli Savaşı", "shorts")
    m = ou.gorsel_kurallari(k, [{"gorsel_id": "g1", "aciklama": "portre"}])
    assert "E1 = " in m and "g1 = portre" in m and "≈%40" in m and "45–60 sn" in m
    bos = ou.gorsel_kurallari(dict(k, harita={}), [])
    assert "'harita' niyeti KULLANMA" in bos and "'gorsel25d' niyeti KULLANMA" in bos


# ================================================================== Commons görselleri (yalnız CC0/PD)

def test_gorseller_yalniz_cc0_pd_ve_kapidan_gecenler(tmp_path, monkeypatch):
    from motor.varlik import tarihi_gorsel
    monkeypatch.setattr(tarihi_gorsel, "dogrulanmis_dosya", lambda gid: (tmp_path / gid, {}))

    def topla(s, hedef):
        gid = s["gorsel_id"]
        (hedef / f"{gid}.jpg").write_bytes(b"x")
        (hedef / f"{gid}.json").write_text("{}")
        if "hata" in gid:
            raise RuntimeError("uygun aday yok")
        lis = {"a": "CC0-1.0", "b": "PD-Art", "c": "CC-BY-SA-4.0", "d": "PD-Old"}[gid[-1]]
        return {"lisans_turu": lis, "eser_adi": gid, "cozunurluk": [2000, 1500], "kaynak_url": "u"}
    sorgular = [{"gorsel_id": x, "sorgu": "q"} for x in ("a", "b", "c", "hata", "d")]
    r = ou.gorselleri_topla("k", sorgular, hedef=tmp_path, topla=topla)
    assert [g["gorsel_id"] for g in r] == ["k-a", "k-b", "k-d"]
    assert not (tmp_path / "k-c.jpg").exists() and not (tmp_path / "k-c.json").exists()   # CC-BY silinir
    assert {g["lisans"] for g in r} <= set(ou.IZINLI) == {"CC0-1.0", "PD-Old", "PD-Art"}


def test_gorsel_lisans_kapisindan_gecmeyen_kullanilmaz(tmp_path, monkeypatch):
    from motor.varlik import tarihi_gorsel

    def red(gid):
        raise tarihi_gorsel.LisansHatasi("sha uyuşmuyor")
    monkeypatch.setattr(tarihi_gorsel, "dogrulanmis_dosya", red)
    r = ou.gorselleri_topla("k", [{"gorsel_id": "a"}], hedef=tmp_path,
                            topla=lambda s, h: {"lisans_turu": "CC0-1.0"})
    assert r == []


# ================================================================== senaryo denetimi ve yeniden deneme

def _cumle(i, tur="3d", **n):
    return {"id": f"S{i}", "metin": f"cümle {i}", "kartlar": ["C1"], "niyet": {"tur": tur, **n}}


@pytest.fixture
def denetim_yalitik(monkeypatch):
    """Korunan kapılar (sozlesme / anlati) varlık önbelleği ister; burada geçer kabul edilir, ek kurallar sınanır."""
    from motor.uretim import anlati, sahne_bolucu, sozlesme
    monkeypatch.setattr(sozlesme, "senaryo_denetle", lambda s, a: [])
    monkeypatch.setattr(anlati, "shorts_denetle", lambda s, sr: ([], {}))
    sure = {"t": 50.0}
    monkeypatch.setattr(sahne_bolucu, "zaman_cizelgesi", lambda s, sr: None)
    monkeypatch.setattr(sahne_bolucu, "toplam_sure", lambda c: sure["t"])
    return sure


def test_ek_niyet_kurallari(denetim_yalitik):
    k = ou.konu_kur(PILOT, "Otlukbeli Savaşı", "shorts")
    g = [{"gorsel_id": "g1", "aciklama": "x"}]
    olc = lambda cs: {}
    iyi = {"cumleler": [_cumle(1, "gorsel25d", gorsel25d={"gorsel_id": "g1"}), _cumle(2, "harita", evre="E1"), _cumle(3)]}
    assert ou.senaryo_denetle(iyi, {}, k, g, olc) == []
    kotu = {"cumleler": [_cumle(1, "gorsel25d", gorsel25d={"gorsel_id": "uydurma"}), _cumle(2, "harita", evre="E9"),
                         _cumle(3, "bilgi_karti")]}
    h = ou.senaryo_denetle(kotu, {}, k, g, olc)
    assert len(h) == 3 and "listede yok" in h[0] and "evresi geçersiz" in h[1] and "bilgi_karti" in h[2]


@pytest.mark.parametrize("t,parca", [(38.0, "uzat"), (66.0, "kısalt")])
def test_sure_hedef_disinda_geri_bildirim(denetim_yalitik, t, parca):
    denetim_yalitik["t"] = t
    k = ou.konu_kur(PILOT, "Otlukbeli Savaşı", "shorts")
    h = ou.senaryo_denetle({"cumleler": [_cumle(1)]}, {}, k, [], lambda cs: {})
    assert len(h) == 1 and f"{t:.1f} sn" in h[0] and "45–60" in h[0] and parca in h[0]


class Sahte:
    def __init__(self, yanitlar):
        self.yanitlar, self.istemler, self.cagri_sayisi, self.kullanilan_model = list(yanitlar), [], 0, "sahte-flash"

    def tamamla(self, istem, adim, baglam):
        self.istemler.append((adim, istem))
        self.cagri_sayisi += 1
        y = self.yanitlar.pop(0)
        if isinstance(y, BaseException):
            raise y
        return y


def test_senaryo_hatalari_geri_beslenir_ucuncu_denemede_gecer(denetim_yalitik):
    k = ou.konu_kur(PILOT, "Otlukbeli Savaşı", "shorts")
    g = [{"gorsel_id": "g1", "aciklama": "x"}]
    iyi = {"cumleler": [_cumle(1, "gorsel25d", gorsel25d={"gorsel_id": "g1"}), _cumle(2)]}
    kotu = {"cumleler": [_cumle(1, "gorsel25d", gorsel25d={"gorsel_id": "yok"})]}
    s = Sahte(["bu JSON değil", json.dumps(kotu), "```json\n" + json.dumps(iyi) + "\n```"])
    sen, gecmis = ou.senaryo_uret(s, k, {"kartlar": []}, g, olc=lambda cs: {})
    assert sen["konu"] == k["kimlik"] and sen["format"] == "shorts" and len(gecmis) == 3
    assert "JSON değil" in s.istemler[1][1] and "listede yok" in s.istemler[2][1]    # hata bir sonraki isteme girer
    assert all("GÖRSEL TÜR KURALLARI" in i for _, i in s.istemler)


def test_senaryo_uc_denemede_gecmezse_durur(denetim_yalitik):
    k = ou.konu_kur(PILOT, "Otlukbeli Savaşı", "shorts")
    with pytest.raises(ou.UretimHatasi) as e:
        ou.senaryo_uret(Sahte(["x", "y", "z"]), k, {"kartlar": []}, [], olc=lambda cs: {})
    assert e.value.asama == "senaryo"


# ================================================================== planla: biçim, anahtar, uçtan uca (sahte)

def test_uzun_bicim_acikca_reddedilir_ve_hicbir_sey_cagrilmaz(tmp_path):
    with pytest.raises(ou.UretimHatasi) as e:
        ou.planla("Otlukbeli Savaşı", "uzun", tmp_path, "AIza", havuz_fn=lambda k: pytest.fail("çağrılmamalı"))
    assert e.value.kod == 3 and "anlati.shorts_denetle" in str(e.value) and "1080×1920" in str(e.value)


def test_anahtarsiz_uretim_yapilmaz_mock_yok(tmp_path):
    with pytest.raises(ou.UretimHatasi) as e:
        ou.planla("Otlukbeli Savaşı", "shorts", tmp_path, None, havuz_fn=lambda k: pytest.fail("çağrılmamalı"))
    assert e.value.kod == 2 and "mock'a geçilmez" in str(e.value)


def _sahte_planla(is_):
    sen = json.loads((is_ / "senaryo.json").read_text())
    cekimler = [{"id": c["id"], "tur": c["niyet"]["tur"], "sure_sn": 4.0 + i, "cumleler": [c["id"]]}
                for i, c in enumerate(sen["cumleler"])]
    (is_ / "cekim_plani.json").write_text(json.dumps({"konu": sen["konu"], "cekimler": cekimler}))
    return {"gecti": True, "hatalar": {}, "toplam_sure_sn": 52.0}


def test_planla_uctan_uca_sahte_saglayiciyla(tmp_path, denetim_yalitik, monkeypatch):
    from motor.varlik import tarihi_gorsel
    monkeypatch.setattr(tarihi_gorsel, "dogrulanmis_dosya", lambda gid: (tmp_path / gid, {}))
    monkeypatch.setattr(ou, "GORSEL_KOK", tmp_path / "gorsel")
    havuz = {"kayitlar": [_kayit(i) for i in range(1, 6)]}
    sorgu = json.dumps([{"gorsel_id": "portre", "sorgu": "q", "aciklama": "portre"}])
    k = ou.konu_kur(PILOT, "Otlukbeli Savaşı", "shorts")
    senaryo = {"cumleler": [_cumle(1, "gorsel25d", gorsel25d={"gorsel_id": f"{k['kimlik']}-portre"}),
                            _cumle(2, "harita", evre="E1"), _cumle(3), _cumle(4), _cumle(5)]}
    s = Sahte([sorgu, json.dumps(senaryo)])
    r = ou.planla("Otlukbeli Savaşı", "shorts", tmp_path / "is", "AIza", 2, havuz_fn=lambda konu: havuz,
                  saglayici_fn=lambda: s, topla=lambda q, h: {"lisans_turu": "PD-Art", "eser_adi": "p"},
                  planla_fn=_sahte_planla, olc=lambda cs: {})
    is_ = Path(r["is"])
    for ad in ("konu.json", "arastirma.json", "senaryo.json", "kart_eslemesi.json", "cekim_plani.json", "parcalar.json"):
        assert (is_ / ad).exists(), ad
    assert r["senaryo"]["turler"] == {"harita": 1, "gorsel25d": 1, "3d": 3} and r["gorseller"][0]["lisans"] == "PD-Art"
    assert r["cekimler"]["3d"] == ["S3", "S4", "S5"] and sum(len(p["cekimler"]) for p in r["parcalar"]) == 3
    assert [a for a, _ in s.istemler] == ["gorsel_sorgu", "senaryo"] and s.cagri_sayisi == 2
    assert r["arastirma"]["kart"] == 5 and r["arastirma"]["kesin"] == 5


def test_gorsel_sorgusu_basarisizsa_25d_siz_devam_kota_ise_durur(tmp_path, denetim_yalitik):
    havuz = {"kayitlar": [_kayit(1)]}
    senaryo = {"cumleler": [_cumle(1), _cumle(2)]}

    class Kota(Exception):
        sinif = "kota"
    r = ou.planla("Otlukbeli Savaşı", "shorts", tmp_path / "a", "AIza", havuz_fn=lambda k: havuz,
                  saglayici_fn=lambda: Sahte([TimeoutError("x"), json.dumps(senaryo)]), topla=lambda q, h: {},
                  planla_fn=_sahte_planla, olc=lambda cs: {})
    assert r["gorseller"] == [] and r["senaryo"]["turler"]["3d"] == 2
    with pytest.raises(ou.UretimHatasi) as e:
        ou.planla("Otlukbeli Savaşı", "shorts", tmp_path / "b", "AIza", havuz_fn=lambda k: havuz,
                  saglayici_fn=lambda: Sahte([Kota("429")]), planla_fn=_sahte_planla)
    assert e.value.kod == 4


def test_plan_kapidan_gecmezse_durur(tmp_path, denetim_yalitik):
    with pytest.raises(ou.UretimHatasi) as e:
        ou.planla("Otlukbeli Savaşı", "shorts", tmp_path, "AIza", havuz_fn=lambda k: {"kayitlar": [_kayit(1)]},
                  saglayici_fn=lambda: Sahte(["[]", json.dumps({"cumleler": [_cumle(1)]})]),
                  planla_fn=lambda is_: {"gecti": False, "hatalar": {"sure": ["toplam 30 sn"]}}, olc=lambda cs: {})
    assert e.value.asama == "plan" and "toplam 30 sn" in str(e.value)


# ================================================================== paralel parçalar

def test_parcalara_bol_dengeli_ve_tam():
    plan = {"cekimler": [{"id": f"S{i}", "tur": "3d" if i % 3 else "harita", "sure_sn": float(i)} for i in range(1, 13)]}
    p = ou.parcalara_bol(plan, 3)
    ids = [c for x in p for c in x["cekimler"]]
    uc = [c["id"] for c in plan["cekimler"] if c["tur"] == "3d"]
    assert sorted(ids) == sorted(uc) and len(ids) == len(set(ids)) and len(p) == 3
    sureler = [x["sure_sn"] for x in p]
    assert max(sureler) - min(sureler) <= max(c["sure_sn"] for c in plan["cekimler"])
    assert ou.parcalara_bol(plan, 50)[-1]["parca"] == len(uc) - 1              # parça sayısı 3D çekim sayısını aşmaz
    assert ou.parcalara_bol({"cekimler": [{"id": "H", "tur": "harita", "sure_sn": 3}]}, 4) == [
        {"parca": 0, "cekimler": [], "sure_sn": 0.0}]                           # matris boş kalmaz


def test_dogrulama_plani_fiksturu(tmp_path, monkeypatch):
    from motor.varlik import tarihi_gorsel
    monkeypatch.setattr(tarihi_gorsel, "dogrulanmis_dosya", lambda gid: (tmp_path / gid, {}))
    monkeypatch.setattr(ou, "GORSEL_KOK", tmp_path / "g")
    r = ou.dogrulama_plani(KOK / "deneyler/faz62b/dogrulama.json", tmp_path / "is", 3,
                           topla=lambda s, h: {"lisans_turu": "PD-Art"}, planla_fn=_sahte_planla)
    sen = json.loads((Path(r["is"]) / "senaryo.json").read_text())
    n = {c["id"]: c["niyet"] for c in sen["cumleler"]}
    assert r["dogrulama_fiksturu"] is True and r["kimlik"].endswith("-dogrulama")
    assert n["S2"]["tur"] == "gorsel25d" and n["S7"] == {"tur": "harita", "evre": "E5", "metin_katmani": "Akkoyunlu merkezi dağılıyor"}
    assert sorted(r["degisen"]) == ["S2", "S7"]


# ================================================================== CLI

def test_cli_cikis_kodlari(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    c = str(tmp_path / "c")
    assert ou.main(["planla", "--cikti", c]) == 3
    assert ou.main(["planla", "--konu", "Otlukbeli Savaşı", "--mod", "uzun", "--cikti", c]) == 3
    assert ou.main(["planla", "--konu", "Otlukbeli Savaşı", "--cikti", c]) == 2
    r = json.loads((tmp_path / "c" / "otonom_planla.json").read_text())
    assert r["gecti"] is False and r["asama"] == "anahtar"


# ================================================================== iş akışı ve ortak eylem

def _yaml(p):
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(p.read_text())


def test_is_akisi_elle_varsayilan_konu_ve_bicimler():
    wf = _yaml(WF)
    t = wf.get("on", wf.get(True))
    assert set(t) == {"workflow_dispatch", "push"} and t["push"]["branches"] == ["faz62b-otonom-uretim"]
    g = t["workflow_dispatch"]["inputs"]
    assert g["konu"]["default"] == "Otlukbeli Savaşı"
    assert g["mod"]["type"] == "choice" and g["mod"]["options"] == ["shorts", "uzun", "her_ikisi"]
    assert wf["permissions"] == {"contents": "read"}


def test_is_akisi_yukleme_yapmaz_gemini_yalniz_elle():
    yazi = "\n".join(x for x in WF.read_text().splitlines() if not x.lstrip().startswith("#")).lower()
    for yasak in ("youtube", "yt_", "upload_video", "tiktok", "git push", "client_secret"):
        assert yasak not in yazi, yasak
    wf = _yaml(WF)
    adim = next(a for a in wf["jobs"]["plan"]["steps"] if a.get("id") == "plan")
    assert adim["env"]["GEMINI_API_KEY"] == "${{ github.event_name == 'workflow_dispatch' && secrets.GEMINI_API_KEY || '' }}"
    assert WF.read_text().count("secrets.") == 2                               # yalnız GEMINI + OPENALEX, yalnız plan işinde


def test_is_akisi_paralel_render_ve_artifactlar():
    wf = _yaml(WF)
    j = wf["jobs"]
    assert j["plan"]["needs"] == "varlik" and j["render"]["needs"] == "plan" and j["kurgu"]["needs"] == ["plan", "render"]
    assert j["render"]["strategy"]["matrix"]["parca"] == "${{ fromJSON(needs.plan.outputs.parcalar) }}"
    assert all(j[x]["timeout-minutes"] >= 25 for x in ("render", "kurgu"))
    yuk = [a for a in j["kurgu"]["steps"] if str(a.get("uses", "")).startswith("actions/upload-artifact")]
    assert yuk and "*.mp4" in yuk[-1]["with"]["path"]
    indir = [a for a in j["kurgu"]["steps"] if str(a.get("uses", "")).startswith("actions/download-artifact")]
    assert any(a["with"].get("pattern") == "render-*" and a["with"].get("merge-multiple") for a in indir)
    # plan sırasında üretilen binek GLB'leri render ve kurgu işlerine aynen devredilir (önbellek anahtarı tutarlı)
    for is_ in ("render", "kurgu"):
        assert any(a.get("with", {}).get("name") == "binek" for a in j[is_]["steps"]
                   if str(a.get("uses", "")).startswith("actions/download-artifact")), is_
    plan_ortam = next(a for a in j["plan"]["steps"] if a.get("uses") == "./.github/actions/motor-ortami")
    assert plan_ortam["with"]["bpy"] == "true"


def test_ortak_eylem_dogrulamali_kurulum():
    e = _yaml(EYLEM)
    assert e["runs"]["using"] == "composite"
    yazi = EYLEM.read_text()
    assert "sha512sum -c -" in yazi and "bpy==5.3.0" in yazi and "$MPFB_COMMIT" in yazi
    assert "secrets." not in yazi and "faz62a-varlik-${{ steps.anahtar.outputs.anahtar }}" in yazi
    assert "fail-on-cache-miss: ${{ inputs.varlik == 'gerekli' }}" in yazi


def test_adaptor_orkestrasyon_katmaninda_degil():
    """Faz-54 kuralı: motor/orkestrasyon üretim modüllerini içe aktarmaz; adaptör depo kökündedir."""
    assert not (KOK / "motor/orkestrasyon/otonom_uret.py").exists() and (KOK / "otonom_uret.py").exists()
