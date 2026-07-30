"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { AlertTriangle, Code, Loader2, MessageSquare } from "lucide-react"
import { SlidingSegmentControl } from "@/components/sliding-segment-control"
import { Button } from "@/components/ui/button"
import {
  fetchPerformance,
  reconcilePerformance,
  type DynamicPerformancePayload,
  type PerformanceData,
  type PerformanceDirection,
  type PerformancePagePayload,
  type PerformancePattern,
  type PerformanceTrendPoint,
} from "@/lib/api"
import {
  chooseInitialPerformanceTab,
  performanceStateNotice,
} from "@/lib/performance-state"
import { safeStorageSet } from "@/lib/safe-storage"

type PracticeTab = "interview" | "coding"

function clampPercent(value?: number | null) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return 0
  return Math.max(0, Math.min(100, Number(value)))
}

function numericScore(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string") {
    const numeric = Number(value.replace("%", "").trim())
    return Number.isFinite(numeric) ? numeric : null
  }
  return null
}

function formatScore(value?: number | null) {
  const numeric = numericScore(value)
  return numeric === null ? "—" : `${Math.round(clampPercent(numeric))}%`
}

function formatTrendDate(value?: string | null, fallback?: string) {
  if (!value) return fallback || "Interview"
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime())
    ? value
    : parsed.toLocaleDateString(undefined, { month: "short", day: "numeric" })
}

function findTrend(payload?: DynamicPerformancePayload | null): PerformanceTrendPoint[] {
  if (payload?.trend?.length) return payload.trend.slice(-5)
  const section = payload?.sections?.find((item) => item.kind === "trend" && item.trend?.length)
  return section?.trend?.slice(-5) || []
}

function findOverviewScore(payload?: DynamicPerformancePayload | null) {
  if (payload?.overall_score !== null && payload?.overall_score !== undefined) return payload.overall_score
  return null
}

function legacyPerformancePage(data: PerformanceData): PerformancePagePayload {
  const dimensionRows = data.interview.sections?.find((section) => section.id === "dimension_scores")?.rows || []
  const dimensionScore = (needles: string[]) => {
    const row = dimensionRows.find((item) => {
      const label = String(item.dimension || item.label || item.metric || "").toLowerCase()
      return needles.some((needle) => label.includes(needle))
    })
    return numericScore(row?.score)
  }
  const repeatedRows = data.interview.sections?.find((section) => section.id === "repeated_mistakes")?.rows || []
  const projectRows = data.interview.sections?.find((section) => section.id === "project_explanation")?.rows || []
  const projectScores = projectRows.map((row) => numericScore(row.score)).filter((score): score is number => score !== null)
  const gaps = data.technical.sections?.find((section) => section.id === "topic_performance")?.rows || []
  const interviewTrend = findTrend(data.interview)
  const interviewScore = findOverviewScore(data.interview)
  const technicalTrend = findTrend(data.technical)
  const technicalScore = findOverviewScore(data.technical)
  const communication = {
    fluency_clarity: {
      score: dimensionScore(["communication", "clarity"]),
      detail: "Based on available transcript assessments.",
    },
    confidence: {
      score: null,
      detail: "Measured voice-delivery evidence is not available yet.",
    },
    patterns: repeatedRows.map((row) => ({
      label: String(row.mistake || row.label || "Communication pattern"),
      count: Number(row.count || 0),
      detail: row.example ? `Seen in: ${row.example}` : undefined,
    })),
  }
  const projectExplanation = {
    score: projectScores.length ? projectScores.reduce((total, score) => total + score, 0) / projectScores.length : null,
    answer_count: projectScores.length,
    detail: projectScores.length ? `Based on ${projectScores.length} scored project answer${projectScores.length === 1 ? "" : "s"}.` : "No project explanation has enough scored evidence yet.",
    breakdown: [],
  }
  const knowledgeGaps = gaps
    .filter((row) => numericScore(row.score) !== null && Number(row.attempts || 0) >= 2 && Number(numericScore(row.score)) < 70)
    .map((row) => ({
      label: String(row.topic || "Technical topic"),
      score: numericScore(row.score),
      session_count: Number(row.attempts || 0),
    }))
  const emptyInsights = { recurring_mistakes: [], improving: [], declining: [] }
  return {
    role: {},
    interview_view: {
      latest_score: interviewScore,
      trend: interviewTrend,
      communication,
      project_explanation: projectExplanation,
      insights: emptyInsights,
      strengths: [],
    },
    technical_view: {
      latest_score: technicalScore,
      trend: technicalTrend,
      knowledge_gaps: knowledgeGaps,
      insights: emptyInsights,
      strengths: [],
    },
    overall: {
      latest_interview_score: interviewScore,
      performance_trend: interviewTrend,
      readiness: {
        score: null,
        label: "Building evidence",
        detail: "Comparable communication, technical, consistency, and interview-history evidence is still being prepared.",
        components: [],
      },
    },
    communication,
    technical: {
      trend: technicalTrend,
      latest_score: technicalScore,
      knowledge_gaps: knowledgeGaps,
      project_explanation: projectExplanation,
    },
    insights: {
      recurring_mistakes: [],
      improving: [],
      declining: [],
      ai_insights: data.interview.next_focus?.description ? [data.interview.next_focus.description] : [],
    },
    strengths: [],
  }
}

