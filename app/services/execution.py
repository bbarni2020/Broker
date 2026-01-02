from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

import httpx

from app.logging import AuditLogger, log_decision


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    FILLED = "filled"
    PARTIAL_FILL = "partially_filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class TimeInForce(Enum):
    DAY = "day"
    GTC = "gtc"
    OPG = "opg"
    CLS = "cls"


@dataclass(frozen=True)
class StopLoss:
    stop_price: float


@dataclass(frozen=True)
class TakeProfit:
    limit_price: float


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    qty: int
    side: str
    order_type: OrderType
    time_in_force: TimeInForce
    limit_price: float | None = None
    stop_loss: StopLoss | None = None
    take_profit: TakeProfit | None = None


@dataclass(frozen=True)
class ExecutedOrder:
    order_id: str
    symbol: str
    qty: int
    filled_qty: int
    side: str
    status: OrderStatus
    filled_avg_price: float | None
    submitted_at: datetime
    filled_at: datetime | None
    estimated_slippage_bps: float


@dataclass(frozen=True)
class ExecutionError(Exception):
    code: str
    message: str
    status_code: int | None = None
    payload: Mapping[str, Any] | None = None

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class HealthStatus:
    is_healthy: bool
    market_state: str
    as_of: datetime
    detail: str


class AlpacaExecutionClient:
    PAPER_BASE_URL = "https://paper-api.alpaca.markets"
    LIVE_BASE_URL = "https://api.alpaca.markets"

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        trading_mode: str = "paper",
        live_trading_confirmed: bool = False,
        http_client: httpx.AsyncClient | None = None,
        base_url_override: str | None = None,
        timeout_seconds: float = 0.5,
    ) -> None:
        normalized_mode = trading_mode.strip().lower()
        if normalized_mode not in {"paper", "live"}:
            raise ExecutionError("invalid_mode", "Trading mode must be paper or live")
        if normalized_mode == "live" and not live_trading_confirmed:
            raise ExecutionError("live_not_confirmed", "Live trading requires explicit confirmation")

        base_url = base_url_override or (self.LIVE_BASE_URL if normalized_mode == "live" else self.PAPER_BASE_URL)
        headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key,
            "Content-Type": "application/json",
        }

        self.base_url = base_url
        self._owns_client = http_client is None
        timeout = httpx.Timeout(timeout_seconds)
        self.client = http_client or httpx.AsyncClient(base_url=base_url, headers=headers, timeout=timeout)

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def submit_order(self, request: OrderRequest, limit_price_override: float | None = None) -> ExecutedOrder:
        payload = self._build_order_payload(request, limit_price_override)
        response = await self._request("POST", "/v2/orders", payload)
        body = response.json()
        return self._parse_order_response(body)

    async def get_order(self, order_id: str) -> ExecutedOrder | None:
        response = await self._request("GET", f"/v2/orders/{order_id}", None, allow_not_found=True)
        if response is None:
            return None
        body = response.json()
        return self._parse_order_response(body)

    async def cancel_order(self, order_id: str) -> bool:
        response = await self._request("DELETE", f"/v2/orders/{order_id}", None, allow_not_found=True)
        if response is None:
            return False
        return response.status_code == 204

    async def check_health(self) -> HealthStatus:
        clock_response = await self._request("GET", "/v2/clock", None)
        account_response = await self._request("GET", "/v2/account", None)
        clock_body = clock_response.json()
        account_body = account_response.json()
        as_of = datetime.fromisoformat(clock_body.get("timestamp", "").replace("Z", "+00:00")) if clock_body.get("timestamp") else datetime.now(timezone.utc)
        is_open = bool(clock_body.get("is_open", False))
        blocked = bool(account_body.get("trading_blocked", False))
        market_state = "open" if is_open else "closed"
        if blocked:
            return HealthStatus(False, market_state, as_of, "account_blocked")
        if not is_open:
            return HealthStatus(False, market_state, as_of, "market_closed")
        return HealthStatus(True, market_state, as_of, "ok")

    def _build_order_payload(self, request: OrderRequest, limit_price_override: float | None) -> Mapping[str, object]:
        payload: dict[str, object] = {
            "symbol": request.symbol,
            "qty": request.qty,
            "side": request.side,
            "type": request.order_type.value,
            "time_in_force": request.time_in_force.value,
        }

        if request.order_type == OrderType.LIMIT:
            limit_price = limit_price_override if limit_price_override is not None else request.limit_price
            if limit_price is None:
                raise ExecutionError("missing_limit_price", "Limit price required for limit orders")
            payload["limit_price"] = limit_price

        if request.stop_loss is not None:
            payload["stop_loss"] = {"stop_price": request.stop_loss.stop_price}

        if request.take_profit is not None:
            payload["take_profit"] = {"limit_price": request.take_profit.limit_price}

        return payload

    def _parse_order_response(self, body: Mapping[str, Any]) -> ExecutedOrder:
        order_id = str(body.get("id", "unknown"))
        status = self._map_status(str(body.get("status", "pending")))
        symbol = str(body.get("symbol", "UNKNOWN"))
        qty = int(body.get("qty", 0))
        filled_qty = int(body.get("filled_qty", 0))
        side = str(body.get("side", "buy"))
        filled_avg_price = float(body["filled_avg_price"]) if body.get("filled_avg_price") is not None else None
        submitted_at = datetime.fromisoformat(str(body.get("created_at", "")).replace("Z", "+00:00")) if body.get("created_at") else datetime.now(timezone.utc)
        filled_at = None
        if body.get("filled_at"):
            filled_at = datetime.fromisoformat(str(body.get("filled_at", "")).replace("Z", "+00:00"))

        return ExecutedOrder(
            order_id=order_id,
            symbol=symbol,
            qty=qty,
            filled_qty=filled_qty,
            side=side,
            status=status,
            filled_avg_price=filled_avg_price,
            submitted_at=submitted_at,
            filled_at=filled_at,
            estimated_slippage_bps=0.0,
        )

    def _map_status(self, status_str: str) -> OrderStatus:
        normalized = status_str.lower()
        status_mapping = {
            "pending": OrderStatus.PENDING,
            "new": OrderStatus.PENDING,
            "accepted": OrderStatus.ACCEPTED,
            "accepted_for_bidding": OrderStatus.ACCEPTED,
            "filled": OrderStatus.FILLED,
            "partially_filled": OrderStatus.PARTIAL_FILL,
            "replaced": OrderStatus.ACCEPTED,
            "pending_replace": OrderStatus.PENDING,
            "pending_cancel": OrderStatus.PENDING,
            "canceled": OrderStatus.CANCELLED,
            "cancelled": OrderStatus.CANCELLED,
            "expired": OrderStatus.EXPIRED,
            "rejected": OrderStatus.REJECTED,
            "done_for_day": OrderStatus.CANCELLED,
        }
        return status_mapping.get(normalized, OrderStatus.PENDING)

    async def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, object] | None,
        allow_not_found: bool = False,
    ) -> httpx.Response | None:
        try:
            response = await self.client.request(method, path, json=payload)
        except httpx.TimeoutException as exc:
            raise ExecutionError("timeout", "Alpaca request timed out", None, {"path": path, "error": str(exc)})
        except httpx.HTTPError as exc:
            raise ExecutionError("network_error", "Alpaca request failed", None, {"path": path, "error": str(exc)})

        if allow_not_found and response.status_code == 404:
            return None

        if response.status_code >= 400:
            detail: Any
            try:
                detail = response.json()
            except Exception:
                detail = response.text
            raise ExecutionError("http_error", "Alpaca returned error", response.status_code, {"path": path, "detail": detail})

        return response


