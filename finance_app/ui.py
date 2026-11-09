import re
from pathlib import Path

from PySide6.QtCore import QDate, QThread, Signal, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QDateEdit,
    QInputDialog,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from finance_app.market_data import YFinanceMarketData
from finance_app.models import StockSnapshot
from finance_app.simulator import SimulationError, SimulationLedger


class AnalysisWorker(QThread):
    completed = Signal(list, list)

    def __init__(self, symbols: list[str], market_data: YFinanceMarketData) -> None:
        super().__init__()
        self.symbols = symbols
        self.market_data = market_data

    def run(self) -> None:
        snapshots: list[StockSnapshot] = []
        errors: list[str] = []
        for symbol in self.symbols:
            try:
                snapshots.append(self.market_data.get_snapshot(symbol))
            except Exception as exc:
                errors.append(str(exc))
        self.completed.emit(snapshots, errors)


class FinanceWindow(QMainWindow):
    def __init__(self, ledger: SimulationLedger) -> None:
        super().__init__()
        self.ledger = ledger
        self.market_data = YFinanceMarketData()
        self.snapshots: dict[str, StockSnapshot] = {}
        self.selected_symbol: str | None = None
        self.worker: AnalysisWorker | None = None

        self.setWindowTitle("FinSim - Analisis y trading simulado")
        self.resize(1060, 760)

        root = QWidget()
        layout = QVBoxLayout(root)

        header = QLabel(
            "FinSim  |  Simulador educativo: no envia ordenes reales"
        )
        header.setStyleSheet("font-size: 19px; font-weight: bold;")
        layout.addWidget(header)

        description = QLabel(
            "Senales orientativas basadas en rendimientos historicos; "
            "no son asesoramiento financiero. Las cotizaciones de acciones "
            "de Yahoo Finance se muestran en USD."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        controls = QHBoxLayout()
        self.symbol_input = QLineEdit("AAPL, MSFT, NVDA, GOOGL, AMZN, SPY")
        self.symbol_input.setPlaceholderText("Simbolos separados por coma")
        self.analyze_button = QPushButton("Analizar acciones")
        self.analyze_button.clicked.connect(self.analyze)
        controls.addWidget(self.symbol_input, 1)
        controls.addWidget(self.analyze_button)
        layout.addLayout(controls)

        self.best_labels = QLabel("Mejor compra: --    |    Senal de venta: --")
        self.best_labels.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.best_labels)

        self.stock_table = QTableWidget(0, 6)
        self.stock_table.setHorizontalHeaderLabels(
            ["Simbolo", "Precio USD", "Cambio 1 dia", "Cambio 1 mes",
             "Cambio 3 meses", "Senal"]
        )
        self.stock_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.stock_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.stock_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.stock_table.itemSelectionChanged.connect(self._selection_changed)
        self.stock_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.stock_table, 1)

        trade_controls = QHBoxLayout()
        self.asset_type_input = QComboBox()
        for label, value in (
            ("Acciones", "ACCIONES"),
            ("Certificado de depósito a término (CDT)", "CDT"),
            ("Bonos", "BONOS"),
            ("Títulos de deuda pública (TES)", "TES"),
        ):
            self.asset_type_input.addItem(label, value)
        self.asset_type_input.currentIndexChanged.connect(
            self._asset_type_changed
        )
        self.instrument_input = QLineEdit()
        self.instrument_input.setPlaceholderText("Símbolo o descripción")
        trade_controls.addWidget(QLabel("Activo:"))
        trade_controls.addWidget(self.asset_type_input)
        trade_controls.addWidget(QLabel("Instrumento:"))
        trade_controls.addWidget(self.instrument_input, 1)
        layout.addLayout(trade_controls)

        trade_details = QHBoxLayout()
        self.operation_date_input = QDateEdit()
        self.operation_date_input.setCalendarPopup(True)
        self.operation_date_input.setDisplayFormat("yyyy-MM-dd")
        self.operation_date_input.setDate(QDate.currentDate())
        self.quantity_input = QDoubleSpinBox()
        self.quantity_input.setRange(0.001, 1_000_000)
        self.quantity_input.setDecimals(3)
        self.quantity_input.setValue(1)
        self.price_input = QDoubleSpinBox()
        self.price_input.setRange(0.01, 1_000_000_000_000)
        self.price_input.setDecimals(4)
        self.commission_input = QDoubleSpinBox()
        self.commission_input.setRange(0, 1_000_000_000_000)
        self.commission_input.setDecimals(2)
        self.currency_input = QComboBox()
        self.currency_input.addItems(["USD", "COP"])
        trade_details.addWidget(QLabel("Fecha:"))
        trade_details.addWidget(self.operation_date_input)
        trade_details.addWidget(QLabel("Cantidad:"))
        trade_details.addWidget(self.quantity_input)
        trade_details.addWidget(QLabel("Valor unitario:"))
        trade_details.addWidget(self.price_input)
        trade_details.addWidget(QLabel("Comisión:"))
        trade_details.addWidget(self.commission_input)
        trade_details.addWidget(QLabel("Moneda:"))
        trade_details.addWidget(self.currency_input)
        layout.addLayout(trade_details)

        trade_buttons = QHBoxLayout()
        self.buy_button = QPushButton("Compra simulada")
        self.sell_button = QPushButton("Venta simulada")
        self.buy_button.clicked.connect(lambda: self._execute_trade("COMPRA"))
        self.sell_button.clicked.connect(lambda: self._execute_trade("VENTA"))
        self.initial_cash_button = QPushButton("Configurar saldo inicial")
        self.initial_cash_button.clicked.connect(self._configure_initial_cash)
        trade_buttons.addWidget(self.buy_button)
        trade_buttons.addWidget(self.sell_button)
        trade_buttons.addWidget(self.initial_cash_button)
        trade_buttons.addStretch(1)
        layout.addLayout(trade_buttons)

        self.cash_label = QLabel()
        self.positions_label = QLabel()
        layout.addWidget(self.cash_label)
        layout.addWidget(self.positions_label)

        self.trade_log = QTableWidget(0, 9)
        self.trade_log.setHorizontalHeaderLabels(
            [
                "Fecha operación",
                "Tipo",
                "Operación",
                "Instrumento",
                "Moneda",
                "Cantidad",
                "Valor unitario",
                "Comisión",
                "Valor transacción",
            ]
        )
        self.trade_log.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.trade_log.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(QLabel("Registro local de operaciones simuladas"))
        layout.addWidget(self.trade_log)

        self.setCentralWidget(root)
        self._asset_type_changed()
        self._refresh_portfolio()

    def analyze(self) -> None:
        raw_symbols = [
            value.strip().upper()
            for value in self.symbol_input.text().split(",")
            if value.strip()
        ]
        symbols = list(dict.fromkeys(raw_symbols))
        invalid = [
            symbol for symbol in symbols
            if not re.fullmatch(r"[A-Z0-9.^=-]{1,20}", symbol)
        ]
        if not symbols:
            QMessageBox.warning(self, "Sin simbolos", "Escribe uno o mas simbolos.")
            return
        if invalid:
            QMessageBox.warning(
                self,
                "Simbolo no valido",
                "Revisa estos simbolos: " + ", ".join(invalid),
            )
            return

        self.analyze_button.setEnabled(False)
        self.analyze_button.setText("Consultando Yahoo Finance...")
        self.worker = AnalysisWorker(symbols, self.market_data)
        self.worker.completed.connect(self._analysis_completed)
        self.worker.finished.connect(self._analysis_finished)
        self.worker.start()

    def _analysis_finished(self) -> None:
        self.analyze_button.setEnabled(True)
        self.analyze_button.setText("Analizar acciones")

    def _analysis_completed(
        self, snapshots: list[StockSnapshot], errors: list[str]
    ) -> None:
        self.snapshots = {snapshot.symbol: snapshot for snapshot in snapshots}
        ordered = sorted(snapshots, key=lambda snapshot: snapshot.score, reverse=True)

        self.stock_table.setRowCount(len(ordered))
        for row, snapshot in enumerate(ordered):
            values = (
                snapshot.symbol,
                f"${snapshot.price:,.2f}",
                f"{snapshot.change_1d_pct:+.2f}%",
                f"{snapshot.change_1m_pct:+.2f}%",
                f"{snapshot.change_3m_pct:+.2f}%",
                f"{snapshot.recommendation} ({snapshot.score:+.2f})",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, snapshot.symbol)
                self.stock_table.setItem(row, column, item)
        self.stock_table.resizeColumnsToContents()

        buys = [item for item in snapshots if item.recommendation == "COMPRA"]
        sells = [item for item in snapshots if item.recommendation == "VENTA"]
        best_buy = max(buys, key=lambda item: item.score) if buys else None
        best_sell = min(sells, key=lambda item: item.score) if sells else None
        buy_text = (
            f"{best_buy.symbol} ({best_buy.score:+.2f})"
            if best_buy else "ninguna"
        )
        sell_text = (
            f"{best_sell.symbol} ({best_sell.score:+.2f})"
            if best_sell else "ninguna"
        )
        self.best_labels.setText(
            f"Mejor compra por la regla: {buy_text}    |    "
            f"Senal de venta mas fuerte: {sell_text}"
        )
        if errors:
            QMessageBox.warning(
                self,
                "Datos incompletos",
                "No se pudieron analizar algunos simbolos:\n\n"
                + "\n".join(errors),
            )

    def _selection_changed(self) -> None:
        items = self.stock_table.selectedItems()
        if not items:
            self.selected_symbol = None
            return
        symbol = self.stock_table.item(items[0].row(), 0).data(
            Qt.ItemDataRole.UserRole
        )
        self.selected_symbol = symbol
        self.asset_type_input.setCurrentIndex(
            self.asset_type_input.findData("ACCIONES")
        )
        self.instrument_input.setText(symbol)
        self.price_input.setValue(self.snapshots[symbol].price)

    def _asset_type_changed(self) -> None:
        asset_type = self.asset_type_input.currentData()
        self.currency_input.setCurrentText(
            "USD" if asset_type == "ACCIONES" else "COP"
        )

    def _configure_initial_cash(self) -> None:
        currency = self.currency_input.currentText()
        amount, accepted = QInputDialog.getText(
            self,
            "Saldo inicial simulado",
            f"Saldo inicial para {currency} (solo se puede cambiar "
            "antes de registrar operaciones en esa moneda):",
        )
        if not accepted:
            return
        try:
            configured_amount = self.ledger.set_initial_cash(currency, amount)
        except SimulationError as exc:
            QMessageBox.warning(self, "Saldo no actualizado", str(exc))
            return
        QMessageBox.information(
            self,
            "Saldo actualizado",
            f"Saldo inicial de {currency}: {configured_amount:,.2f}.",
        )
        self._refresh_portfolio()

    def _execute_trade(self, side: str) -> None:
        symbol = self.instrument_input.text().strip()
        if not symbol:
            QMessageBox.information(
                self,
                "Falta el instrumento",
                "Escribe el símbolo o nombre del activo.",
            )
            return
        try:
            trade = self.ledger.trade(
                symbol,
                side,
                self.quantity_input.value(),
                self.price_input.value(),
                asset_type=self.asset_type_input.currentData(),
                operation_date=self.operation_date_input.date().toString(
                    "yyyy-MM-dd"
                ),
                commission=self.commission_input.value(),
                currency=self.currency_input.currentText(),
            )
        except SimulationError as exc:
            QMessageBox.warning(self, "Operacion no realizada", str(exc))
            return
        QMessageBox.information(
            self,
            "Operacion simulada",
            f"{trade.side} de {trade.quantity} {trade.asset_type} "
            f"{trade.symbol} a {trade.price:,.2f} {trade.currency} por unidad.\n"
            f"Valor: {trade.total:,.2f} {trade.currency}; "
            f"comisión: {trade.commission:,.2f} {trade.currency}.\n"
            "No se envio ninguna orden real.",
        )
        self._refresh_portfolio()

    def _refresh_portfolio(self) -> None:
        self.cash_label.setText(
            f"Saldos simulados — USD: {self.ledger.cash_balance('USD'):,.2f}  |  "
            f"COP: {self.ledger.cash_balance('COP'):,.2f}"
        )
        positions = self.ledger.positions()
        description = ", ".join(
            f"{instrument}: {quantity}"
            for instrument, quantity in sorted(positions.items())
        )
        self.positions_label.setText(
            "Posiciones simuladas: " + (description or "ninguna")
        )

        trades = self.ledger.recent_trades(15)
        self.trade_log.setRowCount(len(trades))
        for row, trade in enumerate(trades):
            values = (
                trade.operation_date,
                trade.asset_type,
                trade.side,
                trade.symbol,
                trade.currency,
                f"{trade.quantity:f}",
                f"{trade.price:,.4f}",
                f"{trade.commission:,.2f}",
                f"{trade.total:,.2f}",
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
