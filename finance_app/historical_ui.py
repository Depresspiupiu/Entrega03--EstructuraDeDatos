import time
from datetime import date

import matplotlib.dates as mdates
from matplotlib.axes import Axes
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.patches import Patch, Rectangle
from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from finance_app.historical_simulation import (
    SIMULATED_DAY_SECONDS,
    AcceleratedSimulationClock,
    COMPANY_NAMES,
    HistoricalBar,
    HistoricalDataError,
    HistoricalPortfolioSimulation,
    MARKET_SYMBOLS,
    PortfolioCandle,
    SimulationCompleteError,
    fetch_2023_history,
)

SYMBOL_CANDLE_COLORS = (
    "#2563eb",
    "#f97316",
    "#16a34a",
    "#9333ea",
    "#0891b2",
    "#db2777",
)


def _draw_candles(
    axes: Axes,
    candles: tuple[HistoricalBar, ...] | tuple[PortfolioCandle, ...],
    *,
    width: float,
    offset: float = 0.0,
    symbol_color: str | None = None,
) -> None:
    for candle in candles:
        x = mdates.date2num(candle.day) + offset
        is_up = candle.close >= candle.open
        color = symbol_color or ("#16a34a" if is_up else "#dc2626")
        facecolor = (
            color if symbol_color is None or is_up else "white"
        )
        axes.vlines(x, candle.low, candle.high, color=color, linewidth=0.8)
        body_height = abs(candle.close - candle.open)
        if body_height == 0:
            axes.hlines(
                candle.close,
                x - width / 2,
                x + width / 2,
                color=color,
                linewidth=1.2,
            )
        else:
            axes.add_patch(
                Rectangle(
                    (x - width / 2, min(candle.open, candle.close)),
                    width,
                    body_height,
                    facecolor=facecolor,
                    edgecolor=color,
                    linewidth=0.8,
                )
            )


class HistoricalDataWorker(QThread):
    completed = Signal(object, str)

    def __init__(self, market: str) -> None:
        super().__init__()
        self.market = market

    def run(self) -> None:
        try:
            history = fetch_2023_history(MARKET_SYMBOLS[self.market])
        except HistoricalDataError as exc:
            self.completed.emit(None, str(exc))
            return
        self.completed.emit(history, "")


