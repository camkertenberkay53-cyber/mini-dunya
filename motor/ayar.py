"""Motorun yolları. Kaynak depoları ve ara çıktılar repo dışında tutulur (büyükler, yeniden üretilebilirler)."""
import os
from pathlib import Path

MOTOR = Path(__file__).resolve().parent
REPO = MOTOR.parent
KAYNAK_KOK = Path(os.environ.get("MOTOR_KAYNAK", "/tmp/varlik"))      # kaynak depoların klonları
ONBELLEK = Path(os.environ.get("MOTOR_ONBELLEK", "/tmp/motor_onbellek"))  # derlenmiş varlık, render
GODOT = os.environ.get("GODOT", "/tmp/godot/Godot_v4.7.2-stable_linux.x86_64")
KAYIT = MOTOR / "varlik" / "kayit.json"
TARIFLER = MOTOR / "varlik" / "tarifler.yaml"
DENETIM_RAPOR = MOTOR / "varlik" / "denetim.json"
GODOT_PROJE = MOTOR / "godot"
for _p in (ONBELLEK,):
    _p.mkdir(parents=True, exist_ok=True)
