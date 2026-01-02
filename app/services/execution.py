from __future__ import annotations

import json
import urllib.request
from asyncio import to_thread
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Mapping


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


class AlpacaExecutionClient:
    def __init__(self, api_key: str, secret_key: str, base_url: str = "https://paper-api.alpaca.markets") -> None:
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = base_url
        self.headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key,
            "Content-Type": "application/json",
        }

    async def submit_order(self, request: OrderRequest, limit_price_override: float | None = None) -> ExecutedOrder:
        payload = self._build_order_payload(request, limit_price_override)
        
        try:
            response = await to_thread(self._post_json, f"{self.base_url}/v2/orders", payload)
            
            if response.status != 200:
                error_body = response.read().decode("utf-8")
                raise ValueError(f"Alpaca order submission failed: {response.status} {error_body}")
            
            body = json.loads(response.read().decode("utf-8"))
            return self._parse_order_response(body, request)
        except Exception as e:
            raise RuntimeError(f"Order submission error for {request.symbol}: {str(e)}")

    async def get_order(self, order_id: str) -> ExecutedOrder | None:
        try:
            response = await to_thread(self._get_json, f"{self.base_url}/v2/orders/{order_id}")
            
            if response.status == 404:
                return None
            
            if response.status != 200:
                raise ValueError(f"Failed to fetch order: {response.status}")
            
            body = json.loads(response.read().decode("utf-8"))
            return self._parse_order_response_simple(body)
        except Exception as e:
            raise RuntimeError(f"Order fetch error: {str(e)}")

    async def cancel_order(self, order_id: str) -> bool:
        try:
            response = await to_thread(self._delete_request, f"{self.base_url}/v2/orders/{order_id}")
            
            if response.status == 204:
                return True
            
            if response.status == 404:
                return False
            
            raise ValueError(f"Cancel failed: {response.status}")
        except Exception as e:
            raise RuntimeError(f"Order cancellation error: {str(e)}")

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
                raise ValueError("Limit price required for limit orders")
            payload["limit_price"] = limit_price
        
        if request.stop_loss is not None:
            payload["stop_price"] = request.stop_loss.stop_price
        
        if request.take_profit is not None:
            payload["limit_price"] = request.take_profit.limit_price
        
        return payload

    def _parse_order_response(self, body: dict, request: OrderRequest) -> ExecutedOrder:
        order_id = body.get("id", "unknown")
        status_str = body.get("status", "pending")
        filled_qty = int(body.get("filled_qty", 0))
        filled_avg_price = body.get("filled_avg_price")
        
        submitted_at = datetime.fromisoformat(body.get("created_at", "").replace("Z", "+00:00")) if body.get("created_at") else datetime.now(timezone.utc)
        filled_at = None
        if body.get("filled_at"):
            filled_at = datetime.fromisoformat(body.get("filled_at", "").replace("Z", "+00:00"))
        
        status = self._map_status(status_str)
        
        slippage_bps = 0.0
        if filled_avg_price and request.order_type == OrderType.MARKET:
            if request.side == "buy":
                slippage_bps = ((filled_avg_price - request.limit_price) / request.limit_price * 10000) if request.limit_price else 0.0
            else:
                slippage_bps = ((request.limit_price - filled_avg_price) / request.limit_price * 10000) if request.limit_price else 0.0
        
        return ExecutedOrder(
            order_id=str(order_id),
            symbol=request.symbol,
            qty=request.qty,
            filled_qty=filled_qty,
            side=request.side,
            status=status,
            filled_avg_price=filled_avg_price,
            submitted_at=submitted_at,
            filled_at=filled_at,
            estimated_slippage_bps=slippage_bps,
        )

    def _parse_order_response_simple(self, body: dict) -> ExecutedOrder:
        order_id = body.get("id", "unknown")
        status_str = body.get("status", "pending")
        symbol = body.get("symbol", "UNKNOWN")
        qty = int(body.get("qty", 0))
        filled_qty = int(body.get("filled_qty", 0))
        side = body.get("side", "buy")
        filled_avg_price = body.get("filled_avg_price")
        
        submitted_at = datetime.fromisoformat(body.get("created_at", "").replace("Z", "+00:00")) if body.get("created_at") else datetime.now(timezone.utc)
        filled_at = None
        if body.get("filled_at"):
            filled_at = datetime.fromisoformat(body.get("filled_at", "").replace("Z", "+00:00"))
        
        status = self._map_status(status_str)
        
        return ExecutedOrder(
            order_id=str(order_id),
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
        status_mapping = {
            "pending": OrderStatus.PENDING,
            "accepted": OrderStatus.ACCEPTED,
            "filled": OrderStatus.FILLED,
            "partially_filled": OrderStatus.PARTIAL_FILL,
            "rejected": OrderStatus.REJECTED,
            "cancelled": OrderStatus.CANCELLED,
            "expired": OrderStatus.EXPIRED,
        }
        return status_mapping.get(status_str.lower(), OrderStatus.PENDING)

    def _post_json(self, url: str, payload: Mapping[str, object]) -> urllib.request.Response:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=self.headers,
            method="POST",
        )
        return urllib.request.urlopen(req)

    def _get_json(self, url: str) -> urllib.request.Response:
        req = urllib.request.Request(url, headers=self.headers, method="GET")
        return urllib.request.urlopen(req)

    def _delete_request(self, url: str) -> urllib.request.Response:
        req = urllib.request.Request(url, headers=self.headers, method="DELETE")
        return urllib.request.urlopen(req)


class ExecutionService:
    def __init__(
        self,
        client: AlpacaExecutionClient,
        max_slippage_bps: float = 50.0,
        require_position_check: bool = True,
    ) -> None:
        self.client = client
        self.max_slippage_bps = max_slippage_bps
        self.require_position_check = require_position_check

    async def execute_trade(
        self,
        request: OrderRequest,
        position_size_from_risk: int,
        entry_price_estimate: float,
        has_passed_all_checks: bool,
    ) -> tuple[bool, str, ExecutedOrder | None]:
        if not has_passed_all_checks:
            return False, "Trade rejected: failed validation/risk checks", None

        if request.qty != position_size_from_risk:
            return False, f"Order qty {request.qty} does not match risk-calculated position {position_size_from_risk}", None

        if entry_price_estimate <= 0:
            return False, "Invalid entry price estimate", None

        try:
            order = await self.client.submit_order(request)
        except RuntimeError as e:
            return False, f"Order submission failed: {str(e)}", None

        if order.status == OrderStatus.REJECTED:
            return False, f"Order rejected by broker: {order.symbol}", None

        if order.status == OrderStatus.CANCELLED:
            return False, f"Order cancelled: {order.symbol}", None

        if order.status == OrderStatus.EXPIRED:
            return False, f"Order expired: {order.symbol}", None

        if order.filled_qty > 0 and order.filled_avg_price is not None:
            if order.estimated_slippage_bps > self.max_slippage_bps:
                try:
                    await self.client.cancel_order(order.order_id)
                except RuntimeError:
                    pass
                return False, f"Slippage {order.estimated_slippage_bps:.1f} bps exceeds max {self.max_slippage_bps} bps", order

        return True, f"Order {order.order_id} submitted successfully", order

    async def check_order_status(self, order_id: str) -> ExecutedOrder | None:
        return await self.client.get_order(order_id)

    async def cancel_trade(self, order_id: str) -> bool:
        return await self.client.cancel_order(order_id)
