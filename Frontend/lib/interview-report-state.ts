export type InterviewReportAvailability = "available" | "active" | "recovering" | "incomplete"
export type InterviewQuestionStatus = "Completed" | "Incomplete" | "Unable to Evaluate" | "Not Answered"

export function interviewReportAvailability(
  status?: string | null,
  attemptStatus?: string | null,
): InterviewReportAvailability {
  const normalizedStatus = String(status || "").trim().toLowerCase()
  const normalizedAttempt = String(attemptStatus || "").trim().toLowerCase()

  if (normalizedAttempt === "incomplete" || normalizedStatus === "cancelled") return "incomplete"
  if (normalizedAttempt === "recovering" || normalizedStatus === "recovering") return "recovering"
  if (["in_progress", "uploading"].includes(normalizedStatus)) return "active"
  return "available"
}

export function interviewQuestionResponse(value: Record<string, any>) {
  return String(value.response ?? value.transcript ?? value.user_answer ?? "")
}

export function interviewQuestionStatus(value: Record<string, any>): InterviewQuestionStatus {
  const response = interviewQuestionResponse(value).trim()
  const explicit = String(value.status || "").trim()
  // Older canonical reports omitted status. A captured answer is never
  // "Not Answered" merely because the UI default was used.
  if (explicit === "Not Answered" && response) {
    if (value.insufficient_evidence || value.evidence_status === "insufficient_evidence") return "Incomplete"
    if (typeof value.score === "number" || typeof value.overall_score === "number") return "Completed"
    return "Unable to Evaluate"
  }
  if (explicit === "Completed" || explicit === "Incomplete" || explicit === "Unable to Evaluate" || explicit === "Not Answered") {
    return explicit
  }
  if (!response) return "Not Answered"
  if (value.insufficient_evidence || value.evidence_status === "insufficient_evidence") return "Incomplete"
  if (typeof value.score === "number" || typeof value.overall_score === "number") return "Completed"
  return "Unable to Evaluate"
}
