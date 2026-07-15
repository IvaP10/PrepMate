"use client"
import { useState } from "react"
import { Check, X } from "lucide-react"
import { useScrollReveal } from "@/hooks/use-scroll-reveal"

interface PricingSectionProps {
  onGetStarted: () => void
}

type BillingCycle = "monthly" | "annual"

const seriousPricing = { monthly: 999, annual: 799, annualBilled: 9588 }
const fullPrepPricing = { monthly: 1499, annual: 1199, annualBilled: 14388 }

function formatPrice(n: number) {
  return `₹${n.toLocaleString("en-IN")}`
}

const weeklyFeatures = [
  { text: "1 AI Mock Interview per week", included: true },
  { text: "Technical Assessments", included: false },
  { text: "Personalised Performance Report", included: true },
  { text: "JD-Based Behavioral Rounds", included: false },
  { text: "Full Loop Simulation", included: false },
]

const seriousFeatures = [
  { text: "3 AI Mock Interviews per week", included: true },
  { text: "1 Technical Assessment per week", included: true },
  { text: "JD-Based Behavioral Rounds", included: true },
  { text: "Personalised Performance Reports", included: true },
]

const fullPrepFeatures = [
  { text: "5 AI Mock Interviews per week", included: true },
  { text: "3 Technical Assessments per week", included: true },
  { text: "JD-Based Interview and Technical Rounds", included: true },
  { text: "Personalised Performance Reports", included: true },
]

