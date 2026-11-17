import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import call, patch

from finance_app.historical_simulation import (
    AcceleratedSimulationClock,
    HistoricalBar,
    HistoricalDataError,
    HistoricalPortfolioSimulation,
    SimulationCompleteError,
    fetch_2023_history,
)
from finance_app.historical_sessions import HistoricalSessionError, HistoricalSessionStore
from finance_app.models import StockCandle


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

    def test_2023_history_uses_the_range_fetcher_for_selected_symbols(self) -> None:
        days = (date(2023, 1, 3), date(2023, 1, 4))

        def candles(base_price: float) -> tuple[StockCandle, ...]:
            return tuple(
                StockCandle(
                    day, base_price, base_price + 2, base_price - 1, base_price + 1
                )
                for day in days
            )

        with patch(
            "finance_app.market_data.YFinanceMarketData.get_history_range",
            side_effect=(candles(100), candles(200)),
        ) as get_history_range:
            history = fetch_2023_history(("KO", "NKE"))

        self.assertEqual(tuple(history), ("KO", "NKE"))
        self.assertEqual(history["KO"][0].day, days[0])
        self.assertEqual(history["KO"][0].close, 101)
        self.assertEqual(history["NKE"][0].close, 201)
        self.assertEqual(
            get_history_range.call_args_list,
            [
                call("KO", date(2023, 1, 1), date(2024, 1, 1)),
                call("NKE", date(2023, 1, 1), date(2024, 1, 1)),
            ],
        )

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

    def test_monthly_price_change_uses_last_close_on_or_before_same_day(self) -> None:
        simulation = HistoricalPortfolioSimulation(
            self.history,
            ("AAPL",),
            100_000,
            date(2023, 1, 3),
            end_date=date(2023, 2, 6),
            seed=7,
        )
        for _ in range(34):
            simulation.advance_calendar_day()

        change = simulation.monthly_price_change("AAPL")

        self.assertIsNotNone(change)
        assert change is not None
        self.assertEqual(change.reference_day, date(2023, 1, 5))
        reference_bar = simulation.price_candles("AAPL")[-1]
        self.assertEqual(change.reference_price, reference_bar.close)
        self.assertAlmostEqual(
            change.absolute_change,
            simulation.prices["AAPL"] - change.reference_price,
        )
        self.assertAlmostEqual(
            change.percent_change,
            change.absolute_change / change.reference_price * 100,
        )

    def test_monthly_price_change_is_unavailable_without_a_prior_month_quote(self) -> None:
        simulation = HistoricalPortfolioSimulation(
            self.history,
            ("AAPL",),
            100_000,
            date(2023, 1, 3),
            seed=7,
        )

        self.assertIsNone(simulation.monthly_price_change("AAPL"))

    def test_calendar_advances_from_january_first_and_carries_closed_day_prices(self) -> None:
        simulation = HistoricalPortfolioSimulation(
            self.history,
            ("AAPL", "PEP"),
            100_000,
            date(2023, 1, 1),
            end_date=date(2023, 1, 7),
            seed=7,
        )
        initial_value = simulation.current_value

        self.assertEqual(simulation.current_date, date(2023, 1, 1))
        self.assertEqual(simulation.candles[0].day, date(2023, 1, 1))

        for expected_day in (date(2023, 1, 2), date(2023, 1, 3)):
            candle = simulation.advance_calendar_day()
            self.assertEqual(candle.day, expected_day)
            self.assertEqual(candle.close, initial_value)
            self.assertEqual(len(simulation.price_candles("AAPL")), 1)

        simulation.advance_calendar_day()
        self.assertEqual(simulation.current_date, date(2023, 1, 4))
        self.assertEqual(len(simulation.price_candles("AAPL")), 2)

        restored = HistoricalPortfolioSimulation.from_state(
            json.loads(json.dumps(simulation.export_state()))
        )
        self.assertEqual(restored.current_date, date(2023, 1, 4))
        self.assertEqual(restored.candles, simulation.candles)
        self.assertEqual(
            restored.advance_calendar_day(), simulation.advance_calendar_day()
        )
        for expected_day in (date(2023, 1, 6), date(2023, 1, 7)):
            candle = simulation.advance_calendar_day()
            self.assertEqual(candle.day, expected_day)
            self.assertEqual(candle.close, simulation.candles[-2].close)
        self.assertTrue(simulation.is_complete)

    def test_accelerated_clock_advances_a_day_after_24_simulated_hours(self) -> None:
        clock = AcceleratedSimulationClock(date(2023, 1, 1))

        for expected_hour in range(1, 24):
            current_date, hour = clock.advance_hour()
            self.assertEqual(current_date, date(2023, 1, 1))
            self.assertEqual(hour, expected_hour)

        self.assertEqual(
            clock.advance_hour(), (date(2023, 1, 2), 0)
        )

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
            date(2023, 1, 1),
            end_date=date(2023, 1, 5),
            seed=13,
            initial_random_symbols=("AAPL",),
        )

        self.assertEqual(simulation.holdings["PEP"], 0)
        initial_cash = simulation.cash_balance
        purchase = simulation.trade("PEP", "COMPRA", 3)

        self.assertEqual(purchase.symbol, "PEP")
        self.assertEqual(purchase.day, date(2023, 1, 1))
        self.assertEqual(simulation.holdings["PEP"], 3)
        self.assertEqual(simulation.trades, (purchase,))
        self.assertEqual(
            simulation.candles[-1].open,
            simulation.candles[-1].close,
        )

        sale = simulation.trade("PEP", "VENTA", 1)

        self.assertEqual(sale.quantity, 1)
        self.assertEqual(simulation.holdings["PEP"], 2)
        self.assertEqual(
            simulation.cash_balance,
            initial_cash - purchase.total + sale.total,
        )

    def test_random_holdings_fit_within_smaller_starting_capital(self) -> None:
        simulation = HistoricalPortfolioSimulation(
            self.history,
            ("AAPL", "PEP"),
            1_000,
            date(2023, 1, 3),
            seed=13,
            random_initial_holdings=True,
        )

        self.assertGreaterEqual(simulation.cash_balance, 0)
        self.assertLessEqual(
            sum(
                simulation.holdings[symbol] * simulation.prices[symbol]
                for symbol in simulation.symbols
            ),
            1_000,
        )
        self.assertAlmostEqual(simulation.current_value, 1_000)

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

    def test_restores_sessions_without_calendar_clock_fields(self) -> None:
        simulation = HistoricalPortfolioSimulation(
            self.history,
            ("AAPL",),
            100_000,
            date(2023, 1, 3),
            seed=5,
        )
        simulation.advance()
        legacy_state = simulation.export_state()
        for key in ("calendar_mode", "current_date", "end_date"):
            legacy_state.pop(key)

        restored = HistoricalPortfolioSimulation.from_state(legacy_state)

        self.assertEqual(restored.current_date, date(2023, 1, 4))
        self.assertEqual(restored.candles, simulation.candles)


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
