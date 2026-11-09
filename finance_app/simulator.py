import sqlite3
from contextlib import closing
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from finance_app.models import (
    IncomeRecord,
    PortfolioPosition,
    PortfolioSummary,
    TradeRecord,
)

ASSET_TYPES = ("ACCIONES", "CDT", "BONOS", "TES")
CURRENCIES = ("COP", "USD")
INCOME_TYPES = ("DIVIDENDO", "INTERES", "PAGO_CAPITAL")


class SimulationError(ValueError):
    """Raised when a simulated transaction violates account rules."""


class SimulationLedger:
    def __init__(
        self,
        database_path: Path,
        initial_cash: Decimal = Decimal("10000.00"),
    ) -> None:
        initial_cash = self._decimal(initial_cash, "El saldo inicial")
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize(initial_cash)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self, initial_cash: Decimal) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS account (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        initial_cash TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS trades (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL DEFAULT (
                            strftime('%Y-%m-%d %H:%M:%S', 'now')
                        ),
                        symbol TEXT NOT NULL,
                        side TEXT NOT NULL CHECK (side IN ('COMPRA', 'VENTA')),
                        quantity TEXT NOT NULL,
                        price TEXT NOT NULL,
                        asset_type TEXT NOT NULL DEFAULT 'ACCIONES',
                        operation_date TEXT NOT NULL DEFAULT '',
                        commission TEXT NOT NULL DEFAULT '0',
                        currency TEXT NOT NULL DEFAULT 'USD'
                    )
                    """
                )
                columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(trades)")
                }
                for name, declaration in (
                    ("asset_type", "TEXT NOT NULL DEFAULT 'ACCIONES'"),
                    ("operation_date", "TEXT NOT NULL DEFAULT ''"),
                    ("commission", "TEXT NOT NULL DEFAULT '0'"),
                    ("currency", "TEXT NOT NULL DEFAULT 'USD'"),
                ):
                    if name not in columns:
                        connection.execute(
                            f"ALTER TABLE trades ADD COLUMN {name} {declaration}"
                        )
                connection.execute(
                    """
                    UPDATE trades
                    SET operation_date = substr(timestamp, 1, 10)
                    WHERE operation_date = ''
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS account_balances (
                        currency TEXT PRIMARY KEY,
                        initial_cash TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS income_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        operation_date TEXT NOT NULL,
                        asset_type TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        income_type TEXT NOT NULL CHECK (
                            income_type IN ('DIVIDENDO', 'INTERES', 'PAGO_CAPITAL')
                        ),
                        amount TEXT NOT NULL,
                        quantity TEXT NOT NULL DEFAULT '0',
                        commission TEXT NOT NULL DEFAULT '0',
                        currency TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS instrument_terms (
                        asset_type TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        currency TEXT NOT NULL,
                        annual_rate_pct TEXT NOT NULL DEFAULT '0',
                        maturity_date TEXT NOT NULL DEFAULT '',
                        PRIMARY KEY (asset_type, symbol, currency)
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS valuations (
                        asset_type TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        currency TEXT NOT NULL,
                        unit_price TEXT NOT NULL,
                        updated_on TEXT NOT NULL,
                        PRIMARY KEY (asset_type, symbol, currency)
                    )
                    """
                )
                legacy_cash = connection.execute(
                    "SELECT initial_cash FROM account WHERE id = 1"
                ).fetchone()
                if legacy_cash is None:
                    connection.execute(
                        "INSERT INTO account (id, initial_cash) VALUES (1, ?)",
                        (str(initial_cash),),
                    )
                    legacy_cash_value = initial_cash
                else:
                    legacy_cash_value = Decimal(legacy_cash["initial_cash"])
                connection.execute(
                    """
                    INSERT OR IGNORE INTO account_balances (currency, initial_cash)
                    VALUES ('USD', ?)
                    """,
                    (str(legacy_cash_value),),
                )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO account_balances (currency, initial_cash)
                    VALUES ('COP', '0')
                    """
                )

    @staticmethod
    def _decimal(value: Decimal | float | str, label: str) -> Decimal:
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise SimulationError(f"{label} no es válido.") from exc
        if not result.is_finite() or result <= 0:
            raise SimulationError(f"{label} debe ser mayor que cero.")
        return result

    @staticmethod
    def _non_negative_decimal(value: Decimal | float | str, label: str) -> Decimal:
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise SimulationError(f"{label} no es válido.") from exc
        if not result.is_finite() or result < 0:
            raise SimulationError(f"{label} no puede ser negativo.")
        return result

    @classmethod
    def _commission(cls, value: Decimal | float | str) -> Decimal:
        return cls._non_negative_decimal(value, "La comisión")

    @staticmethod
    def _operation_date(value: str | date | None) -> str:
        if value is None:
            return date.today().isoformat()
        try:
            parsed = date.fromisoformat(str(value))
        except ValueError as exc:
            raise SimulationError(
                "La fecha debe tener el formato YYYY-MM-DD."
            ) from exc
        if parsed.isoformat() != str(value):
            raise SimulationError("La fecha debe tener el formato YYYY-MM-DD.")
        return parsed.isoformat()

    @staticmethod
    def _currency(value: str) -> str:
        currency = value.strip().upper()
        if currency not in CURRENCIES:
            raise SimulationError("La moneda debe ser COP o USD.")
        return currency

    def _account_state(
        self, connection: sqlite3.Connection, currency: str
    ) -> tuple[Decimal, dict[tuple[str, str], Decimal]]:
        initial_row = connection.execute(
            "SELECT initial_cash FROM account_balances WHERE currency = ?",
            (currency,),
        ).fetchone()
        initial = Decimal(initial_row["initial_cash"]) if initial_row else Decimal("0")
        cash = initial
        positions: dict[tuple[str, str], Decimal] = {}
        rows = connection.execute(
            """
            SELECT side, symbol, quantity, price, asset_type, commission
            FROM trades WHERE currency = ? ORDER BY id
            """,
            (currency,),
        ).fetchall()
        for row in rows:
            quantity = Decimal(row["quantity"])
            total = quantity * Decimal(row["price"])
            commission = Decimal(row["commission"])
            key = (row["asset_type"], row["symbol"])
            if row["side"] == "COMPRA":
                cash -= total + commission
                positions[key] = positions.get(key, Decimal("0")) + quantity
            else:
                cash += total - commission
                positions[key] = positions.get(key, Decimal("0")) - quantity
        income_rows = connection.execute(
            """
            SELECT asset_type, symbol, income_type, amount, quantity, commission
            FROM income_events WHERE currency = ?
            """,
            (currency,),
        ).fetchall()
        for row in income_rows:
            cash += Decimal(row["amount"]) - Decimal(row["commission"])
            if row["income_type"] == "PAGO_CAPITAL":
                key = (row["asset_type"], row["symbol"])
                positions[key] = positions.get(key, Decimal("0")) - Decimal(
                    row["quantity"]
                )
        return cash, {key: value for key, value in positions.items() if value > 0}

    def _positions_through_date(
        self,
        connection: sqlite3.Connection,
        currency: str,
        cutoff_date: str,
    ) -> dict[tuple[str, str], Decimal]:
        trades = connection.execute(
            """
            SELECT id, asset_type, symbol, side, quantity, operation_date
            FROM trades
            WHERE currency = ? AND operation_date <= ?
            ORDER BY operation_date, id
            """,
            (currency, cutoff_date),
        ).fetchall()
        income_events = connection.execute(
            """
            SELECT id, asset_type, symbol, income_type, quantity, operation_date
            FROM income_events
            WHERE currency = ? AND operation_date <= ?
            ORDER BY operation_date, id
            """,
            (currency, cutoff_date),
        ).fetchall()
        events = [
            (row["operation_date"], 0, row["id"], "trade", row)
            for row in trades
        ] + [
            (row["operation_date"], 1, row["id"], "income", row)
            for row in income_events
        ]
        positions: dict[tuple[str, str], Decimal] = {}
        for _, _, _, event_type, row in sorted(events):
            key = (row["asset_type"], row["symbol"])
            quantity = Decimal(row["quantity"])
            if event_type == "trade":
                positions[key] = positions.get(key, Decimal("0")) + (
                    quantity if row["side"] == "COMPRA" else -quantity
                )
            elif row["income_type"] == "PAGO_CAPITAL":
                positions[key] = positions.get(key, Decimal("0")) - quantity
        return {key: value for key, value in positions.items() if value > 0}

    def cash_balance(self, currency: str = "USD") -> Decimal:
        currency = self._currency(currency)
        with closing(self._connect()) as connection:
            cash, _ = self._account_state(connection, currency)
            return cash

    def set_initial_cash(
        self, currency: str, amount: Decimal | float | str
    ) -> Decimal:
        currency = self._currency(currency)
        amount_value = self._non_negative_decimal(amount, "El saldo inicial")
        with closing(self._connect()) as connection:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                trade_count = connection.execute(
                    "SELECT COUNT(*) FROM trades WHERE currency = ?", (currency,)
                ).fetchone()[0]
                if trade_count:
                    raise SimulationError(
                        f"No se puede cambiar el saldo inicial en {currency} "
                        "después de registrar operaciones."
                    )
                connection.execute(
                    """
                    INSERT INTO account_balances (currency, initial_cash)
                    VALUES (?, ?)
                    ON CONFLICT(currency) DO UPDATE SET initial_cash = excluded.initial_cash
                    """,
                    (currency, str(amount_value)),
                )
        return amount_value

    def positions(self) -> dict[str, Decimal]:
        result: dict[str, Decimal] = {}
        with closing(self._connect()) as connection:
            for currency in CURRENCIES:
                _, positions = self._account_state(connection, currency)
                for (asset_type, symbol), quantity in positions.items():
                    if asset_type == "ACCIONES" and currency == "USD":
                        key = symbol
                    else:
                        key = f"{asset_type}: {symbol} ({currency})"
                    result[key] = quantity
        return result

    def update_valuation(
        self,
        symbol: str,
        asset_type: str,
        currency: str,
        unit_price: Decimal | float | str,
        *,
        updated_on: str | date | None = None,
    ) -> Decimal:
        symbol = symbol.strip().upper()
        if not symbol:
            raise SimulationError("El instrumento no puede estar vacío.")
        asset_type = asset_type.strip().upper()
        if asset_type not in ASSET_TYPES:
            raise SimulationError("El tipo de activo no es válido.")
        currency = self._currency(currency)
        price_value = self._decimal(unit_price, "La valoración")
        date_value = self._operation_date(updated_on)
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO valuations (
                        asset_type, symbol, currency, unit_price, updated_on
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(asset_type, symbol, currency) DO UPDATE SET
                        unit_price = excluded.unit_price,
                        updated_on = excluded.updated_on
                    """,
                    (
                        asset_type,
                        symbol,
                        currency,
                        str(price_value),
                        date_value,
                    ),
                )
        return price_value

    def set_instrument_terms(
        self,
        symbol: str,
        asset_type: str,
        currency: str,
        annual_rate_pct: Decimal | float | str,
        maturity_date: str | date | None = None,
    ) -> None:
        symbol = symbol.strip().upper()
        if not symbol:
            raise SimulationError("El instrumento no puede estar vacío.")
        asset_type = asset_type.strip().upper()
        if asset_type not in {"CDT", "BONOS", "TES"}:
            raise SimulationError(
                "Las condiciones contractuales solo aplican a renta fija."
            )
        currency = self._currency(currency)
        rate = self._non_negative_decimal(
            annual_rate_pct, "La tasa efectiva anual"
        )
        maturity = (
            self._operation_date(maturity_date) if maturity_date is not None else ""
        )
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO instrument_terms (
                        asset_type, symbol, currency, annual_rate_pct, maturity_date
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(asset_type, symbol, currency) DO UPDATE SET
                        annual_rate_pct = excluded.annual_rate_pct,
                        maturity_date = excluded.maturity_date
                    """,
                    (asset_type, symbol, currency, str(rate), maturity),
                )

    def record_income(
        self,
        symbol: str,
        asset_type: str,
        income_type: str,
        amount: Decimal | float | str,
        *,
        operation_date: str | date | None = None,
        quantity: Decimal | float | str = Decimal("0"),
        commission: Decimal | float | str = Decimal("0"),
        currency: str = "USD",
    ) -> None:
        symbol = symbol.strip().upper()
        if not symbol:
            raise SimulationError("El instrumento no puede estar vacío.")
        asset_type = asset_type.strip().upper()
        if asset_type not in ASSET_TYPES:
            raise SimulationError("El tipo de activo no es válido.")
        income_type = income_type.strip().upper()
        if income_type not in INCOME_TYPES:
            raise SimulationError("El tipo de rendimiento no es válido.")
        currency = self._currency(currency)
        amount_value = self._decimal(amount, "El valor del rendimiento")
        commission_value = self._commission(commission)
        if commission_value > amount_value:
            raise SimulationError(
                "La comisión no puede superar el valor del rendimiento."
            )
        quantity_value = (
            self._decimal(quantity, "La cantidad amortizada")
            if income_type == "PAGO_CAPITAL"
            else Decimal("0")
        )
        date_value = self._operation_date(operation_date)
        with closing(self._connect()) as connection:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                positions = self._positions_through_date(
                    connection, currency, date_value
                )
                position_key = (asset_type, symbol)
                if positions.get(position_key, Decimal("0")) <= 0:
                    raise SimulationError(
                        f"No tienes una posición de {asset_type} {symbol} en "
                        f"{currency} para registrar este rendimiento."
                    )
                if income_type == "PAGO_CAPITAL" and quantity_value > positions.get(
                    position_key, Decimal("0")
                ):
                    raise SimulationError(
                        "La cantidad amortizada supera las unidades disponibles."
                    )
                connection.execute(
                    """
                    INSERT INTO income_events (
                        operation_date, asset_type, symbol, income_type, amount,
                        quantity, commission, currency
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        date_value,
                        asset_type,
                        symbol,
                        income_type,
                        str(amount_value),
                        str(quantity_value),
                        str(commission_value),
                        currency,
                    ),
                )

    def portfolio_summary(self, currency: str) -> PortfolioSummary:
        currency = self._currency(currency)
        with closing(self._connect()) as connection:
            initial_row = connection.execute(
                "SELECT initial_cash FROM account_balances WHERE currency = ?",
                (currency,),
            ).fetchone()
            initial_cash = (
                Decimal(initial_row["initial_cash"])
                if initial_row
                else Decimal("0")
            )
            cash_balance, positions = self._account_state(connection, currency)
            trade_rows = connection.execute(
                """
                SELECT id, symbol, side, quantity, price, asset_type, commission,
                       operation_date
                FROM trades WHERE currency = ? ORDER BY id
                """,
                (currency,),
            ).fetchall()
            income_rows = connection.execute(
                """
                SELECT id, asset_type, symbol, income_type, amount, quantity,
                       commission, operation_date
                FROM income_events WHERE currency = ?
                """,
                (currency,),
            ).fetchall()
            term_rows = connection.execute(
                """
                SELECT asset_type, symbol, annual_rate_pct, maturity_date
                FROM instrument_terms WHERE currency = ?
                """,
                (currency,),
            ).fetchall()
            valuation_rows = connection.execute(
                "SELECT asset_type, symbol, unit_price FROM valuations WHERE currency = ?",
                (currency,),
            ).fetchall()
            valuation_prices = {
                (row["asset_type"], row["symbol"]): Decimal(row["unit_price"])
                for row in valuation_rows
            }
            terms = {
                (row["asset_type"], row["symbol"]): (
                    Decimal(row["annual_rate_pct"]),
                    date.fromisoformat(row["maturity_date"])
                    if row["maturity_date"]
                    else None,
                )
                for row in term_rows
            }

        basis: dict[tuple[str, str], Decimal] = {}
        units: dict[tuple[str, str], Decimal] = {}
        acquisition_days: dict[tuple[str, str], Decimal] = {}
        costs_total = Decimal("0")
        income_total = Decimal("0")
        interest_received: dict[tuple[str, str], Decimal] = {}
        activity_dates: list[str] = []
        events = [
            (row["operation_date"], 0, row["id"], "trade", row)
            for row in trade_rows
        ] + [
            (row["operation_date"], 1, row["id"], "income", row)
            for row in income_rows
        ]
        for operation_date, _, _, event_type, row in sorted(events):
            key = (row["asset_type"], row["symbol"])
            activity_dates.append(operation_date)
            commission = Decimal(row["commission"])
            costs_total += commission
            current_units = units.get(key, Decimal("0"))
            current_basis = basis.get(key, Decimal("0"))
            if event_type == "trade":
                quantity = Decimal(row["quantity"])
                trade_value = quantity * Decimal(row["price"])
                if row["side"] == "COMPRA":
                    previous_days = acquisition_days.get(key, Decimal("0"))
                    new_day = Decimal(date.fromisoformat(operation_date).toordinal())
                    acquisition_days[key] = (
                        (previous_days * current_units + new_day * quantity)
                        / (current_units + quantity)
                    )
                    units[key] = current_units + quantity
                    basis[key] = current_basis + trade_value + commission
                elif current_units > 0:
                    average_cost = current_basis / current_units
                    remaining_units = current_units - quantity
                    units[key] = remaining_units
                    basis[key] = current_basis - average_cost * quantity
                    if remaining_units <= 0:
                        interest_received.pop(key, None)
                    elif key in interest_received:
                        interest_received[key] *= remaining_units / current_units
                continue

            income_total += Decimal(row["amount"])
            if row["income_type"] == "INTERES":
                interest_received[key] = (
                    interest_received.get(key, Decimal("0"))
                    + Decimal(row["amount"])
                )
            elif row["income_type"] == "PAGO_CAPITAL" and current_units > 0:
                quantity = Decimal(row["quantity"])
                average_cost = current_basis / current_units
                units[key] = current_units - quantity
                basis[key] = current_basis - average_cost * quantity

        market_value = Decimal("0")
        invested_value = Decimal("0")
        fixed_income_value = Decimal("0")
        equity_value = Decimal("0")
        position_summaries: list[PortfolioPosition] = []
        for key, quantity in positions.items():
            if quantity <= 0:
                continue
            cost_basis = max(basis.get(key, Decimal("0")), Decimal("0"))
            unit_price = valuation_prices.get(key)
            if unit_price is None:
                unit_price = cost_basis / quantity if quantity else Decimal("0")
                contract = terms.get(key)
                acquisition_ordinal = acquisition_days.get(key)
                if contract and acquisition_ordinal is not None and key[0] != "ACCIONES":
                    annual_rate_pct, maturity = contract
                    acquired_on = date.fromordinal(round(acquisition_ordinal))
                    valuation_date = date.today()
                    if maturity is not None:
                        valuation_date = min(valuation_date, maturity)
                    elapsed_days = max((valuation_date - acquired_on).days, 0)
                    if elapsed_days:
                        annual_rate = annual_rate_pct / Decimal("100")
                        unit_price *= (Decimal("1") + annual_rate) ** (
                            Decimal(elapsed_days) / Decimal("365.25")
                        )
                        if interest_received.get(key, Decimal("0")):
                            unit_price = max(
                                cost_basis,
                                unit_price * quantity - interest_received[key],
                            ) / quantity
            value = quantity * unit_price
            contract = terms.get(key)
            position_summaries.append(
                PortfolioPosition(
                    asset_type=key[0],
                    symbol=key[1],
                    quantity=quantity,
                    unit_price=unit_price,
                    cost_basis=cost_basis,
                    market_value=value,
                    annual_rate_pct=contract[0] if contract else None,
                    maturity_date=(
                        contract[1].isoformat()
                        if contract and contract[1]
                        else None
                    ),
                )
            )
            market_value += value
            invested_value += cost_basis
            if key[0] == "ACCIONES":
                equity_value += value
            else:
                fixed_income_value += value

        total_value = cash_balance + market_value
        cumulative_return = (
            (total_value / initial_cash - 1) * 100
            if initial_cash > 0
            else Decimal("0")
        )
        annualized_return: Decimal | None = None
        if initial_cash > 0 and activity_dates and total_value > 0:
            elapsed_days = (date.today() - date.fromisoformat(min(activity_dates))).days
            if elapsed_days > 0:
                annualized_return = (
                    (total_value / initial_cash)
                    ** (Decimal("365.25") / Decimal(elapsed_days))
                    - 1
                ) * 100

        return PortfolioSummary(
            currency=currency,
            initial_cash=initial_cash,
            cash_balance=cash_balance,
            invested_value=invested_value,
            market_value=market_value,
            total_value=total_value,
            fixed_income_value=fixed_income_value,
            equity_value=equity_value,
            income_total=income_total,
            costs_total=costs_total,
            cumulative_return_pct=cumulative_return,
            annualized_return_pct=annualized_return,
            positions=tuple(position_summaries),
        )

    def recent_income(self, limit: int = 20) -> list[IncomeRecord]:
        if limit < 1:
            raise ValueError("El límite debe ser mayor que cero.")
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT operation_date, symbol, asset_type, income_type, amount,
                       quantity, commission, currency
                FROM income_events
                ORDER BY operation_date DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            IncomeRecord(
                operation_date=row["operation_date"],
                symbol=row["symbol"],
                asset_type=row["asset_type"],
                income_type=row["income_type"],
                amount=Decimal(row["amount"]),
                quantity=Decimal(row["quantity"]),
                commission=Decimal(row["commission"]),
                currency=row["currency"],
            )
            for row in rows
        ]

    def trade(
        self,
        symbol: str,
        side: str,
        quantity: Decimal | float | str,
        price: Decimal | float | str,
        *,
        asset_type: str = "ACCIONES",
        operation_date: str | date | None = None,
        commission: Decimal | float | str = Decimal("0"),
        currency: str = "USD",
    ) -> TradeRecord:
        symbol = symbol.strip().upper()
        if not symbol:
            raise SimulationError(
                "El nombre o símbolo del instrumento no puede estar vacío."
            )
        if side not in {"COMPRA", "VENTA"}:
            raise SimulationError("La operación debe ser COMPRA o VENTA.")
        asset_type = asset_type.strip().upper()
        if asset_type not in ASSET_TYPES:
            raise SimulationError(
                "El tipo de activo debe ser ACCIONES, CDT, BONOS o TES."
            )
        currency = self._currency(currency)

        quantity_value = self._decimal(quantity, "La cantidad")
        price_value = self._decimal(price, "El precio o valor unitario")
        commission_value = self._commission(commission)
        operation_date_value = self._operation_date(operation_date)
        total = quantity_value * price_value

        with closing(self._connect()) as connection:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                cash, positions = self._account_state(connection, currency)
                position_key = (asset_type, symbol)
                if side == "COMPRA" and total + commission_value > cash:
                    raise SimulationError(
                        f"Saldo insuficiente en {currency}. "
                        f"Disponible: {cash:,.2f} {currency}."
                    )
                if side == "VENTA" and quantity_value > positions.get(
                    position_key, Decimal("0")
                ):
                    raise SimulationError(
                        f"No tienes suficientes unidades simuladas de "
                        f"{asset_type} {symbol} en {currency}."
                    )
                if side == "VENTA" and commission_value > total + cash:
                    raise SimulationError(
                        f"Saldo insuficiente en {currency} para cubrir "
                        "la comisión de venta."
                    )
                cursor = connection.execute(
                    """
                    INSERT INTO trades (
                        symbol, side, quantity, price, asset_type,
                        operation_date, commission, currency
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        symbol,
                        side,
                        str(quantity_value),
                        str(price_value),
                        asset_type,
                        operation_date_value,
                        str(commission_value),
                        currency,
                    ),
                )
                timestamp = connection.execute(
                    "SELECT timestamp FROM trades WHERE id = ?",
                    (cursor.lastrowid,),
                ).fetchone()["timestamp"]

        return TradeRecord(
            timestamp=timestamp,
            symbol=symbol,
            side=side,
            quantity=quantity_value,
            price=price_value,
            total=total,
            asset_type=asset_type,
            operation_date=operation_date_value,
            commission=commission_value,
            currency=currency,
        )

    def recent_trades(self, limit: int = 20) -> list[TradeRecord]:
        if limit < 1:
            raise ValueError("El límite debe ser mayor que cero.")
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT timestamp, symbol, side, quantity, price, asset_type,
                       operation_date, commission, currency
                FROM trades ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            TradeRecord(
                timestamp=row["timestamp"],
                symbol=row["symbol"],
                side=row["side"],
                quantity=Decimal(row["quantity"]),
                price=Decimal(row["price"]),
                total=Decimal(row["quantity"]) * Decimal(row["price"]),
                asset_type=row["asset_type"],
                operation_date=row["operation_date"],
                commission=Decimal(row["commission"]),
                currency=row["currency"],
            )
            for row in rows
        ]
