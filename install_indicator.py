"""Installe et compile l'indicateur TrendBotLines dans ton MT5 (aucun ordre, aucun compte touché)."""
import shutil
import subprocess
import time
import unicodedata
from pathlib import Path

import MetaTrader5 as mt5

HERE = Path(__file__).parent
SRC = HERE / "mql5" / "TrendBotLines.mq5"

# source en ASCII pur (évite tout souci d'encodage dans MetaEditor)
s = SRC.read_text(encoding="utf-8").replace("\u2191", "UP").replace("\u2193", "DN")
s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
SRC.write_text(s.replace("\r\n", "\n"), encoding="ascii", newline="\r\n")

if not mt5.initialize():
    raise SystemExit(f"MT5 injoignable : {mt5.last_error()}")
data = Path(mt5.terminal_info().data_path)
mt5.shutdown()

dest_dir = data / "MQL5" / "Indicators" / "TrendBot"
dest_dir.mkdir(parents=True, exist_ok=True)
dest = dest_dir / "TrendBotLines.mq5"
shutil.copy(SRC, dest)

log = dest_dir / "compile.log"
subprocess.run([r"C:\Program Files\MetaTrader 5\MetaEditor64.exe", f"/compile:{dest}", f"/log:{log}"], timeout=120)
time.sleep(3)
print(log.read_text(encoding="utf-16", errors="replace") if log.exists() else "pas de log")
print("fichiers :", [(f.name, f.stat().st_size) for f in dest_dir.iterdir()])
