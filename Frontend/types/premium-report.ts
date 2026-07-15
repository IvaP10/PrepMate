// ============================================================================
// Premium Report Types
// Shared interfaces for the premium analysis payload produced by
// premium_report_builder.py and rendered by report components.
// ============================================================================

export interface PremiumAnalysis {
  track: "technical" | "behavioral"
  executive_summary: string
  session_integrity_verdict: IntegrityVerdict
  unknown_unknowns: UnknownUnknown[]

  // Track A — Technical Round
  logic_teardown?: AnalysisSection
  complexity_overheads?: AnalysisSection
  optimal_delta?: AnalysisSection
  edge_case_forensics?: AnalysisSection

  // Track B — Mock Interview
  content_accuracy?: AnalysisSection
  vocal_delivery?: VocalDeliverySection
  proctoring_audit?: ProctoringAuditSection
}

export type Severity = "critical" | "warning" | "info"

export interface AnalysisSection {
  title: string
  severity: Severity
  verdict: string
  details: AnalysisDetail[]
}

export interface AnalysisDetail {
  explanation: string
  snippet?: string
  line?: number
  quote?: string
  contrast?: string
  real_world_consequence?: string
  your_approach?: string
  gold_standard?: string
}

export interface VocalDeliverySection extends AnalysisSection {
  metrics: VocalMetrics
}

export interface VocalMetrics {
  words_per_minute: number
  filler_words_per_minute: number
  response_latency_avg: number | null
  clarity_proxy: number | null
}

export interface ProctoringAuditSection extends AnalysisSection {
  integrity_grade: string
  risk_score: number
  risk_level: string
}

export interface ProctoringDetail extends AnalysisDetail {
  event_type: string
  count?: number
  event_severity: Severity | string
}

export interface IntegrityVerdict {
  grade: string
  label: string
  risk_score: number
  high_severity_event_count: number
  total_event_count: number
}

export interface UnknownUnknown {
  title: string
  insight: string
}
