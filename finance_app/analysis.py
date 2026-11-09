from collections.abc import Sequence

from finance_app.models import StockSnapshot


class InsufficientMarketDataError(ValueError):
    """Raised when a quote does not include enough daily prices to analyze."""


def build_snapshot(symbol: str, closes: Sequence[float]) -> StockSnapshot:
    if len(closes) < 64:
        raise InsufficientMarketDataError(
            f"{symbol}: se necesitan al menos 64 precios diarios; "
            f"solo hay {len(closes)}."
        )

    price = float(closes[-1])
    if price <= 0:
        raise ValueError(f"{symbol}: el precio más reciente no es válido.")

    change_1d = (price / float(closes[-2]) - 1) * 100
    change_1m = (price / float(closes[-22]) - 1) * 100
    change_3m = (price / float(closes[-64]) - 1) * 100
    score = 0.6 * change_1m + 0.4 * change_3m

    if score >= 3:
        recommendation = "COMPRA"
    elif score <= -3:
        recommendation = "VENTA"
    else:
        recommendation = "MANTENER"

    return StockSnapshot(
        symbol=symbol,
        price=price,
        change_1d_pct=change_1d,
        change_1m_pct=change_1m,
        change_3m_pct=change_3m,
        score=score,
        recommendation=recommendation,
    )
