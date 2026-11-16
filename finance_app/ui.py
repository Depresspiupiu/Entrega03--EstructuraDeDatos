import re
import sqlite3
from datetime import date
from pathlib import Path

import matplotlib.dates as mdates
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import QDate, QThread, QTimer, Signal, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QDateEdit,
    QGroupBox,
    QInputDialog,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from finance_app.historical_simulation import (
    COMPANY_NAMES,
    MARKET_SYMBOLS,
    HistoricalBar,
    HistoricalDataError,
    HistoricalPortfolioSimulation,
    SimulationCompleteError,
    fetch_2023_history,
)
from finance_app.historical_sessions import (
    HistoricalSessionError,
    HistoricalSessionStore,
)
from finance_app.market_data import YFinanceMarketData
from finance_app.models import StockSnapshot
from finance_app.simulator import SimulationError, SimulationLedger


class HistoricalDataWorker(QThread):
    completed = Signal(object, str)

    def __init__(self, symbols: list[str]) -> None:
        super().__init__()
        self.symbols = symbols

    def run(self) -> None:
        try:
            history = fetch_2023_history(self.symbols)
        except Exception as exc:
            self.completed.emit(None, str(exc))
            return
        self.completed.emit(history, "")


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
        self.historical_session_store = HistoricalSessionStore(
            ledger.database_path
        )
        self.market_data = YFinanceMarketData()
        self.snapshots: dict[str, StockSnapshot] = {}
        self.selected_symbol: str | None = None
        self.worker: AnalysisWorker | None = None

        self.setWindowTitle("FinSim - Analisis y trading simulado")
        self.resize(1220, 900)

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

        valuation_controls = QHBoxLayout()
        self.valuation_input = QDoubleSpinBox()
        self.valuation_input.setRange(0.01, 1_000_000_000_000)
        self.valuation_input.setDecimals(4)
        self.valuation_button = QPushButton("Actualizar valoración")
        self.valuation_button.clicked.connect(self._update_valuation)
        self.annual_rate_input = QDoubleSpinBox()
        self.annual_rate_input.setRange(0, 1_000)
        self.annual_rate_input.setDecimals(4)
        self.maturity_input = QDateEdit()
        self.maturity_input.setCalendarPopup(True)
        self.maturity_input.setDisplayFormat("yyyy-MM-dd")
        self.maturity_input.setDate(QDate.currentDate())
        self.save_terms_button = QPushButton("Guardar condiciones de renta fija")
        self.save_terms_button.clicked.connect(self._save_fixed_terms)
        valuation_controls.addWidget(QLabel("Valor actual unitario:"))
        valuation_controls.addWidget(self.valuation_input)
        valuation_controls.addWidget(self.valuation_button)
        valuation_controls.addWidget(QLabel("Tasa E.A. (%):"))
        valuation_controls.addWidget(self.annual_rate_input)
        valuation_controls.addWidget(QLabel("Vencimiento:"))
        valuation_controls.addWidget(self.maturity_input)
        valuation_controls.addWidget(self.save_terms_button)
        layout.addLayout(valuation_controls)

        income_controls = QHBoxLayout()
        self.income_type_input = QComboBox()
        for label, value in (
            ("Dividendo", "DIVIDENDO"),
            ("Interés", "INTERES"),
            ("Pago de capital", "PAGO_CAPITAL"),
        ):
            self.income_type_input.addItem(label, value)
        self.income_type_input.currentIndexChanged.connect(
            self._income_type_changed
        )
        self.income_amount_input = QDoubleSpinBox()
        self.income_amount_input.setRange(0.01, 1_000_000_000_000)
        self.income_amount_input.setDecimals(2)
        self.income_commission_input = QDoubleSpinBox()
        self.income_commission_input.setRange(0, 1_000_000_000_000)
        self.income_commission_input.setDecimals(2)
        self.repaid_quantity_input = QDoubleSpinBox()
        self.repaid_quantity_input.setRange(0.001, 1_000_000)
        self.repaid_quantity_input.setDecimals(3)
        self.record_income_button = QPushButton("Registrar rendimiento")
        self.record_income_button.clicked.connect(self._record_income)
        income_controls.addWidget(QLabel("Rendimiento:"))
        income_controls.addWidget(self.income_type_input)
        income_controls.addWidget(QLabel("Valor bruto:"))
        income_controls.addWidget(self.income_amount_input)
        income_controls.addWidget(QLabel("Comisión:"))
        income_controls.addWidget(self.income_commission_input)
        income_controls.addWidget(QLabel("Unidades amortizadas:"))
        income_controls.addWidget(self.repaid_quantity_input)
        income_controls.addWidget(self.record_income_button)
        layout.addLayout(income_controls)

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
        self.positions_label.setWordWrap(True)
        self.portfolio_label = QLabel()
        self.portfolio_label.setWordWrap(True)
        layout.addWidget(self.cash_label)
        layout.addWidget(self.portfolio_label)
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

        self.income_log = QTableWidget(0, 8)
        self.income_log.setHorizontalHeaderLabels(
            [
                "Fecha",
                "Tipo de activo",
                "Instrumento",
                "Rendimiento",
                "Moneda",
                "Valor bruto",
                "Unidades amortizadas",
                "Comisión",
            ]
        )
        self.income_log.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.income_log.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(QLabel("Historial de dividendos, intereses y pagos de capital"))
        layout.addWidget(self.income_log)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(root)
        tabs = QTabWidget()
        tabs.addTab(scroll_area, "Portafolio y operaciones")
        tabs.addTab(self._build_historical_tab(), "Simulación histórica 2023")
        self.setCentralWidget(tabs)
        self._income_type_changed()
        self._asset_type_changed()
        self._refresh_portfolio()

    def _build_historical_tab(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        description = QLabel(
            "Precios históricos de 2023 con una ligera variación aleatoria. "
            "Selecciona empresas para las tenencias iniciales; durante la sesión "
            "podrás operar cualquiera de las empresas de ese mercado."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        controls = QHBoxLayout()
        self.historical_market_input = QComboBox()
        self.historical_market_input.addItem("NASDAQ", "NASDAQ")
        self.historical_market_input.addItem("NYSE", "NYSE")
        self.historical_market_input.currentIndexChanged.connect(
            self._update_historical_market
        )
        self.historical_cash_input = QDoubleSpinBox()
        self.historical_cash_input.setRange(1, 1_000_000_000_000)
        self.historical_cash_input.setDecimals(2)
        self.historical_cash_input.setValue(100_000)
        self.historical_start_date_input = QDateEdit()
        self.historical_start_date_input.setCalendarPopup(True)
        self.historical_start_date_input.setDisplayFormat("yyyy-MM-dd")
        self.historical_start_date_input.setDate(QDate(2023, 1, 3))
        self.historical_start_date_input.setMinimumDate(QDate(2023, 1, 1))
        self.historical_start_date_input.setMaximumDate(QDate(2023, 12, 28))
        self.historical_start_button = QPushButton("Iniciar simulación")
        self.historical_start_button.clicked.connect(
            self._start_historical_simulation
        )
        controls.addWidget(QLabel("Mercado:"))
        controls.addWidget(self.historical_market_input)
        controls.addWidget(QLabel("Capital inicial (USD):"))
        controls.addWidget(self.historical_cash_input)
        controls.addWidget(QLabel("Fecha inicial:"))
        controls.addWidget(self.historical_start_date_input)
        controls.addWidget(self.historical_start_button)
        setup_group = QGroupBox("1. Configuración de la sesión")
        setup_group.setLayout(controls)
        layout.addWidget(setup_group)

        self.historical_checkboxes: dict[str, QCheckBox] = {}
        company_controls = QHBoxLayout()
        for symbol, company in COMPANY_NAMES.items():
            checkbox = QCheckBox(f"{company} ({symbol})")
            checkbox.setChecked(True)
            self.historical_checkboxes[symbol] = checkbox
            company_controls.addWidget(checkbox)
        holdings_selection_group = QGroupBox(
            "Tenencias iniciales aleatorias (0–50 acciones)"
        )
        holdings_selection_group.setLayout(company_controls)
        layout.addWidget(holdings_selection_group)

        simulation_controls = QHBoxLayout()
        self.historical_chart_type_input = QComboBox()
        self.historical_chart_type_input.addItem("Clásico (línea)", "line")
        self.historical_chart_type_input.addItem("Velas", "candles")
        self.historical_chart_type_input.currentIndexChanged.connect(
            self._refresh_historical_chart
        )
        self.historical_next_button = QPushButton("Avanzar un día")
        self.historical_next_button.setEnabled(False)
        self.historical_next_button.clicked.connect(self._advance_historical_day)
        simulation_controls.addWidget(QLabel("Gráfico:"))
        simulation_controls.addWidget(self.historical_chart_type_input)
        simulation_controls.addWidget(self.historical_next_button)
        simulation_controls.addStretch(1)
        clock_group = QGroupBox("2. Reproducción del mercado")
        clock_group.setLayout(simulation_controls)
        layout.addWidget(clock_group)

        self.historical_summary_label = QLabel(
            "Elige un mercado, las empresas y la fecha para iniciar."
        )
        self.historical_summary_label.setWordWrap(True)
        self.historical_figure = Figure(figsize=(10, 5))
        self.historical_canvas = FigureCanvasQTAgg(self.historical_figure)
        chart_layout = QVBoxLayout()
        chart_layout.addWidget(self.historical_summary_label)
        chart_layout.addWidget(self.historical_canvas, 1)
        chart_group = QGroupBox("3. Cotización de la empresa seleccionada")
        chart_group.setLayout(chart_layout)
        layout.addWidget(chart_group, 1)

        portfolio_controls = QHBoxLayout()
        self.historical_symbol_input = QComboBox()
        self.historical_symbol_input.currentIndexChanged.connect(
            self._historical_symbol_changed
        )
        self.historical_quantity_input = QSpinBox()
        self.historical_quantity_input.setRange(1, 50)
        self.historical_quantity_input.setValue(1)
        self.historical_quantity_input.valueChanged.connect(
            self._refresh_historical_trade_controls
        )
        self.historical_buy_button = QPushButton("Comprar")
        self.historical_buy_button.clicked.connect(
            lambda: self._trade_historical_asset("COMPRA")
        )
        self.historical_sell_button = QPushButton("Vender")
        self.historical_sell_button.clicked.connect(
            lambda: self._trade_historical_asset("VENTA")
        )
        self.historical_buy_button.setEnabled(False)
        self.historical_sell_button.setEnabled(False)
        portfolio_controls.addWidget(QLabel("Empresa:"))
        portfolio_controls.addWidget(self.historical_symbol_input)
        portfolio_controls.addWidget(QLabel("Cantidad (1–50):"))
        portfolio_controls.addWidget(self.historical_quantity_input)
        portfolio_controls.addWidget(self.historical_buy_button)
        portfolio_controls.addWidget(self.historical_sell_button)
        portfolio_controls.addStretch(1)
        self.historical_trade_hint = QLabel(
            "Inicia una sesión para consultar el precio y operar."
        )

        self.historical_holdings_table = QTableWidget(0, 4)
        self.historical_holdings_table.setHorizontalHeaderLabels(
            ["Empresa", "Acciones", "Precio (USD)", "Valor (USD)"]
        )
        self.historical_holdings_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.historical_holdings_table.horizontalHeader().setStretchLastSection(
            True
        )
        trading_layout = QVBoxLayout()
        trading_layout.addLayout(portfolio_controls)
        trading_layout.addWidget(self.historical_trade_hint)
        trading_layout.addWidget(self.historical_holdings_table)
        trading_group = QGroupBox(
            "4. Operar durante la sesión (todas las empresas del mercado)"
        )
        trading_group.setLayout(trading_layout)
        layout.addWidget(trading_group)

        session_controls = QHBoxLayout()
        self.historical_session_input = QComboBox()
        self.historical_save_session_button = QPushButton("Guardar sesión")
        self.historical_save_session_button.clicked.connect(
            self._save_historical_session
        )
        self.historical_load_session_button = QPushButton("Cargar sesión")
        self.historical_load_session_button.clicked.connect(
            self._load_historical_session
        )
        self.historical_save_session_button.setEnabled(False)
        self.historical_load_session_button.setEnabled(False)
        session_controls.addWidget(QLabel("Sesión guardada:"))
        session_controls.addWidget(self.historical_session_input, 1)
        session_controls.addWidget(self.historical_save_session_button)
        session_controls.addWidget(self.historical_load_session_button)
        sessions_group = QGroupBox("Guardar o recuperar una sesión")
        sessions_group.setLayout(session_controls)
        layout.addWidget(sessions_group)

        self.historical_trade_log = QTableWidget(0, 5)
        self.historical_trade_log.setHorizontalHeaderLabels(
            ["Fecha", "Empresa", "Operación", "Cantidad", "Precio (USD)"]
        )
        self.historical_trade_log.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.historical_trade_log.horizontalHeader().setStretchLastSection(True)
        trade_log_layout = QVBoxLayout()
        trade_log_layout.addWidget(self.historical_trade_log)
        trade_log_group = QGroupBox("Historial de operaciones")
        trade_log_group.setLayout(trade_log_layout)
        layout.addWidget(trade_log_group)
        self.historical_holdings_table.setEnabled(False)

        self.historical_simulation: HistoricalPortfolioSimulation | None = None
        self.historical_worker: HistoricalDataWorker | None = None
        self._historical_pending_symbols: list[str] = []
        self._historical_pending_initial_symbols: list[str] = []
        self._historical_pending_cash = 0.0
        self._historical_pending_date = date(2023, 1, 3)
        self._historical_pending_market = "NASDAQ"
        self.historical_timer = QTimer(self)
        self.historical_timer.timeout.connect(self._advance_historical_day)
        self.historical_speed_input = QSpinBox()
        self.historical_speed_input.setRange(1, 60)
        self.historical_speed_input.setValue(2)
        self.historical_speed_input.setSuffix(" s / día")
        self.historical_speed_input.valueChanged.connect(
            self._set_historical_timer_interval
        )
        simulation_controls.insertWidget(2, QLabel("Velocidad:"))
        simulation_controls.insertWidget(3, self.historical_speed_input)
        self.historical_next_button.setText("Avanzar un día")
        self.historical_next_button.setEnabled(False)
        self.historical_clock_button = QPushButton("Iniciar reloj")
        self.historical_clock_button.setEnabled(False)
        self.historical_clock_button.clicked.connect(self._toggle_historical_clock)
        simulation_controls.addWidget(self.historical_clock_button)
        self._update_historical_market()
        self._refresh_historical_chart()
        self._refresh_saved_sessions()
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(content)
        return scroll_area

    def _update_historical_market(self) -> None:
        market = self.historical_market_input.currentData()
        for symbol, checkbox in self.historical_checkboxes.items():
            available = symbol in MARKET_SYMBOLS[market]
            checkbox.setVisible(available)
            checkbox.setChecked(available)
        previous_symbol = self.historical_symbol_input.currentData()
        self.historical_symbol_input.clear()
        for symbol in MARKET_SYMBOLS[market]:
            self.historical_symbol_input.addItem(
                f"{COMPANY_NAMES[symbol]} ({symbol})", symbol
            )
        if previous_symbol in MARKET_SYMBOLS[market]:
            self.historical_symbol_input.setCurrentIndex(
                self.historical_symbol_input.findData(previous_symbol)
            )

    def _start_historical_simulation(self) -> None:
        if (
            self.historical_simulation is not None
            and self.historical_start_button.text() == "Nueva simulación"
        ):
            answer = QMessageBox.question(
                self,
                "Iniciar otra simulación",
                "La simulación actual se cerrará. Guárdala antes si quieres "
                "poder retomarla luego. ¿Continuar?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.historical_timer.stop()
            self.historical_simulation = None
            self.historical_holdings_table.setRowCount(0)
            self.historical_trade_log.setRowCount(0)
            self.historical_market_input.setEnabled(True)
            self.historical_cash_input.setEnabled(True)
            self.historical_start_date_input.setEnabled(True)
            market = self.historical_market_input.currentData()
            for symbol, checkbox in self.historical_checkboxes.items():
                checkbox.setEnabled(symbol in MARKET_SYMBOLS[market])
            self.historical_start_button.setText("Iniciar simulación")
            self.historical_next_button.setEnabled(False)
            self.historical_clock_button.setEnabled(False)
            self.historical_buy_button.setEnabled(False)
            self.historical_sell_button.setEnabled(False)
            self.historical_save_session_button.setEnabled(False)
            self._refresh_historical_chart()

        self.historical_timer.stop()
        market = self.historical_market_input.currentData()
        initial_symbols = [
            symbol
            for symbol in MARKET_SYMBOLS[market]
            if self.historical_checkboxes[symbol].isChecked()
        ]
        if not initial_symbols:
            QMessageBox.warning(
                self,
                "Sin tenencias iniciales",
                "Selecciona al menos una empresa para asignarle acciones "
                "iniciales aleatorias.",
            )
            return

        symbols = list(MARKET_SYMBOLS[market])
        self._historical_pending_symbols = symbols
        self._historical_pending_initial_symbols = initial_symbols
        self._historical_pending_cash = self.historical_cash_input.value()
        self._historical_pending_date = date.fromisoformat(
            self.historical_start_date_input.date().toString("yyyy-MM-dd")
        )
        self._historical_pending_market = market
        self.historical_market_input.setEnabled(False)
        self.historical_cash_input.setEnabled(False)
        self.historical_start_date_input.setEnabled(False)
        for checkbox in self.historical_checkboxes.values():
            checkbox.setEnabled(False)
        self.historical_start_button.setEnabled(False)
        self.historical_start_button.setText("Descargando datos 2023...")
        self.historical_worker = HistoricalDataWorker(symbols)
        self.historical_worker.completed.connect(self._historical_data_loaded)
        self.historical_worker.finished.connect(
            self._historical_download_finished
        )
        self.historical_worker.start()

    def _historical_download_finished(self) -> None:
        self.historical_start_button.setEnabled(True)
        if self.historical_simulation is None:
            self.historical_start_button.setText("Iniciar simulación")
            self.historical_market_input.setEnabled(True)
            self.historical_cash_input.setEnabled(True)
            self.historical_start_date_input.setEnabled(True)
            market = self.historical_market_input.currentData()
            for symbol, checkbox in self.historical_checkboxes.items():
                checkbox.setEnabled(symbol in MARKET_SYMBOLS[market])
        else:
            self.historical_start_button.setText("Nueva simulación")

    def _historical_data_loaded(
        self,
        history: dict[str, tuple[HistoricalBar, ...]] | None,
        error: str,
    ) -> None:
        if error:
            QMessageBox.warning(self, "Datos históricos no disponibles", error)
            return
        if history is None:
            QMessageBox.warning(
                self,
                "Datos históricos no disponibles",
                "La fuente no devolvió datos históricos utilizables.",
            )
            return
        try:
            self.historical_simulation = HistoricalPortfolioSimulation(
                history,
                self._historical_pending_symbols,
                self._historical_pending_cash,
                self._historical_pending_date,
                initial_random_symbols=self._historical_pending_initial_symbols,
                market=self._historical_pending_market,
            )
        except (HistoricalDataError, ValueError) as exc:
            QMessageBox.warning(self, "Simulación no iniciada", str(exc))
            return
        self.historical_next_button.setEnabled(True)
        self.historical_clock_button.setEnabled(True)
        self.historical_clock_button.setText("Pausar reloj")
        self.historical_timer.start(self.historical_speed_input.value() * 1000)
        self.historical_symbol_input.setCurrentIndex(
            self.historical_symbol_input.findData(
                self.historical_simulation.symbols[0]
            )
        )
        self.historical_buy_button.setEnabled(True)
        self.historical_sell_button.setEnabled(True)
        self.historical_save_session_button.setEnabled(True)
        self.historical_holdings_table.setEnabled(True)
        self.historical_market_input.setEnabled(False)
        self.historical_cash_input.setEnabled(False)
        self.historical_start_date_input.setEnabled(False)
        for checkbox in self.historical_checkboxes.values():
            checkbox.setEnabled(False)
        self._refresh_historical_holdings()
        self._refresh_historical_trade_log()
        self._refresh_historical_summary()
        self._refresh_historical_chart()

    def _advance_historical_day(self) -> None:
        if self.historical_simulation is None:
            return
        try:
            self.historical_simulation.advance()
        except SimulationCompleteError:
            self.historical_timer.stop()
            self.historical_clock_button.setText("Iniciar reloj")
            self.historical_next_button.setEnabled(False)
            self.historical_clock_button.setEnabled(False)
            return
        self._refresh_historical_holdings()
        self._refresh_historical_summary()
        self._refresh_historical_chart()
        if self.historical_simulation.is_complete:
            self.historical_timer.stop()
            self.historical_next_button.setEnabled(False)
            self.historical_clock_button.setEnabled(False)
            self.historical_clock_button.setText("Finalizada")
            self.historical_buy_button.setEnabled(False)
            self.historical_sell_button.setEnabled(False)

    def _set_historical_timer_interval(self, seconds: int) -> None:
        self.historical_timer.setInterval(seconds * 1000)

    def _toggle_historical_clock(self) -> None:
        simulation = self.historical_simulation
        if simulation is None or simulation.is_complete:
            return
        if self.historical_timer.isActive():
            self.historical_timer.stop()
            self.historical_clock_button.setText("Reanudar reloj")
        else:
            self.historical_timer.start(
                self.historical_speed_input.value() * 1000
            )
            self.historical_clock_button.setText("Pausar reloj")

    def _trade_historical_asset(self, side: str) -> None:
        simulation = self.historical_simulation
        if simulation is None:
            return
        try:
            trade = simulation.trade(
                self.historical_symbol_input.currentData(),
                side,
                self.historical_quantity_input.value(),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Operación no realizada", str(exc))
            return
        self._refresh_historical_holdings()
        self._refresh_historical_trade_log()
        self._refresh_historical_summary()
        self._refresh_historical_chart()
        self.statusBar().showMessage(
            f"{trade.side} simulada: {trade.quantity} {trade.symbol} "
            f"a USD {trade.unit_price:,.2f}.",
            5000,
        )

    def _refresh_historical_holdings(self) -> None:
        simulation = self.historical_simulation
        if simulation is None:
            self.historical_holdings_table.setRowCount(0)
            self._refresh_historical_trade_controls()
            return
        self.historical_holdings_table.setRowCount(len(simulation.symbols))
        for row, symbol in enumerate(simulation.symbols):
            quantity = simulation.holdings[symbol]
            price = simulation.prices[symbol]
            values = (
                f"{COMPANY_NAMES[symbol]} ({symbol})",
                str(quantity),
                f"{price:,.2f}",
                f"{quantity * price:,.2f}",
            )
            for column, value in enumerate(values):
                self.historical_holdings_table.setItem(
                    row, column, QTableWidgetItem(value)
                )
        self.historical_holdings_table.resizeColumnsToContents()
        self._refresh_historical_trade_controls()

    def _historical_symbol_changed(self) -> None:
        self._refresh_historical_chart()
        self._refresh_historical_trade_controls()

    def _refresh_historical_trade_controls(self) -> None:
        simulation = self.historical_simulation
        symbol = self.historical_symbol_input.currentData()
        if simulation is None or symbol not in simulation.symbols:
            self.historical_buy_button.setEnabled(False)
            self.historical_sell_button.setEnabled(False)
            self.historical_trade_hint.setText(
                "Inicia una sesión para consultar el precio y operar."
            )
            return

        quantity = self.historical_quantity_input.value()
        price = simulation.prices[symbol]
        position = simulation.holdings[symbol]
        total = price * quantity
        is_active = not simulation.is_complete
        can_buy = is_active and total <= simulation.cash_balance
        can_sell = is_active and quantity <= position
        self.historical_buy_button.setEnabled(can_buy)
        self.historical_sell_button.setEnabled(can_sell)
        self.historical_trade_hint.setText(
            f"{COMPANY_NAMES[symbol]} ({symbol}) · "
            f"Precio USD {price:,.2f} · "
            f"Total estimado ({quantity}): USD {total:,.2f} · "
            f"Acciones disponibles: {position} · "
            f"Efectivo: USD {simulation.cash_balance:,.2f}"
        )

    def _refresh_historical_trade_log(self) -> None:
        trades = (
            self.historical_simulation.trades
            if self.historical_simulation is not None
            else ()
        )
        self.historical_trade_log.setRowCount(len(trades))
        for row, trade in enumerate(reversed(trades)):
            values = (
                trade.day.isoformat(),
                trade.symbol,
                trade.side,
                str(trade.quantity),
                f"{trade.unit_price:,.2f}",
            )
            for column, value in enumerate(values):
                self.historical_trade_log.setItem(
                    row, column, QTableWidgetItem(value)
                )
        self.historical_trade_log.resizeColumnsToContents()

    def _refresh_saved_sessions(self) -> None:
        self.historical_session_input.clear()
        try:
            sessions = self.historical_session_store.list_sessions()
        except (OSError, sqlite3.Error) as exc:
            QMessageBox.warning(
                self, "Sesiones no disponibles", f"No se pudieron leer: {exc}"
            )
            return
        for name, updated_at in sessions:
            self.historical_session_input.addItem(
                f"{name} — {updated_at}", name
            )
        self.historical_load_session_button.setEnabled(bool(sessions))

    def _save_historical_session(self) -> None:
        simulation = self.historical_simulation
        if simulation is None:
            return
        name, accepted = QInputDialog.getText(
            self, "Guardar sesión", "Nombre para esta sesión:"
        )
        if not accepted:
            return
        session_name = name.strip()
        try:
            existing_sessions = self.historical_session_store.list_sessions()
        except sqlite3.Error as exc:
            QMessageBox.warning(
                self, "Sesión no guardada", f"No se pudieron leer sesiones: {exc}"
            )
            return
        if any(saved_name == session_name for saved_name, _ in existing_sessions):
            answer = QMessageBox.question(
                self,
                "Sobrescribir sesión",
                f"«{session_name}» ya existe. ¿Quieres reemplazarla?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        state = simulation.export_state()
        state["chart_type"] = self.historical_chart_type_input.currentData()
        state["timer_interval_seconds"] = self.historical_speed_input.value()
        state["initial_random_symbols"] = self._historical_pending_initial_symbols
        try:
            self.historical_session_store.save(session_name, state)
        except (HistoricalSessionError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Sesión no guardada", str(exc))
            return
        self._refresh_saved_sessions()
        saved_index = self.historical_session_input.findData(session_name)
        if saved_index >= 0:
            self.historical_session_input.setCurrentIndex(saved_index)
        QMessageBox.information(
            self, "Sesión guardada", f"Sesión «{session_name}» guardada."
        )

    def _load_historical_session(self) -> None:
        name = self.historical_session_input.currentData()
        if not name:
            return
        self.historical_timer.stop()
        try:
            state = self.historical_session_store.load(name)
            simulation = HistoricalPortfolioSimulation.from_state(state)
        except (HistoricalSessionError, sqlite3.Error, ValueError) as exc:
            QMessageBox.warning(self, "Sesión no cargada", str(exc))
            return

        market = simulation.market
        if market not in MARKET_SYMBOLS or any(
            symbol not in MARKET_SYMBOLS[market] for symbol in simulation.symbols
        ):
            QMessageBox.warning(
                self, "Sesión no cargada", "El mercado guardado no es válido."
            )
            return
        raw_initial_symbols = state.get(
            "initial_random_symbols", list(simulation.symbols)
        )
        if (
            not isinstance(raw_initial_symbols, list)
            or any(
                not isinstance(symbol, str)
                or symbol not in simulation.symbols
                for symbol in raw_initial_symbols
            )
        ):
            QMessageBox.warning(
                self, "Sesión no cargada", "Las empresas iniciales no son válidas."
            )
            return
        self.historical_simulation = simulation
        self.historical_market_input.setCurrentIndex(
            self.historical_market_input.findData(market)
        )
        for symbol, checkbox in self.historical_checkboxes.items():
            checkbox.setChecked(symbol in raw_initial_symbols)
        self._historical_pending_market = market
        self._historical_pending_symbols = list(simulation.symbols)
        self._historical_pending_initial_symbols = raw_initial_symbols
        self._historical_pending_cash = simulation.initial_cash
        self._historical_pending_date = simulation.start_date
        self.historical_start_button.setText("Nueva simulación")
        self.historical_market_input.setEnabled(False)
        self.historical_cash_input.setEnabled(False)
        self.historical_start_date_input.setEnabled(False)
        for checkbox in self.historical_checkboxes.values():
            checkbox.setEnabled(False)
        chart_type = state.get("chart_type", "line")
        if chart_type in {"line", "candles"}:
            self.historical_chart_type_input.setCurrentIndex(
                self.historical_chart_type_input.findData(chart_type)
            )
        try:
            interval = int(state.get("timer_interval_seconds", 2))
        except (TypeError, ValueError):
            interval = 2
        if 1 <= interval <= 60:
            self.historical_speed_input.setValue(interval)
        self.historical_symbol_input.setCurrentIndex(
            self.historical_symbol_input.findData(simulation.symbols[0])
        )
        self.historical_next_button.setEnabled(not simulation.is_complete)
        self.historical_clock_button.setEnabled(not simulation.is_complete)
        self.historical_clock_button.setText(
            "Pausar reloj" if not simulation.is_complete else "Finalizada"
        )
        self.historical_buy_button.setEnabled(not simulation.is_complete)
        self.historical_sell_button.setEnabled(not simulation.is_complete)
        self.historical_save_session_button.setEnabled(True)
        self.historical_holdings_table.setEnabled(True)
        self._refresh_historical_holdings()
        self._refresh_historical_trade_log()
        self._refresh_historical_summary()
        self._refresh_historical_chart()
        if not simulation.is_complete:
            self.historical_timer.start(
                self.historical_speed_input.value() * 1000
            )

    def _refresh_historical_summary(self) -> None:
        simulation = self.historical_simulation
        if simulation is None:
            self.historical_summary_label.setText(
                "Elige un mercado, las empresas y la fecha para iniciar."
            )
            return
        holdings_text = ", ".join(
            f"{symbol} {simulation.holdings[symbol]}"
            for symbol in simulation.symbols
        )
        self.historical_summary_label.setText(
            f"Mercado: {self._historical_pending_market} · "
            f"Empresas: {', '.join(simulation.symbols)} · "
            f"Capital disponible: USD {simulation.cash_balance:,.2f} · "
            f"Tenencias: {holdings_text} · "
            f"Fecha: {simulation.current_date.isoformat()} · "
            f"Valor: USD {simulation.current_value:,.2f} · "
            f"Rentabilidad: {simulation.return_pct:+.2f}%"
        )

    def _refresh_historical_chart(self) -> None:
        self.historical_figure.clear()
        axes = self.historical_figure.add_subplot(111)
        simulation = self.historical_simulation
        if simulation is None:
            axes.text(
                0.5,
                0.5,
                "La serie histórica aparecerá al iniciar la simulación.",
                ha="center",
                va="center",
                transform=axes.transAxes,
            )
            axes.set_axis_off()
        else:
            symbol = self.historical_symbol_input.currentData()
            candles = simulation.price_candles(symbol)
            dates = [mdates.date2num(item.day) for item in candles]
            holding = simulation.holdings[symbol]
            if self.historical_chart_type_input.currentData() == "line":
                axes.plot(
                    dates,
                    [item.close for item in candles],
                    color="#2563eb",
                    linewidth=1.8,
                )
                axes.set_title(
                    f"{COMPANY_NAMES[symbol]} ({symbol}) · {holding} acciones"
                )
            else:
                body_width = 0.65
                for x, item in zip(dates, candles):
                    rising = item.close >= item.open
                    color = "#16a34a" if rising else "#dc2626"
                    axes.vlines(x, item.low, item.high, color=color, linewidth=1)
                    body_height = max(
                        abs(item.close - item.open),
                        max(item.close, item.open) * 0.00001,
                    )
                    axes.bar(
                        x,
                        body_height,
                        bottom=min(item.open, item.close),
                        width=body_width,
                        color=color,
                        edgecolor=color,
                        linewidth=0.8,
                    )
                axes.set_title(
                    f"Velas OHLC · {COMPANY_NAMES[symbol]} "
                    f"({symbol}) · {holding} acciones"
                )
            symbol_trades = [
                trade for trade in simulation.trades if trade.symbol == symbol
            ]
            for side, marker, color in (
                ("COMPRA", "^", "#16a34a"),
                ("VENTA", "v", "#dc2626"),
            ):
                operations = [trade for trade in symbol_trades if trade.side == side]
                if operations:
                    axes.scatter(
                        [mdates.date2num(trade.day) for trade in operations],
                        [trade.unit_price for trade in operations],
                        marker=marker,
                        color=color,
                        label=side.title(),
                        zorder=3,
                    )
                    axes.legend()
            axes.xaxis_date()
            axes.xaxis.set_major_formatter(mdates.DateFormatter("%d-%b"))
            axes.grid(True, alpha=0.25)
            axes.set_ylabel("Precio por acción (USD)")
            self.historical_figure.autofmt_xdate()
        self.historical_figure.tight_layout()
        self.historical_canvas.draw()

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
        for snapshot in snapshots:
            try:
                self.ledger.update_valuation(
                    snapshot.symbol, "ACCIONES", "USD", snapshot.price
                )
            except SimulationError as exc:
                errors.append(str(exc))
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
        self._refresh_portfolio()

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
        self.valuation_input.setValue(self.snapshots[symbol].price)

    def _asset_type_changed(self) -> None:
        asset_type = self.asset_type_input.currentData()
        self.currency_input.setCurrentText(
            "USD" if asset_type == "ACCIONES" else "COP"
        )
        is_fixed_income = asset_type in {"CDT", "BONOS", "TES"}
        self.annual_rate_input.setEnabled(is_fixed_income)
        self.maturity_input.setEnabled(is_fixed_income)
        self.save_terms_button.setEnabled(is_fixed_income)

    def _income_type_changed(self) -> None:
        self.repaid_quantity_input.setEnabled(
            self.income_type_input.currentData() == "PAGO_CAPITAL"
        )

    def _update_valuation(self) -> None:
        try:
            price = self.ledger.update_valuation(
                self.instrument_input.text(),
                self.asset_type_input.currentData(),
                self.currency_input.currentText(),
                self.valuation_input.value(),
            )
        except SimulationError as exc:
            QMessageBox.warning(self, "Valoración no actualizada", str(exc))
            return
        self._refresh_portfolio()
        QMessageBox.information(
            self,
            "Valoración actualizada",
            f"Valor unitario de {self.instrument_input.text().strip().upper()}: "
            f"{price:,.4f} {self.currency_input.currentText()}.",
        )

    def _save_fixed_terms(self) -> None:
        try:
            self.ledger.set_instrument_terms(
                self.instrument_input.text(),
                self.asset_type_input.currentData(),
                self.currency_input.currentText(),
                self.annual_rate_input.value(),
                self.maturity_input.date().toString("yyyy-MM-dd"),
            )
        except SimulationError as exc:
            QMessageBox.warning(self, "Condiciones no guardadas", str(exc))
            return
        QMessageBox.information(
            self,
            "Condiciones guardadas",
            f"Tasa E.A.: {self.annual_rate_input.value():.4f}% · "
            f"vencimiento: "
            f"{self.maturity_input.date().toString('yyyy-MM-dd')}.",
        )

    def _record_income(self) -> None:
        try:
            self.ledger.record_income(
                self.instrument_input.text(),
                self.asset_type_input.currentData(),
                self.income_type_input.currentData(),
                self.income_amount_input.value(),
                operation_date=self.operation_date_input.date().toString(
                    "yyyy-MM-dd"
                ),
                quantity=self.repaid_quantity_input.value(),
                commission=self.income_commission_input.value(),
                currency=self.currency_input.currentText(),
            )
        except SimulationError as exc:
            QMessageBox.warning(self, "Rendimiento no registrado", str(exc))
            return
        self._refresh_portfolio()
        QMessageBox.information(
            self,
            "Rendimiento registrado",
            f"{self.income_type_input.currentText()} registrado para "
            f"{self.instrument_input.text().strip().upper()}.",
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
        summaries = [
            self.ledger.portfolio_summary(currency)
            for currency in ("USD", "COP")
        ]
        summary_lines = []
        for item in summaries:
            fixed_income_pct = (
                item.fixed_income_value / item.market_value * 100
                if item.market_value > 0
                else 0
            )
            equity_pct = (
                item.equity_value / item.market_value * 100
                if item.market_value > 0
                else 0
            )
            annualized = (
                f"{item.annualized_return_pct:+.2f}%"
                if item.annualized_return_pct is not None
                else "N/D"
            )
            summary_lines.append(
                f"{item.currency}: invertido {item.invested_value:,.2f}, "
                f"valor actual {item.total_value:,.2f}, "
                f"renta fija {item.fixed_income_value:,.2f} "
                f"({fixed_income_pct:.1f}%), "
                f"renta variable {item.equity_value:,.2f} "
                f"({equity_pct:.1f}%), "
                f"ingresos {item.income_total:,.2f}, "
                f"costos {item.costs_total:,.2f}, "
                f"rentabilidad acumulada {item.cumulative_return_pct:+.2f}%, "
                f"E.A. {annualized}"
            )
        self.portfolio_label.setText(
            "Portafolio (sin conversión entre monedas): "
            + "  |  ".join(summary_lines)
        )
        position_lines = []
        for summary in summaries:
            for position in summary.positions:
                details = (
                    f"{position.symbol} ({position.asset_type}, "
                    f"{summary.currency}): {position.quantity:f} × "
                    f"{position.unit_price:,.4f} = "
                    f"{position.market_value:,.2f} "
                    f"(costo {position.cost_basis:,.2f})"
                )
                if position.annual_rate_pct is not None:
                    details += f", tasa E.A. {position.annual_rate_pct}%"
                if position.maturity_date:
                    details += f", vence {position.maturity_date}"
                position_lines.append(details)
        self.positions_label.setText(
            "Posiciones valoradas: "
            + ("; ".join(position_lines) or "ninguna")
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

        income = self.ledger.recent_income(15)
        self.income_log.setRowCount(len(income))
        for row, event in enumerate(income):
            values = (
                event.operation_date,
                event.asset_type,
                event.symbol,
                event.income_type,
                event.currency,
                f"{event.amount:,.2f}",
                f"{event.quantity:f}" if event.quantity else "",
                f"{event.commission:,.2f}",
            )
            for column, value in enumerate(values):
                self.income_log.setItem(row, column, QTableWidgetItem(value))
        self.income_log.resizeColumnsToContents()


def create_application(database_path: Path) -> QApplication:
    application = QApplication.instance() or QApplication([])
    window = FinanceWindow(SimulationLedger(database_path))
    window.show()
    application.exec()
    return application
