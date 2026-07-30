"use client"

import { useState, type PointerEvent } from "react"
import { ArrowRight, Check } from "lucide-react"
import { useScrollReveal } from "@/hooks/use-scroll-reveal"

interface PricingSectionProps {
  onGetStarted: () => void
}

type BillingCycle = "monthly" | "annual"

const prices = {
  pro: { monthly: 999, annual: 799, annualBilled: 9588 },
  premium: { monthly: 1499, annual: 1199, annualBilled: 14388 },
}

const plans = [
  {
    name: "Free",
    description: "For a consistent interview practice habit.",
    price: "₹0",
    features: ["1 Interview Round per week", "Evidence-based feedback report", "Focused Drills from your feedback"],
    action: "Create account",
  },
  {
    name: "Pro",
    description: "For steady Interview and Technical Round preparation.",
    features: ["3 Interview Rounds per week", "1 Technical Round per week", "Job-description-based Interview Rounds", "Evidence-based feedback and Focused Drills"],
    action: "Choose Pro",
    highlighted: true,
  },
  {
    name: "Premium",
    description: "For higher-volume, role-specific preparation.",
    features: ["5 Interview Rounds per week", "3 Technical Rounds per week", "Job-description-based Interview and Technical Rounds", "Code review, feedback, and Focused Drills"],
    action: "Choose Premium",
  },
]

function formatPrice(value: number) {
  return `₹${value.toLocaleString("en-IN")}`
}

