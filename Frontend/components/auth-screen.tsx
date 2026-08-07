"use client"
import { useState, useEffect, useRef, useCallback } from "react"
import Link from "next/link"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Loader2, Eye, EyeOff, ArrowLeft, AlertCircle, CheckCircle2 } from "lucide-react"
import { ThemeLogo } from "@/components/theme-logo"
import { login, signup, googleAuth, type AuthUser } from "@/lib/auth"
declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: any) => void
          renderButton: (element: HTMLElement, config: any) => void
          prompt: () => void
        }
      }
    }
    __interaiGoogleInitialized?: boolean
    __interaiHandleGoogleCredential?: (response: any) => void
  }
}
interface AuthScreenProps {
  onLogin: (user: AuthUser) => void
  onBack: () => void
  theme?: "light" | "dark"
  verified?: boolean
  initialMode?: "login" | "signup"
}
const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || ""
export function AuthScreen({ onLogin, onBack, theme = "dark", verified = false, initialMode = "login" }: AuthScreenProps) {
  const [isLoading, setIsLoading] = useState(false)
  const [name, setName] = useState("")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)
  const [mode, setMode] = useState<"login" | "signup" | "forgot_password">(initialMode)
  const [error, setError] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)
  const googleBtnRef = useRef<HTMLDivElement>(null)
  const passwordRequirementMessage = "Use at least 8 characters with uppercase, lowercase, a number, and a special character."
  const isSignupPasswordValid = (value: string) =>
    value.length >= 8 &&
    /[a-z]/.test(value) &&
    /[A-Z]/.test(value) &&
    /\d/.test(value) &&
    /[!@#$%^&*()_+\-=[\]{}|;:'",.<>?/`~\\]/.test(value)
  const inputClassName = "h-12 rounded-md border-border/80 bg-background/75 text-foreground shadow-none placeholder:text-muted-foreground/45 focus-visible:border-primary focus-visible:ring-primary/20"
  const labelClassName = "text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground"

  const handleGoogleCredentialResponse = useCallback(async (response: any) => {
    if (!response.credential) {
      setError("Google authentication failed: no credential received")
      return
    }
    setIsLoading(true)
    setError(null)
    setSuccessMessage(null)
    try {
      const result = await googleAuth(response.credential)
      onLogin(result.user)
    } catch (err) {
      const message = err instanceof Error ? err.message : "Google authentication failed"
      setError(message)
    } finally {
      setIsLoading(false)
    }
  }, [onLogin])

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) return
    window.__interaiHandleGoogleCredential = handleGoogleCredentialResponse
    return () => {
      if (window.__interaiHandleGoogleCredential === handleGoogleCredentialResponse) {
        window.__interaiHandleGoogleCredential = undefined
      }
    }
  }, [handleGoogleCredentialResponse])

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) return
    const scriptId = "google-gsi-script"
    if (document.getElementById(scriptId)) {
      initializeGoogleAuth()
      return
    }
    const script = document.createElement("script")
    script.id = scriptId
    script.src = "https://accounts.google.com/gsi/client"
    script.async = true
    script.defer = true
    script.onload = () => initializeGoogleAuth()
    document.head.appendChild(script)
  }, [])
  const renderGoogleButton = () => {
    if (!window.google || !googleBtnRef.current) return
    googleBtnRef.current.innerHTML = ""
    window.google.accounts.id.renderButton(googleBtnRef.current, {
      theme: theme === "dark" ? "filled_black" : "outline",
      size: "large",
      width: googleBtnRef.current.offsetWidth,
      text: "continue_with",
      shape: "rectangular",
    })
  }

  const initializeGoogleAuth = () => {
    if (!window.google) return
    if (!window.__interaiGoogleInitialized) {
      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: (response: any) => window.__interaiHandleGoogleCredential?.(response),
      })
      window.__interaiGoogleInitialized = true
    }
    renderGoogleButton()
  }

  useEffect(() => {
    if (window.google && googleBtnRef.current) {
      renderGoogleButton()
    }
  }, [theme])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsLoading(true)
    setError(null)
    setSuccessMessage(null)
    try {
      if (mode === "signup") {
        if (!name.trim()) {
          setError("Please enter your name")
          setIsLoading(false)
          return
        }
        if (!isSignupPasswordValid(password)) {
          setError(passwordRequirementMessage)
          setIsLoading(false)
          return
        }
        if (password !== confirmPassword) {
          setError("Passwords do not match.")
          setIsLoading(false)
          return
        }
        const result = await signup(name, email, password)
        if (result.token) {
          onLogin(result.user)
        } else {
          setSuccessMessage(result.message)
          setTimeout(() => {
            setMode("login")
          }, 100)
        }
      } else if (mode === "forgot_password") {
        const { forgotPassword } = await import("@/lib/auth")
        const result = await forgotPassword(email)
        setSuccessMessage(result.message)
      } else {
        const result = await login(email, password)
        onLogin(result.user)
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Authentication failed"
      setError(message)
    } finally {
      setIsLoading(false)
    }
  }
  return (
    <div className="relative flex min-h-screen overflow-hidden bg-transparent text-foreground">
      <div className="absolute top-6 left-6 z-20">
        <Button
          variant="ghost"
          size="sm"
          onClick={onBack}
          className="text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="mr-1.5 h-4 w-4" />
          Back
        </Button>
      </div>
      <div className="relative hidden flex-1 items-center justify-center overflow-hidden border-r border-border/65 bg-transparent lg:flex">
        <div className="relative z-10 flex max-w-md flex-col items-center px-12 text-center">
          <div className="mb-8 flex items-center gap-1.5">
            <ThemeLogo size={40} />
            <span className="text-2xl font-bold text-foreground">InterAI</span>
          </div>
          <div className="mb-8 grid w-full grid-cols-2 gap-3 text-left">
            {["Signal Map", "Question Model", "Score Trace", "Prep Loop"].map((item) => (
              <div key={item} className="rounded-md border border-border/80 bg-card/70 p-3 backdrop-blur-lg">
                <span className="text-[10px] font-bold uppercase tracking-[0.18em] text-primary">
                  {item}
                </span>
              </div>
            ))}
          </div>
          <p className="leading-relaxed text-muted-foreground">
            Upload your professional resume, conduct simulated interviews at your convenience,
            and receive actionable insights to refine your performance before your next opportunity.
          </p>
        </div>
      </div>
      <div className="relative z-10 flex flex-1 flex-col items-center justify-center px-6 py-12">
        <div className="w-full max-w-[420px] rounded-xl border border-border/70 bg-card/72 p-6 backdrop-blur-xl sm:p-8">
          <div className="mb-8 flex items-center justify-center gap-1.5 lg:hidden">
            <ThemeLogo size={36} />
            <span className="text-xl font-bold text-foreground">InterAI</span>
          </div>
          <div className="mb-8 text-center lg:text-left">
            <h1 className="text-2xl font-bold tracking-tight text-foreground">
              {mode === "login" ? "Welcome back" : mode === "signup" ? "Create an account" : "Reset password"}
            </h1>
            <p className="mt-2 text-sm text-muted-foreground">
              {mode === "login"
                ? "Sign in to continue your professional interview preparation"
                : mode === "signup"
                  ? "Create your account by 31 August 2026 to get Premium free for 30 days"
                  : "Enter your email to receive a secure password reset link"}
            </p>
          </div>
          {error && (
            <div className="mb-4 flex items-center gap-2 rounded-lg border border-red-500/20 bg-red-500/10 p-3 text-sm text-red-600 dark:text-red-400">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <p>{error}</p>
            </div>
          )}
          {successMessage && (
            <div className="mb-4 rounded-lg border border-green-500/20 bg-green-500/10 p-3 text-sm text-green-600 dark:text-green-400">
              <p>{successMessage}</p>
            </div>
          )}
          {verified && !successMessage && !error && (
            <div className="mb-4 flex items-center gap-2 rounded-lg border border-green-500/20 bg-green-500/10 p-3 text-sm text-green-600 dark:text-green-400">
              <CheckCircle2 className="h-4 w-4 shrink-0" />
              <p>Email verified successfully! You can now sign in.</p>
            </div>
          )}
          {GOOGLE_CLIENT_ID && (
            <div
              ref={googleBtnRef}
              className="mb-6 flex min-h-11 w-full items-center justify-center"
            />
          )}
          {GOOGLE_CLIENT_ID && (
            <div className="relative mb-6 flex items-center gap-4">
              <div className="h-px flex-1 bg-border" />
              <span className="text-xs text-muted-foreground">or continue with email</span>
              <div className="h-px flex-1 bg-border" />
            </div>
          )}
          <form onSubmit={handleSubmit} className="flex flex-col gap-5">
            {mode === "signup" && (
              <div className="flex flex-col gap-2">
                <Label htmlFor="name" className={labelClassName}>
                  Full Name
                </Label>
                <Input
                  id="name"
                  type="text"
                  placeholder="Your full name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className={inputClassName}
                  required
                  disabled={isLoading}
                />
              </div>
            )}
            <div className="flex flex-col gap-2">
              <Label htmlFor="email" className={labelClassName}>
                Email address
              </Label>
              <Input
                id="email"
                type="email"
                placeholder="you@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className={inputClassName}
                required
                disabled={isLoading}
              />
            </div>
            {mode !== "forgot_password" && (
              <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <Label htmlFor="password" className={labelClassName}>
                    Password
                  </Label>
                  {mode === "login" && (
                    <button
                      type="button"
                      onClick={() => {
                        setMode("forgot_password")
                        setError(null)
                        setSuccessMessage(null)
                      }}
                      className="text-xs text-primary hover:text-primary/80"
                    >
                      Forgot password?
                    </button>
                  )}
                </div>
                <div className="relative">
                  <Input
                    id="password"
                    type={showPassword ? "text" : "password"}
                    placeholder="Enter your password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className={`${inputClassName} pr-10`}
                    required
                    disabled={isLoading}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute top-1/2 right-3 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    aria-label={showPassword ? "Hide password" : "Show password"}
                  >
                    {showPassword ? (
                      <EyeOff className="h-4 w-4" />
                    ) : (
                      <Eye className="h-4 w-4" />
                    )}
                  </button>
                </div>
                {mode === "signup" && (
                  <p className="text-xs leading-5 text-muted-foreground">
                    {passwordRequirementMessage}
                  </p>
                )}
              </div>
            )}
            {mode === "signup" && (
              <div className="flex flex-col gap-2">
                <Label htmlFor="confirm-password" className={labelClassName}>
                  Confirm password
                </Label>
                <div className="relative">
                  <Input
                    id="confirm-password"
                    type={showConfirmPassword ? "text" : "password"}
                    placeholder="Re-enter your password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    className={`${inputClassName} pr-10`}
                    required
                    disabled={isLoading}
                  />
                  <button
                    type="button"
                    onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                    className="absolute top-1/2 right-3 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    aria-label={showConfirmPassword ? "Hide confirm password" : "Show confirm password"}
                  >
                    {showConfirmPassword ? (
                      <EyeOff className="h-4 w-4" />
                    ) : (
                      <Eye className="h-4 w-4" />
                    )}
                  </button>
                </div>
              </div>
            )}
            <Button
              type="submit"
              disabled={isLoading}
              className="h-12 w-full rounded-md bg-primary font-semibold text-primary-foreground shadow-none hover:bg-primary/90"
            >
              {isLoading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : mode === "login" ? (
                "Sign In"
              ) : mode === "signup" ? (
                "Create Account"
              ) : (
                "Send Reset Link"
              )}
            </Button>
          </form>
          <div className="mt-6 flex flex-col items-center gap-3">
            <p className="text-center text-sm text-muted-foreground">
              {mode === "login"
                ? "Don't have an account? "
                : mode === "signup"
                  ? "Already have an account? "
                  : "Remember your password? "}
              <button
                type="button"
                onClick={() => {
                  setMode(mode === "login" ? "signup" : "login")
                  setError(null)
                  setSuccessMessage(null)
                  setConfirmPassword("")
                }}
                className="font-medium text-primary hover:text-primary/80"
              >
                {mode === "login" ? "Sign up" : "Sign in"}
              </button>
            </p>
          </div>
          <p className="mt-6 text-center text-xs leading-relaxed text-muted-foreground">
            {mode === "signup" ? (
              <>
                By creating an account, you agree to our{" "}
                <Link href="/terms" className="font-medium text-primary hover:underline">
                  Terms of Service
                </Link>{" "}
                and{" "}
                <Link href="/privacy" className="font-medium text-primary hover:underline">
                  Privacy Policy
                </Link>
                .
              </>
            ) : mode === "login" ? (
              <>
                By signing in, you agree to our{" "}
                <Link href="/terms" className="font-medium text-primary hover:underline">
                  Terms of Service
                </Link>{" "}
                and{" "}
                <Link href="/privacy" className="font-medium text-primary hover:underline">
                  Privacy Policy
                </Link>
                .
              </>
            ) : null}
          </p>
        </div>
      </div>
    </div>
  )
}
