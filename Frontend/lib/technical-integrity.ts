export const TECHNICAL_INTEGRITY_WARNING_LIMIT = 5

export type AntiCheatRecordResult = {
  success?: boolean
  warning_count?: number
  flagged?: boolean
  threshold?: number
}

export function integrityWarningMessage(base: string, count: number, limit = TECHNICAL_INTEGRITY_WARNING_LIMIT) {
  return `${base} (Warning ${count}/${limit})`
}
