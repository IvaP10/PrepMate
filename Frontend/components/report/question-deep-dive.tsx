"use client"

import { useState } from "react"
import { ChevronDown, ChevronUp } from "lucide-react"

interface QuestionDeepDiveProps {
  index: number
  sectionId?: string
  responseId?: string
  question: string
  response: string
  score: number | null
  feedback?: string
  coachingHint?: string
  strongerAnswerOutline?: string
  mistake?: { type?: string; diagnosis?: string; quote?: string } | null
  whyBad?: string
  betterStructure?: string[]
  improvedAnswer?: string
  sessionAverageScore?: number | null
  flags?: string[]
  evidenceQuotes?: string[]
}

export function QuestionDeepDive({
  index,
  sectionId,
  question,
  response,
  score,
  feedback,
  coachingHint,
  strongerAnswerOutline,
  mistake,
  whyBad,
  betterStructure = [],
  improvedAnswer,
  sessionAverageScore,
  flags = [],
  evidenceQuotes = [],
}: QuestionDeepDiveProps) {
  const [isExpanded, setIsExpanded] = useState(false)
  const isLongResponse = response.length > 300
  const displayedResponse = isExpanded ? response : response.slice(0, 300) + (isLongResponse ? "..." : "")

  const isGoodScore = score !== null && score >= 80
  const workedText = evidenceQuotes.length
    ? `Captured evidence: ${evidenceQuotes[0]}`
    : isGoodScore
      ? feedback || "This was one of the stronger captured answers in the session."
      : "No clear strength was captured for this answer."

  const getScoreColor = (s: number | null) => {
    if (s === null) return "text-muted-foreground bg-secondary/30 border-border"
    if (s >= 80) return "text-emerald-500 bg-emerald-500/10 border-emerald-500/20"
    if (s >= 60) return "text-amber-500 bg-amber-500/10 border-amber-500/20"
    return "text-rose-500 bg-rose-500/10 border-rose-500/20"
  }

  return (
    <section id={sectionId || `question-${index}`} data-report-section className="scroll-margin-top: 5rem py-6 border-b border-border last:border-b-0 space-y-6">
      {/* Header and Score Info */}
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div className="space-y-1.5 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-primary uppercase tracking-wider">
              Question {index}
            </span>
            {flags.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {flags.map((flg) => (
                  <span key={flg} className="inline-flex items-center rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-600 dark:text-amber-400 border border-amber-500/20">
                    {flg.replace(/_/g, " ")}
                  </span>
                ))}
              </div>
            )}
          </div>
          <h3 className="text-lg font-semibold text-foreground leading-snug">
            {question}
          </h3>
        </div>

        {/* Score Ring / Badge */}
        <div className="flex items-center gap-3 shrink-0">
          <div className={`flex flex-col items-center justify-center border rounded-lg p-2.5 min-w-[70px] ${getScoreColor(score)}`}>
            <span className="text-xl font-bold font-mono leading-none">{Math.round(score ?? 0)}%</span>
            <span className="text-[10px] text-muted-foreground uppercase font-semibold mt-1">Score</span>
          </div>
          {sessionAverageScore !== undefined && sessionAverageScore !== null && (
            <div className="text-[11px] text-muted-foreground flex flex-col">
              <span>Avg score:</span>
              <span className="font-semibold text-foreground">{Math.round(sessionAverageScore)}%</span>
            </div>
          )}
        </div>
      </div>

      {/* Response Box */}
      <div className="bg-secondary/10 border border-border/50 rounded-lg p-4 space-y-2">
        <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Your Response</h4>
        <div className="text-sm leading-relaxed text-foreground/80 whitespace-pre-wrap">
          {displayedResponse || <span className="italic">No response captured.</span>}
        </div>
        {isLongResponse && (
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="text-xs font-semibold text-primary flex items-center gap-1 hover:underline mt-1 pt-1 border-t border-border/30 w-full justify-center"
          >
            {isExpanded ? (
              <>
                Show Less <ChevronUp className="h-3 w-3" />
              </>
            ) : (
              <>
                View Full Response <ChevronDown className="h-3 w-3" />
              </>
            )}
          </button>
        )}
      </div>

      {/* Feedback & Suggestions */}
      <div className="grid gap-5 md:grid-cols-2">
        {/* Good parts */}
        <div className="space-y-2 border border-emerald-500/20 bg-emerald-500/5 p-4 rounded-lg">
          <h4 className="text-xs font-semibold text-emerald-500 uppercase tracking-wider">Captured strength</h4>
          <p className="text-sm leading-relaxed text-muted-foreground">
            {workedText}
          </p>
        </div>

        {/* Needs improvement */}
        <div className="space-y-2 border border-border/60 bg-card p-4 rounded-lg">
          <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Your mistake</h4>
          <p className="text-sm leading-relaxed text-muted-foreground">
            {mistake?.diagnosis || feedback || coachingHint || "No suggestions recorded."}
          </p>
          {whyBad && <p className="text-xs leading-relaxed text-muted-foreground/80">Why it hurts: {whyBad}</p>}
        </div>
      </div>

      {betterStructure.length > 0 && (
        <div className="rounded-lg border border-border/60 bg-secondary/10 p-4">
          <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Better answer structure</h4>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {betterStructure.map((step, idx) => (
              <div key={`${step}-${idx}`} className="rounded-md border border-border/40 bg-background/60 p-3">
                <p className="text-[11px] font-semibold uppercase text-muted-foreground">Step {idx + 1}</p>
                <p className="mt-1 text-sm leading-5 text-foreground/80">{step}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Stronger Answer Rewrite (Rewritten Answer Block) */}
      {(improvedAnswer || strongerAnswerOutline) && (
        <div className="report-rewrite-block p-4 space-y-2">
          <h4 className="text-xs font-semibold text-primary uppercase tracking-wider">Your Answer, Rewritten</h4>
          <p className="text-sm leading-relaxed text-foreground/80 whitespace-pre-wrap">
            {improvedAnswer || strongerAnswerOutline}
          </p>
        </div>
      )}
    </section>
  )
}
