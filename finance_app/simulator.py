import sqlite3
from contextlib import closing
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from finance_app.models import TradeRecord

ASSET_TYPES = ("ACCIONES", "CDT", "BONOS", "TES")
CURRENCIES = ("COP", "USD")


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
        return cash, {key: value for key, value in positions.items() if value > 0}

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