class ExecutionService:
    def __init__(
        self,
        client: AlpacaExecutionClient,
        max_slippage_bps: float = 50.0,
        require_position_check: bool = True,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        self.client = client
        self.max_slippage_bps = max_slippage_bps
        self.require_position_check = require_position_check
        self.audit_logger = audit_logger

    def _log(self, symbol: str, decision: str, reason: str, metadata: Mapping[str, Any] | None = None) -> None:
        log_decision(symbol, "execution", decision, reason, metadata=metadata)

    async def execute_trade(
        self,
        request: OrderRequest,
        position_size_from_risk: int,
        entry_price_estimate: float,
        has_passed_all_checks: bool,
    ) -> tuple[bool, str, ExecutedOrder | None]:
        if request.qty <= 0:
            reason = "Invalid quantity"
            self._log(request.symbol, "rejected", reason)
            return False, reason, None

        if not has_passed_all_checks:
            reason = "Trade rejected: failed validation/risk checks"
            self._log(request.symbol, "rejected", reason)
            return False, reason, None

        if request.qty != position_size_from_risk:
            reason = f"Order qty {request.qty} does not match risk-calculated position {position_size_from_risk}"
            self._log(request.symbol, "rejected", reason)
            return False, reason, None

        if entry_price_estimate <= 0:
            reason = "Invalid entry price estimate"
            self._log(request.symbol, "rejected", reason)
            return False, reason, None

        try:
            order = await self.client.submit_order(request)
        except ExecutionError as exc:
            reason = f"Order submission failed: {exc.message}"
            self._log(request.symbol, "rejected", reason, metadata={"code": exc.code, "status": exc.status_code})
            return False, reason, None

        slippage_bps = 0.0
        if order.filled_avg_price is not None and entry_price_estimate > 0:
            if request.side.lower() == "buy":
                slippage_bps = ((order.filled_avg_price - entry_price_estimate) / entry_price_estimate) * 10000
            else:
                slippage_bps = ((entry_price_estimate - order.filled_avg_price) / entry_price_estimate) * 10000
            order = replace(order, estimated_slippage_bps=slippage_bps)

        if self.audit_logger:
            self.audit_logger.record_order(order)

        if order.status == OrderStatus.REJECTED:
            reason = f"Order rejected by broker: {order.symbol}"
            self._log(order.symbol, "rejected", reason, metadata={"order_id": order.order_id})
            return False, reason, None

        if order.status == OrderStatus.CANCELLED:
            reason = f"Order cancelled: {order.symbol}"
            self._log(order.symbol, "rejected", reason, metadata={"order_id": order.order_id})
            return False, reason, None

        if order.status == OrderStatus.EXPIRED:
            reason = f"Order expired: {order.symbol}"
            self._log(order.symbol, "rejected", reason, metadata={"order_id": order.order_id})
            return False, reason, None

        if order.filled_qty > 0 and order.estimated_slippage_bps > self.max_slippage_bps:
            try:
                await self.client.cancel_order(order.order_id)
            except ExecutionError:
                pass
            if self.audit_logger:
                self.audit_logger.record_trade_outcome(
                    order.order_id,
                    order.symbol,
                    "cancelled_slippage",
                    0.0,
                    context={"slippage_bps": order.estimated_slippage_bps},
                )
            reason = f"Slippage {order.estimated_slippage_bps:.1f} bps exceeds max {self.max_slippage_bps} bps"
            self._log(order.symbol, "rejected", reason, metadata={"order_id": order.order_id})
            return False, reason, order

        if order.status == OrderStatus.PARTIAL_FILL:
            reason = f"Order {order.order_id} partially filled"
            self._log(order.symbol, "accepted", reason, metadata={"filled_qty": order.filled_qty})
            return True, reason, order

        reason = f"Order {order.order_id} submitted successfully"
        self._log(order.symbol, "accepted", reason, metadata={"status": order.status.value})
        return True, reason, order

    async def check_order_status(self, order_id: str) -> ExecutedOrder | None:
        return await self.client.get_order(order_id)

    async def cancel_trade(self, order_id: str) -> bool:
        return await self.client.cancel_order(order_id)

    async def check_health(self) -> HealthStatus:
        status = await self.client.check_health()
        detail = status.detail if status.detail else ""
        self._log("system", "health", detail, metadata={"market_state": status.market_state, "healthy": status.is_healthy})
        return status
