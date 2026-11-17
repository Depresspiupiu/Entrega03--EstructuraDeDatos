import unittest

from finance_app.analysis import InsufficientMarketDataError, build_snapshot


class AnalysisTests(unittest.TestCase):
    def test_builds_price_and_historical_changes(self) -> None:
        closes = [100.0 + index for index in range(64)]

        result = build_snapshot("TEST", closes)

        self.assertEqual(result.symbol, "TEST")
        self.assertAlmostEqual(result.change_1d_pct, (163 / 162 - 1) * 100)
        self.assertAlmostEqual(result.change_1m_pct, (163 / 142 - 1) * 100)
        self.assertAlmostEqual(result.change_3m_pct, (163 / 100 - 1) * 100)

    def test_downward_prices_produce_negative_changes(self) -> None:
        result = build_snapshot("TEST", [200.0 - index for index in range(64)])

        self.assertLess(result.change_1d_pct, 0)
        self.assertLess(result.change_1m_pct, 0)
        self.assertLess(result.change_3m_pct, 0)

    def test_requires_enough_history(self) -> None:
        with self.assertRaises(InsufficientMarketDataError):
            build_snapshot("TEST", [100.0] * 63)


if __name__ == "__main__":
    unittest.main()
