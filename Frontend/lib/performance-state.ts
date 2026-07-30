export type PerformanceTab = "interview" | "coding"

export interface PerformanceStateInput {
  has_evidence?: boolean
  has_official_score?: boolean
  score_state?: string
}

export interface LegacyPerformanceStateInput {
  mode?: string
}

function hasOfficialScore(payload?: PerformanceStateInput | null) {
  return Boolean(
    payload?.has_official_score
    || payload?.score_state === "ready",
  )
}

function hasRecordedEvidence(payload?: PerformanceStateInput | null) {
  return Boolean(payload?.has_evidence)
}

function hasSessionState(payload?: PerformanceStateInput | null) {
  return Boolean(
    payload?.score_state
    && payload.score_state !== "missing",
  )
}

export function chooseInitialPerformanceTab(
  interview?: PerformanceStateInput | null,
  technical?: PerformanceStateInput | null,
  legacy: LegacyPerformanceStateInput[] = [],
): PerformanceTab {
  const interviewOfficial = hasOfficialScore(interview)
  const technicalOfficial = hasOfficialScore(technical)
  if (technicalOfficial && !interviewOfficial) return "coding"
  if (interviewOfficial) return "interview"

  const interviewEvidence = hasRecordedEvidence(interview)
  const technicalEvidence = hasRecordedEvidence(technical)
  if (technicalEvidence && !interviewEvidence) return "coding"
  if (interviewEvidence) return "interview"

  const hasLegacyInterview = legacy.some((item) => item.mode === "interview")
  const hasLegacyTechnical = legacy.some((item) => item.mode === "technical")
  if (hasLegacyTechnical && !hasLegacyInterview) return "coding"
  if (hasLegacyInterview) return "interview"

  const interviewState = hasSessionState(interview)
  const technicalState = hasSessionState(technical)
  if (technicalState && !interviewState) return "coding"
  return "interview"
}

export function performanceStateNotice(
  payload: PerformanceStateInput | null | undefined,
  mode: PerformanceTab,
): string | null {
  switch (payload?.score_state) {
    case "processing":
      return "This round is still being analyzed. Performance refreshes automatically when the evidence-backed report is ready."
    case "blocked":
      return "This round is queued, but the analysis worker is not currently available."
    case "failed":
      return "This round could not be analyzed. Retry analysis to continue processing its saved evidence."
    case "run_only":
      if (payload.has_official_score) {
        return mode === "coding"
          ? "Your latest code run or draft was saved without Final Submit. Your previous official Technical score is shown separately."
          : "Your latest round contains draft evidence without an official score. Your previous official interview score is shown separately."
      }
      return mode === "coding"
        ? "Your code run and draft are saved. Only Final Submit creates an official Technical Round score."
        : "This round contains draft evidence, but no official interview score was finalized."
    case "insufficient":
      if (payload.has_official_score) {
        return payload.has_evidence
          ? "Your latest round saved evidence, but not enough for a new official score. Your previous official score is shown separately."
          : "Your latest completed round did not capture enough candidate evidence for a new official score. Your previous official score is shown separately."
      }
      return payload.has_evidence
        ? "Evidence was saved, but this round did not contain enough gradable evidence for an official score."
        : "This completed round did not capture enough candidate evidence to calculate an official score."
    case "legacy":
      return "This is an older report score. It is preserved for reference but excluded from current readiness and trends."
    default:
      return null
  }
}
