export type SelfReviewSignalResult = {
  success?: boolean
  warning_count?: number
  flagged?: boolean
  threshold?: number | null
  mode?: "self_review" | string
}
