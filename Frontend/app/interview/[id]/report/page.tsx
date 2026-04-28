"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import { AlertTriangle, ArrowLeft, CalendarDays, ChevronDown, RefreshCw, Target } from "lucide-react"

import { Button } from "@/components/ui/button"
import { fetchInterviewReport } from "@/lib/api"

interface DetailedResponse {
  question: string
  question_type: string
  is_followup: boolean
  topic?: string | null
  response: string
  score: number
  feedback: string
  time_taken: number | null
  coaching_hint: string | null
  answer_quality_flags?: string[]
  evidence_quotes?: string[]
  retry_state?: Record<string, unknown> | null
}

interface ReportV2 {
  version?: string
  summary: string
  readiness_label: string
  overall_score: number
  skill_scores: Record<string, number>
  pillar_scores?: Record<string, number>
  topic_breakdown: { topic: string; score: number; turns: number }[]
  behavioral_metrics: {
    average_response_time_seconds?: number
    answer_quality_flags?: Record<string, number>
    question_count?: number
  }
  student_summary?: {
    headline?: string
    blocker?: string
    next_step?: string
    interviewer_signal?: string
    proof_point?: string
  }
  strengths: string[]
  improvements: { title: string; detail: string }[]
  practice_plan: { day: string; task: string }[]
  per_turn_feedback: Array<DetailedResponse & { stronger_answer_outline?: string }>
  next_recommended_session_date?: string
}

interface InterviewReport {
  interview_id: string
  mode: string
  interview_type: string
  job_title: string
  strictness_level: string
  overall_score: number
  report: string | null
  report_v2?: ReportV2 | string | null
  created_at: string | null
  completed_at: string | null
  detailed_responses: DetailedResponse[]
}

const skillLabels: Record<string, string> = {
  technical_accuracy: "Technical depth",
  communication: "Communication",
  problem_solving: "Problem solving",
  confidence: "Confidence",
  relevance: "Relevance",
  interview_readiness: "Interview readiness",
  answer_clarity: "Answer clarity",
  technical_depth: "Technical depth",
  proof_of_work: "Proof of work",
}

function formatDate(value: string | null) {
  if (!value) return "-"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "-"
  return date.toLocaleString()
}

function scoreTone(score: number) {
  if (score >= 80) return "text-emerald-500"
  if (score >= 60) return "text-amber-500"
  return "text-rose-500"
}

function scoreBg(score: number) {
  if (score >= 80) return "bg-emerald-500"
  if (score >= 60) return "bg-amber-500"
  return "bg-rose-500"
}

function parseReportV2(report: InterviewReport | null): ReportV2 | null {
  if (!report?.report_v2) return null
  if (typeof report.report_v2 === "string") {
    try {
      return JSON.parse(report.report_v2) as ReportV2
    } catch {
      return null
    }
  }
  return report.report_v2
}

function strongerOutline(item: DetailedResponse | (DetailedResponse & { stronger_answer_outline?: string })) {
  return "stronger_answer_outline" in item && typeof item.stronger_answer_outline === "string"
    ? item.stronger_answer_outline
    : ""
}

function BarRow({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between gap-3">
        <span className="truncate text-sm font-medium text-foreground">{label}</span>
        <span className={`text-sm font-semibold ${scoreTone(value)}`}>{Math.round(value)}%</span>
      </div>
      <div className="h-2 overflow-hidden rounded bg-border/60">
        <div className={`h-full rounded ${scoreBg(value)}`} style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
      </div>
    </div>
  )
}

