"use client"

import { useState } from "react"
import { AudioLines, Braces, CheckCircle2, FileText, Mic, Send, Target } from "lucide-react"

interface HeroSectionProps {
  onGetStarted: () => void
  theme: "light" | "dark"
}

type InterviewView = "behavioral" | "technical"

function InterviewPreview() {
  const [view, setView] = useState<InterviewView>("behavioral")
  const behavioral = view === "behavioral"

  return (
    <div className="w-full overflow-hidden rounded-2xl border border-border bg-card shadow-[0_24px_70px_rgba(15,23,42,0.12)] dark:shadow-[0_24px_70px_rgba(0,0,0,0.32)]">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/70 px-4 py-3 sm:px-5">
        <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
            {behavioral ? <AudioLines className="h-4 w-4" /> : <Braces className="h-4 w-4" />}
          </span>
          {behavioral ? "Interview Round" : "Technical Round"}
        </div>
        <div className="flex rounded-lg bg-secondary p-1 text-[11px] font-medium sm:text-xs">
          <button
            type="button"
            onClick={() => setView("behavioral")}
            className={`rounded-md px-2.5 py-1.5 transition-colors sm:px-3 ${behavioral ? "bg-card text-foreground shadow-sm" : "text-muted-foreground"}`}
          >
            Interview Round
          </button>
          <button
            type="button"
            onClick={() => setView("technical")}
            className={`rounded-md px-2.5 py-1.5 transition-colors sm:px-3 ${!behavioral ? "bg-card text-foreground shadow-sm" : "text-muted-foreground"}`}
          >
            Technical Round
          </button>
        </div>
      </div>

      {behavioral ? (
        <div className="grid min-w-0 gap-0 lg:grid-cols-[1.25fr_0.75fr]">
          <div className="min-w-0 p-5 sm:p-6">
            <p className="mb-3 text-xs font-medium text-muted-foreground">Question</p>
            <div className="rounded-xl border border-border/70 bg-secondary/35 p-4">
              <div className="mb-3 flex flex-wrap gap-2">
                <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2.5 py-1 text-[10px] font-semibold text-primary"><FileText className="h-3 w-3" /> Resume</span>
                <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2.5 py-1 text-[10px] font-semibold text-primary"><Target className="h-3 w-3" /> Target role</span>
              </div>
              <p className="text-sm font-semibold leading-6 text-foreground">Tell me about a risky production change. How did you protect users?</p>
            </div>
            <div className="mt-4 flex gap-3 rounded-xl border border-border/70 p-4">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground"><Mic className="h-4 w-4" /></span>
              <div>
                <p className="text-xs font-medium text-muted-foreground">Your answer</p>
                <div className="mt-2 flex h-4 items-center gap-1 text-primary" aria-label="Answer waveform">
                  {[6, 12, 8, 15, 10, 13, 7, 11, 5].map((height, index) => <span key={index} className="w-1 rounded-full bg-current" style={{ height }} />)}
                </div>
              </div>
            </div>
          </div>
          <div className="min-w-0 border-t border-border/70 bg-secondary/25 p-5 lg:border-l lg:border-t-0 sm:p-6">
            <p className="text-xs font-medium text-muted-foreground">Why it fits</p>
            <div className="mt-4 space-y-3">
              {[
                "Uses your resume and target role",
                "Saves evidence for feedback",
              ].map((item) => (
                <div key={item} className="flex gap-2 text-sm leading-5 text-foreground/80">
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                  {item}
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <div className="grid min-w-0 gap-0 lg:grid-cols-[1.25fr_0.75fr]">
          <div className="min-w-0 p-5 sm:p-6">
            <p className="mb-3 text-xs font-medium text-muted-foreground">Question</p>
            <div className="rounded-xl border border-border/70 bg-secondary/35 p-4">
              <p className="text-sm font-semibold leading-6 text-foreground">Given an array of integers, return the length of the longest consecutive sequence.</p>
            </div>
            <pre className="mt-4 max-w-full overflow-x-auto rounded-xl border border-border/70 bg-[#111827] p-4 text-xs leading-5 text-slate-100"><code>{`const values = new Set(nums)
let longest = 0
for (const n of values) {
  if (values.has(n - 1)) continue
  let length = 1
  while (values.has(n + length)) length++
  longest = Math.max(longest, length)
}
return longest`}</code></pre>
          </div>
          <div className="min-w-0 border-t border-border/70 bg-secondary/25 p-5 lg:border-l lg:border-t-0 sm:p-6">
            <p className="text-xs font-medium text-muted-foreground">Evaluate</p>
            <div className="mt-4 space-y-3">
              <div className="rounded-lg border border-border/70 bg-card p-3"><p className="text-sm font-semibold text-foreground">Sequence starts</p><div className="mt-2 h-1.5 overflow-hidden rounded-full bg-secondary"><span className="block h-full w-4/5 rounded-full bg-primary" /></div></div>
              <div className="rounded-lg border border-border/70 bg-card p-3"><p className="text-sm font-semibold text-foreground">Linear-time lookup</p><div className="mt-2 h-1.5 overflow-hidden rounded-full bg-secondary"><span className="block h-full w-4/5 rounded-full bg-primary/70" /></div></div>
            </div>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border/70 px-5 py-3 text-xs text-muted-foreground">
        <span>Built from your resume + job description</span>
        <span className="inline-flex items-center gap-1 font-semibold text-primary"><Send className="h-3.5 w-3.5" /> Evidence-led feedback</span>
      </div>
    </div>
  )
}

export function HeroSection({ onGetStarted }: HeroSectionProps) {
  return (
    <section className="relative flex min-h-[100svh] border-b border-border/40 px-6 pb-12 pt-32 sm:pt-36 md:pb-14">
      <div className="mx-auto grid w-full max-w-7xl items-center gap-10 lg:grid-cols-[0.78fr_1.22fr] lg:gap-14">
        <div className="max-w-xl">
          <h1 className="text-balance text-4xl font-semibold leading-[1.04] tracking-[-0.045em] text-foreground sm:text-5xl lg:text-6xl">AI mock interviews that match your role.</h1>
          <p className="mt-6 max-w-lg text-base leading-7 text-muted-foreground">Use your resume and job description to practice, get evidence, and improve the next answer.</p>
          <div className="mt-6 flex flex-wrap gap-x-4 gap-y-2 text-sm font-medium text-foreground/75"><span>Interview Round</span><span className="text-primary">•</span><span>Technical Round</span><span className="text-primary">•</span><span>Focused Drills</span></div>
          <button onClick={onGetStarted} className="mt-7 h-12 rounded-lg bg-primary px-6 text-sm font-semibold text-primary-foreground shadow-lg shadow-primary/20 transition hover:brightness-110">Start practicing</button>
        </div>
        <InterviewPreview />
      </div>
    </section>
  )
}
