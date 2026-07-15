import { API_CONFIG, API_ENDPOINTS } from './config'
import { safeStorageGet, safeStorageRemove, safeStorageSet } from './safe-storage'

const USER_KEY = 'interai-user'
const CSRF_COOKIE_NAME = 'interai_csrf'

export interface AuthUser {
    user_id: string
    email: string
    name: string
    interviews_remaining: number
    plan_type?: string
    is_admin?: boolean
    avatar_url?: string
    auth_provider?: string
}

export interface AuthResult {
    token: string
    user: AuthUser
    message: string
}

function cleanValidationMessage(message: string): string {
    return message.replace(/^value error,\s*/i, '').trim()
}

function extractErrorMessage(err: any, fallback: string): string {
    if (!err) return fallback
    const detail = err.detail
    if (typeof detail === 'string') return cleanValidationMessage(detail)
    if (Array.isArray(detail)) {
        const messages = detail.map((d: any) => cleanValidationMessage(d.msg || d.message || JSON.stringify(d)))
        return messages.join(', ')
    }
    if (detail && typeof detail === 'object') return cleanValidationMessage(detail.msg || detail.message || fallback)
    if (err.message && typeof err.message === 'string') return cleanValidationMessage(err.message)
    return fallback
}

export function getStoredUser(): AuthUser | null {
    if (typeof window === 'undefined') return null
    const raw = safeStorageGet('local', USER_KEY)
    if (!raw) return null
    try {
        const user = JSON.parse(raw)
        return {
            ...user,
            // Keep the last verified entitlement while the session check is
            // in flight.  Replacing every cached plan with Starter made a
            // valid Pro/Premium session briefly (and sometimes permanently
            // after a transient API failure) look like a free account.
            plan_type: typeof user.plan_type === 'string' && user.plan_type.trim()
                ? user.plan_type
                : 'starter',
            is_admin: false,
        }
    } catch {
        return null
    }
}

function storeUser(user: AuthUser): void {
    safeStorageSet('local', USER_KEY, JSON.stringify(user))
}

export function clearAuth(): void {
    safeStorageRemove('local', USER_KEY)
}

function readCookie(name: string): string {
    if (typeof document === 'undefined') return ''
    const match = document.cookie
        .split('; ')
        .find((part) => part.startsWith(`${name}=`))
    return match ? decodeURIComponent(match.slice(name.length + 1)) : ''
}

export function getAuthHeaders(): Record<string, string> {
    const csrfToken = readCookie(CSRF_COOKIE_NAME)
    return csrfToken ? { 'X-CSRF-Token': csrfToken } : {}
}

export async function login(email: string, password: string): Promise<AuthResult> {
    try {
        const response = await fetch(`${API_CONFIG.BASE_URL}${API_ENDPOINTS.AUTH.LOGIN}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ email, password }),
        })

        if (!response.ok) {
            const err = await response.json().catch(() => null)
            throw new Error(extractErrorMessage(err, 'Login failed'))
        }

        const data = await response.json()
        const user: AuthUser = {
            user_id: data.user_id,
            email: data.email,
            name: data.name,
            interviews_remaining: data.interviews_remaining || 0,
            plan_type: data.plan_type || 'starter',
            is_admin: Boolean(data.is_admin),
        }
        storeUser(user)
        return { token: '', user, message: data.message }
    } catch (error) {
        if (error instanceof TypeError && error.message.includes('fetch')) {
            throw new Error('Cannot connect to server. Make sure the backend is running.')
        }
        throw error
    }
}

export async function signup(name: string, email: string, password: string): Promise<AuthResult> {
    try {
        const response = await fetch(`${API_CONFIG.BASE_URL}${API_ENDPOINTS.AUTH.SIGNUP}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ name, email, password }),
        })

        if (!response.ok) {
            const err = await response.json().catch(() => null)
            throw new Error(extractErrorMessage(err, 'Signup failed'))
        }

        const data = await response.json()
        const user: AuthUser = {
            user_id: data.user_id,
            email: data.email,
            name: data.name,
            interviews_remaining: data.interviews_remaining || 0,
            plan_type: data.plan_type || 'starter',
            is_admin: Boolean(data.is_admin),
        }
        return { token: '', user, message: data.message }
    } catch (error) {
        if (error instanceof TypeError && error.message.includes('fetch')) {
            throw new Error('Cannot connect to server. Make sure the backend is running.')
        }
        throw error
    }
}

