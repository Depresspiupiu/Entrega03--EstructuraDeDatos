import math
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Sequence
from datetime import date

from finance_app.analysis import InsufficientMarketDataError, build_snapshot
from finance_app.models import StockCandle, StockSnapshot


class MarketDataError(RuntimeError):
    """Raised when Yahoo Finance cannot provide a usable quote."""


class YFinanceMarketData:
    def get_histories(
        self, symbols: Sequence[str]
    ) -> tuple[
        dict[str, tuple[StockSnapshot, tuple[StockCandle, ...]]], list[str]
    ]:
        ordered_symbols = tuple(dict.fromkeys(symbols))
        if not ordered_symbols:
            return {}, []

        with ThreadPoolExecutor(
            max_workers=min(len(ordered_symbols), 4)
        ) as executor:
            futures = {
                symbol: executor.submit(self.get_history, symbol)
                for symbol in ordered_symbols
            }
            results: dict[
                str, tuple[StockSnapshot, tuple[StockCandle, ...]]
            ] = {}
            errors: list[str] = []
            for symbol, future in futures.items():
                try:
                    results[symbol] = future.result()
                except Exception as exc:
                    errors.append(str(exc))
        return results, errors

    def get_history(
        self, symbol: str, period: str = "6mo"
    ) -> tuple[StockSnapshot, tuple[StockCandle, ...]]:
        try:
            import yfinance as yf

            history = yf.Ticker(symbol).history(
                period=period,
                interval="1d",
                auto_adjust=True,
                actions=False,
            )
            required_columns = {"Open", "High", "Low", "Close"}
            if history.empty or not required_columns.issubset(history.columns):
                raise MarketDataError(f"{symbol}: Yahoo Finance no devolvió datos.")

            candles: list[StockCandle] = []
            for timestamp, row in history.iterrows():
                try:
                    open_price, high, low, close = (
                        float(row[column])
                        for column in ("Open", "High", "Low", "Close")
                    )
                except (TypeError, ValueError, KeyError):
                    continue
                values = (open_price, high, low, close)
                if (
                    not all(math.isfinite(value) and value > 0 for value in values)
                    or low > min(open_price, close)
                    or high < max(open_price, close)
                ):
                    continue
                candles.append(
                    StockCandle(
                        day=date.fromisoformat(timestamp.date().isoformat()),
                        open=open_price,
                        high=high,
                        low=low,
                        close=close,
                    )
                )
            if len(candles) < 64:
                raise InsufficientMarketDataError(
                    f"{symbol}: se necesitan al menos 64 velas diarias; "
                    f"solo hay {len(candles)}."
                )
            snapshot = build_snapshot(
                symbol, [candle.close for candle in candles]
            )
            return snapshot, tuple(candles)
        except (InsufficientMarketDataError, MarketDataError):
            raise
        except Exception as exc:
            raise MarketDataError(
                f"{symbol}: no se pudo obtener o procesar la cotización: {exc}"
            ) from exc

    def get_snapshot(self, symbol: str) -> StockSnapshot:
        snapshot, _ = self.get_history(symbol)
        return snapshot
