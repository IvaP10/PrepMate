"use client"

import React, { useState } from "react"
import { Code2, CheckCircle2, XCircle, AlertCircle, ChevronDown, ChevronUp, Cpu, Flame } from "lucide-react"

interface Annotation {
  line?: number
  start_line?: number
  title?: string
  issue?: string
  detail?: string
  message?: string
  fix?: string
}

interface ProblemDeepDiveProps {
  index: number
  sectionId?: string
  problemId: string
  title: string
  language?: string
  score?: number | null
  visiblePassed?: number
  visibleTotal?: number
  hiddenPassed?: number
  hiddenTotal?: number
  approach?: string
  idealSolution?: string | { approach?: string; complexity?: string }
  complexityDiff?: Record<string, any>
  annotations?: Annotation[]
  rawCode?: string
  evidenceState?: string
  prompt?: string
}

export function ProblemDeepDive({
  index,
  sectionId,
  problemId,
  title,
  language,
  score = null,
  visiblePassed,
  visibleTotal,
  hiddenPassed,
  hiddenTotal,
  approach,
  idealSolution,
  complexityDiff,
  annotations = [],
  rawCode,
  evidenceState,
  prompt,
}: ProblemDeepDiveProps) {
  const [isCodeOpen, setIsCodeOpen] = useState(false)

  const hasVisibleTests = typeof visibleTotal === "number" && visibleTotal > 0
  const hasHiddenTests = typeof hiddenTotal === "number" && hiddenTotal > 0
  const hasAnyTests = hasVisibleTests || hasHiddenTests
  const passedAll = hasAnyTests && visiblePassed === visibleTotal && (!hasHiddenTests || hiddenPassed === hiddenTotal)
  const isEvidenceOnly = Boolean(evidenceState && evidenceState !== "final_submission")
  const evidenceUnknown = !hasAnyTests && !isEvidenceOnly
  const failedVisibleRun = isEvidenceOnly && hasVisibleTests
    && typeof visiblePassed === "number"
    && typeof visibleTotal === "number"
    && visiblePassed < visibleTotal

  return (
    <section id={sectionId || `problem-${index}`} data-report-section className="scroll-margin-top: 5rem py-4 border-b border-border last:border-b-0">
      <div className="flex flex-col gap-6">
        {/* Header */}
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h3 className="text-xl font-semibold text-foreground flex items-center gap-2">
              <span className="text-muted-foreground font-mono text-sm">P{index}.</span>
              {title}
            </h3>
            <p className="mt-1 text-xs text-muted-foreground font-mono">
              Language: {language || "Unknown"}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ${
              passedAll 
                ? "bg-emerald-500/10 text-emerald-500 dark:bg-emerald-500/20" 
                : isEvidenceOnly
                  ? "bg-amber-500/10 text-amber-600 dark:bg-amber-500/20"
                  : evidenceUnknown
                    ? "bg-secondary text-muted-foreground"
                  : "bg-rose-500/10 text-rose-500 dark:bg-rose-500/20"
            }`}>
              {passedAll ? <CheckCircle2 className="h-3.5 w-3.5" /> : isEvidenceOnly || evidenceUnknown ? <AlertCircle className="h-3.5 w-3.5" /> : <XCircle className="h-3.5 w-3.5" />}
              {passedAll ? "Passed" : isEvidenceOnly ? "Evidence only" : evidenceUnknown ? "Unknown" : "Failed"}
            </span>
            <span className="text-lg font-bold font-mono text-foreground">
              {typeof score === "number" ? `${Math.round(score)}%` : "Ungraded"}
            </span>
          </div>
        </div>

        {prompt && (
          <div className="rounded-lg border border-border/50 bg-secondary/10 p-4">
            <h4 className="text-sm font-semibold text-foreground">Problem Prompt</h4>
            <p className="mt-2 line-clamp-5 whitespace-pre-wrap text-sm leading-6 text-muted-foreground">{prompt}</p>
          </div>
        )}

        {/* Grid for Test Matrix & Approach */}
        <div className="grid gap-6 md:grid-cols-2">
          {/* Test Case Breakdown */}
          <div className="space-y-3 rounded-lg border border-border/50 bg-secondary/15 p-4">
            <h4 className="text-sm font-semibold text-foreground flex items-center gap-1.5">
              <CheckCircle2 className="h-4 w-4 text-muted-foreground" />
              Test Results
            </h4>
            <div className="grid grid-cols-2 gap-4 text-sm mt-2">
              <div className="bg-card/40 border border-border/40 p-2.5 rounded">
                <span className="text-xs text-muted-foreground block">Visible Tests</span>
                <span className="text-base font-semibold font-mono mt-0.5 block text-foreground">
                  {hasVisibleTests ? `${typeof visiblePassed === "number" ? visiblePassed : "Unknown"} / ${visibleTotal}` : "Not submitted"}
                </span>
              </div>
              {hasHiddenTests && (
                <div className="bg-card/40 border border-border/40 p-2.5 rounded">
                  <span className="text-xs text-muted-foreground block">Hidden Tests</span>
                  <span className="text-base font-semibold font-mono mt-0.5 block text-foreground">
                    {hiddenPassed} / {hiddenTotal}
                  </span>
                </div>
              )}
            </div>
            {!passedAll && !evidenceUnknown && (
              <p className="text-xs text-rose-500 mt-2 italic flex items-center gap-1">
                <Flame className="h-3 w-3 shrink-0" />
                {failedVisibleRun
                  ? "Latest run failed visible tests; no final submit was recorded."
                  : isEvidenceOnly
                    ? "No final submit was recorded, so this uses the captured draft or run evidence."
                    : "Edge cases or runtime errors prevented complete execution."}
              </p>
            )}
          </div>

          {/* Approach summary */}
          <div className="space-y-3 rounded-lg border border-border/50 bg-secondary/15 p-4">
            <h4 className="text-sm font-semibold text-foreground flex items-center gap-1.5">
              <Cpu className="h-4 w-4 text-muted-foreground" />
              Complexity & Approach
            </h4>
            <div className="text-sm text-muted-foreground leading-relaxed">
              {approach ? (
                <p className="line-clamp-3 hover:line-clamp-none transition-all">{approach}</p>
              ) : (
                <p className="italic">No captured approach label for this problem.</p>
              )}
            </div>
            {complexityDiff && (
              <div className="mt-2 text-xs font-mono bg-card/30 p-2 rounded border border-border/30 text-foreground">
                <span className="text-muted-foreground font-sans block mb-0.5">Complexity gap detected:</span>
                {Object.entries(complexityDiff).map(([key, val]) => (
                  <div key={key} className="flex justify-between">
                    <span>{key}:</span>
                    <span className="font-semibold text-amber-500">{String(val)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Mistakes & Fixes / Code Annotations */}
        {annotations.length > 0 && (
          <div className="space-y-3">
            <h4 className="text-sm font-semibold text-foreground flex items-center gap-1.5">
              <AlertCircle className="h-4 w-4 text-amber-500" />
              Line-Level Feedback
            </h4>
            <div className="space-y-3">
              {annotations.map((note, noteIdx) => {
                const lineNum = note.line ?? note.start_line
                const label = note.title || note.issue || "Issue"
                const detailText = note.detail || note.message || note.fix || ""

                return (
                  <div key={noteIdx} className="report-pattern-callout p-4">
                    <div className="flex items-start gap-2.5 justify-between">
                      <div>
                        <span className="text-xs font-mono px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-600 dark:text-amber-400">
                          {lineNum ? `Line ${lineNum}` : "General"}
                        </span>
                        <h5 className="mt-1.5 text-sm font-semibold text-foreground">{label}</h5>
                      </div>
                    </div>
                    {detailText && (
                      <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{detailText}</p>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {!hasAnyTests && (
          <div className="rounded border border-amber-500/20 bg-amber-500/5 px-3 py-2.5 text-xs text-amber-600 dark:text-amber-400">
            No final submission evidence was captured for this problem, so the report is showing saved code only.
          </div>
        )}

        {/* Collapsible raw code */}
        {rawCode && (
          <div className="border border-border/70 rounded-lg overflow-hidden">
            <button
              onClick={() => setIsCodeOpen(!isCodeOpen)}
              className="report-collapsible-trigger w-full flex items-center justify-between p-3.5 bg-secondary/10 hover:bg-secondary/20 transition-colors text-sm font-medium"
            >
              <span className="flex items-center gap-2">
                <Code2 className="h-4 w-4 text-muted-foreground" />
                {isEvidenceOnly ? "View Captured Code" : "View Submitted Code"}
              </span>
              {isCodeOpen ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            </button>
            {isCodeOpen && (
              <pre className="p-4 bg-secondary/5 border-t border-border/70 overflow-x-auto text-xs font-mono leading-relaxed text-foreground/80 max-h-96">
                <code>{rawCode}</code>
              </pre>
            )}
          </div>
        )}
      </div>
    </section>
  )
}