function SectionHeading({ number, title }: { number: string; title: string }) {
  return (
    <div className="mb-5">
      <div className="flex items-baseline gap-3">
        <span className="text-xs font-semibold text-primary">{number}</span>
        <h2 className="text-lg font-semibold text-foreground">{title}</h2>
      </div>
    </div>
  )
}

function ScoreMetric({ label, score }: {
  label: string
  score?: number | null
}) {
  return (
    <div className="min-w-0 py-3 sm:px-5 sm:first:pl-0 sm:last:pr-0">
      <p className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold tracking-tight text-foreground">{formatScore(score)}</p>
    </div>
  )
}

function TrendChart({ points, label }: {
  points: PerformanceTrendPoint[]
  label: string
}) {
  const [activePoint, setActivePoint] = useState<number | null>(null)
  const available = points.filter((point) => point.score !== null && point.score !== undefined).slice(-5)
  if (!available.length) {
    return <p className="py-10 text-sm text-muted-foreground">No scored rounds yet.</p>
  }

  const width = 680
  const height = 210
  const left = 44
  const right = 28
  const top = 30
  const bottom = 24
  const plotWidth = width - left - right
  const plotHeight = height - top - bottom
  const coordinates = available.map((point, index) => ({
    ...point,
    x: available.length === 1 ? left + plotWidth / 2 : left + (index / (available.length - 1)) * plotWidth,
    y: top + ((100 - clampPercent(point.score)) / 100) * plotHeight,
  }))
  const path = coordinates.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" ")

  return (
    <div className="w-full">
      <svg
        role="img"
        aria-label={label}
        viewBox={`0 0 ${width} ${height}`}
        className="h-auto w-full"
      >
        <title>{label}</title>
        <desc>{available.map((point, index) => `${formatTrendDate(point.date || point.label, `Round ${index + 1}`)}: ${Math.round(Number(point.score))} percent`).join(", ")}</desc>
        {[0, 25, 50, 75, 100].map((tick) => {
          const y = top + ((100 - tick) / 100) * plotHeight
          return (
            <g key={tick}>
              <line x1={left} x2={width - right} y1={y} y2={y} className="stroke-border" strokeWidth="1" />
              <text x={left - 10} y={y + 4} textAnchor="end" className="fill-muted-foreground text-[10px]">{tick}</text>
            </g>
          )
        })}
        {coordinates.length > 1 && <path d={path} fill="none" className="stroke-primary" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />}
        {coordinates.map((point, index) => {
          const date = formatTrendDate(point.date || point.label, `Round ${index + 1}`)
          const tooltipWidth = 126
          const tooltipX = Math.max(4, Math.min(width - tooltipWidth - 4, point.x - tooltipWidth / 2))
          const tooltipY = point.y < 68 ? point.y + 16 : point.y - 58
          return (
            <g
              key={`${point.interview_id || point.round_id || point.date || "point"}-${index}`}
              tabIndex={0}
              role="button"
              aria-label={`${date}, ${Math.round(Number(point.score))} percent`}
              onMouseEnter={() => setActivePoint(index)}
              onMouseLeave={() => setActivePoint(null)}
              onPointerEnter={() => setActivePoint(index)}
              onPointerLeave={() => setActivePoint(null)}
              onFocus={() => setActivePoint(index)}
              onBlur={() => setActivePoint(null)}
              onClick={() => setActivePoint(index)}
              className="cursor-crosshair outline-none"
            >
              <circle cx={point.x} cy={point.y} r="16" className="fill-transparent" />
              <circle cx={point.x} cy={point.y} r={activePoint === index ? 6 : 5} className="fill-primary stroke-card transition-all" strokeWidth="3" />
              {activePoint === index && (
                <g pointerEvents="none">
                  <rect x={tooltipX} y={tooltipY} width={tooltipWidth} height="44" rx="8" className="fill-foreground" />
                  <text x={tooltipX + 10} y={tooltipY + 17} className="fill-background text-[10px] font-medium">{date}</text>
                  <text x={tooltipX + 10} y={tooltipY + 34} className="fill-background text-[12px] font-semibold">Score {Math.round(Number(point.score))}%</text>
                </g>
              )}
            </g>
          )
        })}
      </svg>
    </div>
  )
}