export default function InterviewReportPage() {
  const params = useParams()
  const router = useRouter()
  const interviewId = params.id as string

  const [report, setReport] = useState<InterviewReport | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showDetails, setShowDetails] = useState(false)

  const loadReport = useCallback(async () => {
    if (!interviewId) return
    try {
      setIsLoading(true)
      setError(null)
      setReport(await fetchInterviewReport(interviewId))
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load interview report")
    } finally {
      setIsLoading(false)
    }
  }, [interviewId])

  useEffect(() => {
    loadReport()
  }, [loadReport])

  const reportV2 = useMemo(() => parseReportV2(report), [report])

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background p-6 text-foreground">
        <div className="text-center">
          <div className="mx-auto mb-4 h-12 w-12 rounded-full border-2 border-primary/30 border-t-primary animate-spin" />
          <h1 className="text-xl font-semibold">Loading report</h1>
          <p className="mt-1 text-sm text-muted-foreground">Preparing your feedback.</p>
        </div>
      </div>
    )
  }

  if (error || !report) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background p-6 text-foreground">
        <div className="max-w-md rounded-lg border border-border bg-card p-8 text-center shadow-sm">
          <h1 className="text-xl font-semibold">Report unavailable</h1>
          <p className="mt-2 text-sm text-muted-foreground">{error || "We could not load this interview report."}</p>
          <div className="mt-6 flex justify-center gap-3">
            <Button variant="outline" onClick={() => router.push("/?tab=interview")}>
              <ArrowLeft className="mr-2 h-4 w-4" />
              Dashboard
            </Button>
            <Button onClick={loadReport}>
              <RefreshCw className="mr-2 h-4 w-4" />
              Retry
            </Button>
          </div>
        </div>
      </div>
    )
  }

  const overallScore = reportV2?.overall_score ?? report.overall_score
  const summary = reportV2?.summary || report.report || "This completed interview has per-question feedback, but the structured report has not been generated yet."
  const detailTurns = reportV2?.per_turn_feedback?.length ? reportV2.per_turn_feedback : report.detailed_responses
  const skillEntries = Object.entries(reportV2?.skill_scores || {})
  const pillarEntries = Object.entries(reportV2?.pillar_scores || {})

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="mx-auto flex max-w-6xl flex-col gap-6 p-6 md:p-10">
        <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div>
            <Button variant="ghost" className="mb-3 -ml-3" onClick={() => router.push("/?tab=interview")}>
              <ArrowLeft className="mr-2 h-4 w-4" />
              Back to dashboard
            </Button>
            <p className="text-sm text-muted-foreground">{report.job_title || "General Interview"} / {report.mode} / {report.interview_type}</p>
            <h1 className="mt-1 text-3xl font-bold tracking-tight">Interview Report</h1>
          </div>
          <div className="rounded-lg border border-border bg-card px-6 py-4 shadow-sm">
            <p className="text-xs uppercase tracking-wider text-muted-foreground">Readiness</p>
            <p className={`mt-1 text-3xl font-semibold ${scoreTone(overallScore)}`}>{Math.round(overallScore)}%</p>
            <p className="mt-1 text-sm text-muted-foreground">{reportV2?.readiness_label || "Completed"}</p>
          </div>
        </div>

        <section className="rounded-lg border border-border bg-card p-6 shadow-sm">
          <div className="flex items-start gap-3">
            <Target className="mt-1 h-5 w-5 text-primary" />
            <div>
              <h2 className="text-lg font-semibold">What this means</h2>
              <p className="mt-2 max-w-4xl text-sm leading-6 text-muted-foreground">{summary}</p>
              {reportV2?.student_summary?.interviewer_signal && (
                <p className="mt-3 max-w-4xl text-sm leading-6 text-foreground/80">{reportV2.student_summary.interviewer_signal}</p>
              )}
            </div>
          </div>
        </section>

        <div className="grid gap-6 lg:grid-cols-[1fr_0.9fr]">
          <section className="rounded-lg border border-border bg-card p-6 shadow-sm">
            <h2 className="text-lg font-semibold">Coaching Breakdown</h2>
            <div className="mt-5 space-y-4">
              {pillarEntries.map(([key, value]) => (
                <BarRow key={key} label={skillLabels[key] || key.replaceAll("_", " ")} value={Number(value) || 0} />
              ))}
              {skillEntries.map(([key, value]) => (
                <BarRow key={key} label={skillLabels[key] || key.replaceAll("_", " ")} value={Number(value) || 0} />
              ))}
              {pillarEntries.length === 0 && skillEntries.length === 0 && (
                <p className="text-sm text-muted-foreground">Structured coaching scores are unavailable for this report, but answer-level feedback is still available below.</p>
              )}
            </div>
          </section>

          <section className="rounded-lg border border-border bg-card p-6 shadow-sm">
            <h2 className="text-lg font-semibold">Highest-Impact Fixes</h2>
            <div className="mt-4 space-y-3">
              {(reportV2?.improvements || []).slice(0, 3).map((item, index) => (
                <div key={`${item.title}-${index}`} className="rounded-lg border border-border/60 bg-secondary/20 p-4">
                  <p className="text-sm font-semibold">{item.title}</p>
                  <p className="mt-1 text-sm leading-6 text-muted-foreground">{item.detail}</p>
                </div>
              ))}
              {(!reportV2?.improvements || reportV2.improvements.length === 0) && (
                <p className="text-sm text-muted-foreground">No priority fixes were generated.</p>
              )}
            </div>
          </section>
        </div>

        <div className="grid gap-6 lg:grid-cols-3">
          <section className="rounded-lg border border-border bg-card p-6 shadow-sm lg:col-span-2">
            <h2 className="text-lg font-semibold">7-Day Practice Plan</h2>
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              {(reportV2?.practice_plan || []).map((item) => (
                <div key={item.day} className="rounded-lg border border-border/60 bg-secondary/20 p-4">
                  <p className="text-xs font-semibold uppercase tracking-wider text-primary">{item.day}</p>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">{item.task}</p>
                </div>
              ))}
            </div>
          </section>

          <section className="rounded-lg border border-border bg-card p-6 shadow-sm">
            <h2 className="text-lg font-semibold">Session Metrics</h2>
            <div className="mt-4 space-y-4 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">Questions</span>
                <span className="font-medium">{reportV2?.behavioral_metrics?.question_count ?? report.detailed_responses.length}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">Avg response time</span>
                <span className="font-medium">{Math.round(reportV2?.behavioral_metrics?.average_response_time_seconds || 0)}s</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">Completed</span>
                <span className="font-medium">{formatDate(report.completed_at)}</span>
              </div>
            </div>
          </section>
        </div>

        {reportV2?.topic_breakdown && reportV2.topic_breakdown.length > 0 && (
          <section className="rounded-lg border border-border bg-card p-6 shadow-sm">
            <h2 className="text-lg font-semibold">Topic Performance</h2>
            <div className="mt-5 grid gap-4 md:grid-cols-2">
              {reportV2.topic_breakdown.map((topic) => (
                <BarRow key={topic.topic} label={`${topic.topic} (${topic.turns})`} value={topic.score} />
              ))}
            </div>
          </section>
        )}

        <section className="rounded-lg border border-border bg-card shadow-sm">
          <button
            className="flex w-full items-center justify-between gap-3 border-b border-border px-6 py-4 text-left"
            onClick={() => setShowDetails((prev) => !prev)}
          >
            <div>
              <h2 className="text-lg font-semibold">Answer Breakdown</h2>
              <p className="mt-1 text-sm text-muted-foreground">Detailed transcript evidence and stronger answer outlines.</p>
            </div>
            <ChevronDown className={`h-5 w-5 text-muted-foreground transition-transform ${showDetails ? "rotate-180" : ""}`} />
          </button>

          {showDetails && (
            <div className="divide-y divide-border">
              {detailTurns.length === 0 ? (
                <div className="px-6 py-8 text-sm text-muted-foreground">No recorded responses were found for this session.</div>
              ) : (
                detailTurns.map((item, index) => (
                  <div key={`${item.question}-${index}`} className="px-6 py-5">
                    <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                      <div>
                        <p className="text-xs uppercase tracking-wider text-muted-foreground">
                          {item.topic || item.question_type}{item.is_followup ? " / follow-up" : ""}
                        </p>
                        <h3 className="mt-1 text-base font-medium leading-6">{item.question}</h3>
                      </div>
                      <span className={`text-lg font-semibold ${scoreTone(item.score)}`}>{Math.round(item.score)}%</span>
                    </div>

                    {item.answer_quality_flags && item.answer_quality_flags.length > 0 && (
                      <div className="mt-4 flex flex-wrap gap-2">
                        {item.answer_quality_flags.map((flag) => (
                          <span key={flag} className="inline-flex items-center gap-1 rounded border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-xs text-amber-600">
                            <AlertTriangle className="h-3 w-3" />
                            {flag.replaceAll("_", " ")}
                          </span>
                        ))}
                      </div>
                    )}

                    <div className="mt-4 grid gap-4 lg:grid-cols-2">
                      <div className="rounded-lg border border-border/50 bg-secondary/10 p-4">
                        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Your response</p>
                        <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-foreground/80">{item.response || "No response captured."}</p>
                      </div>
                      <div className="rounded-lg border border-border/50 bg-card p-4">
                        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">What to improve</p>
                        <p className="mt-2 text-sm leading-6 text-foreground/80">{item.feedback || item.coaching_hint || "No feedback recorded."}</p>
                      </div>
                    </div>

                    {strongerOutline(item) && (
                      <div className="mt-4 rounded-lg border border-primary/20 bg-primary/5 p-4">
                        <p className="text-xs font-semibold uppercase tracking-wider text-primary">Stronger answer outline</p>
                        <p className="mt-2 text-sm leading-6 text-foreground/80">{strongerOutline(item)}</p>
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          )}
        </section>

        {reportV2?.next_recommended_session_date && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <CalendarDays className="h-4 w-4" />
            Recommended next full mock: {reportV2.next_recommended_session_date}
          </div>
        )}
      </div>
    </div>
  )
}
