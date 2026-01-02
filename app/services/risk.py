from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Mapping


@dataclass(frozen=True)
class PositionSize:
    shares: int
    notional: float
    risk_per_trade: float
    stop_loss_price: float


@dataclass
class RiskGovernorState:
    trades_today: int = 0
    daily_loss: float = 0.0
    last_trade_timestamp: datetime | None = None
    daily_reset_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0))


class RiskGovernor:
    def __init__(
        self,
        max_risk_per_trade: float = 0.01,
        max_daily_loss: float = 0.05,
        max_trades_per_day: int = 10,
        cooldown_seconds: int = 300,
        account_size: float = 100_000.0,
    ) -> None:
        self.max_risk_per_trade = max_risk_per_trade
        self.max_daily_loss = max_daily_loss
        self.max_trades_per_day = max_trades_per_day
        self.cooldown_seconds = cooldown_seconds
        self.account_size = account_size
        self.state = RiskGovernorState()

    def evaluate(
        self,
        symbol: str,
        decision: str,
        confidence: float,
        price: float,
        atr: float,
        previous_loss: float = 0.0,
    ) -> tuple[bool, str, PositionSize | None]:
        now = datetime.now(timezone.utc)
        self._reset_daily_state_if_needed(now)

        if decision == "NO_TRADE":
            return True, "Trade rejected by AI/strategy", None

        if self._check_max_loss_breach(previous_loss):
            return False, "Max daily loss exceeded", None

        if self._check_max_trades_breach():
            return False, "Max trades per day exceeded", None

        if self._check_cooldown_violation(now):
            return False, "In cooldown period", None

        if not self._validate_inputs(symbol, price, atr):
            return False, "Invalid price or ATR data", None

        if atr <= 0:
            return False, "ATR must be positive", None

        position = self._calculate_position_size(price, atr)

        if self._exceeds_max_risk_per_trade(position):
            return False, f"Trade risk ${position.risk_per_trade:.2f} exceeds max ${self.max_risk_per_trade * self.account_size:.2f}", None

        if self._would_exceed_daily_loss(position.risk_per_trade):
            return False, "Trade would breach daily loss limit", None

        return True, "Trade approved", position

    def record_trade(self, symbol: str, result: float) -> None:
        now = datetime.now(timezone.utc)
        self._reset_daily_state_if_needed(now)
        self.state.trades_today += 1
        self.state.last_trade_timestamp = now
        if result < 0:
            self.state.daily_loss += abs(result)

    def _calculate_position_size(self, price: float, atr: float) -> PositionSize:
        max_risk_dollars = self.account_size * self.max_risk_per_trade
        stop_loss_distance = atr * 2
        stop_loss_price = price - stop_loss_distance
        shares = int(max_risk_dollars / stop_loss_distance)
        if shares == 0:
            shares = 1
        notional = shares * price
        actual_risk = shares * stop_loss_distance
        return PositionSize(
            shares=shares,
            notional=notional,
            risk_per_trade=actual_risk,
            stop_loss_price=stop_loss_price,
        )

    def _check_max_loss_breach(self, previous_loss: float) -> bool:
        if previous_loss > self.max_daily_loss * self.account_size:
            return True
        return self.state.daily_loss > self.max_daily_loss * self.account_size

    def _check_max_trades_breach(self) -> bool:
        return self.state.trades_today >= self.max_trades_per_day

    def _check_cooldown_violation(self, now: datetime) -> bool:
        if self.state.last_trade_timestamp is None:
            return False
        elapsed = (now - self.state.last_trade_timestamp).total_seconds()
        return elapsed < self.cooldown_seconds

    def _would_exceed_daily_loss(self, risk_this_trade: float) -> bool:
        projected = self.state.daily_loss + risk_this_trade
        return projected > self.max_daily_loss * self.account_size

    def _exceeds_max_risk_per_trade(self, position: PositionSize) -> bool:
        return position.risk_per_trade > self.max_risk_per_trade * self.account_size

    def _validate_inputs(self, symbol: str, price: float, atr: float) -> bool:
        if not symbol or not isinstance(symbol, str):
            return False
        if price <= 0:
            return False
        if atr < 0:
            return False
        return True

    def _reset_daily_state_if_needed(self, now: datetime) -> None:
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if today > self.state.daily_reset_time:
            self.state = RiskGovernorState(daily_reset_time=today)
