from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Iterable, Mapping

import base64
import binascii
import os
import secrets

import pyotp
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import load_settings
from app.models import Base, BaseRules, DashboardSecret, Symbol
from app.services.symbols import SymbolService


@dataclass(frozen=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Trade:
    symbol: str
    side: str
    quantity: int
    price: float
    realized_pnl: float
    status: str
    timestamp: datetime


class DashboardDataSource:
    def candles(self) -> Iterable[Candle]:
        raise NotImplementedError

    def trades(self) -> Iterable[Trade]:
        raise NotImplementedError

    def stats(self) -> Mapping[str, float]:
        raise NotImplementedError

    def drawdowns(self) -> Iterable[tuple[datetime, float]]:
        raise NotImplementedError

    def strategy_performance(self) -> Iterable[Mapping[str, float | str]]:
        raise NotImplementedError

    def symbol_performance(self) -> Iterable[Mapping[str, float | str]]:
        raise NotImplementedError


class SampleDataSource(DashboardDataSource):
    def __init__(self) -> None:
        now = datetime.now(timezone.utc)
        base_time = now - timedelta(minutes=60)
        self._candles = []
        price = 100.0
        for i in range(60):
            ts = base_time + timedelta(minutes=i)
            move = ((i % 7) - 3) * 0.2
            open_price = price
            close_price = price + move
            high_price = max(open_price, close_price) + 0.4
            low_price = min(open_price, close_price) - 0.4
            volume = 5000 + i * 15
            self._candles.append(Candle(ts, open_price, high_price, low_price, close_price, volume))
            price = close_price
        self._trades = [
            Trade("AAPL", "buy", 50, 102.5, 125.0, "closed", now - timedelta(minutes=45)),
            Trade("MSFT", "sell", 30, 98.2, -45.0, "closed", now - timedelta(minutes=30)),
            Trade("NVDA", "buy", 20, 110.0, 0.0, "open", now - timedelta(minutes=10)),
        ]
        self._stats = {
            "win_rate": 0.6,
            "loss_rate": 0.4,
            "realized_pnl": 80.0,
            "unrealized_pnl": 35.0,
            "current_drawdown": 0.04,
            "max_drawdown": 0.09,
            "trades": 25,
        }
        self._drawdowns = []
        for i in range(60):
            ts = base_time + timedelta(minutes=i)
            dd = max(0.0, 0.1 - i * 0.0015)
            self._drawdowns.append((ts, dd))
        self._strategy_performance = [
            {"strategy": "Breakout", "win_rate": 0.58, "pnl": 120.0, "trades": 12},
            {"strategy": "Mean Revert", "win_rate": 0.62, "pnl": 95.0, "trades": 9},
            {"strategy": "Momentum", "win_rate": 0.55, "pnl": 60.0, "trades": 4},
        ]
        self._symbol_performance = [
            {"symbol": "AAPL", "pnl": 140.0, "win_rate": 0.64, "trades": 8},
            {"symbol": "MSFT", "pnl": -20.0, "win_rate": 0.48, "trades": 6},
            {"symbol": "NVDA", "pnl": 70.0, "win_rate": 0.6, "trades": 5},
            {"symbol": "TSLA", "pnl": -15.0, "win_rate": 0.4, "trades": 3},
        ]

    def candles(self) -> Iterable[Candle]:
        return list(self._candles)

    def trades(self) -> Iterable[Trade]:
        return list(self._trades)

    def stats(self) -> Mapping[str, float]:
        return dict(self._stats)

    def drawdowns(self) -> Iterable[tuple[datetime, float]]:
        return list(self._drawdowns)

    def strategy_performance(self) -> Iterable[Mapping[str, float | str]]:
        return list(self._strategy_performance)

    def symbol_performance(self) -> Iterable[Mapping[str, float | str]]:
        return list(self._symbol_performance)


def _serialize_candle(candle: Candle) -> Mapping[str, float | str]:
    return {
        "t": candle.timestamp.isoformat(),
        "o": candle.open,
        "h": candle.high,
        "l": candle.low,
        "c": candle.close,
        "v": candle.volume,
    }


def _serialize_trade(trade: Trade) -> Mapping[str, float | str]:
    return {
        "symbol": trade.symbol,
        "side": trade.side,
        "quantity": trade.quantity,
        "price": trade.price,
        "realized_pnl": trade.realized_pnl,
        "status": trade.status,
        "timestamp": trade.timestamp.isoformat(),
    }


def create_dashboard_app(data_source: DashboardDataSource | None = None) -> Flask:
    settings = load_settings()
    source = data_source or SampleDataSource()
    app = Flask(__name__, template_folder="templates", static_folder="static")
    session_secret_env = os.environ.get("DASHBOARD_SESSION_SECRET")
    otp_secret_env = os.environ.get("DASHBOARD_OTP_SECRET")
    created_secret = False
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SECURE"] = False
    app.config["API_BASE_URL"] = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")

    engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    Base.metadata.create_all(engine)

    def get_session() -> Session:
        return SessionLocal()

    def normalize_otp_secret(raw_secret: str | None) -> str:
        if not raw_secret:
            return pyotp.random_base32()
        try:
            base64.b32decode(raw_secret, casefold=True)
            return raw_secret
        except (binascii.Error, ValueError):
            return pyotp.random_base32()

    def get_or_create_secrets() -> tuple[DashboardSecret, bool]:
        db = get_session()
        record = db.query(DashboardSecret).order_by(DashboardSecret.id.asc()).first()
        if record:
            normalized_secret = normalize_otp_secret(record.otp_secret)
            if normalized_secret != record.otp_secret:
                record.otp_secret = normalized_secret
                db.add(record)
                db.commit()
                db.refresh(record)
            db.close()
            return record, False
        session_secret_val = session_secret_env or settings.jwt_secret or secrets.token_urlsafe(32)
        otp_secret_val = normalize_otp_secret(otp_secret_env)
        record = DashboardSecret(session_secret=session_secret_val, otp_secret=otp_secret_val)
        db.add(record)
        db.commit()
        db.refresh(record)
        db.close()
        return record, True

    secrets_record, created_secret = get_or_create_secrets()
    app.secret_key = secrets_record.session_secret
    otp_secret = secrets_record.otp_secret
    provisioning_uri = pyotp.TOTP(otp_secret).provisioning_uri(name="dashboard", issuer_name=settings.otp_issuer_name)
    app.config["SHOW_OTP_SECRET"] = created_secret
    app.config["OTP_PROVISIONING_URI"] = provisioning_uri
    app.config["OTP_SECRET"] = otp_secret

    def require_auth(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if settings.app_env == "test":
                return fn(*args, **kwargs)
            if not session.get("dashboard_auth"):
                return redirect(url_for("login"))
            return fn(*args, **kwargs)

        return wrapper

    @app.route("/")
    @require_auth
    def index():
        return render_template("dashboard.html", api_base_url=app.config["API_BASE_URL"])

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            code = request.form.get("code", "")
            totp = pyotp.TOTP(app.config["OTP_SECRET"])
            if not totp.verify(code, valid_window=1):
                return render_template(
                    "login.html",
                    error="invalid_code",
                    show_secret=False,
                    otp_secret=None,
                    provisioning_uri=None,
                )
            session["dashboard_auth"] = True
            return redirect(url_for("index"))
        show_link = False
        if not session.get("otp_link_seen") and app.config.get("OTP_PROVISIONING_URI"):
            show_link = True
            session["otp_link_seen"] = True
        return render_template(
            "login.html",
            error=None,
            show_secret=show_link,
            otp_secret=app.config.get("OTP_SECRET") if show_link else None,
            provisioning_uri=app.config.get("OTP_PROVISIONING_URI") if show_link else None,
        )

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/api/candles")
    @require_auth
    def candles():
        payload = [_serialize_candle(c) for c in source.candles()]
        return jsonify(payload)

    @app.route("/api/trades")
    @require_auth
    def trades():
        payload = [_serialize_trade(t) for t in source.trades()]
        return jsonify(payload)

    @app.route("/api/stats")
    @require_auth
    def stats():
        return jsonify(source.stats())

    @app.route("/api/drawdown")
    @require_auth
    def drawdown():
        payload = [{"t": ts.isoformat(), "dd": dd} for ts, dd in source.drawdowns()]
        return jsonify(payload)

    @app.route("/api/strategy-performance")
    @require_auth
    def strategy_performance():
        return jsonify(list(source.strategy_performance()))

    @app.route("/api/symbol-performance")
    @require_auth
    def symbol_performance():
        return jsonify(list(source.symbol_performance()))

    @app.route("/api/admin/symbols", methods=["GET"])
    @require_auth
    def list_symbols():
        db = get_session()
        service = SymbolService(db)
        items = service.list_symbols(only_enabled=False)
        db.close()
        return jsonify([{"symbol": s.symbol, "enabled": s.enabled} for s in items])

    @app.route("/api/admin/symbols", methods=["POST"])
    @require_auth
    def add_symbol():
        data = request.get_json(force=True)
        symbol = data.get("symbol", "") if isinstance(data, dict) else ""
        db = get_session()
        service = SymbolService(db)
        try:
            obj = service.add_symbol(symbol)
        except ValueError as exc:
            message = str(exc).lower()
            if "already exists" in message:
                obj = service.set_enabled(symbol, True)
            else:
                db.close()
                return jsonify({"error": "invalid_symbol"}), 400
        db.close()
        return jsonify({"symbol": obj.symbol, "enabled": obj.enabled})

    @app.route("/api/admin/symbols/<symbol>", methods=["PATCH"])
    @require_auth
    def update_symbol(symbol: str):
        data = request.get_json(force=True)
        enabled = bool(data.get("enabled", True)) if isinstance(data, dict) else True
        db = get_session()
        service = SymbolService(db)
        try:
            obj = service.set_enabled(symbol, enabled)
        except Exception:
            db.close()
            return jsonify({"error": "not_found"}), 404
        db.close()
        return jsonify({"symbol": obj.symbol, "enabled": obj.enabled})

    @app.route("/api/admin/symbols/<symbol>", methods=["DELETE"])
    @require_auth
    def delete_symbol(symbol: str):
        db = get_session()
        service = SymbolService(db)
        try:
            service.remove_symbol(symbol)
        except Exception:
            db.close()
            return jsonify({"error": "not_found"}), 404
        db.close()
        return jsonify({"deleted": symbol.upper()})

    @app.route("/api/admin/rules", methods=["GET"])
    @require_auth
    def get_rules():
        db = get_session()
        rules = db.query(BaseRules).order_by(BaseRules.id.asc()).first()
        if not rules:
            rules = BaseRules()
            db.add(rules)
            db.commit()
            db.refresh(rules)
        payload = {
            "max_risk_per_trade": rules.max_risk_per_trade,
            "max_daily_loss": rules.max_daily_loss,
            "max_trades_per_day": rules.max_trades_per_day,
            "cooldown_seconds": rules.cooldown_seconds,
        }
        db.close()
        return jsonify(payload)

    @app.route("/api/admin/rules", methods=["PUT"])
    @require_auth
    def update_rules():
        data = request.get_json(force=True) or {}
        db = get_session()
        rules = db.query(BaseRules).order_by(BaseRules.id.asc()).first()
        if not rules:
            rules = BaseRules()
            db.add(rules)
        try:
            rules.max_risk_per_trade = float(data.get("max_risk_per_trade", rules.max_risk_per_trade))
            rules.max_daily_loss = float(data.get("max_daily_loss", rules.max_daily_loss))
            rules.max_trades_per_day = int(data.get("max_trades_per_day", rules.max_trades_per_day))
            rules.cooldown_seconds = int(data.get("cooldown_seconds", rules.cooldown_seconds))
        except Exception:
            db.rollback()
            db.close()
            return jsonify({"error": "invalid_payload"}), 400
        db.commit()
        db.refresh(rules)
        payload = {
            "max_risk_per_trade": rules.max_risk_per_trade,
            "max_daily_loss": rules.max_daily_loss,
            "max_trades_per_day": rules.max_trades_per_day,
            "cooldown_seconds": rules.cooldown_seconds,
        }
        db.close()
        return jsonify(payload)

    return app
