"use client"

import dynamic from "next/dynamic"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Code2,
  FileText,
  HelpCircle,
  LayoutPanelLeft,
  Loader2,
  Lock,
  Mic,
  MicOff,
  Play,
  ShieldAlert,
  ShieldCheck,
  SquareTerminal,
  Upload,
  Timer,
} from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { getAuthHeaders } from "@/lib/auth"
import { abandonInterviewSession, cancelInterviewSession, endInterviewSession } from "@/lib/api"
import { API_CONFIG } from "@/lib/config"
import { cn } from "@/lib/utils"
import { readRecoveryGraceSeconds } from "@/lib/session-integrity"
import {
  consumePreflightFlag,
  getTechnicalCameraStream,
  getTechnicalPermissionState,
  releaseTechnicalPermissions,
  requestTechnicalPermissions,
  subscribeTechnicalPermissionState,
  type TechnicalPermissionState,
} from "@/lib/technical-permissions"
import {
  integrityWarningMessage,
  type AntiCheatRecordResult,
} from "@/lib/technical-integrity"
import { useFaceCheck } from "@/hooks/use-face-check"
import { useObjectDetection } from "@/hooks/use-object-detection"
import { useAudioEnvironment } from "@/hooks/use-audio-environment"
import { useSessionControlLock } from "@/hooks/use-session-control-lock"
import { WaveformVisualizer } from "@/components/interview/waveform-visualizer"

const MonacoEditor = dynamic(() => import("@monaco-editor/react"), { ssr: false })

type RoundType = string
type Language = "python" | "javascript" | "cpp" | "java"

type Round = {
  round_id: string
  round_type: RoundType
  language: Language | null
  prompt: string
  starter_code: string | null
  whiteboard_json: unknown
  status: string
  metadata?: Record<string, any>
  round_spec?: Record<string, any>
  started_at?: string | null
  expires_at?: string | null
  remaining_seconds?: number | null
  target_duration_seconds?: number | null
  locked_reason?: string | null
  mode?: "mock" | "practice" | string
  max_submissions?: number
  workflow_state?: Record<string, any>
  round_number?: number
}

type TestCase = {
  stdin?: string
  expected?: string
  explanation?: string
}

type CaseResult = {
  index: number
  case_number?: number
  hidden?: boolean
  verdict: "Accepted" | "Wrong Answer" | "TLE" | "Runtime Error" | string
  passed: boolean
  stdin?: string
  expected?: string
  actual?: string
  runtime_ms: number
  memory_kb?: number
  stderr?: string
}

type RunResult = {
  run_id?: string
  executor?: string
  status?: "queued" | "running" | "completed" | "failed" | string
  stdout?: string
  stderr?: string
  exit_code?: number | null
  verdict?: string
  runtime_ms: number
  memory_kb?: number
  suite?: string
  visible_passed?: number
  visible_total?: number
  hidden_passed?: number | null
  hidden_total?: number | null
  pass_count?: number
  total_count?: number
  cases?: CaseResult[]
  locked?: boolean
  submits_left?: number | null
  error?: string
  poll_after_ms?: number
  idempotent_replay?: boolean
  compile?: { status?: string }
  run?: { status?: string; verdict?: string | null; runtime_ms?: number; memory_kb?: number }
  test_summary?: { passed: number; total: number }
  hidden_details?: null
}

type TechnicalResponseResult = {
  round_id: string
  response_id: string
  idempotency_key: string
  status: "committed" | string
  duplicate?: boolean
  assessment?: Record<string, any> | null
  decision?: Record<string, any> | string | null
}

type RecoverableRun = {
  runId: string
  roundId: string
  action: "test" | "custom-run" | "submit"
}

type CodingWorkflowDraft = {
  complexity: string
  explanation: string
}

type JobContext = {
  role?: string | null
  company?: string | null
  job_title?: string | null
  jd_summary?: string | null
  key_skills?: string[]
  profile_type?: string | null
  profile_label?: string | null
}

class RunPollingTimeout extends Error {
  constructor() {
    super("The code runner is still processing. Resume status checks without submitting again.")
    this.name = "RunPollingTimeout"
  }
}

async function sourceSha256(value: string): Promise<string> {
  const bytes = new TextEncoder().encode(value)
  const digest = await crypto.subtle.digest("SHA-256", bytes)
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("")
}

type InfoTab = "description"

const labels: Record<RoundType, string> = {
  dsa: "Coding",
  coding: "Coding",
  debugging: "Debugging",
  technical_concept: "Technical concept",
  system_design: "System design",
  ml: "Machine learning",
  backend: "Backend engineering",
  database: "Databases",
  os: "Operating systems",
  network: "Networking",
  oop: "Object-oriented design",
}

const languageLabels: Record<string, string> = {
  python: "Python3",
  javascript: "JavaScript",
  java: "Java",
  cpp: "C++",
}

const infoTabs: Array<{ id: InfoTab; label: string }> = [
  { id: "description", label: "Description" },
]

const finalizedInterviewStatuses = new Set([
  "analysis_pending",
  "analysis_queued",
  "analysis_running",
  "analyzing",
  "completed",
  "partial",
  "partial_report",
  "failed",
  "ended",
  "report_ready",
  "analyzed",
])

const nonReportableInterviewStatuses = new Set(["cancelled"])

function visibleTests(round?: Round): TestCase[] {
  const tests = round?.metadata?.visible_tests
  return Array.isArray(tests) && tests.length > 0 ? tests : []
}

function formatRoundType(value: RoundType) {
  return labels[value] || value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase())
}

function formatDifficulty(value: unknown) {
  if (!value) return "Medium"
  return String(value)
    .replace(/_/g, " ")
    .replace(/-/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase())
}

function difficultyClass(value: string) {
  const lower = value.toLowerCase()
  if (lower.includes("easy")) return "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
  if (lower.includes("hard")) return "bg-rose-500/15 text-rose-700 dark:text-rose-300"
  return "bg-amber-500/15 text-amber-700 dark:text-amber-300"
}

function problemTitle(round: Round | undefined, index: number) {
  if (!round) return "Technical Round"
  const metadataTitle = round.metadata?.title || round.metadata?.problem_title
  if (metadataTitle) return `${index + 1}. ${metadataTitle}`
  return `${index + 1}. ${formatRoundType(round.round_type)}`
}

function isCodingRound(round?: Round) {
  return Boolean(round && ["coding", "debugging", "dsa"].includes(String(round.round_type).toLowerCase()))
}

function formatPattern(value: unknown) {
  if (!value) return "Topics"
  return String(value)
    .replace(/[:/_-]/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase())
}

function formatCaseInput(stdin?: string) {
  const text = (stdin || "").trim()
  if (!text) return "(empty input)"
  const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
  if (lines.length >= 2 && lines[0].startsWith("[")) {
    return `nums = ${lines[0]}, target = ${lines[1]}`
  }
  return text
}

function expectedOutput(test: TestCase) {
  return test.expected || "(any output)"
}

function starterForLanguage(round: Round | undefined, language: string) {
  const starters = round?.metadata?.starter_code_by_language
  if (starters && typeof starters === "object" && typeof starters[language] === "string") {
    return starters[language]
  }
  return language === "python" ? round?.starter_code || "" : ""
}

function isTerminalRun(status?: string) {
  return status === "completed" || status === "failed"
}

function defaultPermissionState(): TechnicalPermissionState {
  return getTechnicalPermissionState()
}

