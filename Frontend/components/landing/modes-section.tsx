"use client"
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
    title: "Practice Mode",
    description:
      "Proceed question-by-question with immediate, targeted feedback. Ideal for refining specific communication skills in a low-pressure environment.",
    features: [
      "Immediate feedback following each response",
      "Iterate and refine responses seamlessly",
      "Focus on specific question categories",
      "Build confidence at your own pace",
    ],
  },
]
interface ModesSectionProps {
  onGetStarted: () => void
}
export function ModesSection({ onGetStarted }: ModesSectionProps) {
  return (
    <section className="relative px-6 py-28">
      <div className="absolute inset-x-0 top-0 mx-auto h-px max-w-5xl bg-border" />
      <div className="mx-auto max-w-5xl">
        <div className="grid grid-cols-1 items-center gap-16 lg:grid-cols-2">
          <div className="flex flex-col gap-4">
            {modes.map((mode) => (
              <div
                key={mode.title}
                className="group overflow-hidden rounded-2xl bg-secondary/50 transition-all duration-500 ease-out hover:-translate-y-1"
              >
                <div className="flex items-start justify-between p-5">
                  <div className="flex flex-col gap-1.5">
                    <h3 className="text-base font-semibold text-foreground transition-colors duration-300">{mode.title}</h3>
                    <p className="max-w-[280px] text-sm leading-relaxed text-muted-foreground">
                      {mode.description}
                    </p>
                  </div>
                  <mode.icon className="h-5 w-5 shrink-0 text-accent-indigo/70" strokeWidth={1.5} />
                </div>
                <div className="flex flex-col gap-2.5 px-5 pb-5">
                  {mode.features.map((feature, fi) => (
                    <div
                      key={feature}
                      className="flex items-center gap-2.5 transition-transform duration-300 group-hover:translate-x-1"
                      style={{ transitionDelay: `${fi * 50}ms` }}
                    >
                      <Check className="h-3.5 w-3.5 shrink-0 text-accent-indigo/70" strokeWidth={1.5} />
                      <span className="text-sm text-muted-foreground">{feature}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
          <div className="flex flex-col">
            <span className="mb-4 text-sm font-medium uppercase tracking-[0.25em] text-muted-foreground">
              Two Modes
            </span>
            <h2 className="font-serif text-3xl leading-[1.2] tracking-tight sm:text-4xl">
              <span className="text-shimmer">Tailored simulation modes.</span>
              <br />
              <span className="text-shimmer-accent">Designed for optimal preparation.</span>
            </h2>
            <p className="mt-5 max-w-md text-base leading-relaxed text-muted-foreground">
              Whether you require a complete, pressurized interview simulation or focused, step-by-step practice, our platform provides the tools necessary to confidently approach your next professional opportunity.
            </p>
            <div className="mt-8">
              <Button
                onClick={onGetStarted}
                className="h-11 rounded-full bg-primary px-6 text-sm font-semibold text-primary-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.1),0_1px_3px_rgba(0,0,0,0.1)] transition-all duration-150 hover:opacity-95 active:scale-[0.98] active:shadow-[inset_0_2px_4px_rgba(0,0,0,0.1)]"
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
