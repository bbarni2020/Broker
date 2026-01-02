from __future__ import annotations

import pandas as pd


def vwap(df: pd.DataFrame) -> pd.Series:
    required = {"high", "low", "close", "volume"}
    _require_columns(df, required)
    if len(df) == 0:
        raise ValueError("Data insufficient for VWAP")
    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    cumulative_vp = (typical_price * df["volume"]).cumsum()
    cumulative_volume = df["volume"].cumsum()
    return cumulative_vp / cumulative_volume


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    required = {"high", "low", "close"}
    _require_columns(df, required)
    if len(df) < period + 1:
        raise ValueError("Data insufficient for ATR")
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr_series = true_range.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    return atr_series


def rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    _require_columns(df, {"close"})
    if len(df) < period + 1:
        raise ValueError("Data insufficient for RSI")
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi_series = 100 - (100 / (1 + rs))
    return rsi_series


def ema(df: pd.DataFrame, period: int, column: str = "close") -> pd.Series:
    _require_columns(df, {column})
    if len(df) < period:
        raise ValueError("Data insufficient for EMA")
    return df[column].ewm(span=period, adjust=False, min_periods=period).mean()


def sma(df: pd.DataFrame, period: int, column: str = "close") -> pd.Series:
    _require_columns(df, {column})
    if len(df) < period:
        raise ValueError("Data insufficient for SMA")
    return df[column].rolling(window=period, min_periods=period).mean()


def relative_volume(df: pd.DataFrame, period: int = 20) -> pd.Series:
    _require_columns(df, {"volume"})
    if len(df) < period:
        raise ValueError("Data insufficient for relative volume")
    rolling = df["volume"].rolling(window=period, min_periods=period).mean()
    return df["volume"] / rolling


def percent_change(df: pd.DataFrame, column: str = "close") -> pd.Series:
    _require_columns(df, {column})
    if len(df) < 2:
        raise ValueError("Data insufficient for percent change")
    return df[column].pct_change()


def _require_columns(df: pd.DataFrame, required: set[str]) -> None:
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")