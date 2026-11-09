import unittest

from finance_app.analysis import InsufficientMarketDataError, build_snapshot


class AnalysisTests(unittest.TestCase):
    def test_builds_momentum_snapshot_and_buy_signal(self) -> None:
        closes = [100.0 + index for index in range(64)]

        result = build_snapshot("TEST", closes)

        self.assertEqual(result.symbol, "TEST")
        self.assertAlmostEqual(result.change_1d_pct, (163 / 162 - 1) * 100)
        self.assertAlmostEqual(result.change_1m_pct, (163 / 142 - 1) * 100)
        self.assertAlmostEqual(result.change_3m_pct, (163 / 100 - 1) * 100)
        self.assertEqual(result.recommendation, "COMPRA")

    def test_downward_trend_produces_sell_signal(self) -> None:
        result = build_snapshot("TEST", [200.0 - index for index in range(64)])

        self.assertEqual(result.recommendation, "VENTA")

    def test_requires_enough_history(self) -> None:
        with self.assertRaises(InsufficientMarketDataError):
            build_snapshot("TEST", [100.0] * 63)


if __name__ == "__main__":
    unittest.main()
