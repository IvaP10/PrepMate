"use client"
import { lazy, Suspense, useState, useEffect, useRef, useCallback } from "react"
import { createPortal } from "react-dom"
import { useRouter } from "next/navigation"
import { ThemeLogo } from "@/components/theme-logo"
import {
  FileText,
  BarChart3,
  Settings,
  Sun,
  Moon,
  Upload,
  Code,
  X,
  Check,
  Edit3,
  Save,
  Play,
  Eye,
  Loader2,
  Target,
  PanelLeft,
  Copy,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { SlidingSegmentControl } from "@/components/sliding-segment-control"
import { SlidingSidebarNav } from "@/components/sliding-sidebar-nav"
import { InterviewSetupWizard, type BlueprintRuntimeChoice } from "@/components/interview-setup-wizard"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import { toast } from "sonner"
import { safeStorageGet, safeStorageSet } from "@/lib/safe-storage"
import { PremiumBackground } from "./premium-background"
import {
  releaseTechnicalPermissions,
} from "@/lib/technical-permissions"
import {
  uploadResume,
  submitResume,
  startInterviewFromBlueprint,
  cancelInterviewSession,
  fetchTechnicalRoundHistory,
  fetchLearningDashboard,
  reconcilePerformance,
  prepareTechnicalRounds,
  copyInterviewJobProfile,
  fetchLocalSettings,
} from "@/lib/api"
import type { ExactImproveTarget, InterviewBlueprint, InterviewProfileType, LearningDashboard, TechnicalRoundHistoryItem, TechnicalRoundSession } from "@/lib/api"
import { useResume } from "@/context/resume-context"
import type { ResumeData } from "@/types/resume"
import { RESUME_MAX_FILE_BYTES } from "@/lib/config"
import { ProviderSettings } from "@/components/settings/provider-settings"
import { DataPrivacy } from "@/components/settings/data-privacy"

const LazyMissionImproveContent = lazy(() =>
  import("@/components/improve/improve-content").then((module) => ({ default: module.ImproveContent }))
)
const LazyPerformanceContent = lazy(() =>
  import("@/components/performance/performance-content").then((module) => ({ default: module.PerformanceContent }))
)
const LazyResumeAssetsManager = lazy(() =>
  import("@/components/resume-assets-manager").then((module) => ({ default: module.ResumeAssetsManager }))
)

function WorkspacePanelFallback() {
  return (
    <div className="flex flex-1 items-center justify-center p-10">
      <Loader2 className="h-5 w-5 animate-spin text-primary" aria-label="Loading section" />
    </div>
  )
}

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
  theme?: "light" | "dark"
  onToggleTheme?: () => void
  initialTab?: string
  initialImproveTarget?: ExactImproveTarget | null
}
type ActiveNav = "improve" | "interview" | "coding" | "resume" | "performance" | "settings"
const primaryNavItems: { icon: any; label: string; id: ActiveNav }[] = [
  { icon: FileText, label: "Resume", id: "resume" },
  { icon: Play, label: "Interview Round", id: "interview" },
  { icon: Code, label: "Technical Round", id: "coding" },
  { icon: BarChart3, label: "Performance", id: "performance" },
  { icon: Target, label: "Improve", id: "improve" },
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
  job_target?: {
    profile_type?: InterviewProfileType | string | null
    is_custom?: boolean
    role?: string | null
    company?: string | null
    saved_profile_id?: number | null
    can_copy?: boolean
  } | null
}

