"use client"
import { useState, useEffect, useRef, useCallback } from "react"
import { createPortal } from "react-dom"
import { useRouter } from "next/navigation"
import { ThemeLogo } from "@/components/theme-logo"
import {
  FileText,
  BarChart3,
  Settings,
  User,
  LogOut,
  Flame,
  Sun,
  Moon,
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
  X,
  Check,
  Edit3,
  Save,
  Play,
  AlertTriangle,
  CreditCard,
  Eye,
  Loader2,
  Bug,
  MessageCircle,
  Send,
  Star,
  Target,
  Wrench,
  GitBranch,
  BadgeCheck,
  PanelLeft,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { SlidingSegmentControl } from "@/components/sliding-segment-control"
import { SlidingSidebarNav } from "@/components/sliding-sidebar-nav"
import { ImproveContent as MissionImproveContent } from "@/components/improve/improve-content"
import { PerformanceContent } from "@/components/performance/performance-content"
import { InterviewSetupWizard, type BlueprintRuntimeChoice } from "@/components/interview-setup-wizard"
import { ResumeAssetsManager } from "@/components/resume-assets-manager"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import { toast } from "sonner"
import { safeStorageGet, safeStorageRemove, safeStorageSet } from "@/lib/safe-storage"
import { Tabs, TabsContent } from "@/components/ui/tabs"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog"
import { AuthUser } from "@/lib/auth"
import { PremiumBackground } from "./premium-background"
import {
  getTechnicalPermissionState,
  releaseTechnicalPermissions,
  subscribeTechnicalPermissionState,
  type TechnicalPermissionState,
} from "@/lib/technical-permissions"
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
  startInterviewFromBlueprint,
  cancelInterviewSession,
  createSupportSubmission,
  fetchInterviewProfile,
  updateInterviewProfile,
  changePassword,
  deleteAccount,
  updateAccountInfo,
  uploadAvatar,
  exportUserData,
  getNotificationPrefs,
  updateNotificationPrefs,
  fetchPaymentTransactions,
  fetchPaymentPlans,
  fetchTechnicalRoundHistory,
  fetchLearningDashboard,
  reconcilePerformance,
  prepareTechnicalRounds,
} from "@/lib/api"
import type { ExactImproveTarget, InterviewBlueprint, InterviewProfileOption, InterviewProfileType, LearningDashboard, NotificationPrefs, TechnicalRoundHistoryItem, TechnicalRoundSession } from "@/lib/api"
import { useResume } from "@/context/resume-context"
import type { ResumeData } from "@/types/resume"
import { RESUME_MAX_FILE_BYTES } from "@/lib/config"

function isSupportedResumeFile(file: File) {
  const name = file.name.toLowerCase()
  const type = file.type.toLowerCase()
  return (
    name.endsWith(".pdf") ||
    name.endsWith(".docx") ||
    type.includes("pdf") ||
    type.includes("document") ||
    type.includes("wordprocessingml")
  )
}
interface AppShellProps {
  onLogout: () => void
  onUserUpdate?: (updates: Partial<AuthUser>) => void
  theme?: "light" | "dark"
  onToggleTheme?: () => void
  user?: AuthUser | null
  initialTab?: string
  initialImproveTarget?: ExactImproveTarget | null
}
type ActiveNav = "improve" | "interview" | "coding" | "resume" | "performance" | "membership" | "settings"
const INTERVIEW_PROFILE_STORAGE_KEY = "interview-profile-type"

function readCachedProfileType(): InterviewProfileType {
  if (typeof window === "undefined") return "top_tier"
  const cached = safeStorageGet("session", INTERVIEW_PROFILE_STORAGE_KEY)
  if (cached === "top_tier" || cached === "mid_tier" || cached === "startup" || cached === "custom") return cached
  return "top_tier"
}

function cacheProfileType(profileType: InterviewProfileType) {
  if (typeof window === "undefined") return
  safeStorageSet("session", INTERVIEW_PROFILE_STORAGE_KEY, profileType)
}
const primaryNavItems: { icon: any; label: string; id: ActiveNav }[] = [
  { icon: FileText, label: "Resume", id: "resume" },
  { icon: Play, label: "Interview Round", id: "interview" },
  { icon: Code, label: "Technical Round", id: "coding" },
  { icon: BarChart3, label: "Performance", id: "performance" },
  { icon: Target, label: "Improve", id: "improve" },
]
const secondaryNavItems: { icon: any; label: string; id: ActiveNav }[] = [
  { icon: CreditCard, label: "Membership", id: "membership" },
  { icon: Settings, label: "Settings", id: "settings" },
]
const defaultInterviewProfileOptions: InterviewProfileOption[] = [
  {
    profile_type: "top_tier",
    label: "Top Tier",
    interview_instruction: "Rigorous project-depth interview with tough follow-ups.",
    technical_instruction: "Medium-hard DSA first: arrays, strings, hash maps, trees, graphs, DP, heaps, binary search, sliding window, backtracking, complexity, and edge cases.",
    behavioral_instruction: "Analytical behavioral questioning around failures, metrics, trade-offs, and proof.",
    duration: { min_minutes: 40, target_minutes: 55, max_minutes: 55 },
  },
  {
    profile_type: "mid_tier",
    label: "Mid Tier",
    interview_instruction: "In-depth but balanced interview focused on skill validation.",
    technical_instruction: "Medium DSA first: arrays, strings, hash maps, trees, graphs, heaps, binary search, sliding window, recursion, complexity, and edge cases.",
    behavioral_instruction: "Structured teamwork, execution, prioritization, and communication questions.",
    duration: { min_minutes: 40, target_minutes: 50, max_minutes: 55 },
  },
  {
    profile_type: "startup",
    label: "Startup",
    interview_instruction: "Practical, ownership-focused interview with some rigor.",
    technical_instruction: "Practical DSA first: arrays, strings, hash maps, queues, trees, graph basics, sorting, binary search, recursion, complexity, and edge cases.",
    behavioral_instruction: "Fast execution, ownership, uncertainty, and shipping trade-off questions.",
    duration: { min_minutes: 40, target_minutes: 45, max_minutes: 55 },
  },
  {
    profile_type: "custom",
    label: "Custom",
    interview_instruction: "Role- and JD-specific interview coverage with targeted follow-ups.",
    technical_instruction: "Role- and JD-specific technical topics, round mix, and difficulty.",
    behavioral_instruction: "Execution and collaboration questions aligned to the selected job target.",
    duration: { min_minutes: 40, target_minutes: 50, max_minutes: 55 },
  },
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
  score: number | null
  status?: string
  cta?: {
    label?: string
    nav?: ActiveNav | string
    entity_id?: string | number | null
    mode?: string | null
    mission_id?: string | null
    roadmap_node_id?: string | null
    exercise_id?: string | null
  }
  duration?: number | null
  created_at?: string | null
}
function getPlanLabel(planType?: string | null) {
  const normalized = (planType || "starter").toLowerCase()
  if (normalized.includes("premium")) return "Premium"
  if (normalized.includes("pro")) return "Pro"
  return "Free"
}

function getDashboardBackgroundMode(planType?: string | null): "base" | "comets" {
  const normalized = (planType || "starter").toLowerCase()
  if (normalized === "free") return "base"
  if (normalized.includes("premium")) return "comets"
  if (normalized.includes("pro")) return "comets"
  return "base"
}

