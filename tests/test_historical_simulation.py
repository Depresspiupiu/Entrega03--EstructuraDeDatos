import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from finance_app.historical_simulation import (
    HistoricalBar,
    HistoricalDataError,
    HistoricalPortfolioSimulation,
    SimulationCompleteError,
)
from finance_app.historical_sessions import HistoricalSessionError, HistoricalSessionStore


class HistoricalPortfolioSimulationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.history = {
            "AAPL": (
                HistoricalBar(date(2023, 1, 3), 100, 105, 99, 102),
                HistoricalBar(date(2023, 1, 4), 102, 106, 101, 104),
                HistoricalBar(date(2023, 1, 5), 104, 105, 100, 101),
            ),
            "PEP": (
                HistoricalBar(date(2023, 1, 3), 200, 205, 198, 202),
                HistoricalBar(date(2023, 1, 4), 202, 207, 201, 206),
                HistoricalBar(date(2023, 1, 5), 206, 207, 200, 201),
            ),
        }

    def test_equal_investment_starts_at_initial_capital_and_advances_daily(self) -> None:
        simulation = HistoricalPortfolioSimulation(
            self.history,
            ("AAPL", "PEP"),
            100_000,
            date(2023, 1, 3),
            seed=7,
        )

        self.assertEqual(simulation.current_date, date(2023, 1, 3))
        self.assertAlmostEqual(simulation.current_value, 100_000)
        self.assertEqual(len(simulation.candles), 1)

        candle = simulation.advance()

        self.assertEqual(candle.day, date(2023, 1, 4))
        self.assertGreater(simulation.current_value, 100_000)
        self.assertGreaterEqual(candle.high, max(candle.open, candle.close))
        self.assertLessEqual(candle.low, min(candle.open, candle.close))
        self.assertAlmostEqual(simulation.candles[-1].close, simulation.current_value)

    def test_simulation_stops_at_last_historical_day(self) -> None:
        simulation = HistoricalPortfolioSimulation(
            self.history,
            ("AAPL",),
            100_000,
            date(2023, 1, 3),
            seed=1,
        )

        simulation.advance()
        simulation.advance()

        self.assertTrue(simulation.is_complete)
        with self.assertRaises(SimulationCompleteError):
            simulation.advance()

    def test_requires_common_dates_and_a_remaining_trading_day(self) -> None:
        misaligned = {
            "AAPL": self.history["AAPL"],
            "PEP": (
                HistoricalBar(date(2023, 1, 4), 202, 207, 201, 206),
                HistoricalBar(date(2023, 1, 5), 206, 207, 200, 201),
            ),
        }
        with self.assertRaises(HistoricalDataError):
            HistoricalPortfolioSimulation(
                misaligned, ("AAPL", "PEP"), 100, date(2023, 1, 3), seed=1
            )
        with self.assertRaises(HistoricalDataError):
            HistoricalPortfolioSimulation(
                self.history, ("AAPL",), 100, date(2023, 1, 5), seed=1
            )

    def test_rejects_empty_selection_and_invalid_capital(self) -> None:
        with self.assertRaises(ValueError):
            HistoricalPortfolioSimulation(
                self.history, (), 100, date(2023, 1, 3), seed=1
            )
        with self.assertRaises(ValueError):
            HistoricalPortfolioSimulation(
                self.history, ("AAPL",), 0, date(2023, 1, 3), seed=1
            )

    def test_random_starting_holdings_and_trades_update_cash_and_positions(self) -> None:
        simulation = HistoricalPortfolioSimulation(
            self.history,
            ("AAPL", "PEP"),
            100_000,
            date(2023, 1, 3),
            seed=13,
            random_initial_holdings=True,
        )
        initial_total = simulation.current_value
        initial_cash = simulation.cash_balance
        initial_holdings = simulation.holdings

        self.assertTrue(
            all(0 <= quantity <= 50 for quantity in initial_holdings.values())
        )
        self.assertAlmostEqual(initial_total, 100_000)

        bought = simulation.trade("AAPL", "COMPRA", 2)

        self.assertEqual(simulation.holdings["AAPL"], initial_holdings["AAPL"] + 2)
        self.assertAlmostEqual(
            simulation.cash_balance, initial_cash - bought.total
        )
        self.assertAlmostEqual(simulation.current_value, initial_total)
        self.assertEqual(simulation.trades, (bought,))

        sold = simulation.trade("AAPL", "VENTA", 2)
        self.assertEqual(simulation.holdings, initial_holdings)
        self.assertAlmostEqual(simulation.cash_balance, initial_cash)
        self.assertEqual(simulation.trades, (bought, sold))

    def test_can_trade_market_company_without_initial_random_holdings(self) -> None:
        simulation = HistoricalPortfolioSimulation(
            self.history,
            ("AAPL", "PEP"),
            100_000,
            date(2023, 1, 3),
            seed=13,
            initial_random_symbols=("AAPL",),
        )

        self.assertEqual(simulation.holdings["PEP"], 0)
        purchase = simulation.trade("PEP", "COMPRA", 3)

        self.assertEqual(purchase.symbol, "PEP")
        self.assertEqual(simulation.holdings["PEP"], 3)
        self.assertEqual(simulation.trades, (purchase,))

    def test_trade_rejects_insufficient_cash_and_unowned_shares(self) -> None:
        simulation = HistoricalPortfolioSimulation(
            self.history,
            ("AAPL",),
            1,
            date(2023, 1, 3),
            initial_holdings={"AAPL": 0},
            seed=1,
        )

        with self.assertRaisesRegex(ValueError, "Saldo insuficiente"):
            simulation.trade("AAPL", "COMPRA", 1)
        with self.assertRaisesRegex(ValueError, "No tienes suficientes"):
            simulation.trade("AAPL", "VENTA", 1)
        with self.assertRaises(ValueError):
            simulation.trade("AAPL", "COMPRA", 51)

    def test_export_and_restore_preserve_history_trades_and_random_sequence(self) -> None:
        simulation = HistoricalPortfolioSimulation(
            self.history,
            ("AAPL", "PEP"),
            100_000,
            date(2023, 1, 3),
            seed=23,
            random_initial_holdings=True,
            market="NASDAQ",
        )
        simulation.trade("AAPL", "COMPRA", 1)
        simulation.advance()
        restored = HistoricalPortfolioSimulation.from_state(
            json.loads(json.dumps(simulation.export_state()))
        )

        self.assertEqual(restored.current_date, simulation.current_date)
        self.assertEqual(restored.holdings, simulation.holdings)
        self.assertEqual(restored.trades, simulation.trades)
        self.assertEqual(restored.candles, simulation.candles)
        self.assertEqual(restored.price_candles("AAPL"), simulation.price_candles("AAPL"))

        next_original = simulation.advance()
        next_restored = restored.advance()
        self.assertEqual(next_restored, next_original)
        self.assertEqual(restored.prices, simulation.prices)


class HistoricalSessionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = HistoricalSessionStore(
            Path(self.temp_dir.name) / "simulation.sqlite3"
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_saves_and_loads_named_sessions(self) -> None:
        self.store.save("Primera sesión", {"market": "NASDAQ", "cash": 100000})

        self.assertEqual(
            self.store.load("Primera sesión"),
            {"market": "NASDAQ", "cash": 100000},
        )
        self.assertEqual(
            [name for name, _ in self.store.list_sessions()],
            ["Primera sesión"],
        )

    def test_rejects_missing_or_invalid_session_names(self) -> None:
        with self.assertRaises(HistoricalSessionError):
            self.store.load("No existe")
        with self.assertRaises(HistoricalSessionError):
            self.store.save("  ", {})


if __name__ == "__main__":
    unittest.main()
