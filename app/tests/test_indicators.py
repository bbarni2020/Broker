from __future__ import annotations

import unittest

import pandas as pd

from app.indicators import atr, ema, percent_change, relative_volume, rsi, sma, vwap


class IndicatorTests(unittest.TestCase):
    def setUp(self) -> None:
        data = {
            "high": [10, 11, 12, 13, 14, 15],
            "low": [9, 9.5, 10, 11, 12, 13],
            "close": [9.5, 10.5, 11, 12, 13, 14],
            "volume": [100, 110, 120, 130, 140, 150],
        }
        self.df = pd.DataFrame(data)

    def test_vwap(self) -> None:
        series = vwap(self.df)
        self.assertEqual(len(series), len(self.df))
        self.assertGreater(series.iloc[-1], 0)

    def test_atr_insufficient(self) -> None:
        with self.assertRaises(ValueError):
            atr(self.df.iloc[:10], period=10)

    def test_atr_values(self) -> None:
        series = atr(self.df, period=3)
        self.assertFalse(series.dropna().empty)
        self.assertGreater(series.dropna().iloc[-1], 0)

    def test_rsi_insufficient(self) -> None:
        with self.assertRaises(ValueError):
            rsi(self.df.iloc[:5], period=5)

    def test_rsi_values(self) -> None:
        series = rsi(self.df, period=3)
        self.assertTrue((series.dropna() >= 0).all())
        self.assertTrue((series.dropna() <= 100).all())

    def test_ema_sma(self) -> None:
        ema_series = ema(self.df, period=3)
        sma_series = sma(self.df, period=3)
        self.assertEqual(len(ema_series), len(self.df))
        self.assertEqual(len(sma_series), len(self.df))
        self.assertTrue(ema_series.iloc[-1] > 0)
        self.assertTrue(sma_series.iloc[-1] > 0)

    def test_relative_volume(self) -> None:
        rv = relative_volume(self.df, period=3)
        self.assertEqual(len(rv), len(self.df))
        self.assertTrue(rv.iloc[-1] > 0)

    def test_percent_change(self) -> None:
        pc = percent_change(self.df)
        self.assertEqual(len(pc), len(self.df))
        self.assertTrue(pd.isna(pc.iloc[0]))
        self.assertAlmostEqual(pc.iloc[1], (10.5 - 9.5) / 9.5)


if __name__ == "__main__":
    unittest.main()