function renderPlanBadge(planType?: string | null) {
  const normalized = (planType || "starter").toLowerCase()
  if (normalized.includes("premium")) {
    return (
      <span className="mt-0.5 inline-flex items-center gap-1 rounded border border-border bg-secondary px-2 py-0.5 text-xs font-semibold text-foreground self-start">
        Premium
      </span>
    )
  }
  if (normalized.includes("pro")) {
    return (
      <span className="mt-0.5 inline-flex items-center gap-1 rounded border border-border bg-secondary px-2 py-0.5 text-xs font-semibold text-foreground self-start">
        Pro
      </span>
    )
  }
  return (
    <span className="mt-0.5 inline-flex items-center rounded bg-secondary/40 border border-border/50 px-2 py-0.5 text-xs font-semibold text-muted-foreground self-start">
      Free
    </span>
  )
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
    softSkills: (data.softSkills || []).join(", "),
    certifications: (data.certifications || []).map((c) => c.name).join("\n"),
    achievements: (data.achievements || []).join("\n"),
    languages: (data.languages || []).map((l) => l.name).join(", "),
    interests: (data.interests || []).join(", "),
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

function createClientIdempotencyKey(prefix: string) {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`
}
export { InterviewContent, ResumeContent }

function isPlanStartError(message: string) {
  const lower = message.toLowerCase()
  return (
    lower.includes("limit reached") ||
    lower.includes("no interviews remaining") ||
    lower.includes("no credits") ||
    lower.includes("technical rounds are locked") ||
    lower.includes("requires the premium plan") ||
    lower.includes("require the premium plan") ||
    lower.includes("require the pro or premium plan") ||
    lower.includes("your plan includes") ||
    lower.includes("purchase") ||
    lower.includes("upgrade")
  )
}

function isProfileStartError(message: string) {
  const lower = message.toLowerCase()
  return lower.includes("profile") || lower.includes("missing")
}

function InterviewContent({
  interviews = [],
  setActiveNav,
  mode = "interview",
  user
}: {
  interviews?: PastInterview[]
  setActiveNav: (nav: ActiveNav) => void
  mode?: "interview" | "technical"
  user?: AuthUser | null
}) {
  const router = useRouter()
  const [isStartingMock, setIsStartingMock] = useState(false)
  const [isStartingTechnical, setIsStartingTechnical] = useState(false)
  const [mockStartMessage, setMockStartMessage] = useState("")
  const [technicalStartMessage, setTechnicalStartMessage] = useState("")
  const [technicalPermissionError, setTechnicalPermissionError] = useState("")
  const [technicalPermissionState, setTechnicalPermissionState] = useState<TechnicalPermissionState>(() => getTechnicalPermissionState())
  const [mockPreflightOpen, setMockPreflightOpen] = useState(false)
  const [technicalPreflightOpen, setTechnicalPreflightOpen] = useState(false)
  const [selectedProfileType, setSelectedProfileType] = useState<InterviewProfileType>(readCachedProfileType)
  const [profileOptions, setProfileOptions] = useState<InterviewProfileOption[]>(defaultInterviewProfileOptions)
  const [loadingProfile, setLoadingProfile] = useState(true)
  const [technicalSessions, setTechnicalSessions] = useState<TechnicalRoundSession[]>([])
  const [loadingTechnicalRounds, setLoadingTechnicalRounds] = useState(false)
  const [technicalHistoryError, setTechnicalHistoryError] = useState("")
  const [customJobTitle, setCustomJobTitle] = useState("")
  const [customJobDescription, setCustomJobDescription] = useState("")
  const [companyName, setCompanyName] = useState("")
  const [readyBlueprint, setReadyBlueprint] = useState<InterviewBlueprint | null>(null)
  const [runtimeChoice, setRuntimeChoice] = useState<BlueprintRuntimeChoice>({ inputMode: "voice", cameraEnabled: true, interviewMode: "mock" })
  const openBillingSettings = () => {
    if (typeof window !== "undefined") {
      safeStorageSet("session", "settings_tab", "billing")
    }
    setActiveNav("settings")
  }

  useEffect(() => {
    async function loadInterviewProfile() {
      try {
        setLoadingProfile(true)
        const data = await fetchInterviewProfile()
        setSelectedProfileType((current) => {
          const next = data.profile_type
          if (current === next) return current
          return next
        })
        cacheProfileType(data.profile_type)
        if (Array.isArray(data.options) && data.options.length > 0) {
          setProfileOptions(data.options)
        }
      } catch (error: any) {
        console.warn("Failed to load interview profile; using default profile options.", error)
      } finally {
        setLoadingProfile(false)
      }
    }
    loadInterviewProfile()
  }, [])
  const visibleProfileOptions = profileOptions

  const loadTechnicalRounds = useCallback(async () => {
    if (mode !== "technical") return
    setLoadingTechnicalRounds(true)
    setTechnicalHistoryError("")
    try {
      const data = await fetchTechnicalRoundHistory()
      setTechnicalSessions(data.sessions || [])
    } catch (error: any) {
      setTechnicalHistoryError(error?.message || "Failed to load technical rounds.")
    } finally {
      setLoadingTechnicalRounds(false)
    }
  }, [mode])

  useEffect(() => {
    if (mode !== "technical") return
    const unsubscribe = subscribeTechnicalPermissionState(setTechnicalPermissionState)
    void loadTechnicalRounds()
    return unsubscribe
  }, [loadTechnicalRounds, mode])

  const handleSelectProfile = async (profileType: InterviewProfileType) => {
    setSelectedProfileType(profileType)
    cacheProfileType(profileType)
    try {
      await updateInterviewProfile(profileType)
    } catch (error: any) {
      toast.error(error?.message || "Failed to save interview profile.")
    }
  }

  const startMockInterview = async (preflightId: string, blueprint: InterviewBlueprint, runtime: BlueprintRuntimeChoice) => {
    if (!blueprint?.blueprint_id) {
      toast.error("Prepare your interview before starting.")
      return
    }
    setIsStartingMock(true)
    setMockStartMessage("Preparing interview environment")
    try {
      setMockStartMessage("Creating your mock interview")
      const response = await startInterviewFromBlueprint(
        blueprint.blueprint_id,
        createClientIdempotencyKey("mock-start"),
        {
          input_mode: runtime.inputMode,
          camera_mode: "required",
          preflight_id: preflightId,
        },
      )
      const interviewId = response.interview_id || response.session_id
      if (!interviewId) throw new Error("The server did not return an interview ID.")
      setMockStartMessage("Opening interview room")
      const params = new URLSearchParams({
        mode: "mock-voice",
        input: runtime.inputMode,
        camera: "required",
      })
      router.push(`/interview/${interviewId}?${params.toString()}`)
    } catch (error: any) {
      const msg = error?.message || "Failed to start mock interview."
      if (isPlanStartError(msg)) {
        toast.error(msg)
        openBillingSettings()
      } else if (isProfileStartError(msg)) {
        toast.error(msg)
        setActiveNav("resume")
      } else {
        toast.error(msg)
      }
    } finally {
      setIsStartingMock(false)
      setMockStartMessage("")
    }
  }

  const openMockPreflight = () => {
    setMockPreflightOpen(true)
  }

  const openTechnicalPreflight = () => {
    setTechnicalPermissionError("")
    setTechnicalStartMessage("")
    setTechnicalPreflightOpen(true)
  }

  const handleBlueprintReady = (blueprint: InterviewBlueprint, runtime: BlueprintRuntimeChoice, preflightId: string) => {
    setReadyBlueprint(blueprint)
    setRuntimeChoice(runtime)
    if (mode === "technical") void startTechnicalInterview(preflightId, blueprint)
    else void startMockInterview(preflightId, blueprint, runtime)
  }

  const startTechnicalInterview = async (preflightId: string, blueprint: InterviewBlueprint) => {
    if (!blueprint?.blueprint_id) {
      toast.error("Prepare your technical round before starting.")
      return
    }
    setIsStartingTechnical(true)
    setTechnicalStartMessage("Creating technical session")
    let interviewId = ""
    try {
      const response = await startInterviewFromBlueprint(
        blueprint.blueprint_id,
        createClientIdempotencyKey("technical-start"),
        { input_mode: "text", camera_mode: "required", preflight_id: preflightId },
      )
      interviewId = response.interview_id || response.session_id
      if (!interviewId) throw new Error("The server did not return an interview ID.")
      setTechnicalStartMessage("Preparing coding questions")
      const prepared = await prepareTechnicalRounds(interviewId)
      if (!prepared?.rounds?.length) {
        throw new Error("Technical questions were not generated. Please try again.")
      }
      setTechnicalStartMessage("Opening workspace")
      router.push(`/interview/${interviewId}/technical`)
    } catch (error: any) {
      if (interviewId) {
        await cancelInterviewSession(interviewId).catch(() => null)
      }
      await releaseTechnicalPermissions()
      const msg = error?.message || "Failed to start technical interview."
      setTechnicalPermissionError(msg)
      if (isPlanStartError(msg)) {
        toast.error(msg)
        openBillingSettings()
      } else if (isProfileStartError(msg)) {
        toast.error(msg)
        setActiveNav("resume")
      } else {
        toast.error(msg)
      }
    } finally {
      setIsStartingTechnical(false)
      setTechnicalStartMessage("")
    }
  }

  const formatRoundType = (value: string) => value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase())
  const formatDate = (value: string | null) => value ? new Date(value).toLocaleDateString() : "Not recorded"

  const formatActivityDate = (value: string | null | undefined) => {
    if (!value) return "Not recorded"
    const date = new Date(value)
    try {
      const datePart = date.toLocaleDateString("en-GB", { day: "2-digit", month: "2-digit", year: "numeric" })
      const timePart = date.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: true })

      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone
      let tzName = ""
      if (tz && (tz.includes("Kolkata") || tz.includes("Calcutta") || tz === "Asia/Kolkata" || tz === "Asia/Calcutta")) {
        tzName = "IST"
      } else {
        try {
          const parts = new Intl.DateTimeFormat("en-US", { timeZoneName: "short" }).formatToParts(date)
          const tzPart = parts.find(p => p.type === "timeZoneName")
          tzName = tzPart ? tzPart.value : ""
        } catch (e) {}
      }

      return `${datePart}, ${timePart}${tzName ? " " + tzName : ""}`
    } catch (e) {
      return date.toLocaleString()
    }
  }

  const formatDuration = (seconds: number | null | undefined) => {
    if (seconds === undefined || seconds === null) return "\u2014"
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    return `${m}m ${s}s`
  }
  const profileSegmentOptions = visibleProfileOptions.map((profile) => ({
    value: profile.profile_type,
    label: profile.label,
    icon: profile.profile_type === "top_tier"
      ? <BadgeCheck className="h-4 w-4" />
      : profile.profile_type === "startup"
        ? <GitBranch className="h-4 w-4" />
        : profile.profile_type === "custom"
          ? <Wrench className="h-4 w-4" />
          : <Briefcase className="h-4 w-4" />,
  }))

  return (
    <div className="flex-1 overflow-y-auto p-6 md:p-8">
      <div className="mb-8 rounded-xl card-elevated p-7">
        <InterviewSetupWizard
          key={mode}
          mode={mode}
          disabled={isStartingMock || isStartingTechnical}
          onReady={handleBlueprintReady}
        />
        {false && (
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="space-y-4">

            <SlidingSegmentControl
              ariaLabel="Profile type"
              options={profileSegmentOptions}
              value={selectedProfileType}
              onValueChange={handleSelectProfile}
              className="dashboard-segment-tabs w-fit max-w-full gap-1 rounded-full border-0 bg-card p-1.5 shadow-[0_14px_36px_rgba(15,23,42,0.06)] dark:shadow-[0_16px_38px_rgba(0,0,0,0.2)]"
              buttonClassName="h-10 px-4"
              shape="pill"
            />
            {selectedProfileType === "custom" && (
              <div className="mt-4 space-y-4 rounded-xl border border-border/40 bg-zinc-950/20 p-5 shadow-sm animate-fade-in-up w-full">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-1.5">
                    <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Custom Role Title</label>
                    <input
                      type="text"
                      placeholder="e.g. Senior Backend Engineer"
                      value={customJobTitle}
                      onChange={(e) => setCustomJobTitle(e.target.value)}
                      className="w-full rounded-lg border border-border/50 bg-background px-3.5 py-2 text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary transition-all shadow-inner"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Company Name</label>
                    <input
                      type="text"
                      placeholder="e.g. Acme Corp"
                      value={companyName}
                      onChange={(e) => setCompanyName(e.target.value)}
                      className="w-full rounded-lg border border-border/50 bg-background px-3.5 py-2 text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary transition-all shadow-inner"
                    />
                  </div>
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Custom Job Description</label>
                  <textarea
                    placeholder="Paste the job description here..."
                    value={customJobDescription}
                    onChange={(e) => setCustomJobDescription(e.target.value)}
                    className="min-h-[140px] w-full rounded-lg border border-border/50 bg-background px-3.5 py-2.5 text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary transition-all resize-y shadow-inner leading-relaxed"
                  />
                </div>
              </div>
            )}
          </div>
          {mode === "technical" ? (
            <Button
              onClick={openTechnicalPreflight}
              disabled={
                isStartingTechnical ||
                loadingProfile ||
                (selectedProfileType === "custom" && (!customJobTitle.trim() || !customJobDescription.trim() || !companyName.trim()))
              }
              className="gap-2 rounded-lg px-6"
            >
              {isStartingTechnical ? <Loader2 className="h-4 w-4 animate-spin" /> : <Code className="h-4 w-4" />}
              {isStartingTechnical ? "Starting..." : "Start Technical Round"}
            </Button>
          ) : (
            <Button
              onClick={openMockPreflight}
              disabled={
                isStartingMock ||
                loadingProfile ||
                (selectedProfileType === "custom" && (!customJobTitle.trim() || !customJobDescription.trim() || !companyName.trim()))
              }
              className="gap-2 rounded-lg px-6"
            >
              {isStartingMock ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              {isStartingMock ? "Starting..." : "Start Interview"}
            </Button>
          )}
        </div>
        )}
      </div>

      {technicalPermissionError && mode === "technical" && (
        <div className="mb-6 rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {technicalPermissionError}
        </div>
      )}

      {mode === "technical" ? (
        <div className="dashboard-card overflow-hidden p-0">
          <div className={!loadingTechnicalRounds && !technicalHistoryError && technicalSessions.length === 0 ? "p-5" : "border-b border-border/20 p-6"}>
            <h3 className="text-base font-semibold text-foreground">Technical Rounds</h3>
            {!loadingTechnicalRounds && !technicalHistoryError && technicalSessions.length === 0 && (
              <p className="mt-1 text-sm text-muted-foreground">
                Your completed technical rounds will appear here.
              </p>
            )}
          </div>
          {(loadingTechnicalRounds || Boolean(technicalHistoryError) || technicalSessions.length > 0) && <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-border">
                  <th className="px-6 py-3 text-left text-xs font-medium text-muted-foreground">Date</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-muted-foreground">Type</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-muted-foreground">Start Time</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-muted-foreground">Duration</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-muted-foreground">Score</th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-muted-foreground">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {loadingTechnicalRounds ? (
                  <tr>
                    <td colSpan={6} className="px-6 py-12 text-center">
                      <div className="flex flex-col items-center gap-2">
                        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground/50" />
                        <p className="text-sm text-muted-foreground">Loading technical rounds</p>
                      </div>
                    </td>
                  </tr>
                ) : technicalHistoryError ? (
                  <tr>
                    <td colSpan={6} className="px-6 py-10 text-center">
                      <p className="text-sm text-destructive">{technicalHistoryError}</p>
                      <Button variant="outline" size="sm" className="mt-3" onClick={() => void loadTechnicalRounds()}>Try again</Button>
                    </td>
                  </tr>
                ) : (
                  technicalSessions.map((session) => {
                    const rounds = session.rounds || []
                    const firstRound = rounds[0]
                    if (!firstRound) return null

                    // Aggregate score across all rounds in the session
                    let totalPassed = 0
                    let totalTests = 0
                    let totalRuns = 0
                    let totalSuccessfulRuns = 0
                    for (const round of rounds) {
                      totalPassed += (round.visible_passed || 0) + (round.hidden_passed || 0)
                      totalTests += (round.visible_total || 0) + (round.hidden_total || 0)
                      totalRuns += round.run_count || 0
                      totalSuccessfulRuns += round.successful_runs || 0
                    }
                    const successRate: number | null = totalTests > 0
                      ? Math.round((totalPassed / totalTests) * 100)
                      : totalRuns > 0
                        ? Math.round((totalSuccessfulRuns / totalRuns) * 100)
                        : null

                    // Start time from first round
                    const sessionCreatedAt = firstRound.created_at
                    const startTime = sessionCreatedAt
                      ? new Date(sessionCreatedAt).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', timeZoneName: 'short' })
                      : "Unknown"

                    // Duration: compute from session start to completion/last activity
                    let duration = typeof session.duration_seconds === "number"
                      ? formatDuration(session.duration_seconds)
                      : ""
                    const endTime = session.interview_completed_at
                      || rounds.reduce((latest: string | null, r) => {
                        const candidate = r.completed_at || r.last_run_at
                        if (!candidate) return latest
                        if (!latest) return candidate
                        return new Date(candidate) > new Date(latest) ? candidate : latest
                      }, null as string | null)

                    if (!duration && sessionCreatedAt && endTime) {
                      const start = new Date(sessionCreatedAt).getTime()
                      const end = new Date(endTime).getTime()
                      const diffMs = Math.max(0, end - start)
                      const diffMins = Math.floor(diffMs / 60000)
                      if (diffMins <= 180) {
                        const diffSecs = Math.floor((diffMs % 60000) / 1000)
                        duration = `${diffMins}m ${diffSecs}s`
                      }
                    }
                    if (!duration) duration = "—"

                    const profileTypeFormatted = (session.profile_type || firstRound.profile_type || "technical")
                      .replace(/_/g, " ")
                      .replace(/\b\w/g, (char: string) => char.toUpperCase())

                    return (
                      <tr key={session.interview_id} className="transition-colors hover:bg-secondary/30">
                        <td className="whitespace-nowrap px-6 py-4 text-sm text-foreground">{formatDate(sessionCreatedAt)}</td>
                        <td className="whitespace-nowrap px-6 py-4 text-sm text-foreground capitalize">
                          {profileTypeFormatted}
                        </td>
                        <td className="whitespace-nowrap px-6 py-4 text-sm text-foreground">{startTime}</td>
                        <td className="whitespace-nowrap px-6 py-4 text-sm text-foreground">{duration}</td>
                        <td className="whitespace-nowrap px-6 py-4">
                          <div className="flex items-center gap-2">
                            <div className="h-2 w-16 overflow-hidden rounded-full bg-border">
                              <div
                                className={`h-full rounded-full ${successRate === null ? "bg-muted-foreground/30" : successRate >= 80 ? "bg-green-500" : successRate >= 50 ? "bg-amber-500" : "bg-red-500"}`}
                                style={{ width: `${successRate ?? 0}%` }}
                              />
                            </div>
                            <span className="text-sm font-medium text-foreground">{successRate === null ? "Unknown" : `${successRate}%`}</span>
                          </div>
                        </td>
                        <td className="whitespace-nowrap px-6 py-4 text-right">
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={session.cta?.nav !== "report"}
                            className={session.cta?.nav === "report" ? "gap-1.5 text-primary" : "gap-1.5 cursor-not-allowed text-muted-foreground hover:bg-transparent"}
                            onClick={() => {
                              if (session.cta?.nav !== "report") return
                              router.push(`/interview/${session.interview_id}/report`)
                            }}
                          >
                            <Eye className="h-3.5 w-3.5" />
                            {session.cta?.label || "Report unavailable"}
                          </Button>
                        </td>
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          </div>}
        </div>
      ) : (
      <div className="dashboard-card overflow-hidden p-0">
        <div className={interviews.length === 0 ? "p-5" : "border-b border-border/20 p-6"}>
          <h3 className="text-base font-semibold text-foreground">Past Interviews</h3>
          {interviews.length === 0 && (
            <p className="mt-1 text-sm text-muted-foreground">
              Your completed interviews will appear here.
            </p>
          )}
        </div>
        {interviews.length > 0 && <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-border">
                <th className="px-6 py-3 text-left text-xs font-medium text-muted-foreground">Date</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-muted-foreground">Target Role</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-muted-foreground">Duration</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-muted-foreground">Overall Score</th>
                <th className="px-6 py-3 text-right text-xs font-medium text-muted-foreground">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {interviews.map((interview) => (
                  <tr key={interview.id} className="transition-colors hover:bg-secondary/30">
                    <td className="whitespace-nowrap px-6 py-4 text-sm text-foreground">
                      {formatActivityDate(interview.created_at)}
                    </td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm text-foreground">{interview.role}</td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm text-foreground">
                      {formatDuration(interview.duration)}
                    </td>
                    <td className="whitespace-nowrap px-6 py-4">
                      <div className="flex items-center gap-2">
                        <div className="h-2 w-16 overflow-hidden rounded-full bg-border">
                          <div
                            className={`h-full rounded-full ${interview.score === null ? "bg-muted-foreground/30" : interview.score >= 80 ? "bg-green-500" : interview.score >= 60 ? "bg-amber-500" : "bg-red-500"
                              }`}
                            style={{ width: `${interview.score ?? 0}%` }}
                          />
                        </div>
                        <span className="text-sm font-medium text-foreground">{interview.score === null ? "Unknown" : `${interview.score}%`}</span>
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-6 py-4 text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={interview.cta?.nav === "generating" || interview.cta?.nav === "unavailable"}
                        className={`gap-1.5 ${
                          interview.cta?.nav === "generating" || interview.cta?.nav === "unavailable"
                            ? "text-muted-foreground cursor-not-allowed hover:bg-transparent"
                            : "text-primary"
                        }`}
                        onClick={() => {
                          if (interview.cta?.nav === "generating" || interview.cta?.nav === "unavailable") return
                          const entityId = interview.cta?.entity_id || interview.id
                          if (interview.cta?.nav === "dashboard" || interview.cta?.nav === "improve") {
                            if (interview.cta.mission_id && interview.cta.roadmap_node_id && interview.cta.exercise_id) {
                              const params = new URLSearchParams({
                                tab: "improve",
                                mode: interview.cta.mode === "technical" ? "technical" : "interview",
                                mission_id: interview.cta.mission_id,
                                roadmap_node_id: interview.cta.roadmap_node_id,
                                exercise_id: interview.cta.exercise_id,
                              })
                              window.location.assign(`/?${params.toString()}`)
                            } else {
                              setActiveNav("improve")
                            }
                            return
                          }
                          router.push(`/interview/${entityId}/report`)
                        }}
                      >
                        {interview.cta?.nav === "generating" ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Eye className="h-3.5 w-3.5" />
                        )}
                        {interview.cta?.label || "View Full Report"}
                      </Button>
                    </td>
                  </tr>
              ))}
            </tbody>
          </table>
        </div>}
      </div>
      )}
      <StartPreparationOverlay
        show={isStartingMock}
        title="Preparing interview"
        message={mockStartMessage || "Starting your interview"}
      />
      <StartPreparationOverlay
        show={isStartingTechnical}
        title="Starting technical round"
        message={technicalStartMessage || "Preparing your coding workspace"}
      />
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
          <span key={skill} className="rounded-md border border-primary/15 bg-primary/5 px-2.5 py-1 text-xs font-medium text-primary">
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
function ResumeContent() {
  const { resumeData: contextResumeData, isLoading, justParsed, setJustParsed, setResumeData: setContextResumeData } = useResume()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [isUploading, setIsUploading] = useState(false)
  const [isEditing, setIsEditing] = useState(false)
  const [resumeData, setResumeData] = useState<DashboardResumeData>(emptyResumeData)
  const [editData, setEditData] = useState<DashboardResumeData>(emptyResumeData)
  const [assetsRefreshKey, setAssetsRefreshKey] = useState(0)
  const [activeResumeId, setActiveResumeId] = useState<string | null>(contextResumeData?.metadata?.resumeId || null)
  const hasData = Boolean(contextResumeData)

  const openFilePicker = () => {
    if (isUploading) return
    fileInputRef.current?.click()
  }

  const handleFileSelected = async (file: File) => {
    if (!isSupportedResumeFile(file)) {
      toast.error("Please upload a PDF or DOCX file")
      return
    }
    if (file.size > RESUME_MAX_FILE_BYTES) {
      toast.error("File size must be 4MB or less")
      return
    }

    setIsUploading(true)
    try {
      const { parsedData } = await uploadResume(file)
      setContextResumeData(parsedData)
      setActiveResumeId(parsedData.metadata?.resumeId || null)
      setAssetsRefreshKey((value) => value + 1)
      setJustParsed(true)
      toast.success("Your profile is ready", {
        description: "We've updated your details.",
      })
    } catch (err) {
      const error = err as { message?: string }
      toast.error(error.message || "Something went wrong. Please try again.")
    } finally {
      setIsUploading(false)
    }
  }
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
        languages: editData.languages.split(",").map(l => l.trim()).filter(Boolean).map(l => ({ name: l, proficiency: 'professional' })),
        softSkills: editData.softSkills.split(",").map(s => s.trim()).filter(Boolean),
        achievements: editData.achievements.split("\n").map(a => a.trim()).filter(Boolean),
        interests: editData.interests.split(",").map(i => i.trim()).filter(Boolean),
      }
      await submitResume(dataToSubmit, activeResumeId || undefined)
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
  return (
    <div className="relative flex-1 overflow-y-auto p-6 md:p-8">
      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf,.docx"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          e.target.value = ""
          if (file) void handleFileSelected(file)
        }}
      />
      <ResumeAssetsManager
        refreshKey={assetsRefreshKey}
        onActiveResumeId={setActiveResumeId}
        onResumeActivated={(nextResume) => {
          setContextResumeData(nextResume)
          setJustParsed(false)
        }}
      />
      {!hasData ? (
        <div
          className="relative flex min-h-[400px] cursor-pointer flex-col items-center justify-center rounded-2xl empty-state-premium p-12 transition-all duration-300 hover:opacity-90"
          onClick={openFilePicker}
        >
          <div className="mb-6 flex h-20 w-20 items-center justify-center rounded-2xl bg-primary/10">
            <Upload className="h-10 w-10 text-primary" />
          </div>
          <h2 className="text-xl font-bold text-foreground">Upload Your Resume</h2>
          <p className="mt-2 text-sm text-muted-foreground">PDF or DOCX, up to 4MB</p>
          <Button
            onClick={(e) => {
              e.stopPropagation()
              openFilePicker()
            }}
            disabled={isUploading}
            className="mt-6 gap-2 rounded-full px-8 shadow-sm"
          >
            <Upload className="h-4 w-4" />
            {isUploading ? "Uploading..." : "Upload PDF or DOCX"}
          </Button>
        </div>
      ) : (
        <>
          <div className="flex flex-col gap-6 lg:flex-row">
          <div className="flex-1 space-y-6">
            <div className="dashboard-card">
              <div className="mb-4 flex items-center justify-between">
                <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                  <User className="h-4 w-4 text-primary" />
                  Personal Profile
                </h3>
                <div className="flex items-center gap-2">
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
            <div className="dashboard-card">
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
            <div className="dashboard-card">
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
            <div className="dashboard-card">
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
                  <div key={i} className="sub-card relative flex flex-col gap-1 rounded-lg p-3">
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
            <div className="dashboard-card">
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
                  <div key={i} className="sub-card relative flex flex-col gap-1 rounded-lg p-3">
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
            <div className="dashboard-card" >
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
                  <div key={i} className="relative sub-card rounded-lg p-4">
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
                  <div key={i} className="sub-card rounded-lg p-4">
                    <p className="text-sm font-medium text-foreground">{proj.name}</p>
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {proj.techStack.split(",").map((tech) => tech.trim()).filter(Boolean).map((tech) => (
                        <span key={tech} className="rounded-md bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">{tech}</span>
                      ))}
                    </div>
                    <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{proj.description}</p>
                  </div>
                ))}
              </div>
            </div>
            <div className="dashboard-card">
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
              <div className="dashboard-card">
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
              <div className="dashboard-card">
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
                      <span key={lang} className="rounded-lg border border-border/50 bg-secondary/35 px-3 py-1.5 text-xs text-foreground">{lang}</span>
                    )) : <p className="text-xs text-muted-foreground italic">None listed</p>}
                  </div>
                )}
              </div>
            </div>
          </div>
          <div className="w-full lg:w-72 xl:w-80">
            <div className="sticky top-24 space-y-4">
              <div className="dashboard-card">
                <h3 className="mb-1 text-sm font-semibold text-foreground">Upload Resume</h3>
                <p className="mb-4 text-xs text-muted-foreground">Upload a new PDF or DOCX to refresh your details.</p>
                <div
                  className="relative flex flex-col items-center justify-center gap-3 rounded-xl empty-state-premium p-8 transition-all duration-300 cursor-pointer hover:opacity-90"
                  onClick={openFilePicker}
                >
                  <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10">
                    <Upload className="h-6 w-6 text-primary" />
                  </div>
                  <div className="text-center">
                    <p className="text-sm font-medium text-foreground">
                      {isUploading ? "Uploading..." : "Click to upload"}
                    </p>
                    <p className="text-xs text-muted-foreground">PDF or DOCX, up to 4MB</p>
                  </div>
                </div>
                <Button
                  variant="outline"
                  onClick={openFilePicker}
                  disabled={isUploading}
                  className="mt-4 w-full gap-2 text-sm"
                >
                  <Upload className="h-3.5 w-3.5" />
                  {isUploading ? "Uploading..." : "Browse Files"}
                </Button>
              </div>
            </div>
          </div>
          </div>
        </>
      )}
    </div>
  )
}


function SettingsContent({
  onOpenLogout,
  onOpenMembership,
  user,
  onUserUpdate,
}: {
  onOpenLogout: () => void
  onOpenMembership: () => void
  user?: AuthUser | null
  onUserUpdate?: (updates: Partial<AuthUser>) => void
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

  const [AccountTab, setAccountTab] = useState<any>(null)
  const [NotificationsTab, setNotificationsTab] = useState<any>(null)
  const [BillingTab, setBillingTab] = useState<any>(null)
  const [PrivacyTab, setPrivacyTab] = useState<any>(null)

  useEffect(() => {
    import("@/components/settings/account-tab").then(m => setAccountTab(() => m.AccountTab))
    import("@/components/settings/notifications-tab").then(m => setNotificationsTab(() => m.NotificationsTab))
    import("@/components/settings/billing-tab").then(m => setBillingTab(() => m.BillingTab))
    import("@/components/settings/privacy-tab").then(m => setPrivacyTab(() => m.PrivacyTab))
  }, [])

  const [settingsTab, setSettingsTab] = useState<
    "account" | "notifications" | "billing" | "privacy" | "support"
  >(() => {
    if (typeof window === "undefined") return "account"
    return safeStorageGet("session", "settings_tab") === "billing" ? "billing" : "account"
  })

  useEffect(() => {
    if (typeof window === "undefined") return
    const requested = safeStorageGet("session", "settings_tab")
    if (requested === "billing") {
      setSettingsTab("billing")
      safeStorageRemove("session", "settings_tab")
    }
  }, [])

  const settingsTabOptions = [
    { value: "account" as const, label: "Account" },
    { value: "notifications" as const, label: "Notifications" },
    { value: "billing" as const, label: "Billing" },
    { value: "privacy" as const, label: "Privacy & Data" },
    { value: "support" as const, label: "Support" },
  ]

  return (
    <div className="flex-1 overflow-y-auto p-6 md:p-8">
      <Tabs value={settingsTab} onValueChange={(value) => setSettingsTab(value as typeof settingsTab)} className="w-full">
        <SlidingSegmentControl
          ariaLabel="Settings sections"
          options={settingsTabOptions}
          value={settingsTab}
          onValueChange={setSettingsTab}
          className="dashboard-tabs mb-6 w-full max-w-full gap-1 rounded-2xl border-0 bg-card p-1.5 shadow-[0_14px_36px_rgba(15,23,42,0.06)] dark:shadow-[0_16px_38px_rgba(0,0,0,0.2)]"
          buttonClassName="h-9 px-3.5"
        />
        <TabsContent value="account">
          {AccountTab ? <AccountTab user={user} onAccountDeleted={onOpenLogout} onAccountUpdated={onUserUpdate} /> : <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>}
        </TabsContent>
        <TabsContent value="notifications">
          {NotificationsTab ? <NotificationsTab /> : <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>}
        </TabsContent>
        <TabsContent value="billing">
          {BillingTab ? <BillingTab user={user} onOpenMembership={onOpenMembership} /> : <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>}
        </TabsContent>
        <TabsContent value="privacy">
          {PrivacyTab ? <PrivacyTab /> : <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>}
        </TabsContent>
        <TabsContent value="support">
          <div className="space-y-6">
            <div className="dashboard-card">
              <div className="mb-1 flex items-center gap-2">
                <Bug className="h-4 w-4 text-red-400" />
                <h3 className="text-sm font-semibold text-foreground">Report a Bug</h3>
              </div>
              <p className="mb-5 text-xs text-muted-foreground">Found something broken? Send it into the support inbox with enough detail to reproduce it. Valid bug reports can earn a reward.</p>
              <div className="space-y-4">
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs text-muted-foreground">Bug Title</Label>
                  <Input value={bugTitle} onChange={(event) => setBugTitle(event.target.value)} placeholder="e.g. Report page breaks after completing a mock interview" className="h-9" />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs text-muted-foreground">Description</Label>
                  <Textarea value={bugMessage} onChange={(event) => setBugMessage(event.target.value)} placeholder="Describe what happened, what you expected, and what actually occurred..." rows={5} />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs text-muted-foreground">Steps to Reproduce (optional)</Label>
                  <Textarea value={bugSteps} onChange={(event) => setBugSteps(event.target.value)} placeholder={"1. Go to...\n2. Click on...\n3. See error..."} rows={4} />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs text-muted-foreground">Interview ID (optional)</Label>
                  <Input value={bugInterviewId} onChange={(event) => setBugInterviewId(event.target.value)} placeholder="Attach the interview ID if this bug is tied to one session" className="h-9" />
                </div>
                <Button className="gap-2" onClick={submitBugReport} disabled={submittingBug}>
                  {submittingBug ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                  Submit Bug Report
                </Button>
              </div>
            </div>

            <div className="dashboard-card">
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
                      <button key={n} type="button" onClick={() => setFeedbackRating(n)}
                        className={`group flex h-10 w-10 items-center justify-center rounded-lg border transition-all ${feedbackRating >= n ? "border-primary/40 bg-primary/10" : "border-border/40 bg-secondary/20 hover:bg-primary/10 hover:border-primary/30"}`}>
                        <Star className={`h-4 w-4 transition-colors ${feedbackRating >= n ? "fill-primary text-primary" : "text-muted-foreground group-hover:text-primary"}`} />
                      </button>
                    ))}
                  </div>
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs text-muted-foreground">Your Feedback</Label>
                  <Textarea value={feedbackMessage} onChange={(event) => setFeedbackMessage(event.target.value)} placeholder="What do you love? What could be better? Any features you'd like to see?" rows={5} />
                </div>
                <Button className="gap-2" onClick={submitFeedback} disabled={submittingFeedback}>
                  {submittingFeedback ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                  Send Feedback
                </Button>
              </div>
            </div>

            {user?.is_admin && (
              <div className="dashboard-card">
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
function MembershipContent() {
  const router = useRouter()
  const [billing, setBilling] = useState<"monthly" | "annual">("monthly")
  const [plans, setPlans] = useState<any[]>([])
  const isAnnual = billing === "annual"
  useEffect(() => {
    fetchPaymentPlans()
      .then((data) => setPlans(Array.isArray(data) ? data : data.plans || []))
      .catch(() => setPlans([]))
  }, [])
  const planByType = Object.fromEntries(plans.map((plan) => [plan.plan_type, plan]))

  interface FeatureItem {
    text: string
    included: boolean
    upgradeText?: string
  }

  const starterFeatures: FeatureItem[] = [
    ...(planByType.starter?.features || [
      "1 AI Mock Interview per week",
      "Personalised Performance Report",
      "Targeted Improve drills",
    ]).map((feature: any) => typeof feature === "string" ? { text: feature, included: true } : feature),
    { text: "Technical Assessments", included: false, upgradeText: "Pro" },
  ]

  const proFeatures: FeatureItem[] = [
    ...(planByType.pro?.features || [
      "3 AI Mock Interviews per week",
      "1 Technical Assessment per week",
      "Custom Mock Interview (JD-Based)",
      "Personalised Performance Reports",
    ]).map((feature: any) => typeof feature === "string" ? { text: feature, included: true } : feature),
    { text: "Custom Technical Interview (JD-Based)", included: false, upgradeText: "Premium" },
  ]

  const premiumFeatures: FeatureItem[] = (planByType.premium?.features || [
    "5 AI Mock Interviews per week",
    "3 Technical Assessments per week",
    "Custom Mock Interview (JD-Based)",
    "Custom Technical Interview (JD-Based)",
  ]).map((feature: any) => typeof feature === "string" ? { text: feature, included: true } : feature)

  const proPricing = { monthly: planByType.pro?.amount || 999, annual: Math.round((planByType.pro_annual?.amount || 9588) / 12), annualBilled: planByType.pro_annual?.amount || 9588 }
  const premiumPricing = { monthly: planByType.premium?.amount || 1499, annual: Math.round((planByType.premium_annual?.amount || 14388) / 12), annualBilled: planByType.premium_annual?.amount || 14388 }

  const fmt = (n: number) => `₹${n.toLocaleString("en-IN")}`

  return (
    <div className="flex-1 overflow-y-auto p-6 md:p-8">
      <div className="mb-6 rounded-xl card-elevated p-7">
        <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-xs font-semibold text-muted-foreground/70">Pricing</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-foreground">Plans for every stage of prep.</h2>
            <p className="mt-1.5 max-w-2xl text-sm leading-6 text-muted-foreground">
              Free gives you one AI mock interview per week. Upgrade when you need technical assessments, custom JD-based rounds, and higher weekly limits.
            </p>
            <p className="mt-3 text-sm font-medium text-primary">
              Early Bird: register by 30 July 2026 to get Premium free for 1 month.
            </p>
          </div>
          <div className="flex flex-wrap gap-2 text-xs font-medium text-muted-foreground">
            <span className="rounded-md border border-border/50 bg-secondary/20 px-3 py-1.5">Cancel anytime</span>
            <span className="rounded-md border border-border/50 bg-secondary/20 px-3 py-1.5">No commitment</span>
          </div>
        </div>
      </div>


      <div className="dashboard-card mb-6 flex items-center justify-center gap-3">
        <span className={`text-sm font-medium transition-colors ${!isAnnual ? "text-foreground" : "text-muted-foreground"}`}>Monthly</span>
        <button
          onClick={() => setBilling(isAnnual ? "monthly" : "annual")}
          className="relative h-7 w-[52px] rounded-full bg-secondary border border-border transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
          aria-label="Toggle billing cycle"
        >
          <span className={`absolute top-0.5 left-0.5 h-6 w-6 rounded-full bg-primary shadow-md transition-transform duration-300 ${isAnnual ? "translate-x-[24px]" : "translate-x-0"}`} />
        </button>
        <span className={`text-sm font-medium transition-colors ${isAnnual ? "text-foreground" : "text-muted-foreground"}`}>Annual</span>
        <span className={`ml-1 inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-bold transition-all duration-300 ${isAnnual ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 scale-100 opacity-100" : "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 scale-90 opacity-0 pointer-events-none"}`}>
          Save 20%
        </span>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">


        <div className="flex flex-col rounded-xl card-elevated p-7">
          <div className="mb-5">
              <h3 className="text-lg font-semibold text-foreground">Free</h3>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">Explore the feedback system</p>
          </div>
          <div className="mb-3">
            <div className="flex items-baseline gap-1">
              <span className="text-3xl font-bold tracking-tight text-foreground">Free</span>
            </div>
          </div>
          <p className="mb-5 text-sm text-muted-foreground">Perfect for getting started and exploring the feedback system.</p>

          <div className="flex-1 space-y-2.5">
            {starterFeatures.map((f) => (
              <div key={f.text} className="flex items-start gap-2.5 text-sm">
                {f.included ? (
                  <>
                    <Check className="h-4 w-4 shrink-0 text-emerald-500 mt-0.5" />
                    <span className="text-foreground">{f.text}</span>
                  </>
                ) : (
                  <>
                    <X className="h-4 w-4 shrink-0 text-rose-500/80 mt-0.5" />
                    <span className="text-muted-foreground/50 line-through decoration-muted-foreground/30">
                      {f.text}
                      <span className="text-xs ml-1.5 font-bold text-rose-500/70 not-italic">({f.upgradeText})</span>
                    </span>
                  </>
                )}
              </div>
            ))}
          </div>
          <Button className="mt-6 w-full rounded-lg" variant="outline" onClick={() => router.push("/?tab=interview")}>
            Use Free
          </Button>
        </div>


        <div className="dashboard-card flex flex-col ring-1 ring-primary/25">
          <div className="mb-5 flex items-start justify-between gap-3">
            <div>
              <h3 className="text-lg font-semibold text-foreground">Pro</h3>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">Master interviews and build perfect answers</p>
            </div>
            <span className="shrink-0 rounded-md bg-primary/10 px-2.5 py-1 text-xs font-bold text-primary">Most popular</span>
          </div>
          <div className="mb-3">
            <div className="flex items-baseline gap-2">
              <span className={`font-bold tracking-tight transition-all duration-500 ease-out ${
                isAnnual
                  ? "text-lg text-muted-foreground line-through opacity-60"
                  : "text-3xl text-foreground"
              }`}>
                {fmt(proPricing.monthly)}
              </span>
              <span className={`font-bold tracking-tight transition-all duration-500 ease-out origin-left ${
                isAnnual
                  ? "text-3xl text-foreground opacity-100 translate-x-0 max-w-[150px] scale-100"
                  : "text-lg text-transparent opacity-0 -translate-x-2 max-w-0 scale-75 pointer-events-none"
              } overflow-hidden whitespace-nowrap`}>
                {fmt(proPricing.annual)}
              </span>
              <span className="text-sm text-muted-foreground">/ month</span>
            </div>
            {isAnnual && <p className="mt-1 text-xs font-medium text-muted-foreground">billed {fmt(proPricing.annualBilled)} / year</p>}
          </div>
          <p className="mb-5 text-sm text-muted-foreground">Designed for serious candidates who want to master interviews and build perfect answers.</p>
          <div className="flex-1 space-y-2.5">
            {proFeatures.map((f) => (
              <div key={f.text} className="flex items-start gap-2.5 text-sm">
                {f.included ? (
                  <>
                    <Check className="h-4 w-4 shrink-0 text-emerald-500 mt-0.5" />
                    <span className="text-foreground">{f.text}</span>
                  </>
                ) : (
                  <>
                    <X className="h-4 w-4 shrink-0 text-rose-500/80 mt-0.5" />
                    <span className="text-muted-foreground/50 line-through decoration-muted-foreground/30">
                      {f.text}
                      <span className="text-xs ml-1.5 font-bold text-rose-500/70 not-italic">({f.upgradeText})</span>
                    </span>
                  </>
                )}
              </div>
            ))}
          </div>
          <Button className="mt-6 w-full rounded-lg" variant="default" onClick={() => router.push(`/checkout?plan=${isAnnual ? "pro_annual" : "pro"}`)}>
            Get Pro
          </Button>
        </div>


        <div className="flex flex-col rounded-xl card-elevated p-7">
          <div className="mb-5 flex items-start justify-between gap-3">
            <div>
              <h3 className="text-lg font-semibold text-foreground">Premium</h3>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">Custom rounds for elite preparation</p>
            </div>
            <span className="shrink-0 rounded-md bg-primary/10 px-2.5 py-1 text-xs font-semibold text-primary">Full package</span>
          </div>
          <div className="mb-3">
            <div className="flex items-baseline gap-2">
              <span className={`font-bold tracking-tight transition-all duration-500 ease-out ${
                isAnnual
                  ? "text-lg text-muted-foreground line-through opacity-60"
                  : "text-3xl text-foreground"
              }`}>
                {fmt(premiumPricing.monthly)}
              </span>
              <span className={`font-bold tracking-tight transition-all duration-500 ease-out origin-left ${
                isAnnual
                  ? "text-3xl text-foreground opacity-100 translate-x-0 max-w-[150px] scale-100"
                  : "text-lg text-transparent opacity-0 -translate-x-2 max-w-0 scale-75 pointer-events-none"
              } overflow-hidden whitespace-nowrap`}>
                {fmt(premiumPricing.annual)}
              </span>
              <span className="text-sm text-muted-foreground">/ month</span>
            </div>
            {isAnnual && <p className="mt-1 text-xs font-medium text-muted-foreground">billed {fmt(premiumPricing.annualBilled)} / year</p>}
          </div>
          <p className="mb-5 text-sm text-muted-foreground">The ultimate solution with custom rounds for elite preparation.</p>
          <div className="mb-5 rounded-lg border border-primary/20 bg-primary/5 px-3 py-2 text-xs font-medium text-primary">
            Register by 30 July 2026 and your first Premium month is free.
          </div>
          <div className="flex-1 space-y-2.5">
            {premiumFeatures.map((f) => (
              <div key={f.text} className="flex items-start gap-2.5 text-sm">
                {f.included ? (
                  <>
                    <Check className="h-4 w-4 shrink-0 text-emerald-500 mt-0.5" />
                    <span className="text-foreground">{f.text}</span>
                  </>
                ) : (
                  <>
                    <X className="h-4 w-4 shrink-0 text-rose-500/80 mt-0.5" />
                    <span className="text-muted-foreground/50 line-through decoration-muted-foreground/30">
                      {f.text}
                      <span className="text-xs ml-1.5 font-bold text-rose-500/70 not-italic">({f.upgradeText})</span>
                    </span>
                  </>
                )}
              </div>
            ))}
          </div>
          <Button className="mt-6 w-full rounded-lg" variant="default" onClick={() => router.push(`/checkout?plan=${isAnnual ? "premium_annual" : "premium"}`)}>
            Get Premium
          </Button>
        </div>
      </div>
    </div>
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

function StartPreparationOverlay({
  show,
  title,
  message,
}: {
  show: boolean
  title: string
  message: string
}) {
  if (!show) return null
  if (typeof document === "undefined") return null
  return createPortal(
    <div className="fixed inset-0 z-[1000] flex h-dvh w-dvw items-center justify-center bg-background/80 px-4 backdrop-blur-sm">
      <div className="w-full max-w-sm rounded-xl border border-border bg-card p-6 text-center shadow-xl">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-lg border border-border/60 bg-secondary/40 text-primary">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
        <p className="text-base font-semibold text-foreground">{title}</p>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">{message}</p>
      </div>
    </div>,
    document.body
  )
}

export function AppShell({ onLogout, onUserUpdate, theme = "dark", onToggleTheme, user, initialTab, initialImproveTarget = null }: AppShellProps) {
  const normalizeNav = (value?: string | null): ActiveNav | null => {
    switch (value) {
      case "dashboard":
        return "interview"
      case "improve":
        return "improve"
      case "analytics":
      case "performance":
        return "performance"
      case "technical":
      case "coding":
        return "coding"
      case "interview":
      case "resume":
      case "settings":
        return value
      case "membership":
        return "membership"
      default:
        return null
    }
  }
  const [activeNav, _setActiveNav] = useState<ActiveNav>(() => {
    const normalizedInitial = normalizeNav(initialTab)
    if (normalizedInitial) return normalizedInitial
    if (typeof window !== "undefined") {
      const stored = normalizeNav(safeStorageGet("session", "dashboard_tab"))
      if (stored) return stored
    }
    return "interview"
  })
  const setActiveNav = (nav: ActiveNav) => {
    _setActiveNav(nav)
    safeStorageSet("session", "dashboard_tab", nav)
  }
  const [showLogout, setShowLogout] = useState(false)
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [sidebarHovered, setSidebarHovered] = useState(false)
  const isExpanded = !sidebarCollapsed || sidebarHovered
  const prevSidebarExpandedRef = useRef(isExpanded)
  const [sidebarTransitioning, setSidebarTransitioning] = useState(false)
  useEffect(() => {
    if (prevSidebarExpandedRef.current === isExpanded) return
    prevSidebarExpandedRef.current = isExpanded
    setSidebarTransitioning(true)
    const timer = window.setTimeout(() => setSidebarTransitioning(false), 300)
    return () => window.clearTimeout(timer)
  }, [isExpanded])
  const sidebarRevealClass = sidebarTransitioning
    ? "transition-[margin,max-width,transform] duration-300 ease-in-out"
    : ""
  const { justParsed } = useResume()
  const [learning, setLearning] = useState<LearningDashboard | null>(null)
  const [learningLoading, setLearningLoading] = useState(true)
  const [learningError, setLearningError] = useState("")
  const learningReconcileAttemptedRef = useRef(false)
  const [interviews, setInterviews] = useState<PastInterview[]>([])
  const [streakDays, setStreakDays] = useState(0)
  const [refreshTrigger, setRefreshTrigger] = useState(0)
  const [improveTarget, setImproveTarget] = useState<ExactImproveTarget | null>(initialImproveTarget)
  useEffect(() => {
    if (typeof window === "undefined") return
    if (activeNav !== "improve") {
      window.history.replaceState({}, "", `/?tab=${activeNav}`)
      return
    }
    if (!improveTarget) {
      window.history.replaceState({}, "", "/?tab=improve")
      return
    }
    const params = new URLSearchParams({
      tab: "improve",
      mode: improveTarget.mode === "technical" ? "technical" : "interview",
      mission_id: improveTarget.mission_id,
      roadmap_node_id: improveTarget.roadmap_node_id,
      exercise_id: improveTarget.exercise_id,
    })
    window.history.replaceState({}, "", `/?${params.toString()}`)
  }, [activeNav, improveTarget])
  const openImproveTarget = (target: ExactImproveTarget) => {
    setImproveTarget(target)
    _setActiveNav("improve")
    if (typeof window !== "undefined") {
      const params = new URLSearchParams({
        tab: "improve",
        mode: target.mode === "technical" ? "technical" : "interview",
        mission_id: target.mission_id,
        roadmap_node_id: target.roadmap_node_id,
        exercise_id: target.exercise_id,
      })
      window.history.replaceState({}, "", `/?${params.toString()}`)
    }
  }
  const refreshLearning = async () => {
    try {
      setLearningError("")
      const data = await fetchLearningDashboard()
      setLearning(data)
      if (data.analysis_availability?.missing_canonical_count && !learningReconcileAttemptedRef.current) {
        learningReconcileAttemptedRef.current = true
        await reconcilePerformance()
      }
    } catch (error: any) {
      setLearningError(error?.message || "Failed to load improvement data.")
    } finally {
      setLearningLoading(false)
    }
  }
  useEffect(() => {
    async function loadDashboardData() {
      try {
        setLearningLoading(true)
        setLearningError("")
        const [{ fetchRecentActivity, fetchLearningDashboard }] = await Promise.all([
          import('@/lib/api')
        ])
        const [activityData, learningResult] = await Promise.all([
          fetchRecentActivity().catch(() => null),
          fetchLearningDashboard()
            .then((data) => ({ data, error: "" }))
            .catch((error: any) => ({ data: null, error: error?.message || "Failed to load improvement data." }))
        ])
        if (learningResult.data) {
          setLearning(learningResult.data)
          if (learningResult.data.analysis_availability?.missing_canonical_count && !learningReconcileAttemptedRef.current) {
            learningReconcileAttemptedRef.current = true
            void reconcilePerformance().then(() => window.setTimeout(() => setRefreshTrigger((value) => value + 1), 3000))
          }
        } else if (learningResult.error) {
          setLearningError(learningResult.error)
        }
        if (activityData && activityData.activities) {
          const activityDates = new Set(
            activityData.activities
              .filter((act: any) => act.created_at)
              .map((act: any) => new Date(act.created_at).toDateString())
          )
          let streak = 0
          const cursorDate = new Date()
          while (activityDates.has(cursorDate.toDateString())) {
            streak += 1
            cursorDate.setDate(cursorDate.getDate() - 1)
          }
          setStreakDays(streak)
          setInterviews(
            activityData.activities.map((act: any) => ({
              id: act.id || act.interview_id || act.entity_id,
              date: act.created_at ? new Date(act.created_at).toLocaleDateString() : "Not recorded",
              role: act.subtitle || act.job_title || act.title || "General",
              type: act.type ? String(act.type).replace(/_/g, " ") : act.interview_type === "mock" ? "Full" : "Quick",
              score: act.score == null && act.overall_score == null ? null : Math.round(act.score ?? act.overall_score),
              status: act.status,
              cta: act.cta,
              duration: act.duration_seconds || null,
              created_at: act.created_at || null,
            }))
          )
        }
      } catch (error: any) {
        setLearningError(error?.message || "Failed to load dashboard data.")
      } finally {
        setLearningLoading(false)
      }
    }
    if (activeNav === "improve" || activeNav === "interview" || activeNav === "coding") {
      loadDashboardData()
    }
  }, [activeNav, refreshTrigger])

  // Poll for generating reports dynamically
  useEffect(() => {
    const hasGenerating = interviews.some((i) => i.cta?.nav === "generating")
    if (!hasGenerating) return

    let isPolling = true
    const interval = setInterval(async () => {
      try {
        const { fetchRecentActivity } = await import("@/lib/api")
        const activityData = await fetchRecentActivity().catch(() => null)
        if (!isPolling) return
        if (activityData && activityData.activities) {
          const newInterviews = activityData.activities.map((act: any) => ({
            id: act.id || act.interview_id || act.entity_id,
            date: act.created_at ? new Date(act.created_at).toLocaleDateString() : "Not recorded",
            role: act.subtitle || act.job_title || act.title || "General",
            type: act.type ? String(act.type).replace(/_/g, " ") : act.interview_type === "mock" ? "Full" : "Quick",
            score: act.score == null && act.overall_score == null ? null : Math.round(act.score ?? act.overall_score),
            status: act.status,
            cta: act.cta,
            duration: act.duration_seconds || null,
            created_at: act.created_at || null,
          }))

          // Check if any generating interview changed to something else
          const statusChanged = interviews.some((oldInt) => {
            if (oldInt.cta?.nav !== "generating") return false
            const newInt = newInterviews.find((n: any) => n.id === oldInt.id)
            return newInt && newInt.cta?.nav !== "generating"
          })

          if (statusChanged) {
            setRefreshTrigger((prev) => prev + 1)
          } else {
            setInterviews(newInterviews)
          }
        }
      } catch (e) {
        console.error("Failed to poll recent activity:", e)
      }
    }, 5000)

    return () => {
      isPolling = false
      clearInterval(interval)
    }
  }, [interviews])
  useEffect(() => {
    if (justParsed) {
      setActiveNav("resume")
    }
  }, [justParsed])
  const getPageTitle = () => {
    switch (activeNav) {
      case "improve": return "Improve"
      case "interview": return "Interview Round"
      case "coding": return "Technical Round"
      case "resume": return "Resume"
      case "performance": return "Performance"
      case "membership": return "Membership"
      case "settings": return "Settings"
      default: return "Interview Round"
    }
  }
  const backgroundMode = getDashboardBackgroundMode(user?.plan_type)
  const isPaidPlan = backgroundMode === "comets"
  const hasSpaceEffects = theme === "dark" && isPaidPlan

  useEffect(() => {
    if (hasSpaceEffects) {
      document.documentElement.classList.add("premium-theme")
    } else {
      document.documentElement.classList.remove("premium-theme")
    }
    return () => {
      document.documentElement.classList.remove("premium-theme")
    }
  }, [hasSpaceEffects])

  return (
    <>
      <PremiumBackground theme={theme} mode={backgroundMode} />
      <div className={`relative z-10 flex min-h-screen bg-transparent text-foreground ${hasSpaceEffects ? "premium-theme" : ""}`}>
        {/* Desktop Sidebar Spacer/Placeholder to prevent main content layout shifts */}
        <div className={`hidden md:block shrink-0 transition-all duration-300 ease-in-out ${sidebarCollapsed ? "w-[68px]" : "w-56"}`} />

        <aside
          onMouseEnter={() => { if (sidebarCollapsed) setSidebarHovered(true); }}
          onMouseLeave={() => setSidebarHovered(false)}
          className={`fixed left-0 top-0 hidden h-screen flex-col border-r border-border/60 bg-card/80 backdrop-blur-xl md:flex transition-all duration-300 ease-in-out z-30 ${
            isExpanded ? "w-56" : "w-[68px]"
          }`}
        >
          <div className="flex h-16 items-center border-b border-border px-3 justify-between">
            <a
              href="/"
              onClick={(e) => { e.preventDefault(); setActiveNav("interview"); window.scrollTo(0, 0); }}
              className="flex items-center pl-1 transition-opacity hover:opacity-80 shrink-0"
            >
              <ThemeLogo size={36} className="shrink-0" />
              <span className={`whitespace-nowrap overflow-hidden transition-[margin,max-width,transform,opacity] ease-out motion-reduce:transition-none motion-reduce:delay-0 ${
                isExpanded
                  ? "ml-3 max-w-[120px] translate-x-0 opacity-100 delay-[120ms] duration-[180ms]"
                  : "ml-0 max-w-0 -translate-x-2 opacity-0 delay-0 duration-150 pointer-events-none"
              }`}>
                <span className="text-lg font-bold text-foreground">InterAI</span>
              </span>
            </a>
            {!sidebarCollapsed ? (
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setSidebarCollapsed(true)}
                className="h-7 w-7 text-muted-foreground hover:text-foreground shrink-0"
                aria-label="Collapse sidebar"
              >
                <PanelLeft className="h-4 w-4" />
              </Button>
            ) : (
              sidebarHovered && (
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => {
                    setSidebarCollapsed(false);
                    setSidebarHovered(false);
                  }}
                  title="Pin sidebar"
                  className="h-7 w-7 text-muted-foreground hover:text-foreground shrink-0"
                  aria-label="Pin sidebar"
                >
                  <PanelLeft className="h-4 w-4" />
                </Button>
              )
            )}
          </div>
          <div className="flex flex-1 flex-col p-2">
            <SlidingSidebarNav
              ariaLabel="Main navigation"
              items={primaryNavItems}
              activeId={activeNav}
              onSelect={setActiveNav}
              collapsed={!isExpanded}
              expanded={isExpanded}
              className="flex-1"
            />
            <SlidingSidebarNav
              ariaLabel="Account navigation"
              items={secondaryNavItems}
              activeId={activeNav}
              onSelect={setActiveNav}
              collapsed={!isExpanded}
              expanded={isExpanded}
              className="border-t border-border/60 pt-2"
            />
          </div>
          <div className="border-t border-border p-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center pl-1">
                {user?.avatar_url ? (
                  <img src={user.avatar_url} alt="" className="h-9 w-9 rounded-full object-cover shrink-0" />
                ) : (
                  <div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary/10 shrink-0">
                    <User className="h-4 w-4 text-primary" />
                  </div>
                )}
                <div className={`${sidebarRevealClass} flex flex-col overflow-hidden ${
                  isExpanded ? "ml-3 max-w-[140px] translate-x-0" : "ml-0 max-w-0 -translate-x-2 pointer-events-none"
                }`}>
                  <span className="text-sm font-medium text-foreground whitespace-nowrap">
                    {user?.name || "User"}
                  </span>
                  {renderPlanBadge(user?.plan_type)}
                </div>
              </div>
              <div className={`${sidebarRevealClass} overflow-hidden ${
                isExpanded ? "max-w-[40px] translate-x-0" : "max-w-0 translate-x-2 pointer-events-none"
              }`}>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => setShowLogout(true)}
                  className="h-8 w-8 text-muted-foreground hover:text-foreground shrink-0"
                  aria-label="Log out"
                >
                  <LogOut className="h-4 w-4" />
                </Button>
              </div>
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
          className={`fixed inset-y-0 left-0 z-50 w-56 flex-col border-r border-border/40 bg-card/90 backdrop-blur-2xl transition-transform duration-300 md:hidden ${mobileMenuOpen ? "translate-x-0" : "-translate-x-full"
            }`}
        >
          <div className="flex h-16 items-center justify-between border-b border-border/40 px-6">
            <a
              href="/"
              onClick={(e) => { e.preventDefault(); setActiveNav("interview"); setMobileMenuOpen(false); window.scrollTo(0, 0); }}
              className="flex items-center gap-1.5 transition-opacity hover:opacity-80"
            >
              <ThemeLogo size={36} />
              <span className="text-lg font-bold text-foreground">InterAI</span>
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
          <div className="flex flex-1 flex-col p-3">
            <SlidingSidebarNav
              ariaLabel="Main navigation"
              items={primaryNavItems}
              activeId={activeNav}
              onSelect={(id) => {
                setActiveNav(id)
                setMobileMenuOpen(false)
              }}
              buttonClassName="h-auto min-h-10 gap-3 py-2.5 pl-3"
              className="flex-1"
            />
            <SlidingSidebarNav
              ariaLabel="Account navigation"
              items={secondaryNavItems}
              activeId={activeNav}
              onSelect={(id) => {
                setActiveNav(id)
                setMobileMenuOpen(false)
              }}
              buttonClassName="h-auto min-h-10 gap-3 py-2.5 pl-3"
              className="border-t border-border/60 pt-3"
            />
          </div>
          <div className="border-t border-border p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                {user?.avatar_url ? (
                  <img src={user.avatar_url} alt="" className="h-9 w-9 rounded-full object-cover" />
                ) : (
                  <div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary/10">
                    <User className="h-4 w-4 text-primary" />
                  </div>
                )}
                <div className="flex flex-col">
                  <span className="text-sm font-medium text-foreground">
                    {user?.name || "User"}
                  </span>
                  {renderPlanBadge(user?.plan_type)}
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
        <main className="flex flex-1 flex-col bg-transparent">
          <header className="flex h-16 items-center justify-between bg-card/40 backdrop-blur-xl px-4 md:px-8 shadow-[0_1px_12px_-2px_rgba(0,0,0,0.15)]">
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
              <h1 className="text-lg font-semibold text-foreground">{getPageTitle()}</h1>
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
              <div className="flex items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-1.5 text-xs font-semibold text-foreground">
                <Flame className="h-3.5 w-3.5 text-orange-500" />
                <span>{streakDays} day{streakDays === 1 ? "" : "s"}</span>
              </div>
            </div>
          </header>
          <>
            {(() => {
              switch (activeNav) {
                case "improve":
                  return (
                    <MissionImproveContent
                      learning={learning}
                      loading={learningLoading}
                      error={learningError}
                      setActiveNav={setActiveNav}
                      onLearningRefresh={refreshLearning}
                      isPremium={isPaidPlan}
                      navigationTarget={improveTarget}
                      onNavigationConsumed={() => {
                        setImproveTarget(null)
                      }}
                    />
                  )
                case "interview":
                case "coding":
                  return (
                    <InterviewContent
                      interviews={interviews}
                      setActiveNav={setActiveNav}
                      mode={activeNav === "coding" ? "technical" : "interview"}
                      user={user}
                    />
                  )
                case "resume":
                  return <ResumeContent />
                case "performance":
                  return <PerformanceContent onOpenPractice={(tab) => setActiveNav(tab)} />
                case "membership":
                  return <MembershipContent />
                case "settings":
                  return <SettingsContent onOpenLogout={() => setShowLogout(true)} onOpenMembership={() => setActiveNav("membership")} user={user} onUserUpdate={onUserUpdate} />
                default:
                  return null
              }
            })()}
          </>
        </main>
      </div>
      <LogoutModal open={showLogout} onOpenChange={setShowLogout} onConfirm={onLogout} />
    </>
  )
}
