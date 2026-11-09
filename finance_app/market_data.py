from finance_app.analysis import InsufficientMarketDataError, build_snapshot
from finance_app.models import StockSnapshot


class MarketDataError(RuntimeError):
    """Raised when Yahoo Finance cannot provide a usable quote."""


class YFinanceMarketData:
    def get_snapshot(self, symbol: str) -> StockSnapshot:
        try:
            import yfinance as yf

            history = yf.Ticker(symbol).history(
                period="6mo",
                interval="1d",
                auto_adjust=True,
            )
            if history.empty or "Close" not in history:
                raise MarketDataError(f"{symbol}: Yahoo Finance no devolvió datos.")
            closes = history["Close"].dropna().tolist()
            return build_snapshot(symbol, closes)
        except (InsufficientMarketDataError, MarketDataError):
            raise
        except Exception as exc:
            raise MarketDataError(
                f"{symbol}: no se pudo obtener o procesar la cotización: {exc}"
            ) from exc
