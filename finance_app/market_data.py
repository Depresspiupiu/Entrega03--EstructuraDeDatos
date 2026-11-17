import math
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import quote

from curl_cffi import requests

from finance_app.analysis import InsufficientMarketDataError, build_snapshot
from finance_app.models import StockCandle, StockSnapshot


class MarketDataError(RuntimeError):
    """Raised when Yahoo Finance cannot provide a usable quote."""


YFINANCE_ATTEMPTS = 2
YFINANCE_RETRY_DELAY_SECONDS = 0.5
YAHOO_CHART_HOSTS = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")


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
        except ImportError as exc:
            raise MarketDataError(
                "Falta yfinance. Instala las dependencias de "
                "requirements-runtime.txt."
            ) from exc

        yfinance_error: Exception | None = None
        for attempt in range(YFINANCE_ATTEMPTS):
            try:
                history = yf.Ticker(symbol).history(
                    period=period,
                    interval="1d",
                    auto_adjust=True,
                    actions=False,
                )
                candles = self._candles_from_history(symbol, history)
                if len(candles) < 64:
                    raise InsufficientMarketDataError(
                        f"{symbol}: se necesitan al menos 64 velas diarias; "
                        f"solo hay {len(candles)}."
                    )
                return self._build_result(symbol, candles)
            except InsufficientMarketDataError:
                raise
            except Exception as exc:
                yfinance_error = exc
                if attempt + 1 < YFINANCE_ATTEMPTS:
                    time.sleep(YFINANCE_RETRY_DELAY_SECONDS)

        try:
            candles = self._download_chart_candles(symbol, period)
            if len(candles) < 64:
                raise InsufficientMarketDataError(
                    f"{symbol}: se necesitan al menos 64 velas diarias; "
                    f"solo hay {len(candles)}."
                )
            return self._build_result(symbol, candles)
        except InsufficientMarketDataError:
            raise
        except Exception as exc:
            raise MarketDataError(
                f"{symbol}: Yahoo Finance no devolvió cotizaciones válidas. "
                f"yfinance: {yfinance_error}; consulta alternativa: {exc}"
            ) from exc

    def get_history_range(
        self, symbol: str, start: date, end: date
    ) -> tuple[StockCandle, ...]:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise MarketDataError(
                "Falta yfinance. Instala las dependencias de "
                "requirements-runtime.txt."
            ) from exc

        yfinance_error: Exception | None = None
        for attempt in range(YFINANCE_ATTEMPTS):
            try:
                history = yf.Ticker(symbol).history(
                    start=start.isoformat(),
                    end=end.isoformat(),
                    interval="1d",
                    auto_adjust=True,
                    actions=False,
                )
                return self._candles_from_history(symbol, history)
            except Exception as exc:
                yfinance_error = exc
                if attempt + 1 < YFINANCE_ATTEMPTS:
                    time.sleep(YFINANCE_RETRY_DELAY_SECONDS)

        try:
            return self._download_chart_candles(
                symbol, start=start, end=end
            )
        except Exception as exc:
            raise MarketDataError(
                f"{symbol}: Yahoo Finance no devolvió cotizaciones válidas. "
                f"yfinance: {yfinance_error}; consulta alternativa: {exc}"
            ) from exc

    @staticmethod
    def _candles_from_history(
        symbol: str, history: Any
    ) -> tuple[StockCandle, ...]:
        required_columns = {"Open", "High", "Low", "Close"}
        if history.empty or not required_columns.issubset(history.columns):
            raise MarketDataError(
                f"{symbol}: Yahoo Finance no devolvió datos completos."
            )

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
        if not candles:
            raise MarketDataError(f"{symbol}: Yahoo Finance no devolvió velas válidas.")
        return tuple(candles)

    @staticmethod
    def _build_result(
        symbol: str, candles: Sequence[StockCandle]
    ) -> tuple[StockSnapshot, tuple[StockCandle, ...]]:
        snapshot = build_snapshot(symbol, [candle.close for candle in candles])
        return snapshot, tuple(candles)

    def _download_chart_candles(
        self,
        symbol: str,
        period: str | None = None,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> tuple[StockCandle, ...]:
        errors: list[str] = []
        encoded_symbol = quote(symbol, safe="")
        params: dict[str, str | int] = {
            "interval": "1d",
            "events": "div,splits",
        }
        if period is not None:
            params["range"] = period
        elif start is not None and end is not None:
            params["period1"] = int(
                datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp()
            )
            params["period2"] = int(
                datetime(end.year, end.month, end.day, tzinfo=timezone.utc).timestamp()
            )
        else:
            raise ValueError("Se requiere un periodo o un rango de fechas.")

        for host in YAHOO_CHART_HOSTS:
            url = f"https://{host}/v8/finance/chart/{encoded_symbol}"
            try:
                response = requests.get(
                    url,
                    params=params,
                    impersonate="chrome",
                    timeout=20,
                )
                response.raise_for_status()
                return self._candles_from_yahoo_chart(
                    symbol, response.json()
                )
            except Exception as exc:
                errors.append(f"{host}: {exc}")

        raise MarketDataError("; ".join(errors))

    @staticmethod
    def _candles_from_yahoo_chart(
        symbol: str, payload: object
    ) -> tuple[StockCandle, ...]:
        if not isinstance(payload, dict):
            raise MarketDataError("La respuesta de Yahoo Finance no es válida.")
        chart = payload.get("chart")
        if not isinstance(chart, dict):
            raise MarketDataError("La respuesta de Yahoo Finance no es válida.")
        chart_error = chart.get("error")
        if chart_error:
            if isinstance(chart_error, dict):
                chart_error = chart_error.get("description", chart_error)
            raise MarketDataError(str(chart_error))
        results = chart.get("result")
        if not isinstance(results, list) or not results:
            raise MarketDataError(
                f"{symbol}: Yahoo Finance no devolvió datos."
            )

        result = results[0]
        if not isinstance(result, dict):
            raise MarketDataError("La respuesta de Yahoo Finance no es válida.")
        timestamps = result.get("timestamp")
        indicators = result.get("indicators")
        if not isinstance(timestamps, list) or not isinstance(indicators, dict):
            raise MarketDataError("La respuesta de Yahoo Finance está incompleta.")
        quotes = indicators.get("quote")
        if not isinstance(quotes, list) or not quotes or not isinstance(quotes[0], dict):
            raise MarketDataError("La respuesta de Yahoo Finance no incluye OHLC.")
        quote_data = quotes[0]
        adjusted = indicators.get("adjclose")
        adjusted_closes = (
            adjusted[0].get("adjclose")
            if isinstance(adjusted, list)
            and adjusted
            and isinstance(adjusted[0], dict)
            else None
        )

        candles: list[StockCandle] = []
        for index, timestamp in enumerate(timestamps):
            try:
                if not isinstance(timestamp, (int, float)):
                    continue
                open_price, high, low, close = (
                    float(quote_data[name][index])
                    for name in ("open", "high", "low", "close")
                )
                if not math.isfinite(close) or close <= 0:
                    continue
                adjusted_close = (
                    float(adjusted_closes[index])
                    if adjusted_closes is not None
                    else close
                )
                if not math.isfinite(adjusted_close) or adjusted_close <= 0:
                    adjusted_close = close
                adjustment_factor = adjusted_close / close
                open_price *= adjustment_factor
                high *= adjustment_factor
                low *= adjustment_factor
                close = adjusted_close
                values = (open_price, high, low, close)
                if (
                    not all(math.isfinite(value) and value > 0 for value in values)
                    or low > min(open_price, close)
                    or high < max(open_price, close)
                ):
                    continue
                candles.append(
                    StockCandle(
                        day=datetime.fromtimestamp(
                            timestamp, timezone.utc
                        ).date(),
                        open=open_price,
                        high=high,
                        low=low,
                        close=close,
                    )
                )
            except (IndexError, TypeError, ValueError, OverflowError, OSError):
                continue

        if not candles:
            raise MarketDataError(f"{symbol}: Yahoo Finance no devolvió velas.")
        return tuple(candles)

    def get_snapshot(self, symbol: str) -> StockSnapshot:
        snapshot, _ = self.get_history(symbol)
        return snapshot
