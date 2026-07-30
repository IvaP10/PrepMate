"use client"

import { Braces, MessageSquareText, Target } from "lucide-react"
import { Button } from "@/components/ui/button"

type PracticeMode = "interview" | "technical" | "drill"

const practiceTypes = [
  {
    title: "Interview Round",
    icon: MessageSquareText,
    mode: "interview" as PracticeMode,
    description: "Role-aware questions with voice and transcript feedback.",
  },
  {
    title: "Technical Round",
    icon: Braces,
    mode: "technical" as PracticeMode,
    description: "A practical question, your code, and the reasoning behind it.",
  },
  {
    title: "Focused Drills",
    icon: Target,
    mode: "drill" as PracticeMode,
    description: "Retry one identified gap and measure the change.",
  },
]

interface ModesSectionProps {
  onGetStarted: () => void
}

function ModePreview({ mode }: { mode: PracticeMode }) {
  if (mode === "interview") {
    return <div className="mt-6 rounded-xl border border-border/70 bg-secondary/35 p-3"><div className="flex items-center justify-between"><span className="h-2 w-12 rounded-full bg-primary/25" /><span className="h-2 w-6 rounded-full bg-border" /></div><p className="mt-4 text-xs font-medium text-foreground">Tell me about a decision that changed your approach.</p><div className="mt-4 flex items-center gap-2"><span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary text-primary-foreground"><MessageSquareText className="h-3.5 w-3.5" /></span><div className="flex h-4 items-center gap-1 text-primary">{[6, 12, 8, 15, 10, 7, 11].map((height, index) => <span key={index} className="w-1 rounded-full bg-current" style={{ height }} />)}</div></div></div>
  }

  if (mode === "technical") {
    return <div className="mt-6 rounded-xl border border-border/70 bg-[#111827] p-3 font-mono text-[10px] leading-5 text-slate-200"><span className="text-slate-400">Question</span><p className="mt-1 font-sans text-xs font-medium leading-5 text-white">Find the longest consecutive sequence.</p><p className="mt-3"><span className="text-violet-300">const</span> values = <span className="text-violet-300">new</span> Set(nums)</p><p><span className="text-violet-300">return</span> longest</p></div>
  }

  return <div className="mt-6 rounded-xl border border-border/70 bg-secondary/35 p-3"><div className="flex items-center justify-between text-xs"><span className="font-medium text-muted-foreground">Story impact</span><span className="font-semibold text-primary">62 → 78</span></div><div className="mt-4 h-2 overflow-hidden rounded-full bg-border"><span className="block h-full w-[78%] rounded-full bg-primary" /></div><div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground"><span className="h-2 w-2 rounded-full bg-primary" />Add the measurable result</div></div>
}

export function ModesSection({ onGetStarted }: ModesSectionProps) {
  return (
    <section id="modes" className="landing-chapter-gap landing-screen-section relative border-b border-border/40 px-6 py-12 md:py-14">
      <div className="mx-auto max-w-6xl">
        <div className="max-w-2xl">
          <h2 className="text-balance text-3xl font-semibold tracking-[-0.035em] text-foreground sm:text-4xl">Choose how you want to practice.</h2>
          <p className="mt-3 text-base leading-7 text-muted-foreground">Each mode starts with your role and ends with a clear next step.</p>
        </div>

        <div className="mt-8 grid gap-4 lg:grid-cols-3">
          {practiceTypes.map((practice) => (
            <article key={practice.title} className="landing-solid-card flex min-h-[300px] flex-col rounded-xl border border-border p-5 sm:p-6">
              <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary"><practice.icon className="h-5 w-5" /></span>
              <h3 className="mt-5 text-xl font-semibold tracking-tight text-foreground">{practice.title}</h3>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">{practice.description}</p>
              <ModePreview mode={practice.mode} />
            </article>
          ))}
        </div>

        <div className="mt-7 flex justify-center">
          <Button onClick={onGetStarted} className="h-11 rounded-lg px-6 text-sm font-semibold">Create a practice session</Button>
        </div>
      </div>
    </section>
  )
}
