"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import { AlertTriangle, ArrowLeft, RefreshCw } from "lucide-react"

import { Button } from "@/components/ui/button"
import { downloadInterviewReportJson, fetchInterviewAnalysisStatus, fetchInterviewReport, retryInterviewAnalysis, type InterviewAnalysisStatus } from "@/lib/api"
import { interviewQuestionResponse, interviewQuestionStatus, interviewReportAvailability } from "@/lib/interview-report-state"
import { ReportShell } from "@/components/report/report-shell"
import { ProblemDeepDive } from "@/components/report/problem-deep-dive"
import { QuestionDeepDive } from "@/components/report/question-deep-dive"
import { normalizeReportTranscript, ReportTranscript } from "@/components/report/report-transcript"

type AnyRecord = Record<string, any>

interface InterviewReport {
  interview_id: string
  mode: string
  interview_type: string
  job_title: string
  strictness_level: string
  overall_score: number | null
  duration_seconds?: number | null
  duration_allowed_seconds?: number | null
  report: string | null
  report_v2?: AnyRecord | string | null
  created_at: string | null
  completed_at: string | null
  started_at?: string | null
  deadline_at?: string | null
  status?: string
  analysis_pending?: boolean
  job_target?: {
    profile_type?: string | null
    is_custom?: boolean
    role: string
    company?: string | null
    job_description: string
    saved_for_reuse: boolean
  } | null
  detailed_responses: AnyRecord[]
}

const REPORT_POLL_INTERVAL_MS = 5_000
// Analysis is durable and may legitimately wait on the worker/provider. Keep
// the report surface live for the advertised one-hour processing window.
const REPORT_POLL_MAX_ATTEMPTS = 720

function parseReport(report: InterviewReport | null): AnyRecord | null {
  if (!report?.report_v2) return null
  if (typeof report.report_v2 === "string") {
    try {
      return JSON.parse(report.report_v2) as AnyRecord
    } catch {
      return null
    }
  }
  return report.report_v2
}

function arrayValue(value: any): AnyRecord[] {
  return Array.isArray(value) ? value.filter((item) => item && typeof item === "object") : []
}

function formatDate(value?: string | null) {
  if (!value) return "—"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "—"
  return date.toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" })
}

function duration(value?: number | null) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return "—"
  const minutes = Math.floor(value / 60)
  const seconds = Math.round(value % 60)
  return `${minutes}m ${seconds}s`
}

function numberValue(value: any, fallback = 0) {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback
}

function eventId(value: AnyRecord, prefix: string, index: number) {
  return `${prefix}-${value.round_id || value.response_id || value.question_id || index}`
}

function deriveAllowedDuration(report: InterviewReport, reportV2: AnyRecord | null) {
  if (typeof report.duration_allowed_seconds === "number") return report.duration_allowed_seconds
  if (typeof reportV2?.time_allowed_seconds === "number") return reportV2.time_allowed_seconds
  if (report.started_at && report.deadline_at) {
    const start = new Date(report.started_at).getTime()
    const end = new Date(report.deadline_at).getTime()
    if (Number.isFinite(start) && Number.isFinite(end) && end >= start) return Math.round((end - start) / 1000)
  }
  return null
}

function scoreBreakdown(reportV2: AnyRecord | null) {
  return arrayValue(reportV2?.score_breakdown)
}

function roundAnalysis(reportV2: AnyRecord | null, isTechnical: boolean) {
  const fromRoot = arrayValue(reportV2?.round_analysis)
  const fromMode = arrayValue(reportV2?.technical?.round_analysis)
  return isTechnical ? (fromMode.length ? fromMode : fromRoot) : fromRoot
}

