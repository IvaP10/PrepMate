"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import { AlertTriangle, ArrowLeft, RefreshCw } from "lucide-react"

import { Button } from "@/components/ui/button"
import { fetchInterviewAnalysisStatus, fetchInterviewReport, retryInterviewAnalysis, type InterviewAnalysisStatus } from "@/lib/api"
import { buildImproveUrl } from "@/lib/improve-navigation"
import { ReportShell } from "@/components/report/report-shell"
import { SessionSummary } from "@/components/report/session-summary"
import { ProblemDeepDive } from "@/components/report/problem-deep-dive"
import { QuestionDeepDive } from "@/components/report/question-deep-dive"
import { PatternAnalysis } from "@/components/report/pattern-analysis"
import { NextSteps } from "@/components/report/next-steps"
import { PremiumAnalysisSection } from "@/components/report/premium-analysis-section"
import type { PremiumAnalysis } from "@/types/premium-report"

interface DetailedResponse {
  response_id?: string | null
  question_id?: string | null
  section_id?: string | null
  assessment_id?: string | null
  question: string
  question_type: string
  is_followup: boolean
  topic?: string | null
  response: string
  score: number | null
  insufficient_evidence?: boolean
  feedback: string
  time_taken: number | null
  coaching_hint: string | null
  answer_quality_flags?: string[]
  stronger_answer_outline?: string
  evidence_quotes?: string[]
  retry_state?: Record<string, unknown> | null
}

interface ReportV2 {
  version?: string
  report_state?: "ready" | "partial" | "ungradable" | string
  findings?: Array<{
    finding_key?: string
    what_happened?: string
    where_happened?: Record<string, unknown> | string
    why_matters?: string
    evidence_ids?: string[]
    confidence?: number | string
    recommended_action?: string
    measurement?: string
  }>
  summary: string
  readiness_label: string
  overall_score: number | null
  skill_scores: Record<string, number | null>
  dimension_scores?: Record<string, number | null>
  pillar_scores?: Record<string, number | null>
  topic_breakdown: { topic: string; score: number | null; turns: number }[]
  duration_seconds?: number | null
  session?: { duration_seconds?: number | null }
  evidence_status?: Record<string, any>
  transcript?: Array<{ role?: string; speaker?: string; text?: string; content?: string; created_at?: string | null }>
  technical?: {
    state?: string
    problems?: Array<Record<string, any>>
    submissions?: Array<Record<string, any>>
    runs?: Array<Record<string, any>>
    drafts?: Array<Record<string, any>>
    evidence?: Record<string, any>
  }
  technical_process?: Record<string, any>
  test_matrix?: Array<Record<string, any>>
  weak_topics?: Array<Record<string, any> | string>
  ideal_solution?: Record<string, any> | string
  complexity_diff?: Record<string, any>
  line_level_annotations?: Array<Record<string, any>>
  integrity_summary?: Record<string, any>
  candidate_visible_integrity?: Record<string, any>
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
  improvement_plan?: {
    repeated_mistakes?: Array<{ type?: string; count?: number; description?: string; why_bad?: string }>
    weak_areas?: Array<{ response_id?: string; question_id?: string; topic?: string; score?: number | null; mistake?: any }>
    strengths_to_reuse?: string[]
    rewritten_examples?: Array<{
      question?: string
      response_id?: string
      question_id?: string
      original_excerpt?: string
      better_structure?: string[]
      improved_answer?: string
    }>
    next_drills?: Array<{
      mode?: string
      title?: string
      reason?: string
      success_criteria?: string[]
      mission_id?: string
      roadmap_node_id?: string
      exercise_id?: string
      target_mode?: string
    }>
    pre_next_interview_checklist?: string[]
  }
  practice_plan: { day: string; task: string }[]
  per_turn_feedback: Array<DetailedResponse & { stronger_answer_outline?: string }>
  next_recommended_session_date?: string
  premium_analysis?: PremiumAnalysis
}

