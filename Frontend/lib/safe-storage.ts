"use client"

type StorageKind = "local" | "session"

function getStorage(kind: StorageKind): Storage | null {
  if (typeof window === "undefined") return null
  try {
    const storage = kind === "local" ? window.localStorage : window.sessionStorage
    return storage || null
  } catch {
    return null
  }
}

export function safeStorageGet(kind: StorageKind, key: string): string | null {
  try {
    return getStorage(kind)?.getItem(key) ?? null
  } catch {
    return null
  }
}

export function safeStorageSet(kind: StorageKind, key: string, value: string): void {
  try {
    getStorage(kind)?.setItem(key, value)
  } catch {
  }
}

export function safeStorageRemove(kind: StorageKind, key: string): void {
  try {
    getStorage(kind)?.removeItem(key)
  } catch {
  }
}
