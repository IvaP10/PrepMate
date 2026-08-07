"use client"
import { lazy, Suspense, useState, useEffect, useLayoutEffect, useCallback, useRef, type CSSProperties } from "react"
import { Navbar } from "@/components/landing/navbar"
import { AnnouncementBar } from "@/components/landing/announcement-bar"
import { HeroSection } from "@/components/landing/hero-section"

import { HowItWorksSection } from "@/components/landing/how-it-works-section"
import { ModesSection } from "@/components/landing/modes-section"
import { PerformanceSection } from "@/components/landing/performance-section"
import { PricingSection } from "@/components/landing/pricing-section"
import { CtaSection } from "@/components/landing/cta-section"
import { Footer } from "@/components/landing/footer"
import { ThemeLogo } from "@/components/theme-logo"
import { ResumeProvider } from "@/context/resume-context"
import { PremiumBackground } from "@/components/premium-background"
import { useTheme } from "@/hooks/use-theme"
import { logout, getStoredUser, type AuthUser } from "@/lib/auth"
import { bootstrapSessionWithFallback } from "@/lib/auth-bootstrap"
import { safeStorageGet, safeStorageRemove, safeStorageSet } from "@/lib/safe-storage"
import { readImproveTarget } from "@/lib/improve-navigation"
import type { ExactImproveTarget } from "@/lib/api"
import { toast } from "sonner"

type AppView = "checking" | "landing" | "auth" | "dashboard"
type AuthMode = "login" | "signup"

const APP_VIEW_KEY = "interai_app_view"
const AUTH_MODE_KEY = "interai_auth_mode"
const LANDING_NAV_HEIGHT = 64
const ANNOUNCEMENT_BAR_HEIGHT = 40
const LANDING_ANCHOR_GAP = 12
const loadAuthScreen = () =>
  import("@/components/auth-screen").then((module) => ({ default: module.AuthScreen }))
const loadAppShell = () =>
  import("@/components/app-shell").then((module) => ({ default: module.AppShell }))
const LazyAuthScreen = lazy(loadAuthScreen)
const LazyAppShell = lazy(loadAppShell)

function readPersistedAuthMode(): AuthMode {
  if (typeof window === "undefined") return "login"
  return safeStorageGet("session", AUTH_MODE_KEY) === "signup" ? "signup" : "login"
}

function readPersistedAppView(): AppView | null {
  if (typeof window === "undefined") return null
  const saved = safeStorageGet("session", APP_VIEW_KEY)
  if (saved === "landing" || saved === "auth" || saved === "dashboard") return saved
  return null
}

/** Client-only restore — must not run during SSR (causes hydration mismatch). */
function readClientAppState(): { view: AppView; user: AuthUser | null; authMode: AuthMode } {
  const requestedAuth = new URLSearchParams(window.location.search).get("auth")
  if (requestedAuth === "login" || requestedAuth === "signup") {
    return { view: "auth", user: null, authMode: requestedAuth }
  }
  const user = getStoredUser()
  if (user) {
    return { view: "dashboard", user, authMode: "login" }
  }
  const persistedView = readPersistedAppView()
  if (persistedView === "landing" || persistedView === "auth") {
    return { view: persistedView, user: null, authMode: readPersistedAuthMode() }
  }
  if (persistedView === "dashboard") {
    return { view: "landing", user: null, authMode: "login" }
  }
  return { view: "landing", user: null, authMode: "login" }
}

function persistAppView(view: AppView, authMode: AuthMode) {
  if (typeof window === "undefined") return
  if (view === "checking") return
  safeStorageSet("session", APP_VIEW_KEY, view)
  if (view === "auth") {
    safeStorageSet("session", AUTH_MODE_KEY, authMode)
  }
}

function AuthCheckingScreen({ theme }: { theme: "light" | "dark" }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background">
      <PremiumBackground theme={theme} mode="base" />
      <ThemeLogo size={48} className="relative z-10 opacity-60" />
    </div>
  )
}

