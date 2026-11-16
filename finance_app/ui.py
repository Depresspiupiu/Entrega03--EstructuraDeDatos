from decimal import Decimal
from pathlib import Path

import matplotlib.dates as mdates
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.figure import Figure
from PySide6.QtCore import QDate, QThread, Signal, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from finance_app.market_data import YFinanceMarketData
from finance_app.models import StockCandle, StockSnapshot
from finance_app.simulator import SimulationError, SimulationLedger

STOCKS = {"KO": "Coca-Cola", "NKE": "Nike"}


class MarketDataWorker(QThread):
    completed = Signal(object, object)

    def __init__(self, market_data: YFinanceMarketData) -> None:
        super().__init__()
        self.market_data = market_data

    def run(self) -> None:
        results, errors = self.market_data.get_histories(tuple(STOCKS))
        self.completed.emit(results, errors)


class FinanceWindow(QMainWindow):
    def __init__(self, ledger: SimulationLedger) -> None:
        super().__init__()
        self.ledger = ledger
        self.market_data = YFinanceMarketData()
        self.snapshots: dict[str, StockSnapshot] = {}
        self.candles: dict[str, tuple[StockCandle, ...]] = {}
        self.worker: MarketDataWorker | None = None

        self.setWindowTitle("FinSim | Coca-Cola y Nike")
        self.resize(1180, 900)

        content = QWidget()
        layout = QVBoxLayout(content)

        header = QLabel("FinSim | Compraventa simulada de KO y NKE")
        header.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(header)

        description = QLabel(
            "Consulta cotizaciones diarias OHLC de los últimos seis meses, "
            "visualiza velas y registra compras y ventas simuladas en USD. "
            "No se envían órdenes reales ni se ofrece asesoramiento financiero."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        quote_controls = QHBoxLayout()
        self.refresh_button = QPushButton("Actualizar cotizaciones")
        self.refresh_button.clicked.connect(self.refresh_quotes)
        self.symbol_input = QComboBox()
        for symbol, company in STOCKS.items():
            self.symbol_input.addItem(f"{company} ({symbol})", symbol)
        self.symbol_input.currentIndexChanged.connect(self._refresh_chart)
        self.current_price_label = QLabel("Precio actual: --")
        quote_controls.addWidget(self.refresh_button)
        quote_controls.addWidget(QLabel("Acción seleccionada:"))
        quote_controls.addWidget(self.symbol_input)
        quote_controls.addWidget(self.current_price_label, 1)
        layout.addLayout(quote_controls)

        self.stock_table = QTableWidget(0, 4)
        self.stock_table.setHorizontalHeaderLabels(
            ["Empresa", "Símbolo", "Último precio (USD)", "Cambio diario"]
        )
        self.stock_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.stock_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.stock_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.stock_table.itemSelectionChanged.connect(self._stock_selected)
        self.stock_table.horizontalHeader().setStretchLastSection(True)
        market_group = QGroupBox("Acciones disponibles")
        market_layout = QVBoxLayout(market_group)
        market_layout.addWidget(self.stock_table)
        layout.addWidget(market_group)

        self.figure = Figure(figsize=(10, 5))
        self.figure.subplots_adjust(bottom=0.2)
        self.canvas = FigureCanvasQTAgg(self.figure)
        chart_group = QGroupBox("Gráfico de velas OHLC")
        chart_layout = QVBoxLayout(chart_group)
        chart_layout.addWidget(self.canvas)
        layout.addWidget(chart_group, 1)

        trade_controls = QHBoxLayout()
        self.operation_date_input = QDateEdit()
        self.operation_date_input.setCalendarPopup(True)
        self.operation_date_input.setDisplayFormat("yyyy-MM-dd")
        self.operation_date_input.setDate(QDate.currentDate())
        self.quantity_input = QDoubleSpinBox()
        self.quantity_input.setRange(0.001, 1_000_000)
        self.quantity_input.setDecimals(3)
        self.quantity_input.setValue(1)
        self.commission_input = QDoubleSpinBox()
        self.commission_input.setRange(0, 1_000_000_000)
        self.commission_input.setDecimals(2)
        self.buy_button = QPushButton("Comprar (simulado)")
        self.buy_button.clicked.connect(lambda: self._execute_trade("COMPRA"))
        self.sell_button = QPushButton("Vender (simulado)")
        self.sell_button.clicked.connect(lambda: self._execute_trade("VENTA"))
        self.initial_cash_button = QPushButton("Configurar capital inicial")
        self.initial_cash_button.clicked.connect(self._configure_initial_cash)
        for widget in (
            QLabel("Fecha:"),
            self.operation_date_input,
            QLabel("Cantidad:"),
            self.quantity_input,
            QLabel("Comisión (USD):"),
            self.commission_input,
            self.buy_button,
            self.sell_button,
            self.initial_cash_button,
        ):
            trade_controls.addWidget(widget)
        trading_group = QGroupBox("Operar la acción seleccionada")
        trading_group.setLayout(trade_controls)
        layout.addWidget(trading_group)

        self.portfolio_label = QLabel()
        self.portfolio_label.setWordWrap(True)
        layout.addWidget(self.portfolio_label)

        self.positions_table = QTableWidget(0, 7)
        self.positions_table.setHorizontalHeaderLabels(
            [
                "Acción",
                "Cantidad",
                "Costo promedio (USD)",
                "Precio actual (USD)",
                "Valor actual (USD)",
                "Ganancia/pérdida no realizada (USD)",
                "Rentabilidad no realizada",
            ]
        )
        self.positions_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.positions_table.horizontalHeader().setStretchLastSection(True)
        positions_group = QGroupBox("Rentabilidad por acción")
        positions_layout = QVBoxLayout(positions_group)
        positions_layout.addWidget(self.positions_table)
        layout.addWidget(positions_group)

        self.trade_log = QTableWidget(0, 7)
        self.trade_log.setHorizontalHeaderLabels(
            [
                "Fecha",
                "Operación",
                "Símbolo",
                "Cantidad",
                "Precio (USD)",
                "Comisión (USD)",
                "Total (USD)",
            ]
        )
        self.trade_log.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.trade_log.horizontalHeader().setStretchLastSection(True)
        trades_group = QGroupBox("Historial de operaciones simuladas")
        trades_layout = QVBoxLayout(trades_group)
        trades_layout.addWidget(self.trade_log)
        layout.addWidget(trades_group)

        self.status_label = QLabel("Descargando cotizaciones...")
        layout.addWidget(self.status_label)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(content)
        self.setCentralWidget(scroll_area)

        self._refresh_market_table()
        self._refresh_portfolio()
        self._refresh_chart()
        self.refresh_quotes()

    def refresh_quotes(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        self.refresh_button.setEnabled(False)
        self.refresh_button.setText("Consultando Yahoo Finance...")
        self.status_label.setText("Descargando cotizaciones de KO y NKE...")
        self.worker = MarketDataWorker(self.market_data)
        self.worker.completed.connect(self._market_data_completed)
        self.worker.finished.connect(self._market_data_finished)
        self.worker.start()

    def _market_data_finished(self) -> None:
        self.refresh_button.setEnabled(True)
        self.refresh_button.setText("Actualizar cotizaciones")

    def _market_data_completed(
        self,
        results: dict[str, tuple[StockSnapshot, tuple[StockCandle, ...]]],
        errors: list[str],
    ) -> None:
        self.snapshots = {
            symbol: result[0] for symbol, result in results.items()
        }
        self.candles = {
            symbol: result[1] for symbol, result in results.items()
        }
        for symbol, snapshot in self.snapshots.items():
            try:
                self.ledger.update_valuation(
                    symbol, "ACCIONES", "USD", snapshot.price
                )
            except SimulationError as exc:
                errors.append(str(exc))

        self._refresh_market_table()
        self._refresh_chart()
        self._refresh_portfolio()
        if errors:
            self.status_label.setText(
                "No se pudieron actualizar todos los datos."
            )
            QMessageBox.warning(
                self,
                "Cotizaciones incompletas",
                "No se pudieron obtener o actualizar algunos datos:\n\n"
                + "\n".join(errors),
            )
        else:
            self.status_label.setText(
                "Cotizaciones actualizadas desde Yahoo Finance."
            )

    def _refresh_market_table(self) -> None:
        self.stock_table.setRowCount(len(STOCKS))
        for row, (symbol, company) in enumerate(STOCKS.items()):
            snapshot = self.snapshots.get(symbol)
            values = (
                company,
                symbol,
                f"${snapshot.price:,.2f}" if snapshot else "N/D",
                f"{snapshot.change_1d_pct:+.2f}%" if snapshot else "N/D",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 1:
                    item.setData(Qt.ItemDataRole.UserRole, symbol)
                self.stock_table.setItem(row, column, item)
        self.stock_table.resizeColumnsToContents()

    def _stock_selected(self) -> None:
        items = self.stock_table.selectedItems()
        if not items:
            return
        symbol = self.stock_table.item(items[0].row(), 1).data(
            Qt.ItemDataRole.UserRole
        )
        index = self.symbol_input.findData(symbol)
        if index >= 0:
            self.symbol_input.setCurrentIndex(index)

    def _refresh_chart(self) -> None:
        self.figure.clear()
        axes = self.figure.add_subplot(111)
        symbol = self.symbol_input.currentData()
        candles = self.candles.get(symbol, ())
        snapshot = self.snapshots.get(symbol)
        if not candles:
            axes.text(
                0.5,
                0.5,
                "Actualiza las cotizaciones para mostrar el gráfico.",
                ha="center",
                va="center",
                transform=axes.transAxes,
            )
            axes.set_axis_off()
            self.current_price_label.setText("Precio actual: N/D")
        else:
            dates = [mdates.date2num(item.day) for item in candles]
            wicks = []
            bodies = []
            colors = []
            for x, candle in zip(dates, candles):
                color = "#16a34a" if candle.close >= candle.open else "#dc2626"
                lower_body = min(candle.open, candle.close)
                body_height = max(
                    abs(candle.close - candle.open),
                    max(candle.close, candle.open) * 0.00001,
                )
                half_width = 0.325
                wicks.append(((x, candle.low), (x, candle.high)))
                bodies.append(
                    (
                        (x - half_width, lower_body),
                        (x + half_width, lower_body),
                        (x + half_width, lower_body + body_height),
                        (x - half_width, lower_body + body_height),
                    )
                )
                colors.append(color)
            axes.add_collection(
                LineCollection(wicks, colors=colors, linewidths=1),
                autolim=False,
            )
            axes.add_collection(
                PolyCollection(
                    bodies,
                    facecolors=colors,
                    edgecolors=colors,
                    linewidths=0.7,
                ),
                autolim=False,
            )
            axes.update_datalim(
                (
                    (dates[0] - 0.325, min(item.low for item in candles)),
                    (dates[-1] + 0.325, max(item.high for item in candles)),
                )
            )
            axes.autoscale_view()
            axes.set_title(
                f"{STOCKS[symbol]} ({symbol}) · últimos seis meses"
            )
            axes.set_ylabel("Precio por acción (USD)")
            axes.xaxis_date()
            axes.xaxis.set_major_formatter(mdates.DateFormatter("%d-%b"))
            for tick in axes.get_xticklabels():
                tick.set_rotation(30)
                tick.set_horizontalalignment("right")
            axes.grid(True, alpha=0.25)
            if snapshot is not None:
                self.current_price_label.setText(
                    f"Último cierre: ${snapshot.price:,.2f} USD"
                )
        self.canvas.draw()

    def _configure_initial_cash(self) -> None:
        amount, accepted = QInputDialog.getText(
            self,
            "Capital inicial simulado",
            "Capital inicial en USD (solo puede cambiarse antes de operar):",
        )
        if not accepted:
            return
        try:
            configured_amount = self.ledger.set_initial_cash("USD", amount)
        except SimulationError as exc:
            QMessageBox.warning(self, "Capital no actualizado", str(exc))
            return
        self._refresh_portfolio()
        QMessageBox.information(
            self,
            "Capital actualizado",
            f"Capital inicial: ${configured_amount:,.2f} USD.",
        )

    def _execute_trade(self, side: str) -> None:
        symbol = self.symbol_input.currentData()
        snapshot = self.snapshots.get(symbol)
        if snapshot is None:
            QMessageBox.warning(
                self,
                "Cotización no disponible",
                "Actualiza las cotizaciones antes de operar esta acción.",
            )
            return
        try:
            trade = self.ledger.trade(
                symbol,
                side,
                self.quantity_input.value(),
                snapshot.price,
                asset_type="ACCIONES",
                operation_date=self.operation_date_input.date().toString(
                    "yyyy-MM-dd"
                ),
                commission=self.commission_input.value(),
                currency="USD",
            )
        except SimulationError as exc:
            QMessageBox.warning(self, "Operación no realizada", str(exc))
            return

        self._refresh_portfolio()
        QMessageBox.information(
            self,
            "Operación simulada",
            f"{trade.side} de {trade.quantity:f} {trade.symbol} a "
            f"${trade.price:,.2f} USD.\n"
            f"Total: ${trade.total:,.2f} USD; "
            f"comisión: ${trade.commission:,.2f} USD.\n"
            "No se envió ninguna orden real.",
        )

    def _refresh_portfolio(self) -> None:
        summary = self.ledger.portfolio_summary("USD")
        profit = summary.total_value - summary.initial_cash
        self.portfolio_label.setText(
            f"Saldo disponible: ${summary.cash_balance:,.2f} USD  |  "
            f"Valor total de cartera: ${summary.total_value:,.2f} USD  |  "
            f"Ganancia/pérdida acumulada: ${profit:+,.2f} USD "
            f"({summary.cumulative_return_pct:+.2f}%). "
            "El total conserva cualquier operación histórica de esta base local."
        )

        positions = {
            position.symbol: position
            for position in summary.positions
            if position.asset_type == "ACCIONES"
            and position.symbol in STOCKS
        }
        self.positions_table.setRowCount(len(STOCKS))
        for row, symbol in enumerate(STOCKS):
            position = positions.get(symbol)
            snapshot = self.snapshots.get(symbol)
            if position is None:
                values = (
                    f"{STOCKS[symbol]} ({symbol})",
                    "0",
                    "--",
                    f"${snapshot.price:,.2f}" if snapshot else "N/D",
                    "$0.00",
                    "--",
                    "--",
                )
            else:
                average_cost = position.cost_basis / position.quantity
                if snapshot is None:
                    current_price = "N/D"
                    market_value = "N/D"
                    unrealized_profit = "N/D"
                    unrealized_return = "N/D"
                else:
                    market_value_value = position.quantity * Decimal(
                        str(snapshot.price)
                    )
                    unrealized_value = market_value_value - position.cost_basis
                    unrealized_pct = (
                        unrealized_value / position.cost_basis * 100
                        if position.cost_basis
                        else Decimal("0")
                    )
                    current_price = f"${snapshot.price:,.2f}"
                    market_value = f"${market_value_value:,.2f}"
                    unrealized_profit = f"${unrealized_value:+,.2f}"
                    unrealized_return = f"{unrealized_pct:+.2f}%"
                values = (
                    f"{STOCKS[symbol]} ({symbol})",
                    f"{position.quantity:f}",
                    f"${average_cost:,.2f}",
                    current_price,
                    market_value,
                    unrealized_profit,
                    unrealized_return,
                )
            for column, value in enumerate(values):
                self.positions_table.setItem(
                    row, column, QTableWidgetItem(value)
                )
        self.positions_table.resizeColumnsToContents()

        trades = [
            trade
            for trade in self.ledger.recent_trades(100)
            if trade.asset_type == "ACCIONES" and trade.symbol in STOCKS
        ][:20]
        self.trade_log.setRowCount(len(trades))
        for row, trade in enumerate(trades):
            values = (
                trade.operation_date,
                trade.side,
                trade.symbol,
                f"{trade.quantity:f}",
                f"${trade.price:,.2f}",
                f"${trade.commission:,.2f}",
                f"${trade.total:,.2f}",
            )
            for column, value in enumerate(values):
                self.trade_log.setItem(row, column, QTableWidgetItem(value))
        self.trade_log.resizeColumnsToContents()


def create_application(database_path: Path) -> QApplication:
    application = QApplication.instance() or QApplication([])
    window = FinanceWindow(SimulationLedger(database_path))
    window.show()
    application.exec()
    return application
