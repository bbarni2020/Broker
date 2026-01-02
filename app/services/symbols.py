from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.symbol import Symbol


class SymbolService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_symbol(self, symbol: str, enabled: bool = True) -> Symbol:
        normalized = symbol.strip().upper()
        if not normalized:
            raise ValueError("Symbol is required")
        existing = self.session.query(Symbol).filter_by(symbol=normalized).first()
        if existing:
            raise ValueError("Symbol already exists")
        obj = Symbol(symbol=normalized, enabled=enabled)
        self.session.add(obj)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ValueError("Symbol already exists") from exc
        self.session.refresh(obj)
        return obj

    def remove_symbol(self, symbol: str) -> None:
        normalized = symbol.strip().upper()
        obj = self.session.query(Symbol).filter_by(symbol=normalized).first()
        if not obj:
            raise ValueError("Symbol not found")
        self.session.delete(obj)
        self.session.commit()

    def set_enabled(self, symbol: str, enabled: bool) -> Symbol:
        normalized = symbol.strip().upper()
        obj = self.session.query(Symbol).filter_by(symbol=normalized).first()
        if not obj:
            raise ValueError("Symbol not found")
        obj.enabled = enabled
        self.session.commit()
        self.session.refresh(obj)
        return obj

    def enable_symbol(self, symbol: str) -> Symbol:
        return self.set_enabled(symbol, True)

    def disable_symbol(self, symbol: str) -> Symbol:
        return self.set_enabled(symbol, False)

    def exists(self, symbol: str) -> bool:
        normalized = symbol.strip().upper()
        if not normalized:
            return False
        return self.session.query(Symbol).filter_by(symbol=normalized).first() is not None

    def list_symbols(self, only_enabled: bool = False) -> list[Symbol]:
        query = self.session.query(Symbol)
        if only_enabled:
            query = query.filter_by(enabled=True)
        return list(query.order_by(Symbol.symbol).all())
