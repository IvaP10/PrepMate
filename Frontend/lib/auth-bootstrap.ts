import { verifyToken, getStoredUser, type AuthUser } from "@/lib/auth"

/**
 * Client-side session bootstrap for the `/` SPA shell.
 *
 * Architecture: landing, auth, and dashboard share `/` via React state — there
 * is no separate `/dashboard` route. Server middleware cannot redirect
 * authenticated users without that route, so every mount and bfcache restore
 * must call bootstrapSession() before showing the marketing page.
 */

export type AuthBootstrapResult = {
  user: AuthUser | null
  authenticated: boolean
}

const BOOTSTRAP_TIMEOUT_MS = 8000

/** Verify session via HttpOnly cookie — works even when localStorage is empty. */
export async function bootstrapSession(): Promise<AuthBootstrapResult> {
  const user = await verifyToken()
  return { user, authenticated: user !== null }
}

/** Race verify against a timeout; fall back to cached local profile when offline/slow. */
export async function bootstrapSessionWithFallback(): Promise<AuthBootstrapResult> {
  let timeoutId: ReturnType<typeof setTimeout> | undefined
  try {
    const result = await Promise.race([
      bootstrapSession(),
      new Promise<AuthBootstrapResult>((resolve) => {
        timeoutId = setTimeout(() => {
          const stored = getStoredUser()
          resolve({ user: stored, authenticated: stored !== null })
        }, BOOTSTRAP_TIMEOUT_MS)
      }),
    ])
    return result
  } finally {
    if (timeoutId) clearTimeout(timeoutId)
  }
}
