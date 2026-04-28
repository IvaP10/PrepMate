"use client"
import { useState, useEffect, useRef } from "react"
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
  }
}
interface AuthScreenProps {
  onLogin: (user: AuthUser) => void
  onBack: () => void
  theme?: "light" | "dark"
  verified?: boolean
}
const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || ""
export function AuthScreen({ onLogin, onBack, theme = "dark", verified = false }: AuthScreenProps) {
  const [isLoading, setIsLoading] = useState(false)
  const [name, setName] = useState("")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [showPassword, setShowPassword] = useState(false)
  const [mode, setMode] = useState<"login" | "signup" | "forgot_password">("login")
  const [error, setError] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)
  const googleBtnRef = useRef<HTMLDivElement>(null)
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
  const initializeGoogleAuth = () => {
    if (!window.google || !googleBtnRef.current) return
    window.google.accounts.id.initialize({
      client_id: GOOGLE_CLIENT_ID,
      callback: handleGoogleCredentialResponse,
    })
    window.google.accounts.id.renderButton(googleBtnRef.current, {
      theme: theme === "dark" ? "filled_black" : "outline",
      size: "large",
      width: googleBtnRef.current.offsetWidth,
      text: "continue_with",
      shape: "rectangular",
    })
  }
  useEffect(() => {
    if (window.google && googleBtnRef.current) {
      initializeGoogleAuth()
    }
  }, [theme])
  const handleGoogleCredentialResponse = async (response: any) => {
    if (!response.credential) {
      setError("Google authentication failed — no credential received")
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
  }
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
    <div className="relative flex min-h-screen bg-background">
      <div className="relative hidden flex-1 items-center justify-center overflow-hidden border-r border-border bg-card lg:flex">
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            opacity: theme === "dark" ? 0.02 : 0.06,
            backgroundImage:
              theme === "dark"
                ? "linear-gradient(rgba(255,255,255,0.4) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.4) 1px, transparent 1px)"
                : "radial-gradient(circle at 1px 1px, rgba(0,0,0,0.06) 1px, transparent 0)",
            backgroundSize: theme === "dark" ? "80px 80px" : "32px 32px",
          }}
        />
        <div
          className="pointer-events-none absolute top-1/2 left-1/2 h-[500px] w-[500px] -translate-x-1/2 -translate-y-1/2 rounded-full"
          style={{
            background:
              theme === "dark"
                ? "radial-gradient(circle, rgba(37,99,235,0.06) 0%, rgba(59,130,246,0.03) 50%, transparent 70%)"
                : "radial-gradient(circle, rgba(37,99,235,0.06) 0%, transparent 70%)",
          }}
        />
        <div className="relative z-10 flex max-w-md flex-col items-center px-12 text-center">
          <div className="mb-6 flex items-center gap-1.5">
            <ThemeLogo size={40} />
            <span className="text-shimmer text-2xl font-bold">InterAI</span>
          </div>
          <p className="mt-4 leading-relaxed text-muted-foreground">
            Upload your professional resume, conduct simulated interviews at your convenience,
            and receive actionable insights to refine your performance before your next opportunity.
          </p>
          <div className="mt-10 flex flex-wrap justify-center gap-2">
            {["Resume Parsing", "Personalized Questions", "Score Tracking"].map(
              (item) => (
                <span
                  key={item}
                  className="rounded-full border border-border bg-secondary px-3 py-1.5 text-xs font-medium text-muted-foreground"
                >
                  {item}
                </span>
              )
            )}
          </div>
        </div>
      </div>
      <div className="flex flex-1 flex-col items-center justify-center px-6 py-12">
        <div className="absolute top-6 left-6">
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
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center justify-center gap-1.5 lg:hidden">
            <ThemeLogo size={36} />
            <span className="text-shimmer text-xl font-bold">InterAI</span>
          </div>
          <div className="mb-8 text-center lg:text-left">
            <h1 className="text-2xl font-bold tracking-tight text-foreground">
              {mode === "login" ? "Welcome back" : mode === "signup" ? "Create an account" : "Reset password"}
            </h1>
            <p className="mt-2 text-sm text-muted-foreground">
              {mode === "login"
                ? "Sign in to continue your professional interview preparation"
                : mode === "signup"
                  ? "Start your journey with our advanced AI interview platform"
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
          <div className="mb-6">
            <div
              ref={googleBtnRef}
              className="flex h-11 w-full items-center justify-center"
            />
            {!GOOGLE_CLIENT_ID && (
              <Button
                type="button"
                variant="outline"
                className="h-11 w-full border-border bg-card text-foreground hover:bg-secondary"
                disabled
              >
                <svg className="mr-2 h-4 w-4" viewBox="0 0 24 24">
                  <path
                    d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"
                    fill="#4285F4"
                  />
                  <path
                    d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                    fill="#34A853"
                  />
                  <path
                    d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                    fill="#FBBC05"
                  />
                  <path
                    d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                    fill="#EA4335"
                  />
                </svg>
                Google OAuth not configured
              </Button>
            )}
          </div>
          <div className="relative mb-6 flex items-center gap-4">
            <div className="h-px flex-1 bg-border" />
            <span className="text-xs text-muted-foreground">or continue with email</span>
            <div className="h-px flex-1 bg-border" />
          </div>
          <form onSubmit={handleSubmit} className="flex flex-col gap-5">
            {mode === "signup" && (
              <div className="flex flex-col gap-2">
                <Label htmlFor="name" className="text-xs font-medium text-muted-foreground">
                  Full Name
                </Label>
                <Input
                  id="name"
                  type="text"
                  placeholder="Your full name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="h-11 border-border bg-card text-foreground placeholder:text-muted-foreground/60 focus-visible:border-primary focus-visible:ring-primary/20"
                  required
                  disabled={isLoading}
                />
              </div>
            )}
            <div className="flex flex-col gap-2">
              <Label htmlFor="email" className="text-xs font-medium text-muted-foreground">
                Email address
              </Label>
              <Input
                id="email"
                type="email"
                placeholder="you@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="h-11 border-border bg-card text-foreground placeholder:text-muted-foreground/60 focus-visible:border-primary focus-visible:ring-primary/20"
                required
                disabled={isLoading}
              />
            </div>
            {mode !== "forgot_password" && (
              <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <Label htmlFor="password" className="text-xs font-medium text-muted-foreground">
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
                    className="h-11 border-border bg-card pr-10 text-foreground placeholder:text-muted-foreground/60 focus-visible:border-primary focus-visible:ring-primary/20"
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
              </div>
            )}
            <Button
              type="submit"
              disabled={isLoading}
              className="h-11 w-full bg-primary font-semibold text-primary-foreground hover:bg-primary/90"
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
                }}
                className="font-medium text-primary hover:text-primary/80"
              >
                {mode === "login" ? "Sign up" : "Sign in"}
              </button>
            </p>
          </div>
          <p className="mt-6 text-center text-[11px] text-muted-foreground/60">
            {"By continuing, you agree to InterAI's Terms of Service & Privacy Policy."}
          </p>
        </div>
      </div>
    </div>
  )
}
