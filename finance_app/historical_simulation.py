from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Mapping, Sequence


class HistoricalDataError(RuntimeError):
    """Raised when historical market data cannot be loaded or used."""


class SimulationCompleteError(RuntimeError):
    """Raised when the simulation has reached the last available date."""


SIMULATED_DAY_SECONDS = 5


class AcceleratedSimulationClock:
    def __init__(self, start_date: date) -> None:
        self.current_date = start_date
        self.hour = 0

    def advance_hour(self) -> tuple[date, int]:
        self.hour += 1
        if self.hour == 24:
            self.hour = 0
            self.current_date += timedelta(days=1)
        return self.current_date, self.hour


@dataclass(frozen=True)
class HistoricalBar:
    day: date
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class PortfolioCandle:
    day: date
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class SimulatedTrade:
    day: date
    symbol: str
    side: str
    quantity: int
    unit_price: float
    total: float


@dataclass(frozen=True)
class MonthlyPriceChange:
    reference_day: date
    reference_price: float
    current_price: float
    absolute_change: float
    percent_change: float


MARKET_SYMBOLS = {
    "NASDAQ": ("AAPL", "PEP", "NVDA"),
    "NYSE": ("NKE", "KO", "TSM"),
}
COMPANY_NAMES = {
    "AAPL": "Apple",
    "NKE": "Nike",
    "KO": "Coca-Cola",
    "PEP": "PepsiCo",
    "NVDA": "Nvidia",
    "TSM": "TSMC (ADR)",
}


def fetch_2023_history(
    symbols: Sequence[str],
) -> dict[str, tuple[HistoricalBar, ...]]:
    try:
        from finance_app.market_data import MarketDataError, YFinanceMarketData
    except ImportError as exc:
        raise HistoricalDataError(
            "Faltan dependencias para descargar datos. "
            "Instala requirements-runtime.txt."
        ) from exc

    market_data = YFinanceMarketData()
    histories: dict[str, dict[date, HistoricalBar]] = {}
    for symbol in symbols:
        try:
            candles = market_data.get_history_range(
                symbol, date(2023, 1, 1), date(2024, 1, 1)
            )
        except MarketDataError as exc:
            raise HistoricalDataError(
                f"No se pudieron descargar los datos de {symbol}: {exc}"
            ) from exc

        bars = {
            candle.day: HistoricalBar(
                candle.day,
                candle.open,
                candle.high,
                candle.low,
                candle.close,
            )
            for candle in candles
        }
        if not bars:
            raise HistoricalDataError(
                f"No hay precios válidos de {symbol} para 2023."
            )
        histories[symbol] = bars

    common_days = set.intersection(*(set(bars) for bars in histories.values()))
    if len(common_days) < 2:
        raise HistoricalDataError(
            "No hay suficientes fechas de cotización comunes para simular."
        )
    ordered_days = sorted(common_days)
    return {
        symbol: tuple(histories[symbol][day] for day in ordered_days)
        for symbol in symbols
    }


