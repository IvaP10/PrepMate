"use client"

import { ArrowDown, ArrowRight, BarChart3, ClipboardCheck, FileUp, MessageSquareText, Target } from "lucide-react"
import { useScrollReveal } from "@/hooks/use-scroll-reveal"

const steps = [
  {
    icon: FileUp,
    number: "01",
    title: "Add your context",
    description: "Add a resume and job description.",
  },
  {
    icon: MessageSquareText,
    number: "02",
    title: "Take the interview",
    description: "Choose Interview Round or Technical Round.",
  },
  {
    icon: ClipboardCheck,
    number: "03",
    title: "Review the evidence",
    description: "See feedback tied to your work.",
  },
]

const loop = [
  { icon: Target, title: "Weakness detected", description: "A gap is saved from your session." },
  { icon: ClipboardCheck, title: "Drill created", description: "One focused retry is ready." },
  { icon: MessageSquareText, title: "Answer retried", description: "New evidence replaces the guesswork." },
  { icon: BarChart3, title: "Improvement measured", description: "See what changed on the next attempt." },
]

export function HowItWorksSection() {
  const { ref, isVisible } = useScrollReveal({ threshold: 0.12 })

  return (
    <section id="how-it-works" className="landing-chapter-gap landing-screen-section relative border-b border-border/40 px-6 py-12 md:py-14">
      <div ref={ref} className="mx-auto max-w-6xl">
        <div className="max-w-2xl">
          <h2 className={`text-balance text-3xl font-semibold tracking-[-0.035em] text-foreground sm:text-4xl ${isVisible ? "animate-fade-in-up" : "opacity-0"}`}>Every practice session has a clear next step.</h2>
          <p className={`mt-3 max-w-xl text-base leading-7 text-muted-foreground ${isVisible ? "animate-fade-in-up delay-100" : "opacity-0"}`}>Set the context once, then turn each answer into a more useful retry.</p>
        </div>

        <div className={`mt-8 grid gap-4 md:grid-cols-3 ${isVisible ? "animate-fade-in-up delay-100" : "opacity-0"}`}>
          {steps.map((step) => (
            <article key={step.number} className="landing-solid-card rounded-xl border border-border p-5 sm:p-6">
              <div className="flex items-center justify-between">
                <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary"><step.icon className="h-5 w-5" /></span>
                <span className="text-xs font-semibold text-muted-foreground">{step.number}</span>
              </div>
              <h3 className="mt-5 text-lg font-semibold text-foreground">{step.title}</h3>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">{step.description}</p>
            </article>
          ))}
        </div>

        <div className={`mt-6 overflow-hidden rounded-2xl border border-primary/20 bg-primary/[0.045] p-5 sm:p-6 ${isVisible ? "animate-fade-in-up delay-200" : "opacity-0"}`}>
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground"><Target className="h-4 w-4" /></span>
            <div><p className="font-semibold text-foreground">The improvement loop</p><p className="mt-0.5 text-sm text-muted-foreground">One answer becomes a measurable next move.</p></div>
          </div>
          <div className="relative mt-7">
            <div className="absolute left-5 top-5 h-[calc(100%-2.5rem)] w-px bg-primary/25 md:left-[12.5%] md:top-5 md:h-px md:w-[75%]" aria-hidden="true" />
            <div className="grid gap-5 md:grid-cols-4 md:gap-3">
              {loop.map((item, index) => (
                <div key={item.title} className="relative z-10 flex gap-3 bg-transparent md:flex-col md:items-center md:text-center">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-primary/25 bg-card text-primary shadow-sm"><item.icon className="h-4 w-4" /></span>
                  <div className="min-w-0 md:max-w-[11rem]"><p className="text-sm font-semibold text-foreground">{item.title}</p><p className="mt-1 text-xs leading-5 text-muted-foreground">{item.description}</p></div>
                  {index < loop.length - 1 && <><ArrowRight className="absolute -right-2 top-3 hidden h-4 w-4 rounded-full bg-primary/[0.045] text-primary md:block" aria-hidden="true" /><ArrowDown className="absolute left-3 top-11 h-4 w-4 bg-primary/[0.045] text-primary md:hidden" aria-hidden="true" /></>}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
