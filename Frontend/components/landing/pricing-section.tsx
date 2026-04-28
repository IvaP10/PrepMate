"use client"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Check } from "lucide-react"
import { Slider } from "@/components/ui/slider"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog"
import {
  PRICE_PER_CREDIT,
  CURRENCY_SYMBOL,
  MAX_CREDITS,
  MIN_CREDITS,
  MAX_DISCOUNT_PERCENT,
  calculatePricing,
} from "@/lib/pricing"

interface PricingSectionProps {
  onGetStarted: () => void
}
const trialFeatures = [
  "1 Free Interview Session",
  "Basic Performance Report",
  "Resume Upload & Parsing",
]
const proFeatures = [
  "Mock & Practice Interviews",
  "Detailed Performance Analytics",
  "Industry-Specific Questions",
  "Video Recording & Playback",
  "Credits Never Expire",
  "Priority Support",
]
const includedFeatures = [
  "In-depth AI feedback",
  "Industry-specific questions",
  "Video recording & playback",
  "Detailed performance analytics",
  "Priority support",
  "Real-time corrections",
]
export function PricingSection({ onGetStarted }: PricingSectionProps) {
  const [showCustomize, setShowCustomize] = useState(false)
  const [creditCount, setCreditCount] = useState(5)
  const pricing = calculatePricing(creditCount)
  return (
    <>
      <section id="pricing" className="relative px-6 py-24">
        <div className="absolute top-0 left-1/2 h-px w-48 -translate-x-1/2 bg-gradient-to-r from-transparent via-border to-transparent" />
        <div className="mx-auto max-w-5xl">
          <div className="mx-auto mb-12 max-w-2xl text-center">
            <span className="mb-4 inline-block text-sm font-medium uppercase tracking-[0.25em] text-muted-foreground">
              Pricing
            </span>
            <h2 className="text-balance font-serif text-3xl leading-[1.2] tracking-tight sm:text-4xl md:text-5xl">
              <span className="text-shimmer">Transparent, flexible pricing.</span>
              <br />
              <span className="text-shimmer-accent">Aligned with your needs.</span>
            </h2>
            <p className="mt-5 text-lg text-muted-foreground">
              Experience the platform with a complimentary initial session. Purchase additional credits as required, with volume discounts available for advanced preparation.
            </p>
          </div>
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
            <div className="group flex flex-col overflow-hidden rounded-2xl border border-border bg-card transition-all duration-500 ease-out hover:-translate-y-1.5 hover:border-accent-indigo/30 hover:shadow-[0_8px_30px_-12px_rgba(37,99,235,0.15)]">
              <div className="flex flex-1 flex-col p-8">
                <h3 className="text-xl font-bold text-foreground">Trial</h3>
                <p className="mt-1 text-base text-muted-foreground">
                  Evaluate the platform without commitment
                </p>
                <div className="mt-6 flex items-baseline gap-1">
                  <span className="text-4xl font-bold text-foreground">Free</span>
                </div>
                <div className="mt-8 flex flex-col gap-3">
                  {trialFeatures.map((f) => (
                    <div key={f} className="flex items-center gap-3">
                      <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent-indigo/10">
                        <Check className="h-3 w-3 text-accent-indigo" />
                      </div>
                      <span className="text-base text-muted-foreground">{f}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div className="border-t border-border p-8 pt-6">
                <Button
                  variant="outline"
                  onClick={onGetStarted}
                  className="h-11 w-full rounded-full border-border bg-transparent text-base font-semibold text-foreground hover:bg-secondary transition-all duration-200"
                >
                  Start Free Trial
                </Button>
              </div>
            </div>
            <div className="group relative flex flex-col overflow-hidden rounded-2xl border border-border bg-card transition-all duration-500 ease-out hover:-translate-y-1.5 hover:border-accent-indigo/30 hover:shadow-[0_8px_30px_-12px_rgba(37,99,235,0.15)]">
              <div className="flex flex-1 flex-col p-8">
                <h3 className="text-xl font-bold text-foreground">Pro</h3>
                <p className="mt-1 text-base text-muted-foreground">
                  Flexible credits valid for all simulation modes
                </p>
                <div className="mt-6 flex items-baseline gap-1">
                  <span className="text-4xl font-bold text-foreground">
                    {CURRENCY_SYMBOL}{PRICE_PER_CREDIT}
                  </span>
                  <span className="text-base text-muted-foreground">/credit</span>
                </div>
                <div className="mt-8 flex flex-col gap-3">
                  {proFeatures.map((f) => (
                    <div key={f} className="flex items-center gap-3">
                      <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent-indigo/10">
                        <Check className="h-3 w-3 text-accent-indigo" />
                      </div>
                      <span className="text-base text-muted-foreground">{f}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div className="border-t border-border p-8 pt-6">
                <Button
                  onClick={() => setShowCustomize(true)}
                  className="h-11 w-full rounded-full bg-primary text-base font-semibold text-primary-foreground hover:opacity-90 transition-all"
                >
                  Buy Credits
                </Button>
              </div>
            </div>
          </div>
        </div>
      </section>
      <Dialog open={showCustomize} onOpenChange={setShowCustomize}>
        <DialogContent className="max-w-lg gap-0 overflow-hidden border-border bg-card p-0">
          <div className="p-6">
            <DialogHeader>
              <DialogTitle className="text-xl font-bold text-foreground">
                Buy Interview Credits
              </DialogTitle>
              <DialogDescription className="mt-2 text-sm leading-relaxed text-muted-foreground">
                Each credit covers one Mock or Practice session. Buy more credits and get up to {MAX_DISCOUNT_PERCENT}% off.
              </DialogDescription>
            </DialogHeader>
            <div className="mt-6 space-y-6">
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-semibold text-foreground">Interview Credits</span>
                  <div className="flex items-center gap-2">
                    {pricing.hasDiscount && (
                      <span className="rounded-full bg-green-500/10 px-2 py-0.5 text-xs font-bold text-green-600 dark:text-green-400">
                        {pricing.discountPercent}% OFF
                      </span>
                    )}
                    <span className="rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-bold text-primary">
                      {creditCount} {creditCount === 1 ? "credit" : "credits"}
                    </span>
                  </div>
                </div>
                <Slider
                  value={[creditCount]}
                  onValueChange={(val) => setCreditCount(val[0])}
                  max={MAX_CREDITS}
                  min={MIN_CREDITS}
                  step={1}
                  className="py-2"
                />
                <div className="flex justify-between text-[10px] text-muted-foreground">
                  <span>{MIN_CREDITS}</span>
                  <span className="text-green-600 dark:text-green-400">Up to {MAX_DISCOUNT_PERCENT}% off</span>
                  <span>{MAX_CREDITS}</span>
                </div>
              </div>
              <div className="space-y-3 rounded-xl border border-primary/20 bg-primary/5 p-4">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">
                    {creditCount} credits × {CURRENCY_SYMBOL}{PRICE_PER_CREDIT.toLocaleString("en-IN")}
                  </span>
                  <span className="text-foreground">
                    {CURRENCY_SYMBOL}{pricing.basePrice.toLocaleString("en-IN")}
                  </span>
                </div>
                {pricing.hasDiscount && (
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-green-600 dark:text-green-400">{pricing.discountPercent}% Discount</span>
                    <span className="text-green-600 dark:text-green-400">
                      -{CURRENCY_SYMBOL}{pricing.discountAmount.toLocaleString("en-IN")}
                    </span>
                  </div>
                )}
                <div className="border-t border-border pt-3">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-semibold text-foreground">Total</span>
                    <div className="flex items-baseline gap-2">
                      {pricing.hasDiscount && (
                        <span className="text-sm text-muted-foreground line-through">
                          {CURRENCY_SYMBOL}{pricing.basePrice.toLocaleString("en-IN")}
                        </span>
                      )}
                      <span className="text-3xl font-bold text-foreground">
                        {CURRENCY_SYMBOL}{pricing.totalPrice.toLocaleString("en-IN")}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
              <p className="text-center text-xs text-muted-foreground">
                Credits never expire. Use them for Mock or Practice interviews whenever you want.
              </p>
              <div>
                <h4 className="mb-3 text-center text-sm font-bold text-foreground">
                  {"What's Included"}
                </h4>
                <div className="grid grid-cols-3 gap-2">
                  {includedFeatures.map((feat) => (
                    <div key={feat} className="flex items-start gap-2 rounded-lg bg-secondary p-2.5">
                      <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent-indigo" />
                      <span className="text-xs leading-snug text-muted-foreground">{feat}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
          <DialogFooter className="flex items-center gap-3 border-t border-border p-6">
            <Button
              variant="outline"
              className="flex-1"
              onClick={() => setShowCustomize(false)}
            >
              Cancel
            </Button>
            <Button
              className="flex-1"
              onClick={() => {
                setShowCustomize(false)
                onGetStarted()
              }}
            >
              Buy {creditCount} Credits — {CURRENCY_SYMBOL}{pricing.totalPrice.toLocaleString("en-IN")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
