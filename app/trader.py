from __future__ import annotations

import asyncio
import logging
import os
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import load_settings
from app.logging import log_decision
from app.models import Base, Symbol, BaseRules
from app.services import TradingOrchestrator, build_trading_orchestrator

logger = logging.getLogger("broker.trader")


def should_allow_execution(trading_mode: str, trading_live_confirm: bool) -> bool:
    if trading_mode == "live":
        return trading_live_confirm
    return True


def _symbols_from_env(env_value: str | None) -> list[str]:
    if not env_value:
        return []
    return [s.strip().upper() for s in env_value.split(",") if s.strip()]


def _load_symbols(session: Session, env_symbols: Iterable[str]) -> list[str]:
    symbols: list[str] = []
    if env_symbols:
        symbols.extend([s for s in env_symbols if s])
    stmt = select(Symbol).where(Symbol.enabled.is_(True)).order_by(Symbol.symbol)
    rows = session.scalars(stmt).all()
    symbols.extend([row.symbol for row in rows])
    return list(dict.fromkeys(symbols))


def _build_orchestrator(settings, session: Session, allow_execution: bool, budget: float | None = None) -> TradingOrchestrator:
    return build_trading_orchestrator(settings, session, allow_execution=allow_execution, budget=budget)


async def _run_once(orchestrator: TradingOrchestrator, symbols: list[str], use_extended_hours: bool) -> None:
    for symbol in symbols:
        try:
            await orchestrator.run(symbol, execute=True, use_extended_hours=use_extended_hours)
        except Exception as exc:
            log_decision(symbol, "trader", "error", str(exc))


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings()
    allow_exec = should_allow_execution(settings.trading_mode, settings.trading_live_confirm)
    poll_seconds = int(os.environ.get("TRADER_POLL_INTERVAL", "60"))
    env_symbols = _symbols_from_env(os.environ.get("TRADER_SYMBOLS"))
    use_extended_hours = str(os.environ.get("TRADER_USE_EXTENDED_HOURS", "false")).strip().lower() in ("1", "true", "yes")

    engine = None
    SessionLocal = None
    orchestrator = None

    while True:
        try:
            if engine is None:
                from sqlalchemy import create_engine

                engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
                SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
            with SessionLocal() as session:
                symbols = _load_symbols(session, env_symbols)
                rules = session.query(BaseRules).order_by(BaseRules.id.asc()).first()
                if not rules:
                    rules = BaseRules()
                    session.add(rules)
                    session.commit()
                    session.refresh(rules)
                if not symbols:
                    log_decision("system", "trader", "noop", "no_symbols")
                else:
                    orchestrator = orchestrator or _build_orchestrator(
                        settings,
                        session,
                        allow_execution=allow_exec,
                        budget=rules.budget,
                    )
                    logger.info("trader cycle start", extra={"symbols": symbols, "budget": rules.budget, "mode": settings.trading_mode})
                    await _run_once(orchestrator, symbols, use_extended_hours)
        except Exception as exc:
            log_decision("system", "trader", "error", str(exc))
        await asyncio.sleep(poll_seconds)


if __name__ == "__main__":
    asyncio.run(main())
