"use client"

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import {
  AlertTriangle,
  BarChart3,
  Code,
  Loader2,
  MessageSquare,
  Target,
  TrendingUp,
  ExternalLink,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { SlidingSegmentControl } from "@/components/sliding-segment-control"
import {
  fetchPerformance,
  reconcilePerformance,
  type DynamicPerformanceMetric,
  type DynamicPerformancePayload,
  type DynamicPerformanceSection,
  type PerformanceData,
} from "@/lib/api"
import { safeStorageSet } from "@/lib/safe-storage"

type PerformanceTab = "interview" | "technical"
type PracticeTab = "interview" | "coding"

function clampPercent(value?: number | null) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return 0
  return Math.max(0, Math.min(100, Number(value)))
}

function numericScore(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string") {
    const numeric = Number(value.replace("%", ""))
    return Number.isFinite(numeric) ? numeric : null
  }
  return null
}

function metricTone(value?: number | null) {
  if (value === null || value === undefined) return "text-foreground"
  if (value >= 80) return "text-emerald-500"
  if (value >= 60) return "text-amber-500"
  return "text-rose-500"
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined) return ""
  if (Array.isArray(value)) return value.filter(Boolean).join(", ")
  if (typeof value === "object") return JSON.stringify(value)
  return String(value)
}

function hasDisplayValue(value: unknown) {
  return displayValue(value).trim().length > 0
}

function evidenceHref(item: Record<string, any>, fallbackInterviewId?: string | null): string | null {
  if (item.evidence_url) return String(item.evidence_url)
  const interviewId = item.interview_id || fallbackInterviewId
  if (!interviewId) return null
  const evidenceId = item.response_id || item.round_id || item.evidence_id
  const prefix = item.round_id ? "problem" : "question"
  return `/interview/${interviewId}/report${evidenceId ? `#${prefix}-${evidenceId}` : ""}`
}

function formatTrendDate(value?: string | null) {
  if (!value) return ""
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString(undefined, { month: "short", day: "numeric" })
}

function comparisonDescription(section: DynamicPerformanceSection) {
  return section.description || ""
}

function Section({
  title,
  icon,
  description,
  children,
}: {
  title: string
  icon?: ReactNode
  description?: string | null
  children: ReactNode
}) {
  return (
    <section className="dashboard-card">
      <div className="mb-5 flex items-start gap-3">
        {icon && <div className="mt-0.5 text-primary">{icon}</div>}
        <div>
          <h3 className="text-base font-semibold text-foreground">{title}</h3>
          {description && <p className="mt-1 text-sm leading-6 text-muted-foreground">{description}</p>}
        </div>
      </div>
      {children}
    </section>
  )
}

function OverviewMetric({ metric }: { metric: DynamicPerformanceMetric }) {
  const score = numericScore(metric.raw_value ?? metric.value)
  return (
    <div className="rounded-lg border border-border/45 bg-secondary/15 p-4">
      <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">{metric.label}</p>
      <p className={`mt-2 text-2xl font-medium ${metricTone(score)}`}>{displayValue(metric.value)}</p>
      {metric.detail && <p className="mt-2 text-xs leading-5 text-muted-foreground">{metric.detail}</p>}
    </div>
  )
}

function Overview({ data }: { data: DynamicPerformancePayload }) {
  const metrics = (data.overview || []).filter((metric) => hasDisplayValue(metric.value))
  if (!metrics.length && !data.next_focus) return null
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      {metrics.map((metric) => (
        <OverviewMetric key={`${metric.label}-${metric.value}`} metric={metric} />
      ))}
      {data.next_focus && (
        <div className="rounded-lg border border-primary/30 bg-primary/10 p-4 md:col-span-2 xl:col-span-1">
          <p className="inline-flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-primary">
            <Target className="h-3.5 w-3.5" />
            Next focus
          </p>
          <p className="mt-2 text-base font-semibold text-foreground">{data.next_focus.title}</p>
          {data.next_focus.description && <p className="mt-2 text-xs leading-5 text-muted-foreground">{data.next_focus.description}</p>}
        </div>
      )}
    </div>
  )
}