export default function Home() {
  // Render usable landing content first; client auth restore can promote to dashboard.
  const [currentView, setCurrentView] = useState<AppView>("landing")
  const [authMode, setAuthMode] = useState<AuthMode>("login")
  const [authUser, setAuthUser] = useState<AuthUser | null>(null)
  const [emailVerified, setEmailVerified] = useState(false)
  const [scrollProgress, setScrollProgress] = useState(0)
  const [initialTab, setInitialTab] = useState<string | undefined>(undefined)
  const [initialImproveTarget, setInitialImproveTarget] = useState<ExactImproveTarget | null>(null)
  const [announcementVisible, setAnnouncementVisible] = useState(true)
  const { theme, toggleTheme } = useTheme()
  const currentViewRef = useRef(currentView)
  const bootstrapGenerationRef = useRef(0)
  currentViewRef.current = currentView

  useLayoutEffect(() => {
    const state = readClientAppState()
    if (state.user) void loadAppShell()
    setAuthUser(state.user)
    setAuthMode(state.authMode)
    setCurrentView(state.view)
  }, [])

  const bootstrapAuth = useCallback(async (options?: { silent?: boolean }) => {
    const silent = options?.silent ?? false
    const generation = ++bootstrapGenerationRef.current

    if (!silent) {
      setCurrentView((prev) => {
        if (prev === "dashboard" && getStoredUser()) return prev
        if (prev === "auth") return prev
        if (prev === "landing") return prev
        return "checking"
      })
    }

    const { user, authenticated } = await bootstrapSessionWithFallback()
    if (generation !== bootstrapGenerationRef.current) return

    if (authenticated && user) {
      setAuthUser(user)
      setCurrentView("dashboard")
      return
    }

    setAuthUser(null)
    setCurrentView((prev) => {
      if (prev === "auth") return prev
      return "landing"
    })
  }, [])

  useEffect(() => {
    if (typeof window === "undefined") return

    const params = new URLSearchParams(window.location.search)
    const verified = params.get("verified")
    const requestedAuth = params.get("auth")
    let showAuth = false

    if (verified === "true") {
      toast.success("Email verified!", {
        description: "Your email has been verified. You can now sign in.",
      })
      setEmailVerified(true)
      setAuthMode("login")
      showAuth = true
      window.history.replaceState({}, "", window.location.pathname)
    } else if (verified === "false") {
      const errorType = params.get("error")
      toast.error("Verification failed", {
        description:
          errorType === "invalid_or_expired_token"
            ? "The verification link is invalid or has expired. Please sign up again."
            : "Something went wrong. Please try again.",
      })
      setAuthMode("signup")
      showAuth = true
      window.history.replaceState({}, "", window.location.pathname)
    }

    if (requestedAuth === "login" || requestedAuth === "signup") {
      setAuthMode(requestedAuth)
      showAuth = true
      window.history.replaceState({}, "", window.location.pathname)
    }

    const tab = params.get("tab")
    if (tab) {
      setInitialTab(tab)
      if (tab === "improve") setInitialImproveTarget(readImproveTarget(params))
      window.history.replaceState({}, "", window.location.pathname)
    }

    if (showAuth) {
      setCurrentView("auth")
      return
    }

    const hasCachedUser = Boolean(getStoredUser())
    const viewAfterRestore = readClientAppState().view
    void bootstrapAuth({
      silent: hasCachedUser || viewAfterRestore === "dashboard" || viewAfterRestore === "landing",
    })
  }, [bootstrapAuth])

  useEffect(() => {
    persistAppView(currentView, authMode)
  }, [currentView, authMode])

  useEffect(() => {
    const resyncShellFromStorage = () => {
      const state = readClientAppState()
      setAuthUser(state.user)
      setAuthMode(state.authMode)
      setCurrentView(state.view)
      void bootstrapAuth({ silent: true })
    }

    const onPageShow = (event: PageTransitionEvent) => {
      const view = currentViewRef.current

      if (view === "checking" || event.persisted) {
        resyncShellFromStorage()
        return
      }

      if (view === "auth") return
      void bootstrapAuth({ silent: true })
    }

    window.addEventListener("pageshow", onPageShow)
    return () => window.removeEventListener("pageshow", onPageShow)
  }, [bootstrapAuth])

  useEffect(() => {
    if (currentView !== "landing") return
    const headerHeight = LANDING_NAV_HEIGHT + (announcementVisible ? ANNOUNCEMENT_BAR_HEIGHT : 0)
    document.documentElement.style.scrollPaddingTop = `${headerHeight + LANDING_ANCHOR_GAP}px`

    return () => {
      document.documentElement.style.scrollPaddingTop = ""
    }
  }, [announcementVisible, currentView])

  useEffect(() => {
    if (currentView !== "landing") return
    const onScroll = () => {
      const scrollTop = window.scrollY
      const docHeight = document.documentElement.scrollHeight - window.innerHeight
      setScrollProgress(docHeight > 0 ? (scrollTop / docHeight) * 100 : 0)
    }
    window.addEventListener("scroll", onScroll, { passive: true })
    return () => window.removeEventListener("scroll", onScroll)
  }, [currentView])

  const goToAuth = (mode: AuthMode = "login") => {
    void loadAuthScreen()
    void loadAppShell()
    setAuthMode(mode)
    setCurrentView("auth")
  }
  const goToSignup = () => goToAuth("signup")
  const goToLanding = () => {
    if (authUser) {
      setCurrentView("dashboard")
      return
    }
    setCurrentView("landing")
  }
  const handleLogin = (user: AuthUser) => {
    setAuthUser(user)
    if (typeof window !== "undefined") {
      const requestedTab = (
        initialTab
        && ["improve", "interview", "coding", "technical", "resume", "performance", "analytics", "membership", "settings"].includes(initialTab)
      )
        ? initialTab
        : "interview"
      safeStorageSet("session", "dashboard_tab", requestedTab)
    }
    setCurrentView("dashboard")
  }
  const handleLogout = async () => {
    await logout()
    if (typeof window !== "undefined") {
      safeStorageRemove("session", "dashboard_tab")
      safeStorageRemove("session", APP_VIEW_KEY)
      safeStorageRemove("session", AUTH_MODE_KEY)
    }
    setInitialTab(undefined)
    setInitialImproveTarget(null)
    setAuthUser(null)
    setCurrentView("landing")
  }
  const handleUserUpdate = (updates: Partial<AuthUser>) => {
    setAuthUser((current) => {
      if (!current) return current
      const next = { ...current, ...updates }
      safeStorageSet("local", "interai-user", JSON.stringify(next))
      return next
    })
  }

  if (currentView === "checking") {
    return <AuthCheckingScreen theme={theme} />
  }
  if (currentView === "auth") {
    return (
      <>
        <PremiumBackground theme={theme} mode="base" />
        <Suspense fallback={<AuthCheckingScreen theme={theme} />}>
          <LazyAuthScreen onLogin={handleLogin} onBack={goToLanding} theme={theme} verified={emailVerified} initialMode={authMode} />
        </Suspense>
      </>
    )
  }
  if (currentView === "dashboard") {
    return (
      <Suspense fallback={<AuthCheckingScreen theme={theme} />}>
        <ResumeProvider userId={authUser?.user_id ?? null}>
          <LazyAppShell
            user={authUser}
            onLogout={handleLogout}
            onUserUpdate={handleUserUpdate}
            theme={theme}
            onToggleTheme={toggleTheme}
            initialTab={initialTab}
            initialImproveTarget={initialImproveTarget}
          />
        </ResumeProvider>
      </Suspense>
    )
  }

  return (
    <div
      className={`relative min-h-screen ${theme}`}
      style={{
        color: theme === "dark" ? "#FFFFFF" : "#000000",
        "--foreground": theme === "dark" ? "#FFFFFF" : "#000000",
        "--muted-foreground": theme === "dark" ? "#D4D4D8" : "#000000",
        "--color-foreground": theme === "dark" ? "#FFFFFF" : "#000000",
        "--color-muted-foreground": theme === "dark" ? "#D4D4D8" : "#000000",
        "--landing-header-height": `${LANDING_NAV_HEIGHT + (announcementVisible ? ANNOUNCEMENT_BAR_HEIGHT : 0)}px`,
      } as CSSProperties}
    >
      <div className="scroll-progress" style={{ width: `${scrollProgress}%` }} />
      <PremiumBackground theme={theme} mode="base" />
      <div data-landing-header className="fixed top-0 left-0 right-0 z-50 flex flex-col">
        <Navbar
          onLogin={() => goToAuth("login")}
          onSignUp={goToSignup}
          theme={theme}
          onToggleTheme={toggleTheme}
          announcementVisible={announcementVisible}
        />
        {announcementVisible && (
          <AnnouncementBar onDismiss={() => setAnnouncementVisible(false)} />
        )}
      </div>
      <main className="relative z-10">
        <HeroSection onGetStarted={goToSignup} theme={theme} />
        <HowItWorksSection />
        <ModesSection onGetStarted={goToSignup} />
        <PerformanceSection />
        <PricingSection onGetStarted={goToSignup} />
        <CtaSection onGetStarted={goToSignup} />
      </main>
      <Footer />
    </div>
  )
}
