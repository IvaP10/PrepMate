"use client"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Check, X } from "lucide-react"

interface PricingSectionProps {
  onGetStarted: () => void
}

type BillingCycle = "monthly" | "annual"

const starterFeatures = [
  "Mock interviews to practice with",
  "Performance analysis after every session",
  "Access for a full month",
]

const starterExcluded = [
  "Coaching and answer breakdowns",
  "Exercise modes and drills",
]

const proFeatures = [
  "Unlimited mock interviews",
  "Full answer coaching after every session",
  "Personalised drill queue based on weak patterns",
  "All 6 exercise modes",
  "Answer builder with guided frameworks",
  "Deep analytics and pattern diagnosis",
  "Unlimited job profiles",
]

const premiumFeatures = [
  "Everything in Pro, plus:",
  "Technical interview rounds",
  "Built-in code editor",
  "Step-by-step problem walkthroughs",
  "Hints system during technical sessions",
  "Technical performance review",
]

const proPricing = { monthly: 999, annual: 899, annualBilled: 10788 }
const premiumPricing = { monthly: 1499, annual: 1349, annualBilled: 16188 }

function formatPrice(n: number) {
  return `₹${n.toLocaleString("en-IN")}`
}

export function PricingSection({ onGetStarted }: PricingSectionProps) {
  const [billing, setBilling] = useState<BillingCycle>("monthly")
  const isAnnual = billing === "annual"

  return (
    <section id="pricing" className="relative px-6 py-24">
      <div className="absolute top-0 left-1/2 h-px w-48 -translate-x-1/2 bg-gradient-to-r from-transparent via-border to-transparent" />
      <div className="mx-auto max-w-6xl">
        <div className="mx-auto mb-12 max-w-2xl text-center">
          <span className="mb-4 inline-block text-sm font-medium uppercase tracking-[0.25em] text-muted-foreground">
            Pricing
          </span>
          <h2 className="text-balance font-serif text-3xl leading-[1.2] tracking-tight sm:text-4xl md:text-5xl">
            <span className="text-shimmer">Plans for every stage of prep.</span>
            <br />
            <span className="text-shimmer-accent">Cancel anytime.</span>
          </h2>
          <p className="mt-5 text-lg text-muted-foreground">
            Start light or go all-in. Every plan includes real interview practice.
          </p>
        </div>

        {/* ── Billing Toggle ── */}
        <div className="mx-auto mb-10 flex items-center justify-center gap-3">
          <span className={`text-sm font-medium transition-colors ${!isAnnual ? "text-foreground" : "text-muted-foreground"}`}>
            Monthly
          </span>
          <button
            onClick={() => setBilling(isAnnual ? "monthly" : "annual")}
            className="relative h-7 w-[52px] rounded-full bg-secondary border border-border transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
            aria-label="Toggle billing cycle"
          >
            <span
              className={`absolute top-0.5 left-0.5 h-6 w-6 rounded-full bg-primary shadow-md transition-transform duration-300 ${isAnnual ? "translate-x-[24px]" : "translate-x-0"}`}
            />
          </button>
          <span className={`text-sm font-medium transition-colors ${isAnnual ? "text-foreground" : "text-muted-foreground"}`}>
            Annual
          </span>
          <span
            className={`ml-1 inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-bold transition-all duration-300 ${
              isAnnual
                ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 scale-100 opacity-100"
                : "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 scale-90 opacity-0 pointer-events-none"
            }`}
          >
            Save 10%
          </span>
        </div>

        {/* ── Cards Grid ── */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">

          {/* ─── Column 1 — Starter ─── */}
          <div className="group flex flex-col overflow-hidden rounded-xl border border-border bg-card transition-all duration-500 ease-out hover:-translate-y-1.5 hover:border-accent-indigo/30 hover:shadow-[0_8px_30px_-12px_rgba(37,99,235,0.15)]">
            <div className="flex flex-1 flex-col p-8">
              <div>
                <h3 className="text-xl font-bold text-foreground">Starter</h3>
                <p className="mt-1 text-base text-muted-foreground">Get interview ready</p>
              </div>

              <div className="mt-6 flex items-baseline gap-1">
                <span className="text-4xl font-bold text-foreground">{formatPrice(299)}</span>
                <span className="text-base text-muted-foreground">/ month</span>
              </div>

              <p className="mt-3 text-sm font-medium text-muted-foreground">
                Enough practice to build real confidence
              </p>

              {/* Included features */}
              <div className="mt-8 flex flex-col gap-3">
                {starterFeatures.map((f) => (
                  <div key={f} className="flex items-center gap-3">
                    <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent-indigo/10">
                      <Check className="h-3 w-3 text-accent-indigo" />
                    </div>
                    <span className="text-base text-muted-foreground">{f}</span>
                  </div>
                ))}
                {starterExcluded.map((f) => (
                  <div key={f} className="flex items-center gap-3">
                    <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-muted/30">
                      <X className="h-3 w-3 text-muted-foreground/40" />
                    </div>
                    <span className="text-base text-muted-foreground/50">{f}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="border-t border-border p-8 pt-6">
              <Button
                variant="outline"
                onClick={onGetStarted}
                className="h-11 w-full rounded-full text-base font-semibold transition-all duration-200"
              >
                Get started
              </Button>
            </div>
          </div>

          {/* ─── Column 2 — Pro (Featured) ─── */}
          <div className="group flex flex-col overflow-hidden rounded-xl border border-accent-indigo/40 ring-1 ring-accent-indigo/20 bg-card transition-all duration-500 ease-out hover:-translate-y-1.5 hover:border-accent-indigo/50 hover:shadow-[0_8px_30px_-12px_rgba(37,99,235,0.2)]">
            <div className="flex flex-1 flex-col p-8">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-xl font-bold text-foreground">Pro</h3>
                  <p className="mt-1 text-base text-muted-foreground">Unlock the full experience</p>
                </div>
                <span className="shrink-0 rounded-md bg-primary/10 px-2.5 py-1 text-xs font-bold text-primary">
                  Most popular
                </span>
              </div>
              <div className="mt-6 flex items-baseline gap-1">
                <span className="text-4xl font-bold text-foreground">
                  {formatPrice(isAnnual ? proPricing.annual : proPricing.monthly)}
                </span>
                <span className="text-base text-muted-foreground">/ month</span>
              </div>
              {isAnnual && (
                <p className="mt-1 text-sm font-medium text-muted-foreground">
                  billed {formatPrice(proPricing.annualBilled)} / year
                </p>
              )}

              <p className="mt-3 text-sm font-medium text-muted-foreground">
                Everything in Starter, and:
              </p>

              <div className="mt-6 flex flex-col gap-3">
                {proFeatures.map((feature) => (
                  <div key={feature} className="flex items-center gap-3">
                    <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent-indigo/10">
                      <Check className="h-3 w-3 text-accent-indigo" />
                    </div>
                    <span className="text-base text-muted-foreground">{feature}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="border-t border-border p-8 pt-6">
              <Button
                variant="default"
                onClick={onGetStarted}
                className="h-11 w-full rounded-full text-base font-semibold transition-all duration-200"
              >
                Get Pro
              </Button>
            </div>
          </div>

          {/* ─── Column 3 — Premium ─── */}
          <div className="group flex flex-col overflow-hidden rounded-xl border border-accent-indigo/25 bg-card transition-all duration-500 ease-out hover:-translate-y-1.5 hover:border-accent-indigo/40 hover:shadow-[0_8px_30px_-12px_rgba(37,99,235,0.15)]">
            <div className="flex flex-1 flex-col p-8">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-xl font-bold text-foreground">Premium</h3>
                  <p className="mt-1 text-base text-muted-foreground">Ace every round, including technical</p>
                </div>
                <span className="shrink-0 rounded-md bg-violet-500/10 px-2.5 py-1 text-xs font-bold text-violet-600 dark:text-violet-400">
                  Full package
                </span>
              </div>
              <div className="mt-6 flex items-baseline gap-1">
                <span className="text-4xl font-bold text-foreground">
                  {formatPrice(isAnnual ? premiumPricing.annual : premiumPricing.monthly)}
                </span>
                <span className="text-base text-muted-foreground">/ month</span>
              </div>
              {isAnnual && (
                <p className="mt-1 text-sm font-medium text-muted-foreground">
                  billed {formatPrice(premiumPricing.annualBilled)} / year
                </p>
              )}
              <div className="mt-8 flex flex-col gap-3">
                {premiumFeatures.map((feature) => (
                  <div key={feature} className="flex items-center gap-3">
                    <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent-indigo/10">
                      <Check className="h-3 w-3 text-accent-indigo" />
                    </div>
                    <span className="text-base text-muted-foreground">{feature}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="border-t border-border p-8 pt-6">
              <Button
                variant="default"
                onClick={onGetStarted}
                className="h-11 w-full rounded-full text-base font-semibold transition-all duration-200"
              >
                Get Premium
              </Button>
            </div>
          </div>
        </div>

        <div className="mt-8 flex flex-wrap justify-center gap-2 text-sm font-medium text-muted-foreground">
          <span className="rounded-md border border-border bg-card px-3 py-1.5">Cancel anytime</span>
          <span className="rounded-md border border-border bg-card px-3 py-1.5">No commitment</span>
        </div>
      </div>
    </section>
  )
}