export function PricingSection({ onGetStarted }: PricingSectionProps) {
  const [billing, setBilling] = useState<BillingCycle>("monthly")
  const { ref, isVisible } = useScrollReveal({ threshold: 0.1 })
  const annual = billing === "annual"

  const updateSpotlight = (event: PointerEvent<HTMLElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect()
    event.currentTarget.style.setProperty("--pricing-pointer-x", `${event.clientX - bounds.left}px`)
    event.currentTarget.style.setProperty("--pricing-pointer-y", `${event.clientY - bounds.top}px`)
  }

  return (
    <section id="pricing" className="landing-chapter-gap landing-screen-section relative border-b border-border/40 px-6 py-12 md:py-14">
      <div ref={ref} className="mx-auto max-w-7xl">
        <div className="mx-auto max-w-3xl text-center">
          <h2 className={`text-balance text-3xl font-semibold tracking-[-0.035em] text-foreground sm:text-4xl ${isVisible ? "animate-fade-in-up" : "opacity-0"}`}>Choose the practice time you need.</h2>
          <p className={`mt-3 text-base leading-7 text-muted-foreground ${isVisible ? "animate-fade-in-up delay-100" : "opacity-0"}`}>More weekly rounds and Technical Round access when you need it.</p>
        </div>

        <div className="mx-auto mt-7 flex min-h-16 flex-col items-center">
          <div className="billing-switch relative grid w-[220px] grid-cols-2 rounded-xl border border-border bg-card p-1 text-sm shadow-sm">
            <span className={`billing-switch-thumb absolute bottom-1 top-1 left-1 w-[calc(50%-0.25rem)] rounded-lg bg-secondary shadow-sm ${annual ? "translate-x-full" : "translate-x-0"}`} aria-hidden="true" />
            <button type="button" aria-pressed={!annual} onClick={() => setBilling("monthly")} className={`relative z-10 rounded-lg px-4 py-2 font-medium transition-colors duration-300 ${!annual ? "text-foreground" : "text-muted-foreground"}`}>Monthly</button>
            <button type="button" aria-pressed={annual} onClick={() => setBilling("annual")} className={`relative z-10 rounded-lg px-4 py-2 font-medium transition-colors duration-300 ${annual ? "text-foreground" : "text-muted-foreground"}`}>Annual</button>
          </div>
          <div className="h-7 overflow-hidden" aria-live="polite">
            <span className={`mt-2 inline-flex rounded-full bg-primary/10 px-2.5 py-1 text-[11px] font-semibold text-primary transition-all duration-500 ${annual ? "translate-y-0 opacity-100" : "-translate-y-2 opacity-0"}`}>Save 20% with annual billing</span>
          </div>
        </div>

        <div className={`pricing-window-set mt-7 grid gap-3 lg:grid-cols-3 ${isVisible ? "animate-fade-in-up delay-200" : "opacity-0"}`}>
          {plans.map((plan, planIndex) => {
            const price = plan.name === "Pro" ? prices.pro : plan.name === "Premium" ? prices.premium : null
            const displayedPrice = price ? formatPrice(price[annual ? "annual" : "monthly"]) : plan.price
            const windowShape = planIndex === 0
              ? "lg:[border-radius:1.75rem_1.15rem_1.35rem_2rem] lg:[transform:rotateY(3.5deg)_translateX(5px)] lg:[transform-origin:right_center]"
              : planIndex === 1
                ? "lg:z-[2] lg:-translate-y-[7px] lg:[border-radius:1.45rem]"
                : "lg:[border-radius:1.15rem_1.75rem_2rem_1.35rem] lg:[transform:rotateY(-3.5deg)_translateX(-5px)] lg:[transform-origin:left_center]"
            return (
              <article
                key={plan.name}
                data-featured={plan.highlighted ? "true" : "false"}
                data-position={planIndex === 0 ? "left" : planIndex === 1 ? "center" : "right"}
                onPointerMove={updateSpotlight}
                onPointerLeave={(event) => {
                  event.currentTarget.style.setProperty("--pricing-pointer-x", "50%")
                  event.currentTarget.style.setProperty("--pricing-pointer-y", "35%")
                }}
                className={`pricing-plan-card landing-solid-card group relative flex min-h-[410px] flex-col overflow-hidden rounded-3xl border p-6 ${windowShape}`}
              >
                <div className="relative z-10 flex h-full flex-col">
                  <div className="flex items-start justify-between gap-3">
                    <h3 className="text-xl font-semibold text-foreground">{plan.name}</h3>
                    {plan.highlighted && <span className="rounded-full bg-primary px-2.5 py-1 text-[10px] font-semibold text-primary-foreground">Recommended</span>}
                  </div>
                  <p className="mt-3 min-h-10 text-sm leading-5 text-muted-foreground">{plan.description}</p>
                  <div className="mt-4 flex items-baseline gap-2" aria-live="polite"><span key={`${plan.name}-${billing}`} className="animate-blur-in text-4xl font-semibold tracking-tight text-foreground">{displayedPrice}</span>{price && <span className="text-sm text-muted-foreground">/ month</span>}</div>
                  <p className="mt-1 min-h-4 text-xs text-muted-foreground">{annual && price ? `Billed ${formatPrice(price.annualBilled)} yearly` : price ? "Billed monthly" : "No payment required"}</p>

                  <ul className="mt-6 space-y-2">
                    {plan.features.map((feature) => <li key={feature} className="pricing-feature flex gap-2.5 text-sm leading-5 text-foreground/80"><span className="pricing-feature-check mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-primary/20 bg-primary/10 text-primary"><Check className="h-2.5 w-2.5" /></span>{feature}</li>)}
                  </ul>
                  <button onClick={onGetStarted} className={`pricing-card-action mt-auto flex h-11 w-full items-center justify-center gap-2 rounded-xl text-sm font-semibold transition-colors duration-300 ${plan.highlighted ? "bg-primary text-primary-foreground" : "border border-border bg-card/80 text-foreground hover:bg-secondary"}`}>{plan.action}<ArrowRight className="h-4 w-4" /></button>
                </div>
              </article>
            )
          })}
        </div>
        <p className="mx-auto mt-7 max-w-2xl text-center text-xs leading-5 text-muted-foreground">Early Bird: new registrations before 30 July 2026 receive Premium free for 30 days. Cancel any time.</p>
      </div>
    </section>
  )
}
