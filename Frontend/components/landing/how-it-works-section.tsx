"use client"
import { useScrollReveal } from "@/hooks/use-scroll-reveal"
import { Shuffle, Wrench, Video, Mic, FileText, Settings, ArrowRight } from "lucide-react"

/* ── Step 1 Visual: Contextualize ── */
function StepOneVisual() {
  return (
    <div className="relative w-full h-[150px] bg-secondary/25 border border-border/40 rounded-lg flex items-center justify-center p-4 overflow-hidden">
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(20,21,23,0.02)_1px,transparent_1px),linear-gradient(90deg,rgba(20,21,23,0.02)_1px,transparent_1px)] bg-[size:16px_16px] dark:bg-[linear-gradient(rgba(255,255,255,0.01)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.01)_1px,transparent_1px)]" />

      <div className="relative flex items-center gap-3 w-full max-w-[280px] justify-between">
        {/* Left: Input Files */}
        <div className="flex flex-col gap-2 shrink-0">
          <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-primary/10 border border-primary/20 text-primary text-[9px] font-bold">
            <FileText className="w-3.5 h-3.5" />
            resume.pdf
          </div>
          <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-primary/10 border border-primary/20 text-primary text-[9px] font-bold">
            <FileText className="w-3.5 h-3.5" />
            job_desc.md
          </div>
        </div>

        {/* Center: Connector Arrow */}
        <div className="flex items-center justify-center text-muted-foreground animate-pulse">
          <ArrowRight className="w-4 h-4" />
        </div>

        {/* Right: Settings Control panel */}
        <div className="landing-solid-card shadow-sm border border-border/80 rounded-md p-2 flex flex-col gap-1.5 w-[110px]">
          <div className="flex items-center gap-1 text-[8px] font-bold text-muted-foreground uppercase">
            <Settings className="w-2.5 h-2.5" />
            Config
          </div>
          <div className="h-px bg-border/50" />
          <div className="flex items-center justify-between text-[9px] font-semibold text-foreground/85">
            <span>Startup</span>
            <span className="w-5 h-3 bg-primary/20 border border-primary/30 rounded-full flex items-center px-0.5 justify-end">
              <span className="w-2 h-2 rounded-full bg-primary" />
            </span>
          </div>
          <div className="text-[9px] font-bold text-primary">
            Top Tier
          </div>
        </div>
      </div>
    </div>
  )
}

/* ── Step 2 Visual: Simulate ── */
function StepTwoVisual() {
  return (
    <div className="relative w-full h-[150px] bg-secondary/25 border border-border/40 rounded-lg flex items-center justify-center p-4 overflow-hidden">
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(20,21,23,0.02)_1px,transparent_1px),linear-gradient(90deg,rgba(20,21,23,0.02)_1px,transparent_1px)] bg-[size:16px_16px] dark:bg-[linear-gradient(rgba(255,255,255,0.01)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.01)_1px,transparent_1px)]" />

      <div className="relative flex items-center gap-3 w-full max-w-[280px] justify-between">
        {/* Left: Webcam Placeholder */}
        <div className="relative w-[110px] h-[75px] rounded-lg bg-secondary border border-border shadow-md flex items-center justify-center overflow-hidden">
          <div className="absolute top-1.5 left-1.5 flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse" />
            <span className="text-[6.5px] font-mono text-muted-foreground uppercase tracking-widest leading-none">Live</span>
          </div>
          <div className="w-5 h-5 rounded-full bg-secondary border border-border flex items-center justify-center">
            <Video className="w-2.5 h-2.5 text-muted-foreground" />
          </div>
        </div>

        {/* Right: Audio Waveform Panel */}
        <div className="landing-solid-card shadow-sm border border-border/80 rounded-md p-2 flex flex-col gap-1.5 w-[130px] h-[75px] justify-between transition-all duration-300 hover:border-primary/40 hover:shadow-[0_0_15px_rgba(115,86,197,0.1)]">
          <div className="flex items-center justify-between text-[8px] font-bold text-muted-foreground uppercase">
            <div className="flex items-center gap-1">
              <Mic className="w-2.5 h-2.5 text-primary group-hover:scale-110 transition-transform duration-300" />
              Mic State
            </div>
            <span className="text-primary group-hover:animate-pulse">Active</span>
          </div>
          {/* Wave heights */}
          <div className="flex items-end justify-between h-5 gap-0.5 px-0.5">
            {[40, 70, 30, 90, 50, 80, 20, 60, 40, 75, 15, 50].map((h, i) => (
              <div
                key={i}
                className="w-1.5 bg-primary/70 rounded-full landing-wave-bar"
                style={{ height: `${h}%`, animationDelay: `${i * 80}ms` }}
              />
            ))}
          </div>
          <div className="text-[7.5px] text-muted-foreground text-center font-mono group-hover:text-primary transition-colors duration-300">
            Analyzing speech pacing...
          </div>
        </div>
      </div>
    </div>
  )
}

