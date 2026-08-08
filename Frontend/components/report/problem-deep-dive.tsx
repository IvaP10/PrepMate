"use client"

import type { ReactNode } from "react"
import { ChevronDown, Code2, Clock3, FlaskConical, GitCommitHorizontal, Play, Terminal } from "lucide-react"

interface ProblemDeepDiveProps {
  index: number
  sectionId?: string
  title: string
  language?: string
  status?: string
  score?: number | null
  scorePoints?: number | null
  maxPoints?: number | null
  timeUsedSeconds?: number | null
  timeAllowedSeconds?: number | null
  runs?: number
  submissionCount?: number
  visiblePassed?: number
  visibleTotal?: number
  hiddenPassed?: number
  hiddenTotal?: number
  finalSubmission?: boolean
  prompt?: string
  sourceCode?: string
  sourceLabel?: string
  whatHappened?: string
  mainIssue?: string | null
  testEvidence?: Record<string, any>
  complexity?: Record<string, string>
  activity?: Array<{ at?: string | null; event?: string; detail?: string }>
}

function duration(value?: number | null) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return "—"
  const minutes = Math.floor(value / 60)
  const seconds = Math.round(value % 60)
  return `${minutes}m ${seconds}s`
}

function statusClass(status: string) {
  if (status === "Submitted" || status === "Completed") return "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
  if (status === "Unable to Evaluate") return "border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-300"
  if (status === "Incomplete") return "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300"
  return "border-border bg-secondary text-muted-foreground"
}