class HistoricalPortfolioSimulation:
    def __init__(
        self,
        history: Mapping[str, Sequence[HistoricalBar]],
        symbols: Sequence[str],
        initial_cash: float,
        start_date: date,
        *,
        end_date: date | None = None,
        seed: int | None = None,
        random_initial_holdings: bool = False,
        initial_random_symbols: Sequence[str] | None = None,
        initial_holdings: Mapping[str, int] | None = None,
        market: str = "",
    ) -> None:
        if not math.isfinite(initial_cash) or initial_cash <= 0:
            raise ValueError("El capital inicial debe ser mayor que cero.")
        if not symbols:
            raise ValueError("Selecciona al menos una empresa.")
        if any(symbol not in history for symbol in symbols):
            raise HistoricalDataError(
                "Faltan datos históricos para una o más empresas seleccionadas."
            )

        selected = tuple(dict.fromkeys(symbols))
        first_series = history[selected[0]]
        if not first_series:
            raise HistoricalDataError("La serie histórica está vacía.")
        dates = tuple(bar.day for bar in first_series)
        if any(later <= earlier for earlier, later in zip(dates, dates[1:])):
            raise HistoricalDataError(
                "Las fechas históricas deben estar en orden ascendente."
            )
        for symbol in selected:
            if tuple(bar.day for bar in history[symbol]) != dates:
                raise HistoricalDataError(
                    "Las empresas seleccionadas no comparten las mismas fechas."
                )

        start_index = next(
            (index for index, day in enumerate(dates) if day >= start_date),
            None,
        )
        if start_index is None or start_index == len(dates) - 1:
            raise HistoricalDataError(
                "La fecha elegida no deja días de cotización disponibles en 2023."
            )
        simulation_end_date = end_date or dates[-1]
        if simulation_end_date < dates[start_index]:
            raise HistoricalDataError(
                "La fecha final debe incluir al menos un día de cotización."
            )

        self.symbols = selected
        self.initial_cash = initial_cash
        self.start_date = start_date
        self.end_date = simulation_end_date
        self.market = market
        self._history = history
        self._dates = dates
        self._index = start_index
        self._start_index = start_index
        self._current_date = start_date
        self._calendar_mode = start_date != dates[start_index]
        self._random = random.Random(seed)
        if initial_holdings is not None and (
            random_initial_holdings or initial_random_symbols is not None
        ):
            raise ValueError(
                "No se pueden proporcionar tenencias y pedir valores aleatorios."
            )
        if initial_holdings is not None:
            if set(initial_holdings) != set(selected):
                raise ValueError(
                    "Las tenencias iniciales deben incluir todas las empresas."
                )
            if any(
                not isinstance(quantity, int) or quantity < 0
                for quantity in initial_holdings.values()
            ):
                raise ValueError(
                    "Las tenencias iniciales deben ser cantidades enteras "
                    "no negativas."
                )
            self._shares = {
                symbol: float(initial_holdings[symbol]) for symbol in selected
            }
        elif random_initial_holdings:
            self._shares = {
                symbol: float(self._random.randint(0, 50)) for symbol in selected
            }
        else:
            if initial_random_symbols is not None:
                randomized = tuple(dict.fromkeys(initial_random_symbols))
                if any(symbol not in selected for symbol in randomized):
                    raise ValueError(
                        "Las tenencias aleatorias deben pertenecer a la sesión."
                    )
                self._shares = {
                    symbol: (
                        float(self._random.randint(0, 50))
                        if symbol in randomized
                        else 0.0
                    )
                    for symbol in selected
                }
            else:
                allocation = initial_cash / len(selected)
                self._shares = {
                    symbol: allocation / history[symbol][start_index].close
                    for symbol in selected
                }
        self._current_prices = {
            symbol: history[symbol][start_index].close for symbol in selected
        }
        invested = sum(
            self._shares[symbol] * self._current_prices[symbol]
            for symbol in selected
        )
        if random_initial_holdings or initial_random_symbols is not None:
            while invested > initial_cash:
                holdings_with_shares = [
                    symbol for symbol in selected if self._shares[symbol] >= 1
                ]
                if not holdings_with_shares:
                    raise ValueError(
                        "El capital inicial no alcanza para las tenencias."
                    )
                symbol = self._random.choice(holdings_with_shares)
                self._shares[symbol] -= 1
                invested -= self._current_prices[symbol]
        if invested > initial_cash:
            raise ValueError(
                "Las tenencias iniciales superan el capital disponible."
            )
        self._cash_balance = initial_cash - invested
        self._price_candles = {
            symbol: [history[symbol][start_index]] for symbol in selected
        }
        self._trades: list[SimulatedTrade] = []
        initial_value = self._portfolio_value(self._current_prices)
        self._candles = [
            PortfolioCandle(
                self.start_date,
                initial_value,
                initial_value,
                initial_value,
                initial_value,
            )
        ]

    @property
    def current_date(self) -> date:
        return self._current_date

    @property
    def current_value(self) -> float:
        return self._cash_balance + self._portfolio_value(self._current_prices)

    @property
    def cash_balance(self) -> float:
        return self._cash_balance

    @property
    def holdings(self) -> dict[str, int]:
        return {symbol: int(quantity) for symbol, quantity in self._shares.items()}

    @property
    def prices(self) -> dict[str, float]:
        return dict(self._current_prices)

    @property
    def return_pct(self) -> float:
        return (self.current_value / self.initial_cash - 1) * 100

    @property
    def is_complete(self) -> bool:
        return self._current_date >= self.end_date

    @property
    def candles(self) -> tuple[PortfolioCandle, ...]:
        return tuple(self._candles)

    @property
    def trades(self) -> tuple[SimulatedTrade, ...]:
        return tuple(self._trades)

    def price_candles(self, symbol: str) -> tuple[HistoricalBar, ...]:
        if symbol not in self._price_candles:
            raise ValueError(f"{symbol} no pertenece a esta simulación.")
        return tuple(self._price_candles[symbol])

    def monthly_price_change(
        self, symbol: str
    ) -> MonthlyPriceChange | None:
        if symbol not in self._price_candles:
            raise ValueError(f"{symbol} no pertenece a esta simulación.")

        previous_month_end = self._current_date.replace(day=1) - timedelta(days=1)
        comparison_date = previous_month_end.replace(
            day=min(self._current_date.day, previous_month_end.day)
        )
        reference_bar = next(
            (
                bar
                for bar in reversed(self._price_candles[symbol])
                if bar.day <= comparison_date
            ),
            None,
        )
        if reference_bar is None:
            return None

        current_price = self._current_prices[symbol]
        absolute_change = current_price - reference_bar.close
        return MonthlyPriceChange(
            reference_day=reference_bar.day,
            reference_price=reference_bar.close,
            current_price=current_price,
            absolute_change=absolute_change,
            percent_change=absolute_change / reference_bar.close * 100,
        )

    def _portfolio_value(self, prices: Mapping[str, float]) -> float:
        return sum(self._shares[symbol] * prices[symbol] for symbol in self.symbols)

    def trade(self, symbol: str, side: str, quantity: int) -> SimulatedTrade:
        symbol = symbol.strip().upper()
        side = side.strip().upper()
        if symbol not in self._shares:
            raise ValueError("Selecciona una empresa incluida en la sesión.")
        if side not in {"COMPRA", "VENTA"}:
            raise ValueError("La operación debe ser COMPRA o VENTA.")
        if not isinstance(quantity, int) or not 1 <= quantity <= 50:
            raise ValueError("La cantidad debe ser un número entero entre 1 y 50.")

        price = self._current_prices[symbol]
        total = price * quantity
        if side == "COMPRA":
            if total > self._cash_balance:
                raise ValueError(
                    f"Saldo insuficiente. Disponible: "
                    f"USD {self._cash_balance:,.2f}."
                )
            self._cash_balance -= total
            self._shares[symbol] += quantity
        else:
            if quantity > self._shares[symbol]:
                raise ValueError(
                    f"No tienes suficientes acciones de {symbol}. "
                    f"Disponibles: {int(self._shares[symbol])}."
                )
            self._cash_balance += total
            self._shares[symbol] -= quantity

        trade = SimulatedTrade(
            self.current_date, symbol, side, quantity, price, total
        )
        self._trades.append(trade)
        current_bars = {
            item: self._price_candles[item][-1] for item in self.symbols
        }
        if all(bar.day == self.current_date for bar in current_bars.values()):
            self._candles[-1] = self._portfolio_candle(
                self.current_date, current_bars
            )
        else:
            current_value = self.current_value
            self._candles[-1] = PortfolioCandle(
                self.current_date,
                current_value,
                current_value,
                current_value,
                current_value,
            )
        return trade

    def _portfolio_candle(
        self, day: date, bars: Mapping[str, HistoricalBar]
    ) -> PortfolioCandle:
        values = {
            field: self._cash_balance
            + sum(
                self._shares[symbol] * getattr(bars[symbol], field)
                for symbol in self.symbols
            )
            for field in ("open", "high", "low", "close")
        }
        return PortfolioCandle(
            day,
            values["open"],
            max(values["high"], values["open"], values["close"]),
            min(values["low"], values["open"], values["close"]),
            values["close"],
        )

    def advance(self) -> PortfolioCandle:
        return self.advance_calendar_day()

    def advance_calendar_day(self) -> PortfolioCandle:
        if self.is_complete:
            raise SimulationCompleteError(
                "La simulación ya llegó a su fecha final."
            )

        next_date = self._current_date + timedelta(days=1)
        next_index = self._index + 1
        self._calendar_mode = True
        if (
            next_index >= len(self._dates)
            or self._dates[next_index] != next_date
        ):
            self._current_date = next_date
            value = self.current_value
            candle = PortfolioCandle(
                next_date, value, value, value, value
            )
            self._candles.append(candle)
            return candle

        next_prices: dict[str, float] = {}
        next_bars: dict[str, HistoricalBar] = {}
        for symbol in self.symbols:
            previous_market = self._history[symbol][self._index]
            market_bar = self._history[symbol][next_index]
            previous_simulated = self._current_prices[symbol]
            historical_return = market_bar.close / previous_market.close - 1
            noise = self._random.gauss(
                0.0, max(abs(historical_return) * 0.05, 0.0001)
            )
            close = previous_simulated * max(0.01, 1 + historical_return + noise)
            scale = close / market_bar.close
            simulated_open = (
                previous_simulated * market_bar.open / previous_market.close
            ) * scale
            simulated_high = (
                previous_simulated * market_bar.high / previous_market.close
            ) * scale
            simulated_low = (
                previous_simulated * market_bar.low / previous_market.close
            ) * scale
            simulated_high = max(simulated_high, simulated_open, close)
            simulated_low = min(simulated_low, simulated_open, close)
            next_bars[symbol] = HistoricalBar(
                market_bar.day,
                simulated_open,
                simulated_high,
                simulated_low,
                close,
            )
            next_prices[symbol] = close

        self._index = next_index
        self._current_date = next_date
        self._current_prices = next_prices
        for symbol, bar in next_bars.items():
            self._price_candles[symbol].append(bar)
        candle = self._portfolio_candle(self.current_date, next_bars)
        self._candles.append(candle)
        return candle

    def export_state(self) -> dict[str, object]:
        return {
            "version": 1,
            "calendar_mode": self._calendar_mode,
            "market": self.market,
            "symbols": list(self.symbols),
            "initial_cash": self.initial_cash,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "current_date": self.current_date.isoformat(),
            "index": self._index,
            "cash_balance": self._cash_balance,
            "shares": self._shares,
            "current_prices": self._current_prices,
            "random_state": self._random.getstate(),
            "history": {
                symbol: [
                    {
                        "day": bar.day.isoformat(),
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                    }
                    for bar in self._history[symbol]
                ]
                for symbol in self.symbols
            },
            "price_candles": {
                symbol: [
                    {
                        "day": bar.day.isoformat(),
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                    }
                    for bar in self._price_candles[symbol]
                ]
                for symbol in self.symbols
            },
            "candles": [
                {
                    "day": candle.day.isoformat(),
                    "open": candle.open,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                }
                for candle in self._candles
            ],
            "trades": [
                {
                    "day": trade.day.isoformat(),
                    "symbol": trade.symbol,
                    "side": trade.side,
                    "quantity": trade.quantity,
                    "unit_price": trade.unit_price,
                    "total": trade.total,
                }
                for trade in self._trades
            ],
        }

    @classmethod
    def from_state(
        cls, state: Mapping[str, object]
    ) -> HistoricalPortfolioSimulation:
        if state.get("version") != 1:
            raise ValueError("La versión de la sesión guardada no es compatible.")
        try:
            symbols = tuple(state["symbols"])
            start_date = date.fromisoformat(state["start_date"])
            end_date = (
                date.fromisoformat(state["end_date"])
                if state.get("end_date")
                else None
            )
            calendar_mode = state.get("calendar_mode") is True
            history_data = state["history"]
            if not isinstance(history_data, Mapping):
                raise TypeError
            history = {
                symbol: tuple(
                    HistoricalBar(
                        date.fromisoformat(item["day"]),
                        float(item["open"]),
                        float(item["high"]),
                        float(item["low"]),
                        float(item["close"]),
                    )
                    for item in history_data[symbol]
                )
                for symbol in symbols
            }
            raw_shares = state["shares"]
            if not isinstance(raw_shares, Mapping):
                raise TypeError
            shares = {symbol: float(raw_shares[symbol]) for symbol in symbols}
            if any(
                not math.isfinite(quantity) or quantity < 0
                for quantity in shares.values()
            ):
                raise ValueError("Las tenencias guardadas no son válidas.")
            simulation = cls(
                history,
                symbols,
                float(state["initial_cash"]),
                start_date,
                end_date=end_date,
                initial_holdings={symbol: 0 for symbol in symbols},
                market=str(state["market"]),
            )
            simulation._shares = shares
            index = int(state["index"])
            if not simulation._start_index <= index < len(simulation._dates):
                raise ValueError("La fecha guardada no pertenece a la serie.")
            simulation._index = index
            simulation._current_date = (
                date.fromisoformat(state["current_date"])
                if state.get("current_date")
                else simulation._dates[index]
            )
            if not (
                simulation.start_date
                <= simulation._current_date
                <= simulation.end_date
            ):
                raise ValueError("La fecha guardada no pertenece a la sesión.")
            simulation._calendar_mode = calendar_mode
            simulation._cash_balance = float(state["cash_balance"])
            raw_prices = state["current_prices"]
            if not isinstance(raw_prices, Mapping):
                raise TypeError
            simulation._current_prices = {
                symbol: float(raw_prices[symbol]) for symbol in symbols
            }
            simulation._price_candles = {
                symbol: [
                    HistoricalBar(
                        date.fromisoformat(item["day"]),
                        float(item["open"]),
                        float(item["high"]),
                        float(item["low"]),
                        float(item["close"]),
                    )
                    for item in state["price_candles"][symbol]
                ]
                for symbol in symbols
            }
            simulation._candles = [
                PortfolioCandle(
                    date.fromisoformat(item["day"]),
                    float(item["open"]),
                    float(item["high"]),
                    float(item["low"]),
                    float(item["close"]),
                )
                for item in state["candles"]
            ]
            simulation._trades = [
                SimulatedTrade(
                    date.fromisoformat(item["day"]),
                    str(item["symbol"]),
                    str(item["side"]),
                    int(item["quantity"]),
                    float(item["unit_price"]),
                    float(item["total"]),
                )
                for item in state["trades"]
            ]
            simulation._random.setstate(_nested_tuple(state["random_state"]))
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise ValueError(
                "La sesión guardada está incompleta o dañada."
            ) from exc
        if not calendar_mode:
            calendar_candles: list[PortfolioCandle] = []
            for candle in simulation._candles:
                if calendar_candles:
                    fill_date = calendar_candles[-1].day + timedelta(days=1)
                    while fill_date < candle.day:
                        value = calendar_candles[-1].close
                        calendar_candles.append(
                            PortfolioCandle(
                                fill_date, value, value, value, value
                            )
                        )
                        fill_date += timedelta(days=1)
                calendar_candles.append(candle)
            simulation._candles = calendar_candles
            simulation._calendar_mode = True

        expected_candles = (
            (simulation.current_date - simulation.start_date).days + 1
        )
        expected_price_candles = index - simulation._start_index + 1
        if (
            not simulation._candles
            or len(simulation._candles) != expected_candles
            or simulation._candles[0].day != simulation.start_date
            or simulation._candles[-1].day != simulation.current_date
            or any(
                simulation._candles[position].day
                != simulation._candles[position - 1].day + timedelta(days=1)
                for position in range(1, len(simulation._candles))
            )
            or any(
                len(simulation._price_candles[symbol]) != expected_price_candles
                for symbol in symbols
            )
        ):
            raise ValueError("La serie de la sesión guardada está incompleta.")
        return simulation


def _nested_tuple(value: object) -> object:
    if isinstance(value, list):
        return tuple(_nested_tuple(item) for item in value)
    return value
