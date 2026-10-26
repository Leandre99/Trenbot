"""Récupération des bougies via l'API WebSocket publique de Deriv (pas de token requis)."""
import asyncio
import json
from pathlib import Path

import pandas as pd
import websockets

WS_URL = "wss://api.derivws.com/trading/v1/options/ws/public"
CACHE = Path(__file__).parent / "cache"

# Granularités acceptées par Deriv (secondes)
GRANULARITY = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}

SYMBOLS = {
    "Volatility 10": "R_10",
    "Volatility 25": "R_25",
    "Volatility 50": "R_50",
    "Volatility 75": "R_75",
    "Volatility 100": "R_100",
    "Step Index": "stpRNG",
    "EUR/USD": "frxEURUSD",
    "GBP/USD": "frxGBPUSD",
    "USD/JPY": "frxUSDJPY",
    "Gold (XAU/USD)": "frxXAUUSD",
}


async def _fetch(symbol: str, granularity: int, end: int | str, count: int) -> list[dict]:
    async with websockets.connect(WS_URL) as ws:
        await ws.send(json.dumps({
            "ticks_history": symbol,
            "adjust_start_time": 1,
            "count": count,
            "end": end,
            "granularity": granularity,
            "style": "candles",
        }))
        resp = json.loads(await ws.recv())
    if "error" in resp:
        raise RuntimeError(f"{symbol}: {resp['error']['message']}")
    return resp["candles"]


def get_candles(symbol: str, tf: str = "H1", total: int = 20000, use_cache: bool = True) -> pd.DataFrame:
    """Télécharge `total` bougies (par blocs de 5000, en remontant le temps)."""
    CACHE.mkdir(exist_ok=True)
    path = CACHE / f"{symbol}_{tf}_{total}.csv"
    if use_cache and path.exists():
        return pd.read_csv(path, index_col=0, parse_dates=True)

    gran = GRANULARITY[tf]
    rows: list[dict] = []
    end: int | str = "latest"
    while len(rows) < total:
        batch = asyncio.run(_fetch(symbol, gran, end, min(5000, total - len(rows))))
        if not batch:
            break
        rows = batch + rows
        first = batch[0]["epoch"]
        if end != "latest" and first >= end:
            break
        end = first - 1
        if len(batch) < 2:
            break

    df = pd.DataFrame(rows).drop_duplicates("epoch").sort_values("epoch")
    df.index = pd.to_datetime(df["epoch"], unit="s")
    df = df[["open", "high", "low", "close"]].astype(float)
    df.to_csv(path)
    return df


if __name__ == "__main__":
    df = get_candles("R_50", "H1", 1000, use_cache=False)
    print(df.tail())
    print(len(df), "bougies")
