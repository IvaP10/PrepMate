# ============================================================================
# MODULE: pricing.py
# PURPOSE: Credit pricing constants + per-order total/discount/fee calculator.
# STRUCTURE:
#   - PricingConfig dataclass with credit price, fees, free-credit count (lines 13-22)
#   - get_discount_percent / calculate_total methods (lines 24-57)
#   - PRICING singleton (line 61)
# ENDPOINTS: none (consumed by /api/payment/pricing in payment.py)
# DEPENDS ON: (stdlib only)
# CONSUMED BY: payment.py, workspace_api.py
# DATA TABLES: none today (Phase 3 moves the constants into `pricing_plans` /
#              `pricing_discounts` tables; calculate_total signature stays stable)
# ============================================================================

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict


@dataclass(frozen=True)
class PricingConfig:
    CREDIT_PRICE_INR: Decimal = Decimal("199.00")
    PROCESSING_FEE_RAZORPAY: Decimal = Decimal("0.02")
    FREE_CREDITS_ON_SIGNUP: int = 3
    TRANSACTION_EXPIRY_MINUTES: int = 15
    SUBSCRIPTION_DURATION_DAYS: int = 30
    CURRENCY: str = "INR"

    def get_discount_percent(self, sessions: int) -> Decimal:
        if sessions >= 40:
            return Decimal("0.15")
        if sessions >= 25:
            return Decimal("0.12")
        if sessions >= 15:
            return Decimal("0.08")
        if sessions >= 10:
            return Decimal("0.05")
        return Decimal("0")

    def calculate_total(self, sessions: int, provider: str) -> Dict[str, object]:
        base = self.CREDIT_PRICE_INR * sessions
        discount_rate = self.get_discount_percent(sessions)
        discount = base * discount_rate if discount_rate else Decimal("0")
        subtotal = base - discount
        if provider != "razorpay":
            raise ValueError("Only Razorpay pricing is supported")
        fee_rate = self.PROCESSING_FEE_RAZORPAY
        fee = subtotal * fee_rate
        total = (subtotal + fee).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        return {
            "sessions": sessions,
            "price_per_credit": float(self.CREDIT_PRICE_INR),
            "base_price": float(base),
            "discount": float(discount),
            "discount_percent": float(discount_rate * 100) if discount else 0,
            "subtotal": float(subtotal),
            "processing_fee": float(fee.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "processing_fee_percent": float(fee_rate * 100),
            "total": float(total),
            "currency": self.CURRENCY,
        }


PRICING = PricingConfig()