function TrendSection({ section }: { section: DynamicPerformanceSection }) {
  const points = (section.trend || []).filter((item) => item.score !== null && item.score !== undefined).slice(-8)
  if (points.length < 2) return null
  return (
    <Section title={section.title} description={comparisonDescription(section)} icon={<TrendingUp className="h-5 w-5" />}>
      <div className="flex h-36 items-end gap-2 rounded-lg border border-border/40 bg-secondary/10 p-4">
        {points.map((point, index) => {
          const score = Number(point.score)
          const href = evidenceHref(point)
          const pointDate = point.date || point.label
          const pointContent = (
            <>
              <div
                className="w-full rounded-t-md bg-primary/80"
                style={{ height: `${Math.max(8, clampPercent(score))}%` }}
                aria-label={`Score ${Math.round(score)} percent`}
              />
              <span className="text-[10px] font-medium text-muted-foreground">{Math.round(score)}%</span>
              {pointDate && <span className="max-w-full truncate text-[9px] text-muted-foreground">{formatTrendDate(pointDate)}</span>}
            </>
          )
          return href ? (
            <a key={`${pointDate || point.round_id || point.interview_id || "point"}-${index}`} href={href} className="flex flex-1 flex-col items-center gap-2 rounded focus:outline-none focus:ring-2 focus:ring-primary" title="Open source evidence">{pointContent}</a>
          ) : (
            <div key={`${pointDate || point.round_id || point.interview_id || "point"}-${index}`} className="flex flex-1 flex-col items-center gap-2">{pointContent}</div>
          )
        })}
      </div>
    </Section>
  )
}

function MetricsSection({ section }: { section: DynamicPerformanceSection }) {
  const metrics = (section.metrics || []).filter((metric) => hasDisplayValue(metric.value))
  if (!metrics.length) return null
  return (
    <Section title={section.title} description={comparisonDescription(section)} icon={<BarChart3 className="h-5 w-5" />}>
      <div className="grid gap-4 md:grid-cols-3">
        {metrics.map((metric) => (
          <OverviewMetric key={`${section.id}-${metric.label}`} metric={metric} />
        ))}
      </div>
    </Section>
  )
}