export function ProblemDeepDive({
  index,
  sectionId,
  title,
  language,
  status = "Not Attempted",
  score = null,
  scorePoints = null,
  maxPoints = 50,
  timeUsedSeconds,
  timeAllowedSeconds,
  runs = 0,
  submissionCount = 0,
  visiblePassed = 0,
  visibleTotal = 0,
  hiddenPassed = 0,
  hiddenTotal = 0,
  finalSubmission = false,
  prompt,
  sourceCode,
  sourceLabel = "Last saved code",
  whatHappened,
  mainIssue,
  testEvidence = {},
  complexity = {},
  activity = [],
}: ProblemDeepDiveProps) {
  const scoreLabel = status === "Unable to Evaluate"
    ? "Unable to Evaluate"
    : `${Math.round(scorePoints ?? 0)}/${Math.round(maxPoints ?? 50)}`

  return (
    <section id={sectionId || `problem-${index}`} data-report-section className="scroll-mt-8 space-y-5 rounded-lg border border-border bg-card p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="text-xs font-bold uppercase tracking-[0.16em] text-muted-foreground">Problem {index}</p>
          <h2 className="mt-1 text-xl font-bold tracking-tight">{title}</h2>
        </div>
        <div className="flex flex-wrap items-center gap-2 sm:ml-auto sm:justify-end sm:text-right">
          <span className={`rounded-full border px-2.5 py-1 text-xs font-medium ${statusClass(status)}`}>{status}</span>
          <span className="font-mono text-lg font-medium tabular-nums">{scoreLabel}</span>
          {language && <span className="font-mono text-xs text-muted-foreground">{language}</span>}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-4">
        <Metric icon={<Clock3 className="h-4 w-4" />} label="Time" value={`${duration(timeUsedSeconds)}${timeAllowedSeconds ? ` / ${duration(timeAllowedSeconds)}` : ""}`} />
        <Metric icon={<Play className="h-4 w-4" />} label="Runs" value={String(runs)} />
        <Metric icon={<FlaskConical className="h-4 w-4" />} label="Visible tests" value={visibleTotal ? `${visiblePassed}/${visibleTotal}` : "—"} />
        <Metric icon={<Terminal className="h-4 w-4" />} label="Hidden tests" value={hiddenTotal ? `${hiddenPassed}/${hiddenTotal}` : "—"} />
      </div>

      {prompt && (
        <details className="group rounded-md border border-border bg-card">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm font-bold">
            <span className="font-bold">View full problem statement</span>
            <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" />
          </summary>
          <div className="border-t border-border px-4 py-4">
            <p className="whitespace-pre-wrap text-sm leading-6 text-muted-foreground">{prompt}</p>
          </div>
        </details>
      )}

      <section className="rounded-md border border-border bg-card p-4">
        <h3 className="text-xs font-bold uppercase tracking-[0.14em] text-muted-foreground">What happened</h3>
        <p className="mt-2 text-sm leading-6">{whatHappened || "No additional event detail was recorded."}</p>
        {mainIssue && (
          <div className="mt-4 border-t border-border pt-4">
            <h3 className="text-xs font-bold uppercase tracking-[0.14em] text-muted-foreground">Main issue</h3>
            <p className="mt-2 text-sm leading-6">{mainIssue}</p>
          </div>
        )}
      </section>

      {(testEvidence.visible || testEvidence.hidden || testEvidence.final_run || testEvidence.compile || testEvidence.runtime || testEvidence.submission) && (
        <section className="rounded-md border border-border bg-card p-4">
          <h3 className="text-xs font-bold uppercase tracking-[0.14em] text-muted-foreground">Test evidence</h3>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <EvidenceCell label="Visible" value={testEvidence.visible ? `${testEvidence.visible.passed}/${testEvidence.visible.total}` : "Not recorded"} />
            <EvidenceCell label="Hidden" value={testEvidence.hidden ? `${testEvidence.hidden.passed}/${testEvidence.hidden.total}` : "Not recorded"} />
            <EvidenceCell label="Final run" value={testEvidence.final_run ? `${testEvidence.final_run.passed}/${testEvidence.final_run.total}` : "Not recorded"} />
            <EvidenceCell label="Submission" value={finalSubmission || submissionCount > 0 ? "Recorded" : "Not recorded"} />
          </div>
          {(testEvidence.compile || testEvidence.runtime) && (
            <p className="mt-3 text-xs text-muted-foreground">
              {testEvidence.compile ? `Compile failures: ${testEvidence.compile.failed}. ` : ""}
              {testEvidence.runtime ? `Runtime failures: ${testEvidence.runtime.failed}.` : ""}
            </p>
          )}
        </section>
      )}

      {!!Object.keys(complexity).length && (
        <section className="rounded-md border border-border bg-card p-4">
          <h3 className="text-xs font-bold uppercase tracking-[0.14em] text-muted-foreground">Observed complexity</h3>
          <div className="mt-3 flex flex-wrap gap-2">
            {Object.entries(complexity).map(([key, value]) => (
              <span key={key} className="rounded-md border border-border px-3 py-2 font-mono text-xs">
                {key}: {value}
              </span>
            ))}
          </div>
        </section>
      )}

      {!!activity.length && (
        <section className="rounded-md border border-border bg-card p-4">
          <h3 className="text-xs font-bold uppercase tracking-[0.14em] text-muted-foreground">Activity</h3>
          <div className="mt-3 space-y-3">
            {activity.map((event, eventIndex) => (
              <div key={`${event.at || "event"}-${eventIndex}`} className="flex gap-3 text-sm">
                <GitCommitHorizontal className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                <div className="min-w-0">
                  <p className="font-bold">{event.event || "Activity"}</p>
                  {(event.detail || event.at) && <p className="text-xs text-muted-foreground">{event.detail}{event.detail && event.at ? " · " : ""}{event.at || ""}</p>}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {sourceCode && (
        <details className="group overflow-hidden rounded-md border border-border bg-card">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm font-bold">
            <span className="flex items-center gap-2 font-bold"><Code2 className="h-4 w-4 text-muted-foreground" />{sourceLabel}</span>
            <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" />
          </summary>
          <pre className="max-h-[34rem] overflow-auto border-t border-border bg-secondary/20 p-4 text-xs leading-5"><code>{sourceCode}</code></pre>
        </details>
      )}
    </section>
  )
}

function Metric({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-card px-3 py-3">
      <div className="flex items-center gap-2 text-xs font-bold text-muted-foreground">{icon}{label}</div>
      <p className="mt-1 font-mono text-sm font-medium tabular-nums">{value}</p>
    </div>
  )
}

function EvidenceCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border/70 bg-background px-3 py-2">
      <p className="text-xs font-bold text-muted-foreground">{label}</p>
      <p className="mt-1 font-mono text-sm font-medium">{value}</p>
    </div>
  )
}
