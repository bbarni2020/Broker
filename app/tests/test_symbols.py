from __future__ import annotations

import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, Symbol
from app.services import SymbolService


class SymbolServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.service = SymbolService(self.session)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def test_add_symbol_uppercases_and_persists(self) -> None:
        created = self.service.add_symbol("aapl")
        self.assertEqual(created.symbol, "AAPL")
        self.assertTrue(created.enabled)
        stored = self.session.query(Symbol).filter_by(symbol="AAPL").one()
        self.assertEqual(stored.symbol, "AAPL")

    def test_add_symbol_duplicate_raises(self) -> None:
        self.service.add_symbol("msft")
        with self.assertRaises(ValueError):
            self.service.add_symbol("MSFT")

    def test_remove_symbol(self) -> None:
        self.service.add_symbol("nvda")
        self.service.remove_symbol("NVDA")
        self.assertFalse(self.service.exists("NVDA"))

    def test_disable_and_enable_symbol(self) -> None:
        self.service.add_symbol("goog")
        disabled = self.service.disable_symbol("GOOG")
        self.assertFalse(disabled.enabled)
        enabled = self.service.enable_symbol("GOOG")
        self.assertTrue(enabled.enabled)

    def test_exists_checks_presence(self) -> None:
        self.assertFalse(self.service.exists("tsla"))
        self.service.add_symbol("tsla")
        self.assertTrue(self.service.exists("TSLA"))

    def test_list_symbols_filters_enabled(self) -> None:
        self.service.add_symbol("spy")
        self.service.add_symbol("qqq", enabled=False)
        all_symbols = self.service.list_symbols()
        self.assertEqual([s.symbol for s in all_symbols], ["QQQ", "SPY"])
        enabled_only = self.service.list_symbols(only_enabled=True)
        self.assertEqual([s.symbol for s in enabled_only], ["SPY"])
