import tempfile
import unittest
import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path
from contextlib import closing

from finance_app.simulator import SimulationError, SimulationLedger


class SimulationLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database = Path(self.temp_dir.name) / "simulation.sqlite3"
        self.ledger = SimulationLedger(database, Decimal("1000"))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_buy_and_sell_update_simulated_cash_and_positions(self) -> None:
        self.ledger.trade("TEST", "COMPRA", "2", "100")

        self.assertEqual(self.ledger.cash_balance(), Decimal("800"))
        self.assertEqual(self.ledger.positions(), {"TEST": Decimal("2")})

        self.ledger.trade("TEST", "VENTA", "1", "120")

        self.assertEqual(self.ledger.cash_balance(), Decimal("920"))
        self.assertEqual(self.ledger.positions(), {"TEST": Decimal("1")})
        self.assertEqual(len(self.ledger.recent_trades()), 2)

    def test_rejects_buying_beyond_cash(self) -> None:
        with self.assertRaises(SimulationError):
            self.ledger.trade("TEST", "COMPRA", "11", "100")

        self.assertEqual(self.ledger.cash_balance(), Decimal("1000"))
        self.assertEqual(self.ledger.recent_trades(), [])

    def test_rejects_selling_shares_not_owned(self) -> None:
        with self.assertRaises(SimulationError):
            self.ledger.trade("TEST", "VENTA", "1", "100")

        self.assertEqual(self.ledger.recent_trades(), [])

    def test_records_fixed_income_trade_with_date_commission_and_currency(self) -> None:
        self.ledger.set_initial_cash("COP", "1000000")

        trade = self.ledger.trade(
            "TES 2033",
            "COMPRA",
            "2",
            "100000",
            asset_type="TES",
            operation_date="2026-10-15",
            commission="2500",
            currency="COP",
        )

        self.assertEqual(trade.operation_date, "2026-10-15")
        self.assertEqual(trade.asset_type, "TES")
        self.assertEqual(trade.commission, Decimal("2500"))
        self.assertEqual(trade.total, Decimal("200000"))
        self.assertEqual(self.ledger.cash_balance("COP"), Decimal("797500"))
        self.assertEqual(self.ledger.cash_balance("USD"), Decimal("1000"))
        self.assertEqual(self.ledger.positions()["TES: TES 2033 (COP)"], Decimal("2"))

        recorded = self.ledger.recent_trades()[0]
        self.assertEqual(recorded.operation_date, "2026-10-15")
        self.assertEqual(recorded.currency, "COP")
        self.assertEqual(recorded.commission, Decimal("2500"))

    def test_sell_applies_commission_and_restores_correct_currency_balance(self) -> None:
        self.ledger.set_initial_cash("COP", "1000000")
        self.ledger.trade(
            "CDT-1", "COMPRA", "1", "100000",
            asset_type="CDT", currency="COP", commission="100",
        )
        self.ledger.trade(
            "CDT-1", "VENTA", "1", "110000",
            asset_type="CDT", currency="COP", commission="200",
        )

        self.assertEqual(self.ledger.cash_balance("COP"), Decimal("1009700"))

    def test_income_valuation_and_portfolio_returns_include_fees(self) -> None:
        self.ledger.trade("TEST", "COMPRA", "2", "100", commission="5")
        self.ledger.update_valuation("TEST", "ACCIONES", "USD", "120")
        self.ledger.record_income(
            "TEST", "ACCIONES", "DIVIDENDO", "10", commission="1"
        )

        summary = self.ledger.portfolio_summary("USD")

        self.assertEqual(summary.cash_balance, Decimal("804"))
        self.assertEqual(summary.invested_value, Decimal("205"))
        self.assertEqual(summary.market_value, Decimal("240"))
        self.assertEqual(summary.total_value, Decimal("1044"))
        self.assertEqual(summary.equity_value, Decimal("240"))
        self.assertEqual(summary.fixed_income_value, Decimal("0"))
        self.assertEqual(summary.income_total, Decimal("10"))
        self.assertEqual(summary.costs_total, Decimal("6"))
        self.assertEqual(summary.cumulative_return_pct, Decimal("4.400"))
        self.assertEqual(summary.positions[0].unit_price, Decimal("120"))
        self.assertEqual(summary.positions[0].market_value, Decimal("240"))

    def test_fixed_income_terms_accrue_value_until_maturity(self) -> None:
        self.ledger.set_initial_cash("COP", "1000")
        self.ledger.trade(
            "CDT-1",
            "COMPRA",
            "1",
            "100",
            asset_type="CDT",
            operation_date="2025-01-01",
            currency="COP",
        )
        self.ledger.set_instrument_terms(
            "CDT-1", "CDT", "COP", "10", "2025-12-31"
        )

        summary = self.ledger.portfolio_summary("COP")

        self.assertGreater(summary.market_value, Decimal("109"))
        self.assertLess(summary.market_value, Decimal("111"))
        self.assertEqual(summary.fixed_income_value, summary.market_value)
        self.assertEqual(summary.equity_value, Decimal("0"))
        self.assertEqual(summary.positions[0].annual_rate_pct, Decimal("10"))
        self.assertEqual(summary.positions[0].maturity_date, "2025-12-31")

    def test_paid_fixed_income_interest_is_not_double_counted(self) -> None:
        self.ledger.set_initial_cash("COP", "1000")
        self.ledger.trade(
            "CDT-2",
            "COMPRA",
            "1",
            "100",
            asset_type="CDT",
            operation_date="2025-01-01",
            currency="COP",
        )
        self.ledger.set_instrument_terms(
            "CDT-2", "CDT", "COP", "10", "2030-01-01"
        )
        self.ledger.record_income(
            "CDT-2",
            "CDT",
            "INTERES",
            "5",
            operation_date="2025-07-01",
            currency="COP",
        )

        summary = self.ledger.portfolio_summary("COP")
        days = (date.today() - date(2025, 1, 1)).days
        expected_value = (
            Decimal("100")
            * (Decimal("1.1") ** (Decimal(days) / Decimal("365.25")))
            - Decimal("5")
        )

        self.assertAlmostEqual(
            float(summary.market_value), float(expected_value), places=5
        )

    def test_principal_payment_reduces_units_and_adds_net_cash(self) -> None:
        self.ledger.set_initial_cash("COP", "1000")
        self.ledger.trade(
            "TES-1", "COMPRA", "10", "10", asset_type="TES", currency="COP"
        )
        self.ledger.record_income(
            "TES-1",
            "TES",
            "PAGO_CAPITAL",
            "20",
            quantity="2",
            commission="1",
            currency="COP",
        )

        self.assertEqual(
            self.ledger.positions()["TES: TES-1 (COP)"], Decimal("8")
        )
        self.assertEqual(self.ledger.cash_balance("COP"), Decimal("919"))
        summary = self.ledger.portfolio_summary("COP")
        self.assertEqual(summary.income_total, Decimal("20"))
        self.assertEqual(summary.invested_value, Decimal("80"))

    def test_rejects_income_for_unowned_assets_and_excess_principal(self) -> None:
        with self.assertRaises(SimulationError):
            self.ledger.record_income("TEST", "ACCIONES", "DIVIDENDO", "1")

        self.ledger.trade("TES-1", "COMPRA", "1", "10", asset_type="TES")
        with self.assertRaises(SimulationError):
            self.ledger.record_income(
                "TES-1", "TES", "PAGO_CAPITAL", "1", quantity="2"
            )

    def test_income_can_be_recorded_for_past_holding_after_it_was_sold(self) -> None:
        self.ledger.trade(
            "TEST", "COMPRA", "1", "100", operation_date="2025-01-01"
        )
        self.ledger.trade(
            "TEST", "VENTA", "1", "110", operation_date="2025-02-01"
        )

        self.ledger.record_income(
            "TEST",
            "ACCIONES",
            "DIVIDENDO",
            "5",
            operation_date="2025-01-15",
        )

        self.assertEqual(self.ledger.cash_balance(), Decimal("1015"))
        self.assertEqual(
            self.ledger.portfolio_summary("USD").income_total, Decimal("5")
        )

    def test_commission_is_included_in_purchase_balance_validation(self) -> None:
        with self.assertRaises(SimulationError):
            self.ledger.trade("TEST", "COMPRA", "10", "100", commission="1")

        self.assertEqual(self.ledger.cash_balance(), Decimal("1000"))
        self.assertEqual(self.ledger.recent_trades(), [])

    def test_rejects_invalid_date_currency_and_negative_commission(self) -> None:
        with self.assertRaises(SimulationError):
            self.ledger.trade("TEST", "COMPRA", "1", "1", operation_date="20261015")
        with self.assertRaises(SimulationError):
            self.ledger.trade("TEST", "COMPRA", "1", "1", currency="EUR")
        with self.assertRaises(SimulationError):
            self.ledger.trade("TEST", "COMPRA", "1", "1", commission="-1")

    def test_migrates_existing_trade_database(self) -> None:
        legacy_database = Path(self.temp_dir.name) / "legacy.sqlite3"
        with closing(sqlite3.connect(legacy_database)) as connection:
            with connection:
                connection.execute(
                    "CREATE TABLE account (id INTEGER PRIMARY KEY, initial_cash TEXT NOT NULL)"
                )
                connection.execute(
                    "INSERT INTO account (id, initial_cash) VALUES (1, '500')"
                )
                connection.execute(
                    """
                    CREATE TABLE trades (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL DEFAULT (
                            strftime('%Y-%m-%d %H:%M:%S', 'now')
                        ),
                        symbol TEXT NOT NULL,
                        side TEXT NOT NULL,
                        quantity TEXT NOT NULL,
                        price TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO trades (timestamp, symbol, side, quantity, price)
                    VALUES ('2025-01-02 12:00:00', 'OLD', 'COMPRA', '1', '50')
                    """
                )

        ledger = SimulationLedger(legacy_database)

        self.assertEqual(ledger.cash_balance(), Decimal("450"))
        migrated = ledger.recent_trades()[0]
        self.assertEqual(migrated.operation_date, "2025-01-02")
        self.assertEqual(migrated.asset_type, "ACCIONES")
        self.assertEqual(migrated.currency, "USD")
        self.assertEqual(migrated.commission, Decimal("0"))


if __name__ == "__main__":
    unittest.main()
