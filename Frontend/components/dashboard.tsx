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
  Flame,
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
  Eye,
  Loader2,
  Bug,
  MessageCircle,
  Send,
  Star,
  Plus,
  Target,
  Wrench,
  Pencil,
  Volume2,
  GitBranch,
  Shuffle,
  Scale,
  BadgeCheck,
  Bell,
  Download,
  Shield,
  Lock,
  Calendar,
  Camera,
  Receipt,
  Eye as EyeIcon,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import { toast } from "sonner"
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
  createSupportSubmission,
  fetchJobProfiles,
  createJobProfile,
  selectJobProfile,
  changePassword,
  deleteAccount,
  updateAccountInfo,
  uploadAvatar,
  exportUserData,
  deleteSessionHistory,
  getNotificationPrefs,
  updateNotificationPrefs,
  fetchPaymentTransactions,
} from "@/lib/api"
import type { JobProfile, NotificationPrefs } from "@/lib/api"
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
type ActiveNav = "dashboard" | "interview" | "resume" | "analytics" | "membership" | "settings"
const primaryNavItems: { icon: any; label: string; id: ActiveNav }[] = [
  { icon: LayoutDashboard, label: "Dashboard", id: "dashboard" },
  { icon: Play, label: "Interview", id: "interview" },
  { icon: FileText, label: "Profile", id: "resume" },
  { icon: BarChart3, label: "Analytics", id: "analytics" },
]
const secondaryNavItems: { icon: any; label: string; id: ActiveNav }[] = [
  { icon: CreditCard, label: "Membership", id: "membership" },
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
  todayDrill: {
    question: string
    question_type: string
    topic: string
    score: number
    user_answer: string
    steps: { title: string; instruction: string }[]
  } | null
  whatToFix: { title: string; diagnosis: string; fix: string }[]
  quantification: { answers_with_metrics: number; total_answers: number } | null
  averageScore: number | null
  totalInterviews: number
}
const defaultMetrics: DashboardMetrics = {
  coachingMetrics: {},
  primaryFocus: null,
  studentSummary: null,
  todayDrill: null,
  whatToFix: [],
  quantification: null,
  averageScore: null,
  totalInterviews: 0,
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
export { DashboardContent, InterviewContent, ResumeContent }
function DashboardContent({ metrics = defaultMetrics, setActiveNav }: { metrics?: DashboardMetrics; setActiveNav: (nav: ActiveNav) => void }) {
  const [builderType, setBuilderType] = useState("project")
  const hasData = Boolean(metrics.todayDrill)
  const drill = metrics.todayDrill
  const fixCards = metrics.whatToFix.length > 0
    ? metrics.whatToFix.slice(0, 2)
    : [
      {
        title: "No pattern yet",
        diagnosis: "Complete a mock interview so your weakest repeated habit can be detected from real answers.",
        fix: "The next dashboard update will show one direct diagnosis and one exact fix.",
      },
      {
        title: "No weak answer yet",
        diagnosis: "There is not enough answer history to build a personal drill.",
        fix: "Start one mock and the drill will target your lowest-scored answer.",
      },
    ]

  const builderSteps: Record<string, { label: string; steps: string[] }> = {
    project: {
      label: "Explain your project",
      steps: [
        "Open with the project outcome in one sentence.",
        "State your exact ownership, not the whole team scope.",
        "Name the core technical decision and why it fit.",
        "Add one constraint, trade-off, or failure case.",
        "Close with the metric, user impact, or shipped result.",
      ],
    },
    role: {
      label: "Why this role",
      steps: [
        "Name the specific part of the role that matches your past work.",
        "Prove the match with one project, internship, or shipped feature.",
        "Connect one company or product need to your skills.",
        "Say what you can own or improve in the first few months.",
        "Close with why this is a logical next step for you.",
      ],
    },
    technical: {
      label: "Technical deep-dive",
      steps: [
        "Give the direct answer before describing the system.",
        "Walk through the mechanism, data flow, or algorithm.",
        "Compare your approach with one alternative.",
        "Mention one bottleneck, edge case, or debugging signal.",
        "End with evidence from tests, production behavior, or a metric.",
      ],
    },
    intro: {
      label: "Tell me about yourself",
      steps: [
        "Start with your current professional focus.",
        "Use one relevant project or experience as proof.",
        "Name two skills that map to the role.",
        "Include one result or visible deliverable.",
        "Bridge directly into why this interview makes sense.",
      ],
    },
  }

  const exerciseModes = [
    { title: "Write it", icon: Pencil, text: "Draft the answer in five structured lines before saying it." },
    { title: "Say it", icon: Volume2, text: "Record a 60-second version and keep only the strongest proof." },
    { title: "Fix it", icon: Wrench, text: "Rewrite one weak answer by adding the missing number or trade-off." },
    { title: "Chain it", icon: GitBranch, text: "Answer the main question, then add the likely follow-up." },
    { title: "Blind Start", icon: Shuffle, text: "Start answering immediately with only the question visible." },
    { title: "Best vs Worst", icon: Scale, text: "Compare your weakest answer against the stronger structure." },
  ]

  return (
    <div className="flex-1 overflow-y-auto p-6 md:p-8 animate-fade-in-up">
      <div className="mb-6 rounded-xl border border-border/40 bg-card p-6 shadow-sm">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="text-xl font-semibold tracking-tight text-foreground">
              {hasData ? "Today, fix the answer that cost you most." : "Start with one mock to unlock a real drill."}
            </h2>
            <p className="mt-1.5 max-w-2xl text-sm leading-6 text-muted-foreground">
              {hasData
                ? "The dashboard now turns your weakest answer into a concrete exercise, not a vague score."
                : "After your first mock, this page will use your exact words, weakest pattern, and strongest next structure."}
            </p>
          </div>
          <Button className="shrink-0 gap-2 rounded-lg" onClick={() => setActiveNav("interview")}>
            <Play className="h-4 w-4" />
            Start Mock Interview
          </Button>
        </div>
      </div>

      <div className="mb-6 grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
        <div className="rounded-xl border border-border/40 bg-card p-6 shadow-sm">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-muted-foreground/70">Today's Drill</p>
              <h3 className="mt-2 text-lg font-semibold text-foreground">
                {drill?.question_type || "Weakest answer drill"}
              </h3>
            </div>
            {drill?.score !== undefined && (
              <span className="rounded-md border border-border/50 bg-secondary/30 px-2.5 py-1 text-xs font-semibold text-foreground">
                {Math.round(drill.score)}%
              </span>
            )}
          </div>
          {drill ? (
            <>
              <p className="rounded-lg border border-border/40 bg-secondary/25 p-4 text-sm font-medium leading-6 text-foreground">
                {drill.question}
              </p>
              <div className="mt-5 space-y-3">
                {drill.steps.map((step, index) => (
                  <div key={`${step.title}-${index}`} className="flex gap-3">
                    <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-primary text-xs font-bold text-primary-foreground">
                      {index + 1}
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-foreground">{step.title}</p>
                      <p className="mt-0.5 text-sm leading-6 text-muted-foreground">{step.instruction}</p>
                    </div>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <div className="flex min-h-[260px] flex-col items-center justify-center rounded-lg border border-dashed border-border/70 bg-secondary/20 p-8 text-center">
              <Target className="mb-3 h-8 w-8 text-muted-foreground/60" />
              <p className="text-sm font-medium text-foreground">No weak answer detected yet</p>
              <p className="mt-1 max-w-sm text-sm leading-6 text-muted-foreground">Run one mock interview and this card will pull the lowest-scored answer into a five-step drill.</p>
            </div>
          )}
        </div>

        <div className="rounded-xl border border-border/40 bg-card p-6 shadow-sm">
          <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-muted-foreground/70">Answer Builder</p>
              <h3 className="mt-2 text-lg font-semibold text-foreground">{builderSteps[builderType].label}</h3>
            </div>
            <Select value={builderType} onValueChange={setBuilderType}>
              <SelectTrigger className="h-9 w-full sm:w-[210px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="project">Explain your project</SelectItem>
                <SelectItem value="role">Why this role</SelectItem>
                <SelectItem value="technical">Technical deep-dive</SelectItem>
                <SelectItem value="intro">Tell me about yourself</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-3">
            {builderSteps[builderType].steps.map((step, index) => (
              <div key={step} className="rounded-lg border border-border/35 bg-secondary/20 p-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Step {index + 1}</p>
                <p className="mt-1 text-sm leading-6 text-foreground">{step}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="mb-6 grid gap-4 md:grid-cols-2">
        {fixCards.map((card) => (
          <div key={card.title} className="rounded-xl border border-border/40 bg-card p-5 shadow-sm">
            <div className="mb-3 flex items-center gap-2">
              <Wrench className="h-4 w-4 text-amber-500" />
              <h3 className="text-sm font-semibold text-foreground">{card.title}</h3>
            </div>
            <p className="text-sm leading-6 text-muted-foreground">{card.diagnosis}</p>
            <p className="mt-2 text-sm leading-6 text-foreground/85">{card.fix}</p>
          </div>
        ))}
      </div>

      <div className="rounded-xl border border-border/40 bg-card p-6 shadow-sm">
        <div className="mb-4">
          <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-muted-foreground/70">Exercise Modes</p>
          <h3 className="mt-2 text-lg font-semibold text-foreground">Pick the smallest useful rep.</h3>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {exerciseModes.map((mode) => (
            <button
              key={mode.title}
              type="button"
              className="group flex min-h-[112px] flex-col items-start rounded-lg border border-border/40 bg-secondary/20 p-4 text-left transition-colors hover:border-primary/30 hover:bg-primary/5"
            >
              <div className="mb-3 flex h-8 w-8 items-center justify-center rounded-md bg-card ring-1 ring-border/50 text-primary">
                <mode.icon className="h-4 w-4" />
              </div>
              <p className="text-sm font-semibold text-foreground">{mode.title}</p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">{mode.text}</p>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
function InterviewContent({
  interviews = [],
  setActiveNav
}: {
  interviews?: PastInterview[]
  setActiveNav: (nav: ActiveNav) => void
}) {
  const router = useRouter()
  const [isStartingMock, setIsStartingMock] = useState(false)
  const [profiles, setProfiles] = useState<JobProfile[]>([])
  const [selectedProfileId, setSelectedProfileId] = useState<number | null>(null)
  const [loadingProfiles, setLoadingProfiles] = useState(true)
  const [showProfileDialog, setShowProfileDialog] = useState(false)
  const [newRole, setNewRole] = useState("")
  const [newCompany, setNewCompany] = useState("")
  const [newTechStack, setNewTechStack] = useState("")
  const [savingProfile, setSavingProfile] = useState(false)

  useEffect(() => {
    async function loadProfiles() {
      try {
        setLoadingProfiles(true)
        const data = await fetchJobProfiles()
        setProfiles(data)
        const selected = data.find((profile) => profile.is_selected) || data[0]
        setSelectedProfileId(selected?.profile_id ?? null)
      } catch (error: any) {
        toast.error(error?.message || "Failed to load job profiles.")
      } finally {
        setLoadingProfiles(false)
      }
    }
    loadProfiles()
  }, [])

  const handleSelectProfile = async (profileId: number) => {
    setSelectedProfileId(profileId)
    setProfiles((items) => items.map((item) => ({ ...item, is_selected: item.profile_id === profileId })))
    try {
      await selectJobProfile(profileId)
    } catch (error: any) {
      toast.error(error?.message || "Failed to select job profile.")
    }
  }

  const handleCreateProfile = async () => {
    if (!newRole.trim()) {
      toast.error("Add a role for this profile.")
      return
    }
    const tags = newTechStack.split(",").map((item) => item.trim()).filter(Boolean)
    try {
      setSavingProfile(true)
      const created = await createJobProfile({
        role: newRole.trim(),
        company: newCompany.trim() || undefined,
        tech_stack: tags,
      })
      const selected = await selectJobProfile(created.profile_id)
      setProfiles((items) => [{ ...selected, is_selected: true }, ...items.map((item) => ({ ...item, is_selected: false }))])
      setSelectedProfileId(selected.profile_id)
      setNewRole("")
      setNewCompany("")
      setNewTechStack("")
      setShowProfileDialog(false)
      toast.success("Job profile saved.")
    } catch (error: any) {
      toast.error(error?.message || "Failed to save job profile.")
    } finally {
      setSavingProfile(false)
    }
  }

  const startMockInterview = async () => {
    if (!selectedProfileId) {
      toast.error("Create or select a job profile first.")
      setShowProfileDialog(true)
      return
    }
    setIsStartingMock(true)
    try {
      const response = await startInterviewSession("mock", "Mock Interview", selectedProfileId)
      const interviewId = response.interview_id || response.session_id
      router.push(`/interview/${interviewId}?mode=mock-voice`)
    } catch (error: any) {
      const msg = error?.message || "Failed to start mock interview."
      if (msg.toLowerCase().includes('no interviews remaining') || msg.toLowerCase().includes('no credits')) {
        toast.error('Your current plan cannot start another mock right now.')
        setActiveNav("membership")
      } else {
        toast.error(msg)
      }
    } finally {
      setIsStartingMock(false)
    }
  }

  return (
    <div className="flex-1 overflow-y-auto p-6 md:p-8 animate-fade-in-up">
      <div className="mb-6 rounded-xl border border-border/40 bg-card p-6 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-muted-foreground/70">Mock Interview</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-foreground">Choose a saved job profile, then start.</h2>
            <p className="mt-1.5 max-w-2xl text-sm leading-6 text-muted-foreground">
              Profiles are saved once with role, company, and stack tags. You can switch the interview target with one tap.
            </p>
          </div>
          <Button onClick={startMockInterview} disabled={isStartingMock || loadingProfiles} className="gap-2 rounded-lg px-6">
            {isStartingMock ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {isStartingMock ? "Starting..." : "Start Mock Interview"}
          </Button>
        </div>
      </div>

      <div className="mb-8 rounded-xl border border-border/40 bg-card p-6 shadow-sm">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h3 className="text-base font-semibold text-foreground">Saved Profiles</h3>
            <p className="mt-1 text-xs text-muted-foreground">Pick one profile for this mock session.</p>
          </div>
          <Button variant="outline" size="sm" onClick={() => setShowProfileDialog(true)} className="gap-2 rounded-lg">
            <Plus className="h-4 w-4" />
            Add Profile
          </Button>
        </div>

        {loadingProfiles ? (
          <div className="flex items-center justify-center rounded-lg border border-dashed border-border py-12">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            <span className="ml-2 text-sm text-muted-foreground">Loading profiles...</span>
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {profiles.map((profile) => {
              const selected = selectedProfileId === profile.profile_id
              return (
                <button
                  key={profile.profile_id}
                  type="button"
                  onClick={() => handleSelectProfile(profile.profile_id)}
                  className={`min-h-[150px] rounded-lg border p-4 text-left transition-colors ${selected
                    ? "border-primary/50 bg-primary/5 ring-1 ring-primary/30"
                    : "border-border/40 bg-secondary/20 hover:border-primary/25 hover:bg-primary/5"
                    }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-foreground">{profile.role}</p>
                      <p className="mt-1 truncate text-xs text-muted-foreground">{profile.company || "Any company"}</p>
                    </div>
                    {selected && <Check className="h-4 w-4 shrink-0 text-primary" />}
                  </div>
                  <div className="mt-4 flex flex-wrap gap-1.5">
                    {profile.tech_stack.length > 0 ? profile.tech_stack.slice(0, 5).map((tag) => (
                      <span key={tag} className="rounded-md border border-border/40 bg-card px-2 py-1 text-[11px] font-medium text-muted-foreground">
                        {tag}
                      </span>
                    )) : (
                      <span className="text-xs text-muted-foreground">No stack tags yet</span>
                    )}
                  </div>
                </button>
              )
            })}

            <button
              type="button"
              onClick={() => setShowProfileDialog(true)}
              className="flex min-h-[150px] flex-col items-center justify-center rounded-lg border border-dashed border-border/70 bg-secondary/20 p-4 text-center transition-colors hover:border-primary/30 hover:bg-primary/5"
            >
              <Plus className="mb-2 h-5 w-5 text-primary" />
              <span className="text-sm font-semibold text-foreground">Add Profile</span>
              <span className="mt-1 text-xs text-muted-foreground">Role, company, stack tags</span>
            </button>
          </div>
        )}
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
      <Dialog open={showProfileDialog} onOpenChange={setShowProfileDialog}>
        <DialogContent className="max-w-md border-border bg-card">
          <DialogHeader>
            <DialogTitle className="text-lg font-bold text-foreground">Add Job Profile</DialogTitle>
            <DialogDescription className="mt-2 text-sm text-muted-foreground">
              Save the interview target once. You can pick it again from the grid.
            </DialogDescription>
          </DialogHeader>
          <div className="mt-4 space-y-4">
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Role</Label>
              <Input value={newRole} onChange={(event) => setNewRole(event.target.value)} placeholder="Frontend Engineer" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Company</Label>
              <Input value={newCompany} onChange={(event) => setNewCompany(event.target.value)} placeholder="Acme" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Tech Stack Tags</Label>
              <Input value={newTechStack} onChange={(event) => setNewTechStack(event.target.value)} placeholder="React, TypeScript, Node" />
              <p className="text-xs text-muted-foreground">Separate tags with commas.</p>
            </div>
          </div>
          <DialogFooter className="mt-5 flex gap-3">
            <Button variant="outline" className="flex-1" onClick={() => setShowProfileDialog(false)} disabled={savingProfile}>Cancel</Button>
            <Button className="flex-1 gap-2" onClick={handleCreateProfile} disabled={savingProfile}>
              {savingProfile ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              Save Profile
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
function AnalyticsContent({ setActiveNav }: { setActiveNav: (nav: ActiveNav) => void }) {
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
    summary,
    followup_performance,
    answer_comparisons = [],
    pattern_diagnoses = [],
    best_answer_of_week,
    weak_question_drill_queue = [],
    quantification,
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

  const scoreColor = (s: number) => s >= 80 ? "text-emerald-500" : s >= 60 ? "text-amber-500" : "text-rose-500"
  const mainScore = Math.round(followup_performance?.main_avg || 0)
  const followupScore = Math.round(followup_performance?.followup_avg || 0)
  const followupInsight = followup_performance?.followup_count
    ? `You scored ${mainScore} on main questions but ${followupScore} on follow-ups. Your problem is ${followupScore < mainScore - 8 ? "depth after the first answer" : "consistency, not just starting"}.`
    : "No follow-up answers have been recorded yet, so depth under pressure is still unknown."
  const metricCount = quantification?.answers_with_metrics ?? 0
  const totalAnswers = quantification?.total_answers ?? summary.total_questions ?? 0
  const handleStartDrill = () => {
    toast.success("Drill queue opened on the dashboard.")
    setActiveNav("dashboard")
  }

  return (
    <div className="flex-1 overflow-y-auto p-6 md:p-8 animate-fade-in-up">
      <div className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-4">
        <div className="rounded-xl border border-border/40 bg-card p-5 shadow-sm">
          <p className="mb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">Average Score</p>
          <p className={`text-2xl font-semibold tracking-tight ${scoreColor(summary.average_score)}`}>{summary.average_score}%</p>
          <p className="mt-1 text-xs text-muted-foreground">Best: {summary.best_score}% · Lowest: {summary.worst_score}%</p>
        </div>
        <div className="rounded-xl border border-border/40 bg-card p-5 shadow-sm">
          <p className="mb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">Total Interviews</p>
          <p className="text-2xl font-semibold tracking-tight text-foreground">{summary.total_interviews}</p>
          <p className="mt-1 text-xs text-muted-foreground">Sessions completed</p>
        </div>
        <div className="rounded-xl border border-border/40 bg-card p-5 shadow-sm">
          <p className="mb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">Quantification Score</p>
          <p className="text-2xl font-semibold tracking-tight text-foreground">{metricCount}</p>
          <p className="mt-1 text-xs text-muted-foreground">Answers with a real metric or result out of {totalAnswers}</p>
        </div>
        <div className="rounded-xl border border-border/40 bg-card p-5 shadow-sm">
          <p className="mb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">Follow-up Gap</p>
          <p className={`text-2xl font-semibold tracking-tight ${scoreColor(followupScore)}`}>{mainScore} / {followupScore}</p>
          <p className="mt-1 text-xs text-muted-foreground">Main vs follow-up average</p>
        </div>
      </div>

      <div className="mb-6 rounded-xl border border-border/40 bg-card p-6 shadow-sm">
        <div className="mb-5">
          <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-muted-foreground/70">Your Answer vs A Strong Answer</p>
          <h3 className="mt-2 text-lg font-semibold text-foreground">Worst-scored questions</h3>
        </div>
        {answer_comparisons.length === 0 ? (
          <p className="text-sm text-muted-foreground">No answer comparisons are available yet.</p>
        ) : (
          <div className="space-y-5">
            {answer_comparisons.slice(0, 3).map((item: any, index: number) => (
              <div key={`${item.question}-${index}`} className="rounded-lg border border-border/35 bg-secondary/15 p-4">
                <div className="mb-4 flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
                  <div>
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">{item.topic}</p>
                    <p className="mt-1 text-sm font-semibold leading-6 text-foreground">{item.question}</p>
                  </div>
                  <span className={`shrink-0 text-xs font-semibold ${scoreColor(item.score)}`}>{Math.round(item.score)}%</span>
                </div>
                <div className="grid gap-4 lg:grid-cols-2">
                  <div className="rounded-lg border border-border/35 bg-card p-4">
                    <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Their Actual Words</p>
                    <p className="whitespace-pre-wrap text-sm leading-6 text-muted-foreground">{item.their_answer}</p>
                  </div>
                  <div className="rounded-lg border border-primary/20 bg-primary/5 p-4">
                    <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-primary">Strong Answer Shape</p>
                    <p className="text-sm leading-6 text-foreground/90">{item.strong_answer}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="mb-6 grid gap-6 lg:grid-cols-[0.95fr_1.05fr]">
        <div className="rounded-xl border border-border/40 bg-card p-6 shadow-sm">
          <div className="mb-4 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-500" />
            <h3 className="text-sm font-semibold text-foreground">Pattern Diagnosis</h3>
          </div>
          <div className="space-y-3">
            {pattern_diagnoses.length === 0 ? (
              <p className="text-sm text-muted-foreground">No repeated patterns detected yet.</p>
            ) : pattern_diagnoses.map((pattern: any) => (
              <div key={pattern.title} className="rounded-lg border border-border/35 bg-secondary/20 p-4">
                <p className="text-sm font-semibold text-foreground">{pattern.title}</p>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">{pattern.diagnosis}</p>
                <p className="mt-2 text-sm leading-6 text-foreground/85">{pattern.fix}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-xl border border-border/40 bg-card p-6 shadow-sm">
          <div className="mb-4 flex items-center gap-2">
            <Target className="h-4 w-4 text-primary" />
            <h3 className="text-sm font-semibold text-foreground">Follow-up Collapse Insight</h3>
          </div>
          <p className="text-sm leading-6 text-muted-foreground">{followupInsight}</p>
          <div className="mt-5 grid grid-cols-2 gap-3">
            <div className="rounded-lg border border-border/35 bg-secondary/20 p-4">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Main Questions</p>
              <p className={`mt-2 text-2xl font-semibold ${scoreColor(mainScore)}`}>{mainScore}%</p>
            </div>
            <div className="rounded-lg border border-border/35 bg-secondary/20 p-4">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Follow-ups</p>
              <p className={`mt-2 text-2xl font-semibold ${scoreColor(followupScore)}`}>{followupScore}%</p>
            </div>
          </div>
        </div>
      </div>

      <div className="mb-6 grid gap-6 lg:grid-cols-[1.05fr_0.95fr]">
        <div className="rounded-xl border border-border/40 bg-card p-6 shadow-sm">
          <div className="mb-4 flex items-center gap-2">
            <BadgeCheck className="h-4 w-4 text-emerald-500" />
            <h3 className="text-sm font-semibold text-foreground">Best Answer of the Week</h3>
          </div>
          {best_answer_of_week ? (
            <div>
              <div className="mb-4 flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">{best_answer_of_week.topic}</p>
                  <p className="mt-1 text-sm font-semibold leading-6 text-foreground">{best_answer_of_week.question}</p>
                </div>
                <span className={`shrink-0 text-xs font-semibold ${scoreColor(best_answer_of_week.score)}`}>{Math.round(best_answer_of_week.score)}%</span>
              </div>
              <p className="whitespace-pre-wrap rounded-lg border border-border/35 bg-secondary/15 p-4 text-sm leading-6 text-muted-foreground">
                {best_answer_of_week.answer}
              </p>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No best answer is available yet.</p>
          )}
        </div>

        <div className="rounded-xl border border-border/40 bg-card p-6 shadow-sm">
          <div className="mb-4 flex items-center gap-2">
            <Play className="h-4 w-4 text-primary" />
            <h3 className="text-sm font-semibold text-foreground">Weak Question Drill Queue</h3>
          </div>
          <div className="space-y-3">
            {weak_question_drill_queue.length === 0 ? (
              <p className="text-sm text-muted-foreground">No weak questions are queued yet.</p>
            ) : weak_question_drill_queue.slice(0, 3).map((item: any, index: number) => (
              <div key={`${item.question}-${index}`} className="rounded-lg border border-border/35 bg-secondary/20 p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">{item.question_type} · {item.topic}</p>
                    <p className="mt-1 text-sm font-medium leading-6 text-foreground">{item.question}</p>
                  </div>
                  <span className={`shrink-0 text-xs font-semibold ${scoreColor(item.score)}`}>{Math.round(item.score)}%</span>
                </div>
                <Button size="sm" className="mt-3 gap-2 rounded-lg" onClick={handleStartDrill}>
                  <Play className="h-3.5 w-3.5" />
                  Start
                </Button>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function SettingsContent({
  onOpenMembership,
  onOpenLogout,
  user
}: {
  onOpenMembership: () => void
  onOpenLogout: () => void
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

  // Lazy-import the tab components to avoid bloating this file
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

  return (
    <div className="flex-1 overflow-y-auto p-6 md:p-8 animate-fade-in-up">
      <Tabs defaultValue="account" className="w-full">
        <TabsList className="mb-6 w-full justify-start bg-transparent p-0 flex-wrap gap-1">
          <TabsTrigger value="account" className="rounded-lg data-[state=active]:bg-secondary">Account</TabsTrigger>
          <TabsTrigger value="notifications" className="rounded-lg data-[state=active]:bg-secondary">Notifications</TabsTrigger>
          <TabsTrigger value="billing" className="rounded-lg data-[state=active]:bg-secondary">Membership & Billing</TabsTrigger>
          <TabsTrigger value="privacy" className="rounded-lg data-[state=active]:bg-secondary">Privacy & Data</TabsTrigger>
          <TabsTrigger value="support" className="rounded-lg data-[state=active]:bg-secondary">Support</TabsTrigger>
        </TabsList>
        <TabsContent value="account">
          {AccountTab ? <AccountTab user={user} onAccountDeleted={onOpenLogout} /> : <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>}
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
            <div className="rounded-2xl border border-border/40 bg-card shadow-sm p-6">
              <div className="mb-1 flex items-center gap-2">
                <Bug className="h-4 w-4 text-red-400" />
                <h3 className="text-sm font-semibold text-foreground">Report a Bug</h3>
              </div>
              <p className="mb-5 text-xs text-muted-foreground">Found something broken? Send it into the support inbox with enough detail to reproduce it.</p>
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
function MembershipContent() {
  const router = useRouter()
  const [billing, setBilling] = useState<"monthly" | "annual">("monthly")
  const isAnnual = billing === "annual"

  const starterFeatures = [
    "Mock interviews to practice with",
    "Performance analysis after every session",
    "Access for a full month",
  ]

  const starterExcluded = [
    "Coaching and answer breakdowns",
    "Exercise modes and drills",
  ]

  const proFeatures = [
    "Unlimited mock interviews",
    "Full answer coaching after every session",
    "Personalised drill queue based on weak patterns",
    "All 6 exercise modes",
    "Answer builder with guided frameworks",
    "Deep analytics and pattern diagnosis",
    "Unlimited job profiles",
  ]

  const premiumFeatures = [
    "Everything in Pro, plus:",
    "Technical interview rounds",
    "Built-in code editor",
    "Step-by-step problem walkthroughs",
    "Hints system during technical sessions",
    "Technical performance review",
  ]

  const proPricing = { monthly: 999, annual: 899, annualBilled: 10788 }
  const premiumPricing = { monthly: 1499, annual: 1349, annualBilled: 16188 }

  const fmt = (n: number) => `₹${n.toLocaleString("en-IN")}`

  return (
    <div className="flex-1 overflow-y-auto p-6 md:p-8 animate-fade-in-up">
      <div className="mb-6 rounded-xl border border-border/40 bg-card p-6 shadow-sm">
        <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-muted-foreground/70">Pricing</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-foreground">Plans for every stage of prep.</h2>
            <p className="mt-1.5 max-w-2xl text-sm leading-6 text-muted-foreground">
              Start light or go all-in. Every plan includes real interview practice.
            </p>
          </div>
          <div className="flex flex-wrap gap-2 text-xs font-medium text-muted-foreground">
            <span className="rounded-md border border-border/50 bg-secondary/20 px-3 py-1.5">Cancel anytime</span>
            <span className="rounded-md border border-border/50 bg-secondary/20 px-3 py-1.5">No commitment</span>
          </div>
        </div>
      </div>

      {/* ── Billing Toggle ── */}
      <div className="mb-6 flex items-center justify-center gap-3">
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
          Save 10%
        </span>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">

        {/* ─── Starter Column ─── */}
        <div className="flex flex-col rounded-xl border border-border/40 bg-card p-6 shadow-sm">
          <div className="mb-5">
            <h3 className="text-lg font-semibold text-foreground">Starter</h3>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">Get interview ready</p>
          </div>
          <div className="mb-3">
            <div className="flex items-baseline gap-1">
              <span className="text-3xl font-bold tracking-tight text-foreground">{fmt(299)}</span>
              <span className="text-sm text-muted-foreground">/ month</span>
            </div>
          </div>
          <p className="mb-5 text-sm text-muted-foreground">Enough practice to build real confidence</p>

          <div className="flex-1 space-y-2">
            {starterFeatures.map((f) => (
              <div key={f} className="flex items-center gap-2 text-sm text-muted-foreground">
                <Check className="h-4 w-4 shrink-0 text-primary" />
                <span>{f}</span>
              </div>
            ))}
            {starterExcluded.map((f) => (
              <div key={f} className="flex items-center gap-2 text-sm text-muted-foreground">
                <X className="h-4 w-4 shrink-0 text-muted-foreground/40" />
                <span className="text-muted-foreground/50">{f}</span>
              </div>
            ))}
          </div>
          <Button className="mt-6 w-full rounded-lg" variant="outline" onClick={() => router.push("/checkout?plan=starter")}>
            Get started
          </Button>
        </div>

        {/* ─── Pro Column (Featured) ─── */}
        <div className="flex flex-col rounded-xl border border-primary/40 bg-primary/5 ring-1 ring-primary/20 p-6 shadow-sm">
          <div className="mb-5 flex items-start justify-between gap-3">
            <div>
              <h3 className="text-lg font-semibold text-foreground">Pro</h3>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">Unlock the full experience</p>
            </div>
            <span className="shrink-0 rounded-md bg-primary/10 px-2.5 py-1 text-xs font-bold text-primary">Most popular</span>
          </div>
          <div className="mb-3">
            <div className="flex items-baseline gap-1">
              <span className="text-3xl font-bold tracking-tight text-foreground">{fmt(isAnnual ? proPricing.annual : proPricing.monthly)}</span>
              <span className="text-sm text-muted-foreground">/ month</span>
            </div>
            {isAnnual && <p className="mt-1 text-xs font-medium text-muted-foreground">billed {fmt(proPricing.annualBilled)} / year</p>}
          </div>
          <p className="mb-5 text-sm text-muted-foreground">Everything in Starter, and:</p>
          <div className="flex-1 space-y-2">
            {proFeatures.map((feature) => (
              <div key={feature} className="flex items-center gap-2 text-sm text-muted-foreground">
                <Check className="h-4 w-4 shrink-0 text-primary" />
                <span>{feature}</span>
              </div>
            ))}
          </div>
          <Button className="mt-6 w-full rounded-lg" variant="default" onClick={() => router.push(`/checkout?plan=pro${isAnnual ? "&cycle=annual" : ""}`)}>
            Get Pro
          </Button>
        </div>

        {/* ─── Premium Column ─── */}
        <div className="flex flex-col rounded-xl border border-border/40 bg-card p-6 shadow-sm">
          <div className="mb-5 flex items-start justify-between gap-3">
            <div>
              <h3 className="text-lg font-semibold text-foreground">Premium</h3>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">Ace every round, including technical</p>
            </div>
            <span className="shrink-0 rounded-md bg-violet-500/10 px-2.5 py-1 text-xs font-bold text-violet-600 dark:text-violet-400">Full package</span>
          </div>
          <div className="mb-3">
            <div className="flex items-baseline gap-1">
              <span className="text-3xl font-bold tracking-tight text-foreground">{fmt(isAnnual ? premiumPricing.annual : premiumPricing.monthly)}</span>
              <span className="text-sm text-muted-foreground">/ month</span>
            </div>
            {isAnnual && <p className="mt-1 text-xs font-medium text-muted-foreground">billed {fmt(premiumPricing.annualBilled)} / year</p>}
          </div>
          <div className="flex-1 space-y-2">
            {premiumFeatures.map((feature) => (
              <div key={feature} className="flex items-center gap-2 text-sm text-muted-foreground">
                <Check className="h-4 w-4 shrink-0 text-primary" />
                <span>{feature}</span>
              </div>
            ))}
          </div>
          <Button className="mt-6 w-full rounded-lg" variant="default" onClick={() => router.push(`/checkout?plan=premium${isAnnual ? "&cycle=annual" : ""}`)}>
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
export function Dashboard({ onLogout, theme = "dark", onToggleTheme, onUploadResume, user, initialTab }: DashboardProps) {
  const [activeNav, _setActiveNav] = useState<ActiveNav>(() => {
    // Priority: URL param > sessionStorage > default
    if (initialTab) return initialTab
    if (typeof window !== "undefined") {
      const stored = sessionStorage.getItem("dashboard_tab") as ActiveNav | null
      if (stored && ["dashboard", "interview", "resume", "analytics", "membership", "settings"].includes(stored)) return stored
    }
    return "dashboard"
  })
  const setActiveNav = (nav: ActiveNav) => {
    _setActiveNav(nav)
    sessionStorage.setItem("dashboard_tab", nav)
  }
  const [showLogout, setShowLogout] = useState(false)
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const { justParsed } = useResume()
  const [metrics, setMetrics] = useState<DashboardMetrics>(defaultMetrics)
  const [interviews, setInterviews] = useState<PastInterview[]>([])
  const [streakDays, setStreakDays] = useState(0)
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
            todayDrill: statsData.today_drill || null,
            whatToFix: statsData.what_to_fix || [],
            quantification: statsData.quantification || null,
            averageScore: statsData.average_score ?? null,
            totalInterviews: statsData.total_interviews || 0,
          })
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
      case "membership": return "Membership"
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
      case "membership": return "Pick the plan that fits your prep"
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
            {primaryNavItems.map((item) => (
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
            <div className="flex flex-col gap-1">
              {secondaryNavItems.map((item) => (
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
            </div>
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
            {primaryNavItems.map((item) => (
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
            <div className="flex flex-col gap-1">
              {secondaryNavItems.map((item) => (
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
            </div>
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
              <div className="flex items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-1.5 text-xs font-semibold text-foreground">
                <Flame className="h-3.5 w-3.5 text-orange-500" />
                <span>{streakDays} day{streakDays === 1 ? "" : "s"}</span>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setActiveNav("membership")}
                className="hidden gap-1.5 text-xs sm:inline-flex"
              >
                <CreditCard className="h-3.5 w-3.5 text-primary" />
                Membership
              </Button>
            </div>
          </header>
          <>
            {(() => {
              switch (activeNav) {
                case "dashboard":
                  return <DashboardContent metrics={metrics} setActiveNav={setActiveNav} />
                case "interview":
                  return <InterviewContent interviews={interviews} setActiveNav={setActiveNav} />
                case "resume":
                  return <ResumeContent onUploadResume={onUploadResume} />
                case "analytics":
                  return <AnalyticsContent setActiveNav={setActiveNav} />
                case "membership":
                  return <MembershipContent />
                case "settings":
                  return <SettingsContent onOpenMembership={() => setActiveNav("membership")} onOpenLogout={() => setShowLogout(true)} user={user} />
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