function safeResumeLink(value: string, kind: "linkedin" | "github" | "portfolio") {
  const trimmed = value.trim()
  if (!trimmed) return null
  try {
    const parsed = new URL(/^https:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`)
    if (parsed.protocol !== "https:") return null
    const host = parsed.hostname.toLowerCase()
    if (kind === "linkedin" && host !== "linkedin.com" && !host.endsWith(".linkedin.com")) return null
    if (kind === "github" && host !== "github.com" && !host.endsWith(".github.com")) return null
    return parsed.toString()
  } catch {
    return null
  }
}

function ResumeExternalLink({ value, kind }: { value: string; kind: "linkedin" | "github" | "portfolio" }) {
  const href = safeResumeLink(value, kind)
  if (!href) return <span className="truncate text-sm text-muted-foreground">Invalid or unsafe link</span>
  return <a href={href} target="_blank" rel="noopener noreferrer" className="truncate text-sm text-primary hover:underline">{value}</a>
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

function normalizeTechnicalSessions(data: {
  rounds?: TechnicalRoundHistoryItem[]
  sessions?: TechnicalRoundSession[]
}): TechnicalRoundSession[] {
  const sessions = (data.sessions || []).filter((session) => Boolean(session.rounds?.length))
  if (sessions.length) return sessions

  const grouped = new Map<string, TechnicalRoundSession>()
  for (const round of data.rounds || []) {
    if (!round.interview_id) continue
    const session = grouped.get(round.interview_id) || {
      interview_id: round.interview_id,
      profile_type: round.profile_type || null,
      job_title: round.title || null,
      rounds: [],
    }
    session.rounds.push(round)
    grouped.set(round.interview_id, session)
  }
  return Array.from(grouped.values())
}

export { InterviewContent, ResumeContent }

function isProfileStartError(message: string) {
  const lower = message.toLowerCase()
  return lower.includes("profile") || lower.includes("missing")
}

function InterviewContent({
  interviews = [],
  setActiveNav,
  mode = "interview",
  refreshKey = 0,
  onProfilesChanged,
}: {
  interviews?: PastInterview[]
  setActiveNav: (nav: ActiveNav) => void
  mode?: "interview" | "technical"
  refreshKey?: number
  onProfilesChanged?: () => void
}) {
  const router = useRouter()
  const [isStartingMock, setIsStartingMock] = useState(false)
  const [isStartingTechnical, setIsStartingTechnical] = useState(false)
  const [mockStartMessage, setMockStartMessage] = useState("")
  const [technicalStartMessage, setTechnicalStartMessage] = useState("")
  const [technicalPermissionError, setTechnicalPermissionError] = useState("")
  const [technicalSessions, setTechnicalSessions] = useState<TechnicalRoundSession[]>([])
  const [loadingTechnicalRounds, setLoadingTechnicalRounds] = useState(false)
  const [technicalHistoryError, setTechnicalHistoryError] = useState("")
  const [profileRevision, setProfileRevision] = useState(0)
  const [copyingInterviewId, setCopyingInterviewId] = useState<string | number | null>(null)
  const [copiedInterviewIds, setCopiedInterviewIds] = useState<Set<string | number>>(() => new Set())
  const loadTechnicalRounds = useCallback(async () => {
    if (mode !== "technical") return
    setLoadingTechnicalRounds(true)
    setTechnicalHistoryError("")
    try {
      const data = await fetchTechnicalRoundHistory()
      setTechnicalSessions(normalizeTechnicalSessions(data))
    } catch (error: any) {
      setTechnicalHistoryError(error?.message || "Failed to load technical rounds.")
    } finally {
      setLoadingTechnicalRounds(false)
    }
  }, [mode])

  useEffect(() => {
    if (mode !== "technical") return
    void loadTechnicalRounds()
  }, [loadTechnicalRounds, mode, refreshKey])

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
          camera_mode: "optional",
          preflight_id: preflightId,
        },
      )
      const interviewId = response.interview_id || response.session_id
      if (!interviewId) throw new Error("The server did not return an interview ID.")
      setMockStartMessage("Opening interview room")
      const params = new URLSearchParams({
        mode: runtime.inputMode === "voice" ? "mock-voice" : "mock-ai",
        input: runtime.inputMode,
        camera: "optional",
      })
      router.push(`/interview/${interviewId}?${params.toString()}`)
    } catch (error: any) {
      const msg = error?.message || "Failed to start mock interview."
      if (isProfileStartError(msg)) {
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

  const handleBlueprintReady = (blueprint: InterviewBlueprint, runtime: BlueprintRuntimeChoice, preflightId: string) => {
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
        { input_mode: "text", camera_mode: "optional", preflight_id: preflightId },
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
      if (isProfileStartError(msg)) {
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

  const formatDate = (value: string | null) => value
    ? new Date(value).toLocaleDateString("en-IN", {
        timeZone: "Asia/Kolkata",
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
      })
    : "Not recorded"

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
    if (seconds === undefined || seconds === null) return "0m 0s"
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    return `${m}m ${s}s`
  }
  const profilesChanged = () => {
    setProfileRevision((value) => value + 1)
    onProfilesChanged?.()
  }

  const hasTechnicalHistory = technicalSessions.some((session) => Boolean(session.rounds?.length))
  const hasPastInterviews = interviews.length > 0

  const copyPastProfile = async (interview: PastInterview) => {
    setCopyingInterviewId(interview.id)
    try {
      await copyInterviewJobProfile(String(interview.id))
      setCopiedInterviewIds((current) => new Set(current).add(interview.id))
      toast.success("Profile saved")
      profilesChanged()
    } catch (error: any) {
      toast.error(error?.message || "Failed to copy this profile.")
    } finally {
      setCopyingInterviewId(null)
    }
  }

  return (
    <div className="min-w-0 flex-1 overflow-y-auto p-4 sm:p-6 md:p-8">
      <div className="mb-8 rounded-xl card-elevated p-7">
        <InterviewSetupWizard
          key={`${mode}-${profileRevision}`}
          mode={mode}
          disabled={isStartingMock || isStartingTechnical}
          onReady={handleBlueprintReady}
          onProfilesChanged={profilesChanged}
        />
      </div>

      {technicalPermissionError && mode === "technical" && (
        <div className="mb-6 rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {technicalPermissionError}
        </div>
      )}

      {mode === "technical" ? (
        <div className="dashboard-card overflow-hidden p-0">
          <div className={!loadingTechnicalRounds && !technicalHistoryError && !hasTechnicalHistory ? "p-5" : "border-b border-border/20 p-6"}>
            <h3 className="text-base font-semibold text-foreground">Technical Rounds</h3>
            {!loadingTechnicalRounds && !technicalHistoryError && !hasTechnicalHistory && (
              <p className="mt-1 text-sm text-muted-foreground">Your completed technical rounds will appear here.</p>
            )}
          </div>
          {(loadingTechnicalRounds || Boolean(technicalHistoryError) || hasTechnicalHistory) && <div className="max-w-full overflow-x-auto">
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
                    const observedRunRate = totalTests > 0
                      ? Math.round((totalPassed / totalTests) * 100)
                      : totalRuns > 0
                        ? Math.round((totalSuccessfulRuns / totalRuns) * 100)
                        : 0
                    const officialScore = typeof session.official_score === "number"
                      ? Math.round(session.official_score)
                      : null

                    // Start time from first round
                    const sessionCreatedAt = firstRound.created_at
                    const startTime = sessionCreatedAt
                      ? new Date(sessionCreatedAt).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', timeZoneName: 'short' })
                      : "Not recorded"

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
                    if (!duration) duration = "0m 0s"

                    const profileTypeValue = session.profile_type || firstRound.profile_type || "technical"
                    const profileTypeFormatted = (profileTypeValue === "custom" && session.job_title
                      ? `Custom (${session.job_title})`
                      : profileTypeValue)
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
                            <div className="h-2 w-16 overflow-hidden rounded-full bg-border" title={officialScore == null && observedRunRate > 0 ? "Runs saved; no official score" : undefined}>
                              <div
                                className={`h-full rounded-full ${officialScore != null && officialScore >= 80 ? "bg-green-500" : officialScore != null && officialScore >= 50 ? "bg-amber-500" : "bg-red-500"}`}
                                style={{ width: `${officialScore ?? 0}%` }}
                              />
                            </div>
                            <span className="text-sm font-medium text-foreground">{officialScore == null ? "—" : `${officialScore}%`}</span>
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
                            {session.cta?.nav === "unavailable" ? "Report not ready" : session.cta?.label || "Report not ready"}
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
        <div className={!hasPastInterviews ? "p-5" : "border-b border-border/20 p-6"}>
          <h3 className="text-base font-semibold text-foreground">Recent Interviews</h3>
          {!hasPastInterviews && (
            <p className="mt-1 text-sm text-muted-foreground">Your recent interview attempts will appear here.</p>
          )}
        </div>
        {hasPastInterviews && <div className="max-w-full overflow-x-auto">
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
              {interviews.map((interview) => {
                const customProfile = Boolean(
                  interview.job_target?.is_custom || interview.job_target?.profile_type === "custom"
                )
                const role = interview.job_target?.role || interview.role
                const profileSaved = Boolean(interview.job_target?.saved_profile_id || copiedInterviewIds.has(interview.id))
                return (
                  <tr key={interview.id} className="transition-colors hover:bg-secondary/30">
                    <td className="whitespace-nowrap px-6 py-4 text-sm text-foreground">
                      {formatActivityDate(interview.created_at)}
                    </td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm text-foreground">
                      <div className="flex items-center gap-2">
                        <span>{customProfile ? `Custom (${role})` : role}</span>
                        {customProfile && profileSaved && (
                          <span className="rounded-md bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">Saved</span>
                        )}
                        {customProfile && !profileSaved && interview.job_target?.can_copy && (
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="h-7 gap-1 px-2 text-xs text-primary"
                            disabled={copyingInterviewId === interview.id}
                            onClick={() => void copyPastProfile(interview)}
                          >
                            {copyingInterviewId === interview.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Copy className="h-3.5 w-3.5" />}
                            Copy profile
                          </Button>
                        )}
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm text-foreground">
                      {formatDuration(interview.duration)}
                    </td>
                    <td className="whitespace-nowrap px-6 py-4">
                      <div className="flex items-center gap-2">
                        <div className="h-2 w-16 overflow-hidden rounded-full bg-border">
                          <div
                            className={`h-full rounded-full ${(interview.score ?? 0) >= 80 ? "bg-green-500" : (interview.score ?? 0) >= 60 ? "bg-amber-500" : "bg-red-500"
                              }`}
                            style={{ width: `${interview.score ?? 0}%` }}
                          />
                        </div>
                        <span className="text-sm font-medium text-foreground">{interview.score == null ? "—" : `${interview.score}%`}</span>
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
                        {interview.cta?.nav === "unavailable" ? "Report not ready" : interview.cta?.label || "View Full Report"}
                      </Button>
                    </td>
                  </tr>
                )
              })}
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
  const { resumeData: contextResumeData, justParsed, setJustParsed, setResumeData: setContextResumeData } = useResume()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [isUploading, setIsUploading] = useState(false)
  const [isEditing, setIsEditing] = useState(false)
  const [resumeData, setResumeData] = useState<DashboardResumeData>(emptyResumeData)
  const [editData, setEditData] = useState<DashboardResumeData>(emptyResumeData)
  const [assetsRefreshKey, setAssetsRefreshKey] = useState(0)
  const [activeResumeId, setActiveResumeId] = useState<string | null>(contextResumeData?.metadata?.resumeId || null)
  const [uploadFailure, setUploadFailure] = useState<{ message: string; requestId?: string; retryable?: boolean } | null>(null)
  const hasData = Boolean(contextResumeData)

  const openFilePicker = () => {
    if (isUploading) return
    fileInputRef.current?.click()
  }

  const handleFileSelected = async (file: File) => {
    if (!isSupportedResumeFile(file)) {
      setUploadFailure({ message: "Please upload a PDF or DOCX file." })
      toast.error("Please upload a PDF or DOCX file")
      return
    }
    if (file.size > RESUME_MAX_FILE_BYTES) {
      setUploadFailure({ message: "File size must be 4MB or less." })
      toast.error("File size must be 4MB or less")
      return
    }

    setIsUploading(true)
    setUploadFailure(null)
    try {
      const { parsedData } = await uploadResume(file)
      setContextResumeData(parsedData)
      setActiveResumeId(parsedData.metadata?.resumeId || null)
      setAssetsRefreshKey((value) => value + 1)
      setJustParsed(true)
      setUploadFailure(null)
      toast.success("Your profile is ready", {
        description: "We've updated your details.",
      })
    } catch (err) {
      const error = err as { message?: string; details?: { request_id?: string; retryable?: boolean } }
      const message = error.message || "Something went wrong. Please try again."
      setUploadFailure({
        message,
        requestId: error.details?.request_id,
        retryable: error.details?.retryable,
      })
      toast.error(message)
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
    <div className="relative min-w-0 flex-1 overflow-y-auto p-4 sm:p-6 md:p-8">
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
      <Suspense fallback={<WorkspacePanelFallback />}>
        <LazyResumeAssetsManager
          refreshKey={assetsRefreshKey}
          onActiveResumeId={setActiveResumeId}
          onResumeActivated={(nextResume) => {
            setContextResumeData(nextResume)
            setJustParsed(false)
          }}
        />
      </Suspense>
      {uploadFailure && (
        <div role="alert" className="mb-5 flex items-start justify-between gap-4 rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-destructive">
          <div className="min-w-0">
            <p className="text-sm font-semibold">Resume upload failed</p>
            <p className="mt-1 text-sm leading-6">{uploadFailure.message}</p>
            {uploadFailure.requestId && <p className="mt-2 break-all font-mono text-xs opacity-80">Request ID: {uploadFailure.requestId}</p>}
            {uploadFailure.retryable && <p className="mt-1 text-xs opacity-80">You can retry without losing your saved profile.</p>}
          </div>
          <Button type="button" variant="ghost" size="icon" className="h-8 w-8 shrink-0" aria-label="Dismiss resume upload error" onClick={() => setUploadFailure(null)}>
            <X className="h-4 w-4" />
          </Button>
        </div>
      )}
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
          <div className="flex-1">
            <div className="dashboard-card">
              <div className="mb-6 flex items-center justify-between">
                <h2 className="text-lg font-semibold text-foreground">Current Resume Preview</h2>
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
              <div className="divide-y divide-border/60">
                <section className="pb-6">
                  <h3 className="mb-4 text-sm font-semibold text-foreground">Personal Profile</h3>
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
                  <Label className="text-xs text-muted-foreground">Target Role</Label>
                  {isEditing ? (
                    <Input value={editData.targetRole} onChange={(e) => setEditData({ ...editData, targetRole: e.target.value })} className="h-9 bg-secondary/50" />
                  ) : (
                    <p className="text-sm font-medium text-primary">{resumeData.targetRole}</p>
                  )}
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs text-muted-foreground">Email</Label>
                  {isEditing ? (
                    <Input value={editData.email} onChange={(e) => setEditData({ ...editData, email: e.target.value })} className="h-9 bg-secondary/50" />
                  ) : (
                    <p className="text-sm text-foreground">{resumeData.email}</p>
                  )}
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs text-muted-foreground">Phone</Label>
                  {isEditing ? (
                    <Input value={editData.phone} onChange={(e) => setEditData({ ...editData, phone: e.target.value })} className="h-9 bg-secondary/50" />
                  ) : (
                    <p className="text-sm text-foreground">{resumeData.phone}</p>
                  )}
                </div>
                  </div>
                </section>
            <section className="py-6">
              <h3 className="mb-4 text-sm font-semibold text-foreground">Links</h3>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs text-muted-foreground">LinkedIn</Label>
                  {isEditing ? (
                    <Input value={editData.linkedin} onChange={(e) => setEditData({ ...editData, linkedin: e.target.value })} className="h-9 bg-secondary/50" />
                  ) : (
                    <ResumeExternalLink value={resumeData.linkedin} kind="linkedin" />
                  )}
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs text-muted-foreground">GitHub</Label>
                  {isEditing ? (
                    <Input value={editData.github} onChange={(e) => setEditData({ ...editData, github: e.target.value })} className="h-9 bg-secondary/50" />
                  ) : (
                    <ResumeExternalLink value={resumeData.github} kind="github" />
                  )}
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs text-muted-foreground">Portfolio</Label>
                  {isEditing ? (
                    <Input value={editData.portfolio} onChange={(e) => setEditData({ ...editData, portfolio: e.target.value })} className="h-9 bg-secondary/50" />
                  ) : (
                    <ResumeExternalLink value={resumeData.portfolio} kind="portfolio" />
                  )}
                </div>
              </div>
            </section>
            <section className="py-6">
              <h3 className="mb-4 text-sm font-semibold text-foreground">Summary / About</h3>
              {isEditing ? (
                <Textarea value={editData.summary} onChange={(e) => setEditData({ ...editData, summary: e.target.value })} rows={3} className="bg-secondary/50" />
              ) : (
                <p className="text-sm leading-relaxed text-muted-foreground">{resumeData.summary}</p>
              )}
            </section>
            <section className="py-6">
              <div className="mb-4 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-foreground">Education</h3>
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
            </section>
            <section className="py-6">
              <div className="mb-4 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-foreground">Experience</h3>
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
            </section>
            <section className="py-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-semibold text-foreground">Projects</h3>
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
                  <div key={i} className="flex flex-col gap-1">
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
            </section>
            <section className="py-6">
              <div className="mb-4 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-foreground">Technical Skills</h3>
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
            </section>
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
              <section className="py-6 sm:pr-6">
                <h3 className="mb-4 text-sm font-semibold text-foreground">Certifications</h3>
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
              </section>
              <section className="border-t border-border/60 py-6 sm:border-l sm:border-t-0 sm:pl-6">
                <h3 className="mb-4 text-sm font-semibold text-foreground">Languages Known</h3>
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
              </section>
            </div>
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


function SettingsContent() {
  return (
    <div className="min-w-0 flex-1 overflow-y-auto p-4 sm:p-6 md:p-8">
      <div className="mx-auto max-w-2xl space-y-6">
        <div className="flex items-center justify-between rounded-lg border border-border/60 bg-secondary/20 px-4 py-3 text-sm">
          <span className="text-muted-foreground">PrepMate 0.1.0-alpha.1 · local desktop app</span>
          <a className="text-primary underline" href="/about">About and release details</a>
        </div>
        <ProviderSettings />
        <DataPrivacy />
      </div>
    </div>
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

export function AppShell({ theme = "dark", onToggleTheme, initialTab, initialImproveTarget = null }: AppShellProps) {
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
      default:
        return null
    }
  }
  const [refreshTrigger, setRefreshTrigger] = useState(0)
  const [activeNav, _setActiveNav] = useState<ActiveNav>(() => {
    const normalizedInitial = normalizeNav(initialTab)
    if (normalizedInitial) return normalizedInitial
    if (typeof window !== "undefined") {
      const stored = normalizeNav(safeStorageGet("session", "dashboard_tab"))
      if (stored) return stored
    }
    return "interview"
  })
  const activeNavRef = useRef<ActiveNav>(activeNav)
  activeNavRef.current = activeNav
  const setActiveNav = (nav: ActiveNav) => {
    if (nav === activeNavRef.current) return
    activeNavRef.current = nav
    _setActiveNav(nav)
    setRefreshTrigger((value) => value + 1)
    safeStorageSet("session", "dashboard_tab", nav)
  }
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [sidebarHovered, setSidebarHovered] = useState(false)
  const isExpanded = !sidebarCollapsed || sidebarHovered
  const { justParsed } = useResume()
  const [learning, setLearning] = useState<LearningDashboard | null>(null)
  const [learningLoading, setLearningLoading] = useState(true)
  const [learningError, setLearningError] = useState("")
  const learningReconcileAttemptedRef = useRef(false)
  const [interviews, setInterviews] = useState<PastInterview[]>([])
  const [improveTarget, setImproveTarget] = useState<ExactImproveTarget | null>(initialImproveTarget)
  const [providerConfigured, setProviderConfigured] = useState<boolean | null>(null)
  const navigationItems = primaryNavItems
  useEffect(() => {
    if (typeof window === "undefined") return
    if (activeNav !== "improve") {
      const publicTab = activeNav === "coding" ? "technical" : activeNav
      window.history.replaceState({}, "", `/?tab=${publicTab}`)
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
          setInterviews(
            activityData.activities.map((act: any) => ({
              id: act.id || act.interview_id || act.entity_id,
              date: act.created_at ? new Date(act.created_at).toLocaleDateString() : "Not recorded",
              role: act.subtitle || act.job_title || act.title || "General",
              type: act.type ? String(act.type).replace(/_/g, " ") : act.interview_type === "mock" ? "Full" : "Quick",
              score: act.score == null && act.overall_score == null
                ? null
                : Math.round(Number(act.score ?? act.overall_score)),
              status: act.status,
              cta: act.cta,
              duration: act.duration_seconds ?? 0,
              created_at: act.created_at || null,
              job_target: act.job_target || null,
            }))
          )
        }
      } catch (error: any) {
        setLearningError(error?.message || "Failed to load dashboard data.")
      } finally {
        setLearningLoading(false)
      }
    }
    if (activeNav === "improve" || activeNav === "interview" || activeNav === "coding" || activeNav === "performance") {
      loadDashboardData()
    }
  }, [activeNav, refreshTrigger])

  useEffect(() => {
    let cancelled = false
    void fetchLocalSettings()
      .then((settings) => {
        if (!cancelled) setProviderConfigured(Boolean(settings.has_api_key || settings.requires_api_key === false))
      })
      .catch(() => undefined)
    return () => { cancelled = true }
  }, [activeNav])

  // Poll for generating reports dynamically
  useEffect(() => {
    const isGeneratingReport = (interview: PastInterview) => {
      const status = String(interview.status || "").toLowerCase()
      return interview.cta?.nav === "report" && (
        ["analysis_pending", "analysis_queued", "analysis_running", "analyzing", "uploading"].includes(status)
        || String(interview.cta?.label || "").toLowerCase().includes("progress")
      )
    }
    const hasGenerating = interviews.some(isGeneratingReport)
    if (!hasGenerating) return

    let isPolling = true
    const interval = setInterval(async () => {
      if (document.hidden) return
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
            score: act.score == null && act.overall_score == null
              ? null
              : Math.round(Number(act.score ?? act.overall_score)),
            status: act.status,
            cta: act.cta,
            duration: act.duration_seconds ?? 0,
            created_at: act.created_at || null,
            job_target: act.job_target || null,
          }))

          // Check if any generating interview changed to something else
          const statusChanged = interviews.some((oldInt) => {
            if (!isGeneratingReport(oldInt)) return false
            const newInt = newInterviews.find((n: any) => n.id === oldInt.id)
            return newInt && !isGeneratingReport(newInt)
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
      case "settings": return "Settings"
      default: return "Interview Round"
    }
  }
  return (
    <>
      <PremiumBackground theme={theme} mode="base" />
      <div className="relative z-10 flex min-h-screen bg-transparent text-foreground">
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
                <span className="text-lg font-bold text-foreground">PrepMate</span>
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
              items={navigationItems}
              activeId={activeNav}
              onSelect={setActiveNav}
              collapsed={!isExpanded}
              expanded={isExpanded}
              className="flex-1"
            />
          </div>
        </aside>
        {mobileMenuOpen && (
          <div
            className="fixed inset-0 z-[200] bg-black/50 md:hidden"
            onClick={() => setMobileMenuOpen(false)}
          />
        )
        }
        <aside
          className={`fixed inset-y-0 left-0 z-[300] w-56 flex-col border-r border-border/40 bg-card/90 backdrop-blur-2xl transition-transform duration-300 md:hidden ${mobileMenuOpen ? "translate-x-0" : "-translate-x-full"
            }`}
        >
          <div className="flex h-16 items-center justify-between border-b border-border/40 px-6">
            <a
              href="/"
              onClick={(e) => { e.preventDefault(); setActiveNav("interview"); setMobileMenuOpen(false); window.scrollTo(0, 0); }}
              className="flex items-center gap-1.5 transition-opacity hover:opacity-80"
            >
              <ThemeLogo size={36} />
              <span className="text-lg font-bold text-foreground">PrepMate</span>
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
              items={navigationItems}
              activeId={activeNav}
              onSelect={(id) => {
                setActiveNav(id)
                setMobileMenuOpen(false)
              }}
              buttonClassName="h-auto min-h-10 gap-3 py-2.5 pl-3"
              className="flex-1"
            />
          </div>
        </aside>
        <main className="flex min-w-0 flex-1 flex-col bg-transparent">
          <header className="relative z-[100] flex h-16 min-w-0 items-center justify-between bg-card/40 px-4 shadow-[0_1px_12px_-2px_rgba(0,0,0,0.15)] backdrop-blur-xl md:px-8">
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
            <div className="flex items-center gap-4">
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
                variant="ghost"
                size="icon"
                onClick={() => setActiveNav("settings")}
                className="h-10 w-10 rounded-full border border-border bg-card p-0 hover:bg-accent"
                aria-label="Open local settings"
              >
                <Settings className="h-4 w-4 text-muted-foreground" />
              </Button>
            </div>
          </header>
          <>
            {providerConfigured === false && activeNav !== "settings" && (
              <div className="flex items-start justify-between gap-4 border-b border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-900 dark:text-amber-100 md:px-8">
                <div>
                  <p className="font-semibold">Finish local setup before starting a round</p>
                  <p className="mt-1 text-xs leading-5 opacity-85">Choose a provider or loopback model endpoint in Settings. PrepMate will test the connection before saving it.</p>
                </div>
                <Button size="sm" variant="outline" onClick={() => setActiveNav("settings")}>Open Settings</Button>
              </div>
            )}
            {(() => {
              switch (activeNav) {
                case "improve":
                  return (
                    <Suspense fallback={<WorkspacePanelFallback />}>
                      <LazyMissionImproveContent
                        learning={learning}
                        loading={learningLoading}
                        error={learningError}
                        setActiveNav={setActiveNav}
                        onLearningRefresh={refreshLearning}
                        navigationTarget={improveTarget}
                        onNavigationConsumed={() => {
                          setImproveTarget(null)
                        }}
                      />
                    </Suspense>
                  )
                case "interview":
                case "coding":
                  return (
                    <InterviewContent
                      key={activeNav}
                      interviews={interviews}
                      setActiveNav={setActiveNav}
                      mode={activeNav === "coding" ? "technical" : "interview"}
                      refreshKey={refreshTrigger}
                      onProfilesChanged={() => setRefreshTrigger((value) => value + 1)}
                    />
                  )
                case "resume":
                  return <ResumeContent />
                case "performance":
                  return (
                    <Suspense fallback={<WorkspacePanelFallback />}>
                      <LazyPerformanceContent onOpenPractice={(tab) => setActiveNav(tab)} />
                    </Suspense>
                  )
                case "settings":
                  return <SettingsContent />
                default:
                  return null
              }
            })()}
          </>
        </main>
      </div>
    </>
  )
}