/* ── Step 3 Visual: Repair ── */
function StepThreeVisual() {
  return (
    <div className="relative w-full h-[150px] bg-secondary/25 border border-border/40 rounded-lg flex items-center justify-center p-4 overflow-hidden">
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(20,21,23,0.02)_1px,transparent_1px),linear-gradient(90deg,rgba(20,21,23,0.02)_1px,transparent_1px)] bg-[size:16px_16px] dark:bg-[linear-gradient(rgba(255,255,255,0.01)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.01)_1px,transparent_1px)]" />

      <div className="relative flex gap-3 w-full max-w-[280px] justify-between">
        {/* Blind Start Card */}
        <div className="landing-solid-card shadow-sm border border-border/80 rounded-md p-2.5 flex flex-col gap-1 w-[125px] h-[80px] justify-between">
          <div className="flex items-center gap-1.5 text-[10.5px] font-bold text-foreground">
            <Shuffle className="w-3.5 h-3.5 text-muted-foreground" />
            Blind Start
          </div>
          <div className="text-[7.5px] leading-relaxed text-muted-foreground">
            No context, rapid-fire drills.
          </div>
          <span className="text-[8px] font-semibold text-primary bg-primary/10 border border-primary/20 px-1.5 py-0.5 rounded w-fit">
            3 drills queued
          </span>
        </div>

        {/* Fix It Card */}
        <div className="landing-solid-card shadow-sm border border-border/80 rounded-md p-2.5 flex flex-col gap-1 w-[125px] h-[80px] justify-between">
          <div className="flex items-center gap-1.5 text-[10.5px] font-bold text-foreground">
            <Wrench className="w-3.5 h-3.5 text-muted-foreground" />
            Fix It
          </div>
          <div className="text-[7.5px] leading-relaxed text-muted-foreground">
            Guided response revisions.
          </div>
          <span className="text-[8px] font-semibold text-primary/70 bg-primary/5 border border-primary/15 px-1.5 py-0.5 rounded w-fit">
            5 errors flagged
          </span>
        </div>
      </div>
    </div>
  )
}

export function HowItWorksSection() {
  const { ref: sectionRef, isVisible } = useScrollReveal({ threshold: 0.15 })

  return (
    <section
      id="how-it-works"
      className="relative px-6 py-28 md:py-36 border-t border-border/40"
    >
      <div ref={sectionRef} className="mx-auto max-w-6xl">
        {/* Section Header */}
        <div className="mx-auto mb-20 max-w-2xl text-center">
          <span
            className={`mb-4 inline-block text-xs font-semibold uppercase tracking-[0.25em] text-primary ${
              isVisible ? "animate-fade-in-up" : "opacity-0"
            }`}
          >
            The Process
          </span>
          <h2
            className={`text-balance text-4xl sm:text-5xl md:text-6xl font-semibold tracking-[-0.03em] leading-[1.05] text-foreground transition-all duration-700 ${
              isVisible ? "animate-blur-in delay-100" : "opacity-0"
            }`}
          >
            How InterAI works.
          </h2>
          <p
            className={`mt-6 text-base text-muted-foreground leading-[1.7] ${
              isVisible ? "animate-fade-in-up delay-300" : "opacity-0"
            }`}
          >
            Three steps. Your resume, the job description, and an AI that builds the interview around both. No generic question banks.
          </p>
        </div>

        {/* 3-Step Timeline Grid */}
        <div
          className={`grid grid-cols-1 lg:grid-cols-3 gap-8 transition-all duration-700 ${
            isVisible ? "animate-fade-in-up delay-300" : "opacity-0"
          }`}
        >
          {/* Step 1: Contextualize */}
          <div className="landing-solid-card p-6 border border-border/80 flex flex-col gap-6 justify-between min-h-[380px] rounded-xl hover:scale-[1.01] hover:shadow-xl hover:border-border transition-all duration-300">
            <div>
              <div className="flex items-center justify-between mb-4">
                <span className="text-sm font-bold uppercase tracking-wider text-primary">Step 01</span>
                <span className="text-[9px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-primary/10 text-primary">Setup</span>
              </div>
              <h3 className="text-xl font-bold text-foreground tracking-tight mb-3">Upload Your Profile</h3>
              <p className="text-sm text-muted-foreground leading-[1.6]">
                Paste your resume and the job description. The engine maps your experience against the role requirements to build a custom interview.
              </p>
            </div>
            <StepOneVisual />
          </div>

          {/* Step 2: Simulate */}
          <div className="group landing-solid-card p-6 border border-border/80 flex flex-col gap-6 justify-between min-h-[380px] rounded-xl hover:scale-[1.01] hover:shadow-xl hover:border-border transition-all duration-300">
            <div>
              <div className="flex items-center justify-between mb-4">
                <span className="text-sm font-bold uppercase tracking-wider text-primary">Step 02</span>
                <span className="text-[9px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-primary/10 text-primary">Execution</span>
              </div>
              <h3 className="text-xl font-bold text-foreground tracking-tight mb-3">Run the Simulation</h3>
              <p className="text-sm text-muted-foreground leading-[1.6]">
                The AI builds a custom interview loop for your exact role. Every question targets your profile gaps. No two sessions are the same.
              </p>
            </div>
            <StepTwoVisual />
          </div>

          {/* Step 3: Repair */}
          <div className="landing-solid-card p-6 border border-border/80 flex flex-col gap-6 justify-between min-h-[380px] rounded-xl hover:scale-[1.01] hover:shadow-xl hover:border-border transition-all duration-300">
            <div>
              <div className="flex items-center justify-between mb-4">
                <span className="text-sm font-bold uppercase tracking-wider text-primary">Step 03</span>
                <span className="text-[9px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-primary/10 text-primary">Feedback</span>
              </div>
              <h3 className="text-xl font-bold text-foreground tracking-tight mb-3">Fix Your Weaknesses</h3>
              <p className="text-sm text-muted-foreground leading-[1.6]">
                Get evidence-backed feedback for the areas you actually completed. Communication and technical evidence stay separate, and missing evidence is never invented.
              </p>
            </div>
            <StepThreeVisual />
          </div>
        </div>
      </div>
    </section>
  )
}
