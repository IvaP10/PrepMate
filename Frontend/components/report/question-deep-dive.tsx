"use client"

import { Clock3 } from "lucide-react"

interface QuestionDeepDiveProps {
  index: number
  sectionId?: string
  question: string
  response?: string
  transcript?: string
  score?: number | null
  status?: string
  timeUsedSeconds?: number | null
  whatCandidateAnswered?: string
  whatWasGood?: string[]
  whatReducedScore?: string[]
  evidence?: {
    correctly_mentioned?: string[]
    missing?: string[]
    incorrect_claims?: string[]
    contradictions?: string[]
    quotes?: string[]
  }
  answerStructure?: Record<string, string>
  projectResumeCoverage?: {
    covered?: string[]
    missing?: string[]
    incorrect?: string[]
  }
  topic?: string
}

function duration(value?: number | null) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return "—"
  const minutes = Math.floor(value / 60)
  const seconds = Math.round(value % 60)
  return `${minutes}m ${seconds}s`
}

function statusClass(status: string) {
  if (status === "Completed") return "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
  if (status === "Unable to Evaluate") return "border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-300"
  if (status === "Incomplete") return "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300"
  return "border-border bg-secondary text-muted-foreground"
}

export function questionScoreLabel(score: number | null | undefined, status: string) {
  if (typeof score === "number" && Number.isFinite(score)) return `${Math.round(score)}/10`
  if (status === "Not Answered") return "0/10"
  return "Unable to Evaluate"
}

export function QuestionDeepDive({
  index,
  sectionId,
  question,
  response = "",
  transcript,
  score = null,
  status = "Not Answered",
  timeUsedSeconds,
  whatCandidateAnswered,
  whatWasGood = [],
  whatReducedScore = [],
  evidence = {},
  answerStructure = {},
  projectResumeCoverage,
  topic,
}: QuestionDeepDiveProps) {
  const unanswered = status === "Not Answered"
  const answerText = transcript || response
  const scoreLabel = questionScoreLabel(score, status)
  const good = whatWasGood.length ? whatWasGood : evidence.correctly_mentioned || []
  const reduced = whatReducedScore.length ? whatReducedScore : [
    ...(evidence.missing || []).map((item) => `Missing: ${item}`),
    ...(evidence.incorrect_claims || []).map((item) => `Incorrect: ${item}`),
    ...(evidence.contradictions || []).map((item) => `Contradiction: ${item}`),
  ]

  return (
    <section id={sectionId || `question-${index}`} data-report-section className="scroll-mt-8 space-y-5 border-b border-border pb-8 last:border-b-0">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.16em] text-muted-foreground">Question {index}</p>
          <h2 className="mt-1 text-xl font-bold tracking-tight">{question || "Question text unavailable"}</h2>
          {topic && <p className="mt-1 text-xs text-muted-foreground">{topic}</p>}
        </div>
        <div className="flex items-center gap-2 sm:text-right">
          <span className={`rounded-full border px-2.5 py-1 text-xs font-medium ${statusClass(status)}`}>{status}</span>
          <span className="font-mono text-lg font-medium tabular-nums">{scoreLabel}</span>
        </div>
      </div>

      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Clock3 className="h-4 w-4" />
        <span className="font-bold">Time used:</span> <span className="font-mono text-foreground">{duration(timeUsedSeconds)}</span>
      </div>

      <section className="rounded-md border border-border bg-card p-4">
        <h3 className="text-xs font-bold uppercase tracking-[0.14em] text-muted-foreground">Full answer / transcript</h3>
        <p className="mt-3 whitespace-pre-wrap text-sm leading-6">{answerText || "No answer was captured."}</p>
      </section>

      <section className="rounded-md border border-border bg-card p-4">
        <h3 className="text-xs font-bold uppercase tracking-[0.14em] text-muted-foreground">What candidate answered</h3>
        <p className="mt-3 whitespace-pre-wrap text-sm leading-6">{whatCandidateAnswered || answerText || "No answer was captured."}</p>
      </section>

      {!unanswered && (
        <>
          {!!good.length && (
            <EvidenceList title="What was good" items={good} tone="good" />
          )}
          {!!reduced.length && (
            <EvidenceList title="What reduced score" items={reduced} tone="neutral" />
          )}

          {(evidence.correctly_mentioned?.length || evidence.missing?.length || evidence.incorrect_claims?.length || evidence.quotes?.length) ? (
            <section className="rounded-md border border-border bg-card p-4">
              <h3 className="text-xs font-bold uppercase tracking-[0.14em] text-muted-foreground">Evidence</h3>
              <div className="mt-3 grid gap-4 sm:grid-cols-2">
                <EvidenceColumn label="Correctly mentioned" items={evidence.correctly_mentioned || []} />
                <EvidenceColumn label="Missing" items={evidence.missing || []} />
                <EvidenceColumn label="Incorrect claims" items={evidence.incorrect_claims || []} />
                <EvidenceColumn label="Recorded quotes" items={evidence.quotes || []} />
              </div>
            </section>
          ) : null}

          {!!Object.keys(answerStructure).length && (
            <section className="rounded-md border border-border bg-card p-4">
              <h3 className="text-xs font-bold uppercase tracking-[0.14em] text-muted-foreground">Answer structure</h3>
              <div className="mt-3 grid gap-2 sm:grid-cols-4">
                {Object.entries(answerStructure).map(([key, value]) => (
                  <div key={key} className="rounded-md border border-border/70 bg-background px-3 py-2">
                    <p className="text-xs font-bold uppercase text-muted-foreground">{key}</p>
                    <p className="mt-1 text-sm">{value}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          {projectResumeCoverage && (
            <section className="rounded-md border border-border bg-card p-4">
              <h3 className="text-xs font-bold uppercase tracking-[0.14em] text-muted-foreground">Project / resume coverage</h3>
              <div className="mt-3 grid gap-4 sm:grid-cols-3">
                <EvidenceColumn label="Covered" items={projectResumeCoverage.covered || []} />
                <EvidenceColumn label="Missing" items={projectResumeCoverage.missing || []} />
                <EvidenceColumn label="Incorrect" items={projectResumeCoverage.incorrect || []} />
              </div>
            </section>
          )}
        </>
      )}
    </section>
  )
}

function EvidenceList({ title, items, tone }: { title: string; items: string[]; tone: "good" | "neutral" }) {
  return (
    <section className={`rounded-md border p-4 ${tone === "good" ? "border-emerald-500/20 bg-emerald-500/5" : "border-border bg-card"}`}>
      <h3 className="text-xs font-bold uppercase tracking-[0.14em] text-muted-foreground">{title}</h3>
      <ul className="mt-3 space-y-2 text-sm leading-6">
        {items.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}
      </ul>
    </section>
  )
}

function EvidenceColumn({ label, items }: { label: string; items: string[] }) {
  if (!items.length) return null
  return (
    <div>
      <p className="text-xs font-bold text-muted-foreground">{label}</p>
      <ul className="mt-2 space-y-1 text-sm leading-5">
        {items.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}
      </ul>
    </div>
  )
}
