"""Phase C — reusable validation engine.

Pure logic with no I/O. MUST NOT import from app.main to avoid circular imports —
import only from app.models and the standard library.

Severity ladder:
    info < warning < error < critical

`critical` findings block an apply; everything else is advisory.
"""
from __future__ import annotations

import enum
from typing import Any


class ValidationLevel(str, enum.Enum):
    info = "info"
    warning = "warning"
    error = "error"
    critical = "critical"  # blocks apply


# Ordering for "worst level" comparisons.
_LEVEL_RANK = {
    ValidationLevel.info: 0,
    ValidationLevel.warning: 1,
    ValidationLevel.error: 2,
    ValidationLevel.critical: 3,
}

# Hard numeric bounds for price sanity checks.
PRICE_EXTREMELY_LOW = 0.001
PRICE_EXTREMELY_HIGH = 999999.0
LARGE_INCREASE_FACTOR = 10.0

VALID_STOCK_STATUSES = frozenset({"instock", "outofstock", "onbackorder"})


class ValidationResult:
    __slots__ = ("level", "rule", "product_id", "field", "value", "message")

    def __init__(
        self,
        level: ValidationLevel,
        rule: str,
        product_id: int | None,
        field: str,
        value: Any,
        message: str,
    ) -> None:
        self.level = level
        self.rule = rule
        self.product_id = product_id
        self.field = field
        self.value = value
        self.message = message

    def to_dict(self) -> dict:
        return {
            "level": self.level.value if isinstance(self.level, ValidationLevel) else self.level,
            "rule": self.rule,
            "product_id": self.product_id,
            "field": self.field,
            "value": self.value,
            "message": self.message,
        }


def worst_level(results: list[ValidationResult]) -> ValidationLevel | None:
    """Return the highest-severity level in results, or None if empty."""
    if not results:
        return None
    return max(results, key=lambda r: _LEVEL_RANK.get(r.level, 0)).level


def has_critical(results: list[ValidationResult]) -> bool:
    return any(r.level == ValidationLevel.critical for r in results)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    s = str(value).strip()
    if s == "":
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def validate_price(
    product_id: int | None,
    new_price: Any,
    old_price: Any = None,
) -> list[ValidationResult]:
    """Validate a single price value.

    Rules:
      non-numeric  → critical (invalid_price)
      negative     → critical (negative_price)
      < 0.001      → critical (extremely_low)
      > 999999     → critical (extremely_high)
      zero         → warning  (zero_price)
      > 10x old    → warning  (large_increase)
    """
    out: list[ValidationResult] = []

    # Empty / blank price is treated as zero (intentional "out of stock" signal),
    # not as a non-numeric error — matches existing _stock_from_price semantics.
    if new_price is None or str(new_price).strip() == "":
        out.append(ValidationResult(
            ValidationLevel.warning, "zero_price", product_id, "new_price", new_price,
            "Price is blank — product will be marked out of stock.",
        ))
        return out

    new_f = _to_float(new_price)
    if new_f is None:
        out.append(ValidationResult(
            ValidationLevel.critical, "non_numeric_price", product_id, "new_price", new_price,
            f"Price '{new_price}' is not a number.",
        ))
        return out

    if new_f < 0:
        out.append(ValidationResult(
            ValidationLevel.critical, "negative_price", product_id, "new_price", new_price,
            f"Price {new_f} is negative.",
        ))
        return out

    if new_f == 0:
        out.append(ValidationResult(
            ValidationLevel.warning, "zero_price", product_id, "new_price", new_price,
            "Price is zero — product will be marked out of stock.",
        ))
        return out

    if new_f < PRICE_EXTREMELY_LOW:
        out.append(ValidationResult(
            ValidationLevel.critical, "extremely_low", product_id, "new_price", new_price,
            f"Price {new_f} is below the minimum allowed ({PRICE_EXTREMELY_LOW}).",
        ))
    if new_f > PRICE_EXTREMELY_HIGH:
        out.append(ValidationResult(
            ValidationLevel.critical, "extremely_high", product_id, "new_price", new_price,
            f"Price {new_f} exceeds the maximum allowed ({PRICE_EXTREMELY_HIGH:.0f}).",
        ))

    old_f = _to_float(old_price)
    if old_f is not None and old_f > 0 and new_f > old_f * LARGE_INCREASE_FACTOR:
        out.append(ValidationResult(
            ValidationLevel.warning, "large_increase", product_id, "new_price", new_price,
            f"Price {new_f} is more than {LARGE_INCREASE_FACTOR:.0f}× the previous price ({old_f}).",
        ))

    return out


def validate_stock(
    product_id: int | None,
    stock_status: Any,
    stock_quantity: Any = None,
) -> list[ValidationResult]:
    """Validate stock status and (optional) quantity.

    Rules:
      invalid stock_status → critical (invalid_stock_status)
      negative quantity    → error    (negative_stock_quantity)
    """
    out: list[ValidationResult] = []

    if stock_status is not None and str(stock_status).strip() != "":
        if str(stock_status).strip() not in VALID_STOCK_STATUSES:
            out.append(ValidationResult(
                ValidationLevel.critical, "invalid_stock_status", product_id, "stock_status",
                stock_status, f"Stock status '{stock_status}' is not recognised.",
            ))

    if stock_quantity is not None:
        try:
            qty = int(stock_quantity)
            if qty < 0:
                out.append(ValidationResult(
                    ValidationLevel.error, "negative_stock_quantity", product_id,
                    "stock_quantity", stock_quantity, f"Stock quantity {qty} is negative.",
                ))
        except (ValueError, TypeError):
            out.append(ValidationResult(
                ValidationLevel.error, "non_numeric_stock_quantity", product_id,
                "stock_quantity", stock_quantity,
                f"Stock quantity '{stock_quantity}' is not an integer.",
            ))

    return out


def validate_product(product_id: int | None, cache_row: Any) -> list[ValidationResult]:
    """Validate product-level invariants.

    Rules:
      missing wc_id          → critical (missing_wc_id)
      missing cache entry    → warning  (missing_cache_entry)
    """
    out: list[ValidationResult] = []

    if not product_id or product_id <= 0:
        out.append(ValidationResult(
            ValidationLevel.critical, "missing_wc_id", product_id, "product_id", product_id,
            "Product has no valid WooCommerce ID.",
        ))
        return out

    if cache_row is None:
        out.append(ValidationResult(
            ValidationLevel.warning, "missing_cache_entry", product_id, "product_id", product_id,
            "Product is not present in the local WooCommerce cache.",
        ))

    return out


def validate_items(items: list, cache_map: dict) -> list[ValidationResult]:
    """Run the full validation suite over a list of SyncItem-like objects.

    `cache_map` maps product_id → ProductCache row (or any object / None).
    Each item is accessed with getattr() so rows created before Phase C columns
    existed validate without raising.
    """
    out: list[ValidationResult] = []
    for item in items:
        pid = getattr(item, "product_id", None)
        cache_row = cache_map.get(pid) if cache_map else None

        out.extend(validate_product(pid, cache_row))

        new_price = getattr(item, "new_price", None)
        old_price = getattr(item, "old_price", None)
        out.extend(validate_price(pid, new_price, old_price))

        stock_status = getattr(item, "stock_status", None)
        stock_quantity = getattr(item, "stock_quantity", None)
        out.extend(validate_stock(pid, stock_status, stock_quantity))

    return out
