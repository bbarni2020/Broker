from __future__ import annotations

import unittest

from app.trader import should_allow_execution


class TraderExecutionTests(unittest.TestCase):
    def test_allows_paper(self) -> None:
        self.assertTrue(should_allow_execution("paper", False))

    def test_blocks_live_without_confirm(self) -> None:
        self.assertFalse(should_allow_execution("live", False))

    def test_allows_live_with_confirm(self) -> None:
        self.assertTrue(should_allow_execution("live", True))


if __name__ == "__main__":
    unittest.main()
