"use client"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { MonitorPlay, Target, Check } from "lucide-react"

const modes = [
  {
    icon: MonitorPlay,
    title: "Mock Interview",
    description:
      "A comprehensive, end-to-end simulation. Respond to inquiries under simulated time constraints, followed by a detailed performance evaluation.",
    features: [
      "Timed questions that simulate real interviews",
      "Overall score plus per-answer feedback",
      "Session history to track your progress",
      "Objective evaluations of response effectiveness",
    ],
  },
  {
    icon: Target,
    title: "Exercise Modes",
    description:
      "Use focused drills like Write it, Say it, Fix it, Chain it, Blind Start, and Best vs Worst to repair specific answer patterns.",
    features: [
      "Question-type answer builders",
      "Weak-answer drill queue",
      "Pattern-level fixes",
      "Short reps between full mocks",
    ],
  },
]

interface ModesSectionProps {
  onGetStarted: () => void
}

export function ModesSection({ onGetStarted }: ModesSectionProps) {
  const [hoveredCard, setHoveredCard] = useState<number | null>(null)

  return (
    <section id="modes" className="relative px-6 py-28 md:py-36 overflow-visible bg-background-secondary/20">
      <div className="absolute inset-x-0 top-0 mx-auto h-px max-w-5xl bg-border" />

      <div className="mx-auto max-w-5xl">
        <div className="grid grid-cols-1 items-center gap-16 lg:grid-cols-2">

          {/* 3D Stages Container (Left Side) */}
          <div className="relative w-full min-h-[440px] flex flex-col gap-8 justify-center spatial-stage overflow-visible">

            {/* Stage 1: Full Mock */}
            <div
              onMouseEnter={() => setHoveredCard(0)}
              onMouseLeave={() => setHoveredCard(null)}
              className="landing-solid-card w-full max-w-[420px] rounded-xl border border-border/50 bg-white p-6 transition-all duration-500 ease-out select-none"
              style={{
                transform: hoveredCard === 0
                  ? "rotateX(10deg) rotateY(-8deg) translateZ(30px)"
                  : "rotateX(0) rotateY(0) translateZ(0)",
                boxShadow: hoveredCard === 0 ? "0 25px 50px -12px rgba(0,0,0,0.15)" : "none",
                transformStyle: "preserve-3d"
              }}
            >
              <div className="flex justify-between items-start mb-4">
                <div className="flex items-center gap-2.5">
                  <MonitorPlay className="h-5 w-5 text-primary" strokeWidth={1.5} />
                  <h3 className="text-base font-bold text-foreground">Interview Round</h3>
                </div>
                <span className="text-[9px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-primary/10 text-primary">Live voice</span>
              </div>
              <p className="text-xs text-muted-foreground leading-relaxed mb-4">
                Practise a natural, role-calibrated conversation with the camera on and focused feedback after the round.
              </p>

              {/* Floating Webcam mock frame */}
              <div
                className="landing-solid-card rounded-lg border border-border bg-white p-3 transition-all duration-500 flex items-center justify-between"
                style={{
                  transform: hoveredCard === 0 ? "translateZ(20px)" : "translateZ(0)"
                }}
              >
                <div className="flex items-center gap-2">
                  <div className="w-2.5 h-2.5 rounded-full bg-primary animate-pulse" />
                  <span className="text-[10px] font-bold text-foreground">Webcam Stream Active</span>
                </div>
                <span className="text-[10px] font-mono text-muted-foreground/60">00:12:45 elapsed</span>
              </div>
            </div>

            {/* Stage 2: Exercises */}
            <div
              onMouseEnter={() => setHoveredCard(1)}
              onMouseLeave={() => setHoveredCard(null)}
              className="landing-solid-card w-full max-w-[420px] self-end rounded-xl border border-border/50 bg-white p-6 transition-all duration-500 ease-out select-none"
              style={{
                transform: hoveredCard === 1
                  ? "rotateX(10deg) rotateY(8deg) translateZ(30px)"
                  : "rotateX(0) rotateY(0) translateZ(0)",
                boxShadow: hoveredCard === 1 ? "0 25px 50px -12px rgba(0,0,0,0.15)" : "none",
                transformStyle: "preserve-3d"
              }}
            >
              <div className="flex justify-between items-start mb-4">
                <div className="flex items-center gap-2.5">
                  <Target className="h-5 w-5 text-foreground/60" strokeWidth={1.5} />
                  <h3 className="text-base font-bold text-foreground">Focused Drills</h3>
                </div>
                <span className="text-[9px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-secondary text-muted-foreground">Tactical Reps</span>
              </div>
              <p className="text-xs text-muted-foreground leading-relaxed mb-4">
                Fix specific mistakes. Use focused drills to rebuild structural responses until they are solid.
              </p>

              {/* Drill cards */}
              <div className="flex gap-3 w-full justify-start mt-2 overflow-visible">
                {[
                  { label: "Write It", desc: "Draft responses" },
                  { label: "Say It", desc: "Vocal coaching" },
                  { label: "Fix It", desc: "Correct flaws" }
                ].map((item, idx) => (
                  <div
                    key={idx}
                    className="landing-solid-card flex-1 rounded-md border border-border bg-white p-3 flex flex-col justify-between premium-transition hover:-translate-y-1.5 hover:shadow-md hover:shadow-black/5 select-none cursor-pointer"
                    style={{
                      transformStyle: "preserve-3d"
                    }}
                  >
                    <span className="text-[10px] font-bold text-foreground">
                      {item.label}
                    </span>
                    <span className="text-[8px] text-muted-foreground mt-1 block leading-tight">
                      {item.desc}
                    </span>
                  </div>
                ))}
              </div>
            </div>

          </div>

          {/* Right Side Description */}
          <div className="flex flex-col items-start text-left">
            <span className="mb-4 text-xs font-semibold uppercase tracking-[0.25em] text-primary">
              Two ways to practice
            </span>
            <h2 className="text-4xl sm:text-5xl md:text-6xl font-semibold tracking-[-0.03em] leading-[1.05] text-foreground">
              Full mocks or focused drills.
            </h2>
            <p className="mt-6 max-w-md text-base leading-relaxed text-muted-foreground">
              Build confidence in a complete interview conversation, then use focused drills to strengthen the answers that need the most work.
            </p>
            <div className="mt-8">
              <Button
                onClick={onGetStarted}
                className="h-12 rounded-lg bg-primary px-8 text-sm font-semibold text-primary-foreground shadow-lg shadow-primary/20 premium-transition hover:brightness-110 hover:scale-[1.015] active:scale-[0.985] cursor-pointer"
              >
                Try Your First Interview
              </Button>
            </div>
          </div>

        </div>
      </div>
    </section>
  )
}
