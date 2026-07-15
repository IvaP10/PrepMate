"use client"
import { Check } from "lucide-react"
import { useState } from "react"
import { useScrollReveal } from "@/hooks/use-scroll-reveal"

interface CtaSectionProps {
  onGetStarted: () => void
}

const benefits = [
  "Questions tailored to your actual resume",
  "Scored mock interviews with actionable feedback",
  "Focused Improve drills for weak answers",
]

export function CtaSection({ onGetStarted }: CtaSectionProps) {
  const { ref: cardRef, isVisible } = useScrollReveal({ threshold: 0.3 })
  const { ref: rightSideRef, isVisible: isRightVisible } = useScrollReveal({ threshold: 0.2 })
  const [hovered, setHovered] = useState(false)

  return (
    <section className="relative overflow-visible px-6 pb-16 pt-24 md:pb-20 md:pt-28">
      <div className="mx-auto max-w-6xl">
        <div className="mb-16 h-px w-full bg-border" />
        <div className="grid grid-cols-1 items-center gap-12 overflow-visible lg:grid-cols-2 spatial-stage">

          {/* 3D Floating Preview (Left Side) */}
          <div className="flex w-full justify-center lg:justify-end">
            <div
              ref={cardRef}
              onMouseEnter={() => setHovered(true)}
              onMouseLeave={() => setHovered(false)}
              className={`landing-solid-card relative w-full max-w-sm overflow-visible rounded-xl border border-border bg-white transition-all duration-[900ms] ease-out select-none shadow-2xl shadow-black/5 ${
                isVisible ? 'opacity-100 translate-y-0 scale-100' : 'opacity-0 translate-y-20 scale-95'
              }`}
              style={{
                transform: hovered ? "rotateX(8deg) rotateY(-8deg) translateZ(24px)" : "rotateX(4deg) rotateY(-4deg) translateZ(0)",
                transformStyle: "preserve-3d",
              }}
            >
              <div className="flex flex-col p-6" style={{ transformStyle: "preserve-3d" }}>
                <div
                  className="mb-5 flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary border border-primary/20 shadow-sm"
                  style={{ transform: "translateZ(15px)" }}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" /><path d="M19 10v2a7 7 0 0 1-14 0v-2" /><line x1="12" x2="12" y1="19" y2="22" /></svg>
                </div>
                <h3 className="text-xl font-bold tracking-tight text-foreground leading-snug">Simulated Interview</h3>
                <p className="mt-2 text-xs leading-[1.6] text-muted-foreground">
                  A natural voice Interview Round tailored to your resume and the role. Technical assessments run separately in a focused workspace.
                </p>
                <div className="mt-4 flex flex-wrap gap-2" style={{ transform: "translateZ(10px)" }}>
                  <span className="rounded bg-secondary px-2.5 py-1 text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Voice</span>
                  <span className="rounded bg-secondary px-2.5 py-1 text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Resume</span>
                  <span className="rounded bg-secondary px-2.5 py-1 text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Role Calibrated</span>
                </div>
              </div>

              <div
                className="landing-solid-card border-t border-border/40 bg-white p-5 rounded-b-xl"
                style={{ transform: "translateZ(20px)" }}
              >
                <div className="flex w-full items-center justify-center gap-2 rounded-lg border border-primary/30 bg-primary text-primary-foreground h-11 text-xs font-bold uppercase tracking-wider shadow-lg shadow-primary/15 transition-all cursor-default">
                  <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polygon points="6 3 20 12 6 21 6 3" /></svg>
                  Start Interview
                </div>
              </div>
            </div>
          </div>

          {/* Right Side Content */}
          <div ref={rightSideRef} className="flex flex-col items-start text-left">
            <span className={`mb-4 text-xs font-semibold uppercase tracking-[0.25em] text-primary ${isRightVisible ? 'animate-fade-in-up' : 'opacity-0'}`}>
              Ready to start
            </span>
            <h2
              className={`text-4xl sm:text-5xl md:text-6xl font-semibold tracking-[-0.03em] leading-[1.05] text-foreground transition-all duration-700 ${isRightVisible ? 'animate-blur-in delay-100' : 'opacity-0'}`}
            >
              Stop reading interview guides.
            </h2>
            <p className={`mt-3 text-2xl sm:text-3xl font-medium text-foreground/50 tracking-tight ${isRightVisible ? 'animate-fade-in-up delay-200' : 'opacity-0'}`}>
              Start practicing your answers.
            </p>
            <p className={`mt-6 text-base leading-relaxed text-muted-foreground ${isRightVisible ? 'animate-fade-in-up delay-300' : 'opacity-0'}`}>
              Paste your resume and the job description. The first mock interview is free. No credit card, no commitment.
            </p>
            <div className={`mt-8 flex flex-col gap-4 ${isRightVisible ? 'animate-fade-in-up delay-400' : 'opacity-0'}`}>
              {benefits.map((benefit) => (
                <div key={benefit} className="flex items-center gap-3">
                  <Check className="h-4 w-4 shrink-0 text-primary" strokeWidth={2} />
                  <span className="text-sm font-semibold text-foreground">{benefit}</span>
                </div>
              ))}
            </div>
            <div className={`mt-10 ${isRightVisible ? 'animate-fade-in-up delay-500' : 'opacity-0'}`}>
              <button
                onClick={onGetStarted}
                className="h-12 rounded-lg bg-primary px-8 text-sm font-semibold text-primary-foreground shadow-lg shadow-primary/25 premium-transition hover:scale-[1.015] hover:brightness-110 hover:shadow-xl hover:shadow-primary/30 active:scale-[0.985] cursor-pointer"
              >
                Create Your Account
              </button>
            </div>
          </div>

        </div>
      </div>
    </section>
  )
}
