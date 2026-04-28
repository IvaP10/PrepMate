"use client"
import { useState, useEffect } from "react"
import { Navbar } from "@/components/landing/navbar"
import { HeroSection } from "@/components/landing/hero-section"
import { ProblemsSection } from "@/components/landing/problems-section"
import { HowItWorksSection } from "@/components/landing/how-it-works-section"
import { ModesSection } from "@/components/landing/modes-section"
import { PricingSection } from "@/components/landing/pricing-section"
import { CtaSection } from "@/components/landing/cta-section"
import { Footer } from "@/components/landing/footer"
import { AuthScreen } from "@/components/auth-screen"
import { ThemeLogo } from "@/components/theme-logo"
import { Dashboard } from "@/components/dashboard"
import { ResumeModal } from "@/components/resume-modal"
import { ResumeProvider } from "@/context/resume-context"
import { PremiumBackground } from "@/components/premium-background"
import { useTheme } from "@/hooks/use-theme"
import { verifyToken, clearAuth, getStoredUser, logout, type AuthUser } from "@/lib/auth"
import { API_CONFIG, API_ENDPOINTS } from "@/lib/config"
import { toast } from "sonner"
type AppView = "landing" | "auth" | "authenticating" | "dashboard"
export default function Home() {
  const [currentView, setCurrentView] = useState<AppView>("landing")
  const [authUser, setAuthUser] = useState<AuthUser | null>(null)
  const [showResumeModal, setShowResumeModal] = useState(false)
  const [emailVerified, setEmailVerified] = useState(false)
  const [scrollProgress, setScrollProgress] = useState(0)
  const [initialTab, setInitialTab] = useState<string | undefined>(undefined)
  const { theme, toggleTheme } = useTheme()
  useEffect(() => {
    if (typeof window === "undefined") return
    const params = new URLSearchParams(window.location.search)
    const verified = params.get("verified")
    if (verified === "true") {
      toast.success("Email verified!", {
        description: "Your email has been verified. You can now sign in.",
      })
      setEmailVerified(true)
      setCurrentView("auth")
      window.history.replaceState({}, "", window.location.pathname)
    } else if (verified === "false") {
      const errorType = params.get("error")
      toast.error("Verification failed", {
        description:
          errorType === "invalid_or_expired_token"
            ? "The verification link is invalid or has expired. Please sign up again."
            : "Something went wrong. Please try again.",
      })
      setCurrentView("auth")
      window.history.replaceState({}, "", window.location.pathname)
    }
    // Read ?tab= param for deep-linking into dashboard sections
    const tab = params.get("tab")
    if (tab) {
      setInitialTab(tab)
      window.history.replaceState({}, "", window.location.pathname)
    }
  }, [])
  useEffect(() => {
    const storedUser = getStoredUser()
    if (storedUser) {
      verifyToken().then((user) => {
        if (user) {
          setAuthUser(user)
          setCurrentView("dashboard")
        }
      })
    }
  }, [])
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
  useEffect(() => {
    if (currentView !== "dashboard" || !authUser) return
    const checkResumeStatus = async () => {
      try {
        const response = await fetch(
          `${API_CONFIG.BASE_URL}${API_ENDPOINTS.PROFILE.ME}`,
          {
            credentials: 'include' as RequestCredentials,
          }
        )
        if (response.ok) {
          const data = await response.json()
          if (!data.profile_completed && !data.resume_text) {
            setShowResumeModal(true)
          }
        }
      } catch {
      }
    }
    checkResumeStatus()
  }, [currentView, authUser])
  const goToAuth = () => setCurrentView("auth")
  const goToLanding = () => setCurrentView("landing")
  const handleLogin = (user: AuthUser) => {
    setAuthUser(user)
    setCurrentView("authenticating")
    setTimeout(() => {
      setCurrentView("dashboard")
    }, 2000)
  }
  const handleLogout = async () => {
    await logout()
    setAuthUser(null)
    setCurrentView("landing")
  }
  if (currentView === "auth") {
    return (
      <>
        <PremiumBackground theme={theme} />
        <AuthScreen onLogin={handleLogin} onBack={goToLanding} theme={theme} verified={emailVerified} />
      </>
    )
  }
  if (currentView === "authenticating") {
    return (
      <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-background">
        <PremiumBackground theme={theme} />
        <div className="animate-blur-in flex flex-col items-center gap-8 relative z-10">
          <div className="animate-float">
            <div className="animate-glow-pulse relative">
              <div className="absolute inset-0 bg-primary/20 blur-3xl rounded-full scale-150"></div>
              <ThemeLogo size={100} className="relative z-10" />
            </div>
          </div>
          <div className="overflow-hidden">
            <span className="animate-fade-in-up delay-300 block text-shimmer text-sm font-medium tracking-[0.3em] uppercase opacity-0">
              Authenticating
            </span>
          </div>
        </div>
      </div>
    )
  }
  if (currentView === "dashboard") {
    return (
      <>
        <PremiumBackground theme={theme} />
        <ResumeProvider userId={authUser?.user_id ?? null}>
          <Dashboard user={authUser} onLogout={handleLogout} theme={theme} onToggleTheme={toggleTheme} onUploadResume={() => setShowResumeModal(true)} initialTab={initialTab as any} />
          <ResumeModal
            open={showResumeModal}
            onClose={() => setShowResumeModal(false)}
          />
        </ResumeProvider>
      </>
    )
  }

  return (
    <div className="relative min-h-screen">
      <div className="scroll-progress" style={{ width: `${scrollProgress}%` }} />
      <PremiumBackground theme={theme} />
      <Navbar
        onLogin={goToAuth}
        onSignUp={goToAuth}
        theme={theme}
        onToggleTheme={toggleTheme}
      />
      <main>
        <HeroSection onGetStarted={goToAuth} />
        <ProblemsSection />
        <HowItWorksSection />
        <ModesSection onGetStarted={goToAuth} />
        <PricingSection onGetStarted={goToAuth} />
        <CtaSection onGetStarted={goToAuth} />
      </main>
      <Footer theme={theme} />
    </div>
  )
}
