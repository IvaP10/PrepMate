"use client"

import { useEffect, useRef, useState } from "react"

export type SessionControlLockState = "checking" | "owned" | "blocked"

const FALLBACK_LEASE_MS = 45_000
const FALLBACK_HEARTBEAT_MS = 5_000

function newOwnerId() {
  return typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `session-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function useSessionControlLock(sessionId: string): SessionControlLockState {
  const [state, setState] = useState<SessionControlLockState>("checking")
  const ownerRef = useRef(newOwnerId())

  useEffect(() => {
    if (!sessionId || typeof window === "undefined") return
    let active = true
    let releaseNavigatorLock: (() => void) | null = null
    let heartbeat: ReturnType<typeof setInterval> | null = null
    let retryTimer: ReturnType<typeof setInterval> | null = null
    const lockName = `interai-session-control:${sessionId}`
    const lockManager = (navigator as Navigator & { locks?: LockManager }).locks

    const holdNavigatorLock = async () => {
      if (!active) return
      setState("owned")
      await new Promise<void>((resolve) => {
        releaseNavigatorLock = resolve
      })
    }

    const startNavigatorLock = async () => {
      let acquiredImmediately = false
      if (!lockManager) return
      await lockManager.request(lockName, { ifAvailable: true }, async (lock) => {
        if (!lock || !active) return
        acquiredImmediately = true
        await holdNavigatorLock()
      })
      if (!active || acquiredImmediately) return
      setState("blocked")
      await lockManager.request(lockName, async () => {
        await holdNavigatorLock()
      })
    }

    const storageKey = `interai-session-control:${sessionId}`
    const owner = ownerRef.current
    const readLease = () => {
      try {
        return JSON.parse(window.localStorage.getItem(storageKey) || "null") as { owner?: string; expiresAt?: number } | null
      } catch {
        return null
      }
    }
    const writeLease = () => {
      window.localStorage.setItem(storageKey, JSON.stringify({ owner, expiresAt: Date.now() + FALLBACK_LEASE_MS }))
    }
    const tryFallbackLease = () => {
      const current = readLease()
      if (current?.owner && current.owner !== owner && Number(current.expiresAt || 0) > Date.now()) {
        setState("blocked")
        return false
      }
      try {
        writeLease()
        const confirmed = readLease()?.owner === owner
        setState(confirmed ? "owned" : "blocked")
        return confirmed
      } catch {
        // If storage is unavailable, the backend WebSocket/session guards
        // remain authoritative; do not dead-end the candidate.
        setState("owned")
        return true
      }
    }
    const startFallbackLease = () => {
      if (tryFallbackLease()) {
        heartbeat = setInterval(() => {
          if (readLease()?.owner === owner) writeLease()
          else setState("blocked")
        }, FALLBACK_HEARTBEAT_MS)
      }
      retryTimer = setInterval(() => {
        const lease = readLease()
        if (lease?.owner === owner) return
        if (!lease || Number(lease.expiresAt || 0) <= Date.now()) {
          if (tryFallbackLease() && !heartbeat) {
            heartbeat = setInterval(() => {
              if (readLease()?.owner === owner) writeLease()
              else setState("blocked")
            }, FALLBACK_HEARTBEAT_MS)
          }
        }
      }, FALLBACK_HEARTBEAT_MS)
      const onStorage = (event: StorageEvent) => {
        if (event.key !== storageKey) return
        if (readLease()?.owner === owner) return
        if (!readLease() || Number(readLease()?.expiresAt || 0) <= Date.now()) {
          tryFallbackLease()
        } else {
          setState("blocked")
        }
      }
      window.addEventListener("storage", onStorage)
      return () => window.removeEventListener("storage", onStorage)
    }

    let stopFallback: (() => void) | undefined
    if (lockManager) {
      void startNavigatorLock()
    } else {
      stopFallback = startFallbackLease()
    }

    return () => {
      active = false
      releaseNavigatorLock?.()
      if (heartbeat) clearInterval(heartbeat)
      if (retryTimer) clearInterval(retryTimer)
      stopFallback?.()
      try {
        if (readLease()?.owner === owner) window.localStorage.removeItem(storageKey)
      } catch {
      }
    }
  }, [sessionId])

  return state
}
