"""Fetch and normalize hourly BTC-USD candles from three public exchange APIs (no API keys)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

HOUR = pd.Timedelta(hours=1)
COLUMNS = ["ts", "open", "high", "low", "close", "volume"]
SOURCES = ("coinbase", "kraken", "binance_us")
_HEADERS = {"User-Agent": "mdq/0.1 (market data quality demo)"}


def _get(url: str, params: dict | None = None):
    response = requests.get(url, params=params, headers=_HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()


def _finish(df: pd.DataFrame) -> pd.DataFrame:
    df = df[COLUMNS].copy()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    for col in COLUMNS[1:]:
        df[col] = df[col].astype(float)
    return df.sort_values("ts").reset_index(drop=True)


def normalize_coinbase(payload: list) -> pd.DataFrame:
    """Coinbase rows are [time, low, high, open, close, volume], newest first."""
    df = pd.DataFrame(payload, columns=["ts", "low", "high", "open", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="s", utc=True)
    return _finish(df)


def normalize_kraken(payload: dict) -> pd.DataFrame:
    """Kraken rows are [time, open, high, low, close, vwap, volume, count]."""
    key = next(k for k in payload["result"] if k != "last")
    df = pd.DataFrame(
        payload["result"][key],
        columns=["ts", "open", "high", "low", "close", "vwap", "volume", "count"],
    )
    df["ts"] = pd.to_datetime(df["ts"], unit="s", utc=True)
    return _finish(df)


def normalize_binance(payload: list) -> pd.DataFrame:
    """Binance rows start with [open_time_ms, open, high, low, close, volume, ...]."""
    df = pd.DataFrame(payload).iloc[:, :6]
    df.columns = ["ts", "open", "high", "low", "close", "volume"]
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return _finish(df)


def drop_incomplete(df: pd.DataFrame, fetched_at: pd.Timestamp) -> pd.DataFrame:
    """Exchanges return the in-progress hour as the newest bar; it is not final, so drop it."""
    return df[df["ts"] + HOUR <= fetched_at].reset_index(drop=True)


def fetch_all(now: pd.Timestamp | None = None) -> tuple[dict[str, pd.DataFrame], pd.Timestamp]:
    fetched_at = now or pd.Timestamp(datetime.now(timezone.utc))
    raw = {
        "coinbase": normalize_coinbase(
            _get("https://api.exchange.coinbase.com/products/BTC-USD/candles", {"granularity": 3600})
        ),
        "kraken": normalize_kraken(
            _get("https://api.kraken.com/0/public/OHLC", {"pair": "XBTUSD", "interval": 60})
        ),
        "binance_us": normalize_binance(
            _get("https://api.binance.us/api/v3/klines", {"symbol": "BTCUSD", "interval": "1h", "limit": 1000})
        ),
    }
    return {name: drop_incomplete(df, fetched_at) for name, df in raw.items()}, fetched_at


def save_snapshot(frames: dict[str, pd.DataFrame], directory: Path, fetched_at: pd.Timestamp) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, df in frames.items():
        df.to_csv(directory / f"{name}.csv", index=False)
    meta = {"fetched_at_utc": fetched_at.isoformat(), "bars": {n: len(d) for n, d in frames.items()}}
    (directory / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")


def load_snapshot(directory: Path) -> dict[str, pd.DataFrame]:
    frames = {}
    for name in SOURCES:
        df = pd.read_csv(directory / f"{name}.csv", parse_dates=["ts"])
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        frames[name] = df
    return frames
