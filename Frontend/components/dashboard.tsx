"use client"
import { useState, useEffect } from "react"
import { useRouter } from "next/navigation"
import { ThemeLogo } from "@/components/theme-logo"
import {
  LayoutDashboard,
  Mic,
  FileText,
  BarChart3,
  Settings,
  User,
  LogOut,
  Zap,
  Sun,
  Moon,
  AlertCircle,
  Upload,
  Mail,
  Phone,
  Linkedin,
  Globe,
  GraduationCap,
  Briefcase,
  Code,
  Award,
  Languages,
  Heart,
  X,
  Check,
  Edit3,
  Save,
  Play,
  Timer,
  MessageSquare,
  AlertTriangle,
  Trash2,
  CreditCard,
  Sliders,
  Eye,
  Loader2,
  Bug,
  MessageCircle,
  Send,
  Gift,
  Star,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import { toast } from "sonner"
import { Slider } from "@/components/ui/slider"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog"
import { AuthUser } from "@/lib/auth"
import {
  PRICE_PER_CREDIT,
  CURRENCY_SYMBOL,
  MAX_CREDITS,
  MIN_CREDITS,
  MAX_DISCOUNT_PERCENT,
  calculatePricing,
} from "@/lib/pricing"
import { PremiumBackground } from "./premium-background"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  uploadResume,
  submitResume,
  startInterviewSession,
  createPaymentSession,
  createSupportSubmission,
  fetchPaymentTransactions,
} from "@/lib/api"
import { useResume } from "@/context/resume-context"
import type { ResumeData } from "@/types/resume"
interface DashboardProps {
  onLogout: () => void
  theme?: "light" | "dark"
  onToggleTheme?: () => void
  onUploadResume?: () => void
  user?: AuthUser | null
  initialTab?: ActiveNav
}
type ActiveNav = "dashboard" | "interview" | "resume" | "analytics" | "settings"
const navItems: { icon: any; label: string; id: ActiveNav }[] = [
  { icon: LayoutDashboard, label: "Dashboard", id: "dashboard" },
  { icon: Play, label: "Interview", id: "interview" },
  { icon: FileText, label: "Profile", id: "resume" },
  { icon: BarChart3, label: "Analytics", id: "analytics" },
  { icon: Settings, label: "Settings", id: "settings" },
]
interface DashboardResumeData {
  fullName: string
  email: string
  phone: string
  linkedin: string
  github: string
  portfolio: string
  targetRole: string
  summary: string
  education: { institution: string; degree: string; major: string; graduationYear: string; cgpa: string }[]
  experience: { title: string; company: string; dates: string; description: string }[]
  projects: { name: string; techStack: string; description: string }[]
  technicalSkills: string
  softSkills: string
  certifications: string
  achievements: string
  languages: string
  interests: string
}
export interface PastInterview {
  id: number | string
  date: string
  role: string
  type: "Full" | "Quick" | string
  score: number
}
export interface DashboardMetrics {
  coachingMetrics: Record<string, { score: number; label: string; insight: string }>
  primaryFocus: {
    title: string
    reason: string
    action: string
    interviewer_signal: string
    project_anchor: string
  } | null
  studentSummary: {
    headline: string
    blocker: string
    next_step: string
    interviewer_signal: string
    proof_point: string
  } | null
  averageScore: number | null
  totalInterviews: number
}
export interface UserCredits {
  availableSessions: number | string
}
const defaultMetrics: DashboardMetrics = {
  coachingMetrics: {},
  primaryFocus: null,
  studentSummary: null,
  averageScore: null,
  totalInterviews: 0,
}
const defaultCredits: UserCredits = {
  availableSessions: 0,
}
function mapResumeDataToDashboard(data: ResumeData): DashboardResumeData {
  return {
    fullName: data.fullName || "",
    email: data.email || "",
    phone: data.phoneNumber || "",
    linkedin: data.linkedinUrl || "",
    github: data.githubUrl || "",
    portfolio: data.portfolioUrl || "",
    targetRole: data.targetRole || "",
    summary: data.professionalSummary || data.summary || "",
    education: (data.education || []).map((edu) => ({
      institution: edu.institution || "",
      degree: edu.degree || "",
      major: edu.field || "",
      graduationYear: edu.endYear?.toString() || "",
      cgpa: edu.gpa?.toString() || "",
    })),
    experience: (data.experiences || []).map((exp) => ({
      title: exp.position || "",
      company: exp.company || "",
      dates: [exp.startDate, exp.isCurrent ? "Present" : exp.endDate].filter(Boolean).join(" - "),
      description: exp.description || "",
    })),
    projects: (data.projects || []).map((proj) => ({
      name: proj.name || "",
      techStack: (proj.technologies || []).join(", "),
      description: proj.description || "",
    })),
    technicalSkills: (data.skills || []).map((s) => s.name).join(", "),
    softSkills: "",
    certifications: (data.certifications || []).map((c) => c.name).join("\n"),
    achievements: "",
    languages: (data.languages || []).map((l) => l.name).join(", "),
    interests: "",
  }
}
const emptyResumeData: DashboardResumeData = {
  fullName: "",
  email: "",
  phone: "",
  linkedin: "",
  github: "",
  portfolio: "",
  targetRole: "",
  summary: "",
  education: [],
  experience: [],
  projects: [],
  technicalSkills: "",
  softSkills: "",
  certifications: "",
  achievements: "",
  languages: "",
  interests: "",
}
const PRICE_PER_SESSION = 200
export { DashboardContent, InterviewContent, ResumeContent }
function DashboardContent({ onOpenPricing, metrics = defaultMetrics, credits, setActiveNav }: { onOpenPricing: () => void; metrics?: DashboardMetrics; credits?: UserCredits; setActiveNav: (nav: ActiveNav) => void }) {
  const hasData = Object.keys(metrics.coachingMetrics || {}).length > 0
  const router = useRouter()
  const PRICE_PER_SESSION = 199

  const quickBuyOptions = [
    { credits: 5, label: "Starter", price: 5 * PRICE_PER_SESSION },
    { credits: 10, label: "Popular", price: 10 * PRICE_PER_SESSION, badge: "Best Value" },
    { credits: 25, label: "Pro Pack", price: 25 * PRICE_PER_SESSION },
  ]

  const metricCards = [
    {
      key: "interview_readiness",
      title: "Interview Readiness",
      icon: Play,
      accent: "text-primary",
    },
    {
      key: "answer_clarity",
      title: "Answer Clarity",
      icon: MessageSquare,
      accent: "text-cyan-500",
    },
    {
      key: "technical_depth",
      title: "Technical Depth",
      icon: Code,
      accent: "text-emerald-500",
    },
    {
      key: "proof_of_work",
      title: "Proof of Work",
      icon: Award,
      accent: "text-amber-500",
    },
  ]

  return (
    <div className="flex-1 overflow-y-auto p-6 md:p-8 animate-fade-in-up">
      <div className="mb-6 overflow-hidden rounded-2xl border border-border/40 bg-card p-6 md:p-8 shadow-sm">
        <div className="flex items-start gap-5">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-secondary text-primary ring-1 ring-border/50">
            <Play className="h-5 w-5" />
          </div>
          <div>
            <h2 className="text-xl font-semibold tracking-tight text-foreground">
              {hasData ? (metrics.studentSummary?.headline || "Your coaching dashboard is ready") : "Start with one mock to unlock real coaching"}
            </h2>
            <p className="mt-1.5 text-sm text-muted-foreground/90 leading-relaxed">
              {hasData
                ? (metrics.studentSummary?.interviewer_signal || "Your recent interviews now have enough signal to show what interviewers are likely noticing.")
                : "Complete an interview session first. The dashboard will then convert your answers, follow-ups, and proof points into coaching you can actually use."
              }
            </p>
          </div>
        </div>
      </div>
      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {metricCards.map((card) => {
          const value = metrics.coachingMetrics?.[card.key]
          return (
            <div key={card.key} className="group relative overflow-hidden rounded-2xl border border-border/40 bg-card/40 p-5 transition-all duration-300 hover:bg-card hover:shadow-md hover:border-border/60">
              <div className="mb-4 flex items-center justify-between">
                <span className="text-xs font-medium text-muted-foreground tracking-wide uppercase">{card.title}</span>
                <div className={`flex h-8 w-8 items-center justify-center rounded-xl bg-secondary ring-1 ring-border/50 transition-transform duration-500 group-hover:scale-105 ${card.accent}`}>
                  <card.icon className="h-4 w-4" />
                </div>
              </div>
              <p className="text-2xl font-semibold tracking-tight text-foreground">
                {value ? `${Math.round(value.score)}%` : "—"}
              </p>
              <p className="mt-1.5 text-[13px] text-muted-foreground">
                {value?.insight || "Complete an interview to unlock this coaching score."}
              </p>
            </div>
          )
        })}
      </div>

      <div className="mb-6 grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
        <div className="rounded-2xl border border-border/40 bg-card p-6 shadow-sm">
          <p className="text-[11px] font-semibold uppercase tracking-[0.25em] text-muted-foreground/70">What Interviewers Notice</p>
          <h3 className="mt-3 text-lg font-semibold text-foreground">
            {metrics.primaryFocus?.title || "No coaching focus yet"}
          </h3>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            {metrics.studentSummary?.blocker || "Run a mock or practice session first so the system can identify your highest-leverage blocker."}
          </p>
          <div className="mt-5 rounded-xl border border-border/50 bg-secondary/20 p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Next practice step</p>
            <p className="mt-2 text-sm leading-6 text-foreground/85">
              {metrics.studentSummary?.next_step || "Your next actionable practice step will appear here after the first interview."}
            </p>
          </div>
        </div>
        <div className="rounded-2xl border border-border/40 bg-card p-6 shadow-sm">
          <p className="text-[11px] font-semibold uppercase tracking-[0.25em] text-muted-foreground/70">Best Proof Point</p>
          <h3 className="mt-3 text-lg font-semibold text-foreground">
            {metrics.primaryFocus?.project_anchor || "Your strongest project"}
          </h3>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            {metrics.studentSummary?.proof_point || "This area will start pointing you to your best story once the system has seen a real interview session."}
          </p>
          {metrics.averageScore !== null && (
            <div className="mt-5 flex items-center justify-between rounded-xl border border-border/50 bg-secondary/20 p-4 text-sm">
              <span className="text-muted-foreground">Average score</span>
              <span className="font-semibold text-foreground">{Math.round(metrics.averageScore)}%</span>
            </div>
          )}
        </div>
      </div>

      <div className="mb-6 flex items-center gap-4">
        <div className="h-px flex-1 bg-border/60" />
        <span className="text-[11px] font-medium uppercase tracking-widest text-muted-foreground/50">Shop</span>
        <div className="h-px flex-1 bg-border/60" />
      </div>

      {/* Credit Shop */}
      <div className="mb-6 overflow-hidden rounded-2xl border border-border/40 bg-card shadow-sm">
        <div className="flex flex-col gap-5 p-6 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-4">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary/10 ring-1 ring-primary/20">
              <CreditCard className="h-5 w-5 text-primary" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-foreground">Interview Credits</h3>
              <p className="text-xs text-muted-foreground">
                You have <span className="font-semibold text-foreground">{credits?.availableSessions ?? 0}</span> {credits?.availableSessions === 'Unlimited' ? '' : 'credits remaining'}
              </p>
            </div>
          </div>
          <Button variant="outline" size="sm" onClick={onOpenPricing} className="gap-1.5 rounded-lg text-xs shrink-0">
            <Sliders className="h-3.5 w-3.5" />
            Custom Amount
          </Button>
        </div>
        <div className="border-t border-border/40 px-6 py-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {quickBuyOptions.map((opt) => (
              <button
                key={opt.credits}
                onClick={() => router.push(`/checkout?sessions=${opt.credits}`)}
                className="group relative flex items-center gap-4 rounded-xl border border-border/50 bg-secondary/20 px-5 py-4 text-left transition-all duration-200 hover:bg-primary/5 hover:border-primary/25 hover:shadow-sm"
              >
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/8 ring-1 ring-primary/15 transition-colors group-hover:bg-primary/15">
                  <Zap className="h-4 w-4 text-primary" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-foreground">{opt.credits} Credits</span>
                    {opt.badge && (
                      <span className="rounded-full bg-primary/10 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-primary">
                        {opt.badge}
                      </span>
                    )}
                  </div>
                  <span className="text-xs text-muted-foreground">{opt.label} · ₹{opt.price.toLocaleString("en-IN")}</span>
                </div>
                <svg className="h-4 w-4 text-muted-foreground/40 transition-transform group-hover:translate-x-0.5 group-hover:text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                </svg>
              </button>
            ))}
          </div>
          <p className="mt-3 text-center text-[11px] text-muted-foreground/60">
            Buy 30+ credits and save 15% · Credits never expire
          </p>
        </div>
      </div>

      <div className="overflow-hidden rounded-2xl border border-border/40 bg-secondary/30 p-6 transition-all duration-300 hover:bg-secondary/40 hover:shadow-sm">
        <div className="flex flex-col items-start justify-between gap-5 md:flex-row md:items-center">
          <div className="flex items-start gap-4">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-card text-foreground ring-1 ring-border/50 shadow-sm">
              <Zap className="h-4 w-4" />
            </div>
            <div>
              <h3 className="font-medium text-foreground">
                {hasData ? "Primary Coaching Focus" : "Get Started"}
              </h3>
              <p className="mt-1.5 text-[13px] text-muted-foreground">
                {hasData
                  ? (metrics.primaryFocus?.action || "Your next coaching recommendation will appear here.")
                  : "Complete your initial practice session to unlock personalized, student-focused recommendations."
                }
              </p>
            </div>
          </div>
          <Button className="shrink-0 gap-2 rounded-full px-6 shadow-sm" onClick={() => setActiveNav("interview")}>
            <Play className="h-3.5 w-3.5" />
            Initiate Practice
          </Button>
        </div>
      </div>
    </div>
  )
}
function InterviewContent({
  onOpenPricing,
  credits = defaultCredits,
  interviews = [],
  setActiveNav
}: {
  onOpenPricing: () => void
  credits?: UserCredits
  interviews?: PastInterview[]
  setActiveNav: (nav: ActiveNav) => void
}) {
  const router = useRouter()
  const [isStartingMock, setIsStartingMock] = useState(false)
  const [isStartingPractice, setIsStartingPractice] = useState(false)
  const [showStartConfirm, setShowStartConfirm] = useState(false)
  const [sessionToStart, setSessionToStart] = useState<'mock' | 'practice' | null>(null)
  const handleStartSession = (mode: 'mock' | 'practice') => {
    setSessionToStart(mode)
    setShowStartConfirm(true)
  }
  const confirmStartSession = async () => {
    if (!sessionToStart) return
    const mode = sessionToStart
    if (mode === 'mock') setIsStartingMock(true)
    else setIsStartingPractice(true)
    try {
      const response = await startInterviewSession(mode, "General")
      const interviewId = response.interview_id || response.session_id
      const urlMode = mode === 'mock' ? 'mock-voice' : 'practice-voice'
      router.push(`/interview/${interviewId}?mode=${urlMode}`)
    } catch (error: any) {
      const msg = error?.message || `Failed to start ${mode} session.`
      if (msg.toLowerCase().includes('no interviews remaining') || msg.toLowerCase().includes('no credits')) {
        toast.error('You have no credits left. Please purchase a plan.')
        onOpenPricing()
      } else {
        toast.error(msg)
      }
    } finally {
      if (mode === 'mock') setIsStartingMock(false)
      else setIsStartingPractice(false)
      setShowStartConfirm(false)
      setSessionToStart(null)
    }
  }
  return (
    <div className="flex-1 overflow-y-auto p-6 md:p-8 animate-fade-in-up">
      <div className="mb-6 flex items-center gap-2 text-sm text-muted-foreground">
        <Zap className="h-4 w-4 text-primary" />
        <span>Available: <strong className="text-foreground">{credits.availableSessions} {credits.availableSessions === 'Unlimited' ? '' : 'Sessions'}</strong></span>
        <Button variant="link" className="h-auto p-0 text-sm text-primary" onClick={onOpenPricing}>
          Get more
        </Button>
      </div>
      <div className="mb-8 grid grid-cols-1 gap-6 md:grid-cols-2">
        <div className="group relative flex flex-col overflow-hidden rounded-2xl border border-border/20 bg-card/30 backdrop-blur-sm transition-all duration-500 hover:bg-card/60 hover:shadow-xl hover:shadow-primary/5 hover:border-border/40">
          <div className="absolute inset-0 bg-gradient-to-br from-cyan-500/5 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-700" />
          <div className="relative flex flex-1 flex-col p-8">
            <span className="mb-6 text-[10px] font-bold uppercase tracking-[0.3em] text-muted-foreground/70">Skill Builder</span>
            <h3 className="text-2xl font-semibold tracking-tight text-foreground">Practice</h3>
            <p className="mt-3 flex-1 text-sm leading-relaxed text-muted-foreground/80">
              30-minute focused sessions targeting specific concepts. Refine individual skills with AI-powered feedback.
            </p>
            <div className="mt-6 flex flex-wrap gap-2">
              <span className="rounded-full bg-white/5 px-3 py-1 text-[11px] font-medium text-muted-foreground border border-white/5">Data Structures</span>
              <span className="rounded-full bg-white/5 px-3 py-1 text-[11px] font-medium text-muted-foreground border border-white/5">Algorithms</span>
              <span className="rounded-full bg-white/5 px-3 py-1 text-[11px] font-medium text-muted-foreground border border-white/5">System Design</span>
            </div>
          </div>
          <div className="relative border-t border-border/20 p-6">
            <Button onClick={() => handleStartSession('practice')} disabled={isStartingPractice} className="w-full gap-2 rounded-xl text-sm font-semibold shadow-sm transition-all hover:scale-[1.02]">
              {isStartingPractice ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              {isStartingPractice ? "Starting..." : "Practice Now"}
            </Button>
          </div>
        </div>
        <div className="group relative flex flex-col overflow-hidden rounded-2xl border border-border/20 bg-card/30 backdrop-blur-sm transition-all duration-500 hover:bg-card/60 hover:shadow-xl hover:shadow-primary/5 hover:border-border/40">
          <div className="absolute inset-0 bg-gradient-to-br from-primary/5 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-700" />
          <div className="relative flex flex-1 flex-col p-8">
            <span className="mb-6 text-[10px] font-bold uppercase tracking-[0.3em] text-muted-foreground/70">Full Simulation</span>
            <h3 className="text-2xl font-semibold tracking-tight text-foreground">Mock Interview</h3>
            <p className="mt-3 flex-1 text-sm leading-relaxed text-muted-foreground/80">
              Comprehensive 30-45 minute role-play simulation. Experience a realistic professional interview environment.
            </p>
            <div className="mt-6 flex flex-wrap gap-2">
              <span className="rounded-full bg-white/5 px-3 py-1 text-[11px] font-medium text-muted-foreground border border-white/5">Behavioral</span>
              <span className="rounded-full bg-white/5 px-3 py-1 text-[11px] font-medium text-muted-foreground border border-white/5">Technical</span>
              <span className="rounded-full bg-white/5 px-3 py-1 text-[11px] font-medium text-muted-foreground border border-white/5">Role-specific</span>
            </div>
          </div>
          <div className="relative border-t border-border/20 p-6">
            <Button onClick={() => handleStartSession('mock')} disabled={isStartingMock} className="w-full gap-2 rounded-xl shadow-sm transition-all hover:scale-[1.02]">
              {isStartingMock ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              {isStartingMock ? "Starting..." : "Start Mock Interview"}
            </Button>
          </div>
        </div>
      </div>
      <div className="overflow-hidden rounded-2xl border border-border/20 bg-card/30 backdrop-blur-sm shadow-sm">
        <div className="border-b border-border/20 p-6">
          <span className="text-[10px] font-bold uppercase tracking-[0.3em] text-muted-foreground/70">History</span>
          <h3 className="mt-2 text-base font-semibold text-foreground">Past Interviews</h3>
          <p className="mt-1 text-sm text-muted-foreground/80">Review your sessions and performance data.</p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-border">
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">Date</th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">Target Role</th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">Session Type</th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">Overall Score</th>
                <th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-muted-foreground">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {interviews.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-6 py-12 text-center">
                    <div className="flex flex-col items-center gap-2">
                      <Mic className="h-8 w-8 text-muted-foreground/50" />
                      <p className="text-sm text-muted-foreground">No sessions recorded</p>
                      <p className="text-xs text-muted-foreground">Complete your initial interview to begin tracking your performance history.</p>
                    </div>
                  </td>
                </tr>
              ) : (
                interviews.map((interview) => (
                  <tr key={interview.id} className="transition-colors hover:bg-secondary/30">
                    <td className="whitespace-nowrap px-6 py-4 text-sm text-foreground">{interview.date}</td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm text-foreground">{interview.role}</td>
                    <td className="whitespace-nowrap px-6 py-4">
                      <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${interview.type === "Full"
                        ? "bg-primary/10 text-primary"
                        : "bg-cyan-500/10 text-cyan-400"
                        }`}>
                        {interview.type}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-6 py-4">
                      <div className="flex items-center gap-2">
                        <div className="h-2 w-16 overflow-hidden rounded-full bg-border">
                          <div
                            className={`h-full rounded-full ${interview.score >= 80 ? "bg-green-500" : interview.score >= 60 ? "bg-amber-500" : "bg-red-500"
                              }`}
                            style={{ width: `${interview.score}%` }}
                          />
                        </div>
                        <span className="text-sm font-medium text-foreground">{interview.score}%</span>
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-6 py-4 text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="gap-1.5 text-primary"
                        onClick={() => router.push(`/interview/${interview.id}/report`)}
                      >
                        <Eye className="h-3.5 w-3.5" />
                        View Full Report
                      </Button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
      <Dialog open={showStartConfirm} onOpenChange={setShowStartConfirm}>
        <DialogContent className="max-w-sm border-border bg-card">
          <DialogHeader>
            <DialogTitle className="text-lg font-bold text-foreground flex items-center gap-2">
              <AlertCircle className="h-5 w-5 text-amber-500" /> Confirm Session Start
            </DialogTitle>
            <DialogDescription className="mt-2 text-sm text-muted-foreground">
              You are about to start a {sessionToStart === 'mock' ? 'Full Mock' : 'Practice'} Interview.
              <br /><br />
              This will deduct <strong>1 credit</strong> from your available balance. Please ensure you are in a quiet environment and your microphone/camera is ready.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="mt-4 flex gap-3">
            <Button
              variant="outline"
              className="flex-1"
              onClick={() => setShowStartConfirm(false)}
              disabled={isStartingMock || isStartingPractice}
            >
              Cancel
            </Button>
            <Button
              className="flex-1"
              onClick={confirmStartSession}
              disabled={isStartingMock || isStartingPractice}
            >
              {(isStartingMock || isStartingPractice) ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              {(isStartingMock || isStartingPractice) ? "Starting..." : "Yes, Start Next Session"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
function SkillsDisplay({ skills }: { skills: string }) {
  const [showAll, setShowAll] = useState(false)
  const allSkills = skills.split(",").map(s => s.trim()).filter(Boolean)
  const MAX_VISIBLE = 12
  const visibleSkills = showAll ? allSkills : allSkills.slice(0, MAX_VISIBLE)
  const hiddenCount = allSkills.length - MAX_VISIBLE

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-1.5">
        {visibleSkills.map((skill) => (
          <span key={skill} className="rounded-md border border-primary/15 bg-primary/5 px-2.5 py-1 text-[11px] font-medium text-primary">
            {skill}
          </span>
        ))}
      </div>
      {hiddenCount > 0 && (
        <button
          type="button"
          onClick={() => setShowAll(!showAll)}
          className="self-start text-xs font-medium text-primary hover:text-primary/80 transition-colors"
        >
          {showAll ? "Show less" : `+${hiddenCount} more skills`}
        </button>
      )}
    </div>
  )
}
function ResumeContent({
  onUploadResume
}: {
  onUploadResume?: () => void
}) {
  const { resumeData: contextResumeData, isLoading, justParsed, setJustParsed } = useResume()
  const [isEditing, setIsEditing] = useState(false)
  const [resumeData, setResumeData] = useState<DashboardResumeData>(emptyResumeData)
  const [editData, setEditData] = useState<DashboardResumeData>(emptyResumeData)
  const hasData = Boolean(contextResumeData)
  useEffect(() => {
    if (contextResumeData) {
      const mapped = mapResumeDataToDashboard(contextResumeData)
      setResumeData(mapped)
      setEditData(mapped)
      if (justParsed) {
        setIsEditing(true)
        setJustParsed(false)
      }
    }
  }, [contextResumeData, justParsed, setJustParsed])
  const [isSaving, setIsSaving] = useState(false)
  const handleSave = async () => {
    setIsSaving(true)
    try {
      const dataToSubmit: ResumeData = {
        fullName: editData.fullName,
        email: editData.email,
        phoneNumber: editData.phone,
        linkedinUrl: editData.linkedin,
        githubUrl: editData.github,
        portfolioUrl: editData.portfolio,
        targetRole: editData.targetRole,
        professionalSummary: editData.summary,
        skills: editData.technicalSkills.split(",").map(s => s.trim()).filter(Boolean).map(s => ({ name: s })),
        experiences: editData.experience.map(exp => ({
          position: exp.title,
          company: exp.company,
          startDate: exp.dates.includes('-') ? exp.dates.split('-')[0].trim() : exp.dates,
          endDate: exp.dates.includes('-') ? exp.dates.split('-')[1].trim() : '',
          isCurrent: exp.dates.toLowerCase().includes('present'),
          description: exp.description
        })),
        education: editData.education.map(edu => ({
          institution: edu.institution,
          degree: edu.degree,
          field: edu.major,
          endYear: parseInt(edu.graduationYear) || undefined,
          gpa: parseFloat(edu.cgpa) || undefined
        })),
        projects: editData.projects.map(proj => ({
          name: proj.name,
          technologies: proj.techStack.split(',').map(s => s.trim()),
          description: proj.description
        })),
        certifications: editData.certifications.split("\n").map(c => c.trim()).filter(Boolean).map(c => ({ name: c, issuer: "" })),
        languages: editData.languages.split(",").map(l => l.trim()).filter(Boolean).map(l => ({ name: l, proficiency: 'professional' }))
      }
      await submitResume(dataToSubmit)
      setResumeData(editData)
      setIsEditing(false)
      toast.success("Profile saved successfully!")
    } catch (error: any) {
      toast.error("Failed to save profile. Please try again.")
    } finally {
      setIsSaving(false)
    }
  }
  const handleCancel = () => {
    setEditData(resumeData)
    setIsEditing(false)
  }
  const missingKeywords = hasData && resumeData.targetRole && resumeData.technicalSkills.length < 5
  return (
    <div className="flex-1 overflow-y-auto p-6 md:p-8 animate-fade-in-up">
      {!hasData ? (
        <div className="relative flex min-h-[400px] flex-col items-center justify-center rounded-2xl border-2 border-dashed border-border bg-card/50 p-12 transition-all duration-300 hover:border-primary/50 hover:bg-primary/5">
          <div className="mb-6 flex h-20 w-20 items-center justify-center rounded-2xl bg-primary/10">
            <Upload className="h-10 w-10 text-primary" />
          </div>
          <h2 className="text-xl font-bold text-foreground">Upload Your Resume</h2>
          <p className="mt-2 max-w-sm text-center text-sm text-muted-foreground">
            Drag and drop your PDF or DOCX file here, or click to browse. Our AI will parse and auto-fill your profile.
          </p>
          <Button onClick={onUploadResume} className="mt-6 gap-2 rounded-full px-8 shadow-sm">
            <Upload className="h-4 w-4" />
            Upload PDF or DOCX
          </Button>
        </div>
      ) : (
        <div className="flex flex-col gap-6 lg:flex-row">
          <div className="flex-1 space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-bold text-foreground">Profile</h2>
                <p className="text-xs text-muted-foreground">View and edit your parsed profile details</p>
              </div>
              <div className="flex items-center gap-2">
                {missingKeywords && (
                  <div className="flex items-center gap-1.5 rounded-lg bg-amber-500/10 px-3 py-1.5 text-xs font-medium text-amber-400">
                    <AlertTriangle className="h-3.5 w-3.5" />
                    Missing Keywords
                  </div>
                )}
                {!isEditing ? (
                  <Button variant="outline" size="sm" onClick={() => setIsEditing(true)} className="gap-1.5">
                    <Edit3 className="h-3.5 w-3.5" />
                    Edit
                  </Button>
                ) : (
                  <div className="flex items-center gap-2">
                    <Button variant="ghost" size="sm" onClick={handleCancel} disabled={isSaving}>Cancel</Button>
                    <Button size="sm" onClick={handleSave} disabled={isSaving} className="gap-1.5">
                      {isSaving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                      {isSaving ? "Saving..." : "Save"}
                    </Button>
                  </div>
                )}
              </div>
            </div>
            <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
              <h3 className="mb-4 flex items-center gap-2 text-sm font-semibold text-foreground">
                <User className="h-4 w-4 text-primary" />
                Personal Information
              </h3>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs text-muted-foreground">Full Name</Label>
                  {isEditing ? (
                    <Input value={editData.fullName} onChange={(e) => setEditData({ ...editData, fullName: e.target.value })} className="h-9 bg-secondary/50" />
                  ) : (
                    <p className="text-sm font-medium text-foreground">{resumeData.fullName}</p>
                  )}
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs text-muted-foreground"><Play className="inline h-3 w-3 mr-1" />Target Role</Label>
                  {isEditing ? (
                    <Input value={editData.targetRole} onChange={(e) => setEditData({ ...editData, targetRole: e.target.value })} className="h-9 bg-secondary/50" />
                  ) : (
                    <p className="text-sm font-medium text-primary">{resumeData.targetRole}</p>
                  )}
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs text-muted-foreground"><Mail className="inline h-3 w-3 mr-1" />Email</Label>
                  {isEditing ? (
                    <Input value={editData.email} onChange={(e) => setEditData({ ...editData, email: e.target.value })} className="h-9 bg-secondary/50" />
                  ) : (
                    <p className="text-sm text-foreground">{resumeData.email}</p>
                  )}
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs text-muted-foreground"><Phone className="inline h-3 w-3 mr-1" />Phone</Label>
                  {isEditing ? (
                    <Input value={editData.phone} onChange={(e) => setEditData({ ...editData, phone: e.target.value })} className="h-9 bg-secondary/50" />
                  ) : (
                    <p className="text-sm text-foreground">{resumeData.phone}</p>
                  )}
                </div>
              </div>
            </div>
            <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
              <h3 className="mb-4 flex items-center gap-2 text-sm font-semibold text-foreground">
                <Globe className="h-4 w-4 text-primary" />
                Links
              </h3>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs text-muted-foreground"><Linkedin className="inline h-3 w-3 mr-1" />LinkedIn</Label>
                  {isEditing ? (
                    <Input value={editData.linkedin} onChange={(e) => setEditData({ ...editData, linkedin: e.target.value })} className="h-9 bg-secondary/50" />
                  ) : (
                    <a href={resumeData.linkedin} target="_blank" rel="noreferrer" className="truncate text-sm text-primary hover:underline">{resumeData.linkedin}</a>
                  )}
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs text-muted-foreground"><Code className="inline h-3 w-3 mr-1" />GitHub</Label>
                  {isEditing ? (
                    <Input value={editData.github} onChange={(e) => setEditData({ ...editData, github: e.target.value })} className="h-9 bg-secondary/50" />
                  ) : (
                    <a href={resumeData.github} target="_blank" rel="noreferrer" className="truncate text-sm text-primary hover:underline">{resumeData.github}</a>
                  )}
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs text-muted-foreground"><Globe className="inline h-3 w-3 mr-1" />Portfolio</Label>
                  {isEditing ? (
                    <Input value={editData.portfolio} onChange={(e) => setEditData({ ...editData, portfolio: e.target.value })} className="h-9 bg-secondary/50" />
                  ) : (
                    <a href={resumeData.portfolio} target="_blank" rel="noreferrer" className="truncate text-sm text-primary hover:underline">{resumeData.portfolio}</a>
                  )}
                </div>
              </div>
            </div>
            <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
              <h3 className="mb-4 flex items-center gap-2 text-sm font-semibold text-foreground">
                <FileText className="h-4 w-4 text-primary" />
                Summary / About
              </h3>
              {isEditing ? (
                <Textarea value={editData.summary} onChange={(e) => setEditData({ ...editData, summary: e.target.value })} rows={3} className="bg-secondary/50" />
              ) : (
                <p className="text-sm leading-relaxed text-muted-foreground">{resumeData.summary}</p>
              )}
            </div>
            <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
              <div className="mb-4 flex items-center justify-between">
                <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                  <GraduationCap className="h-4 w-4 text-primary" />
                  Education
                </h3>
                {isEditing && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setEditData({ ...editData, education: [{ institution: "", degree: "", major: "", graduationYear: "", cgpa: "" }, ...editData.education] })}
                    className="h-7 px-2 text-xs"
                  >
                    + Add
                  </Button>
                )}
              </div>
              <div className="flex flex-col gap-4">
                {isEditing ? editData.education.map((edu, i) => (
                  <div key={i} className="relative flex flex-col gap-1 rounded-md border border-border bg-secondary/20 p-3">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => { const ed = [...editData.education]; ed.splice(i, 1); setEditData({ ...editData, education: ed }) }}
                      className="absolute right-2 top-2 h-6 w-6 p-0 text-muted-foreground hover:text-destructive"
                    >
                      <X className="h-3 w-3" />
                    </Button>
                    <div className="grid grid-cols-1 gap-3 pr-8 sm:grid-cols-2">
                      <Input value={edu.institution} onChange={(e) => { const ed = [...editData.education]; ed[i] = { ...ed[i], institution: e.target.value }; setEditData({ ...editData, education: ed }); }} placeholder="Institution" className="h-9 bg-secondary/50" />
                      <Input value={edu.degree} onChange={(e) => { const ed = [...editData.education]; ed[i] = { ...ed[i], degree: e.target.value }; setEditData({ ...editData, education: ed }); }} placeholder="Degree (e.g., BS)" className="h-9 bg-secondary/50" />
                      <Input value={edu.major} onChange={(e) => { const ed = [...editData.education]; ed[i] = { ...ed[i], major: e.target.value }; setEditData({ ...editData, education: ed }); }} placeholder="Major" className="h-9 bg-secondary/50" />
                      <Input value={edu.graduationYear} onChange={(e) => { const ed = [...editData.education]; ed[i] = { ...ed[i], graduationYear: e.target.value }; setEditData({ ...editData, education: ed }); }} placeholder="Grad Year" className="h-9 bg-secondary/50" />
                      <Input value={edu.cgpa} onChange={(e) => { const ed = [...editData.education]; ed[i] = { ...ed[i], cgpa: e.target.value }; setEditData({ ...editData, education: ed }); }} placeholder="CGPA" className="h-9 bg-secondary/50" />
                    </div>
                  </div>
                )) : resumeData.education.map((edu, i) => (
                  <div key={i} className="flex flex-col gap-1">
                    <p className="text-sm font-medium text-foreground">{edu.institution}</p>
                    <p className="text-xs text-muted-foreground">{edu.degree} in {edu.major} | Grad: {edu.graduationYear} | CGPA: {edu.cgpa}</p>
                  </div>
                ))}
              </div>
            </div>
            <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
              <div className="mb-4 flex items-center justify-between">
                <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                  <Briefcase className="h-4 w-4 text-primary" />
                  Experience
                </h3>
                {isEditing && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setEditData({ ...editData, experience: [{ title: "", company: "", dates: "", description: "" }, ...editData.experience] })}
                    className="h-7 px-2 text-xs"
                  >
                    + Add
                  </Button>
                )}
              </div>
              <div className="flex flex-col gap-4">
                {isEditing ? editData.experience.map((exp, i) => (
                  <div key={i} className="relative flex flex-col gap-1 rounded-md border border-border bg-secondary/20 p-3">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => { const ex = [...editData.experience]; ex.splice(i, 1); setEditData({ ...editData, experience: ex }) }}
                      className="absolute right-2 top-2 h-6 w-6 p-0 text-muted-foreground hover:text-destructive"
                    >
                      <X className="h-3 w-3" />
                    </Button>
                    <div className="grid grid-cols-1 gap-3 pr-8 sm:grid-cols-2">
                      <Input value={exp.title} onChange={(e) => { const ex = [...editData.experience]; ex[i] = { ...ex[i], title: e.target.value }; setEditData({ ...editData, experience: ex }); }} placeholder="Job Title" className="h-9 bg-secondary/50" />
                      <Input value={exp.company} onChange={(e) => { const ex = [...editData.experience]; ex[i] = { ...ex[i], company: e.target.value }; setEditData({ ...editData, experience: ex }); }} placeholder="Company" className="h-9 bg-secondary/50" />
                      <Input value={exp.dates} onChange={(e) => { const ex = [...editData.experience]; ex[i] = { ...ex[i], dates: e.target.value }; setEditData({ ...editData, experience: ex }); }} placeholder="Dates" className="h-9 bg-secondary/50 sm:col-span-2" />
                      <Textarea value={exp.description} onChange={(e) => { const ex = [...editData.experience]; ex[i] = { ...ex[i], description: e.target.value }; setEditData({ ...editData, experience: ex }); }} placeholder="Description" className="bg-secondary/50 sm:col-span-2" rows={3} />
                    </div>
                  </div>
                )) : resumeData.experience.map((exp, i) => (
                  <div key={i} className="flex flex-col gap-1">
                    <p className="text-sm font-medium text-foreground">{exp.title} at {exp.company}</p>
                    <p className="text-xs text-muted-foreground">{exp.dates}</p>
                    <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{exp.description}</p>
                  </div>
                ))}
              </div>
            </div>
            <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6" >
              <div className="flex items-center justify-between mb-4">
                <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                  <Code className="h-4 w-4 text-primary" />
                  Projects
                </h3>
                {isEditing && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setEditData({ ...editData, projects: [{ name: "", description: "", techStack: "" }, ...editData.projects] })}
                    className="h-7 px-2 text-xs"
                  >
                    + Add
                  </Button>
                )}
              </div>
              <div className="flex flex-col gap-4">
                {isEditing ? editData.projects.map((proj, i) => (
                  <div key={i} className="relative rounded-lg border border-border bg-secondary/30 p-4">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => { const p = [...editData.projects]; p.splice(i, 1); setEditData({ ...editData, projects: p }) }}
                      className="absolute right-2 top-2 h-6 w-6 p-0 text-muted-foreground hover:text-destructive"
                    >
                      <X className="h-3 w-3" />
                    </Button>
                    <div className="grid grid-cols-1 gap-3 pr-8">
                      <Input value={proj.name} onChange={(e) => { const p = [...editData.projects]; p[i] = { ...p[i], name: e.target.value }; setEditData({ ...editData, projects: p }); }} placeholder="Project Name" className="h-9 bg-card" />
                      <Input value={proj.techStack} onChange={(e) => { const p = [...editData.projects]; p[i] = { ...p[i], techStack: e.target.value }; setEditData({ ...editData, projects: p }); }} placeholder="Tech Stack (comma separated)" className="h-9 bg-card" />
                      <Textarea value={proj.description} onChange={(e) => { const p = [...editData.projects]; p[i] = { ...p[i], description: e.target.value }; setEditData({ ...editData, projects: p }); }} placeholder="Description" className="bg-card" rows={3} />
                    </div>
                  </div>
                )) : resumeData.projects.map((proj, i) => (
                  <div key={i} className="rounded-lg border border-border bg-secondary/30 p-4">
                    <p className="text-sm font-medium text-foreground">{proj.name}</p>
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {proj.techStack.split(",").map((tech) => tech.trim()).filter(Boolean).map((tech) => (
                        <span key={tech} className="rounded-md bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">{tech}</span>
                      ))}
                    </div>
                    <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{proj.description}</p>
                  </div>
                ))}
              </div>
            </div>
            <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
              <div className="mb-4 flex items-center justify-between">
                <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                  <Code className="h-4 w-4 text-primary" />
                  Technical Skills
                </h3>
                {!isEditing && (() => {
                  const allSkills = resumeData.technicalSkills.split(",").map(s => s.trim()).filter(Boolean)
                  return allSkills.length > 0 ? (
                    <span className="text-xs text-muted-foreground">{allSkills.length} skills</span>
                  ) : null
                })()}
              </div>
              {isEditing ? (
                <div className="flex flex-col gap-2">
                  <Textarea
                    value={editData.technicalSkills}
                    onChange={(e) => setEditData({ ...editData, technicalSkills: e.target.value })}
                    className="bg-secondary/50"
                    placeholder="Comma-separated skills (e.g. Python, React, SQL)"
                    rows={3}
                  />
                  <p className="text-xs text-muted-foreground">Separate skills with commas</p>
                </div>
              ) : (
                <SkillsDisplay skills={resumeData.technicalSkills} />
              )}
            </div>
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
              <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
                <h3 className="mb-4 flex items-center gap-2 text-sm font-semibold text-foreground">
                  <Award className="h-4 w-4 text-primary" />
                  Certifications
                </h3>
                {isEditing ? (
                  <div className="flex flex-col gap-2">
                    <Textarea
                      value={editData.certifications}
                      onChange={(e) => setEditData({ ...editData, certifications: e.target.value })}
                      className="bg-secondary/50"
                      placeholder="One certification per line"
                      rows={4}
                    />
                    <p className="text-xs text-muted-foreground">Put each certification on a new line</p>
                  </div>
                ) : (
                  <div className="flex flex-col gap-2">
                    {resumeData.certifications.split("\n").map(s => s.trim()).filter(Boolean).length > 0 ? resumeData.certifications.split("\n").map(s => s.trim()).filter(Boolean).map((cert) => (
                      <div key={cert} className="flex items-center gap-2">
                        <Check className="h-3.5 w-3.5 shrink-0 text-primary" />
                        <span className="text-xs text-foreground">{cert}</span>
                      </div>
                    )) : <p className="text-xs text-muted-foreground italic">None listed</p>}
                  </div>
                )}
              </div>
              <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
                <h3 className="mb-4 flex items-center gap-2 text-sm font-semibold text-foreground">
                  <Languages className="h-4 w-4 text-primary" />
                  Languages Known
                </h3>
                {isEditing ? (
                  <div className="flex flex-col gap-2">
                    <Textarea
                      value={editData.languages}
                      onChange={(e) => setEditData({ ...editData, languages: e.target.value })}
                      className="bg-secondary/50"
                      placeholder="Comma-separated languages (e.g. English, Spanish)"
                      rows={3}
                    />
                    <p className="text-xs text-muted-foreground">Separate languages with commas</p>
                  </div>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {resumeData.languages.split(",").map(s => s.trim()).filter(Boolean).length > 0 ? resumeData.languages.split(",").map(s => s.trim()).filter(Boolean).map((lang) => (
                      <span key={lang} className="rounded-lg border border-border bg-secondary/50 px-3 py-1.5 text-xs text-foreground">{lang}</span>
                    )) : <p className="text-xs text-muted-foreground italic">None listed</p>}
                  </div>
                )}
              </div>
            </div>
          </div>
          <div className="w-full lg:w-72 xl:w-80">
            <div className="sticky top-24 space-y-4">
              <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
                <h3 className="mb-1 text-sm font-semibold text-foreground">Upload Resume</h3>
                <p className="mb-4 text-xs text-muted-foreground">Re-upload to update your parsed profile</p>
                <div className="relative flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed border-border bg-secondary/30 p-8 transition-all duration-300 hover:border-primary/30 hover:bg-primary/5" onClick={onUploadResume}>
                  <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10">
                    <Upload className="h-6 w-6 text-primary" />
                  </div>
                  <div className="text-center">
                    <p className="text-sm font-medium text-foreground">Click to upload</p>
                    <p className="text-xs text-muted-foreground">PDF or DOCX, up to 5MB</p>
                  </div>
                </div>
                <Button variant="outline" onClick={onUploadResume} className="mt-4 w-full gap-2 text-sm">
                  <Upload className="h-3.5 w-3.5" />
                  Browse Files
                </Button>
              </div>
              <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
                <h3 className="mb-3 text-sm font-semibold text-foreground">Profile Completeness</h3>
                {(() => {
                  const checks = [
                    { label: "Personal Info", done: Boolean(resumeData.fullName) },
                    { label: "Education", done: resumeData.education.length > 0 },
                    { label: "Skills", done: resumeData.technicalSkills.length > 0 },
                    { label: "Experience", done: resumeData.experience.length > 0 },
                    { label: "Projects", done: resumeData.projects.length > 0 },
                  ]
                  const doneCount = checks.filter((c) => c.done).length
                  const pct = Math.round((doneCount / checks.length) * 100)
                  return (
                    <>
                      <div className="mb-2 h-2 overflow-hidden rounded-full bg-border">
                        <div className="h-full rounded-full bg-gradient-to-r from-primary to-[#60A5FA] transition-all duration-500" style={{ width: `${pct}%` }} />
                      </div>
                      <p className="text-xs text-muted-foreground">{pct}% complete</p>
                      <div className="mt-4 flex flex-col gap-2">
                        {checks.map((c) => (
                          <div key={c.label} className="flex items-center gap-2 text-xs">
                            {c.done ? (
                              <Check className="h-3.5 w-3.5 text-primary" />
                            ) : (
                              <div className="h-3.5 w-3.5 rounded-full border border-border" />
                            )}
                            <span className={c.done ? "text-foreground" : "text-muted-foreground"}>{c.label}</span>
                          </div>
                        ))}
                      </div>
                    </>
                  )
                })()}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
function AnalyticsContent() {
  const [analyticsData, setAnalyticsData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    async function loadAnalytics() {
      try {
        setLoading(true)
        setError(null)
        const { fetchAnalytics } = await import("@/lib/api")
        const data = await fetchAnalytics()
        setAnalyticsData(data)
      } catch {
        setError("Failed to load analytics")
      } finally {
        setLoading(false)
      }
    }
    loadAnalytics()
  }, [])

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
          <p className="text-sm text-muted-foreground">Loading analytics...</p>
        </div>
      </div>
    )
  }

  if (error || !analyticsData) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="text-center">
          <AlertCircle className="mx-auto mb-3 h-10 w-10 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">{error || "Unable to load analytics"}</p>
        </div>
      </div>
    )
  }

  const {
    score_trend,
    skill_gap,
    response_time,
    summary,
    coaching_metrics = {},
    followup_performance,
    weak_patterns = [],
    weak_topics = [],
    question_pressure_points = [],
    evidence_health,
    practice_priorities = [],
  } = analyticsData
  const hasData = summary.total_interviews > 0

  if (!hasData) {
    return (
      <div className="flex-1 overflow-y-auto p-6 md:p-8 animate-fade-in-up">
        <div className="flex min-h-[400px] flex-col items-center justify-center rounded-2xl border-2 border-dashed border-border bg-card/50 p-12">
          <div className="mb-6 flex h-20 w-20 items-center justify-center rounded-2xl bg-primary/10">
            <BarChart3 className="h-10 w-10 text-primary" />
          </div>
          <h2 className="text-xl font-bold text-foreground">No Analytics Yet</h2>
          <p className="mt-2 max-w-sm text-center text-sm text-muted-foreground">
            Complete your first interview session to see student-focused coaching analytics.
          </p>
        </div>
      </div>
    )
  }

  const trendData: number[] = score_trend.map((s: any) => s.score)
  const trendLabels: string[] = score_trend.map((s: any) => {
    if (!s.date) return ""
    const d = new Date(s.date)
    return `${d.getMonth() + 1}/${d.getDate()}`
  })
  const improvementColor = summary.improvement > 0 ? "text-emerald-500" : summary.improvement < 0 ? "text-rose-500" : "text-muted-foreground"
  const improvementPrefix = summary.improvement > 0 ? "+" : ""
  const scoreColor = (s: number) => s >= 80 ? "text-emerald-500" : s >= 60 ? "text-amber-500" : "text-rose-500"
  const scoreBg = (s: number) => s >= 80 ? "bg-emerald-500" : s >= 60 ? "bg-amber-500" : "bg-rose-500"
  const pillarCards = [
    ["interview_readiness", "Interview Readiness"],
    ["answer_clarity", "Answer Clarity"],
    ["technical_depth", "Technical Depth"],
    ["proof_of_work", "Proof of Work"],
  ]

  return (
    <div className="flex-1 overflow-y-auto p-6 md:p-8 animate-fade-in-up">
      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <div className="group rounded-2xl border border-border/40 bg-card/40 p-5 transition-all duration-300 hover:bg-card hover:shadow-md hover:border-border/60">
          <p className="mb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">Average Score</p>
          <p className={`text-2xl font-semibold tracking-tight ${scoreColor(summary.average_score)}`}>{summary.average_score}%</p>
          <p className="mt-1 text-xs text-muted-foreground">Best: {summary.best_score}% · Lowest: {summary.worst_score}%</p>
        </div>
        <div className="group rounded-2xl border border-border/40 bg-card/40 p-5 transition-all duration-300 hover:bg-card hover:shadow-md hover:border-border/60">
          <p className="mb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">Total Interviews</p>
          <p className="text-2xl font-semibold tracking-tight text-foreground">{summary.total_interviews}</p>
          <p className="mt-1 text-xs text-muted-foreground">Sessions completed</p>
        </div>
        <div className="group rounded-2xl border border-border/40 bg-card/40 p-5 transition-all duration-300 hover:bg-card hover:shadow-md hover:border-border/60">
          <p className="mb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">Questions Answered</p>
          <p className="text-2xl font-semibold tracking-tight text-foreground">{summary.total_questions}</p>
          <p className="mt-1 text-xs text-muted-foreground">Across all sessions</p>
        </div>
        <div className="group rounded-2xl border border-border/40 bg-card/40 p-5 transition-all duration-300 hover:bg-card hover:shadow-md hover:border-border/60">
          <p className="mb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">Improvement</p>
          <p className={`text-2xl font-semibold tracking-tight ${improvementColor}`}>{improvementPrefix}{summary.improvement}%</p>
          <p className="mt-1 text-xs text-muted-foreground">First → Latest session</p>
        </div>
      </div>

      <div className="mb-6 rounded-2xl border border-border/40 bg-card shadow-sm p-6">
        <h3 className="mb-1 text-sm font-semibold text-foreground">Coaching Pillars</h3>
        <p className="mb-5 text-xs text-muted-foreground">Four all-rounder signals based on your answers, follow-ups, and evidence quality.</p>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {pillarCards.map(([key, label]) => {
            const item = coaching_metrics[key]
            return (
              <div key={key} className="rounded-xl border border-border/30 bg-secondary/20 p-4">
                <p className="text-xs font-medium text-muted-foreground">{label}</p>
                <p className={`mt-2 text-2xl font-semibold ${scoreColor(item?.score || 0)}`}>{Math.round(item?.score || 0)}%</p>
                <p className="mt-2 text-xs leading-5 text-muted-foreground">{item?.insight || "No signal yet."}</p>
              </div>
            )
          })}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
          <h3 className="mb-1 text-sm font-semibold text-foreground">Performance Trend</h3>
          <p className="mb-5 text-xs text-muted-foreground">Score over last {trendData.length} interviews</p>
          <div className="relative h-48">
            <svg className="h-full w-full" viewBox="0 0 400 150" preserveAspectRatio="none">
              {[0, 25, 50, 75, 100].map((y, i) => (
                <line key={i} x1="0" y1={150 - y * 1.5} x2="400" y2={150 - y * 1.5} className="stroke-border" strokeWidth="1" strokeDasharray="4,4" />
              ))}
              <defs>
                <linearGradient id="analyticsGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity="0.3" />
                  <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity="0" />
                </linearGradient>
              </defs>
              {trendData.length > 1 && (
                <>
                  <path
                    d={`M0,${150 - trendData[0] * 1.5} ${trendData.map((v, i) => `L${(i / (trendData.length - 1)) * 400},${150 - v * 1.5}`).join(" ")} L400,150 L0,150 Z`}
                    fill="url(#analyticsGrad)"
                  />
                  <path
                    d={`M0,${150 - trendData[0] * 1.5} ${trendData.map((v, i) => `L${(i / (trendData.length - 1)) * 400},${150 - v * 1.5}`).join(" ")}`}
                    fill="none"
                    className="stroke-primary"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </>
              )}
            </svg>
            <div className="absolute left-0 top-0 flex h-full flex-col justify-between text-[10px] text-muted-foreground">
              <span>100</span><span>75</span><span>50</span><span>25</span><span>0</span>
            </div>
            {trendLabels.length > 1 && (
              <div className="mt-1 flex justify-between px-1 text-[10px] text-muted-foreground">
                {trendLabels.filter((_, i) => i === 0 || i === trendLabels.length - 1 || i === Math.floor(trendLabels.length / 2)).map((label, index) => (
                  <span key={index}>{label}</span>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
          <h3 className="mb-1 text-sm font-semibold text-foreground">Topic Performance</h3>
          <p className="mb-5 text-xs text-muted-foreground">Where your answers are holding up, and where they drop off.</p>
          {skill_gap.labels.length > 0 ? (
            <div className="space-y-3">
              {skill_gap.labels.map((label: string, i: number) => {
                const value = skill_gap.values[i] || 0
                return (
                  <div key={label}>
                    <div className="mb-1.5 flex items-center justify-between">
                      <span className="max-w-[220px] truncate text-xs font-medium text-foreground">{label}</span>
                      <span className={`text-xs font-semibold ${scoreColor(value)}`}>{value}%</span>
                    </div>
                    <div className="h-2 overflow-hidden rounded-full bg-border/60">
                      <div className={`h-full rounded-full ${scoreBg(value)}`} style={{ width: `${value}%` }} />
                    </div>
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">
              No topic data available yet
            </div>
          )}
        </div>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
          <h3 className="mb-1 text-sm font-semibold text-foreground">Follow-up Pressure</h3>
          <p className="mb-5 text-xs text-muted-foreground">How well you hold up once the interviewer pushes deeper.</p>
          <div className="grid grid-cols-2 gap-4">
            <div className="rounded-xl border border-border/30 bg-secondary/30 p-4 text-center">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Main</p>
              <p className={`mt-2 text-2xl font-semibold ${scoreColor(followup_performance.main_avg)}`}>{followup_performance.main_avg}%</p>
            </div>
            <div className="rounded-xl border border-border/30 bg-secondary/30 p-4 text-center">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Follow-up</p>
              <p className={`mt-2 text-2xl font-semibold ${scoreColor(followup_performance.followup_avg)}`}>{followup_performance.followup_avg}%</p>
            </div>
          </div>
          <p className="mt-4 text-sm leading-6 text-muted-foreground">{followup_performance.insight}</p>
        </div>

        <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
          <h3 className="mb-1 text-sm font-semibold text-foreground">Evidence Health</h3>
          <p className="mb-5 text-xs text-muted-foreground">How often your claims are backed by concrete proof.</p>
          <p className={`text-3xl font-semibold ${scoreColor(evidence_health.score)}`}>{Math.round(evidence_health.score)}%</p>
          <div className="mt-4 space-y-3 text-sm">
            <div className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground">Supported answers</span>
              <span className="font-medium">{evidence_health.supported_answers}</span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground">Evidence gaps</span>
              <span className="font-medium">{evidence_health.flagged_answers}</span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground">Resume/project alignment</span>
              <span className="font-medium">{Math.round(evidence_health.alignment_rate)}%</span>
            </div>
          </div>
          <p className="mt-4 text-sm leading-6 text-muted-foreground">{evidence_health.note}</p>
        </div>

        <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
          <h3 className="mb-1 text-sm font-semibold text-foreground">Response Timing</h3>
          <p className="mb-5 text-xs text-muted-foreground">Pacing stays visible, but it is secondary to answer quality.</p>
          <div className="grid grid-cols-3 gap-3">
            <div className="rounded-xl border border-border/30 bg-secondary/30 p-4 text-center">
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Average</p>
              <p className="mt-2 text-xl font-semibold text-foreground">{response_time.average}s</p>
            </div>
            <div className="rounded-xl border border-border/30 bg-secondary/30 p-4 text-center">
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Fastest</p>
              <p className="mt-2 text-xl font-semibold text-emerald-500">{response_time.fastest}s</p>
            </div>
            <div className="rounded-xl border border-border/30 bg-secondary/30 p-4 text-center">
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Slowest</p>
              <p className="mt-2 text-xl font-semibold text-amber-500">{response_time.slowest}s</p>
            </div>
          </div>
        </div>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-[0.95fr_1.05fr]">
        <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
          <div className="mb-1 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-500" />
            <h3 className="text-sm font-semibold text-foreground">Weak Patterns</h3>
          </div>
          <p className="mb-5 text-xs text-muted-foreground">These habits are the clearest reasons good candidates still miss offers.</p>
          <div className="space-y-3">
            {weak_patterns.length === 0 ? (
              <p className="text-sm text-muted-foreground">No repeated weak patterns detected yet.</p>
            ) : weak_patterns.map((pattern: any) => (
              <div key={pattern.pattern} className="rounded-xl border border-border/30 bg-secondary/20 p-4">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm font-semibold text-foreground">{pattern.pattern}</p>
                  <span className="text-xs font-semibold text-amber-500">{pattern.count}x</span>
                </div>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">{pattern.impact}</p>
                <p className="mt-2 text-sm leading-6 text-foreground/85">{pattern.coaching}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
          <div className="mb-1 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-500" />
            <h3 className="text-sm font-semibold text-foreground">Question Pressure Points</h3>
          </div>
          <p className="mb-5 text-xs text-muted-foreground">The moments where the interview started getting harder for you.</p>
          {question_pressure_points.length === 0 ? (
            <p className="text-sm text-muted-foreground">No pressure points recorded yet.</p>
          ) : (
            <div className="space-y-3">
              {question_pressure_points.map((item: any, index: number) => (
                <div key={`${item.question}-${index}`} className="rounded-xl border border-border/30 bg-secondary/20 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-xs uppercase tracking-wide text-muted-foreground">{item.topic} · {item.kind}</p>
                      <p className="mt-1 text-sm font-medium text-foreground">{item.question}</p>
                    </div>
                    <span className={`shrink-0 text-xs font-semibold ${scoreColor(item.score)}`}>{Math.round(item.score)}%</span>
                  </div>
                  <p className="mt-3 text-sm leading-6 text-muted-foreground">{item.coaching}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-[0.8fr_1.2fr]">
        <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
          <h3 className="mb-1 text-sm font-semibold text-foreground">Weak Topics</h3>
          <p className="mb-5 text-xs text-muted-foreground">Areas where your average answer quality is still low.</p>
          <div className="space-y-3">
            {weak_topics.length === 0 ? (
              <p className="text-sm text-muted-foreground">No weak topics detected yet.</p>
            ) : weak_topics.map((topic: any) => (
              <div key={topic.topic} className="rounded-xl border border-border/30 bg-secondary/20 p-4">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm font-semibold text-foreground">{topic.topic}</p>
                  <span className={`text-xs font-semibold ${scoreColor(topic.avg_score)}`}>{Math.round(topic.avg_score)}%</span>
                </div>
                <p className="mt-2 text-xs text-muted-foreground">{topic.attempts} questions logged in this topic</p>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
          <h3 className="mb-1 text-sm font-semibold text-foreground">Next 3 Practice Priorities</h3>
          <p className="mb-5 text-xs text-muted-foreground">Use these as your next checklist instead of staring at raw charts.</p>
          <div className="space-y-3">
            {practice_priorities.length === 0 ? (
              <p className="text-sm text-muted-foreground">No priorities generated yet.</p>
            ) : practice_priorities.map((priority: any, index: number) => (
              <div key={`${priority.title}-${index}`} className="rounded-xl border border-border/30 bg-secondary/20 p-4">
                <p className="text-sm font-semibold text-foreground">{priority.title}</p>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">{priority.reason}</p>
                <p className="mt-2 text-sm leading-6 text-foreground/85">{priority.action}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {score_trend.length > 0 && (
        <div className="mt-6 rounded-2xl border border-border/40 bg-card shadow-sm">
          <div className="border-b border-border/30 px-6 py-4">
            <h3 className="text-sm font-semibold text-foreground">Recent Interview Sessions</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">Click to view detailed report</p>
          </div>
          <div className="divide-y divide-border/30">
            {[...score_trend].reverse().map((s: any) => (
              <a
                key={s.interview_id}
                href={`/interview/${s.interview_id}/report`}
                className="flex items-center justify-between px-6 py-3.5 transition-colors hover:bg-secondary/30"
              >
                <div className="flex min-w-0 items-center gap-4">
                  <div className={`h-2 w-2 shrink-0 rounded-full ${scoreBg(s.score)}`} />
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-foreground">{s.job_title || "General Interview"}</p>
                    <p className="text-[11px] text-muted-foreground">
                      {s.mode} · {s.interview_type} · {s.date ? new Date(s.date).toLocaleDateString() : "—"}
                    </p>
                  </div>
                </div>
                <span className={`text-sm font-semibold ${scoreColor(s.score)}`}>{Math.round(s.score)}%</span>
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Purchase History Component ──
interface Transaction {
  transaction_id: string
  amount: number
  currency: string
  payment_method: string
  payment_provider: string
  status: string
  credits_purchased: number | null
  created_at: string | null
}

function PurchaseHistory() {
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function fetchTransactions() {
      try {
        const data = await fetchPaymentTransactions(20)
        setTransactions(data.transactions || [])
      } catch {
        // silently fail — no transactions to show
      } finally {
        setLoading(false)
      }
    }
    fetchTransactions()
  }, [])

  const statusBadge = (status: string) => {
    switch (status) {
      case "completed":
        return <span className="inline-flex items-center gap-1 rounded-full bg-green-500/10 px-2 py-0.5 text-xs font-semibold text-green-600 dark:text-green-400"><Check className="h-3 w-3" /> Paid</span>
      case "pending":
        return <span className="inline-flex items-center gap-1 rounded-full bg-yellow-500/10 px-2 py-0.5 text-xs font-semibold text-yellow-600 dark:text-yellow-400"><Loader2 className="h-3 w-3 animate-spin" /> Processing</span>
      case "failed":
        return <span className="inline-flex items-center gap-1 rounded-full bg-red-500/10 px-2 py-0.5 text-xs font-semibold text-red-500"><AlertCircle className="h-3 w-3" /> Declined</span>
      case "refunded":
        return <span className="inline-flex items-center gap-1 rounded-full bg-blue-500/10 px-2 py-0.5 text-xs font-semibold text-blue-500">Refunded</span>
      default:
        return <span className="inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-xs font-semibold text-muted-foreground">{status}</span>
    }
  }

  const formatDate = (iso: string | null) => {
    if (!iso) return "—"
    const d = new Date(iso)
    return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) + " · " + d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })
  }

  return (
    <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
      <h3 className="mb-1 text-sm font-semibold text-foreground">Purchase History</h3>
      <p className="mb-4 text-xs text-muted-foreground">All your credit purchases and payment receipts</p>

      {loading ? (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          <span className="ml-2 text-sm text-muted-foreground">Loading transactions...</span>
        </div>
      ) : transactions.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border py-10">
          <CreditCard className="h-8 w-8 text-muted-foreground/40 mb-2" />
          <p className="text-sm text-muted-foreground">No purchases yet</p>
          <p className="text-xs text-muted-foreground/60 mt-1">Your transaction history will appear here</p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left">
                <th className="pb-3 pr-4 text-xs font-semibold text-muted-foreground">Date</th>
                <th className="pb-3 pr-4 text-xs font-semibold text-muted-foreground">Credits</th>
                <th className="pb-3 pr-4 text-xs font-semibold text-muted-foreground">Amount</th>
                <th className="pb-3 pr-4 text-xs font-semibold text-muted-foreground">Provider</th>
                <th className="pb-3 pr-4 text-xs font-semibold text-muted-foreground">Status</th>
                <th className="pb-3 text-xs font-semibold text-muted-foreground">Transaction ID</th>
              </tr>
            </thead>
            <tbody>
              {transactions.map((txn) => (
                <tr key={txn.transaction_id} className="border-b border-border/40 last:border-0 hover:bg-secondary/30 transition-colors">
                  <td className="py-3 pr-4 text-xs text-muted-foreground whitespace-nowrap">{formatDate(txn.created_at)}</td>
                  <td className="py-3 pr-4">
                    <span className="font-semibold text-foreground">{txn.credits_purchased ?? "—"}</span>
                    <span className="text-xs text-muted-foreground ml-1">{txn.credits_purchased === 1 ? "credit" : "credits"}</span>
                  </td>
                  <td className="py-3 pr-4 font-semibold text-foreground whitespace-nowrap">
                    ₹{txn.amount.toLocaleString("en-IN")}
                  </td>
                  <td className="py-3 pr-4 text-xs text-muted-foreground capitalize">{txn.payment_provider || txn.payment_method || "—"}</td>
                  <td className="py-3 pr-4">{statusBadge(txn.status)}</td>
                  <td className="py-3 text-xs text-muted-foreground/60 font-mono truncate max-w-[140px]" title={txn.transaction_id}>{txn.transaction_id.slice(0, 12)}…</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function SettingsContent({
  onOpenPricing,
  onOpenLogout,
  credits = defaultCredits,
  user
}: {
  onOpenPricing: () => void
  onOpenLogout: () => void
  credits?: UserCredits
  user?: AuthUser | null
}) {
  const [bugTitle, setBugTitle] = useState("")
  const [bugMessage, setBugMessage] = useState("")
  const [bugSteps, setBugSteps] = useState("")
  const [bugInterviewId, setBugInterviewId] = useState("")
  const [feedbackMessage, setFeedbackMessage] = useState("")
  const [feedbackRating, setFeedbackRating] = useState<number>(0)
  const [submittingBug, setSubmittingBug] = useState(false)
  const [submittingFeedback, setSubmittingFeedback] = useState(false)

  const submitBugReport = async () => {
    if (!bugTitle.trim() || !bugMessage.trim()) {
      toast.error("Add a title and a clear bug description.")
      return
    }

    try {
      setSubmittingBug(true)
      await createSupportSubmission({
        kind: "bug",
        title: bugTitle.trim(),
        message: bugMessage.trim(),
        steps: bugSteps.trim() || undefined,
        interview_id: bugInterviewId.trim() || undefined,
        page_url: typeof window !== "undefined" ? window.location.pathname : undefined,
      })
      toast.success("Bug report submitted.")
      setBugTitle("")
      setBugMessage("")
      setBugSteps("")
      setBugInterviewId("")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to submit bug report.")
    } finally {
      setSubmittingBug(false)
    }
  }

  const submitFeedback = async () => {
    if (!feedbackMessage.trim()) {
      toast.error("Add some feedback before sending.")
      return
    }

    try {
      setSubmittingFeedback(true)
      await createSupportSubmission({
        kind: "feedback",
        message: feedbackMessage.trim(),
        rating: feedbackRating || undefined,
        page_url: typeof window !== "undefined" ? window.location.pathname : undefined,
      })
      toast.success("Feedback sent.")
      setFeedbackMessage("")
      setFeedbackRating(0)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to send feedback.")
    } finally {
      setSubmittingFeedback(false)
    }
  }

  return (
    <div className="flex-1 overflow-y-auto p-6 md:p-8 animate-fade-in-up">
      <Tabs defaultValue="profile" className="w-full">
        <TabsList className="mb-6 w-full justify-start bg-transparent p-0">
          <TabsTrigger value="profile" className="rounded-lg data-[state=active]:bg-secondary">Profile Details</TabsTrigger>
          <TabsTrigger value="billing" className="rounded-lg data-[state=active]:bg-secondary">Billing</TabsTrigger>
          <TabsTrigger value="feedback" className="rounded-lg data-[state=active]:bg-secondary">Bug Report & Feedback</TabsTrigger>
        </TabsList>
        <TabsContent value="profile">
          <div className="space-y-6">
            <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
              <h3 className="mb-4 text-sm font-semibold text-foreground">Account Information</h3>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs text-muted-foreground">Full Name</Label>
                  <Input defaultValue={user?.name || ""} className="h-9" />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs text-muted-foreground">Email Address</Label>
                  <Input defaultValue={user?.email || ""} className="h-9" />
                </div>
              </div>
              <Button className="mt-4">Save Changes</Button>
            </div>
            {/* Danger Zone — Account Settings */}
            <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-6">
              <h3 className="mb-1 text-sm font-semibold text-red-400">Danger Zone</h3>
              <p className="mb-4 text-xs text-muted-foreground">Irreversible actions for your account</p>
              <Button variant="outline" className="border-red-500/30 text-red-400 hover:bg-red-500/10 hover:text-red-400">
                <Trash2 className="mr-2 h-4 w-4" />
                Delete Account
              </Button>
            </div>
          </div>
        </TabsContent>
        <TabsContent value="billing">
          <div className="space-y-6">
            <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
              <h3 className="mb-1 text-sm font-semibold text-foreground">Current Plan</h3>
              <p className="mb-4 text-xs text-muted-foreground">Manage your subscription and credits</p>
              <div className="flex items-center justify-between rounded-lg border border-border bg-secondary/30 p-4">
                <div>
                  <p className="font-semibold text-foreground">Current Plan</p>
                  <p className="text-xs text-muted-foreground">{credits.availableSessions} {credits.availableSessions === 'Unlimited' ? 'Sessions available' : 'Sessions remaining'}</p>
                </div>
                <Button onClick={onOpenPricing} className="gap-2 rounded-full shadow-sm">
                  <CreditCard className="h-4 w-4" />
                  Buy More Credits
                </Button>
              </div>
            </div>
            {/* Purchase History */}
            <PurchaseHistory />
          </div>
        </TabsContent>
        <TabsContent value="feedback">
          <div className="space-y-6">
            <div className="rounded-2xl border border-amber-500/20 bg-gradient-to-r from-amber-500/5 to-amber-600/5 p-5">
              <div className="flex items-start gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-500/10 shrink-0">
                  <Gift className="h-5 w-5 text-amber-500" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-foreground">Earn Free Credits!</h3>
                  <p className="mt-1 text-xs text-muted-foreground leading-relaxed">
                    Report a bug that we can verify and reproduce, and you'll receive <span className="font-bold text-amber-500">free credits</span> as a thank-you. Help us improve and practice more!
                  </p>
                </div>
              </div>
            </div>

            <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
              <div className="mb-1 flex items-center gap-2">
                <Bug className="h-4 w-4 text-red-400" />
                <h3 className="text-sm font-semibold text-foreground">Report a Bug</h3>
              </div>
              <p className="mb-5 text-xs text-muted-foreground">Found something broken? Send it into the support inbox with enough detail to reproduce it.</p>
              <div className="space-y-4">
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs text-muted-foreground">Bug Title</Label>
                  <Input
                    value={bugTitle}
                    onChange={(event) => setBugTitle(event.target.value)}
                    placeholder="e.g. Report page breaks after completing a mock interview"
                    className="h-9"
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs text-muted-foreground">Description</Label>
                  <Textarea
                    value={bugMessage}
                    onChange={(event) => setBugMessage(event.target.value)}
                    placeholder="Describe what happened, what you expected, and what actually occurred..."
                    rows={5}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs text-muted-foreground">Steps to Reproduce (optional)</Label>
                  <Textarea
                    value={bugSteps}
                    onChange={(event) => setBugSteps(event.target.value)}
                    placeholder="1. Go to...&#10;2. Click on...&#10;3. See error..."
                    rows={4}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs text-muted-foreground">Interview ID (optional)</Label>
                  <Input
                    value={bugInterviewId}
                    onChange={(event) => setBugInterviewId(event.target.value)}
                    placeholder="Attach the interview ID if this bug is tied to one session"
                    className="h-9"
                  />
                </div>
                <Button className="gap-2" onClick={submitBugReport} disabled={submittingBug}>
                  {submittingBug ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                  Submit Bug Report
                </Button>
              </div>
            </div>

            <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
              <div className="mb-1 flex items-center gap-2">
                <MessageCircle className="h-4 w-4 text-primary" />
                <h3 className="text-sm font-semibold text-foreground">Send Feedback</h3>
              </div>
              <p className="mb-5 text-xs text-muted-foreground">Tell us what is helping, what is weak, and what students need more of.</p>
              <div className="space-y-4">
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs text-muted-foreground">How would you rate your experience?</Label>
                  <div className="flex gap-1">
                    {[1, 2, 3, 4, 5].map((n) => (
                      <button
                        key={n}
                        type="button"
                        onClick={() => setFeedbackRating(n)}
                        className={`group flex h-10 w-10 items-center justify-center rounded-lg border transition-all ${feedbackRating >= n ? "border-primary/40 bg-primary/10" : "border-border/40 bg-secondary/20 hover:bg-primary/10 hover:border-primary/30"}`}
                      >
                        <Star className={`h-4 w-4 transition-colors ${feedbackRating >= n ? "fill-primary text-primary" : "text-muted-foreground group-hover:text-primary"}`} />
                      </button>
                    ))}
                  </div>
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs text-muted-foreground">Your Feedback</Label>
                  <Textarea
                    value={feedbackMessage}
                    onChange={(event) => setFeedbackMessage(event.target.value)}
                    placeholder="What do you love? What could be better? Any features you'd like to see?"
                    rows={5}
                  />
                </div>
                <Button className="gap-2" onClick={submitFeedback} disabled={submittingFeedback}>
                  {submittingFeedback ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                  Send Feedback
                </Button>
              </div>
            </div>

            {user?.is_admin && (
              <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
                <h3 className="text-sm font-semibold text-foreground">Admin Inbox</h3>
                <p className="mt-1 text-xs text-muted-foreground">Your account has admin access. Open the hidden support inbox route.</p>
                <Button className="mt-4" variant="outline" onClick={() => window.location.assign("/admin/bugs")}>
                  Open Support Inbox
                </Button>
              </div>
            )}
          </div>
        </TabsContent>
      </Tabs>
    </div>
  )
}
function PricingModal({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [creditCount, setCreditCount] = useState([5])
  const [isProcessing, setIsProcessing] = useState(false)
  const router = useRouter()
  const pricing = calculatePricing(creditCount[0])
  const handleCheckout = () => {
    setIsProcessing(true)
    onOpenChange(false)
    router.push(`/checkout?sessions=${creditCount[0]}`)
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg gap-0 overflow-hidden border-border bg-card p-0">
        <div className="p-6">
          <DialogHeader>
            <DialogTitle className="text-xl font-bold text-foreground">
              Buy Interview Credits
            </DialogTitle>
            <DialogDescription className="mt-2 text-sm leading-relaxed text-muted-foreground">
              Credits can be used for both Mock Interviews and Practice Sessions. Buy 10+ credits to unlock discounts up to {MAX_DISCOUNT_PERCENT}%!
            </DialogDescription>
          </DialogHeader>
          <div className="mt-6 space-y-6">
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold text-foreground">Interview Credits</span>
                <div className="flex items-center gap-2">
                  {pricing.hasDiscount && (
                    <span className="rounded-full bg-green-500/10 px-2 py-0.5 text-xs font-bold text-green-600 dark:text-green-400">
                      {pricing.discountPercent}% OFF
                    </span>
                  )}
                  <span className="rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-bold text-primary">
                    {creditCount[0]} {creditCount[0] === 1 ? "credit" : "credits"}
                  </span>
                </div>
              </div>
              <Slider
                value={creditCount}
                onValueChange={setCreditCount}
                max={MAX_CREDITS}
                min={MIN_CREDITS}
                step={1}
                className="py-2"
              />
              <div className="flex justify-between text-[10px] text-muted-foreground">
                <span>{MIN_CREDITS}</span>
                <span className="text-green-600 dark:text-green-400">up to {MAX_DISCOUNT_PERCENT}% discount</span>
                <span>{MAX_CREDITS}</span>
              </div>
            </div>
            <div className="space-y-3 rounded-xl border border-primary/20 bg-primary/5 p-4">
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">
                  {creditCount[0]} credits x {CURRENCY_SYMBOL}{PRICE_PER_CREDIT.toLocaleString("en-IN")}
                </span>
                <span className="text-foreground">
                  {CURRENCY_SYMBOL}{pricing.basePrice.toLocaleString("en-IN")}
                </span>
              </div>
              {pricing.hasDiscount && (
                <div className="flex items-center justify-between text-sm">
                  <span className="text-green-600 dark:text-green-400">{pricing.discountPercent}% Discount</span>
                  <span className="text-green-600 dark:text-green-400">
                    -{CURRENCY_SYMBOL}{pricing.discountAmount.toLocaleString("en-IN")}
                  </span>
                </div>
              )}
              <div className="border-t border-border pt-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-semibold text-foreground">Total</span>
                  <div className="flex items-baseline gap-2">
                    {pricing.hasDiscount && (
                      <span className="text-sm text-muted-foreground line-through">
                        {CURRENCY_SYMBOL}{pricing.basePrice.toLocaleString("en-IN")}
                      </span>
                    )}
                    <span className="text-3xl font-bold text-foreground">
                      {CURRENCY_SYMBOL}{pricing.totalPrice.toLocaleString("en-IN")}
                    </span>
                  </div>
                </div>
              </div>
            </div>
            <p className="text-center text-xs text-muted-foreground pt-4">
              Credits never expire and can be used anytime for Mock or Practice interviews.
            </p>
          </div>
        </div>
        <DialogFooter className="flex items-center gap-3 border-t border-border p-6 bg-card/50">
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={isProcessing}
            className="w-1/3"
          >
            Cancel
          </Button>
          <Button
            className="flex-1"
            onClick={handleCheckout}
            disabled={isProcessing}
          >
            {isProcessing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            {isProcessing ? "Redirecting..." : `Proceed to Checkout - ${CURRENCY_SYMBOL}${pricing.totalPrice.toLocaleString("en-IN")}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
function LogoutModal({
  open,
  onOpenChange,
  onConfirm
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onConfirm: () => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm border-border bg-card">
        <DialogHeader>
          <DialogTitle className="text-lg font-bold text-foreground">
            Are you sure you want to log out?
          </DialogTitle>
          <DialogDescription className="mt-2 text-sm text-muted-foreground">
            Your progress and history are safely stored. You can log back in anytime.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="mt-4 flex gap-3">
          <Button
            variant="outline"
            className="flex-1"
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button
            variant="destructive"
            className="flex-1"
            onClick={() => {
              onOpenChange(false)
              onConfirm()
            }}
          >
            Log Out
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
export function Dashboard({ onLogout, theme = "dark", onToggleTheme, onUploadResume, user, initialTab }: DashboardProps) {
  const [activeNav, _setActiveNav] = useState<ActiveNav>(() => {
    // Priority: URL param > sessionStorage > default
    if (initialTab) return initialTab
    if (typeof window !== "undefined") {
      const stored = sessionStorage.getItem("dashboard_tab") as ActiveNav | null
      if (stored && ["dashboard", "interview", "resume", "analytics", "settings"].includes(stored)) return stored
    }
    return "dashboard"
  })
  const setActiveNav = (nav: ActiveNav) => {
    _setActiveNav(nav)
    sessionStorage.setItem("dashboard_tab", nav)
  }
  const [showPricing, setShowPricing] = useState(false)
  const [showLogout, setShowLogout] = useState(false)
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const { justParsed } = useResume()
  const [metrics, setMetrics] = useState<DashboardMetrics>(defaultMetrics)
  const [credits, setCredits] = useState<UserCredits>(defaultCredits)
  const [interviews, setInterviews] = useState<PastInterview[]>([])
  const [loadingStats, setLoadingStats] = useState(true)
  useEffect(() => {
    async function loadDashboardData() {
      try {
        setLoadingStats(true)
        const [{ fetchDashboardStats, fetchRecentActivity }] = await Promise.all([
          import('@/lib/api')
        ])
        const [statsData, activityData] = await Promise.all([
          fetchDashboardStats().catch(() => null),
          fetchRecentActivity().catch(() => null)
        ])
        if (statsData) {
          setMetrics({
            coachingMetrics: statsData.coaching_metrics || {},
            primaryFocus: statsData.primary_focus || null,
            studentSummary: statsData.student_summary || null,
            averageScore: statsData.average_score ?? null,
            totalInterviews: statsData.total_interviews || 0,
          })
          setCredits({
            availableSessions: (statsData.plan_type === 'premium' || statsData.plan_type === 'enterprise') ? 'Unlimited' : (statsData.interviews_remaining || 0)
          })
        }
        if (activityData && activityData.activities) {
          setInterviews(
            activityData.activities.map((act: any) => ({
              id: act.interview_id,
              date: new Date(act.created_at).toLocaleDateString(),
              role: act.job_title || "General",
              type: act.interview_type === "mock" ? "Full" : "Quick",
              score: Math.round(act.overall_score || 0)
            }))
          )
        }
      } catch {
      } finally {
        setLoadingStats(false)
      }
    }
    if (activeNav === "dashboard" || activeNav === "interview") {
      loadDashboardData()
    }
  }, [activeNav])
  useEffect(() => {
    if (justParsed) {
      setActiveNav("resume")
    }
  }, [justParsed])
  const getPageTitle = () => {
    switch (activeNav) {
      case "dashboard": return "Dashboard"
      case "interview": return "Interview"
      case "resume": return "Profile"
      case "analytics": return "Analytics"
      case "settings": return "Settings"
      default: return "Dashboard"
    }
  }
  const getPageSubtitle = () => {
    switch (activeNav) {
      case "dashboard": return "Your personal interview coach"
      case "interview": return "Start practicing and improve your skills"
      case "resume": return "View and edit your parsed profile details"
      case "analytics": return "Deep dive into your performance data"
      case "settings": return "Manage your account and preferences"
      default: return "Let's prepare for your next interview."
    }
  }
  return (
    <>
      <div className="flex min-h-screen bg-background text-foreground">
        <aside className="sticky top-0 hidden h-screen w-64 flex-col border-r border-border bg-card md:flex">
          <div className="flex h-16 items-center border-b border-border px-6">
            <a
              href="/"
              onClick={(e) => { e.preventDefault(); window.location.reload(); }}
              className="flex items-center gap-1.5 transition-opacity hover:opacity-80"
            >
              <ThemeLogo size={36} />
              <span className="text-shimmer text-lg font-bold">InterAI</span>
            </a>
          </div>
          <nav className="flex flex-1 flex-col gap-1 p-4">
            {navItems.map((item) => (
              <button
                key={item.id}
                onClick={() => setActiveNav(item.id)}
                className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all duration-300 ${activeNav === item.id
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-secondary hover:text-foreground"
                  }`}
              >
                <item.icon className="h-4 w-4" />
                {item.label}
              </button>
            ))}
          </nav>
          <div className="border-t border-border p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary/10">
                  <User className="h-4 w-4 text-primary" />
                </div>
                <div className="flex flex-col">
                  <span className="text-sm font-medium text-foreground">
                    {user?.name || "User"}
                  </span>
                  <span className="text-[11px] text-muted-foreground">{user?.interviews_remaining === 0 ? "Free Plan" : "Active Plan"}</span>
                </div>
              </div>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setShowLogout(true)}
                className="h-8 w-8 text-muted-foreground hover:text-foreground"
                aria-label="Log out"
              >
                <LogOut className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </aside>
        {mobileMenuOpen && (
          <div
            className="fixed inset-0 z-40 bg-black/50 md:hidden"
            onClick={() => setMobileMenuOpen(false)}
          />
        )
        }
        <aside
          className={`fixed inset-y-0 left-0 z-50 w-64 flex-col border-r border-border bg-card transition-transform duration-300 md:hidden ${mobileMenuOpen ? "translate-x-0" : "-translate-x-full"
            }`}
        >
          <div className="flex h-16 items-center justify-between border-b border-border px-6">
            <a
              href="/"
              onClick={(e) => { e.preventDefault(); window.location.reload(); }}
              className="flex items-center gap-1.5 transition-opacity hover:opacity-80"
            >
              <ThemeLogo size={36} />
              <span className="text-shimmer text-lg font-bold">InterAI</span>
            </a>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setMobileMenuOpen(false)}
              className="h-8 w-8 text-muted-foreground hover:text-foreground"
              aria-label="Close menu"
            >
              <X className="h-5 w-5" />
            </Button>
          </div>
          <nav className="flex flex-1 flex-col gap-1 p-4">
            {navItems.map((item) => (
              <button
                key={item.id}
                onClick={() => {
                  setActiveNav(item.id)
                  setMobileMenuOpen(false)
                }}
                className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all duration-300 ${activeNav === item.id
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-secondary hover:text-foreground"
                  }`}
              >
                <item.icon className="h-4 w-4" />
                {item.label}
              </button>
            ))}
          </nav>
          <div className="border-t border-border p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary/10">
                  <User className="h-4 w-4 text-primary" />
                </div>
                <div className="flex flex-col">
                  <span className="text-sm font-medium text-foreground">
                    {user?.name || "User"}
                  </span>
                  <span className="text-[11px] text-muted-foreground">{user?.interviews_remaining === 0 ? "Free Plan" : "Active Plan"}</span>
                </div>
              </div>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => {
                  setShowLogout(true)
                  setMobileMenuOpen(false)
                }}
                className="h-8 w-8 text-muted-foreground hover:text-foreground"
                aria-label="Log out"
              >
                <LogOut className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </aside>
        <main className="flex flex-1 flex-col">
          <header className="flex h-16 items-center justify-between border-b border-border px-4 md:px-8">
            <div className="flex items-center gap-3">
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setMobileMenuOpen(true)}
                className="h-9 w-9 text-foreground md:hidden"
                aria-label="Open menu"
              >
                <svg
                  className="h-5 w-5"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M4 6h16M4 12h16M4 18h16"
                  />
                </svg>
              </Button>
              <div>
                <h1 className="text-lg font-bold text-foreground">{getPageTitle()}</h1>
                <p className="hidden text-xs text-muted-foreground sm:block">{getPageSubtitle()}</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {onToggleTheme && (
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={onToggleTheme}
                  className="h-8 w-8 text-muted-foreground hover:text-foreground"
                  aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
                >
                  {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
                </Button>
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowPricing(true)}
                className="gap-1.5 text-xs"
              >
                <Zap className="h-3.5 w-3.5 text-primary" />
                <span className="hidden sm:inline">
                  {credits.availableSessions} {credits.availableSessions === 'Unlimited' ? '' : (credits.availableSessions === 1 ? 'Session' : 'Sessions')} Left
                </span>
                <span className="sm:hidden">{credits.availableSessions}</span>
              </Button>
            </div>
          </header>
          <>
            {(() => {
              switch (activeNav) {
                case "dashboard":
                  return <DashboardContent onOpenPricing={() => setShowPricing(true)} metrics={metrics} credits={credits} setActiveNav={setActiveNav} />
                case "interview":
                  return <InterviewContent onOpenPricing={() => setShowPricing(true)} credits={credits} interviews={interviews} setActiveNav={setActiveNav} />
                case "resume":
                  return <ResumeContent onUploadResume={onUploadResume} />
                case "analytics":
                  return <AnalyticsContent />
                case "settings":
                  return <SettingsContent onOpenPricing={() => setShowPricing(true)} onOpenLogout={() => setShowLogout(true)} credits={credits} user={user} />
                default:
                  return null
              }
            })()}
          </>
        </main>
      </div>
      <PricingModal open={showPricing} onOpenChange={setShowPricing} />
      <LogoutModal open={showLogout} onOpenChange={setShowLogout} onConfirm={onLogout} />
    </>
  )
}