interface InterviewReport {
  interview_id: string
  mode: string
  interview_type: string
  job_title: string
  strictness_level: string
  overall_score: number | null
  duration_seconds?: number | null
  report: string | null
  report_v2?: ReportV2 | string | null
  created_at: string | null
  completed_at: string | null
  status?: string
  analysis_pending?: boolean
  detailed_responses: DetailedResponse[]
}

function formatDate(value: string | null) {
  if (!value) return "-"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "-"
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

function formatDurationSeconds(value?: number | null) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return undefined
  const minutes = Math.floor(value / 60)
  const seconds = Math.round(value % 60)
  return `${minutes}m ${seconds}s`
}

function stableClientToken(value: string) {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return (hash >>> 0).toString(36)
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

const activeInterviewStatuses = new Set(["in_progress", "uploading"])

export default function InterviewReportPage() {
  const params = useParams()
  const router = useRouter()
  const interviewId = params.id as string

  const [report, setReport] = useState<InterviewReport | null>(null)
  const [analysisStatus, setAnalysisStatus] = useState<InterviewAnalysisStatus | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [retryingReport, setRetryingReport] = useState(false)

  const loadReport = useCallback(async () => {
    if (!interviewId) return
    try {
      setError(null)
      setReport(await fetchInterviewReport(interviewId))
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load interview report")
    } finally {
      setIsLoading(false)
    }
  }, [interviewId])

  const refreshAnalysis = useCallback(async () => {
    if (!interviewId) return
    try {
      setError(null)
      const status = await fetchInterviewAnalysisStatus(interviewId)
      setAnalysisStatus(status)
      if (status.report_ready) {
        await loadReport()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load analysis status")
    } finally {
      setIsLoading(false)
    }
  }, [interviewId, loadReport])

  const retryReport = useCallback(async () => {
    if (!interviewId || retryingReport) return
    setRetryingReport(true)
    setError(null)
    try {
      await retryInterviewAnalysis(interviewId)
      await refreshAnalysis()
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : (err as { message?: string })?.message || "Failed to retry report analysis",
      )
    } finally {
      setRetryingReport(false)
    }
  }, [interviewId, refreshAnalysis, retryingReport])

  useEffect(() => {
    refreshAnalysis()
  }, [refreshAnalysis])

  useEffect(() => {
    if (report || !analysisStatus || analysisStatus.report_ready || analysisStatus.report_state === "failed") return
    const timer = setInterval(() => {
      void refreshAnalysis()
    }, 5000)
    return () => clearInterval(timer)
  }, [analysisStatus, refreshAnalysis, report])

  const reportV2 = useMemo(() => parseReportV2(report), [report])

  const statusValue = (analysisStatus?.status || report?.status || "").toLowerCase()
  const interviewStillActive = activeInterviewStatuses.has(statusValue)
  const reportFailed = !report && analysisStatus?.report_state === "failed"
  const reportPending = !report && analysisStatus && !analysisStatus.report_ready && !reportFailed && !interviewStillActive
  const [pendingElapsed, setPendingElapsed] = useState(0)

  useEffect(() => {
    if (!reportPending) return
    const timer = setInterval(() => setPendingElapsed((prev) => prev + 1), 1000)
    return () => clearInterval(timer)
  }, [reportPending])

  if (interviewStillActive) {
    return (
      <div className="min-h-screen bg-background p-6 text-foreground md:p-10">
        <div className="mx-auto flex max-w-3xl flex-col gap-6">
          <Button variant="outline" onClick={() => router.push("/?tab=interview")}>
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to Interview
          </Button>
          <section className="rounded-lg border border-border bg-card p-6 shadow-sm">
            <p className="text-sm font-medium text-muted-foreground">Report unavailable</p>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight">This interview is still active.</h1>
            <p className="mt-3 text-sm leading-6 text-muted-foreground">
              Finish the interview first. The report is generated only after the backend records the session as ended.
            </p>
          </section>
        </div>
      </div>
    )
  }

  if (reportPending) {
    const progress = Math.max(0, Math.min(100, analysisStatus.job?.progress || 0))
    const stage = analysisStatus.job?.current_stage?.replace(/_/g, " ") || "queued"
    const showTimeoutWarning = pendingElapsed > 300 // 5 minutes
    return (
      <div className="min-h-screen bg-background p-6 text-foreground md:p-10">
        <div className="mx-auto flex max-w-5xl flex-col gap-6">
          <div>
            <Button variant="outline" onClick={() => router.push("/?tab=interview")}>
              <ArrowLeft className="mr-2 h-4 w-4" />
              Back to Interview
            </Button>
          </div>
          <section className="rounded-lg border border-border bg-card p-6 shadow-sm">
            <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <div className="h-3 w-3 rounded-full bg-primary animate-pulse" />
                  <p className="text-sm font-medium text-primary">
                    {analysisStatus.retry_in_progress ? "Report retry is in progress" : "Report being generated"}
                  </p>
                </div>
                <h1 className="mt-2 text-2xl font-semibold tracking-tight">
                  {analysisStatus.retry_in_progress
                    ? "A failed report job is being retried against the same sealed evidence."
                    : "Your report is still being generated."}
                </h1>
                <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
                  This usually takes 3-5 minutes. We&apos;ll automatically load it when it&apos;s ready. You can also leave this page and come back later.
                </p>
              </div>
              <Button onClick={refreshAnalysis} variant="outline" className="gap-2">
                <RefreshCw className="h-4 w-4" />
                Refresh
              </Button>
            </div>
            <div className="mt-6">
              <div className="mb-2 flex items-center justify-between text-sm">
                <span className="capitalize text-muted-foreground">{stage}</span>
                <span className="font-semibold">{progress}%</span>
              </div>
              <div className="h-2 overflow-hidden rounded bg-border/60">
                <div className="h-full rounded bg-primary transition-all" style={{ width: `${progress}%` }} />
              </div>
            </div>
            {showTimeoutWarning && (
              <div className="mt-4 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-700 dark:text-amber-300 flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 shrink-0" />
                Report generation is taking longer than expected. Please try refreshing or come back later.
              </div>
            )}
          </section>
          <section className="grid gap-4 md:grid-cols-3">
            {["Transcript & media", "Content scoring", "Report writing"].map((item, index) => (
              <div key={item} className="rounded-lg border border-border bg-card p-4">
                <p className="text-sm font-semibold">{item}</p>
                <p className="mt-2 text-sm text-muted-foreground">
                  {progress > (index + 1) * 28 ? "Completed or in progress from stored interview data." : "Queued in the analysis job."}
                </p>
              </div>
            ))}
          </section>
        </div>
      </div>
    )
  }

  if (reportFailed) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background p-6 text-foreground">
        <div className="max-w-lg rounded-lg border border-rose-500/30 bg-card p-8 text-center shadow-sm">
          <AlertTriangle className="mx-auto h-8 w-8 text-rose-500" />
          <h1 className="mt-4 text-xl font-semibold">Report generation failed</h1>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            Your completed attempt and sealed evidence are preserved. Retry the same analysis without duplicating or replacing your report history.
          </p>
          <div className="mt-6 flex justify-center gap-3">
            <Button variant="outline" onClick={() => router.push("/?tab=interview")}>
              <ArrowLeft className="mr-2 h-4 w-4" />
              Interview
            </Button>
            <Button onClick={() => void retryReport()} disabled={retryingReport || !analysisStatus?.retryable} className="gap-2">
              <RefreshCw className={`h-4 w-4 ${retryingReport ? "animate-spin" : ""}`} />
              {retryingReport ? "Retrying" : analysisStatus?.retryable ? "Retry report" : "Retry limit reached"}
            </Button>
          </div>
        </div>
      </div>
    )
  }

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
              Interview
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

  // Data Extraction & Formatting
  const isTechnical = report.mode === "technical" || report.interview_type?.toLowerCase().includes("technical")
  const overallScore = reportV2?.overall_score ?? report.overall_score
  const summary = reportV2?.summary || report.report || "This completed session has feedback generated."
  const detailTurns = reportV2?.per_turn_feedback?.length ? reportV2.per_turn_feedback : report.detailed_responses
  const technicalProblems = isTechnical
    ? (reportV2?.technical?.problems?.length ? reportV2.technical.problems : reportV2?.test_matrix || [])
    : []
  const transcriptEntries = Array.isArray(reportV2?.transcript) && reportV2.transcript.length
    ? reportV2.transcript
    : detailTurns.map((turn) => ({ role: "candidate", speaker: "candidate", text: turn.response, content: turn.response }))

  const integritySummary = reportV2?.integrity_summary || reportV2?.candidate_visible_integrity || {}
  const findings = Array.isArray(reportV2?.findings) ? reportV2.findings : []
  const nextRecommendedDate = reportV2?.next_recommended_session_date
  const questionSectionId = (turn: DetailedResponse) => `question-${turn.response_id || turn.question_id || turn.section_id || stableClientToken(`${turn.question}|${turn.response}`)}`
  const problemSectionId = (problem: Record<string, any>) => `problem-${problem.round_id || problem.problem_id || stableClientToken(`${problem.round_type || "technical"}|${problem.prompt || problem.title || "round"}`)}`

  // Sections list for ToC
  const sections = [
    { id: "summary", title: "Summary" }
  ]

  if (findings.length) sections.push({ id: "evidence-findings", title: "Evidence Findings" })

  if (isTechnical) {
    technicalProblems.forEach((problem, idx) => {
      sections.push({ id: problemSectionId(problem), title: `Problem ${idx + 1}` })
    })
  } else {
    detailTurns.forEach((turn, idx) => {
      sections.push({ id: questionSectionId(turn), title: `Question ${idx + 1}` })
    })
  }

  // Add remaining general sections
  const hasImprovements = Array.isArray(reportV2?.improvements) && reportV2.improvements.length > 0
  const hasPracticePlan = Array.isArray(reportV2?.practice_plan) && reportV2.practice_plan.length > 0

  if (hasImprovements || hasPracticePlan) {
    sections.push({ id: "patterns", title: "Patterns" })
  }

  if (hasImprovements || hasPracticePlan) {
    sections.push({ id: "next-steps", title: "Next Steps" })
  }

  // Premium analysis section (if present)
  const hasPremiumAnalysis = !!reportV2?.premium_analysis
  if (hasPremiumAnalysis) {
    sections.push({ id: "premium-analysis", title: "Premium Analysis" })
  }

  // Single-session metadata package
  const metadata = {
    date: formatDate(report.completed_at || report.created_at),
    duration: formatDurationSeconds(report.duration_seconds ?? reportV2?.duration_seconds ?? reportV2?.session?.duration_seconds),
    role: report.job_title || "General Candidate",
    itemCountLabel: isTechnical
      ? `${technicalProblems.length} Problem${technicalProblems.length === 1 ? "" : "s"} Attempted`
      : `${detailTurns.length} Questions Asked`,
    overallScore,
  }

  // Formulate patterns from quality flags / improvements
  const patterns: Array<{ name: string; description: string; countLabel?: string; isPositive?: boolean }> = []
  if (reportV2?.improvement_plan?.repeated_mistakes?.length) {
    reportV2.improvement_plan.repeated_mistakes.slice(0, 4).forEach((item) => {
      patterns.push({
        name: item.type?.replace(/-/g, " ") || "Repeated mistake",
        description: item.why_bad || item.description || "This pattern repeated in the session.",
        countLabel: `${item.count || 1}x`,
      })
    })
  } else if (reportV2?.improvements) {
    reportV2.improvements.slice(0, 3).forEach((item) => {
      patterns.push({
        name: item.title,
        description: item.detail,
        countLabel: "Identified Pitfall"
      })
    })
  }

  // Next steps action items
  const actionItems: Array<{
    title: string
    detail: string
    mode?: string
    mission_id?: string
    roadmap_node_id?: string
    exercise_id?: string
    target_mode?: string
  }> = []
  if (reportV2?.improvement_plan?.next_drills?.length) {
    reportV2.improvement_plan.next_drills.forEach((item) => {
      actionItems.push({
        title: item.title || "Targeted drill",
        detail: item.reason || (item.success_criteria || []).join(", ") || "Redo the weakest answer with the stronger structure.",
        mode: item.mode || "write_it",
        mission_id: item.mission_id,
        roadmap_node_id: item.roadmap_node_id,
        exercise_id: item.exercise_id,
        target_mode: item.target_mode,
      })
    })
  }
  if (!actionItems.length && reportV2?.improvements) {
    reportV2.improvements.forEach((item) => {
      actionItems.push({ title: item.title, detail: item.detail })
    })
  }
  if (reportV2?.practice_plan) {
    reportV2.practice_plan.forEach((item) => {
      actionItems.push({ title: item.day, detail: item.task })
    })
  }
  const startReportDrill = (step: typeof actionItems[number]) => {
    router.push(buildImproveUrl({
      mode: step.target_mode || (isTechnical ? "technical" : "interview"),
      mission_id: step.mission_id,
      roadmap_node_id: step.roadmap_node_id,
      exercise_id: step.exercise_id,
    }))
  }

  return (
    <ReportShell
      reportType={isTechnical ? "technical" : "interview"}
      title={isTechnical ? "Technical Round Report" : "Interview Round Report"}
      metadata={metadata}
      sections={sections}
    >
      {reportV2?.report_state === "partial" && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
          This is a partial report. Deterministic evidence is available, but one or more non-critical analysis stages were unavailable.
        </div>
      )}
      {reportV2?.report_state === "ungradable" && (
        <div className="rounded-lg border border-sky-500/30 bg-sky-500/10 px-4 py-3 text-sm text-sky-800 dark:text-sky-200">
          This session is ungradable. The report preserves what was captured without assigning an official score where evidence was insufficient.
        </div>
      )}

      {/* 1. Summary Section */}
      <SessionSummary
        summary={summary}
        interviewerSignal={reportV2?.student_summary?.interviewer_signal}
      />

      {findings.length > 0 && (
        <section id="evidence-findings" data-report-section className="scroll-mt-20 space-y-3 rounded-lg border border-border bg-card p-5">
          <div>
            <p className="text-sm font-semibold">Evidence-backed findings</p>
            <p className="mt-1 text-xs text-muted-foreground">Each conclusion points to sealed session evidence and a measurable next action.</p>
          </div>
          {findings.map((finding, index) => (
            <article key={finding.finding_key || index} className="rounded-md border border-border/70 bg-secondary/40 p-4">
              <p className="text-sm font-medium text-foreground">{finding.what_happened || "Observed session finding"}</p>
              {finding.why_matters && <p className="mt-2 text-sm text-muted-foreground">{finding.why_matters}</p>}
              {finding.recommended_action && <p className="mt-2 text-sm"><span className="font-medium">Next action:</span> {finding.recommended_action}</p>}
              {finding.measurement && <p className="mt-1 text-xs text-muted-foreground"><span className="font-medium">Measure:</span> {finding.measurement}</p>}
              {!!finding.evidence_ids?.length && (
                <p className="mt-3 font-mono text-[11px] text-muted-foreground">Evidence: {finding.evidence_ids.join(", ")}</p>
              )}
            </article>
          ))}
        </section>
      )}

      {/* 2. Main Content Breakdown: Problems or Questions */}
      {isTechnical ? (
        <div className="space-y-4">
          {technicalProblems.length ? (
            technicalProblems.map((testRow, idx) => (
                <ProblemDeepDive
                  key={testRow.round_id || idx}
                  index={idx + 1}
                  sectionId={problemSectionId(testRow)}
                  problemId={testRow.round_id || testRow.problem_id || stableClientToken(`${testRow.round_type || "technical"}|${testRow.prompt || testRow.title || "round"}`)}
                  title={testRow.title || `Problem ${idx + 1}`}
                  language={testRow.language || report.strictness_level}
                  score={testRow.final_pass_rate ?? testRow.score ?? null}
                  visiblePassed={testRow.visible_passed}
                  visibleTotal={testRow.visible_total}
                  hiddenPassed={testRow.hidden_passed}
                  hiddenTotal={testRow.hidden_total}
                  approach={testRow.algorithm_pattern}
                  idealSolution={
                    testRow.ideal_solution ||
                    (testRow.round_id && typeof reportV2?.ideal_solution === "object" && reportV2?.ideal_solution?.[testRow.round_id]) ||
                    (technicalProblems.length === 1 ? reportV2?.ideal_solution : undefined)
                  }
                  complexityDiff={
                    testRow.complexity_diff ||
                    (testRow.round_id && reportV2?.complexity_diff?.[testRow.round_id]) ||
                    (technicalProblems.length === 1 ? reportV2?.complexity_diff : undefined)
                  }
                  annotations={(reportV2?.line_level_annotations || []).filter((annotation) => (
                    annotation.round_id === testRow.round_id ||
                    (!annotation.round_id && technicalProblems.length === 1)
                  ))}
                  rawCode={testRow.source_code || testRow.source_excerpt}
                  evidenceState={testRow.evidence_state}
                  prompt={testRow.prompt}
                />
              ))
          ) : (
            <section className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">
              No technical code, run, draft, or final submission evidence was captured for this session.
            </section>
          )}
        </div>
      ) : (
        <div className="space-y-4">
          {detailTurns.map((turn, idx) => (
            (() => {
              const weakArea = reportV2?.improvement_plan?.weak_areas?.find((item) => (
                (turn.response_id && item.response_id === turn.response_id) ||
                (turn.question_id && item.question_id === turn.question_id) ||
                (!item.response_id && !item.question_id && item.topic === turn.topic)
              ))
              const rewrite = reportV2?.improvement_plan?.rewritten_examples?.find((item) => (
                (turn.response_id && item.response_id === turn.response_id) ||
                (turn.question_id && item.question_id === turn.question_id) ||
                (!item.response_id && !item.question_id && item.question === turn.question)
              ))
              const mistake = weakArea?.mistake
              return (
                <QuestionDeepDive
                  key={turn.response_id || turn.question_id || idx}
                  sectionId={questionSectionId(turn)}
                  responseId={turn.response_id || undefined}
                  index={idx + 1}
                  question={turn.question}
                  response={turn.response}
                  score={turn.score}
                  feedback={turn.feedback}
                  coachingHint={turn.coaching_hint || undefined}
                  strongerAnswerOutline={turn.stronger_answer_outline}
                  mistake={mistake}
                  whyBad={mistake?.why_bad}
                  betterStructure={rewrite?.better_structure || mistake?.better_structure || []}
                  improvedAnswer={rewrite?.improved_answer || mistake?.improved_answer}
                  sessionAverageScore={overallScore}
                  flags={turn.answer_quality_flags}
                  evidenceQuotes={turn.evidence_quotes}
                />
              )
            })()
          ))}
        </div>
      )}

      {/* 3. Pattern Analysis Section */}
      {(hasImprovements || hasPracticePlan) && (
        <PatternAnalysis patterns={patterns} />
      )}

      {/* 4. Premium Deep Analysis (if available) */}
      {reportV2?.premium_analysis && (
        <section id="premium-analysis" data-report-section className="scroll-mt-20">
          <PremiumAnalysisSection premium={reportV2.premium_analysis} />
        </section>
      )}

      {/* 5. Recommended Next Steps Section */}
      {(hasImprovements || hasPracticePlan) && (
        <NextSteps steps={actionItems.slice(0, 4)} onStartStep={startReportDrill} />
      )}

      {nextRecommendedDate && (
        <div className="text-xs text-muted-foreground text-center mt-6">
          Recommended Next Session Target: {nextRecommendedDate}
        </div>
      )}
    </ReportShell>
  )
}
