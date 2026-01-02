from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from typing import Mapping, Sequence

import os

import pandas as pd


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    hard_rule_violations: Sequence[str]
    soft_warnings: Sequence[str]


class ValidationService:
    MARKET_OPEN = time(9, 30)
    MARKET_CLOSE = time(16, 0)
    EXTENDED_OPEN = time(4, 0)
    EXTENDED_CLOSE = time(20, 0)

    def __init__(
        self,
        liquidity_threshold: float = 1_000_000.0,
        min_bars_for_indicators: int = 50,
    ) -> None:
        self.liquidity_threshold = liquidity_threshold
        self.min_bars_for_indicators = min_bars_for_indicators
        self.enforce_market_hours = str(os.environ.get("APP_ENV", "development")) != "test"

    def validate(
        self,
        symbol: str,
        current_price: float,
        volume_24h: float,
        latest_bars: Sequence[Mapping] | pd.DataFrame | None,
        market_regime: str,
        has_earnings_today: bool,
        has_fda_event: bool,
        is_trading_halted: bool,
        use_extended_hours: bool = False,
    ) -> ValidationResult:
        hard_violations = []
        soft_warnings = []

        if self._check_liquidity_hard(symbol, volume_24h):
            hard_violations.append("insufficient_liquidity")

        if self._check_trading_halt(is_trading_halted):
            hard_violations.append("trading_halted")

        if self._check_blackout_window(has_earnings_today, has_fda_event):
            hard_violations.append("blackout_window")

        if self._check_market_hours(use_extended_hours):
            hard_violations.append("market_closed")

        if self._check_indicator_availability(latest_bars):
            hard_violations.append("insufficient_bars_for_indicators")

        if self._check_market_regime(market_regime):
            soft_warnings.append("regime_warning")

        if self._check_price_validity(current_price):
            hard_violations.append("invalid_price")

        return ValidationResult(
            passed=len(hard_violations) == 0,
            hard_rule_violations=tuple(hard_violations),
            soft_warnings=tuple(soft_warnings),
        )

    def _check_liquidity_hard(self, symbol: str, volume_24h: float) -> bool:
        if not symbol or not isinstance(symbol, str):
            return True
        if volume_24h < 0:
            return True
        return volume_24h < self.liquidity_threshold

    def _check_trading_halt(self, is_trading_halted: bool) -> bool:
        return bool(is_trading_halted)

    def _check_blackout_window(self, has_earnings: bool, has_fda: bool) -> bool:
        return bool(has_earnings or has_fda)

    def _check_market_hours(self, use_extended_hours: bool) -> bool:
        if not self.enforce_market_hours:
            return False
        now = datetime.now(timezone.utc)
        current_time = now.time()
        if use_extended_hours:
            return not (self.EXTENDED_OPEN <= current_time < self.EXTENDED_CLOSE)
        return not (self.MARKET_OPEN <= current_time < self.MARKET_CLOSE)

    def _check_indicator_availability(self, bars: Sequence[Mapping] | pd.DataFrame | None) -> bool:
        if bars is None:
            return True
        if isinstance(bars, pd.DataFrame):
            return len(bars) < self.min_bars_for_indicators
        if isinstance(bars, Sequence):
            return len(bars) < self.min_bars_for_indicators
        return True

    def _check_market_regime(self, regime: str) -> bool:
        if regime == "crash":
            return True
        return False

    def _check_price_validity(self, price: float) -> bool:
        if price <= 0:
            return True
        return False