export function PricingSection({ onGetStarted }: PricingSectionProps) {
  const [billing, setBilling] = useState<BillingCycle>("monthly")
  const [hoveredCard, setHoveredCard] = useState<number | null>(null)
  const { ref: sectionRef, isVisible } = useScrollReveal({ threshold: 0.1 })
  const isAnnual = billing === "annual"

  return (
    <section id="pricing" className="relative px-6 pt-14 pb-24 md:pt-16 md:pb-28 border-t border-border/40">
      <div ref={sectionRef} className="mx-auto max-w-6xl">

        {/* Section Header */}
        <div className="mx-auto mb-10 max-w-2xl text-center">
          <span className={`mb-4 inline-block text-xs font-semibold uppercase tracking-[0.25em] text-primary ${isVisible ? "animate-fade-in-up" : "opacity-0"}`}>
            Pricing
          </span>
          <h2 className={`text-balance text-3xl sm:text-4xl md:text-5xl font-semibold tracking-[-0.03em] leading-[1.1] text-foreground transition-all duration-700 ${isVisible ? "animate-blur-in delay-100" : "opacity-0"}`}>
            Pick your prep intensity.
          </h2>
          <p className={`mt-5 text-sm sm:text-base text-muted-foreground leading-[1.65] ${isVisible ? "animate-fade-in-up delay-300" : "opacity-0"}`}>
            Start free. Scale up when you have a real interview on the calendar.
          </p>
        </div>

        {/* Toggle Billing Cycles */}
        <div className="mx-auto mb-10 flex items-center justify-center gap-4">
          <span className={`text-sm font-medium transition-colors duration-200 ${!isAnnual ? "text-foreground" : "text-muted-foreground"}`}>
            Monthly
          </span>
          <button
            onClick={() => setBilling(isAnnual ? "monthly" : "annual")}
            className="relative h-7 w-[52px] cursor-pointer rounded-full border border-foreground/15 bg-secondary shadow-[inset_0_0_0_1px_rgba(255,255,255,0.22)] transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/20 dark:border-white/15 dark:shadow-[inset_0_0_0_1px_rgba(255,255,255,0.08)]"
            aria-label="Toggle billing cycle"
          >
            <span
              className={`absolute top-0.5 left-0.5 h-5.5 w-5.5 rounded-full bg-primary shadow-sm transition-transform duration-300 ${
                isAnnual ? "translate-x-[24px]" : "translate-x-0"
              }`}
            />
          </button>
          <span className={`text-sm font-medium transition-colors duration-200 ${isAnnual ? "text-foreground" : "text-muted-foreground"}`}>
            Annual
          </span>
          <span
            className={`inline-flex items-center rounded-[4px] bg-primary/10 px-2 py-0.5 text-[10px] font-semibold text-primary transition-all duration-300 ${
              isAnnual ? "scale-100 opacity-100" : "scale-90 opacity-0 pointer-events-none"
            }`}
          >
            Save 20%
          </span>
        </div>

        {/* Pricing Cards Grid */}
        <div className={`grid grid-cols-1 gap-8 items-stretch lg:grid-cols-3 spatial-stage overflow-visible pt-2 pb-4 ${isVisible ? "animate-fade-in-up delay-300" : "opacity-0"}`}>

          {/* Card 1: Weekly (Free) */}
          <div
            onMouseEnter={() => setHoveredCard(0)}
            onMouseLeave={() => setHoveredCard(null)}
            className={`landing-solid-card flex flex-col justify-between rounded-xl border border-border bg-white p-8 transition-all duration-500 ease-out select-none ${
              hoveredCard === 0
                ? "shadow-xl shadow-primary/5"
                : hoveredCard !== null
                  ? "scale-[0.99]"
                  : ""
            }`}
            style={{
              transform: hoveredCard === 0
                ? "rotateX(0deg) rotateY(0deg) translateZ(12px) scale(1.012)"
                : hoveredCard !== null
                  ? "rotateX(10deg) rotateY(8deg) translateZ(-4px)"
                  : "rotateX(8deg) rotateY(6deg) translateZ(0px)",
              transformStyle: "preserve-3d",
            }}
          >
            <div>
              <div className="mb-6">
                <h3 className="text-lg font-semibold text-foreground">Weekly</h3>
                <p className="mt-1 text-xs text-muted-foreground leading-relaxed">Build the habit. One real interview every week, free forever.</p>
              </div>

              <div className="flex items-baseline gap-1 my-6" style={{ transform: "translateZ(5px)" }}>
                <span className="text-4xl font-bold tracking-tight text-foreground">₹0</span>
              </div>

              <div className="space-y-3.5 border-t border-border/40 pt-6">
                {weeklyFeatures.map((f) => (
                  <div key={f.text} className="flex items-start gap-2.5">
                    {f.included ? (
                      <Check className="h-4 w-4 shrink-0 text-primary mt-0.5" />
                    ) : (
                      <X className="h-4 w-4 shrink-0 text-foreground/20 mt-0.5" />
                    )}
                    <span className={`text-sm leading-relaxed ${f.included ? "text-foreground/70" : "text-foreground/25 line-through"}`}>
                      {f.text}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <div className="mt-8 pt-4" style={{ transform: "translateZ(10px)" }}>
              <button
                onClick={onGetStarted}
                className="h-11 w-full rounded-lg border border-border/60 bg-transparent text-sm font-medium text-foreground/70 transition-all duration-200 hover:bg-secondary/50 hover:text-foreground cursor-pointer"
              >
                Create Account
              </button>
            </div>
          </div>

          {/* Card 2: Serious (Most Popular) */}
          <div
            onMouseEnter={() => setHoveredCard(1)}
            onMouseLeave={() => setHoveredCard(null)}
            className={`landing-solid-card relative flex flex-col justify-between rounded-xl border border-primary/30 bg-white p-8 shadow-lg shadow-primary/8 transition-all duration-500 ease-out select-none ${
              hoveredCard === 1
                ? ""
                : hoveredCard !== null
                  ? "scale-[0.99]"
                  : ""
            }`}
            style={{
              transform: hoveredCard === 1
                ? "rotateX(0deg) rotateY(0deg) translateZ(24px) scale(1.012)"
                : hoveredCard !== null
                  ? "rotateX(10deg) rotateY(4deg) translateZ(-3px)"
                  : "rotateX(8deg) rotateY(2deg) translateZ(12px)",
              transformStyle: "preserve-3d",
            }}
          >
            {/* Badge */}
            <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-1 rounded-full bg-primary text-primary-foreground text-[11px] font-semibold tracking-wide whitespace-nowrap">
              MOST POPULAR
            </div>

            <div>
              <div className="mb-4">
                <h3 className="text-lg font-semibold text-foreground">Serious</h3>
                <p className="mt-1 text-xs text-muted-foreground leading-relaxed">For when you have an interview coming up and can&apos;t afford to guess.</p>
              </div>

              <div className="flex items-baseline gap-2 my-6" style={{ transform: "translateZ(10px)" }}>
                <span className={`font-bold tracking-tight transition-all duration-500 ease-out ${
                  isAnnual
                    ? "text-xl text-muted-foreground line-through opacity-60"
                    : "text-4xl text-foreground"
                }`}>
                  {formatPrice(seriousPricing.monthly)}
                </span>
                <span className={`font-bold tracking-tight transition-all duration-500 ease-out origin-left ${
                  isAnnual
                    ? "text-4xl text-foreground opacity-100 translate-x-0 max-w-[150px] scale-100"
                    : "text-xl text-transparent opacity-0 -translate-x-2 max-w-0 scale-75 pointer-events-none"
                } overflow-hidden whitespace-nowrap`}>
                  {formatPrice(seriousPricing.annual)}
                </span>
                <span className="text-xs text-muted-foreground">/ month</span>
              </div>

              {isAnnual && (
                <p className="text-[11px] text-muted-foreground mb-4">
                  billed {formatPrice(seriousPricing.annualBilled)} / year
                </p>
              )}

              <div className="space-y-3.5 border-t border-border/40 pt-6">
                {seriousFeatures.map((f) => (
                  <div key={f.text} className="flex items-start gap-2.5">
                    <Check className="h-4 w-4 shrink-0 text-primary mt-0.5" />
                    <span className="text-sm text-foreground/70 leading-relaxed">{f.text}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="mt-8 pt-4" style={{ transform: "translateZ(15px)" }}>
              <button
                onClick={onGetStarted}
                className="h-11 w-full rounded-lg bg-primary text-sm font-semibold text-primary-foreground shadow-lg shadow-primary/20 hover:shadow-primary/30 hover:brightness-110 transition-all duration-200 cursor-pointer"
              >
                Upgrade to Serious
              </button>
            </div>
          </div>

          {/* Card 3: Full Prep */}
          <div
            onMouseEnter={() => setHoveredCard(2)}
            onMouseLeave={() => setHoveredCard(null)}
            className={`landing-solid-card flex flex-col justify-between rounded-xl border border-border bg-white p-8 transition-all duration-500 ease-out select-none ${
              hoveredCard === 2
                ? "shadow-xl shadow-primary/5"
                : hoveredCard !== null
                  ? "scale-[0.99]"
                  : ""
            }`}
            style={{
              transform: hoveredCard === 2
                ? "rotateX(0deg) rotateY(0deg) translateZ(12px) scale(1.012)"
                : hoveredCard !== null
                  ? "rotateX(10deg) rotateY(-8deg) translateZ(-4px)"
                  : "rotateX(8deg) rotateY(-5deg) translateZ(0px)",
              transformStyle: "preserve-3d",
            }}
          >
            <div>
              <div className="mb-4">
                <h3 className="text-lg font-semibold text-foreground">Full Prep</h3>
                <p className="mt-1 text-xs text-muted-foreground leading-relaxed">Unlimited prep, fully calibrated to every role you apply for.</p>
              </div>

              <div className="mb-4 px-3 py-1.5 rounded-lg bg-primary/8 border border-primary/15 text-[11px] text-primary font-medium text-center">
                Early Bird: Register by 30 July 2026 to get Premium free for 1 month
              </div>

              <div className="flex items-baseline gap-2 my-6" style={{ transform: "translateZ(5px)" }}>
                <span className={`font-bold tracking-tight transition-all duration-500 ease-out ${
                  isAnnual
                    ? "text-xl text-muted-foreground line-through opacity-60"
                    : "text-4xl text-foreground"
                }`}>
                  {formatPrice(fullPrepPricing.monthly)}
                </span>
                <span className={`font-bold tracking-tight transition-all duration-500 ease-out origin-left ${
                  isAnnual
                    ? "text-4xl text-foreground opacity-100 translate-x-0 max-w-[150px] scale-100"
                    : "text-xl text-transparent opacity-0 -translate-x-2 max-w-0 scale-75 pointer-events-none"
                } overflow-hidden whitespace-nowrap`}>
                  {formatPrice(fullPrepPricing.annual)}
                </span>
                <span className="text-xs text-muted-foreground">/ month</span>
              </div>

              {isAnnual && (
                <p className="text-[11px] text-muted-foreground mb-4">
                  billed {formatPrice(fullPrepPricing.annualBilled)} / year
                </p>
              )}

              <div className="space-y-3.5 border-t border-border/40 pt-6">
                {fullPrepFeatures.map((f) => (
                  <div key={f.text} className="flex items-start gap-2.5">
                    <Check className="h-4 w-4 shrink-0 text-primary mt-0.5" />
                    <span className="text-sm text-foreground/70 leading-relaxed">{f.text}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="mt-8 pt-4" style={{ transform: "translateZ(10px)" }}>
              <button
                onClick={onGetStarted}
                className="h-11 w-full rounded-lg bg-secondary text-sm font-semibold text-foreground/70 hover:bg-secondary/80 hover:text-foreground transition-all duration-200 cursor-pointer"
              >
                Get Full Prep
              </button>
            </div>
          </div>

        </div>

        {/* Trust signal */}
        <p className="text-center mt-10 text-sm text-foreground/35 max-w-md mx-auto">
          Cancel anytime. No commitment. Built for the exact interview you&apos;re facing.
        </p>
      </div>
    </section>
  )
}