export default function TechnicalInterviewPage() {
  const params = useParams()
  const router = useRouter()
  const interviewId = params.id as string
  const recoveryGraceSeconds = readRecoveryGraceSeconds()
  const sessionControlLock = useSessionControlLock(interviewId)
  const [rounds, setRounds] = useState<Round[]>([])
  const [jobContext, setJobContext] = useState<JobContext | null>(null)
  const [activeRoundId, setActiveRoundId] = useState("")
  const [codeByRound, setCodeByRound] = useState<Record<string, string>>({})
  const [languageByRound, setLanguageByRound] = useState<Record<string, Language>>({})
  const [customInputByRound, setCustomInputByRound] = useState<Record<string, string>>({})
  const [output, setOutput] = useState<RunResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadPhase, setLoadPhase] = useState("Preparing environment")
  const [roundLoadError, setRoundLoadError] = useState("")
  const [executorName, setExecutorName] = useState("Code runner")
  const [running, setRunning] = useState(false)
  const [recoverableRun, setRecoverableRun] = useState<RecoverableRun | null>(null)
  const [pollingError, setPollingError] = useState("")
  const [responseByRound, setResponseByRound] = useState<Record<string, string>>({})
  const [responseResultByRound, setResponseResultByRound] = useState<Record<string, TechnicalResponseResult>>({})
  const [submittingResponseByRound, setSubmittingResponseByRound] = useState<Record<string, boolean>>({})
  const [strictWarnings, setStrictWarnings] = useState(0)
  const [sessionFlagged, setSessionFlagged] = useState(false)
  const [submitLockedByRound, setSubmitLockedByRound] = useState<Record<string, boolean>>({})
  const [submitCountByRound, setSubmitCountByRound] = useState<Record<string, number>>({})
  const [workflowDraftByRound, setWorkflowDraftByRound] = useState<Record<string, CodingWorkflowDraft>>({})
  const [workflowSaving, setWorkflowSaving] = useState(false)
  const [permissionState, setPermissionState] = useState<TechnicalPermissionState>(defaultPermissionState)
  const [permissionError, setPermissionError] = useState("")
  const [requestingPermission, setRequestingPermission] = useState(false)
  const [preflightDone, setPreflightDone] = useState(() => consumePreflightFlag())
  const [reviewMode, setReviewMode] = useState(false)
  const [statusChecked, setStatusChecked] = useState(false)

  useEffect(() => {
    if (permissionState.ready && preflightDone) {
      setPreflightDone(false)
    }
  }, [permissionState.ready, preflightDone])

  const [showLeaveConfirm, setShowLeaveConfirm] = useState(false)
  const [leaveIntent, setLeaveIntent] = useState<"abandon" | "complete">("abandon")
  const [activeInfoTab, setActiveInfoTab] = useState<InfoTab>("description")
  const [selectedCaseIndex, setSelectedCaseIndex] = useState(0)
  const [revealedConstraintsByRound, setRevealedConstraintsByRound] = useState<Record<string, boolean>>({})
  const [revealedHintByRound, setRevealedHintByRound] = useState<Record<string, boolean>>({})
  const [clarificationAskedByRound, setClarificationAskedByRound] = useState<Record<string, boolean>>({})
  const [technicalTranscript, setTechnicalTranscript] = useState("")
  const [micListening, setMicListening] = useState(false)
  const [micSupported, setMicSupported] = useState(true)
  const roundStartedAtRef = useRef(Date.now())
  const endSentRef = useRef(false)
  const roundsRef = useRef<Round[]>([])
  const codeByRoundRef = useRef<Record<string, string>>({})
  const languageByRoundRef = useRef<Record<string, Language>>({})
  const reviewModeRef = useRef(false)
  const finishSessionRef = useRef<(options?: { keepalive?: boolean }) => Promise<boolean> | boolean | void>(() => undefined)
  const noClarificationLoggedRef = useRef<Set<string>>(new Set())
  const recognitionRef = useRef<any>(null)
  const technicalTranscriptRef = useRef("")
  const lastPermissionStateRef = useRef<TechnicalPermissionState>({
    fullscreenAttempted: false,
    fullscreenActive: false,
    fullscreenReady: false,
    screenShareReady: false,
    screenShareSurface: null,
    cameraReady: false,
    microphoneReady: false,
    ready: false,
  })
  const proctoringStartedRef = useRef(false)
  const cameraVideoRef = useRef<HTMLVideoElement>(null)
  const faceMissingSinceRef = useRef<number | null>(null)
  const pageLoadTimeRef = useRef(Date.now())
  const lastMobileWarningRef = useRef<number | null>(null)
  const lastMultiplePeopleWarningRef = useRef<number | null>(null)
  const lastCodeJumpWarningRef = useRef<number | null>(null)
  const responseIdempotencyRef = useRef<Record<string, { text: string; key: string }>>({})
  const workflowIdempotencyRef = useRef<Record<string, string>>({})
  const editorRevisionRef = useRef<Record<string, number>>({})
  const responseByRoundRef = useRef<Record<string, string>>({})
  const responseResultByRoundRef = useRef<Record<string, TechnicalResponseResult>>({})
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [targetDurationSeconds, setTargetDurationSeconds] = useState(3600)
  const sessionStartedAtRef = useRef(Date.now())
  const { metrics: faceMetrics, isRunning: faceCheckRunning, start: startFaceCheck, stop: stopFaceCheck } = useFaceCheck(cameraVideoRef)
  const { metrics: objMetrics, isRunning: objCheckRunning, start: startObjCheck, stop: stopObjCheck } = useObjectDetection(cameraVideoRef)
  const [cameraStream, setCameraStream] = useState<MediaStream | null>(null)

  const activeRound = useMemo(
    () => rounds.find((round) => round.round_id === activeRoundId) || rounds[0],
    [rounds, activeRoundId]
  )
  const activeRoundIndex = Math.max(0, rounds.findIndex((round) => round.round_id === activeRound?.round_id))
  const activeTests = useMemo(() => visibleTests(activeRound), [activeRound])
  const selectedCase = activeTests[selectedCaseIndex] || activeTests[0]
  const customInput = activeRound ? customInputByRound[activeRound.round_id] || "" : ""
  const currentLanguage: Language = activeRound ? languageByRound[activeRound.round_id] || activeRound.language || "python" : "python"
  const permissionsReady = permissionState.ready
  const submitsUsed = activeRound ? submitCountByRound[activeRound.round_id] || 0 : 0
  const maxSubmissions = Math.max(1, Number(activeRound?.max_submissions || 1))
  const submitsLeft = Math.max(0, maxSubmissions - submitsUsed)
  const activeRoundStatus = (activeRound?.status || "").toLowerCase()
  const activeRoundIsCoding = isCodingRound(activeRound)
  const durationPerQuestionMinutes = Math.max(1, Math.round(targetDurationSeconds / Math.max(1, rounds.length) / 60))
  const headerJobTitle = jobContext?.profile_type === "custom"
    ? jobContext.job_title || jobContext.role || "Technical Round"
    : jobContext?.company
      ? `${jobContext.profile_label || "Technical"} Technical Round`
      : jobContext?.role || `${jobContext?.profile_label || "Technical"} Technical Round`
  const activeRoundDeadlineMs = activeRound?.expires_at ? Date.parse(activeRound.expires_at) : Number.NaN
  const activeRoundExpired = Number.isFinite(activeRoundDeadlineMs) && Date.now() >= activeRoundDeadlineMs
  const roundActionLocked = reviewMode || activeRoundExpired || ["pending", "expired", "submitted", "submitting", "awaiting_explanation", "cancelled"].includes(activeRoundStatus)
  const roundLockMessage = activeRoundStatus === "expired"
    ? "Time has expired for this technical round."
    : activeRoundStatus === "submitting"
      ? "Your final submission is being graded."
      : activeRoundStatus === "submitted"
        ? "This technical round has already been submitted."
        : activeRoundStatus === "pending"
          ? "Complete the current round before starting this one."
          : activeRoundStatus === "awaiting_explanation"
            ? "Final code is locked. Complete the complexity and explanation steps."
        : reviewMode
          ? "This interview has ended and is no longer accepting changes."
          : "This technical round is closed."

  useEffect(() => {
    roundsRef.current = rounds
  }, [rounds])

  useEffect(() => {
    codeByRoundRef.current = codeByRound
  }, [codeByRound])

  useEffect(() => {
    languageByRoundRef.current = languageByRound
  }, [languageByRound])

  useEffect(() => {
    responseByRoundRef.current = responseByRound
  }, [responseByRound])

  useEffect(() => {
    responseResultByRoundRef.current = responseResultByRound
  }, [responseResultByRound])

  useEffect(() => {
    reviewModeRef.current = reviewMode
  }, [reviewMode])

  const recordAntiCheat = useCallback(async (eventType: string, payload: Record<string, unknown> = {}) => {
    try {
      const response = await fetch(`${API_CONFIG.BASE_URL}/technical/anti-cheat`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify({ interview_id: interviewId, event_type: eventType, payload }),
      })
      const data = (await response.json().catch(() => ({}))) as AntiCheatRecordResult
      if (typeof data.warning_count === "number") {
        setStrictWarnings(data.warning_count)
      }
      if (data.flagged) {
        setSessionFlagged(true)
      }
      return data
    } catch {
      return null
    }
  }, [interviewId])

  const recordTechnicalEvent = useCallback(async (eventType: string, payload: Record<string, unknown> = {}, roundId?: string) => {
    try {
      await fetch(`${API_CONFIG.BASE_URL}/technical/events`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify({ interview_id: interviewId, round_id: roundId || activeRoundId || null, event_type: eventType, payload }),
      })
    } catch {
    }
  }, [activeRoundId, interviewId])

  const warnStrictMode = useCallback((eventType: string, message: string, payload: Record<string, unknown> = {}) => {
    if (sessionFlagged) return
    void recordAntiCheat(eventType, payload).then((result) => {
      const count = result?.warning_count ?? strictWarnings + 1
      setStrictWarnings(count)
      toast.warning(integrityWarningMessage(message, count))
      if (result?.flagged) {
        setSessionFlagged(true)
        toast.error("This technical round has been flagged after repeated integrity violations.")
      }
    })
  }, [recordAntiCheat, sessionFlagged, strictWarnings])

  useAudioEnvironment(cameraStream, {
    enabled: false,
    onBackgroundAudioDetected: useCallback((details: { type: string; confidence: number }) => {
      warnStrictMode(
        "background_audio_detected",
        details.type === "background_music"
          ? "Background music detected. Please mute other audio sources."
          : "Background audio detected. Please ensure a quiet environment.",
        details
      )
    }, [warnStrictMode]),
  })

  const revealConstraints = useCallback((roundId: string) => {
    setRevealedConstraintsByRound((prev) => ({ ...prev, [roundId]: true }))
    setClarificationAskedByRound((prev) => ({ ...prev, [roundId]: true }))
    void recordTechnicalEvent("clarifying_question", { kind: "constraints" }, roundId)
  }, [recordTechnicalEvent])

  const revealHint = useCallback((roundId: string) => {
    setRevealedHintByRound((prev) => ({ ...prev, [roundId]: true }))
    void recordTechnicalEvent("hint_requested", { kind: "hint" }, roundId)
  }, [recordTechnicalEvent])

  const noteNoClarificationBeforeCoding = useCallback((roundId: string) => {
    if (clarificationAskedByRound[roundId] || noClarificationLoggedRef.current.has(roundId)) return
    noClarificationLoggedRef.current.add(roundId)
    void recordTechnicalEvent("no_clarification_before_coding", {}, roundId)
  }, [clarificationAskedByRound, recordTechnicalEvent])

  useEffect(() => {
    if (typeof window === "undefined") return
    setMicSupported(Boolean((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition))
    return () => {
      recognitionRef.current?.stop?.()
    }
  }, [])

  useEffect(() => {
    technicalTranscriptRef.current = technicalTranscript
  }, [technicalTranscript])

  const stopTechnicalMic = useCallback(() => {
    recognitionRef.current?.stop?.()
    recognitionRef.current = null
    setMicListening(false)
    void recordTechnicalEvent("technical_mic_stopped", { transcript_chars: technicalTranscriptRef.current.length }, activeRound?.round_id)
  }, [activeRound?.round_id, recordTechnicalEvent])

  const startTechnicalMic = useCallback(() => {
    if (typeof window === "undefined") return
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (!SpeechRecognition) {
      setMicSupported(false)
      toast.error("Live transcript is not supported in this browser.")
      return
    }

    recognitionRef.current?.stop?.()
    const recognition = new SpeechRecognition()
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = "en-US"
    recognition.onresult = (event: any) => {
      let finalText = ""
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index]
        if (result?.isFinal) {
          finalText += `${result[0]?.transcript || ""} `
        }
      }
      const clean = finalText.trim()
      if (!clean) return
      setTechnicalTranscript((prev) => `${prev}${prev ? "\n" : ""}${clean}`)
      void recordTechnicalEvent(
        "technical_transcript",
        {
          text: clean,
          chars: clean.length,
          words: clean.split(/\s+/).filter(Boolean).length,
          capture: "browser_speech_recognition",
        },
        activeRound?.round_id
      )
    }
    recognition.onerror = () => {
      setMicListening(false)
      void recordTechnicalEvent("technical_mic_error", {}, activeRound?.round_id)
    }
    recognition.onend = () => {
      setMicListening(false)
    }
    recognitionRef.current = recognition
    recognition.start()
    setMicListening(true)
    void recordTechnicalEvent("technical_mic_started", {}, activeRound?.round_id)
  }, [activeRound?.round_id, recordTechnicalEvent])

  const requestPermissions = useCallback(async () => {
    setPermissionError("")
    setRequestingPermission(true)
    const result = await requestTechnicalPermissions()
    setRequestingPermission(false)

    const state = result.ok ? result.state : getTechnicalPermissionState()

    if (!result.ok || !state.ready) {
      const message = result.ok ? "Camera, microphone, and screen sharing are required to continue." : result.message
      await releaseTechnicalPermissions()
      setPermissionError(message)
      toast.error(message)
      void recordAntiCheat("technical_permission_failed", { reason: result.ok ? "incomplete" : result.reason })
      return
    }

    setPermissionState(state)
    toast.success("Technical permissions are active.")
  }, [recordAntiCheat, recordTechnicalEvent, warnStrictMode])

  useEffect(() => {
    if (!statusChecked || reviewMode || permissionState.ready || endSentRef.current) return
    if (preflightDone) {
      setPermissionState(getTechnicalPermissionState())
    }
  }, [reviewMode, statusChecked, permissionState.ready, preflightDone])

  useEffect(() => {
    const unsubscribe = subscribeTechnicalPermissionState((state) => {
      const previous = lastPermissionStateRef.current
      setPermissionState(state)
      lastPermissionStateRef.current = state

      if (!previous.screenShareReady && state.screenShareReady) {
        void recordTechnicalEvent("screen_share_started", { tracks: 1, surface: state.screenShareSurface || null })
        if (state.screenShareSurface && state.screenShareSurface !== "monitor") {
          warnStrictMode("screen_not_monitor", "Strict mode warning: share your entire screen, not a tab or window.", { surface: state.screenShareSurface })
        }
      }

      if (previous.screenShareReady && !state.screenShareReady) {
        setPermissionError("Screen sharing stopped. Resume sharing to continue the test.")
        void recordTechnicalEvent("screen_share_stopped")
        void recordAntiCheat("screen_share_stopped")
      }
    })

    return unsubscribe
  }, [recordAntiCheat, recordTechnicalEvent])

  useEffect(() => {
    return () => {
      stopFaceCheck()
      stopObjCheck()
      stopTechnicalMic()
    }
  }, [stopFaceCheck, stopObjCheck, stopTechnicalMic])

  useEffect(() => {
    if (permissionsReady) {
      proctoringStartedRef.current = true
      pageLoadTimeRef.current = Date.now()
    }
  }, [permissionsReady])

  useEffect(() => {
    if (!permissionState.cameraReady) return
    const stream = getTechnicalCameraStream()
    setCameraStream(stream)
    const video = cameraVideoRef.current
    if (video && stream && video.srcObject !== stream) {
      video.srcObject = stream
      void video.play().catch(() => undefined)
    }
    if (permissionState.cameraReady && !faceCheckRunning) {
      startFaceCheck()
    }
    if (permissionState.cameraReady && !objCheckRunning) {
      startObjCheck()
    }
  }, [permissionState.cameraReady, faceCheckRunning, objCheckRunning, startFaceCheck, startObjCheck, permissionsReady])

  useEffect(() => {
    if (!permissionState.cameraReady || sessionFlagged) return
    if (faceMetrics.source === "fallback") return
    if (Date.now() - pageLoadTimeRef.current < 15000) return
    const now = Date.now()
    if (!faceMetrics.facePresent) {
      if (!faceMissingSinceRef.current) faceMissingSinceRef.current = now
      if (now - faceMissingSinceRef.current > 2500) {
        warnStrictMode("face_missing", "Camera check: your face is not visible.")
        faceMissingSinceRef.current = now + 8000
      }
    } else {
      faceMissingSinceRef.current = null
    }

  }, [faceMetrics, permissionState.cameraReady, sessionFlagged, warnStrictMode])

  useEffect(() => {
    if (!permissionState.cameraReady || sessionFlagged) return
    if (Date.now() - pageLoadTimeRef.current < 15000) return

    const now = Date.now()

    if (objMetrics.mobileDetected) {
      if (!lastMobileWarningRef.current || now - lastMobileWarningRef.current > 10000) {
        warnStrictMode("mobile_phone_detected", "Anti-cheat: Cell phone detected in your environment.")
        lastMobileWarningRef.current = now
      }
    }

    if (objMetrics.multiplePeopleDetected) {
      if (!lastMultiplePeopleWarningRef.current || now - lastMultiplePeopleWarningRef.current > 10000) {
        warnStrictMode("multiple_people_detected", "Anti-cheat: Multiple people detected in the camera frame.")
        lastMultiplePeopleWarningRef.current = now
      }
    }
  }, [objMetrics, permissionState.cameraReady, sessionFlagged, warnStrictMode])

  useEffect(() => {
    if (reviewMode || !activeRound) return
    const interval = setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - sessionStartedAtRef.current) / 1000))
    }, 1000)
    return () => clearInterval(interval)
  }, [reviewMode, activeRound])

  useEffect(() => {
    if (!rounds.length) return
    void (async () => {
      try {
        const response = await fetch(`${API_CONFIG.BASE_URL}/technical/sessions/${interviewId}/integrity`, {
          credentials: "include",
          headers: getAuthHeaders(),
        })
        if (!response.ok) return
        const data = await response.json()
        if (typeof data.warning_count === "number") setStrictWarnings(data.warning_count)
        if (data.flagged) setSessionFlagged(true)
      } catch {
      }
    })()
  }, [interviewId, rounds.length])

  const loadRounds = useCallback(async () => {
    setLoading(true)
    setRoundLoadError("")
    setLoadPhase("Preparing environment")
    try {
      // Check interview status first — if ended, enable review mode (no permissions needed)
      try {
        const statusResp = await fetch(`${API_CONFIG.BASE_URL}/interview/status/${interviewId}`, {
          credentials: "include",
          headers: getAuthHeaders(),
        })
        if (statusResp.ok) {
          const statusData = await statusResp.json()
          const interviewStatus = statusData?.status || statusData?.interview_status || ""
          if (nonReportableInterviewStatuses.has(interviewStatus.toLowerCase())) {
            router.replace("/?tab=technical")
            return
          }
          if (finalizedInterviewStatuses.has(interviewStatus.toLowerCase())) {
            setReviewMode(true)
            setStatusChecked(true)
            router.replace(`/interview/${interviewId}/report`)
            return
          }
        }
      } catch {
        // Status check failed — continue normally
      }
      setStatusChecked(true)
      setLoadPhase("Loading typed technical rounds")
      const response = await fetch(`${API_CONFIG.BASE_URL}/technical/sessions/${interviewId}/rounds`, {
        credentials: "include",
        headers: getAuthHeaders(),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data.detail || data.message || "Failed to load technical rounds")
      if (data.job_context && typeof data.job_context === "object") setJobContext(data.job_context as JobContext)
      const parentStatus = String(data.interview_status || "").toLowerCase()
      if (nonReportableInterviewStatuses.has(parentStatus)) {
        router.replace("/?tab=technical")
        return
      }
      if (data.read_only || finalizedInterviewStatuses.has(parentStatus)) {
        setReviewMode(true)
        router.replace(`/interview/${interviewId}/report`)
        return
      }
      setLoadPhase("Opening workspace")
      const loadedRounds = (data.rounds || []) as Round[]
      if (!loadedRounds.length) throw new Error("No technical questions were generated. Please retry.")
      setExecutorName(data.executor_label || data.generation?.executor_label || data.executor || data.generation?.executor || "Code runner")
      const firstRound = loadedRounds[0]
      const durationSeconds = Number(data.target_duration_seconds || firstRound?.target_duration_seconds || 3600)
      setTargetDurationSeconds(Number.isFinite(durationSeconds) && durationSeconds > 0 ? durationSeconds : 3600)
      if (firstRound?.started_at) {
        const startedAt = Date.parse(firstRound.started_at)
        if (Number.isFinite(startedAt)) {
          sessionStartedAtRef.current = startedAt
          setElapsedSeconds(Math.max(0, Math.floor((Date.now() - startedAt) / 1000)))
        }
      } else if (typeof firstRound?.remaining_seconds === "number") {
        setElapsedSeconds(Math.max(0, durationSeconds - firstRound.remaining_seconds))
      }
      setRounds(loadedRounds)
      const nextActiveRound = loadedRounds.find((round) => ["active", "awaiting_explanation"].includes(String(round.status || "").toLowerCase())) || loadedRounds[0]
      setActiveRoundId(nextActiveRound?.round_id || "")
      const code: Record<string, string> = {}
      const languages: Record<string, Language> = {}
      const inputs: Record<string, string> = {}
      const writtenResponses: Record<string, string> = {}
      const workflowDrafts: Record<string, CodingWorkflowDraft> = {}
      const submitCounts: Record<string, number> = {}
      loadedRounds.forEach((round) => {
        code[round.round_id] = isCodingRound(round) ? round.starter_code || starterForLanguage(round, round.language || "python") : ""
        languages[round.round_id] = round.language || "python"
        inputs[round.round_id] = visibleTests(round)[0]?.stdin || ""
        if (!isCodingRound(round)) writtenResponses[round.round_id] = ""
        workflowDrafts[round.round_id] = { complexity: "", explanation: "" }
        submitCounts[round.round_id] = Number(round.workflow_state?.final_submission?.submit_number || 0)
      })
      setCodeByRound(code)
      setLanguageByRound(languages)
      setCustomInputByRound(inputs)
      setResponseByRound(writtenResponses)
      setWorkflowDraftByRound(workflowDrafts)
      setSubmitCountByRound(submitCounts)
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to load technical mode."
      setRoundLoadError(message)
      toast.error(message)
    } finally {
      setLoading(false)
    }
  }, [interviewId, router])

  useEffect(() => {
    if (sessionControlLock !== "owned") return
    void loadRounds()
  }, [loadRounds, sessionControlLock])

  useEffect(() => {
    setSelectedCaseIndex(0)
    setOutput(null)
    setActiveInfoTab("description")
  }, [activeRoundId])

  useEffect(() => {
    // Strict mode constraints disabled
  }, [])

  const pollRunStatus = async (runId: string, initialPollAfterMs = 250) => {
    let latest: RunResult | null = null
    const deadline = Date.now() + 45_000
    let attempt = 0
    let pollAfterMs = Math.max(100, Math.min(initialPollAfterMs, 2_000))
    while (Date.now() < deadline && attempt < 60) {
      await new Promise((resolve) => setTimeout(resolve, pollAfterMs))
      attempt += 1
      const controller = new AbortController()
      const timeout = window.setTimeout(() => controller.abort(), 10_000)
      try {
        const response = await fetch(`${API_CONFIG.BASE_URL}/technical/runs/${runId}`, {
          credentials: "include",
          headers: getAuthHeaders(),
          signal: controller.signal,
        })
        const data = await response.json().catch(() => ({}))
        if (!response.ok) {
          if (response.status === 429 || response.status >= 500) continue
          throw new Error(data.detail || "Failed to poll run status")
        }
        latest = data
        setOutput(data)
        pollAfterMs = Math.max(100, Math.min(Number(data.poll_after_ms) || 250, 2_000))
        if (isTerminalRun(data.status)) return data as RunResult
      } catch (error) {
        if (error instanceof Error && error.name === "AbortError") continue
        throw error
      } finally {
        window.clearTimeout(timeout)
      }
    }
    if (latest) setOutput(latest)
    throw new RunPollingTimeout()
  }

  const applyFinalRunResult = (context: RecoverableRun, finalResult: RunResult) => {
    setRecoverableRun(null)
    setPollingError("")
    if (context.action !== "submit") return
    if (finalResult.status !== "completed") {
      setRounds((current) => current.map((round) => round.round_id === context.roundId ? { ...round, status: "active", locked_reason: null } : round))
      return
    }
    const remaining = typeof finalResult.submits_left === "number" ? Math.max(0, finalResult.submits_left) : 0
    const round = roundsRef.current.find((item) => item.round_id === context.roundId)
    const allowed = Math.max(1, Number(round?.max_submissions || 1))
    const practiceCanRetry = round?.mode === "practice" && remaining > 0
    setSubmitCountByRound((current) => ({ ...current, [context.roundId]: Math.max(1, allowed - remaining) }))
    setSubmitLockedByRound((current) => ({ ...current, [context.roundId]: !practiceCanRetry }))
    setRounds((current) => current.map((round) => (
      round.round_id === context.roundId
        ? {
            ...round,
            status: practiceCanRetry ? "active" : "awaiting_explanation",
            locked_reason: practiceCanRetry ? null : "awaiting_explanation",
            workflow_state: {
              ...(round.workflow_state || {}),
              final_submission: round.workflow_state?.final_submission?.committed
                ? round.workflow_state.final_submission
                : {
                    committed: true,
                    execution_job_id: context.runId,
                    submit_number: Math.max(1, allowed - remaining),
                  },
              latest_submission: {
                committed: true,
                execution_job_id: context.runId,
                submit_number: Math.max(1, allowed - remaining),
              },
            },
          }
        : round
    )))
  }

  const resumeRunPolling = async () => {
    if (!recoverableRun || running) return
    setRunning(true)
    setPollingError("")
    try {
      const result = await pollRunStatus(recoverableRun.runId)
      applyFinalRunResult(recoverableRun, result)
    } catch (error) {
      const message = error instanceof Error ? error.message : "Could not recover code-run status."
      setPollingError(message)
      if (!(error instanceof RunPollingTimeout)) setRecoverableRun(null)
    } finally {
      setRunning(false)
    }
  }

  const codeLooksHardcoded = (code: string) => {
    const expectedValues = activeTests
      .map((test) => expectedOutput(test).trim())
      .filter((value) => value.length >= 2)
    return expectedValues.some((value) => code.includes(value))
  }

  const submitWorkflowEvidence = async (
    stage: "clarification" | "complexity" | "explanation" | "followup",
    content: string,
    round: Round = activeRound as Round,
  ) => {
    if (!round || !content.trim()) return false
    const keySlot = `${round.round_id}:${stage}:${content.trim()}`
    const idempotencyKey = workflowIdempotencyRef.current[keySlot]
      || (typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `workflow-${Date.now()}-${Math.random().toString(16).slice(2)}`)
    workflowIdempotencyRef.current[keySlot] = idempotencyKey
    setWorkflowSaving(true)
    try {
      const response = await fetch(`${API_CONFIG.BASE_URL}/technical/rounds/${round.round_id}/workflow`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey, ...getAuthHeaders() },
        body: JSON.stringify({ stage, content: content.trim(), idempotency_key: idempotencyKey }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data.detail || `Could not save ${stage} evidence.`)
      setRounds((current) => current.map((item) => item.round_id === round.round_id
        ? { ...item, status: data.round_status || item.status, workflow_state: data.workflow_state || item.workflow_state }
        : item))
      if (data.next_round_id) await loadRounds()
      return true
    } catch (error) {
      toast.error(error instanceof Error ? error.message : `Could not save ${stage} evidence.`)
      return false
    } finally {
      setWorkflowSaving(false)
    }
  }

  const executeRound = async (action: "test" | "custom-run" | "submit") => {
    if (!activeRound) return
    if (!isCodingRound(activeRound)) {
      toast.error("Use the written-response form for this round type.")
      return
    }
    if (reviewMode) {
      toast.error("This interview has ended and is no longer accepting changes.")
      return
    }
    const currentStatus = (activeRound.status || "").toLowerCase()
    if (["expired", "submitted", "submitting", "cancelled"].includes(currentStatus)) {
      toast.error(roundLockMessage)
      return
    }
    if (sessionFlagged) {
      toast.error("This technical round is locked after repeated integrity warnings.")
      return
    }
    if (action === "submit" && (submitLockedByRound[activeRound.round_id] || submitsLeft <= 0)) {
      toast.error("No final submits remain for this round.")
      return
    }
    const source = codeByRound[activeRound.round_id] || ""
    if (action === "test" || action === "submit") {
      noteNoClarificationBeforeCoding(activeRound.round_id)
    }
    if ((action === "test" || action === "submit") && codeLooksHardcoded(source)) {
      void recordTechnicalEvent("visible_output_hardcode", { round_id: activeRound.round_id }, activeRound.round_id)
      void recordAntiCheat("visible_output_hardcode", { round_id: activeRound.round_id })
    }
    setRunning(true)
    setOutput(null)
    setPollingError("")
    setRecoverableRun(null)
    let activeRun: RecoverableRun | null = null
    try {
      const idempotencyKey = typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `run-${Date.now()}-${Math.random().toString(16).slice(2)}`
      const editorRevision = editorRevisionRef.current[activeRound.round_id] || 0
      const editorHash = await sourceSha256(source)
      const response = await fetch(`${API_CONFIG.BASE_URL}/technical/rounds/${activeRound.round_id}/${action}`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey, ...getAuthHeaders() },
        body: JSON.stringify({
          language: currentLanguage,
          code: source,
          stdin: selectedCase?.stdin || "",
          custom_input: customInput,
          idempotency_key: idempotencyKey,
          editor_revision: editorRevision,
          editor_hash: editorHash,
        }),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || "Code execution failed")
      setOutput(data)
      if (data.run_id) {
        activeRun = { runId: data.run_id, roundId: activeRound.round_id, action }
      }
      const finalResult = data.run_id ? await pollRunStatus(data.run_id, data.poll_after_ms) : data
      if (
        action === "submit" &&
        finalResult?.status === "completed" &&
        finalResult.pass_count === finalResult.total_count &&
        Date.now() - roundStartedAtRef.current < 120000
      ) {
        void recordTechnicalEvent("suspicious_fast_submit", { elapsed_ms: Date.now() - roundStartedAtRef.current }, activeRound.round_id)
        void recordAntiCheat("suspicious_fast_submit", { elapsed_ms: Date.now() - roundStartedAtRef.current })
      }
      if (activeRun) applyFinalRunResult(activeRun, finalResult)
    } catch (error) {
      const message = error instanceof Error ? error.message : "Code execution failed"
      if (error instanceof RunPollingTimeout && activeRun) {
        setRecoverableRun(activeRun)
        setPollingError(message)
        toast.info("The submission was not sent again. Resume status checks when ready.")
      } else {
        toast.error(message)
      }
    } finally {
      setRunning(false)
    }
  }

  const handleRun = () => {
    if (!activeRound) return
    const activeTestStdin = activeTests[selectedCaseIndex]?.stdin || ""
    if (customInput && customInput.trim() !== activeTestStdin.trim()) {
      void executeRound("custom-run")
    } else {
      void executeRound("test")
    }
  }

  const updateCustomInput = (value: string) => {
    if (!activeRound) return
    setCustomInputByRound((prev) => ({ ...prev, [activeRound.round_id]: value }))
  }

  const updateCode = (value: string) => {
    if (!activeRound) return
    const previous = codeByRound[activeRound.round_id] || ""
    if (previous.trim().length < 20 && value.trim().length > 20) {
      noteNoClarificationBeforeCoding(activeRound.round_id)
    }
    if (Math.abs(value.length - previous.length) > 300) {
      void recordTechnicalEvent("large_code_jump", { from_chars: previous.length, to_chars: value.length }, activeRound.round_id)
      const now = Date.now()
      if (!lastCodeJumpWarningRef.current || now - lastCodeJumpWarningRef.current > 15000) {
        lastCodeJumpWarningRef.current = now
        void recordAntiCheat("large_code_jump", { from_chars: previous.length, to_chars: value.length })
      }
    }
    editorRevisionRef.current[activeRound.round_id] = (editorRevisionRef.current[activeRound.round_id] || 0) + 1
    setCodeByRound((prev) => ({ ...prev, [activeRound.round_id]: value }))
  }

  const updateWorkflowDraft = (field: keyof CodingWorkflowDraft, value: string) => {
    if (!activeRound) return
    setWorkflowDraftByRound((current) => ({
      ...current,
      [activeRound.round_id]: {
        ...(current[activeRound.round_id] || { complexity: "", explanation: "" }),
        [field]: value,
      },
    }))
  }

  const commitActiveFinalEvidence = async () => {
    if (!activeRound) return
    const draft = workflowDraftByRound[activeRound.round_id] || { complexity: "", explanation: "" }
    if (!draft.complexity.trim() || !draft.explanation.trim()) {
      toast.error("Add both the complexity analysis and final explanation.")
      return
    }
    if (!activeRound.workflow_state?.complexity) {
      if (!await submitWorkflowEvidence("complexity", draft.complexity, activeRound)) return
    }
    await submitWorkflowEvidence("explanation", draft.explanation, activeRound)
  }

  const updateWrittenResponse = (roundId: string, value: string) => {
    setResponseByRound((current) => ({ ...current, [roundId]: value }))
  }

  const submitWrittenResponse = async () => {
    if (!activeRound || activeRoundIsCoding || reviewMode || sessionFlagged) return
    const roundId = activeRound.round_id
    const previousResult = responseResultByRound[roundId]
    const previousDecision = previousResult?.decision && typeof previousResult.decision === "object"
      ? previousResult.decision
      : null
    const phase: "primary" | "followup" = previousDecision?.action === "targeted_followup" ? "followup" : "primary"
    const responseText = (responseByRound[roundId] || "").trim()
    if (!responseText) {
      toast.error("Write your response before submitting this round.")
      return
    }
    if (roundActionLocked) {
      toast.error(roundLockMessage)
      return
    }
    const responseKeySlot = `${roundId}:${phase}`
    const previous = responseIdempotencyRef.current[responseKeySlot]
    const idempotencyKey = previous?.text === responseText
      ? previous.key
      : typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `response-${Date.now()}-${Math.random().toString(16).slice(2)}`
    responseIdempotencyRef.current[responseKeySlot] = { text: responseText, key: idempotencyKey }
    setSubmittingResponseByRound((current) => ({ ...current, [roundId]: true }))
    try {
      const response = await fetch(`${API_CONFIG.BASE_URL}/technical/rounds/${roundId}/response`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey, ...getAuthHeaders() },
        body: JSON.stringify({
          response_text: responseText,
          response_payload: {
            round_type: activeRound.round_type,
            renderer: activeRound.round_type,
            word_count: responseText.split(/\s+/).filter(Boolean).length,
            workflow: activeRound.round_spec?.workflow || activeRound.metadata?.workflow || [],
          },
          idempotency_key: idempotencyKey,
          phase,
          parent_response_id: phase === "followup" ? previousResult?.response_id : null,
        }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data.detail || data.message || "Failed to submit technical response")
      if (data.status !== "committed") {
        toast.info("Your response is saved and assessment is still pending. Use Submit again to resume safely.")
        return
      }
      setResponseResultByRound((current) => ({ ...current, [roundId]: data as TechnicalResponseResult }))
      const decision = data.decision && typeof data.decision === "object" ? data.decision : null
      const needsFollowup = decision?.action === "targeted_followup"
      setRounds((current) => current.map((round) => round.round_id === roundId
        ? { ...round, status: needsFollowup ? "active" : "submitted", locked_reason: needsFollowup ? null : "submitted" }
        : round))
      setResponseByRound((current) => ({ ...current, [roundId]: "" }))
      if (!needsFollowup && data.next_round_id) await loadRounds()
      toast.success(needsFollowup ? "Primary response saved. Complete the targeted follow-up." : (data.duplicate ? "Saved response restored." : "Technical response saved."))
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to submit technical response")
    } finally {
      setSubmittingResponseByRound((current) => ({ ...current, [roundId]: false }))
    }
  }

  const selectRound = (roundId: string) => {
    setActiveRoundId(roundId)
    roundStartedAtRef.current = Date.now()
  }

  const selectCase = (index: number) => {
    setSelectedCaseIndex(index)
    if (activeRound) {
      setCustomInputByRound((prev) => ({
        ...prev,
        [activeRound.round_id]: activeTests[index]?.stdin || "",
      }))
    }
  }

  const requestLeave = useCallback(() => {
    setLeaveIntent("abandon")
    setShowLeaveConfirm(true)
  }, [])

  const requestFinish = useCallback(() => {
    setLeaveIntent("complete")
    setShowLeaveConfirm(true)
  }, [])

  const saveCurrentDrafts = useCallback(async (options: { keepalive?: boolean } = {}) => {
    await Promise.all(
      roundsRef.current.map(async (round) => {
        const code = codeByRoundRef.current[round.round_id] || ""
        const language = languageByRoundRef.current[round.round_id] || round.language || "python"
        if (!code.trim()) return null
        return fetch(`${API_CONFIG.BASE_URL}/technical/rounds/${round.round_id}/save-draft`, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json", ...getAuthHeaders() },
          keepalive: options.keepalive,
          body: JSON.stringify({ code, language }),
        }).catch(() => null)
      })
    )
  }, [interviewId])

  useEffect(() => {
    if (
      reviewMode
      || endSentRef.current
      || !proctoringStartedRef.current
      || permissionState.screenShareReady
    ) return
    toast.warning(`Screen sharing stopped. Restore it within ${recoveryGraceSeconds} seconds or this attempt will end incomplete.`)
    const timeout = window.setTimeout(() => {
      if (getTechnicalPermissionState().screenShareReady || endSentRef.current) return
      endSentRef.current = true
      void saveCurrentDrafts({ keepalive: true }).finally(() => {
        void cancelInterviewSession(interviewId).finally(() => {
          stopFaceCheck()
          stopObjCheck()
          stopTechnicalMic()
          void releaseTechnicalPermissions()
          toast.error("The restoration window expired. This attempt was marked incomplete.")
          router.replace("/?tab=technical")
        })
      })
    }, recoveryGraceSeconds * 1000)
    return () => window.clearTimeout(timeout)
  }, [interviewId, permissionState.screenShareReady, recoveryGraceSeconds, reviewMode, router, saveCurrentDrafts, stopFaceCheck, stopObjCheck, stopTechnicalMic])

  const commitCurrentWrittenResponses = useCallback(async (options: { keepalive?: boolean } = {}) => {
    await Promise.all(roundsRef.current.map(async (round) => {
      if (isCodingRound(round)) return null
      const priorResult = responseResultByRoundRef.current[round.round_id]
      const priorDecision = priorResult?.decision && typeof priorResult.decision === "object" ? priorResult.decision : null
      if (priorResult && priorDecision?.action !== "targeted_followup") return null
      if (["submitted", "completed", "expired", "cancelled"].includes(String(round.status || "").toLowerCase())) return null
      const responseText = (responseByRoundRef.current[round.round_id] || "").trim()
      if (!responseText) {
        if (priorDecision?.action === "targeted_followup" && !options.keepalive) {
          throw new Error("Complete the targeted technical follow-up before finishing.")
        }
        return null
      }
      const phase: "primary" | "followup" = priorDecision?.action === "targeted_followup" ? "followup" : "primary"
      const responseKeySlot = `${round.round_id}:${phase}`
      const previous = responseIdempotencyRef.current[responseKeySlot]
      const idempotencyKey = previous?.text === responseText
        ? previous.key
        : typeof crypto !== "undefined" && "randomUUID" in crypto
          ? crypto.randomUUID()
          : `response-${Date.now()}-${Math.random().toString(16).slice(2)}`
      responseIdempotencyRef.current[responseKeySlot] = { text: responseText, key: idempotencyKey }
      const response = await fetch(`${API_CONFIG.BASE_URL}/technical/rounds/${round.round_id}/response`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey, ...getAuthHeaders() },
        keepalive: options.keepalive,
        body: JSON.stringify({
          response_text: responseText,
          response_payload: { round_type: round.round_type, renderer: round.round_type, finish_commit: true },
          idempotency_key: idempotencyKey,
          phase,
          parent_response_id: phase === "followup" ? priorResult?.response_id : null,
        }),
      })
      const body = await response.json().catch(() => ({}))
      if ((!response.ok || body.status !== "committed") && !options.keepalive) {
        throw new Error(body.detail || "A written response is saved but its assessment is still pending. Try finishing again.")
      }
      return response
    }))
  }, [])

  const commitPendingCodingEvidence = async (options: { keepalive?: boolean } = {}) => {
    for (const round of roundsRef.current) {
      if (!isCodingRound(round) || String(round.status || "").toLowerCase() !== "awaiting_explanation") continue
      const draft = workflowDraftByRound[round.round_id] || { complexity: "", explanation: "" }
      if (!draft.complexity.trim() || !draft.explanation.trim()) {
        if (!options.keepalive) {
          throw new Error("Complete the complexity and final explanation for every submitted coding round before finishing.")
        }
        continue
      }
      if (!round.workflow_state?.complexity) {
        if (!await submitWorkflowEvidence("complexity", draft.complexity, round)) throw new Error("Could not save complexity evidence.")
      }
      const latestRound = roundsRef.current.find((item) => item.round_id === round.round_id) || round
      if (!latestRound.workflow_state?.explanation) {
        if (!await submitWorkflowEvidence("explanation", draft.explanation, latestRound)) throw new Error("Could not save final explanation.")
      }
    }
  }

  const finishTechnicalSession = useCallback(async (options: { keepalive?: boolean } = {}) => {
    if (reviewModeRef.current || endSentRef.current) return true
    endSentRef.current = true
    await saveCurrentDrafts(options)
    try {
      await commitPendingCodingEvidence(options)
      await commitCurrentWrittenResponses(options)
      let ended = await endInterviewSession(interviewId, { keepalive: options.keepalive })
      if (ended?.pending_execution && !options.keepalive) {
        toast.info("Your final code is still being graded. Analysis will start automatically when it finishes.")
        const drainDeadline = Date.now() + 30_000
        while (ended?.pending_execution && Date.now() < drainDeadline) {
          await new Promise((resolve) => setTimeout(resolve, 1_000))
          ended = await endInterviewSession(interviewId)
        }
      }
    } catch (error) {
      if (!options.keepalive) {
        endSentRef.current = false
        toast.error(error instanceof Error ? error.message : "Could not finish the test. Check your connection and try again.")
        return false
      }
    }
    stopFaceCheck()
    stopObjCheck()
    stopTechnicalMic()
    await releaseTechnicalPermissions()
    return true
  }, [commitCurrentWrittenResponses, interviewId, saveCurrentDrafts, stopFaceCheck, stopObjCheck, stopTechnicalMic])

  useEffect(() => {
    finishSessionRef.current = finishTechnicalSession
  }, [finishTechnicalSession])

  const confirmLeave = useCallback(async () => {
    setShowLeaveConfirm(false)
    if (leaveIntent === "complete") {
      const finished = await finishTechnicalSession()
      if (finished) router.replace(`/interview/${interviewId}/report`)
      return
    }
    if (endSentRef.current) return
    endSentRef.current = true
    try {
      await saveCurrentDrafts()
      await commitCurrentWrittenResponses()
      await cancelInterviewSession(interviewId)
      stopFaceCheck()
      stopObjCheck()
      stopTechnicalMic()
      await releaseTechnicalPermissions()
      router.replace("/?tab=technical")
    } catch (error) {
      endSentRef.current = false
      toast.error(error instanceof Error ? error.message : "Could not end this attempt. Check your connection and try again.")
    }
  }, [commitCurrentWrittenResponses, finishTechnicalSession, interviewId, leaveIntent, router, saveCurrentDrafts, stopFaceCheck, stopObjCheck, stopTechnicalMic])

  useEffect(() => {
    if (!rounds.length || reviewMode) return
    const preserveOnLeave = () => {
      void saveCurrentDrafts({ keepalive: true })
      if (!endSentRef.current) {
        endSentRef.current = true
        void abandonInterviewSession(interviewId, { keepalive: true }).catch(() => undefined)
      }
      stopFaceCheck()
      stopObjCheck()
      stopTechnicalMic()
      void releaseTechnicalPermissions()
    }
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ""
    }
    const onPageHide = () => preserveOnLeave()
    window.addEventListener("beforeunload", onBeforeUnload)
    window.addEventListener("pagehide", onPageHide)
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload)
      window.removeEventListener("pagehide", onPageHide)
    }
  }, [interviewId, reviewMode, rounds.length, saveCurrentDrafts, stopFaceCheck, stopObjCheck, stopTechnicalMic])

  useEffect(() => {
    if (reviewMode) return
    window.history.pushState({ technicalInterviewGuard: true }, "", window.location.href)
    const onPopState = () => {
      setShowLeaveConfirm(true)
      window.history.pushState({ technicalInterviewGuard: true }, "", window.location.href)
    }
    window.addEventListener("popstate", onPopState)
    return () => window.removeEventListener("popstate", onPopState)
  }, [reviewMode])

  if (sessionControlLock === "blocked") {
    return (
      <TechnicalLoadingScreen
        phase="This attempt is already active in another tab."
        error="Close the other tab before taking control of this continuous attempt."
        onRetry={() => window.location.reload()}
        onBack={() => router.replace("/?tab=technical")}
      />
    )
  }

  if (sessionControlLock !== "owned") {
    return <TechnicalLoadingScreen phase="Securing this attempt…" error="" onRetry={() => window.location.reload()} onBack={() => router.replace("/?tab=technical")} />
  }

  if (!statusChecked && !preflightDone && !endSentRef.current) {
    return (
      <TechnicalLoadingScreen
        phase="Checking session status..."
        error=""
        onRetry={loadRounds}
        onBack={requestLeave}
      />
    )
  }

  if (!permissionsReady && !preflightDone && !reviewMode && !endSentRef.current) {
    return (
      <>
        <PermissionGate
          permissionState={permissionState}
          permissionError={permissionError}
          requestingPermission={requestingPermission}
          strictWarnings={strictWarnings}
          cameraVideoRef={cameraVideoRef}
          onBack={requestLeave}
          onRequestPermissions={requestPermissions}
        />
        <TechnicalLeaveConfirmDialog
          open={showLeaveConfirm}
          intent={leaveIntent}
          onCancel={() => setShowLeaveConfirm(false)}
          onConfirm={confirmLeave}
        />
      </>
    )
  }

  /* Fullscreen re-entry overlay: bypassed */

  if (loading) {
    return (
      <>
        <TechnicalLoadingScreen
          phase={loadPhase}
          error={roundLoadError}
          onRetry={loadRounds}
          onBack={requestLeave}
        />
        <TechnicalLeaveConfirmDialog
          open={showLeaveConfirm}
          intent={leaveIntent}
          onCancel={() => setShowLeaveConfirm(false)}
          onConfirm={confirmLeave}
        />
      </>
    )
  }

  if (roundLoadError) {
    return (
      <>
        <TechnicalLoadingScreen
          phase={loadPhase}
          error={roundLoadError}
          onRetry={loadRounds}
          onBack={requestLeave}
        />
        <TechnicalLeaveConfirmDialog
          open={showLeaveConfirm}
          intent={leaveIntent}
          onCancel={() => setShowLeaveConfirm(false)}
          onConfirm={confirmLeave}
        />
      </>
    )
  }

  return (
    <div className="flex h-dvh min-h-0 flex-col overflow-hidden bg-background text-foreground">
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-border bg-secondary px-3">
        <div className="flex min-w-0 items-center gap-2">
          <Button variant="ghost" size="icon-sm" className="text-foreground hover:bg-secondary hover:text-foreground" onClick={requestLeave}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div className="hidden min-w-0 sm:block">
            <p className="truncate text-sm font-semibold text-foreground">{headerJobTitle}</p>
            <p className="truncate text-xs text-muted-foreground">{jobContext?.profile_label || "Technical"}</p>
          </div>
          <select
            className="h-8 rounded-md border border-border bg-secondary px-2 text-sm text-foreground outline-none"
            value={activeRound?.round_id || ""}
            onChange={(event) => selectRound(event.target.value)}
          >
            {rounds.map((round, index) => (
              <option key={round.round_id} value={round.round_id} disabled={String(round.status || "").toLowerCase() === "pending"}>
                {problemTitle(round, index)}
              </option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-3">
          {rounds.length > 0 && (
            <span className="hidden text-xs text-muted-foreground xl:inline">
              {rounds.length} questions · {durationPerQuestionMinutes} min each
            </span>
          )}
          {!reviewMode && (() => {
            const parsedRoundDeadline = activeRound?.expires_at ? Date.parse(activeRound.expires_at) : Number.NaN
            const remainingSeconds = Number.isFinite(parsedRoundDeadline)
              ? Math.max(0, Math.floor((parsedRoundDeadline - Date.now()) / 1000))
              : typeof activeRound?.remaining_seconds === "number"
                ? Math.max(0, activeRound.remaining_seconds)
                : Math.max(0, targetDurationSeconds - elapsedSeconds)
            const isCountdown = true
            const displayMinutes = Math.floor(remainingSeconds / 60)
            const displaySecs = remainingSeconds % 60
            const isLow = isCountdown && remainingSeconds <= 300 && remainingSeconds > 60
            const isCritical = isCountdown && remainingSeconds <= 60
            const isExpired = isCountdown && remainingSeconds === 0

            let timerClasses = "hidden sm:flex items-center gap-1.5 rounded px-2.5 py-1 text-sm font-medium border "
            if (isCritical || isExpired) {
              timerClasses += "bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/30 animate-pulse"
            } else if (isLow) {
              timerClasses += "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/30"
            } else {
              timerClasses += "bg-background text-muted-foreground border-border"
            }

            return (
              <div className={timerClasses}>
                <Timer className="h-3.5 w-3.5" />
                {isExpired ? (
                  <span>Time&apos;s up</span>
                ) : (
                  <span>{displayMinutes}:{displaySecs.toString().padStart(2, "0")}</span>
                )}
              </div>
            )
          })()}
          {reviewMode && (
            <span className="hidden items-center gap-1 rounded-md bg-sky-500/15 px-2 py-1 text-xs text-sky-700 dark:text-sky-300 sm:flex">
              <CheckCircle2 className="h-3 w-3" />
              Review Mode
            </span>
          )}
          {!reviewMode && strictWarnings > 0 && (
            <span className="hidden items-center gap-1 rounded-md bg-amber-500/15 px-2 py-1 text-xs text-amber-700 dark:text-amber-300 sm:flex">
              <ShieldAlert className="h-3 w-3" />
              Session protected
            </span>
          )}
          {!reviewMode && permissionsReady && (
          <span className="hidden items-center gap-1 rounded-md bg-emerald-500/15 px-2 py-1 text-xs text-emerald-700 dark:text-emerald-300 sm:flex">
            <ShieldCheck className="h-3 w-3" />
            Sharing active
          </span>
          )}
          {!reviewMode && (
            <Button
              size="sm"
              className="gap-2 bg-rose-600 hover:bg-rose-700 text-white font-medium"
              onClick={requestFinish}
            >
              Finish round
            </Button>
          )}
        </div>
      </header>

      {sessionFlagged && (
        <div className="flex items-center gap-2 border-b border-rose-500/40 bg-rose-500/15 px-4 py-2 text-xs font-semibold text-rose-800 dark:text-rose-200">
          <ShieldAlert className="h-4 w-4" />
          This attempt is locked after repeated session-integrity warnings.
        </div>
      )}

      {strictWarnings > 0 && !sessionFlagged && (
        <div className="flex items-center gap-2 border-b border-amber-500/30 bg-amber-500/10 px-4 py-2 text-xs font-medium text-amber-700 dark:text-amber-300 sm:hidden">
          <ShieldAlert className="h-4 w-4" />
          Integrity warnings: {strictWarnings}
        </div>
      )}

      <video ref={cameraVideoRef} autoPlay playsInline muted className="hidden" />

      {activeRoundIsCoding ? (
      <main className="grid min-h-0 flex-1 gap-2 overflow-hidden bg-background p-2 lg:grid-cols-[minmax(360px,0.95fr)_minmax(520px,1fr)]">
        <section className="grid min-h-[620px] gap-2 overflow-hidden lg:min-h-0 lg:grid-rows-[minmax(0,1fr)_224px]">
          <ProblemPanel
            round={activeRound}
            roundIndex={activeRoundIndex}
            activeTab={activeInfoTab}
            onTabChange={setActiveInfoTab}
            tests={activeTests}
            constraintsRevealed={activeRound ? !!revealedConstraintsByRound[activeRound.round_id] : false}
            hintRevealed={activeRound ? !!revealedHintByRound[activeRound.round_id] : false}
            technicalTranscript={technicalTranscript}
            micListening={micListening}
            micSupported={micSupported}
            onRevealConstraints={() => activeRound && revealConstraints(activeRound.round_id)}
            onRevealHint={() => activeRound && revealHint(activeRound.round_id)}
            onToggleMic={micListening ? stopTechnicalMic : startTechnicalMic}
            workflowDraft={activeRound ? workflowDraftByRound[activeRound.round_id] || { complexity: "", explanation: "" } : { complexity: "", explanation: "" }}
            workflowState={activeRound?.workflow_state || {}}
            workflowSaving={workflowSaving}
            actionLocked={roundActionLocked || sessionFlagged}
            onWorkflowChange={updateWorkflowDraft}
            onCommitFinalEvidence={() => void commitActiveFinalEvidence()}
          />
          <TestcasePanel
            tests={activeTests}
            selectedCaseIndex={selectedCaseIndex}
            customInput={customInput}
            onSelectCase={selectCase}
            onCustomInputChange={updateCustomInput}
          />
        </section>

        <section className="grid min-h-[720px] gap-2 overflow-hidden lg:min-h-0 lg:grid-rows-[minmax(350px,1.45fr)_minmax(240px,0.85fr)]">
          <CodePanel
            round={activeRound}
            language={currentLanguage}
            code={activeRound ? codeByRound[activeRound.round_id] || "" : ""}
            executorName={executorName}
            onLanguageChange={(language) => {
              if (!activeRound) return
              setLanguageByRound((prev) => ({ ...prev, [activeRound.round_id]: language }))
              setCodeByRound((prev) => ({
                ...prev,
                [activeRound.round_id]: prev[activeRound.round_id]?.trim() ? prev[activeRound.round_id] : starterForLanguage(activeRound, language),
              }))
            }}
            onCodeChange={reviewMode ? () => undefined : updateCode}
            onRecordTechnicalEvent={recordTechnicalEvent}
          />
          <ResultPanel
            output={output}
            running={running}
            executorName={executorName}
            actionLocked={roundActionLocked || sessionFlagged}
            lockMessage={sessionFlagged ? "This technical round is locked after repeated integrity warnings." : roundLockMessage}
            submitLocked={roundActionLocked || sessionFlagged || (activeRound ? !!submitLockedByRound[activeRound.round_id] : false) || submitsLeft <= 0}
            submitsLeft={submitsLeft}
            maxSubmissions={maxSubmissions}
            pollingError={activeRound && recoverableRun?.roundId === activeRound.round_id ? pollingError : ""}
            canResumePolling={Boolean(activeRound && recoverableRun?.roundId === activeRound.round_id)}
            onRun={handleRun}
            onSubmit={() => executeRound("submit")}
            onResumePolling={() => void resumeRunPolling()}
          />
        </section>
      </main>
      ) : (
        <TypedTechnicalResponsePanel
          round={activeRound}
          roundIndex={activeRoundIndex}
          value={activeRound ? responseByRound[activeRound.round_id] || "" : ""}
          result={activeRound ? responseResultByRound[activeRound.round_id] : undefined}
          submitting={Boolean(activeRound && submittingResponseByRound[activeRound.round_id])}
          locked={roundActionLocked || sessionFlagged}
          lockMessage={sessionFlagged ? "This technical round is locked after repeated integrity warnings." : roundLockMessage}
          onChange={(value) => activeRound && updateWrittenResponse(activeRound.round_id, value)}
          onSubmit={() => void submitWrittenResponse()}
        />
      )}
      <TechnicalLeaveConfirmDialog
        open={showLeaveConfirm}
        intent={leaveIntent}
        onCancel={() => setShowLeaveConfirm(false)}
        onConfirm={confirmLeave}
      />
    </div>
  )
}

function PermissionGate({
  permissionState,
  permissionError,
  requestingPermission,
  strictWarnings,
  cameraVideoRef,
  onBack,
  onRequestPermissions,
}: {
  permissionState: TechnicalPermissionState
  permissionError: string
  requestingPermission: boolean
  strictWarnings: number
  cameraVideoRef: React.RefObject<HTMLVideoElement | null>
  onBack: () => void
  onRequestPermissions: () => void
}) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4 text-foreground">
      <div className="w-full max-w-lg overflow-hidden rounded-lg border border-border bg-card shadow-2xl">
        <div className="border-b border-border bg-secondary px-6 py-5">
          <div className="flex items-start gap-3">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-secondary text-emerald-300 ring-1 ring-border">
              <Lock className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-lg font-semibold">Restore permissions</h1>
              <p className="mt-1 text-sm text-muted-foreground">Restore any permission that was interrupted.</p>
            </div>
          </div>
        </div>

        <div className="space-y-4 px-6 py-5">
          <div className="grid gap-2">
            <PermissionRow label="Screen share" active={permissionState.screenShareReady} />
            <PermissionRow label="Camera" active={permissionState.cameraReady} />
            <PermissionRow label="Microphone input" active={permissionState.microphoneReady} />
          </div>
          {permissionState.cameraReady && (
            <div className="overflow-hidden rounded-lg border border-border bg-black">
              <video ref={cameraVideoRef} autoPlay playsInline muted className="aspect-video w-full object-cover" />
            </div>
          )}
          {permissionError && (
            <div className="rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-800 dark:text-rose-200">
              {permissionError}
            </div>
          )}
          {strictWarnings > 0 && (
            <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-750 dark:text-amber-200">
              Strict mode has logged {strictWarnings} warning{strictWarnings === 1 ? "" : "s"} for this session.
            </div>
          )}
        </div>

        <div className="flex flex-col gap-2 border-t border-border px-6 py-4 sm:flex-row sm:justify-end">
          <Button variant="outline" className="border-border bg-secondary text-foreground hover:bg-secondary" onClick={onBack}>
            Back
          </Button>
          <Button className="gap-2 bg-primary text-primary-foreground hover:bg-primary/90" onClick={onRequestPermissions} disabled={requestingPermission}>
            {requestingPermission ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
            {requestingPermission ? "Requesting…" : "Restore"}
          </Button>
        </div>
      </div>
    </div>
  )
}

function TechnicalLoadingScreen({
  phase,
  error,
  onRetry,
  onBack,
}: {
  phase: string
  error: string
  onRetry: () => void
  onBack: () => void
}) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4 text-foreground">
      <div className="w-full max-w-md rounded-lg border border-border bg-card p-6 text-center shadow-2xl">
        {!error ? (
          <>
            <div className="mx-auto mb-5 flex h-12 w-12 items-center justify-center rounded-lg bg-secondary ring-1 ring-border">
              <Loader2 className="h-5 w-5 animate-spin text-emerald-300" />
            </div>
            <h1 className="text-lg font-semibold">Preparing…</h1>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">{phase}</p>
          </>
        ) : (
          <>
            <div className="mx-auto mb-5 flex h-12 w-12 items-center justify-center rounded-lg bg-rose-500/10 text-rose-600 dark:text-rose-300 ring-1 ring-rose-500/30">
              <AlertTriangle className="h-5 w-5" />
            </div>
            <h1 className="text-lg font-semibold">Could not open the technical round</h1>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">{error}</p>
            <div className="mt-5 flex flex-col gap-2 sm:flex-row sm:justify-center">
              <Button variant="outline" className="border-border bg-secondary text-foreground hover:bg-secondary" onClick={onBack}>
                Back
              </Button>
              <Button className="bg-primary text-primary-foreground hover:bg-primary/90" onClick={onRetry}>
                Retry
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function TechnicalLeaveConfirmDialog({
  open,
  intent,
  onCancel,
  onConfirm,
}: {
  open: boolean
  intent: "abandon" | "complete"
  onCancel: () => void
  onConfirm: () => void
}) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/65 px-4 backdrop-blur-sm">
      <div className="w-full max-w-sm overflow-hidden rounded-lg border border-border bg-card shadow-2xl">
        <div className="p-6 text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-amber-500/10 text-amber-700 dark:text-amber-300 ring-1 ring-amber-500/30">
            <AlertTriangle className="h-5 w-5" />
          </div>
          <h2 className="text-lg font-semibold text-foreground">{intent === "complete" ? "Finish this test?" : "End this attempt?"}</h2>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            {intent === "complete"
              ? "Your submitted work will be locked and queued for evidence-backed analysis. Draft-only rounds stay clearly marked and do not become final scored submissions."
              : "This session cannot be resumed. Available drafts and responses will be kept, but the attempt will be marked incomplete and will not receive an official final score."}
          </p>
        </div>
        <div className="flex border-t border-border">
          <button onClick={onCancel} className="flex-1 px-4 py-3 text-sm font-medium text-foreground hover:bg-secondary">
            {intent === "complete" ? "Continue working" : "Stay in session"}
          </button>
          <div className="w-px bg-border" />
          <button onClick={onConfirm} className="flex-1 px-4 py-3 text-sm font-medium text-amber-600 dark:text-amber-200 hover:bg-amber-500/10">
            {intent === "complete" ? "Finish test" : "End attempt"}
          </button>
        </div>
      </div>
    </div>
  )
}

function PermissionRow({ label, active }: { label: string; active: boolean }) {
  return (
    <div className="flex items-center justify-between rounded-md border border-border bg-secondary px-3 py-2">
      <span className="text-sm text-foreground">{label}</span>
      <span className={cn("rounded-md px-2 py-1 text-xs font-medium", active ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300" : "bg-amber-500/15 text-amber-700 dark:text-amber-300")}>
        {active ? "Ready" : "Required"}
      </span>
    </div>
  )
}

function writtenRoundGuidance(roundType: string) {
  const guidance: Record<string, string[]> = {
    technical_concept: ["Define the mechanism precisely", "Apply it to the scenario", "Compare trade-offs", "Cover failure modes and measurement"],
    system_design: ["Clarify requirements and scale", "Describe components and data flow", "Explain storage and consistency", "Cover failure recovery, observability, and trade-offs"],
    ml: ["Define the objective and data", "Choose an evaluation strategy", "Address leakage and drift", "Describe deployment and monitoring trade-offs"],
    backend: ["State API and data invariants", "Explain concurrency and failure handling", "Cover retry safety and observability", "Discuss scaling trade-offs"],
    database: ["Model data and access patterns", "Explain consistency and transactions", "Discuss indexes and contention", "Cover recovery and measurement"],
    os: ["Explain the operating-system mechanism", "Connect it to the incident", "Describe diagnosis evidence", "Propose mitigation and validation"],
    network: ["Trace the distributed request path", "Cover timeouts and retry safety", "Discuss partial failure and security", "Explain observability"],
    oop: ["Define responsibilities and invariants", "Show extension points", "Explain testability", "Discuss composition versus inheritance"],
  }
  return guidance[roundType] || ["Explain the mechanism", "Apply it concretely", "Discuss trade-offs", "Cover failure modes and validation"]
}

function TypedTechnicalResponsePanel({
  round,
  roundIndex,
  value,
  result,
  submitting,
  locked,
  lockMessage,
  onChange,
  onSubmit,
}: {
  round?: Round
  roundIndex: number
  value: string
  result?: TechnicalResponseResult
  submitting: boolean
  locked: boolean
  lockMessage: string
  onChange: (value: string) => void
  onSubmit: () => void
}) {
  if (!round) return null
  const expectedPoints = (round.round_spec?.expected_points || round.metadata?.expected_points || []) as Array<Record<string, unknown>>
  const rubric = (round.round_spec?.rubric || round.metadata?.rubric || {}) as Record<string, any>
  const weights = rubric.weights && typeof rubric.weights === "object" ? Object.entries(rubric.weights) : []
  const assessment = result?.assessment && typeof result.assessment === "object" ? result.assessment : null
  const decision = result?.decision && typeof result.decision === "object" ? result.decision : null
  const needsFollowup = decision?.action === "targeted_followup"
  const responsePrompt = needsFollowup
    ? String(decision?.followup_prompt || "Go deeper on the missing technical evidence.")
    : round.prompt || round.metadata?.statement || "Technical response prompt"
  const assessmentScore = assessment && typeof (assessment.overall_score ?? assessment.score) === "number"
    ? Number(assessment.overall_score ?? assessment.score)
    : null
  const assessmentSummary = assessment
    ? String(assessment.summary || assessment.feedback || assessment.rationale || "Response committed. Detailed evidence will appear in the final report.")
    : ""
  const guidance = writtenRoundGuidance(round.round_type)
  const wordCount = value.trim() ? value.trim().split(/\s+/).length : 0

  return (
    <main className="min-h-0 flex-1 overflow-y-auto bg-background p-3 lg:p-5">
      <div className="mx-auto grid max-w-7xl gap-4 lg:grid-cols-[minmax(0,0.9fr)_minmax(480px,1.1fr)]">
        <section className="space-y-4 rounded-lg border border-border bg-card p-5">
          <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border pb-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.12em] text-primary">Round {roundIndex + 1} · {formatRoundType(round.round_type)}</p>
              <h1 className="mt-2 text-xl font-semibold text-foreground">{round.metadata?.title || formatRoundType(round.round_type)}</h1>
            </div>
            <span className={cn("rounded-md px-2.5 py-1 text-xs font-semibold", difficultyClass(formatDifficulty(round.metadata?.difficulty)))}>
              {formatDifficulty(round.metadata?.difficulty)}
            </span>
          </div>
          <div>
            <h2 className="text-sm font-semibold text-foreground">Prompt</h2>
            <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-foreground">{responsePrompt}</p>
            {needsFollowup && <p className="mt-2 text-xs font-semibold uppercase tracking-wide text-primary">Targeted follow-up · one final response</p>}
          </div>
          <div>
            <h2 className="text-sm font-semibold text-foreground">Response structure</h2>
            <ol className="mt-3 space-y-2">
              {guidance.map((item, index) => <li key={item} className="flex gap-2 text-sm leading-6 text-muted-foreground"><span className="font-mono text-primary">{index + 1}.</span>{item}</li>)}
            </ol>
          </div>
          {!!expectedPoints.length && (
            <div>
              <h2 className="text-sm font-semibold text-foreground">Evidence points</h2>
              <div className="mt-3 flex flex-wrap gap-2">
                {expectedPoints.map((point, index) => <span key={String(point.point_id || index)} className="rounded-md border border-border bg-secondary px-2.5 py-1.5 text-xs text-muted-foreground">{String(point.label || point.point_id || `Point ${index + 1}`)}</span>)}
              </div>
            </div>
          )}
          {!!weights.length && (
            <div className="rounded-md border border-border bg-secondary/40 p-3">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Public rubric</p>
              <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                {weights.map(([key, raw]) => <span key={key}>{formatPattern(key)} · {typeof raw === "number" ? `${Math.round(raw * 100)}%` : String(raw)}</span>)}
              </div>
            </div>
          )}
        </section>

        <section className="flex min-h-[560px] flex-col overflow-hidden rounded-lg border border-border bg-card">
          <div className="flex items-center justify-between border-b border-border bg-secondary px-4 py-3">
            <div className="text-sm font-semibold text-foreground">Written response</div>
            <span className="text-xs text-muted-foreground">{wordCount} words · saved in this tab</span>
          </div>
          <textarea
            value={value}
            onChange={(event) => onChange(event.target.value)}
            disabled={locked || submitting || Boolean(result && !needsFollowup)}
            placeholder={needsFollowup ? "Answer the targeted follow-up with the missing mechanism and evidence…" : "Write a structured, evidence-backed technical response…"}
            className="min-h-[410px] flex-1 resize-none bg-card p-5 text-sm leading-7 text-foreground outline-none placeholder:text-muted-foreground disabled:opacity-70"
          />
          <div className="space-y-3 border-t border-border p-4">
            {result && !needsFollowup && (
              <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-900 dark:text-emerald-100">
                <div className="flex items-center justify-between gap-3 font-semibold"><span className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4" /> Response committed</span><span>{assessmentScore === null ? "Assessment pending" : `${Math.round(assessmentScore)}%`}</span></div>
                {assessmentSummary && <p className="mt-2 text-xs leading-5 opacity-90">{assessmentSummary}</p>}
              </div>
            )}
            {locked && !result && <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-800 dark:text-amber-200">{lockMessage}</div>}
            <div className="flex justify-end">
              <Button onClick={onSubmit} disabled={locked || submitting || Boolean(result && !needsFollowup) || !value.trim()} className="gap-2">
                {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                {submitting ? "Saving response…" : (result && !needsFollowup) ? "Response saved" : needsFollowup ? "Submit follow-up" : "Submit response"}
              </Button>
            </div>
          </div>
        </section>
      </div>
    </main>
  )
}

function ProblemPanel({
  round,
  roundIndex,
  activeTab,
  onTabChange,
  tests,
  constraintsRevealed,
  hintRevealed,
  technicalTranscript,
  micListening,
  micSupported,
  onRevealConstraints,
  onRevealHint,
  onToggleMic,
  workflowDraft,
  workflowState,
  workflowSaving,
  actionLocked,
  onWorkflowChange,
  onCommitFinalEvidence,
}: {
  round?: Round
  roundIndex: number
  activeTab: InfoTab
  onTabChange: (tab: InfoTab) => void
  tests: TestCase[]
  constraintsRevealed: boolean
  hintRevealed: boolean
  technicalTranscript: string
  micListening: boolean
  micSupported: boolean
  onRevealConstraints: () => void
  onRevealHint: () => void
  onToggleMic: () => void
  workflowDraft: CodingWorkflowDraft
  workflowState: Record<string, any>
  workflowSaving: boolean
  actionLocked: boolean
  onWorkflowChange: (field: keyof CodingWorkflowDraft, value: string) => void
  onCommitFinalEvidence: () => void
}) {
  const difficulty = formatDifficulty(round?.metadata?.difficulty)
  const prompt = String(round?.metadata?.statement || round?.prompt || "No prompt is available for this round.")
  const hasHint = Boolean(round?.metadata?.hint)

  return (
    <div className="min-h-0 overflow-hidden rounded-lg border border-border bg-card">
      <div className="flex h-10 items-center justify-between border-b border-border bg-secondary px-3">
        <div className="flex min-w-0 items-center gap-1 overflow-x-auto">
          {infoTabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => onTabChange(tab.id)}
              className={cn(
                "flex h-8 shrink-0 items-center gap-1.5 rounded-md px-2 text-sm transition-colors",
                activeTab === tab.id ? "font-semibold text-foreground" : "text-muted-foreground hover:bg-secondary hover:text-foreground"
              )}
            >
              {tab.id === "description" && <FileText className="h-3.5 w-3.5 text-sky-400" />}
              {tab.label}
            </button>
          ))}
        </div>
        <LayoutPanelLeft className="hidden h-4 w-4 text-muted-foreground sm:block" />
      </div>

      <div className="iv-thin-scrollbar h-[calc(100%-2.5rem)] min-h-0 overflow-y-auto px-5 py-6">
        {activeTab === "description" ? (
          <div className="space-y-7 pb-12">
            <div>
              <h1 className="text-2xl font-bold tracking-normal text-foreground">{problemTitle(round, roundIndex)}</h1>
              <div className="mt-4 flex flex-wrap gap-2 text-xs font-medium">
                <span className={cn("rounded-full px-2.5 py-1", difficultyClass(difficulty))}>{difficulty}</span>
              </div>
            </div>

            <div className="rounded-lg border border-border bg-secondary/70 p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                  <LayoutPanelLeft className="h-4 w-4 text-emerald-400" />
                  Problem
                </div>
              </div>
              <div className="space-y-4 text-[15px] leading-7 text-foreground">
                {prompt.split(/\n{2,}/).map((paragraph) => (
                  <p key={paragraph}>{paragraph}</p>
                ))}
              </div>
            </div>

            <div className="grid gap-3 text-sm text-muted-foreground md:grid-cols-2">
              <ProblemSpecBlock title="Input Format" value={round?.metadata?.input_format} />
              <ProblemSpecBlock title="Output Format" value={round?.metadata?.output_format} />
              <ProblemSpecBlock
                title="Constraints"
                value={constraintsRevealed ? round?.metadata?.constraints : "Hidden until you ask the interviewer."}
                muted={!constraintsRevealed}
              />
              <ProblemSpecBlock
                title="Expected Complexity"
                value={constraintsRevealed ? `${round?.metadata?.expected_time_complexity || "Not specified"} time, ${round?.metadata?.expected_space_complexity || "not specified"} space` : "Hidden until constraints are clarified."}
                muted={!constraintsRevealed}
              />
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                className="h-8 gap-1.5 border-sky-500/30 bg-sky-500/10 text-sky-700 hover:bg-sky-500/20 hover:text-sky-800 dark:text-sky-300 dark:hover:text-sky-200"
                onClick={onRevealConstraints}
                disabled={constraintsRevealed}
              >
                <HelpCircle className="h-3.5 w-3.5" />
                {constraintsRevealed ? "Constraints shown" : "Ask constraints"}
              </Button>
              {hasHint && (
                <Button
                  size="sm"
                  variant="outline"
                  className="h-8 gap-1.5 border-violet-500/30 bg-violet-500/10 text-violet-700 hover:bg-violet-500/20 hover:text-violet-800 dark:text-violet-300 dark:hover:text-violet-200"
                  onClick={onRevealHint}
                  disabled={hintRevealed}
                >
                  <HelpCircle className="h-3.5 w-3.5" />
                  {hintRevealed ? "Hint shown" : "Ask hint"}
                </Button>
              )}
              <Button
                size="sm"
                variant="outline"
                className="h-8 gap-1.5 border-emerald-500/30 bg-emerald-500/10 text-emerald-700 hover:bg-emerald-500/20 hover:text-emerald-800 dark:text-emerald-300 dark:hover:text-emerald-200"
                onClick={onToggleMic}
                disabled={!micSupported}
              >
                {micListening ? <MicOff className="h-3.5 w-3.5" /> : <Mic className="h-3.5 w-3.5" />}
                {micListening ? "Stop voice notes" : "Use voice notes"}
              </Button>
            </div>

            {String(round?.status || "").toLowerCase() === "awaiting_explanation" && (
              <div className="space-y-3 rounded-md border border-primary/30 bg-primary/5 p-4">
                <div>
                  <p className="text-sm font-semibold text-foreground">Final reasoning</p>
                  <p className="mt-1 text-xs text-muted-foreground">Your code is locked. Complete both evidence steps to finish this round.</p>
                </div>
                <textarea
                  value={workflowDraft.complexity}
                  onChange={(event) => onWorkflowChange("complexity", event.target.value)}
                  disabled={Boolean(workflowState.complexity) || workflowSaving}
                  placeholder="Time complexity…, space complexity…, and why…"
                  className="h-24 w-full resize-none rounded-md border border-border bg-background p-3 text-sm leading-6 text-foreground outline-none focus:border-primary disabled:opacity-60"
                />
                <textarea
                  value={workflowDraft.explanation}
                  onChange={(event) => onWorkflowChange("explanation", event.target.value)}
                  disabled={Boolean(workflowState.explanation) || workflowSaving}
                  placeholder="Explain the final implementation, edge cases, debugging changes, and remaining trade-offs…"
                  className="h-28 w-full resize-none rounded-md border border-border bg-background p-3 text-sm leading-6 text-foreground outline-none focus:border-primary disabled:opacity-60"
                />
                <div className="flex justify-end">
                  <Button size="sm" onClick={onCommitFinalEvidence} disabled={workflowSaving || Boolean(workflowState.explanation) || !workflowDraft.complexity.trim() || !workflowDraft.explanation.trim()}>
                    {workflowSaving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />} Commit final reasoning
                  </Button>
                </div>
              </div>
            )}

            {hasHint && hintRevealed && (
              <div className="rounded-md border border-border bg-secondary px-4 py-3 text-sm leading-6 text-foreground">
                <p className="mb-1 text-xs font-bold uppercase tracking-[0.12em] text-muted-foreground">Hint</p>
                <p>{String(round?.metadata?.hint || "")}</p>
              </div>
            )}

            {micListening && (
              <div className="rounded-md border border-border bg-secondary px-4 py-3">
                <WaveformVisualizer isActive={micListening} variant="emerald" size="sm" />
              </div>
            )}

            {tests.length > 0 && (
              <div className="space-y-5">
                {tests.map((test, index) => (
                  <div key={`${test.stdin}-${index}`}>
                    <p className="mb-3 text-base font-semibold text-foreground">Example {index + 1}:</p>
                    <div className="border-l-2 border-border bg-secondary/60 px-4 py-3 font-mono text-sm leading-6 text-foreground/90">
                      <p><span className="font-semibold text-foreground">Input:</span> {formatCaseInput(test.stdin)}</p>
                      <p><span className="font-semibold text-foreground">Output:</span> {expectedOutput(test)}</p>
                      {test.explanation && <p className="mt-2 whitespace-pre-wrap text-muted-foreground"><span className="font-semibold text-foreground">Explanation:</span> {test.explanation}</p>}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {technicalTranscript.trim() && (
              <div>
                <p className="mb-3 text-base font-semibold text-foreground">Transcript</p>
                <pre className="max-h-36 whitespace-pre-wrap overflow-y-auto rounded-md border border-border bg-secondary px-4 py-3 text-sm leading-6 text-muted-foreground">
                  {technicalTranscript}
                </pre>
              </div>
            )}
          </div>
        ) : (
          <div className="flex h-full min-h-[300px] items-center justify-center text-center">
            <div>
              <p className="text-base font-semibold text-foreground">{infoTabs.find((tab) => tab.id === activeTab)?.label}</p>
              <p className="mt-2 max-w-sm text-sm leading-6 text-muted-foreground">
                This section unlocks after you run or submit a solution in the technical workspace.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function ProblemSpecBlock({ title, value, muted = false }: { title: string; value: unknown; muted?: boolean }) {
  return (
    <div className="rounded-md border border-border bg-secondary px-4 py-3">
      <p className="mb-2 text-xs font-bold uppercase tracking-[0.12em] text-muted-foreground">{title}</p>
      <p className={cn("whitespace-pre-wrap leading-6", muted ? "text-muted-foreground" : "text-foreground")}>{String(value || "Not specified")}</p>
    </div>
  )
}

function TestcasePanel({
  tests,
  selectedCaseIndex,
  customInput,
  onSelectCase,
  onCustomInputChange,
}: {
  tests: TestCase[]
  selectedCaseIndex: number
  customInput: string
  onSelectCase: (index: number) => void
  onCustomInputChange: (value: string) => void
}) {
  const hasCases = tests.length > 0

  return (
    <div className="min-h-0 overflow-hidden rounded-lg border border-border bg-card">
      <div className="flex h-10 items-center gap-2 border-b border-border bg-secondary px-4">
        <CheckCircle2 className="h-4 w-4 text-emerald-400" />
        <span className="text-sm font-semibold text-foreground">Testcase</span>
      </div>
      <div className="p-4">
        {hasCases && (
          <div className="mb-4 flex flex-wrap gap-2">
            {tests.map((test, index) => (
              <button
                key={`${test.stdin}-${index}`}
                type="button"
                onClick={() => onSelectCase(index)}
                className={cn(
                  "h-8 rounded-md px-4 text-sm font-semibold transition-colors",
                  selectedCaseIndex === index ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-secondary hover:text-foreground"
                )}
              >
                Case {index + 1}
              </button>
            ))}
          </div>
        )}
        <label className="mb-2 block text-sm font-medium text-muted-foreground">
          Custom input
        </label>
        <textarea
          className="h-24 w-full resize-none rounded-md border border-border bg-secondary p-3 font-mono text-sm text-foreground outline-none placeholder:text-muted-foreground focus:border-ring"
          placeholder={hasCases ? "Custom input" : "Type custom stdin for this generated problem"}
          value={customInput}
          onChange={(event) => onCustomInputChange(event.target.value)}
        />
        <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
          <Code2 className="h-3.5 w-3.5" />
          <span>Source</span>
        </div>
      </div>
    </div>
  )
}

function CodePanel({
  round,
  language,
  code,
  executorName,
  onLanguageChange,
  onCodeChange,
  onRecordTechnicalEvent,
}: {
  round?: Round
  language: Language
  code: string
  executorName: string
  onLanguageChange: (language: Language) => void
  onCodeChange: (code: string) => void
  onRecordTechnicalEvent: (eventType: string, payload?: Record<string, unknown>, roundId?: string) => void
}) {
  const keyActivityRef = useRef({ count: 0, lastSentAt: 0, firstSent: false })

  useEffect(() => {
    keyActivityRef.current = { count: 0, lastSentAt: 0, firstSent: false }
  }, [round?.round_id])

  const recordKeyActivity = useCallback(() => {
    const now = Date.now()
    keyActivityRef.current.count += 1
    if (!keyActivityRef.current.firstSent) {
      void onRecordTechnicalEvent(
        "first_code_activity",
        { keystrokes: 1 },
        round?.round_id
      )
      keyActivityRef.current.firstSent = true
    }
    const shouldSend =
      keyActivityRef.current.count >= 25 ||
      now - keyActivityRef.current.lastSentAt >= 10000

    if (!shouldSend) return

    void onRecordTechnicalEvent(
      "code_activity",
      {
        keystrokes: keyActivityRef.current.count,
        window_ms: keyActivityRef.current.lastSentAt ? now - keyActivityRef.current.lastSentAt : null,
      },
      round?.round_id
    )
    keyActivityRef.current = { count: 0, lastSentAt: now, firstSent: true }
  }, [onRecordTechnicalEvent, round?.round_id])

  return (
    <div
      className="min-h-0 overflow-hidden rounded-lg border border-border bg-card"
      onPasteCapture={(event) => {
        event.preventDefault()
        toast.warning("Paste is blocked in strict mode.")
        void onRecordTechnicalEvent("paste_blocked", { chars: event.clipboardData.getData("text").length }, round?.round_id)
      }}
      onDropCapture={(event) => {
        event.preventDefault()
        toast.warning("Dropping code is blocked in strict mode.")
        void onRecordTechnicalEvent("drop_blocked", {}, round?.round_id)
      }}
    >
      <div className="flex h-10 items-center justify-between border-b border-border bg-secondary px-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <Code2 className="h-4 w-4 text-emerald-400" />
          Code
        </div>
        <div className="flex items-center gap-3">
          <select
            className="h-8 rounded-md border border-transparent bg-secondary px-1 text-sm text-muted-foreground outline-none hover:border-border"
            value={language}
            onChange={(event) => onLanguageChange(event.target.value as Language)}
          >
            <option value="python">Python3</option>
            <option value="javascript">JavaScript</option>
            <option value="java">Java</option>
            <option value="cpp">C++</option>
          </select>
          <span className="text-sm text-muted-foreground">{executorName || "Code runner"}</span>
        </div>
      </div>

      <div className="h-[calc(100%-4.9rem)] min-h-[260px]">
        <MonacoEditor
          height="100%"
          theme="vs-dark"
          language={language === "cpp" ? "cpp" : language}
          value={code}
          onChange={(value) => onCodeChange(value || "")}
          onMount={(editor) => {
            editor.onDidPaste(() => {
              const currentCode = editor.getValue()
              void onRecordTechnicalEvent("paste_blocked", { chars: currentCode.length }, round?.round_id)
            })
            editor.onKeyDown(recordKeyActivity)
          }}
          options={{
            automaticLayout: true,
            fontSize: 14,
            lineNumbersMinChars: 3,
            minimap: { enabled: false },
            padding: { top: 10 },
            quickSuggestions: false,
            scrollBeyondLastLine: false,
            suggestOnTriggerCharacters: false,
          }}
        />
      </div>
      <div className="flex h-9 items-center justify-between border-t border-border bg-card px-4 text-xs text-muted-foreground">
        <span>Saved</span>
        <span>{languageLabels[language] || language}</span>
      </div>
    </div>
  )
}

function ResultPanel({
  output,
  running,
  executorName,
  actionLocked,
  lockMessage,
  submitLocked,
  submitsLeft,
  maxSubmissions,
  pollingError,
  canResumePolling,
  onRun,
  onSubmit,
  onResumePolling,
}: {
  output: RunResult | null
  running: boolean
  executorName: string
  actionLocked: boolean
  lockMessage: string
  submitLocked: boolean
  submitsLeft: number
  maxSubmissions: number
  pollingError: string
  canResumePolling: boolean
  onRun: () => void
  onSubmit: () => void
  onResumePolling: () => void
}) {
  return (
    <div className="min-h-0 overflow-hidden rounded-lg border border-border bg-card">
      <div className="flex h-10 items-center justify-between border-b border-border bg-secondary px-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <SquareTerminal className="h-4 w-4 text-emerald-400" />
          Test Result
        </div>
        <div className="flex gap-2">
          <Button size="sm" className="h-7 gap-1.5 bg-indigo-600 px-3 text-white hover:bg-indigo-700" onClick={onRun} disabled={running || actionLocked}>
            <Play className="h-3 w-3" />
            Run
          </Button>
          <Button size="sm" className="h-7 gap-1.5 bg-emerald-600 px-3 text-white hover:bg-emerald-700" onClick={onSubmit} disabled={running || submitLocked || submitsLeft <= 0}>
            <Upload className="h-3 w-3" />
            Submit{maxSubmissions > 1 ? ` (${submitsLeft})` : ""}
          </Button>
        </div>
      </div>

      <div className="iv-thin-scrollbar h-[calc(100%-2.5rem)] min-h-0 overflow-y-auto p-4">

          {pollingError && (
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-800 dark:text-amber-200">
              <span>{pollingError}</span>
              {canResumePolling && (
                <Button size="sm" variant="outline" disabled={running} onClick={onResumePolling}>
                  {running ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
                  Resume status check
                </Button>
              )}
            </div>
          )}

          {running && (
            <div className="mb-3 flex items-center gap-3 rounded-md border border-sky-500/25 bg-sky-500/10 px-3 py-2 text-sm text-sky-100">
              <Loader2 className="h-4 w-4 animate-spin" />
              {output?.status === "queued" ? `Queued in ${output.executor || executorName || "code runner"}` : "Running test cases"}
            </div>
          )}

          {output ? (
            <div className="space-y-3 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border bg-secondary px-3 py-2">
                <div className="flex items-center gap-2">
                  {output.status === "failed" ? (
                    <AlertTriangle className="h-4 w-4 text-rose-400" />
                  ) : typeof output.pass_count === "number" && output.total_count === output.pass_count ? (
                    <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                  ) : (
                    <AlertTriangle className="h-4 w-4 text-amber-400" />
                  )}
                  <span className="font-semibold text-foreground">
                    {output.status === "failed"
                      ? "Run failed"
                      : typeof output.pass_count === "number"
                        ? `Passed ${output.pass_count}/${output.total_count}`
                        : output.verdict || `Exit code ${output.exit_code ?? 0}`}
                  </span>
                </div>
                <span className="text-xs text-muted-foreground">
                  runtime {output.runtime_ms || 0}ms - memory {output.memory_kb || 0}KB
                </span>
              </div>

              {typeof output.hidden_total === "number" && output.hidden_total > 0 && (
                <div className="flex items-center justify-between rounded-md border border-violet-500/25 bg-violet-500/10 px-3 py-2 text-xs">
                  <span className="font-semibold text-violet-800 dark:text-violet-200">Hidden validation</span>
                  <span className="text-muted-foreground">
                    {output.status === "completed"
                      ? `${output.hidden_passed || 0}/${output.hidden_total} passed`
                      : "Results available when execution completes"}
                  </span>
                </div>
              )}

              {output.cases?.map((item) => (
                <div key={item.index} className={cn("rounded-md border p-3", item.passed ? "border-emerald-500/30 bg-emerald-500/10" : "border-rose-500/30 bg-rose-500/10")}>
                  <div className="mb-2 flex items-center justify-between">
                    <span className={cn("text-xs font-bold uppercase", item.passed ? "text-emerald-700 dark:text-emerald-300" : "text-rose-700 dark:text-rose-300")}>
                      {item.verdict || (item.passed ? "Accepted" : "Wrong Answer")}
                    </span>
                    <span className="text-xs text-muted-foreground">{item.hidden ? "Hidden " : ""}Case {item.case_number || item.index + 1}</span>
                  </div>
                  {item.hidden ? (
                    <p className="font-mono text-xs leading-5 text-foreground">runtime {item.runtime_ms || 0}ms - memory {item.memory_kb || 0}KB</p>
                  ) : (
                    <div className="space-y-1 font-mono text-xs leading-5 text-foreground">
                      <p>Input: {formatCaseInput(item.stdin)}</p>
                      <p>Expected: {item.expected || "(any)"}</p>
                      <p>Actual: {item.actual || "(no output)"}</p>
                      {item.stderr && <p className="text-rose-700 dark:text-rose-200">stderr: {item.stderr}</p>}
                    </div>
                  )}
                </div>
              ))}

              {(output.error || output.stdout || output.stderr || !output.cases?.length) && (
                <pre className="whitespace-pre-wrap rounded-md border border-border bg-secondary p-3 font-mono text-xs leading-5 text-foreground">
                  {output.error || output.stdout || output.stderr || "(no output)"}
                </pre>
              )}

              {submitLocked && (
                <div className="rounded-md border border-sky-500/30 bg-sky-500/10 px-3 py-2 text-xs text-sky-200">
                  {actionLocked ? lockMessage : "Final submits are closed for this round."}
                </div>
              )}
            </div>
          ) : !running ? (
            <div className="flex h-44 items-center justify-center text-center text-sm text-muted-foreground">
              You must run your code first
            </div>
          ) : null}
      </div>
    </div>
  )
}