class HistoricalSimulationWindow(QMainWindow):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("FinSim | Simulación histórica 2023")
        self.resize(1100, 700)

        self.simulation: HistoricalPortfolioSimulation | None = None
        self.clock: AcceleratedSimulationClock | None = None
        self.worker: HistoricalDataWorker | None = None
        self._pending_market = "NYSE"
        self._pending_initial_cash = 100_000.0
        self._clock_started_at: float | None = None
        self._elapsed_real_seconds = 0.0
        self._elapsed_hours = 0

        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._advance_clock)

        content = QWidget()
        layout = QVBoxLayout(content)

        controls = QHBoxLayout()
        self.market_input = QComboBox()
        self.market_input.addItem("NYSE", "NYSE")
        self.market_input.addItem("NASDAQ", "NASDAQ")
        self.initial_cash_input = QDoubleSpinBox()
        self.initial_cash_input.setRange(1_000, 1_000_000_000)
        self.initial_cash_input.setDecimals(2)
        self.initial_cash_input.setValue(100_000)
        self.start_button = QPushButton("Iniciar simulación")
        self.start_button.clicked.connect(self._start_simulation)
        self.pause_button = QPushButton("Pausar")
        self.pause_button.setEnabled(False)
        self.pause_button.clicked.connect(self._toggle_pause)
        for widget in (
            QLabel("Mercado:"),
            self.market_input,
            QLabel("Capital inicial (USD):"),
            self.initial_cash_input,
            self.start_button,
            self.pause_button,
        ):
            controls.addWidget(widget)
        controls.addStretch()
        layout.addLayout(controls)

        trade_group = QGroupBox("Compra y venta manual")
        trade_controls = QVBoxLayout(trade_group)
        trade_row = QHBoxLayout()
        self.symbol_input = QComboBox()
        self.quantity_input = QSpinBox()
        self.quantity_input.setRange(1, 50)
        self.buy_button = QPushButton("Comprar")
        self.buy_button.clicked.connect(lambda: self._execute_trade("COMPRA"))
        self.sell_button = QPushButton("Vender")
        self.sell_button.clicked.connect(lambda: self._execute_trade("VENTA"))
        self.position_label = QLabel("Tenencia: 0 | Precio: --")
        self.trade_status_label = QLabel("Sin operaciones manuales.")
        self.symbol_input.currentIndexChanged.connect(
            self._refresh_trade_quote
        )
        for widget in (
            QLabel("Empresa:"),
            self.symbol_input,
            QLabel("Cantidad (1–50):"),
            self.quantity_input,
            self.buy_button,
            self.sell_button,
            self.position_label,
        ):
            trade_row.addWidget(widget)
        trade_row.addStretch()
        trade_controls.addLayout(trade_row)
        self.monthly_change_label = QLabel("Variación mensual: --")
        self.monthly_change_label.setWordWrap(True)
        trade_controls.addWidget(self.monthly_change_label)
        trade_group.setEnabled(False)
        self.trade_group = trade_group
        layout.addWidget(trade_group)
        layout.addWidget(self.trade_status_label)

        summary_group = QGroupBox("Estado de la cartera")
        summary_layout = QVBoxLayout(summary_group)
        self.summary_label = QLabel("Inicia una simulación para ver los valores.")
        self.summary_label.setWordWrap(True)
        summary_layout.addWidget(self.summary_label)
        layout.addWidget(summary_group)

        chart_group = QGroupBox("Gráficas de la simulación")
        chart_layout = QVBoxLayout(chart_group)
        chart_header = QHBoxLayout()
        self.date_label = QLabel("Fecha simulada: 2023-01-01")
        self.clock_label = QLabel("Hora simulada: 00:00")
        self.clock_label.setStyleSheet(
            "font-size: 10px; padding: 2px 6px; border: 1px solid #888;"
        )
        self.chart_mode_input = QComboBox()
        self.chart_mode_input.addItem("Líneas", "line")
        self.chart_mode_input.addItem("Velas OHLC", "candlestick")
        self.chart_mode_input.currentIndexChanged.connect(
            lambda _index: self._refresh_simulation()
        )
        chart_header.addWidget(self.date_label)
        chart_header.addStretch()
        chart_header.addWidget(QLabel("Gráficas:"))
        chart_header.addWidget(self.chart_mode_input)
        chart_header.addWidget(self.clock_label)
        chart_layout.addLayout(chart_header)

        self.figure = Figure(figsize=(10, 4))
        self.canvas = FigureCanvasQTAgg(self.figure)
        chart_layout.addWidget(self.canvas)
        layout.addWidget(chart_group, 1)

        self.status_label = QLabel(
            "Un día simulado equivale a 5 segundos reales. "
            "Los precios permanecen iguales en días sin cotización."
        )
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.setCentralWidget(content)

    def _start_simulation(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return

        self.timer.stop()
        self._clock_started_at = None
        self._elapsed_real_seconds = 0.0
        self._elapsed_hours = 0
        self.simulation = None
        self.clock = None
        self.trade_group.setEnabled(False)
        self.clock_label.setText("Hora simulada: 00:00")
        self.date_label.setText("Fecha simulada: 2023-01-01")
        self.start_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.status_label.setText("Descargando cotizaciones históricas de 2023...")
        self._pending_market = str(self.market_input.currentData())
        self._pending_initial_cash = self.initial_cash_input.value()
        self.worker = HistoricalDataWorker(self._pending_market)
        self.worker.completed.connect(self._historical_data_loaded)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def _worker_finished(self) -> None:
        self.start_button.setEnabled(True)
        self.worker = None

    def _historical_data_loaded(
        self, history: dict[str, tuple[HistoricalBar, ...]] | None, error: str
    ) -> None:
        if error:
            self.status_label.setText("No se pudieron cargar los datos históricos.")
            QMessageBox.warning(self, "Datos no disponibles", error)
            return
        if history is None:
            self.status_label.setText("No se recibieron datos históricos.")
            QMessageBox.warning(
                self,
                "Datos no disponibles",
                "No se recibieron datos históricos para iniciar la simulación.",
            )
            return

        try:
            self.simulation = HistoricalPortfolioSimulation(
                history,
                MARKET_SYMBOLS[self._pending_market],
                self._pending_initial_cash,
                date(2023, 1, 1),
                end_date=date(2023, 12, 31),
                initial_holdings={
                    symbol: 0
                    for symbol in MARKET_SYMBOLS[self._pending_market]
                },
                market=self._pending_market,
            )
        except (HistoricalDataError, ValueError) as exc:
            self.simulation = None
            self.status_label.setText("No se pudo iniciar la simulación histórica.")
            QMessageBox.warning(self, "Simulación no iniciada", str(exc))
            return

        self.symbol_input.clear()
        for symbol in self.simulation.symbols:
            company = COMPANY_NAMES.get(symbol, symbol)
            self.symbol_input.addItem(f"{company} ({symbol})", symbol)
        self.trade_group.setEnabled(True)
        self.trade_status_label.setText("Sin operaciones manuales.")

        first_quote_date = min(bars[0].day for bars in history.values())
        self.clock = AcceleratedSimulationClock(self.simulation.current_date)
        self._clock_started_at = time.monotonic()
        self._elapsed_real_seconds = 0.0
        self._elapsed_hours = 0
        self._refresh_simulation()
        self.status_label.setText(
            f"El reloj inicia el 01-ene; los valores usan como referencia el "
            f"primer cierre común ({first_quote_date:%d-%b-%Y}). "
            "Un día simulado equivale a 5 segundos reales; en días sin "
            "cotización se conserva el último precio."
        )
        self.pause_button.setText("Pausar")
        self.pause_button.setEnabled(True)
        self.timer.start()

    def _advance_clock(self) -> None:
        if self.simulation is None or self.clock is None:
            return

        elapsed = self._elapsed_real_seconds
        if self._clock_started_at is not None:
            elapsed += time.monotonic() - self._clock_started_at
        target_hours = int(elapsed * 24 / SIMULATED_DAY_SECONDS)
        date_advanced = False
        while self._elapsed_hours < target_hours:
            self._elapsed_hours += 1
            clock_date, hour = self.clock.advance_hour()
            self.clock_label.setText(f"Hora simulada: {hour:02d}:00")
            if clock_date <= self.simulation.current_date:
                continue
            try:
                self.simulation.advance_calendar_day()
            except SimulationCompleteError:
                self.timer.stop()
                self._clock_started_at = None
                self.pause_button.setEnabled(False)
                self.status_label.setText("La simulación histórica ha terminado.")
                return
            date_advanced = True
            if self.simulation.is_complete:
                self.timer.stop()
                self._clock_started_at = None
                self.pause_button.setEnabled(False)
                self.status_label.setText("La simulación histórica ha terminado.")
                break
        if date_advanced:
            self._refresh_simulation()

    def _toggle_pause(self) -> None:
        if self.timer.isActive():
            self._advance_clock()
            if not self.timer.isActive():
                return
            if self._clock_started_at is not None:
                self._elapsed_real_seconds += (
                    time.monotonic() - self._clock_started_at
                )
                self._clock_started_at = None
            self.timer.stop()
            self.pause_button.setText("Continuar")
            self.status_label.setText("Simulación pausada.")
        elif self.simulation is not None and not self.simulation.is_complete:
            self._clock_started_at = time.monotonic()
            self.timer.start()
            self.pause_button.setText("Pausar")
            self.status_label.setText("Simulación en curso.")

    def _execute_trade(self, side: str) -> None:
        if self.simulation is None:
            return
        symbol = self.symbol_input.currentData()
        if not isinstance(symbol, str):
            QMessageBox.warning(
                self,
                "Operación no realizada",
                "Selecciona una empresa para operar.",
            )
            return
        try:
            trade = self.simulation.trade(
                symbol, side, self.quantity_input.value()
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Operación no realizada", str(exc))
            return

        self._refresh_simulation()
        self.trade_status_label.setText(
            f"{trade.side}: {trade.quantity} {trade.symbol} a "
            f"USD {trade.unit_price:,.2f} (total USD {trade.total:,.2f})."
        )

    def _refresh_trade_quote(self, _index: int = -1) -> None:
        if self.simulation is None:
            return
        symbol = self.symbol_input.currentData()
        if not isinstance(symbol, str):
            return
        self.position_label.setText(
            f"Tenencia: {self.simulation.holdings[symbol]} | "
            f"Precio: USD {self.simulation.prices[symbol]:,.2f}"
        )
        monthly_change = self.simulation.monthly_price_change(symbol)
        if monthly_change is None:
            self.monthly_change_label.setText(
                "Variación mensual: aún no hay un cierre de referencia "
                "del mes anterior."
            )
        else:
            self.monthly_change_label.setText(
                f"Variación desde {monthly_change.reference_day.isoformat()}: "
                f"USD {monthly_change.absolute_change:+,.2f} "
                f"({monthly_change.percent_change:+.2f}%)."
            )

    def _refresh_simulation(self) -> None:
        if self.simulation is None:
            return

        simulation = self.simulation
        self.date_label.setText(
            f"Fecha simulada: {simulation.current_date.isoformat()}"
        )
        self.summary_label.setText(
            f"Valor total: USD {simulation.current_value:,.2f}  |  "
            f"Efectivo: USD {simulation.cash_balance:,.2f}  |  "
            f"Rentabilidad: {simulation.return_pct:+.2f}%"
        )
        self._refresh_trade_quote()

        self.figure.clear()
        portfolio_axes, price_axes = self.figure.subplots(1, 2)
        portfolio_candles = simulation.candles
        if self.chart_mode_input.currentData() == "candlestick":
            _draw_candles(portfolio_axes, portfolio_candles, width=0.65)
        else:
            portfolio_axes.plot(
                [candle.day for candle in portfolio_candles],
                [candle.close for candle in portfolio_candles],
                color="#2563eb",
                linewidth=1.5,
            )
        portfolio_axes.set_title("Valor total de la cartera")
        portfolio_axes.set_ylabel("USD")
        portfolio_axes.grid(True, alpha=0.25)

        if self.chart_mode_input.currentData() == "candlestick":
            bar_width = 0.72 / len(simulation.symbols)
            legend_handles = []
            for index, symbol in enumerate(simulation.symbols):
                bars = simulation.price_candles(symbol)
                if bars and bars[0].day > simulation.start_date:
                    first_bar = bars[0]
                    bars = (
                        HistoricalBar(
                            simulation.start_date,
                            first_bar.close,
                            first_bar.close,
                            first_bar.close,
                            first_bar.close,
                        ),
                        *bars,
                    )
                color = SYMBOL_CANDLE_COLORS[index % len(SYMBOL_CANDLE_COLORS)]
                offset = (index - (len(simulation.symbols) - 1) / 2) * bar_width
                _draw_candles(
                    price_axes,
                    bars,
                    width=bar_width * 0.8,
                    offset=offset,
                    symbol_color=color,
                )
                legend_handles.append(
                    Patch(facecolor=color, edgecolor=color, label=symbol)
                )
            price_axes.set_title("Velas diarias por acción (hueca: baja)")
            price_axes.legend(
                handles=legend_handles,
                title="Acción (rellena: sube)",
            )
        else:
            for symbol in simulation.symbols:
                bars = simulation.price_candles(symbol)
                price_dates = [bar.day for bar in bars]
                close_prices = [bar.close for bar in bars]
                if bars and bars[0].day > simulation.start_date:
                    price_dates.insert(0, simulation.start_date)
                    close_prices.insert(0, bars[0].close)
                price_axes.plot(
                    price_dates,
                    close_prices,
                    label=symbol,
                    linewidth=1.2,
                )
            price_axes.set_title("Precios históricos de cierre")
            price_axes.legend()
        price_axes.set_ylabel("USD por acción")
        price_axes.grid(True, alpha=0.25)

        for axes in (portfolio_axes, price_axes):
            axes.xaxis.set_major_formatter(mdates.DateFormatter("%d-%b"))
            for tick in axes.get_xticklabels():
                tick.set_rotation(30)
                tick.set_horizontalalignment("right")
        self.figure.tight_layout()
        self.canvas.draw_idle()
