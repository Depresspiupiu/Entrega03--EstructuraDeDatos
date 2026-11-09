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