export default function InterviewReportPage() {
  const params = useParams()
  const router = useRouter()
  const interviewId = params.id as string
  const [report, setReport] = useState<InterviewReport | null>(null)
  const [analysisStatus, setAnalysisStatus] = useState<InterviewAnalysisStatus | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [retryingReport, setRetryingReport] = useState(false)
  const [downloadingJson, setDownloadingJson] = useState(false)
  const [pendingElapsed, setPendingElapsed] = useState(0)
  const analysisRequestInFlightRef = useRef(false)
  const reportPollAttemptsRef = useRef(0)

  const loadReport = useCallback(async () => {
    if (!interviewId) return
    try {
      setError(null)
      setReport(await fetchInterviewReport(interviewId) as InterviewReport)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load interview report")
    } finally {
      setIsLoading(false)
    }
  }, [interviewId])

  const refreshAnalysis = useCallback(async () => {
    if (!interviewId || analysisRequestInFlightRef.current) return
    analysisRequestInFlightRef.current = true
    try {
      setError(null)
      const status = await fetchInterviewAnalysisStatus(interviewId)
      setAnalysisStatus(status)
      if (status.report_ready) await loadReport()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load analysis status")
    } finally {
      analysisRequestInFlightRef.current = false
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
      setError(err instanceof Error ? err.message : "Failed to retry report analysis")
    } finally {
      setRetryingReport(false)
    }
  }, [interviewId, refreshAnalysis, retryingReport])

  const downloadJson = useCallback(async () => {
    if (!interviewId || downloadingJson) return
    setDownloadingJson(true)
    setError(null)
    try {
      await downloadInterviewReportJson(interviewId)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to download report JSON")
    } finally {
      setDownloadingJson(false)
    }
  }, [downloadingJson, interviewId])

  useEffect(() => { void refreshAnalysis() }, [refreshAnalysis])

  const statusValue = (analysisStatus?.status || report?.status || "").toLowerCase()
  const reportAvailability = interviewReportAvailability(statusValue, analysisStatus?.attempt_status)
  const interviewStillActive = reportAvailability === "active"
  const interviewRecovering = reportAvailability === "recovering"
  const interviewIncomplete = reportAvailability === "incomplete"
  const reportFailed = !report && analysisStatus?.report_state === "failed"
  const reportPending = !report && !!analysisStatus && !analysisStatus.report_ready && !reportFailed && reportAvailability === "available"

  useEffect(() => {
    if (!reportPending) {
      reportPollAttemptsRef.current = 0
      return
    }
    const timer = setInterval(() => setPendingElapsed((previous) => previous + 1), 1000)
    return () => clearInterval(timer)
  }, [reportPending])

  useEffect(() => {
    if (!reportPending) return

    const poll = () => {
      if (
        document.visibilityState !== "visible"
        || analysisRequestInFlightRef.current
        || reportPollAttemptsRef.current >= REPORT_POLL_MAX_ATTEMPTS
      ) return
      reportPollAttemptsRef.current += 1
      void refreshAnalysis()
    }
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") poll()
    }
    const timer = window.setInterval(poll, REPORT_POLL_INTERVAL_MS)
    document.addEventListener("visibilitychange", onVisibilityChange)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener("visibilitychange", onVisibilityChange)
    }
  }, [refreshAnalysis, reportPending])

  if (interviewRecovering) {
    return <Unavailable title="Interview interrupted" detail="Reopen this interview before the recovery window expires. An official report is not generated while the attempt is recovering." onBack={() => router.push(`/interview/${interviewId}`)} />
  }

  if (interviewIncomplete) {
    return <Unavailable title="Report unavailable" detail="This attempt ended incomplete, so no official report was generated. Your saved evidence remains available for recovery coaching." onBack={() => router.push("/?tab=interview")} />
  }

  if (interviewStillActive) {
    return <Unavailable title="Report unavailable" detail="This interview is still active. Finish the round before opening its report." onBack={() => router.push("/?tab=interview")} />
  }

  if (reportPending) {
    const progress = Math.max(0, Math.min(100, analysisStatus?.job?.progress || 0))
    const executionPending = Boolean(analysisStatus?.execution_pending)
    const stage = executionPending
      ? "grading final code"
      : analysisStatus?.job?.current_stage?.replace(/_/g, " ") || "queued"
    const processingMinutes = analysisStatus?.processing_sla_minutes || 60
    return (
      <div className="min-h-screen bg-background p-6 text-foreground md:p-10">
        <div className="mx-auto max-w-3xl space-y-6">
          <Button variant="outline" onClick={() => router.push("/?tab=interview")}><ArrowLeft className="mr-2 h-4 w-4" />Back to Interview</Button>
          <section className="rounded-lg border border-border bg-card p-6">
            <p className="text-sm font-bold text-primary">{executionPending ? "Final submission processing" : "Report being generated"}</p>
            <h1 className="mt-2 text-2xl font-bold">{executionPending ? "Your final code is still being graded." : "The report is still being generated from the recorded round."}</h1>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">Current stage: <span className="capitalize">{stage}</span>. We will keep checking for up to {processingMinutes} minutes. You can safely leave and return; the recorded round and queued report remain saved.</p>
            <div className="mt-6 h-2 overflow-hidden rounded bg-border/60"><div className="h-full rounded bg-primary transition-all" style={{ width: `${progress}%` }} /></div>
            <div className="mt-2 flex justify-between text-xs text-muted-foreground"><span>{pendingElapsed}s elapsed</span><span>{progress}%</span></div>
            <Button className="mt-6" variant="outline" onClick={refreshAnalysis}><RefreshCw className="mr-2 h-4 w-4" />Refresh</Button>
          </section>
        </div>
      </div>
    )
  }

  if (reportFailed) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background p-6 text-foreground">
        <section className="max-w-lg rounded-lg border border-rose-500/30 bg-card p-8 text-center">
          <AlertTriangle className="mx-auto h-8 w-8 text-rose-500" />
          <h1 className="mt-4 text-xl font-bold">Report generation failed</h1>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">The completed attempt and recorded evidence are preserved. Retry the same analysis when available.</p>
          <div className="mt-6 flex justify-center gap-3">
            <Button variant="outline" onClick={() => router.push("/?tab=interview")}>Interview</Button>
            <Button onClick={() => void retryReport()} disabled={retryingReport || !analysisStatus?.retryable}><RefreshCw className={`mr-2 h-4 w-4 ${retryingReport ? "animate-spin" : ""}`} />{retryingReport ? "Retrying" : "Retry report"}</Button>
          </div>
        </section>
      </div>
    )
  }

  if (isLoading) {
    return <div className="flex min-h-screen items-center justify-center bg-background p-6 text-foreground"><div className="text-center"><div className="mx-auto mb-4 h-10 w-10 animate-spin rounded-full border-2 border-primary/30 border-t-primary" /><h1 className="text-xl font-bold">Loading report</h1></div></div>
  }

  if (error || !report) {
    return <Unavailable title="Report unavailable" detail={error || "We could not load this interview report."} onBack={() => router.push("/?tab=interview")} onRetry={refreshAnalysis} />
  }

  const reportV2 = parseReport(report)
  const isTechnical = report.mode === "technical" || report.interview_type.toLowerCase().includes("technical")
  const isCustomTarget = Boolean(
    report.job_target?.is_custom
      || report.job_target?.profile_type === "custom"
      || reportV2?.profile_type === "custom",
  )
  const profileType = isCustomTarget
    ? "custom"
    : report.job_target?.profile_type || reportV2?.profile_type || null
  const technicalProblems = arrayValue(reportV2?.technical?.problems || reportV2?.problems || reportV2?.test_matrix)
  const reportSummary = typeof reportV2?.summary === "string" ? reportV2.summary.trim() : ""
  const findings = arrayValue(reportV2?.findings)
  const questions: AnyRecord[] = arrayValue(reportV2?.questions || reportV2?.per_turn_feedback || report.detailed_responses)
    .filter((item) => !item.scoring_excluded && !["warmup", "introduction"].includes(String(item.question_type || "").toLowerCase()))
    .map<AnyRecord>((item): AnyRecord => ({
      ...item,
      response: interviewQuestionResponse(item),
      status: interviewQuestionStatus(item),
    }))
  const overallScore = typeof reportV2?.overall_score === "number" ? reportV2.overall_score : report.overall_score
  const counts = reportV2?.counts || {}
  const allowedDuration = deriveAllowedDuration(report, reportV2)
  const usedDuration = typeof report.duration_seconds === "number" ? report.duration_seconds : reportV2?.time_used_seconds
  const analysis = roundAnalysis(reportV2, isTechnical)
  const breakdown = scoreBreakdown(reportV2)
  const timeline = arrayValue(reportV2?.timeline)
  const transcriptTurns = normalizeReportTranscript(reportV2?.transcript, questions)
  const sectionId = (prefix: string, item: AnyRecord, index: number) => eventId(item, prefix, index)

  const stats = isTechnical
    ? [
        { label: "Problems attempted", value: `${numberValue(counts.problems_attempted, technicalProblems.filter((item) => !["Not Attempted", "Unable to Evaluate"].includes(item.status)).length)}/${numberValue(counts.problems_total, technicalProblems.length)}` },
        { label: "Submitted", value: `${numberValue(counts.problems_submitted, technicalProblems.filter((item) => item.final_submission).length)}/${technicalProblems.length}` },
        { label: "Tests passed", value: `${numberValue(counts.tests_passed, technicalProblems.reduce((sum, item) => sum + numberValue(item.visible_passed) + numberValue(item.hidden_passed), 0))}/${numberValue(counts.tests_total, technicalProblems.reduce((sum, item) => sum + numberValue(item.visible_total) + numberValue(item.hidden_total), 0))}` },
        { label: "Problems solved", value: `${numberValue(counts.problems_solved, technicalProblems.filter((item) => item.final_run?.total && item.final_run.passed === item.final_run.total).length)}/${technicalProblems.length}` },
      ]
    : [
        { label: "Questions asked", value: String(numberValue(counts.questions_asked, questions.length)) },
        { label: "Answered", value: `${numberValue(counts.questions_answered, questions.filter((item) => item.status !== "Not Answered").length)}/${questions.length}` },
        { label: "Fully answered", value: String(numberValue(counts.questions_fully_answered, questions.filter((item) => item.fully_answered).length)) },
        { label: "Partially answered", value: String(numberValue(counts.questions_partially_answered, questions.filter((item) => item.partially_answered).length)) },
        { label: "Not answered", value: String(numberValue(counts.questions_not_answered, questions.filter((item) => item.status === "Not Answered").length)) },
      ]

  const sections = [
    { id: "overall-result", title: "Overall Result" },
    ...(reportSummary ? [{ id: "report-summary", title: "Summary" }] : []),
    ...(findings.length ? [{ id: "evidence-findings", title: "Evidence-backed findings" }] : []),
    ...(breakdown.length && !isTechnical ? [{ id: "score-breakdown", title: "Breakdown" }] : []),
    ...(isTechnical ? technicalProblems.map((item, index) => ({ id: sectionId("problem", item, index), title: `Problem ${index + 1}` })) : questions.map((item, index) => ({ id: sectionId("question", item, index), title: `Question ${index + 1}` }))),
    ...(isTechnical && timeline.length ? [{ id: "time-activity", title: "Time / Activity" }] : []),
    ...(!isTechnical && timeline.length ? [{ id: "timeline", title: "Timeline" }] : []),
    ...(analysis.length ? [{ id: "round-analysis", title: "Round Analysis" }] : []),
    ...(transcriptTurns.length ? [{ id: "transcript", title: "Transcript" }] : []),
  ]

  return (
    <ReportShell
      reportType={isTechnical ? "technical" : "interview"}
      title={isTechnical ? "Technical / Coding Round Report" : "Interview Round Report"}
      metadata={{
        date: formatDate(report.completed_at || report.created_at),
        durationUsed: duration(usedDuration),
        durationAllowed: duration(allowedDuration),
        profileType,
        isCustom: isCustomTarget,
        role: report.job_target?.role || report.job_title || undefined,
        company: report.job_target?.company,
        jobDescription: report.job_target?.job_description,
        overallScore,
        stats,
      }}
      sections={sections}
      onDownloadJson={downloadJson}
      downloadingJson={downloadingJson}
    >
      {reportSummary && (
        <section id="report-summary" data-report-section className="rounded-lg border border-border bg-card p-5">
          <h2 className="text-base font-bold">Summary</h2>
          <p className="mt-3 text-sm leading-6 text-muted-foreground">{reportSummary}</p>
        </section>
      )}

      {findings.length > 0 && (
        <section id="evidence-findings" data-report-section className="rounded-lg border border-border bg-card p-5">
          <h2 className="text-base font-bold">Evidence-backed findings</h2>
          <div className="mt-4 space-y-4">
            {findings.map((finding, index) => (
              <div key={finding.finding_key || finding.id || index} className="border-b border-border pb-4 last:border-b-0 last:pb-0">
                <p className="text-sm font-bold">{finding.title || finding.label || finding.finding_key || "Finding"}</p>
                <p className="mt-1 text-sm leading-6 text-muted-foreground">{finding.what_happened || finding.detail || finding.summary || "Recorded evidence from this round."}</p>
                {finding.why_matters && <p className="mt-2 text-sm leading-6 text-muted-foreground">Why it matters: {finding.why_matters}</p>}
              </div>
            ))}
          </div>
        </section>
      )}

      {!isTechnical && breakdown.length > 0 && (
        <section id="score-breakdown" data-report-section className="scroll-mt-8 rounded-lg border border-border bg-card p-5">
          <h2 className="text-base font-bold">Score breakdown</h2>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {breakdown.map((item, index) => (
              <div key={item.key || index} className="rounded-md border border-border/70 bg-background px-4 py-3">
                <p className="text-xs font-bold text-muted-foreground">{item.label || item.key}</p>
                <p className="mt-1 font-mono text-lg font-medium">{item.score == null ? "Unable to Evaluate" : `${Math.round(item.score)}/100`}</p>
              </div>
            ))}
          </div>
        </section>
      )}

      {isTechnical ? (
        technicalProblems.length > 0 ? technicalProblems.map((problem, index) => (
          <ProblemDeepDive
            key={eventId(problem, "problem", index)}
            index={index + 1}
            sectionId={sectionId("problem", problem, index)}
            title={problem.title || `Problem ${index + 1}`}
            language={problem.language}
            status={problem.status}
            score={problem.score}
            scorePoints={problem.score_points ?? (typeof problem.score === "number" ? problem.score * numberValue(problem.max_points, 50) / 100 : null)}
            maxPoints={problem.max_points || (technicalProblems.length ? 100 / technicalProblems.length : 50)}
            timeUsedSeconds={problem.time_used_seconds}
            timeAllowedSeconds={problem.time_allowed_seconds}
            runs={problem.runs ?? problem.run_count}
            submissionCount={problem.submission_count}
            visiblePassed={problem.visible_passed}
            visibleTotal={problem.visible_total}
            hiddenPassed={problem.hidden_passed}
            hiddenTotal={problem.hidden_total}
            finalSubmission={problem.final_submission || Boolean(problem.submission_id)}
            prompt={problem.prompt}
            sourceCode={problem.source_code || problem.source_excerpt}
            sourceLabel={problem.source_label || (problem.submission_id ? "Submitted code" : "Last saved code")}
            whatHappened={problem.what_happened}
            mainIssue={problem.main_issue}
            testEvidence={problem.test_evidence}
            complexity={problem.complexity}
            activity={problem.activity}
          />
        )) : <p className="text-sm text-muted-foreground">No prepared technical problems were recorded.</p>
      ) : (
        questions.length > 0 ? questions.map((question, index) => (
          <QuestionDeepDive
            key={eventId(question, "question", index)}
            index={index + 1}
            sectionId={sectionId("question", question, index)}
            question={question.question}
            response={question.response}
            transcript={question.transcript}
            score={question.score_10 ?? (typeof question.score === "number" ? question.score / 10 : null)}
            status={question.status}
            timeUsedSeconds={question.time_used_seconds ?? question.time_taken}
            whatCandidateAnswered={question.what_candidate_answered}
            whatWasGood={question.what_was_good}
            whatReducedScore={question.what_reduced_score}
            evidence={question.evidence}
            answerStructure={question.answer_structure}
            projectResumeCoverage={question.project_resume_coverage}
            topic={question.topic}
          />
        )) : <p className="text-sm text-muted-foreground">No interview questions were recorded.</p>
      )}

      {isTechnical && timeline.length > 0 && (
        <section id="time-activity" data-report-section className="scroll-mt-8 rounded-lg border border-border bg-card p-5">
          <h2 className="text-base font-bold">Time / activity</h2>
          <Timeline items={timeline} />
        </section>
      )}

      {!isTechnical && timeline.length > 0 && (
        <section id="timeline" data-report-section className="scroll-mt-8 rounded-lg border border-border bg-card p-5">
          <h2 className="text-base font-bold">Timeline</h2>
          <Timeline items={timeline} />
        </section>
      )}

      {analysis.length > 0 && (
        <section id="round-analysis" data-report-section className="scroll-mt-8 rounded-lg border border-border bg-card p-5">
          <h2 className="text-base font-bold">Round analysis</h2>
          <div className="mt-4 space-y-4">
            {analysis.map((item, index) => (
              <div key={`${item.pattern || "pattern"}-${index}`} className="border-b border-border pb-4 last:border-b-0 last:pb-0">
                <p className="text-sm font-bold">{item.pattern}</p>
                <p className="mt-1 text-sm leading-6 text-muted-foreground">{item.detail}</p>
              </div>
            ))}
          </div>
        </section>
      )}

      <ReportTranscript turns={transcriptTurns} />
    </ReportShell>
  )
}

