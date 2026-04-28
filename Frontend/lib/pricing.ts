/**
 * Centralized pricing configuration — single source of truth for the frontend.
 * Mirrors backend pricing.py exactly. Change values here and they reflect
 * in both the landing page and the dashboard.
 */

export const PRICE_PER_CREDIT = 199
export const CURRENCY = "INR"
export const CURRENCY_SYMBOL = "₹"
export const MAX_CREDITS = 50
export const MIN_CREDITS = 1

/**
 * Tiered discount schedule.
 * Must match backend pricing.py → PricingConfig.get_discount_percent()
 */
const DISCOUNT_TIERS: [number, number][] = [
  [40, 15],
  [25, 12],
  [15, 8],
  [10, 5],
]

export function getDiscountPercent(count: number): number {
  for (const [threshold, percent] of DISCOUNT_TIERS) {
    if (count >= threshold) return percent
  }
  return 0
}

export const MAX_DISCOUNT_PERCENT = DISCOUNT_TIERS[0][1] // 15

export function calculatePricing(count: number) {
  const discountPercent = getDiscountPercent(count)
  const hasDiscount = discountPercent > 0
  const basePrice = count * PRICE_PER_CREDIT
  const discountAmount = hasDiscount
    ? Math.round(basePrice * (discountPercent / 100))
    : 0
  const totalPrice = basePrice - discountAmount

  return {
    count,
    basePrice,
    discountPercent,
    hasDiscount,
    discountAmount,
    totalPrice,
    pricePerCredit: PRICE_PER_CREDIT,
    currency: CURRENCY,
    currencySymbol: CURRENCY_SYMBOL,
  }
}