export async function googleAuth(googleToken: string): Promise<AuthResult> {
    try {
        const response = await fetch(`${API_CONFIG.BASE_URL}${API_ENDPOINTS.AUTH.GOOGLE}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ google_token: googleToken }),
        })

        if (!response.ok) {
            const err = await response.json().catch(() => null)
            throw new Error(extractErrorMessage(err, 'Google authentication failed'))
        }

        const data = await response.json()
        const user: AuthUser = {
            user_id: data.user_id,
            email: data.email,
            name: data.name,
            interviews_remaining: data.interviews_remaining || 0,
            plan_type: data.plan_type || 'starter',
            is_admin: Boolean(data.is_admin),
        }
        storeUser(user)
        return { token: '', user, message: data.message }
    } catch (error) {
        if (error instanceof TypeError && error.message.includes('fetch')) {
            throw new Error('Cannot connect to server. Make sure the backend is running.')
        }
        throw error
    }
}

export async function verifyToken(): Promise<AuthUser | null> {
    try {
        const response = await fetch(`${API_CONFIG.BASE_URL}${API_ENDPOINTS.AUTH.VERIFY}`, {
            method: 'GET',
            credentials: 'include',
        })

        if (!response.ok) {
            clearAuth()
            return null
        }

        const data = await response.json()
        if (data.valid) {
            const user: AuthUser = {
                user_id: data.user_id,
                email: data.email,
                name: data.name || getStoredUser()?.name || "User",
                interviews_remaining: data.interviews_remaining || 0,
                plan_type: data.plan_type || 'starter',
                is_admin: Boolean(data.is_admin),
            }
            storeUser(user)
            return user
        }

        clearAuth()
        return null
    } catch {
        // Network blip — keep cached profile; don't wipe a valid session locally.
        return getStoredUser()
    }
}

export async function forgotPassword(email: string): Promise<{ message: string }> {
    try {
        const response = await fetch(`${API_CONFIG.BASE_URL}${API_ENDPOINTS.AUTH.FORGOT_PASSWORD}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ email }),
        })

        if (!response.ok) {
            const err = await response.json().catch(() => null)
            throw new Error(extractErrorMessage(err, 'Failed to send reset link'))
        }

        const data = await response.json()
        return { message: data.message }
    } catch (error) {
        if (error instanceof TypeError && error.message.includes('fetch')) {
            throw new Error('Cannot connect to server. Make sure the backend is running.')
        }
        throw error
    }
}

export async function resetPassword(token: string, password: string): Promise<{ message: string }> {
    try {
        const response = await fetch(`${API_CONFIG.BASE_URL}${API_ENDPOINTS.AUTH.RESET_PASSWORD}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ token, password }),
        })

        if (!response.ok) {
            const err = await response.json().catch(() => null)
            throw new Error(extractErrorMessage(err, 'Failed to reset password'))
        }

        const data = await response.json()
        return { message: data.message }
    } catch (error) {
        if (error instanceof TypeError && error.message.includes('fetch')) {
            throw new Error('Cannot connect to server. Make sure the backend is running.')
        }
        throw error
    }
}

export async function logout(): Promise<void> {
    try {
        await fetch(`${API_CONFIG.BASE_URL}${API_ENDPOINTS.AUTH.LOGOUT}`, {
            method: 'POST',
            headers: {
                ...getAuthHeaders(),
            },
            credentials: 'include',
        })
    } catch {
    } finally {
        clearAuth()
    }
}
