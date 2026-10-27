"""Vérifie que les réglages enregistrés depuis l'interface sont bien lus par le bot (config.py). python test_settings.py"""
import importlib
import json
import tkinter.messagebox as mb
from pathlib import Path

mb.showinfo = mb.showerror = lambda *a, **k: None
f = Path(__file__).with_name("settings.json")
backup = f.read_text(encoding="utf-8") if f.exists() else None
try:
    import app
    import config

    a = app.App()
    a.entries["CAPITAL_CAP"].set("250")
    a.entries["RISK_PCT"].set("0,5")          # virgule française acceptée
    a.entries["MAX_POSITIONS"].set("1")
    a.save_settings()
    saved = json.loads(f.read_text(encoding="utf-8"))
    assert saved["CAPITAL_CAP"] == 250 and saved["RISK_PCT"] == 0.5 and saved["MAX_POSITIONS"] == 1, saved
    importlib.reload(config)
    assert config.CAPITAL_CAP == 250 and config.RISK_PCT == 0.5 and config.MAX_POSITIONS == 1
    # valeur invalide : rien n'est écrit
    f.unlink()
    a.entries["RISK_PCT"].set("abc")
    a.save_settings()
    assert not f.exists(), "une valeur invalide ne doit rien enregistrer"
    # capital vide = capital réel
    a.entries["RISK_PCT"].set("1")
    a.entries["CAPITAL_CAP"].set("")
    a.save_settings()
    importlib.reload(config)
    assert config.CAPITAL_CAP is None
    a.destroy()
    print("OK    réglages : enregistrement, lecture par le bot, valeur invalide refusée, capital vide = réel")
finally:
    if backup is None:
        f.unlink(missing_ok=True)
    else:
        f.write_text(backup, encoding="utf-8")
