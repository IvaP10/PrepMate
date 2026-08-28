"use client"

import { safeStorageGet, safeStorageSet } from "@/lib/safe-storage"

const RECOVERY_GRACE_KEY = "prepmate-session-recovery-grace-seconds"
const DEFAULT_RECOVERY_GRACE_SECONDS = 60

export function rememberRecoveryGraceSeconds(value: number | null | undefined) {
  const seconds = Number(value)
  if (!Number.isFinite(seconds)) return
  safeStorageSet("session", RECOVERY_GRACE_KEY, String(Math.max(15, Math.min(300, Math.round(seconds)))))
}

export function readRecoveryGraceSeconds() {
  const seconds = Number(safeStorageGet("session", RECOVERY_GRACE_KEY))
  return Number.isFinite(seconds) && seconds >= 15 && seconds <= 300
    ? Math.round(seconds)
    : DEFAULT_RECOVERY_GRACE_SECONDS
}
