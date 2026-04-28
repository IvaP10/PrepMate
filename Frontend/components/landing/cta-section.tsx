"use client"
import { Button } from "@/components/ui/button"
import { ArrowRight, Check } from "lucide-react"
import { useEffect, useState } from "react"
import { useScrollReveal } from "@/hooks/use-scroll-reveal"
interface CtaSectionProps {
  onGetStarted: () => void
}
const benefits = [
  "Questions tailored to your actual resume",
  "Scored mock interviews with actionable feedback",
  "Practice mode with strategic advice per response",
]
const TARGET_SCORE = 86
const TARGET_SESSIONS = 12
const TARGET_PRACTICE_HOURS = 4.2
export function CtaSection({ onGetStarted }: CtaSectionProps) {
  const { ref: cardRef, isVisible } = useScrollReveal({ threshold: 0.3 })
  const { ref: rightSideRef, isVisible: isRightVisible } = useScrollReveal({ threshold: 0.2 })
  const [animatedScore, setAnimatedScore] = useState(0)
  const [animatedSessions, setAnimatedSessions] = useState(0)
  const [animatedPractice, setAnimatedPractice] = useState(0)
  useEffect(() => {
    if (!isVisible) return
    const duration = 1500
    const startTime = performance.now()
    const animate = (currentTime: number) => {
      const elapsed = currentTime - startTime
      const progress = Math.min(elapsed / duration, 1)
      const easeOut = 1 - Math.pow(1 - progress, 3)
      setAnimatedScore(Math.round(easeOut * TARGET_SCORE))
      setAnimatedSessions(Math.round(easeOut * TARGET_SESSIONS))
      setAnimatedPractice(Math.round(easeOut * TARGET_PRACTICE_HOURS * 10) / 10)
      if (progress < 1) {
        requestAnimationFrame(animate)
      }
    }
    requestAnimationFrame(animate)
  }, [isVisible])
  const progressAngle = (animatedScore / 100) * 360
  return (
    <section className="px-6 py-28 relative">
      <div className="mx-auto max-w-6xl">
        <div className="mb-28 h-px w-full bg-border" />
        <div className="grid grid-cols-1 items-center gap-16 lg:grid-cols-2">
          <div className="flex w-full justify-center lg:justify-end">
            <div
              ref={cardRef}
              className={`relative w-full max-w-sm overflow-hidden rounded-2xl border border-border/40 bg-card/60 shadow-[0_12px_40px_-15px_rgba(37,99,235,0.12)] transition-all duration-[800ms] ease-out hover:-translate-y-2 ${isVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-20'}`}
            >
              <div className="flex flex-col p-6 backdrop-blur-md">
                <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-xl bg-secondary text-primary ring-1 ring-border/50">
                  <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" /><path d="M19 10v2a7 7 0 0 1-14 0v-2" /><line x1="12" x2="12" y1="19" y2="22" /></svg>
                </div>
                <h3 className="text-xl font-semibold tracking-tight text-foreground">Full Mock Interview</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground/90">
                  Comprehensive 30-45 minute role-play. Experience a realistic professional interview environment.
                </p>
                <div className="mt-4 flex flex-wrap gap-2">
                  <span className="rounded-lg bg-secondary px-2.5 py-1 text-xs font-medium text-muted-foreground ring-1 ring-border/50">Behavioral</span>
                  <span className="rounded-lg bg-secondary px-2.5 py-1 text-xs font-medium text-muted-foreground ring-1 ring-border/50">Technical</span>
                </div>
              </div>
              <div className="border-t border-border/40 bg-card/80 p-5">
                <div className="flex w-full items-center justify-center gap-2 rounded-full border border-border bg-primary/10 h-10 text-sm font-semibold text-primary transition-all cursor-default">
                  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="6 3 20 12 6 21 6 3" /></svg>
                  Initiate Mock Interview
                </div>
              </div>
            </div>
          </div>
          <div ref={rightSideRef} className="flex flex-col">
            <span className={`mb-4 text-sm font-medium uppercase tracking-[0.25em] text-muted-foreground ${isRightVisible ? 'animate-fade-in-up' : 'opacity-0'}`}>
              Why It Works
            </span>
            <h2 className="font-serif text-3xl leading-[1.2] tracking-tight sm:text-4xl">
              <span className={`text-shimmer inline-block ${isRightVisible ? 'animate-blur-in delay-100' : 'opacity-0'}`}>Experience measurable improvement</span>
              <br />
              <span className={`text-shimmer-accent inline-block ${isRightVisible ? 'animate-blur-in delay-200' : 'opacity-0'}`}>through consistent practice.</span>
            </h2>
            <p className={`mt-5 max-w-md text-base leading-relaxed text-muted-foreground ${isRightVisible ? 'animate-fade-in-up delay-300' : 'opacity-0'}`}>
              Consistent, targeted practice refines your communication skills. Build confidence, articulate your value proposition clearly, and approach every interview with professional assurance.
            </p>
            <div className={`mt-8 flex flex-col gap-4 ${isRightVisible ? 'animate-fade-in-up delay-400' : 'opacity-0'}`}>
              {benefits.map((benefit) => (
                <div key={benefit} className="group/benefit flex items-center gap-3 transition-transform duration-300 hover:translate-x-1">
                  <Check className="h-4 w-4 shrink-0 text-accent-indigo/70" strokeWidth={1.5} />
                  <span className="text-base font-medium text-foreground">{benefit}</span>
                </div>
              ))}
            </div>
            <div className={`mt-10 flex flex-wrap gap-3 ${isRightVisible ? 'animate-fade-in-up delay-500' : 'opacity-0'}`}>
              <div className="hover-border-reveal rounded-full">
                <Button
                  onClick={onGetStarted}
                  className="group h-11 rounded-full bg-primary px-6 text-sm font-semibold text-primary-foreground transition-all duration-300 hover:scale-105"
                >
                  Start Practicing Now
                  <ArrowRight className="ml-1.5 h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                </Button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
