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
from flask_wtf.csrf import CSRFProtect, generate_csrf
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import load_settings
from app.models import Base, BaseRules, DashboardSecret, OrderLog, Symbol, TradeOutcomeLog
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


class DatabaseDataSource(DashboardDataSource):
    def __init__(self, session_factory: sessionmaker) -> None:
        self.session_factory = session_factory

    def candles(self) -> Iterable[Candle]:
        return []

    def trades(self) -> Iterable[Trade]:
        session = self.session_factory()
        try:
            orders = (
                session.query(OrderLog)
                .order_by(OrderLog.created_at.desc())
                .limit(50)
                .all()
            )
            outcomes = session.query(TradeOutcomeLog).order_by(TradeOutcomeLog.created_at.desc()).all()
        finally:
            session.close()
        if not orders:
            return []
        outcome_by_order: dict[str, TradeOutcomeLog] = {}
        for outcome in outcomes:
            if outcome.order_id not in outcome_by_order:
                outcome_by_order[outcome.order_id] = outcome
        trades = []
        for order in orders:
            outcome = outcome_by_order.get(order.order_id)
            realized_pnl = outcome.pnl if outcome else 0.0
            status = outcome.outcome if outcome else order.status
            timestamp = order.filled_at or order.submitted_at or order.created_at
            qty = order.filled_qty if order.filled_qty else order.qty
            price = order.filled_avg_price if order.filled_avg_price is not None else 0.0
            trades.append(Trade(order.symbol, order.side, qty, price, realized_pnl, status, timestamp))
        return trades

    def stats(self) -> Mapping[str, float]:
        session = self.session_factory()
        try:
            outcomes = session.query(TradeOutcomeLog).order_by(TradeOutcomeLog.created_at.asc()).all()
        finally:
            session.close()
        if not outcomes:
            return {
                "win_rate": 0.0,
                "loss_rate": 0.0,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
                "current_drawdown": 0.0,
                "max_drawdown": 0.0,
                "trades": 0,
            }
        realized = sum(outcome.pnl for outcome in outcomes)
        wins = sum(1 for outcome in outcomes if outcome.pnl > 0)
        total = len(outcomes)
        equity_curve = self._equity_curve(outcomes)
        current_drawdown, max_drawdown = self._drawdown_metrics(equity_curve)
        loss_rate = (total - wins) / total if total else 0.0
        win_rate = wins / total if total else 0.0
        return {
            "win_rate": win_rate,
            "loss_rate": loss_rate,
            "realized_pnl": realized,
            "unrealized_pnl": 0.0,
            "current_drawdown": current_drawdown,
            "max_drawdown": max_drawdown,
            "trades": total,
        }

    def drawdowns(self) -> Iterable[tuple[datetime, float]]:
        session = self.session_factory()
        try:
            outcomes = session.query(TradeOutcomeLog).order_by(TradeOutcomeLog.created_at.asc()).all()
        finally:
            session.close()
        if not outcomes:
            return []
        equity_curve = self._equity_curve(outcomes)
        series = []
        peak = 0.0
        for timestamp, equity in equity_curve:
            if equity > peak:
                peak = equity
            drawdown = 0.0 if peak <= 0 else max(0.0, (peak - equity) / peak)
            series.append((timestamp, drawdown))
        return series

    def strategy_performance(self) -> Iterable[Mapping[str, float | str]]:
        return []

    def symbol_performance(self) -> Iterable[Mapping[str, float | str]]:
        session = self.session_factory()
        try:
            outcomes = session.query(TradeOutcomeLog).order_by(TradeOutcomeLog.created_at.desc()).all()
        finally:
            session.close()
        if not outcomes:
            return []
        data: dict[str, dict[str, float]] = {}
        for outcome in outcomes:
            record = data.setdefault(outcome.symbol, {"pnl": 0.0, "wins": 0.0, "total": 0.0})
            record["pnl"] += outcome.pnl
            record["total"] += 1
            if outcome.pnl > 0:
                record["wins"] += 1
        result = []
        for symbol, record in data.items():
            win_rate = record["wins"] / record["total"] if record["total"] else 0.0
            result.append(
                {
                    "symbol": symbol,
                    "pnl": record["pnl"],
                    "win_rate": win_rate,
                    "trades": int(record["total"]),
                }
            )
        return result

    def _equity_curve(self, outcomes: Iterable[TradeOutcomeLog]) -> list[tuple[datetime, float]]:
        equity = 0.0
        curve = []
        for outcome in outcomes:
            equity += outcome.pnl
            curve.append((outcome.created_at, equity))
        return curve

    def _drawdown_metrics(self, curve: Iterable[tuple[datetime, float]]) -> tuple[float, float]:
        peak = 0.0
        current = 0.0
        maximum = 0.0
        for _, equity in curve:
            if equity > peak:
                peak = equity
            drawdown = 0.0 if peak <= 0 else max(0.0, (peak - equity) / peak)
            current = drawdown
            if drawdown > maximum:
                maximum = drawdown
        return current, maximum


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
    source = data_source
    app = Flask(__name__, template_folder="templates", static_folder="static")
    session_secret_env = os.environ.get("DASHBOARD_SESSION_SECRET")
    otp_secret_env = os.environ.get("DASHBOARD_OTP_SECRET")
    created_secret = False
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SECURE"] = settings.app_env != "test"
    app.config["SESSION_COOKIE_SAMESITE"] = "Strict"
    app.config["PERMANENT_SESSION_LIFETIME"] = 900

    engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    Base.metadata.create_all(engine)
    csrf = CSRFProtect(app)

    resolved_source = source or DatabaseDataSource(SessionLocal)

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
        env_otp_secret = None
        if otp_secret_env and otp_secret_env.strip():
            env_otp_secret = normalize_otp_secret(otp_secret_env)
        record = db.query(DashboardSecret).order_by(DashboardSecret.id.asc()).first()
        if record:
            current_secret = record.otp_secret
            target_secret = env_otp_secret or normalize_otp_secret(current_secret)
            if target_secret != current_secret:
                record.otp_secret = target_secret
                db.add(record)
                db.commit()
                db.refresh(record)
            db.close()
            return record, False
        session_secret_val = session_secret_env or settings.jwt_secret or secrets.token_urlsafe(32)
        otp_secret_val = env_otp_secret or normalize_otp_secret(None)
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

    def require_admin(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if settings.app_env == "test":
                return fn(*args, **kwargs)
            if not session.get("dashboard_auth") or not session.get("is_admin"):
                return jsonify({"error": "unauthorized"}), 403
            return fn(*args, **kwargs)

        return wrapper

    @app.route("/")
    @require_auth
    def index():
        return render_template("dashboard.html")

    @app.route("/login", methods=["GET", "POST"])
    @csrf.exempt
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
                    csrf_token=None,
                )
            session["dashboard_auth"] = True
            session["is_admin"] = True
            session.permanent = True
            return redirect(url_for("index"))
        db = get_session()
        record = db.query(DashboardSecret).order_by(DashboardSecret.id.asc()).first()
        show_link = False
        if record and not record.provisioning_link_shown and app.config.get("OTP_PROVISIONING_URI"):
            show_link = True
            record.provisioning_link_shown = True
            db.commit()
        db.close()
        csrf_token = None
        if settings.app_env != "test":
            csrf_token = generate_csrf()
        return render_template(
            "login.html",
            error=None,
            show_secret=show_link,
            otp_secret=app.config.get("OTP_SECRET") if show_link else None,
            provisioning_uri=app.config.get("OTP_PROVISIONING_URI") if show_link else None,
            csrf_token=csrf_token,
        )

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.before_request
    def before_request():
        if settings.app_env != "test":
            pass

    @app.after_request
    def after_request(response):
        if settings.app_env != "test":
            response.set_cookie(
                "XSRF-TOKEN",
                generate_csrf(),
                secure=settings.app_env != "development",
                httponly=False,
                samesite="Strict",
            )
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.route("/api/candles")
    @require_auth
    def candles():
        payload = [_serialize_candle(c) for c in resolved_source.candles()]
        return jsonify(payload)

    @app.route("/api/trades")
    @require_auth
    def trades():
        payload = [_serialize_trade(t) for t in resolved_source.trades()]
        return jsonify(payload)

    @app.route("/api/stats")
    @require_auth
    def stats():
        return jsonify(resolved_source.stats())

    @app.route("/api/drawdown")
    @require_auth
    def drawdown():
        payload = [{"t": ts.isoformat(), "dd": dd} for ts, dd in resolved_source.drawdowns()]
        return jsonify(payload)

    @app.route("/api/strategy-performance")
    @require_auth
    def strategy_performance():
        return jsonify(list(resolved_source.strategy_performance()))

    @app.route("/api/symbol-performance")
    @require_auth
    def symbol_performance():
        return jsonify(list(resolved_source.symbol_performance()))

    @app.route("/api/admin/symbols", methods=["GET"])
    @require_admin
    def list_symbols():
        db = get_session()
        service = SymbolService(db)
        items = service.list_symbols(only_enabled=False)
        db.close()
        return jsonify([{"symbol": s.symbol, "enabled": s.enabled} for s in items])

    @app.route("/api/admin/symbols", methods=["POST"])
    @require_admin
    @csrf.exempt
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
    @require_admin
    @csrf.exempt
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
    @require_admin
    @csrf.exempt
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
    @require_admin
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
            "budget": rules.budget,
        }
        db.close()
        return jsonify(payload)

    @app.route("/api/admin/rules", methods=["PUT"])
    @require_admin
    @csrf.exempt
    def update_rules():
        data = request.get_json(force=True) or {}
        db = get_session()
        rules = db.query(BaseRules).order_by(BaseRules.id.asc()).first()
        if not rules:
            rules = BaseRules()
            db.add(rules)
        try:
            max_risk = float(data.get("max_risk_per_trade", rules.max_risk_per_trade))
            max_loss = float(data.get("max_daily_loss", rules.max_daily_loss))
            max_trades = int(data.get("max_trades_per_day", rules.max_trades_per_day))
            cooldown = int(data.get("cooldown_seconds", rules.cooldown_seconds))
            budget = float(data.get("budget", rules.budget))
            if not (0 < max_risk < 0.5):
                return jsonify({"error": "max_risk_per_trade must be between 0 and 0.5"}), 400
            if not (0 < max_loss < 1.0):
                return jsonify({"error": "max_daily_loss must be between 0 and 1.0"}), 400
            if not (1 <= max_trades <= 1000):
                return jsonify({"error": "max_trades_per_day must be between 1 and 1000"}), 400
            if not (0 <= cooldown <= 3600):
                return jsonify({"error": "cooldown_seconds must be between 0 and 3600"}), 400
            if budget <= 0:
                return jsonify({"error": "budget must be greater than 0"}), 400
            rules.max_risk_per_trade = max_risk
            rules.max_daily_loss = max_loss
            rules.max_trades_per_day = max_trades
            rules.cooldown_seconds = cooldown
            rules.budget = budget
        except (ValueError, TypeError):
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
            "budget": rules.budget,
        }
        db.close()
        return jsonify(payload)

    return app
