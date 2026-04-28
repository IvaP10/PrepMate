"use client"
import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { ArrowRight } from "lucide-react"

interface HeroSectionProps {
  onGetStarted: () => void
}

export function HeroSection({ onGetStarted }: HeroSectionProps) {
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    const t = setTimeout(() => setLoaded(true), 100)
    return () => clearTimeout(t)
  }, [])

  return (
    <section className="relative flex min-h-[100vh] flex-col items-center justify-center overflow-hidden px-6 pt-20">

      <div className="relative z-10 mx-auto flex max-w-4xl flex-col items-center text-center">
        {/* Eyebrow badge */}
        <button
          type="button"
          onClick={onGetStarted}
          className={`group mb-12 inline-flex cursor-pointer items-center gap-2.5 rounded-full border border-border bg-card/80 px-5 py-2.5 backdrop-blur-sm transition-all duration-500 hover:border-primary/50 hover:bg-card hover:shadow-[0_0_25px_rgba(37,99,235,0.15)] ${
            loaded ? "opacity-100 translate-y-0" : "opacity-0 translate-y-4"
          }`}
          style={{ transitionDelay: "200ms" }}
        >
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary/60 opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
          </span>
          <span className="text-sm text-muted-foreground">
            AI-Powered Interview Coaching
          </span>
          <span className="inline-flex items-center gap-1 text-sm font-medium text-primary transition-transform duration-200 group-hover:translate-x-0.5">
            Get started
            <ArrowRight className="h-3.5 w-3.5" />
          </span>
        </button>

        {/* Main headline — line-by-line reveal */}
        <h1 className="font-serif text-4xl leading-[1.1] tracking-tight sm:text-5xl md:text-6xl lg:text-7xl relative z-10">
          <span className="overflow-hidden block">
            <span
              className={`block transition-all duration-700 ease-out ${
                loaded ? "translate-y-0 opacity-100" : "translate-y-full opacity-0"
              }`}
              style={{ transitionDelay: "400ms" }}
            >
              <span className="text-shimmer">Master your interviews</span>
            </span>
          </span>
          <span className="overflow-hidden block">
            <span
              className={`block transition-all duration-700 ease-out ${
                loaded ? "translate-y-0 opacity-100" : "translate-y-full opacity-0"
              }`}
              style={{ transitionDelay: "550ms" }}
            >
              <span className="text-shimmer">with AI-driven </span>
              <span className="text-shimmer-accent">practice.</span>
            </span>
          </span>
        </h1>

        {/* Subtitle */}
        <p
          className={`mt-8 max-w-xl text-pretty text-lg leading-relaxed text-muted-foreground sm:text-xl relative z-10 transition-all duration-700 ease-out ${
            loaded ? "opacity-100 translate-y-0 blur-0" : "opacity-0 translate-y-6 blur-sm"
          }`}
          style={{ transitionDelay: "700ms" }}
        >
          Upload your resume, select your target industry, and engage in realistic, simulated interviews. Receive actionable, real-time feedback to secure your next role.
        </p>

        {/* CTA */}
        <div
          className={`mt-10 flex flex-wrap items-center justify-center gap-4 relative z-10 transition-all duration-700 ease-out ${
            loaded ? "opacity-100 translate-y-0" : "opacity-0 translate-y-6"
          }`}
          style={{ transitionDelay: "900ms" }}
        >
          <Button
            size="lg"
            onClick={onGetStarted}
            className="h-13 rounded-full bg-primary px-8 text-base font-semibold text-primary-foreground transition-all duration-300 hover:scale-105 hover:shadow-[0_0_30px_rgba(37,99,235,0.3)] relative overflow-hidden group"
          >
            <span className="relative z-10">Start Your Free Mock Interview</span>
            <span className="absolute inset-0 bg-gradient-to-r from-transparent via-white/10 to-transparent translate-x-[-200%] group-hover:translate-x-[200%] transition-transform duration-700" />
          </Button>
        </div>

        {/* Trust metrics */}
        <div
          className={`mt-16 flex items-center gap-8 text-xs font-mono text-muted-foreground/50 uppercase tracking-widest transition-all duration-700 ${
            loaded ? "opacity-100" : "opacity-0"
          }`}
          style={{ transitionDelay: "1100ms" }}
        >
          <span>Resume Aware</span>
          <span className="h-px w-4 bg-border" />
          <span>Real-time Feedback</span>
          <span className="h-px w-4 bg-border" />
          <span>AI Coaching</span>
        </div>
      </div>

      {/* Scroll line indicator (no text) */}
      <div
        className={`absolute bottom-8 left-1/2 -translate-x-1/2 transition-all duration-700 ${
          loaded ? "opacity-100" : "opacity-0"
        }`}
        style={{ transitionDelay: "1300ms" }}
      >
        <div className="w-px h-10 bg-gradient-to-b from-transparent via-muted-foreground/30 to-muted-foreground/50 animate-pulse" />
      </div>
    </section>
  )
}