function ScoreRowsSection({ section, interviewId }: { section: DynamicPerformanceSection; interviewId?: string | null }) {
  const rows: Record<string, any>[] = (section.rows || [])
    .map((row): Record<string, any> => ({ ...row, label: row.label ?? row.dimension ?? row.skill ?? row.name }))
    .filter((row) => hasDisplayValue(row.label) && row.score !== null && row.score !== undefined)
  if (!rows.length) return null
  return (
    <Section title={section.title} description={comparisonDescription(section)} icon={<BarChart3 className="h-5 w-5" />}>
      <div className="space-y-3">
        {rows.map((row) => {
          const score = numericScore(row.score)
          return (
            <div key={`${section.id}-${row.label}`} className="space-y-1.5">
              <div className="flex items-center justify-between gap-3 text-sm">
                <span className="text-foreground">
                  {evidenceHref(row, interviewId) ? (
                    <a className="inline-flex items-center gap-1 hover:text-primary hover:underline" href={evidenceHref(row, interviewId)!}>
                      {displayValue(row.label)} <ExternalLink className="h-3 w-3" />
                    </a>
                  ) : displayValue(row.label)}
                </span>
                <span className={`font-medium ${metricTone(score)}`}>
                  {score !== null ? `${Math.round(score)}%` : displayValue(row.score)}
                  {row.detail && <span className="ml-2 text-xs font-normal text-muted-foreground">{displayValue(row.detail)}</span>}
                </span>
              </div>
              {score !== null && (
                <div className="h-2 overflow-hidden rounded-full bg-secondary/70">
                  <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${clampPercent(score)}%` }} />
                </div>
              )}
            </div>
          )
        })}
      </div>
    </Section>
  )
}

function TableSection({ section, interviewId }: { section: DynamicPerformanceSection; interviewId?: string | null }) {
  const rows = section.rows || []
  if (!rows.length) return null
  const declaredColumns = section.columns?.length
    ? section.columns
    : Object.keys(rows[0] || {}).map((key) => ({ key, label: key.replace(/_/g, " ") }))
  const columns = declaredColumns.filter((column) => rows.some((row) => hasDisplayValue(row[column.key])))
  const visibleRows = rows.filter((row) => columns.some((column) => hasDisplayValue(row[column.key])))
  if (!columns.length || !visibleRows.length) return null
  return (
    <Section title={section.title} description={comparisonDescription(section)} icon={<BarChart3 className="h-5 w-5" />}>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-border/40 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {columns.map((column) => (
                <th key={column.key} className="py-3 pr-4">{column.label}</th>
              ))}
              {visibleRows.some((row) => evidenceHref(row, interviewId)) && <th className="py-3 pr-4">Evidence</th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-border/35">
            {visibleRows.map((row, rowIndex) => (
              <tr key={`${section.id}-${row.evidence_id || rowIndex}`}>
                {columns.map((column, columnIndex) => {
                  const value = displayValue(row[column.key])
                  return (
                    <td
                      key={column.key}
                      className={`py-3 pr-4 ${columnIndex === 0 ? "text-foreground" : "text-muted-foreground"}`}
                    >
                      {value}
                    </td>
                  )
                })}
                {visibleRows.some((candidate) => evidenceHref(candidate, interviewId)) && (
                  <td className="py-3 pr-4">
                    {evidenceHref(row, interviewId) ? (
                      <a className="inline-flex items-center gap-1 text-xs font-semibold text-primary hover:underline" href={evidenceHref(row, interviewId)!}>View <ExternalLink className="h-3 w-3" /></a>
                    ) : <span className="text-xs text-muted-foreground">Unavailable</span>}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  )
}

function DynamicSectionRenderer({ section, interviewId }: { section: DynamicPerformanceSection; interviewId?: string | null }) {
  if (section.kind === "trend") return <TrendSection section={section} />
  if (section.kind === "metrics") return <MetricsSection section={section} />
  if (section.kind === "score_rows") return <ScoreRowsSection section={section} interviewId={interviewId} />
  return <TableSection section={section} interviewId={interviewId} />
}

function NoPerformanceData({
  activeTab,
  onOpenPractice,
  message,
}: {
  activeTab: PerformanceTab
  onOpenPractice: (tab: PracticeTab) => void
  message?: string
}) {
  const isTechnical = activeTab === "technical"
  return (
    <div className="dashboard-card flex min-h-[260px] flex-col items-center justify-center gap-4 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-lg border border-border/60 bg-secondary/30 text-primary">
        {isTechnical ? <Code className="h-5 w-5" /> : <MessageSquare className="h-5 w-5" />}
      </div>
      <h3 className="text-base font-semibold text-foreground">
        {message || (isTechnical ? "Complete a technical round to unlock attempted-problem insights." : "Complete an interview to unlock answer insights.")}
      </h3>
      <Button className="gap-2" onClick={() => onOpenPractice(isTechnical ? "coding" : "interview")}>
        {isTechnical ? <Code className="h-4 w-4" /> : <MessageSquare className="h-4 w-4" />}
        {isTechnical ? "Start Technical Round" : "Take Interview Round"}
      </Button>
    </div>
  )
}

function isNotFoundPerformanceError(message: string) {
  const lower = message.toLowerCase()
  return lower.includes("not found") || lower.includes("404")
}

export function PerformanceContent({
  onOpenPractice,
}: {
  onOpenPractice?: (tab: PracticeTab) => void
}) {
  const [activeTab, setActiveTab] = useState<PerformanceTab>("interview")
  const [data, setData] = useState<PerformanceData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [reconcileStatus, setReconcileStatus] = useState("")
  const reconcileAttemptedRef = useRef(false)

  const options = useMemo(() => [
    { value: "interview" as const, label: "Interview Performance", icon: <MessageSquare className="h-4 w-4" /> },
    { value: "technical" as const, label: "Technical Performance", icon: <Code className="h-4 w-4" /> },
  ], [])

  const loadPerformance = async () => {
    setLoading(true)
    setError("")
    try {
      const response = await fetchPerformance()
      setData(response)
    } catch (err: any) {
      setError(err?.message || "Failed to load performance.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadPerformance()
  }, [])

  useEffect(() => {
    const missing = Number(data?.availability?.missing_canonical_count || 0)
    if (!missing || reconcileAttemptedRef.current) return
    reconcileAttemptedRef.current = true
    setReconcileStatus(`Preparing analysis for ${missing} completed interview${missing === 1 ? "" : "s"}…`)
    void reconcilePerformance()
      .then((result) => {
        setReconcileStatus(result.queued_count > 0 ? "Performance analysis is queued. Refresh shortly." : "Performance is up to date.")
        window.setTimeout(() => void loadPerformance(), 3000)
      })
      .catch((reconcileError: any) => setReconcileStatus(reconcileError?.message || "Performance analysis could not be queued."))
  }, [data])

  const openPractice = (tab: PracticeTab) => {
    if (onOpenPractice) {
      onOpenPractice(tab)
      return
    }
    if (typeof window !== "undefined") {
      safeStorageSet("session", "dashboard_tab", tab)
      window.location.assign(`/?tab=${tab}`)
    }
  }

  const activeData = data?.[activeTab] ?? null
  const comparableCount = activeData?.comparability?.comparable_analysis_count ?? 0
  const comparabilityNotice = activeData?.comparison_notice || (comparableCount > 1
    ? `Trend lines compare ${comparableCount} sessions assessed with the same criteria.`
    : "")
  const shouldShowNoData = (!data && isNotFoundPerformanceError(error)) || Boolean(activeData && !activeData.has_data)
  const shouldShowError = Boolean(error && !isNotFoundPerformanceError(error))
  const availability = data?.availability
  const noDataMessage = availability?.completed_count
    ? availability.pending_count > 0 || availability.missing_canonical_count > 0
      ? "Your completed interviews are still being analyzed."
      : availability.failed_count > 0
        ? "Analysis failed for a completed interview. Open Performance again to retry it."
        : "Your completed interviews did not contain enough comparable evidence."
    : undefined

  return (
    <div className="flex-1 overflow-y-auto p-5 font-sans md:p-6">
      <div className="mb-6 flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <SlidingSegmentControl
          options={options}
          value={activeTab}
          onValueChange={setActiveTab}
          ariaLabel="Performance view"
          className="dashboard-segment-tabs w-fit max-w-full gap-1 rounded-full border-0 bg-card p-1.5 shadow-[0_14px_36px_rgba(15,23,42,0.06)] dark:shadow-[0_16px_38px_rgba(0,0,0,0.2)]"
          shape="pill"
        />
      </div>

      {reconcileStatus && (
        <div className="mb-4 rounded-lg border border-border/60 bg-secondary/20 px-4 py-3 text-sm text-muted-foreground">
          {reconcileStatus}
        </div>
      )}

      {loading ? (
        <div className="dashboard-card flex min-h-[260px] flex-col items-center justify-center gap-3 text-center">
          <Loader2 className="h-6 w-6 animate-spin text-primary" />
          <p className="text-sm text-muted-foreground">Loading performance...</p>
        </div>
      ) : shouldShowError ? (
        <div className="dashboard-card flex min-h-[260px] flex-col items-center justify-center gap-4 text-center">
          <AlertTriangle className="h-7 w-7 text-amber-500" />
          <p className="max-w-sm text-sm text-muted-foreground">{error || "Unable to load performance."}</p>
          <Button variant="outline" className="rounded-lg" onClick={loadPerformance}>Try Again</Button>
        </div>
      ) : shouldShowNoData || !activeData ? (
        <NoPerformanceData activeTab={activeTab} onOpenPractice={openPractice} message={noDataMessage} />
      ) : (
        <div className="space-y-6">
          {comparabilityNotice && (
            <div className="rounded-lg border border-border/60 bg-secondary/20 px-4 py-3 text-sm text-muted-foreground">
              {comparabilityNotice}
            </div>
          )}
          {activeData.empty_state_explanation && (
            <div className="flex items-start gap-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{activeData.empty_state_explanation}</span>
            </div>
          )}
          <Overview data={activeData} />
          {(activeData.sections || []).map((section) => (
            <DynamicSectionRenderer key={section.id} section={section} interviewId={activeData.interview_id} />
          ))}
        </div>
      )}
    </div>
  )
}
