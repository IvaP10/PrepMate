/**
 * Centralized pricing configuration — single source of truth for the frontend.
 * Mirrors backend pricing.py exactly. Change values here and they reflect
 * in both the landing page and the dashboard.
 */

export const CURRENCY = "INR"
export const CURRENCY_SYMBOL = "₹"

/* ── Starter Pack ── */
export const STARTER_PACK = {
  name: "Starter",
  price: 299,
  interviews: 3,
  durationDays: 30,
}

/* ── Pro plan pricing ── */
export const PRO_PRICING = { monthly: 999, annual: 899, annualBilled: 10788 }

/* ── Premium plan pricing ── */
export const PREMIUM_PRICING = { monthly: 1499, annual: 1349, annualBilled: 16188 }