function Timeline({ items }: { items: AnyRecord[] }) {
  return (
    <div className="mt-4 space-y-3">
      {items.map((item, index) => (
        <div key={`${item.at || item.created_at || "event"}-${index}`} className="flex gap-3 border-b border-border pb-3 last:border-b-0 last:pb-0">
          <div className="mt-1 h-2 w-2 shrink-0 rounded-full bg-primary" />
          <div>
            <p className="text-sm font-bold">{item.event || item.event_type || "Activity"}</p>
            <p className="mt-1 text-xs text-muted-foreground">{item.detail || item.label || ""}{(item.detail || item.label) && (item.at || item.created_at) ? " · " : ""}{item.at || item.created_at || ""}</p>
          </div>
        </div>
      ))}
    </div>
  )
}

function Unavailable({ title, detail, onBack, onRetry }: { title: string; detail: string; onBack: () => void; onRetry?: () => void }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6 text-foreground">
      <section className="max-w-lg rounded-lg border border-border bg-card p-8 text-center">
        <h1 className="text-xl font-bold">{title}</h1>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">{detail}</p>
        <div className="mt-6 flex justify-center gap-3">
          <Button variant="outline" onClick={onBack}><ArrowLeft className="mr-2 h-4 w-4" />Interview</Button>
          {onRetry && <Button onClick={onRetry}><RefreshCw className="mr-2 h-4 w-4" />Retry</Button>}
        </div>
      </section>
    </div>
  )
}
