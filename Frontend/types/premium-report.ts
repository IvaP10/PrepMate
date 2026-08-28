// ============================================================================
// Premium Report Types
// Shared interfaces for the premium analysis payload produced by
// premium_report_builder.py and rendered by report components.
// ============================================================================

export interface PremiumAnalysis {
  track: "technical" | "behavioral"
  executive_summary: string
  self_review_verdict: SelfReviewVerdict
  unknown_unknowns: UnknownUnknown[]

  // Track A — Technical Round
  logic_teardown?: AnalysisSection
  complexity_overheads?: AnalysisSection
  optimal_delta?: AnalysisSection
  edge_case_forensics?: AnalysisSection

  // Track B — Mock Interview
  content_accuracy?: AnalysisSection
  vocal_delivery?: VocalDeliverySection
  self_review_signals?: SelfReviewSignalsSection
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

export interface SelfReviewSignalsSection extends AnalysisSection {
  mode: "self_review"
}

export interface SelfReviewSignalDetail extends AnalysisDetail {
  event_type: string
  count?: number
  event_severity: Severity | string
}

export interface SelfReviewVerdict {
  label: string
  signal_count: number
  mode?: "self_review"
}

export interface UnknownUnknown {
  title: string
  insight: string
}