function PatternList({ items, emptyMessage = "None" }: { items: PerformancePattern[]; emptyMessage?: string }) {
  if (!items.length) return <EmptyList message={emptyMessage} />
  return (
    <div className="divide-y divide-border/45">
      {items.map((item, index) => (
        <div key={`${item.label}-${index}`} className="py-3 first:pt-0 last:pb-0">
          <div className="flex items-start justify-between gap-3">
            <p className="text-sm font-medium text-foreground">{item.label}</p>
            {item.session_count ? <span className="shrink-0 text-xs text-muted-foreground">{item.session_count} interviews</span> : null}
          </div>
          {item.score !== null && item.score !== undefined && (
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-secondary">
              <div className="h-full rounded-full bg-primary" style={{ width: `${clampPercent(item.score)}%` }} />
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function DirectionList({ items, direction }: { items: PerformanceDirection[]; direction: "up" | "down" }) {
  if (!items.length) {
    return <EmptyList message="None" />
  }
  return (
    <div className="space-y-3">
      {items.map((item) => (
        <div key={`${direction}-${item.label}`} className="flex items-center justify-between gap-3 border-b border-border/40 pb-3 last:border-0 last:pb-0">
          <span className="text-sm text-foreground">{item.label}</span>
          <span className="shrink-0 text-sm font-semibold text-foreground">{item.delta > 0 ? "+" : ""}{Math.round(item.delta)} pts</span>
        </div>
      ))}
    </div>
  )
}

function EmptyList({ message }: { message: string }) {
  return <p className="py-2 text-sm leading-6 text-muted-foreground">{message}</p>
}

function NoPerformanceData({ onOpenPractice, message }: {
  onOpenPractice: (tab: PracticeTab) => void
  message?: string
}) {
  return (
    <div className="dashboard-card flex min-h-[300px] flex-col items-center justify-center gap-4 text-center">
      <h3 className="text-base font-semibold text-foreground">{message || "No performance data"}</h3>
      <div className="flex flex-wrap justify-center gap-3">
        <Button className="gap-2" onClick={() => onOpenPractice("interview")}>
          <MessageSquare className="h-4 w-4" /> Take Interview Round
        </Button>
        <Button variant="outline" className="gap-2" onClick={() => onOpenPractice("coding")}>
          <Code className="h-4 w-4" /> Start Technical Round
        </Button>
      </div>
    </div>
  )
}

function LegacyHistory({
  points,
  activeTab,
}: {
  points: PerformanceTrendPoint[]
  activeTab: PracticeTab
}) {
  const mode = activeTab === "coding" ? "technical" : "interview"
  const visible = points.filter((point) => point.mode === mode).slice(0, 8)
  if (!visible.length) return null
  return (
    <section className="dashboard-card">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-foreground">Legacy history</h2>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">
            Older saved report scores are shown for reference only. They do not affect current readiness or trends.
          </p>
        </div>
        <span className="rounded-full bg-secondary px-3 py-1 text-xs font-medium text-muted-foreground">Not comparable</span>
      </div>
      <div className="divide-y divide-border/50 border-y border-border/60">
        {visible.map((point, index) => (
          <div key={`${point.interview_id || point.date || "legacy"}-${index}`} className="flex items-center justify-between gap-4 py-3">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-foreground">{point.label || (mode === "technical" ? "Technical Round" : "Interview Round")}</p>
              <p className="mt-0.5 text-xs text-muted-foreground">{formatTrendDate(point.date, "Historical report")}</p>
            </div>
            <span className="shrink-0 text-sm font-semibold text-foreground">{formatScore(point.score)}</span>
          </div>
        ))}
      </div>
    </section>
  )
}

function PerformancePage({
  page,
  legacyHistory = [],
  interviewPayload,
  technicalPayload,
}: {
  page: PerformancePagePayload
  legacyHistory?: PerformanceTrendPoint[]
  interviewPayload?: DynamicPerformancePayload | null
  technicalPayload?: DynamicPerformancePayload | null
}) {
  const [activeTab, setActiveTab] = useState<PracticeTab>(() => (
    chooseInitialPerformanceTab(
      interviewPayload,
      technicalPayload,
      legacyHistory,
    )
  ))
  const interview = page.interview_view || {
    latest_score: page.overall.latest_interview_score,
    trend: page.overall.performance_trend || [],
    communication: page.communication,
    project_explanation: page.technical.project_explanation,
    insights: page.insights,
    strengths: page.strengths || [],
  }
  const technical = page.technical_view || {
    latest_score: page.technical.latest_score,
    trend: page.technical.trend || [],
    knowledge_gaps: page.technical.knowledge_gaps || [],
    insights: page.insights,
    strengths: page.strengths || [],
  }
  const activePayload = activeTab === "coding"
    ? technicalPayload
    : interviewPayload
  const stateNotice = performanceStateNotice(activePayload, activeTab)

  return (
    <div
      className="space-y-5"
      data-testid="performance-page"
      data-performance-mode={activeTab}
      data-performance-state={activePayload?.score_state || "unknown"}
    >
      <SlidingSegmentControl
        ariaLabel="Performance round type"
        options={[
          { value: "interview" as const, label: "Interview Round", icon: <MessageSquare className="h-4 w-4" /> },
          { value: "coding" as const, label: "Technical Round", icon: <Code className="h-4 w-4" /> },
        ]}
        value={activeTab}
        onValueChange={setActiveTab}
        className="dashboard-segment-tabs w-fit max-w-full gap-1 rounded-full border-0 bg-card p-1.5 shadow-[0_14px_36px_rgba(15,23,42,0.06)] dark:shadow-[0_16px_38px_rgba(0,0,0,0.2)]"
        buttonClassName="h-10 px-4"
        shape="pill"
      />

      {stateNotice ? (
        <div className="dashboard-card flex items-start gap-3 border-amber-500/25 bg-amber-500/5">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
          <div>
            <p className="text-sm font-medium text-foreground">Score status</p>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">{stateNotice}</p>
          </div>
        </div>
      ) : null}

      {activePayload?.overall_score == null && activePayload?.official_score != null ? (
        <div className="dashboard-card flex flex-wrap items-center justify-between gap-4" data-testid="previous-official-score">
          <div>
            <p className="text-sm font-semibold text-foreground">Previous official score</p>
            <p className="mt-1 text-sm text-muted-foreground">Kept for reference; your latest attempt remains unscored.</p>
          </div>
          <span className="text-2xl font-semibold tracking-tight text-foreground">{formatScore(activePayload.official_score)}</span>
        </div>
      ) : null}

      {activeTab === "interview" ? (
        <div className="animate-fade-in-up space-y-5">
        <section className="dashboard-card">
          <SectionHeading number="01" title="Interview Performance" />
          <TrendChart points={interview.trend || []} label="Last five interview scores" />
        </section>

        <section className="dashboard-card">
          <SectionHeading number="02" title="Communication" />
          <div className="grid divide-y divide-border/60 border-y border-border/60 sm:grid-cols-2 sm:divide-x sm:divide-y-0">
            <ScoreMetric label="Fluency & Clarity" score={interview.communication.fluency_clarity?.score} />
            <ScoreMetric label="Confidence" score={interview.communication.confidence?.score} />
          </div>
          <div className="pt-5">
            <h3 className="mb-3 text-sm font-semibold text-foreground">Communication Patterns</h3>
            <PatternList items={interview.communication.patterns || []} emptyMessage="No recurring communication pattern yet." />
          </div>
        </section>

        <section className="dashboard-card">
          <SectionHeading number="03" title="Project Explanation" />
          <div className="grid divide-y divide-border/60 border-y border-border/60 sm:grid-cols-2 sm:divide-x sm:divide-y-0 lg:grid-cols-5">
            <ScoreMetric label="Score" score={interview.project_explanation.score} />
            {(interview.project_explanation.breakdown || []).map((item) => (
              <ScoreMetric key={item.label} label={item.label} score={item.score} />
            ))}
          </div>
        </section>

        <InsightsSection number="04" title="Interview Insights" insights={interview.insights} />
        <StrengthsSection number="05" strengths={interview.strengths || []} />
        </div>
      ) : (
        <div className="animate-fade-in-up space-y-5">
        <section className="dashboard-card">
          <SectionHeading number="01" title="Technical Performance" />
          <TrendChart points={technical.trend || []} label="Last five technical scores" />
        </section>

        <section className="dashboard-card">
          <SectionHeading number="02" title="Knowledge Gaps" />
          <PatternList items={technical.knowledge_gaps || []} />
        </section>

        <InsightsSection number="03" title="Technical Insights" insights={technical.insights} />
        <StrengthsSection number="04" strengths={technical.strengths || []} />
        </div>
      )}
      <LegacyHistory points={legacyHistory} activeTab={activeTab} />
    </div>
  )
}

function InsightsSection({
  number,
  title,
  insights,
}: {
  number: string
  title: string
  insights: {
    recurring_mistakes: PerformancePattern[]
    improving: PerformanceDirection[]
    declining: PerformanceDirection[]
  }
}) {
  return (
    <section className="dashboard-card">
      <SectionHeading number={number} title={title} />
      <div className="grid divide-y divide-border/60 border-y border-border/60 lg:grid-cols-3 lg:divide-x lg:divide-y-0">
        <div className="py-4 lg:pr-5">
          <h3 className="mb-3 text-sm font-semibold text-foreground">Recurring Mistakes</h3>
          <PatternList items={insights.recurring_mistakes || []} emptyMessage="No recurring mistake yet." />
        </div>
        <div className="py-4 lg:px-5">
          <h3 className="mb-3 text-sm font-semibold text-foreground">Areas Improving</h3>
          <DirectionList items={insights.improving || []} direction="up" />
        </div>
        <div className="py-4 lg:pl-5">
          <h3 className="mb-3 text-sm font-semibold text-foreground">Areas Declining</h3>
          <DirectionList items={insights.declining || []} direction="down" />
        </div>
      </div>
    </section>
  )
}

function StrengthsSection({ number, strengths }: { number: string; strengths: string[] }) {
  return (
    <section className="dashboard-card">
      <SectionHeading number={number} title="Strengths" />
      {strengths.length ? (
        <div className="divide-y divide-border/50 border-y border-border/60">
          {strengths.slice(0, 5).map((strength, index) => (
            <div key={`${strength}-${index}`} className="flex gap-3 py-3 text-sm leading-6 text-foreground">
              <span className="text-primary">•</span>
              <span>{strength}</span>
            </div>
          ))}
        </div>
      ) : (
        <EmptyList message="None" />
      )}
    </section>
  )
}

function isNotFoundPerformanceError(message: string) {
  const lower = message.toLowerCase()
  return lower.includes("not found") || lower.includes("404")
}

export function PerformanceContent({ onOpenPractice }: { onOpenPractice?: (tab: PracticeTab) => void }) {
  const [data, setData] = useState<PerformanceData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [reconcileError, setReconcileError] = useState("")
  const [reconciling, setReconciling] = useState(false)
  const reconcileAttemptedRef = useRef(false)
  const pollingStartedAtRef = useRef(0)

  const loadPerformance = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true)
    setError("")
    try {
      setData(await fetchPerformance())
    } catch (err: any) {
      setError(err?.message || "Failed to load performance.")
    } finally {
      if (showLoading) setLoading(false)
    }
  }, [])

  const runReconciliation = useCallback(async () => {
    if (reconciling) return
    setReconciling(true)
    setReconcileError("")
    reconcileAttemptedRef.current = true
    pollingStartedAtRef.current = Date.now()
    try {
      let cursor: string | null | undefined = null
      let exhausted = 0
      let pageCount = 0
      do {
        const result = await reconcilePerformance(cursor)
        exhausted += Number(result.retry_exhausted_count || 0)
        cursor = result.next_cursor
        pageCount += 1
      } while (cursor && pageCount < 20)
      if (exhausted) {
        setReconcileError(`${exhausted} analysis job${exhausted === 1 ? "" : "s"} reached the retry limit.`)
      }
      await loadPerformance(false)
    } catch (err: any) {
      reconcileAttemptedRef.current = false
      setReconcileError(err?.message || "Could not prepare performance analysis.")
    } finally {
      setReconciling(false)
    }
  }, [loadPerformance, reconciling])

  useEffect(() => {
    void loadPerformance()
  }, [loadPerformance])

  useEffect(() => {
    const missing = Number(data?.availability?.missing_canonical_count || 0)
    const pending = Number(data?.availability?.pending_count || 0)
    if (!missing && !pending) {
      reconcileAttemptedRef.current = false
      pollingStartedAtRef.current = 0
      return
    }
    if (missing && !reconcileAttemptedRef.current) {
      void runReconciliation()
      return
    }
    if (!pollingStartedAtRef.current) pollingStartedAtRef.current = Date.now()
    const elapsed = Date.now() - pollingStartedAtRef.current
    if (elapsed >= 15 * 60 * 1000) return
    const delay = elapsed < 15_000 ? 3_000 : 15_000
    const timer = window.setTimeout(() => {
      void loadPerformance(false)
    }, delay)
    return () => window.clearTimeout(timer)
  }, [
    data?.availability?.missing_canonical_count,
    data?.availability?.pending_count,
    loadPerformance,
    runReconciliation,
  ])

  const openPractice = (tab: PracticeTab) => {
    if (onOpenPractice) {
      onOpenPractice(tab)
      return
    }
    safeStorageSet("session", "dashboard_tab", tab)
    window.location.assign(`/?tab=${tab}`)
  }

  const legacyHistory = data?.history?.legacy || []
  const hasAnyData = Boolean(
    data?.interview?.has_data
    || data?.technical?.has_data
    || legacyHistory.length,
  )
  const shouldShowNoData = (!data && isNotFoundPerformanceError(error)) || Boolean(data && !hasAnyData)
  const shouldShowError = Boolean(error && !isNotFoundPerformanceError(error))
  const availability = data?.availability
  const noDataMessage = availability?.completed_count
    ? availability.blocked_count
      ? "Analysis is waiting for the worker service"
      : availability.pending_count > 0 || availability.missing_canonical_count > 0
      ? "Performance will appear after analysis finishes"
      : availability.failed_count > 0
        ? "Score analysis failed"
        : "No scored interviews"
    : undefined
  const page = data ? data.page || legacyPerformancePage(data) : null
  const stateMessage = availability?.blocked_count
    ? "Analysis is queued, but the analysis worker is not currently available."
    : availability?.pending_count || availability?.missing_canonical_count
      ? "Your completed rounds are being converted into evidence-backed Performance. This page refreshes automatically."
      : availability?.failed_count
        ? "One or more completed rounds could not be analyzed."
        : reconcileError
          ? reconcileError
          : ""

  return (
    <div
      className="flex-1 overflow-y-auto p-5 font-sans md:p-6"
      data-testid="performance-content"
    >
      {loading ? (
        <div className="dashboard-card flex min-h-[300px] flex-col items-center justify-center gap-3 text-center">
          <Loader2 className="h-6 w-6 animate-spin text-primary" />
          <p className="text-sm text-muted-foreground">Loading performance...</p>
        </div>
      ) : shouldShowError ? (
        <div className="dashboard-card flex min-h-[300px] flex-col items-center justify-center gap-4 text-center">
          <AlertTriangle className="h-7 w-7 text-amber-500" />
          <p className="max-w-sm text-sm text-muted-foreground">{error || "Unable to load performance."}</p>
          <Button variant="outline" className="rounded-lg" onClick={() => void loadPerformance(true)}>Try Again</Button>
        </div>
      ) : (
        <div className="space-y-4">
          {stateMessage ? (
            <div className="dashboard-card flex flex-wrap items-center justify-between gap-3 border-amber-500/25 bg-amber-500/5">
              <div className="flex min-w-0 items-start gap-3">
                {reconciling || availability?.pending_count ? (
                  <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-amber-600" />
                ) : (
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
                )}
                <p className="text-sm leading-6 text-foreground">{stateMessage}</p>
              </div>
              {(availability?.failed_count || availability?.blocked_count || reconcileError) ? (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={reconciling}
                  onClick={() => {
                    reconcileAttemptedRef.current = false
                    void runReconciliation()
                  }}
                >
                  {reconciling ? "Retrying…" : "Retry analysis"}
                </Button>
              ) : null}
            </div>
          ) : null}
          {shouldShowNoData || !page ? (
            <NoPerformanceData onOpenPractice={openPractice} message={noDataMessage} />
          ) : (
            <PerformancePage
              page={page}
              legacyHistory={legacyHistory}
              interviewPayload={data?.interview}
              technicalPayload={data?.technical}
            />
          )}
        </div>
      )}
    </div>
  )
}
