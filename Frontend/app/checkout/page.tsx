"use client"

import { Suspense, useEffect, useMemo, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { ArrowLeft, Check, Loader2, Lock, Shield, Zap } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { createPaymentSession, fetchPaymentPlans, verifyRazorpayPayment } from "@/lib/api"
import { API_CONFIG, API_ENDPOINTS } from "@/lib/config"
import { getAuthHeaders } from "@/lib/auth"

type CheckoutPlan = {
  plan_type: string
  name: string
  amount: number
  currency: string
  duration_days?: number
  features?: string[]
  description?: string
}

const FALLBACK_PLANS: Record<string, CheckoutPlan> = {
  starter: {
    plan_type: "starter",
    name: "Free",
    amount: 0,
    currency: "INR",
    description: "Free access with limited weekly practice.",
    features: ["Starter mock interview access", "Improve basics"],
  },
  pro: {
    plan_type: "pro",
    name: "Pro",
    amount: 999,
    currency: "INR",
    description: "Focused interview and technical practice.",
    features: ["3 mock interviews per week", "1 technical assessment per week", "Targeted drills"],
  },
  premium: {
    plan_type: "premium",
    name: "Premium",
    amount: 1499,
    currency: "INR",
    description: "Higher practice limits with deeper coaching.",
    features: ["5 mock interviews per week", "3 technical assessments per week", "Advanced reports"],
  },
}

function formatMoney(amount: number, currency = "INR") {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(amount)
}

function loadRazorpay(): Promise<boolean> {
  return new Promise((resolve) => {
    if ((window as any).Razorpay) {
      resolve(true)
      return
    }
    const script = document.createElement("script")
    script.src = "https://checkout.razorpay.com/v1/checkout.js"
    script.onload = () => resolve(true)
    script.onerror = () => resolve(false)
    document.body.appendChild(script)
  })
}

function CheckoutContent() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const planParam = searchParams.get("plan") || "pro"
  const sessionsParam = searchParams.get("sessions")
  const sessionCount = sessionsParam ? Math.max(1, Math.min(100, Number.parseInt(sessionsParam, 10) || 5)) : null
  const isCreditsCheckout = Boolean(sessionCount && !searchParams.get("plan"))

  const [plans, setPlans] = useState<CheckoutPlan[]>([])
  const [creditPricing, setCreditPricing] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [processing, setProcessing] = useState(false)
  const [authBlocked, setAuthBlocked] = useState(false)
  const [checkoutReady, setCheckoutReady] = useState(true)

  useEffect(() => {
    async function loadCheckoutData() {
      setLoading(true)
      setAuthBlocked(false)
      setCheckoutReady(true)
      try {
        const planPayload = await fetchPaymentPlans()
        setPlans(Array.isArray(planPayload?.plans) ? planPayload.plans : [])
        setCheckoutReady(planPayload?.checkout_ready !== false)
        if (isCreditsCheckout && sessionCount) {
          const response = await fetch(`${API_CONFIG.BASE_URL}${API_ENDPOINTS.PAYMENT.PRICING}?sessions=${sessionCount}&provider=razorpay`, {
            credentials: "include",
            headers: { ...getAuthHeaders() },
          })
          if (!response.ok) throw new Error("Failed to load pricing")
          setCreditPricing(await response.json())
        }
      } catch (error: any) {
        const message = error?.message || ""
        if (/session expired|access denied|unauthorized|401|403/i.test(message)) {
          setAuthBlocked(true)
          toast.error("Please log in before checkout.")
        } else {
          toast.error(message || "Failed to load checkout.")
        }
      } finally {
        setLoading(false)
      }
    }
    void loadCheckoutData()
  }, [isCreditsCheckout, sessionCount])

  const selectedPlan = useMemo(() => {
    if (isCreditsCheckout) return null
    return plans.find((plan) => plan.plan_type === planParam) || FALLBACK_PLANS[planParam] || FALLBACK_PLANS.pro
  }, [isCreditsCheckout, planParam, plans])

  const amount = isCreditsCheckout ? Number(creditPricing?.total || 0) : Number(selectedPlan?.amount || 0)
  const currency = isCreditsCheckout ? creditPricing?.currency || "INR" : selectedPlan?.currency || "INR"
  const title = isCreditsCheckout ? `${sessionCount} interview credits` : `${selectedPlan?.name || "Pro"} membership`
  const description = isCreditsCheckout ? "One-time practice credit purchase." : selectedPlan?.description || "Membership upgrade."
  const features = isCreditsCheckout
    ? ["Instant credit activation", "Use credits for mock interviews", "Secure Razorpay checkout"]
    : selectedPlan?.features || []
  const paymentBlocked = !checkoutReady && amount > 0

  const openRazorpay = async (order: any) => {
    const loaded = await loadRazorpay()
    if (!loaded) throw new Error("Payment gateway failed to load.")
    const key = process.env.NEXT_PUBLIC_RAZORPAY_KEY_ID
    if (!key) throw new Error("Payment gateway is not configured.")

    const checkout = new (window as any).Razorpay({
      key,
      amount: Math.round(Number(order.amount || amount) * 100),
      currency: order.currency || currency,
      name: "InterAI",
      description: title,
      order_id: order.provider_order_id || order.session_url,
      handler: async (response: any) => {
        try {
          await verifyRazorpayPayment(
            response.razorpay_order_id,
            response.razorpay_payment_id,
            response.razorpay_signature,
          )
          toast.success("Payment verified. Your plan is active.")
          router.push("/")
        } catch (error: any) {
          toast.error(error?.message || "Payment verification failed. Contact support.")
        } finally {
          setProcessing(false)
        }
      },
      modal: {
        confirm_close: true,
        ondismiss: () => setProcessing(false),
      },
      theme: { color: "#2F6F68" },
    })

    checkout.on("payment.failed", (response: any) => {
      toast.error(response?.error?.description || "Payment failed. Please try again.")
      setProcessing(false)
    })
    checkout.open()
  }

  const handlePay = async () => {
    if (authBlocked) {
      router.push("/")
      return
    }
    if (!isCreditsCheckout && selectedPlan?.amount === 0) {
      router.push("/")
      return
    }
    if (paymentBlocked) {
      toast.error("Payments are temporarily unavailable. Please try again later.")
      return
    }
    setProcessing(true)
    try {
      const order = await createPaymentSession(
        isCreditsCheckout ? "credits" : planParam,
        "razorpay",
        "razorpay_checkout",
        isCreditsCheckout ? sessionCount || undefined : undefined,
      )
      await openRazorpay(order)
    } catch (error: any) {
      setProcessing(false)
      if (/session expired|access denied|unauthorized|401|403/i.test(error?.message || "")) {
        setAuthBlocked(true)
        toast.error("Please log in before checkout.")
      } else {
        toast.error(error?.message || "Could not start payment.")
      }
    }
  }

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-40 border-b border-border/40 bg-card shadow-sm">
        <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-4 sm:px-6">
          <button onClick={() => router.back()} className="flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground">
            <ArrowLeft className="h-4 w-4" />
            Back
          </button>
          <div className="flex items-center gap-1.5 text-muted-foreground">
            <Lock className="h-3.5 w-3.5" />
            <span className="text-xs font-medium">Razorpay secure checkout</span>
          </div>
        </div>
      </header>

      <main className="mx-auto grid max-w-5xl gap-6 px-4 py-8 sm:px-6 lg:grid-cols-[1fr_380px]">
        <section className="rounded-lg border border-border/40 bg-card p-6 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Checkout</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight text-foreground">{title}</h1>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">{description}</p>
          {!isCreditsCheckout && selectedPlan?.plan_type?.includes("premium") && (
            <div className="mt-4 rounded-lg border border-primary/20 bg-primary/5 px-3 py-2 text-xs font-medium leading-5 text-primary">
              New accounts registered by 30 July 2026 get their first Premium month free automatically at signup.
            </div>
          )}

          <div className="mt-6 grid gap-3">
            {features.map((feature) => (
              <div key={feature} className="flex items-center gap-3 rounded-md border border-border/40 bg-secondary/15 p-3 text-sm text-foreground">
                <Check className="h-4 w-4 text-emerald-500" />
                {feature}
              </div>
            ))}
          </div>

          <div className="mt-6 rounded-lg border border-primary/20 bg-primary/5 p-4">
            <div className="flex items-start gap-3">
              <Shield className="mt-0.5 h-4 w-4 text-primary" />
              <div>
                <p className="text-sm font-semibold text-foreground">Payment details stay inside Razorpay.</p>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  InterAI creates an order and verifies Razorpay's signed response. We do not collect or store raw card, UPI, or banking details.
                </p>
              </div>
            </div>
          </div>
        </section>

        <aside className="rounded-lg border border-border/40 bg-card p-6 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Order summary</p>
          {loading ? (
            <div className="mt-8 flex items-center justify-center py-10 text-muted-foreground">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Loading checkout
            </div>
          ) : (
            <>
              <div className="mt-5 space-y-3">
                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="text-muted-foreground">{title}</span>
                  <span className="font-semibold text-foreground">{formatMoney(amount, currency)}</span>
                </div>
                <div className="flex items-center justify-between gap-3 border-t border-border/40 pt-3 text-base font-semibold">
                  <span>Total</span>
                  <span>{formatMoney(amount, currency)}</span>
                </div>
              </div>

              {authBlocked && (
                <div className="mt-5 rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-xs leading-5 text-amber-700 dark:text-amber-300">
                  You need to log in before purchasing a plan.
                </div>
              )}

              {paymentBlocked && (
                <div className="mt-5 rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-xs leading-5 text-amber-700 dark:text-amber-300">
                  Payments are temporarily unavailable. Please try again later.
                </div>
              )}

              <Button className="mt-6 h-11 w-full gap-2 rounded-lg" onClick={handlePay} disabled={processing || loading || paymentBlocked}>
                {processing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />}
                {authBlocked ? "Go to login" : amount === 0 ? "Return to Improve" : paymentBlocked ? "Checkout unavailable" : "Continue to Razorpay"}
              </Button>
            </>
          )}
        </aside>
      </main>
    </div>
  )
}

export default function CheckoutPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-background" />}>
      <CheckoutContent />
    </Suspense>
  )
}
