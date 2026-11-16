import math
import sys
import threading
import types
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from finance_app.market_data import YFinanceMarketData
from finance_app.models import StockCandle, StockSnapshot


class FakeHistory:
    columns = {"Open", "High", "Low", "Close"}

    def __init__(self, rows: list[tuple[datetime, dict[str, float]]]) -> None:
        self.rows = rows
        self.empty = not rows

    def iterrows(self):
        return iter(self.rows)


def _history(valid_rows: int, *, include_invalid: bool = False) -> FakeHistory:
    rows = []
    start = datetime(2026, 1, 1)
    if include_invalid:
        rows.append(
            (
                start,
                {"Open": math.nan, "High": 102, "Low": 99, "Close": 101},
            )
        )
    for index in range(valid_rows):
        close = 100.0 + index
        rows.append(
            (
                start + timedelta(days=index + int(include_invalid)),
                {
                    "Open": close - 0.5,
                    "High": close + 1,
                    "Low": close - 1,
                    "Close": close,
                },
            )
        )
    return FakeHistory(rows)


class MarketDataTests(unittest.TestCase):
    def _get_history(self, history: FakeHistory):
        module = types.ModuleType("yfinance")
        module.Ticker = lambda _symbol: types.SimpleNamespace(
            history=lambda **_kwargs: history
        )
        with patch.dict(sys.modules, {"yfinance": module}):
            return YFinanceMarketData().get_history("KO")

    def test_returns_snapshot_and_valid_daily_ohlc_candles(self) -> None:
        snapshot, candles = self._get_history(_history(64, include_invalid=True))

        self.assertEqual(snapshot.symbol, "KO")
        self.assertEqual(snapshot.price, 163.0)
        self.assertEqual(len(candles), 64)
        self.assertIsInstance(candles[0], StockCandle)
        self.assertEqual(candles[0].open, 99.5)
        self.assertEqual(candles[0].high, 101.0)
        self.assertEqual(candles[0].low, 99.0)
        self.assertEqual(candles[0].close, 100.0)

    def test_rejects_history_with_fewer_than_64_valid_candles(self) -> None:
        with self.assertRaisesRegex(ValueError, "64 velas diarias"):
            self._get_history(_history(63))

    def test_fetches_symbols_concurrently_and_preserves_input_order(self) -> None:
        barrier = threading.Barrier(2)

        class ConcurrentMarketData(YFinanceMarketData):
            def get_history(self, symbol: str, period: str = "6mo"):
                barrier.wait(timeout=2)
                return StockSnapshot(symbol, 100, 0, 0, 0), ()

        results, errors = ConcurrentMarketData().get_histories(("NKE", "KO"))

        self.assertEqual(list(results), ["NKE", "KO"])
        self.assertEqual(errors, [])

    def test_returns_partial_results_and_surfaces_symbol_errors(self) -> None:
        class PartiallyFailingMarketData(YFinanceMarketData):
            def get_history(self, symbol: str, period: str = "6mo"):
                if symbol == "NKE":
                    raise ValueError("NKE no disponible")
                return StockSnapshot(symbol, 100, 0, 0, 0), ()

        results, errors = PartiallyFailingMarketData().get_histories(
            ("KO", "NKE")
        )

        self.assertEqual(list(results), ["KO"])
        self.assertEqual(errors, ["NKE no disponible"])


if __name__ == "__main__":
    unittest.main()
