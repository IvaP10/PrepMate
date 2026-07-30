"use client"

import { ArrowUpRight, BarChart3, CheckCircle2, MessageSquareQuote, Target } from "lucide-react"
import { useScrollReveal } from "@/hooks/use-scroll-reveal"

export function PerformanceSection() {
  const { ref, isVisible } = useScrollReveal({ threshold: 0.12 })

  return (
    <section id="performance" className="landing-chapter-gap landing-screen-section relative border-b border-border/40 px-6 py-12 md:py-14">
      <div ref={ref} className="mx-auto max-w-6xl">
        <div className="mx-auto max-w-3xl text-center">
          <h2 className={`text-balance text-3xl font-semibold tracking-[-0.035em] text-foreground sm:text-4xl ${isVisible ? "animate-fade-in-up" : "opacity-0"}`}>Feedback you can use.</h2>
          <p className={`mt-3 text-base leading-7 text-muted-foreground ${isVisible ? "animate-fade-in-up delay-100" : "opacity-0"}`}>See the evidence from your answer, the gap it reveals, and the best next retry.</p>
        </div>

        <div className={`mt-8 overflow-hidden rounded-2xl border border-border bg-card shadow-[0_18px_55px_rgba(15,23,42,0.08)] dark:shadow-[0_18px_55px_rgba(0,0,0,0.24)] ${isVisible ? "animate-fade-in-up delay-200" : "opacity-0"}`}>
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/70 px-5 py-4 sm:px-6">
            <div>
              <p className="text-sm font-semibold text-foreground">Session feedback</p>
              <p className="mt-0.5 text-xs text-muted-foreground">Interview Round · Backend Engineer</p>
            </div>
            <span className="rounded-full bg-primary/10 px-3 py-1 text-xs font-semibold text-primary">Evidence saved</span>
          </div>
          <div className="grid lg:grid-cols-[1.1fr_0.9fr]">
            <div className="space-y-4 border-b border-border/70 p-5 lg:border-b-0 lg:border-r sm:p-6">
              <p className="text-xs font-medium text-muted-foreground">Evidence</p>
              <div className="rounded-xl border border-border/70 p-4">
                <div className="flex items-center gap-2 text-sm font-semibold text-foreground"><MessageSquareQuote className="h-4 w-4 text-primary" /> Answer evidence</div>
                <p className="mt-3 text-sm leading-6 text-foreground/80">“I used staged releases and kept a rollback path.”</p>
                <div className="mt-4 flex items-center gap-3 border-t border-border/60 pt-3"><span className="text-xs font-medium text-muted-foreground">Story impact</span><div className="h-1.5 flex-1 overflow-hidden rounded-full bg-secondary"><span className="block h-full w-[62%] rounded-full bg-primary" /></div><span className="text-xs font-semibold text-foreground">62</span></div>
              </div>
              <div className="flex items-center gap-3 rounded-xl border border-border/70 p-4"><span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary"><BarChart3 className="h-4 w-4" /></span><div><p className="text-sm font-semibold text-foreground">Clear risk control</p><p className="mt-0.5 text-xs text-muted-foreground">Add the measured user outcome next.</p></div></div>
            </div>
            <div className="bg-secondary/25 p-5 sm:p-6">
              <p className="text-xs font-medium text-muted-foreground">Next attempt</p>
              <div className="mt-4 rounded-xl border border-primary/20 bg-primary/5 p-4"><div className="flex gap-2"><Target className="mt-0.5 h-4 w-4 shrink-0 text-primary" /><div><p className="text-sm font-semibold text-foreground">Focused Drill ready</p><p className="mt-1 text-xs leading-5 text-muted-foreground">Retry this story with a measurable result.</p></div></div></div>
              <div className="mt-4 rounded-xl border border-border/70 bg-card p-4"><div className="flex items-center justify-between"><div className="flex items-center gap-2 text-sm font-semibold text-foreground"><CheckCircle2 className="h-4 w-4 text-primary" /> Improvement</div><ArrowUpRight className="h-4 w-4 text-primary" /></div><div className="mt-4 flex items-end gap-2"><span className="h-5 w-[62%] rounded-sm bg-primary/25" /><span className="h-8 w-[78%] rounded-sm bg-primary" /></div><div className="mt-2 flex justify-between text-xs text-muted-foreground"><span>Original</span><span>Retry</span></div></div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
