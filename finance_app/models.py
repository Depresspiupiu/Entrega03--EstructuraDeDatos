from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class StockSnapshot:
    symbol: str
    price: float
    change_1d_pct: float
    change_1m_pct: float
    change_3m_pct: float
    score: float
    recommendation: str


@dataclass(frozen=True)
class TradeRecord:
    timestamp: str
    symbol: str
    side: str
    quantity: Decimal
    price: Decimal
    total: Decimal
    asset_type: str = "ACCIONES"
    operation_date: str = ""
    commission: Decimal = Decimal("0")
    currency: str = "USD"


@dataclass(frozen=True)
class PortfolioPosition:
    asset_type: str
    symbol: str
    quantity: Decimal
    unit_price: Decimal
    cost_basis: Decimal
    market_value: Decimal
    annual_rate_pct: Decimal | None = None
    maturity_date: str | None = None


@dataclass(frozen=True)
class PortfolioSummary:
    currency: str
    initial_cash: Decimal
    cash_balance: Decimal
    invested_value: Decimal
    market_value: Decimal
    total_value: Decimal
    fixed_income_value: Decimal
    equity_value: Decimal
    income_total: Decimal
    costs_total: Decimal
    cumulative_return_pct: Decimal
    annualized_return_pct: Decimal | None
    positions: tuple[PortfolioPosition, ...]


@dataclass(frozen=True)
class IncomeRecord:
    operation_date: str
    symbol: str
    asset_type: str
    income_type: str
    amount: Decimal
    quantity: Decimal
    commission: Decimal
    currency: str
