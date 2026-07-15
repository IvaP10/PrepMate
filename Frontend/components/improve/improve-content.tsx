"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  BadgeCheck,
  Check,
  CheckCircle2,
  ChevronRight,
  Circle,
  CircleDot,
  Clock,
  Code,
  Lock,
  MessageSquare,
  Mic,
  Play,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  Target,
  Timer,
  Unlock,
  X,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { SlidingSegmentControl } from "@/components/sliding-segment-control"
import { Textarea } from "@/components/ui/textarea"
import {
  createExerciseAttemptSession,
  submitExerciseAttempt,
  updateExerciseAttemptSession,
  type ActiveImproveMission,
  type ExerciseAttemptResult,
  type ImproveAttemptSession,
  type ImproveRoadmapNode,
  type ImprovementHistory,
  type LearningDashboard,
  type ExactImproveTarget,
} from "@/lib/api"
import { cn } from "@/lib/utils"
import {
  buildActivityAttemptPayload,
  completedRoadmapSteps,
  estimatedRemainingMinutes,
  formatAttemptResult,
  getActivityPrompt,
  getCurrentRoadmapNode,
  getPassConditionLabels,
  historyHasRealData,
  isDraftSubmittable,
  nextActionLabel,
  nodeStateLabel,
  shouldHideHints,
  type ActivityDraft,
} from "./activity-helpers"

type ImproveContentProps = {
  learning?: LearningDashboard | null
  loading?: boolean
  error?: string
  setActiveNav: (nav: "improve" | "interview" | "coding" | "resume" | "performance" | "membership" | "settings") => void
  onLearningRefresh?: () => Promise<void> | void
  isPremium?: boolean
  navigationTarget?: ExactImproveTarget | null
  onNavigationConsumed?: () => void
}

type ActivityPhase = "before" | "during" | "feedback"
type ImproveMode = "interview" | "technical"

type SpeechRecognitionLike = {
  continuous: boolean
  interimResults: boolean
  lang: string
  onresult: ((event: any) => void) | null
  onerror: ((event: any) => void) | null
  onend: (() => void) | null
  start: () => void
  stop: () => void
  abort: () => void
}

declare global {
  interface Window {
    SpeechRecognition?: new () => SpeechRecognitionLike
    webkitSpeechRecognition?: new () => SpeechRecognitionLike
  }
}

function createAttemptKey() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID()
  return `attempt-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function scoreLabel(value: number | undefined | null) {
  return `${Math.round(Number(value || 0))}`
}

function isTechnicalHistoryKey(value?: string | null) {
  const key = String(value || "").toLowerCase()
  return key.startsWith("technical:") || key.startsWith("algorithm:") || key.startsWith("debugging:") || key.startsWith("dsa:")
}

function historyRecordMode(record: {
  mode?: string | null
  skill_key?: string | null
  weakness_key?: string | null
  weakness_type?: string | null
  title?: string | null
}): ImproveMode {
  const mode = String(record.mode || "").toLowerCase()
  if (mode === "technical") return "technical"
  if (mode === "mock" || mode === "interview") return "interview"
  if (
    record.weakness_type === "technical_failure" ||
    isTechnicalHistoryKey(record.skill_key) ||
    isTechnicalHistoryKey(record.weakness_key)
  ) {
    return "technical"
  }
  return "interview"
}

function filterHistoryForMode(history: ImprovementHistory | null | undefined, mode: ImproveMode): ImprovementHistory | null {
  if (!history) return null
  const skills = (history.skills || []).filter((skill) => historyRecordMode(skill) === mode)
  const completedMissions = (history.completed_missions || []).filter((mission) => historyRecordMode(mission) === mode)
  const recentAttempts = (history.recent_attempts || []).filter((attempt) => historyRecordMode(attempt) === mode)
  return {
    ...history,
    skills,
    completed_missions: completedMissions,
    recent_attempts: recentAttempts,
    has_history: Boolean(skills.length || completedMissions.length || recentAttempts.length),
  }
}

function formatActivityType(type?: string | null) {
  return String(type || "activity").replace(/_/g, " ")
}

function draftFromSession(session: ImproveAttemptSession | null | undefined, node: ImproveRoadmapNode | null): ActivityDraft {
  const payload = session?.draft_payload || {}
  const prompt = getActivityPrompt(node)
  if (!session && node?.activity_type === "arrange_blocks") {
    const blocks = Array.isArray(prompt.blocks) ? prompt.blocks : []
    return { blockOrder: blocks.map((block: any) => String(block.id)) }
  }
  return {
    selectedOption: String(payload.selected_option || payload.selectedOption || ""),
    reason: String(payload.reason || ""),
    blockOrder: Array.isArray(payload.block_order)
      ? payload.block_order.map(String)
      : Array.isArray(payload.blockOrder)
        ? payload.blockOrder.map(String)
        : node?.activity_type === "arrange_blocks" && Array.isArray(prompt.blocks)
          ? prompt.blocks.map((block: any) => String(block.id))
          : undefined,
    rewrite: String(payload.rewrite || ""),
    transcript: String(payload.transcript || ""),
    answer: String(payload.answer || ""),
  }
}

function sessionSecondsRemaining(session: ImproveAttemptSession | null | undefined, fallbackSeconds: number): number | null {
  if (!session) return fallbackSeconds > 0 ? fallbackSeconds : null
  if (session.deadline_at) {
    const deadline = new Date(session.deadline_at).getTime()
    if (Number.isFinite(deadline)) return Math.max(0, Math.ceil((deadline - Date.now()) / 1000))
  }
  if (session.remaining_seconds !== null && session.remaining_seconds !== undefined) {
    return Math.max(0, Number(session.remaining_seconds))
  }
  return fallbackSeconds > 0 ? fallbackSeconds : null
}

export function ImproveContent({
  learning,
  loading = false,
  error = "",
  setActiveNav,
  onLearningRefresh,
  navigationTarget = null,
  onNavigationConsumed,
}: ImproveContentProps) {
  const [activeMode, setActiveMode] = useState<ImproveMode>("interview")
  const modeMissions = learning?.active_missions || {}
  const fallbackMission = learning?.active_mission || null
  const mission = modeMissions[activeMode] || (
    fallbackMission && (fallbackMission.mode === activeMode || (activeMode === "interview" && fallbackMission.mode === "mock"))
      ? fallbackMission
      : null
  )
  const history = learning?.improvement_history || null
  const modeHistory = useMemo(() => filterHistoryForMode(history, activeMode), [history, activeMode])
  const currentNode = useMemo(() => getCurrentRoadmapNode(mission), [mission])
  const activeSession = mission?.active_attempt_session || null
  const [activityNode, setActivityNode] = useState<ImproveRoadmapNode | null>(null)
  const [startFromSession, setStartFromSession] = useState(false)
  const [navigationError, setNavigationError] = useState("")
  const handledTargetRef = useRef("")

  useEffect(() => {
    if (!navigationTarget) {
      handledTargetRef.current = ""
      return
    }
    if (!learning) return
    const targetKey = `${navigationTarget.mission_id}:${navigationTarget.roadmap_node_id}:${navigationTarget.exercise_id}`
    if (handledTargetRef.current === targetKey) return
    handledTargetRef.current = targetKey

    const interviewMission = learning.active_missions?.interview || null
    const technicalMission = learning.active_missions?.technical || null
    const targetMission = [interviewMission, technicalMission, learning.active_mission || null]
      .find((candidate) => candidate?.mission_id === navigationTarget.mission_id) || null
    if (!targetMission) {
      setNavigationError("The requested improvement mission is no longer active.")
      onNavigationConsumed?.()
      return
    }
    const targetNode = (targetMission.roadmap || []).find((node) => (
      node.roadmap_node_id === navigationTarget.roadmap_node_id &&
      node.exercise_id === navigationTarget.exercise_id
    )) || null
    if (!targetNode) {
      setNavigationError("The requested activity does not belong to this mission.")
      onNavigationConsumed?.()
      return
    }
    if (
      targetNode.availability_status !== "current" ||
      targetNode.result_status === "passed" ||
      targetNode.result_status === "strong_pass"
    ) {
      setNavigationError("This activity is no longer the current roadmap step.")
      onNavigationConsumed?.()
      return
    }
    setNavigationError("")
    setActiveMode(targetMission === technicalMission || targetMission.mode === "technical" ? "technical" : "interview")
    setActivityNode(targetNode)
    setStartFromSession(Boolean(
      targetMission.active_attempt_session?.roadmap_node_id === targetNode.roadmap_node_id &&
      targetMission.active_attempt_session?.exercise_id === targetNode.exercise_id
    ))
    onNavigationConsumed?.()
  }, [learning, navigationTarget, onNavigationConsumed])

  const openActivity = (node: ImproveRoadmapNode | null, resume = false) => {
    if (!node || !node.exercise_id || node.availability_status !== "current") return
    setActivityNode(node)
    setStartFromSession(resume)
  }

  if (!learning && loading) {
    return (
      <main className="w-full px-4 py-6 md:px-8">
        <div className="mx-auto flex max-w-6xl flex-col gap-4">
          <div className="h-28 animate-pulse rounded-lg border border-border/70 bg-card/70" />
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
            <div className="h-[520px] animate-pulse rounded-lg border border-border/70 bg-card/60" />
            <div className="h-[360px] animate-pulse rounded-lg border border-border/70 bg-card/60" />
          </div>
        </div>
      </main>
    )
  }

  if (!learning) {
    return (
      <main className="w-full px-4 py-6 md:px-8">
        <div className="mx-auto flex max-w-4xl flex-col gap-4 rounded-lg border border-border/70 bg-card/75 p-6 shadow-sm">
          <div>
            <h2 className="text-xl font-semibold text-foreground">No improvement data loaded</h2>
            {error && <p className="mt-2 text-sm leading-6 text-destructive">{error}</p>}
          </div>
          <div className="flex flex-wrap gap-2">
            {onLearningRefresh && (
              <Button variant="outline" onClick={() => void onLearningRefresh()}>
                <RotateCcw className="h-4 w-4" />
                Retry
              </Button>
            )}
            <Button onClick={() => setActiveNav("interview")}>
              <Mic className="h-4 w-4" />
              Take interview
            </Button>
          </div>
        </div>
      </main>
    )
  }

  if (!mission) {
    return (
      <main className="w-full px-4 py-6 md:px-8">
        <div className="mx-auto flex max-w-6xl flex-col gap-6">
          <ImproveModeSwitch activeMode={activeMode} onChange={setActiveMode} />
          {navigationError && <ErrorBanner message={navigationError} />}
          <EmptyImproveState
            setActiveNav={setActiveNav}
            history={modeHistory}
            activeMode={activeMode}
            analysisAvailability={learning.analysis_availability}
          />
          <ImprovementHistorySection history={modeHistory} />
        </div>
      </main>
    )
  }

  const hasActiveSession = Boolean(
    activeSession &&
    currentNode &&
    activeSession.roadmap_node_id === currentNode.roadmap_node_id &&
    activeSession.exercise_id === currentNode.exercise_id,
  )

  return (
    <main className="w-full px-4 py-6 pb-24 md:px-8 md:pb-8">
      <div className="mx-auto flex max-w-7xl flex-col gap-5">
        <ImproveModeSwitch activeMode={activeMode} onChange={setActiveMode} />
        {navigationError && <ErrorBanner message={navigationError} />}
        <ImproveMissionHeader mission={mission} />
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
          <section className="min-w-0 rounded-lg border border-border/70 bg-card/70 p-4 shadow-sm backdrop-blur md:p-5">
            <div className="mb-5 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <p className="text-xs font-medium text-primary">Practice plan</p>
                <h2 className="text-xl font-semibold text-foreground">Focused steps for your next round</h2>
              </div>
              <MissionProgress mission={mission} />
            </div>
            <SkillRoadmap
              nodes={mission.roadmap}
              mission={mission}
              currentNodeId={currentNode?.roadmap_node_id || null}
              onInspect={(node) => openActivity(
                node,
                Boolean(activeSession && activeSession.roadmap_node_id === node.roadmap_node_id && activeSession.exercise_id === node.exercise_id),
              )}
              onVerify={() => setActiveNav(mission.mode === "technical" ? "coding" : "interview")}
            />
          </section>
          <aside className="flex min-w-0 flex-col gap-4">
            <CurrentActivityCard
              mission={mission}
              node={currentNode}
              hasActiveSession={hasActiveSession}
              onStart={() => openActivity(currentNode, hasActiveSession)}
              onVerify={() => setActiveNav(mission.mode === "technical" ? "coding" : "interview")}
            />
            <EvidenceDrawer mission={mission} node={currentNode} />
          </aside>
        </div>
        <MissionOutcomeSummary mission={mission} onVerify={() => setActiveNav(mission.mode === "technical" ? "coding" : "interview")} />
        <ImprovementHistorySection history={modeHistory} />
      </div>
      {currentNode?.exercise_id && (
        <div className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-card/95 p-3 shadow-2xl backdrop-blur md:hidden">
          <Button className="h-11 w-full" onClick={() => openActivity(currentNode, hasActiveSession)}>
            <Play className="h-4 w-4" />
            {nextActionLabel(currentNode, hasActiveSession)}
          </Button>
        </div>
      )}
      {activityNode && (
        <ActivityShell
          mission={mission}
          node={activityNode}
          activeSession={startFromSession ? activeSession : null}
          onClose={() => {
            setActivityNode(null)
            setStartFromSession(false)
          }}
          onLearningRefresh={onLearningRefresh}
        />
      )}
    </main>
  )
}

function EmptyImproveState({
  setActiveNav,
  history,
  activeMode,
  analysisAvailability,
}: {
  setActiveNav: ImproveContentProps["setActiveNav"]
  history?: ImprovementHistory | null
  activeMode: ImproveMode
  analysisAvailability?: { completed_count: number; missing_canonical_count: number }
}) {
  const hasCompletedMission = Boolean(history?.completed_missions?.length)
  const isTechnical = activeMode === "technical"
  const analysisPending = Number(analysisAvailability?.missing_canonical_count || 0) > 0
  const hasCompletedEvidence = Number(analysisAvailability?.completed_count || 0) > 0
  if (hasCompletedMission) {
    const latest = history?.completed_missions?.[0]
    return (
      <section className="rounded-lg border border-border/70 bg-card/75 p-5 shadow-sm backdrop-blur md:p-6">
        <div className="flex flex-col gap-5 md:flex-row md:items-center md:justify-between">
          <div className="max-w-2xl">
            <p className="text-xs font-semibold uppercase tracking-[0.12em] text-primary">Mission completed</p>
            <h2 className="mt-1 text-2xl font-semibold text-foreground">{latest?.title || "Improvement mission completed"}</h2>
          </div>
          <div className="grid min-w-[220px] grid-cols-3 gap-2 text-center">
            <ScorePill label="Baseline" value={latest?.baseline_readiness} />
            <ScorePill label="Latest" value={latest?.current_readiness} />
            <ScorePill label="Improved" value={latest?.improvement} signed />
          </div>
        </div>
        <div className="mt-5 flex justify-start">
          <Button onClick={() => setActiveNav(isTechnical ? "coding" : "interview")}>
            {isTechnical ? <Code className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
            {isTechnical ? "Take next technical round" : "Take next interview"}
          </Button>
        </div>
      </section>
    )
  }
  return (
    <section className="rounded-lg border border-border/70 bg-card/75 p-6 shadow-sm backdrop-blur">
      <div className="flex max-w-2xl flex-col gap-3">
        <div className="flex h-11 w-11 items-center justify-center rounded-lg border border-border bg-secondary/50 text-primary">
          {isTechnical ? <Code className="h-5 w-5" /> : <Target className="h-5 w-5" />}
        </div>
        <h2 className="text-2xl font-semibold text-foreground">
          {analysisPending
            ? "Preparing your practice plan"
            : hasCompletedEvidence
              ? "No verified weakness yet"
              : isTechnical ? "Build your technical practice plan" : "Build your interview practice plan"}
        </h2>
        <p className="text-sm leading-6 text-muted-foreground">
          {analysisPending
            ? "Your completed interviews are being converted into evidence-backed performance and Improve missions."
            : hasCompletedEvidence
              ? "Your completed evidence did not identify a reliable weakness for this mode. Take another comparable round to gather more evidence."
              : isTechnical
            ? "After your first technical round, you’ll get focused practice based on the problems you attempted and the decisions you made."
            : "After your first interview, you’ll get focused practice based on your answers and the areas that will make the biggest difference."}
        </p>
        <div>
          <Button onClick={() => setActiveNav(isTechnical ? "coding" : "interview")}>
            {isTechnical ? <Code className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
            {isTechnical ? "Start technical round" : "Take an interview"}
          </Button>
        </div>
      </div>
    </section>
  )
}

function ImproveModeSwitch({
  activeMode,
  onChange,
}: {
  activeMode: ImproveMode
  onChange: (mode: ImproveMode) => void
}) {
  const options = [
    { value: "interview" as const, label: "Interview Round", icon: <MessageSquare className="h-4 w-4" /> },
    { value: "technical" as const, label: "Technical Round", icon: <Code className="h-4 w-4" /> },
  ]
  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
      <SlidingSegmentControl
        options={options}
        value={activeMode}
        onValueChange={onChange}
        ariaLabel="Improve pathway mode"
        className="dashboard-segment-tabs w-fit max-w-full gap-1 rounded-full border-0 bg-card p-1.5 shadow-[0_14px_36px_rgba(15,23,42,0.06)] dark:shadow-[0_16px_38px_rgba(0,0,0,0.2)]"
        shape="pill"
      />
    </div>
  )
}

function ImproveMissionHeader({ mission }: { mission: ActiveImproveMission }) {
  const remaining = estimatedRemainingMinutes(mission)
  const completed = completedRoadmapSteps(mission)
  const total = mission.roadmap.length || 1
  const confidence = Math.round(Number(mission.diagnosis?.confidence_score || 0))
  const evidenceCount = Number(mission.diagnosis?.evidence_count || 0)
  return (
    <section className="overflow-hidden rounded-lg border border-border/70 bg-card/75 shadow-sm backdrop-blur">
      <div className="grid gap-5 p-5 md:grid-cols-[minmax(0,1fr)_auto] md:p-6">
        <div className="min-w-0">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-md border border-primary/20 bg-primary/10 px-2.5 py-1 text-xs font-semibold text-primary">
              <ShieldCheck className="h-3.5 w-3.5" />
              Current focus
            </span>
            <span className="rounded-md border border-border bg-secondary/35 px-2.5 py-1 text-xs text-muted-foreground">
              {mission.validation_status === "validation_pending" ? "Ready to verify in a later interview" : "Role readiness"}
            </span>
          </div>
          <h2 className="text-2xl font-semibold tracking-normal text-foreground md:text-3xl">{mission.title}</h2>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground">{mission.assignment_reason}</p>
          <div className="mt-4 flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
            <span className="inline-flex items-center gap-1.5">
              <CheckCircle2 className="h-4 w-4 text-primary" />
              Progress: {completed} of {total} steps
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Clock className="h-4 w-4 text-primary" />
              Estimated remaining practice: {remaining} minutes
            </span>
            <span className="inline-flex items-center gap-1.5">
              <ShieldCheck className="h-4 w-4 text-primary" />
              Prediction confidence: {confidence}% · {evidenceCount} evidence {evidenceCount === 1 ? "item" : "items"}
            </span>
          </div>
        </div>
        <div className="grid min-w-[280px] grid-cols-3 gap-2 self-start">
          <ScorePill label="Predicted" value={mission.current_readiness} large />
          <ScorePill label="Target" value={mission.target_readiness} large />
          <ScorePill label="Baseline" value={mission.baseline_readiness} large />
        </div>
      </div>
      <div className="h-1 bg-secondary">
        <div
          className="h-full bg-primary transition-all duration-700 ease-out"
          style={{ width: `${Math.max(2, Math.min(100, Number(mission.progress_percent || 0)))}%` }}
        />
      </div>
    </section>
  )
}

function ScorePill({
  label,
  value,
  large,
  signed,
}: {
  label: string
  value?: number | null
  large?: boolean
  signed?: boolean
}) {
  const numeric = Number(value || 0)
  return (
    <div className="rounded-lg border border-border bg-background/55 px-3 py-3 text-center">
      <p className="text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">{label}</p>
      <p className={cn("mt-1 font-semibold text-foreground transition-all duration-700", large ? "text-3xl" : "text-xl")}>
        {signed && numeric > 0 ? "+" : ""}
        {scoreLabel(numeric)}
      </p>
    </div>
  )
}

function MissionProgress({ mission }: { mission: ActiveImproveMission }) {
  return (
    <div className="min-w-[210px]">
      <div className="mb-1 flex items-center justify-between text-xs text-muted-foreground">
        <span>Plan progress</span>
        <span className="font-semibold text-foreground">{Math.round(mission.progress_percent || 0)}%</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-secondary">
        <div
          className="h-full rounded-full bg-primary transition-all duration-700"
          style={{ width: `${Math.max(3, Math.min(100, Number(mission.progress_percent || 0)))}%` }}
        />
      </div>
    </div>
  )
}

function SkillRoadmap({
  nodes,
  mission,
  currentNodeId,
  onInspect,
  onVerify,
}: {
  nodes: ImproveRoadmapNode[]
  mission: ActiveImproveMission
  currentNodeId: string | null
  onInspect: (node: ImproveRoadmapNode) => void
  onVerify: () => void
}) {
  const verificationReady = mission.validation_status === "validation_pending" && !currentNodeId
  return (
    <ol className="relative mx-auto max-w-3xl space-y-3 before:absolute before:left-5 before:top-4 before:h-[calc(100%-2rem)] before:w-px before:bg-border md:before:left-1/2">
      {nodes.map((node, index) => (
        <RoadmapNode
          key={node.roadmap_node_id}
          node={node}
          index={index}
          isCurrent={node.roadmap_node_id === currentNodeId}
          onInspect={() => onInspect(node)}
        />
      ))}
      <VerificationRoadmapNode
        index={nodes.length}
        mode={mission.mode === "technical" ? "technical" : "interview"}
        ready={verificationReady}
        verified={Boolean(mission.validated_by_interview_id) || mission.validation_status === "validated"}
        onVerify={onVerify}
      />
    </ol>
  )
}

function VerificationRoadmapNode({
  index,
  mode,
  ready,
  verified,
  onVerify,
}: {
  index: number
  mode: ImproveMode
  ready: boolean
  verified: boolean
  onVerify: () => void
}) {
  const technical = mode === "technical"
  return (
    <li className={cn("relative grid gap-3 md:grid-cols-[1fr_44px_1fr]", index % 2 === 1 && "md:[&>div:first-child]:order-3")}>
      <div className={cn("pl-12 md:pl-0", index % 2 === 0 ? "md:text-right" : "md:col-start-3")}>
        <button
          type="button"
          onClick={onVerify}
          disabled={!ready}
          className={cn(
            "w-full rounded-lg border p-3 text-left transition-all md:max-w-md",
            index % 2 === 0 && "md:ml-auto md:text-right",
            ready && "border-primary/45 bg-primary/10 hover:border-primary/70",
            verified && "border-emerald-500/35 bg-emerald-500/10",
            !ready && !verified && "border-border/50 bg-secondary/20 opacity-65",
          )}
          aria-current={ready ? "step" : undefined}
        >
          <div className={cn("flex items-center gap-2", index % 2 === 0 && "md:justify-end")}>
            <span className="text-xs font-medium text-muted-foreground">Step {index + 1}</span>
            <span className={cn(
              "rounded-md px-2 py-0.5 text-[11px] font-semibold",
              verified ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-300" : ready ? "bg-primary/15 text-primary" : "bg-secondary text-muted-foreground",
            )}>
              {verified ? "Verified" : ready ? "Ready now" : "After practice"}
            </span>
          </div>
          <h3 className="mt-1 text-sm font-semibold text-foreground">{technical ? "Retry in a Technical Round" : "Retry in an Interview Round"}</h3>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            {technical
              ? "Attempt a fresh technical round so the product can verify what improved and what still needs work."
              : "Take a fresh interview so the product can verify what improved and what still needs work."}
          </p>
        </button>
      </div>
      <div className="absolute left-0 top-3 z-10 flex h-10 w-10 items-center justify-center rounded-full border border-border bg-card text-muted-foreground md:static md:mx-auto">
        <span className={cn(
          "flex h-8 w-8 items-center justify-center rounded-full",
          verified ? "bg-emerald-500 text-white" : ready ? "bg-primary text-primary-foreground" : "bg-secondary text-muted-foreground",
        )}>
          {verified ? <BadgeCheck className="h-4 w-4" /> : ready ? <Play className="h-4 w-4" /> : <Lock className="h-4 w-4" />}
        </span>
      </div>
      <div className="hidden md:block" />
    </li>
  )
}

function RoadmapNode({
  node,
  index,
  isCurrent,
  onInspect,
}: {
  node: ImproveRoadmapNode
  index: number
  isCurrent: boolean
  onInspect: () => void
}) {
  const locked = node.availability_status === "locked" || node.availability_status === "blocked"
  const verified = node.mastery_status === "verified"
  const heldOutPassed = node.mastery_status === "held_out_passed"
  const needsReinforcement = node.mastery_status === "needs_reinforcement"
  const passed = node.result_status === "passed" || node.result_status === "strong_pass"
  const icon = locked ? (
    <Lock className="h-4 w-4" />
  ) : verified || heldOutPassed ? (
    <BadgeCheck className="h-4 w-4" />
  ) : needsReinforcement ? (
    <AlertTriangle className="h-4 w-4" />
  ) : passed ? (
    <Check className="h-4 w-4" />
  ) : isCurrent ? (
    <CircleDot className="h-4 w-4" />
  ) : (
    <Circle className="h-4 w-4" />
  )

  return (
    <li className={cn("relative grid gap-3 md:grid-cols-[1fr_44px_1fr]", index % 2 === 1 && "md:[&>div:first-child]:order-3")}>
      <div className={cn("pl-12 md:pl-0", index % 2 === 0 ? "md:text-right" : "md:col-start-3")}>
        <button
          type="button"
          onClick={onInspect}
          disabled={locked || !isCurrent}
          className={cn(
            "w-full rounded-lg border p-3 text-left transition-all md:max-w-md",
            index % 2 === 0 && "md:ml-auto md:text-right",
            locked && "border-border/50 bg-secondary/20 opacity-55",
            !locked && !isCurrent && "border-border/70 bg-background/45",
            isCurrent && "border-primary/45 bg-primary/10 shadow-[0_0_0_1px_rgba(99,102,241,0.15)]",
            !locked && isCurrent && "hover:border-primary/70",
          )}
          aria-current={isCurrent ? "step" : undefined}
        >
          <div className={cn("flex items-center gap-2", index % 2 === 0 && "md:justify-end")}>
            <span className="text-xs font-medium text-muted-foreground">Step {index + 1}</span>
            <span className={cn(
              "rounded-md px-2 py-0.5 text-[11px] font-semibold",
              verified || heldOutPassed ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-300" :
                needsReinforcement ? "bg-amber-500/10 text-amber-700 dark:text-amber-300" :
                  isCurrent ? "bg-primary/15 text-primary" :
                    "bg-secondary text-muted-foreground",
            )}>
              {nodeStateLabel(node)}
            </span>
          </div>
          <h3 className="mt-1 text-sm font-semibold text-foreground">{node.title}</h3>
          {isCurrent && (
            <p className="mt-1 text-xs leading-5 text-muted-foreground">{node.description || node.expected_result}</p>
          )}
        </button>
      </div>
      <div className="absolute left-0 top-3 z-10 flex h-10 w-10 items-center justify-center rounded-full border border-border bg-card text-muted-foreground md:static md:mx-auto">
        <span className={cn(
          "flex h-8 w-8 items-center justify-center rounded-full transition-all duration-500",
          verified || heldOutPassed || passed ? "bg-emerald-500 text-white" :
            needsReinforcement ? "bg-amber-500 text-white" :
              isCurrent ? "bg-primary text-primary-foreground shadow-md shadow-primary/20" :
                locked ? "bg-secondary text-muted-foreground" :
                  "bg-background text-muted-foreground",
        )}>
          {icon}
        </span>
      </div>
      <div className="hidden md:block" />
    </li>
  )
}

function CurrentActivityCard({
  mission,
  node,
  hasActiveSession,
  onStart,
  onVerify,
}: {
  mission: ActiveImproveMission
  node: ImproveRoadmapNode | null
  hasActiveSession: boolean
  onStart: () => void
  onVerify: () => void
}) {
  if (!node) {
    const awaitingInterview = mission.validation_status === "validation_pending"
    return (
      <section className="rounded-lg border border-border/70 bg-card/70 p-5">
        <p className="text-sm font-semibold text-foreground">{awaitingInterview ? "Practice checkpoint passed" : "Roadmap paused"}</p>
        <p className="mt-2 text-sm text-muted-foreground">
          {awaitingInterview
            ? "Complete a later comparable interview to verify whether this behaviour transfers under interview conditions."
            : "There is no current activity. Refresh after new interview evidence is analysed."}
        </p>
        {awaitingInterview && (
          <Button className="mt-5 w-full" onClick={onVerify}>
            {mission.mode === "technical" ? <Code className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
            {mission.mode === "technical" ? "Start verification Technical Round" : "Start verification Interview Round"}
          </Button>
        )}
      </section>
    )
  }
  const conditions = getPassConditionLabels(node)
  const hideHints = shouldHideHints(node)
  return (
    <section className="rounded-lg border border-primary/30 bg-card/85 p-5 shadow-sm shadow-primary/5 backdrop-blur">
      <div className="mb-3 flex items-center justify-between gap-3">
        <span className="inline-flex items-center gap-1.5 rounded-md border border-primary/20 bg-primary/10 px-2.5 py-1 text-xs font-semibold text-primary">
          <Target className="h-3.5 w-3.5" />
          Next best action
        </span>
        <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
          <Timer className="h-3.5 w-3.5" />
          {node.estimated_minutes} min
        </span>
      </div>
      <h2 className="text-xl font-semibold text-foreground">{node.title}</h2>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">{node.description}</p>
      <div className="mt-4 space-y-3 rounded-lg border border-border/70 bg-background/45 p-3">
        <InfoRow label="Activity" value={formatActivityType(node.activity_type)} />
        <InfoRow label="Skill trained" value={mission.skills.find((skill) => skill.mission_skill_id === node.mission_skill_id)?.label || "Interview answer clarity"} />
        <InfoRow label="Expected result" value={node.expected_result || "Meet the measurable pass conditions for this behaviour."} />
      </div>
      {!hideHints && conditions.length > 0 && (
        <div className="mt-4">
          <p className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">Pass conditions</p>
          <ul className="mt-2 space-y-1.5">
            {conditions.slice(0, 3).map((condition) => (
              <li key={condition} className="flex gap-2 text-sm text-muted-foreground">
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                <span>{condition}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {hideHints && (
        <div className="mt-4 rounded-lg border border-border/70 bg-secondary/20 p-3 text-sm text-muted-foreground">
          This is an unseen checkpoint. The structure, hints, and rubric stay hidden until after submission.
        </div>
      )}
      <Button className="mt-5 hidden h-11 w-full md:inline-flex" onClick={onStart}>
        <Play className="h-4 w-4" />
        {nextActionLabel(node, hasActiveSession)}
      </Button>
    </section>
  )
}

function MissionOutcomeSummary({ mission, onVerify }: { mission: ActiveImproveMission; onVerify: () => void }) {
  const improved = mission.skills.filter((skill) => Number(skill.latest_score) > Number(skill.baseline_score))
  const remaining = mission.skills.filter((skill) => (
    Number(skill.latest_score) < Number(skill.target_score)
    || !["verified", "held_out_passed"].includes(String(skill.mastery_status || ""))
  ))
  const verificationReady = mission.validation_status === "validation_pending"
  return (
    <section className="rounded-lg border border-border/70 bg-card/70 p-5 shadow-sm backdrop-blur">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-primary">Progress and next proof</p>
          <h2 className="mt-1 text-xl font-semibold text-foreground">What improved, what remains, and what happens next</h2>
        </div>
        {verificationReady && (
          <Button onClick={onVerify}>
            <Play className="h-4 w-4" />
            {mission.mode === "technical" ? "Take Technical Round again" : "Take Interview Round again"}
          </Button>
        )}
      </div>
      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-emerald-500/25 bg-emerald-500/5 p-4">
          <p className="flex items-center gap-2 text-sm font-semibold text-foreground"><Sparkles className="h-4 w-4 text-emerald-500" /> Improved in practice</p>
          <ul className="mt-3 space-y-2">
            {(improved.length ? improved : mission.skills.slice(0, 1)).map((skill) => (
              <li key={skill.mission_skill_id} className="flex items-start justify-between gap-3 text-sm">
                <span className="text-muted-foreground">{skill.label}</span>
                <span className="shrink-0 font-semibold text-emerald-600 dark:text-emerald-300">{scoreLabel(skill.baseline_score)} → {scoreLabel(skill.latest_score)}</span>
              </li>
            ))}
          </ul>
          {!improved.length && <p className="mt-3 text-xs text-muted-foreground">Complete the current practice steps to record an improvement signal.</p>}
        </div>
        <div className="rounded-lg border border-amber-500/25 bg-amber-500/5 p-4">
          <p className="flex items-center gap-2 text-sm font-semibold text-foreground"><Target className="h-4 w-4 text-amber-500" /> Remaining to prove</p>
          <ul className="mt-3 space-y-2">
            {(remaining.length ? remaining : mission.skills.slice(0, 1)).map((skill) => (
              <li key={skill.mission_skill_id} className="flex items-start justify-between gap-3 text-sm">
                <span className="text-muted-foreground">{skill.label}</span>
                <span className="shrink-0 font-semibold text-amber-700 dark:text-amber-300">Target {scoreLabel(skill.target_score)}</span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs leading-5 text-muted-foreground">
            {verificationReady
              ? `Practice is complete. The next ${mission.mode === "technical" ? "Technical Round" : "Interview Round"} will confirm which gains transfer under real round conditions.`
              : "Finish the remaining roadmap steps first; the final step is a fresh official round."}
          </p>
        </div>
      </div>
    </section>
  )
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid gap-1 sm:grid-cols-[110px_1fr]">
      <p className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">{label}</p>
      <p className="text-sm leading-5 text-foreground">{value}</p>
    </div>
  )
}

function EvidenceDrawer({ mission, node }: { mission: ActiveImproveMission; node: ImproveRoadmapNode | null }) {
  const evidence = node?.evidence || {}
  const promptEvidence = getActivityPrompt(node).source_evidence
  const excerpt = Array.isArray(promptEvidence) && promptEvidence[0]?.answer_excerpt
    ? String(promptEvidence[0].answer_excerpt)
    : String(evidence.summary || mission.assignment_reason || "")
  return (
    <details className="group rounded-lg border border-border/70 bg-card/70 p-4 backdrop-blur">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-foreground">Why was this assigned?</p>
          <p className="mt-1 text-xs text-muted-foreground">Interview evidence and expected behaviour</p>
        </div>
        <ChevronRight className="h-4 w-4 text-muted-foreground transition-transform group-open:rotate-90" />
      </summary>
      <div className="mt-4 space-y-3">
        <EvidenceBlock label="Relevant transcript excerpt" value={excerpt || "Interview evidence is unavailable for this node. The roadmap remains usable, but evidence should be regenerated after the next interview."} />
        <EvidenceBlock label="Detected issue" value={node?.description || mission.assignment_reason} />
        <EvidenceBlock label="Effect on the answer" value="The interviewer cannot separate the problem, your ownership, and the result quickly enough." />
        <EvidenceBlock label="Expected behaviour" value={node?.expected_result || "Answer with the specific behaviour trained by this node."} />
      </div>
    </details>
  )
}

function EvidenceBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border/70 bg-background/45 p-3">
      <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{label}</p>
      <p className="mt-1 text-sm leading-6 text-foreground">{value}</p>
    </div>
  )
}

function ActivityShell({
  mission,
  node,
  activeSession,
  onClose,
  onLearningRefresh,
}: {
  mission: ActiveImproveMission
  node: ImproveRoadmapNode
  activeSession?: ImproveAttemptSession | null
  onClose: () => void
  onLearningRefresh?: () => Promise<void> | void
}) {
  const [phase, setPhase] = useState<ActivityPhase>(activeSession ? "during" : "before")
  const [draft, setDraft] = useState<ActivityDraft>(() => draftFromSession(activeSession, node))
  const [attemptSession, setAttemptSession] = useState<ImproveAttemptSession | null>(activeSession || null)
  const [idempotencyKey, setIdempotencyKey] = useState(activeSession?.idempotency_key || createAttemptKey())
  const [isStarting, setIsStarting] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [saveError, setSaveError] = useState("")
  const [submitError, setSubmitError] = useState("")
  const [result, setResult] = useState<ExerciseAttemptResult | null>(null)
  const prompt = getActivityPrompt(node)
  const timerSeconds = Number(prompt.timer_seconds || node.estimated_minutes * 60 || 0)
  const [secondsLeft, setSecondsLeft] = useState<number | null>(() => sessionSecondsRemaining(activeSession, timerSeconds))
  const lastSavedDraft = useRef(JSON.stringify(draftFromSession(activeSession, node)))
  const resumedSessionRef = useRef("")
  const hideHints = shouldHideHints(node)
  const conditions = getPassConditionLabels(node)
  const submittable = isDraftSubmittable(node, draft)
  const timeExpired = secondsLeft === 0

  useEffect(() => {
    if (!activeSession || phase !== "during" || resumedSessionRef.current === activeSession.attempt_session_id) return
    resumedSessionRef.current = activeSession.attempt_session_id
    void (async () => {
      try {
        const resumed = await updateExerciseAttemptSession(node.exercise_id || "", activeSession.attempt_session_id, {
          mission_id: mission.mission_id,
          roadmap_node_id: node.roadmap_node_id,
          idempotency_key: activeSession.idempotency_key,
          status: "in_progress",
          draft_payload: normalizeDraftForPersistence(draft),
        })
        setAttemptSession(resumed)
        setIdempotencyKey(resumed.idempotency_key)
        setSecondsLeft(sessionSecondsRemaining(resumed, timerSeconds))
        lastSavedDraft.current = JSON.stringify(draft)
        setSaveError("")
      } catch (error) {
        setSaveError(error instanceof Error ? error.message : "This saved attempt can no longer be resumed.")
        setSecondsLeft(0)
      }
    })()
  }, [activeSession, draft, node.exercise_id, phase, timerSeconds])

  useEffect(() => {
    if (phase !== "during" || !timerSeconds || secondsLeft === null) return
    if (secondsLeft <= 0) return
    const timer = window.setTimeout(() => setSecondsLeft((value) => value === null ? null : Math.max(0, value - 1)), 1000)
    return () => window.clearTimeout(timer)
  }, [phase, secondsLeft, timerSeconds])

  useEffect(() => {
    if (phase !== "during" || !attemptSession) return
    const serialized = JSON.stringify(draft)
    if (serialized === lastSavedDraft.current) return
    const timer = window.setTimeout(async () => {
      try {
        const payload = normalizeDraftForPersistence(draft)
        const session = await updateExerciseAttemptSession(node.exercise_id || "", attemptSession.attempt_session_id, {
          mission_id: mission.mission_id,
          roadmap_node_id: node.roadmap_node_id,
          idempotency_key: attemptSession.idempotency_key,
          status: "in_progress",
          draft_payload: payload,
        })
        lastSavedDraft.current = serialized
        setAttemptSession(session)
        setSaveError("")
      } catch (error) {
        setSaveError(error instanceof Error ? error.message : "Draft could not be saved.")
      }
    }, 650)
    return () => window.clearTimeout(timer)
  }, [attemptSession, draft, node.exercise_id, phase])

  const beginAttempt = async () => {
    if (!node.exercise_id) return
    setIsStarting(true)
    setSaveError("")
    try {
      const existingSession = attemptSession && attemptSession.roadmap_node_id === node.roadmap_node_id ? attemptSession : null
      const session = existingSession
        ? await updateExerciseAttemptSession(node.exercise_id, existingSession.attempt_session_id, {
            mission_id: mission.mission_id,
            roadmap_node_id: node.roadmap_node_id,
            idempotency_key: existingSession.idempotency_key,
            status: "in_progress",
            draft_payload: normalizeDraftForPersistence(draft),
          })
        : await createExerciseAttemptSession(node.exercise_id, {
            mission_id: mission.mission_id,
            roadmap_node_id: node.roadmap_node_id,
            idempotency_key: idempotencyKey,
            draft_payload: normalizeDraftForPersistence(draft),
          })
      setAttemptSession(session)
      setIdempotencyKey(session.idempotency_key || idempotencyKey)
      setDraft(draftFromSession(session, node))
      lastSavedDraft.current = JSON.stringify(draftFromSession(session, node))
      setSecondsLeft(sessionSecondsRemaining(session, timerSeconds))
      setPhase("during")
      await onLearningRefresh?.()
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : "Could not start a persisted attempt.")
    } finally {
      setIsStarting(false)
    }
  }

  const retryAttempt = async () => {
    const nextKey = createAttemptKey()
    setIdempotencyKey(nextKey)
    setAttemptSession(null)
    setResult(null)
    setSecondsLeft(null)
    setSubmitError("")
    setSaveError("")
    setPhase("before")
  }

  const restartExpiredAttempt = async () => {
    if (attemptSession && node.exercise_id) {
      try {
        await updateExerciseAttemptSession(node.exercise_id, attemptSession.attempt_session_id, {
          mission_id: mission.mission_id,
          roadmap_node_id: node.roadmap_node_id,
          idempotency_key: attemptSession.idempotency_key,
          status: "abandoned",
          draft_payload: normalizeDraftForPersistence(draft),
        })
      } catch {
        // An already-expired session is intentionally no longer mutable.
      }
    }
    const nextKey = createAttemptKey()
    setIdempotencyKey(nextKey)
    setAttemptSession(null)
    setSecondsLeft(null)
    setSaveError("")
    setSubmitError("")
    setPhase("before")
    await onLearningRefresh?.()
  }

  const submitAttempt = async () => {
    if (!node.exercise_id || !attemptSession || !submittable || timeExpired || isSubmitting) return
    setIsSubmitting(true)
    setSubmitError("")
    try {
      const payload = buildActivityAttemptPayload(node, draft, mission.mission_id, idempotencyKey, attemptSession.attempt_session_id)
      const response = await submitExerciseAttempt(node.exercise_id, payload)
      setResult(response)
      setPhase("feedback")
      await onLearningRefresh?.()
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : "Attempt could not be saved.")
    } finally {
      setIsSubmitting(false)
    }
  }

  const closeActivity = async () => {
    if (phase === "during" && attemptSession && node.exercise_id) {
      try {
        await updateExerciseAttemptSession(node.exercise_id, attemptSession.attempt_session_id, {
          mission_id: mission.mission_id,
          roadmap_node_id: node.roadmap_node_id,
          idempotency_key: attemptSession.idempotency_key,
          status: "draft",
          draft_payload: normalizeDraftForPersistence(draft),
        })
        await onLearningRefresh?.()
      } catch {
        setSaveError("The latest draft could not be confirmed. Keep this window open and try again.")
        return
      }
    }
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 p-3 backdrop-blur-sm md:p-6" role="dialog" aria-modal="true">
      <section className="flex max-h-[92vh] w-full max-w-4xl flex-col overflow-hidden rounded-lg border border-border bg-card shadow-2xl">
        <div className="flex items-center justify-between border-b border-border px-4 py-3 md:px-5">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-[0.12em] text-primary">{formatActivityType(node.activity_type)}</p>
            <h2 className="truncate text-lg font-semibold text-foreground">{node.title}</h2>
          </div>
          <Button variant="ghost" size="icon" onClick={() => void closeActivity()} aria-label="Close activity">
            <X className="h-4 w-4" />
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-4 md:p-6">
          {phase === "before" && (
            <BeforeAttempt
              node={node}
              conditions={conditions}
              hideHints={hideHints}
              saveError={saveError}
              isStarting={isStarting}
              onStart={beginAttempt}
            />
          )}
          {phase === "during" && (
            <DuringAttempt
              node={node}
              draft={draft}
              setDraft={setDraft}
              saveError={saveError}
              submitError={submitError}
              secondsLeft={secondsLeft}
              isSubmitting={isSubmitting}
              submittable={submittable && !timeExpired}
              timeExpired={timeExpired}
              onSubmit={submitAttempt}
              onRestart={() => void restartExpiredAttempt()}
            />
          )}
          {phase === "feedback" && result && (
            <FocusedFeedback
              result={result}
              node={node}
              onRetry={retryAttempt}
              onContinue={onClose}
            />
          )}
        </div>
      </section>
    </div>
  )
}

function normalizeDraftForPersistence(draft: ActivityDraft): Record<string, unknown> {
  return {
    selected_option: draft.selectedOption || "",
    reason: draft.reason || "",
    block_order: draft.blockOrder || [],
    rewrite: draft.rewrite || "",
    transcript: draft.transcript || "",
    answer: draft.answer || "",
  }
}

function BeforeAttempt({
  node,
  conditions,
  hideHints,
  saveError,
  isStarting,
  onStart,
}: {
  node: ImproveRoadmapNode
  conditions: string[]
  hideHints: boolean
  saveError: string
  isStarting: boolean
  onStart: () => void
}) {
  const prompt = getActivityPrompt(node)
  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-5">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-primary">Before attempt</p>
        <h3 className="mt-1 text-2xl font-semibold text-foreground">{prompt.title || node.title}</h3>
        <p className="mt-3 text-base leading-7 text-foreground">{prompt.question || node.description}</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <InfoBlock icon={<Target className="h-4 w-4" />} label="Skill goal" value={node.expected_result || "Demonstrate the targeted interview behaviour."} />
        <InfoBlock icon={<Clock className="h-4 w-4" />} label="Time" value={`${node.estimated_minutes} minutes`} />
      </div>
      {!hideHints && conditions.length > 0 && (
        <div className="rounded-lg border border-border bg-background/55 p-4">
          <p className="text-sm font-semibold text-foreground">Pass conditions</p>
          <ul className="mt-3 space-y-2">
            {conditions.slice(0, 3).map((condition) => (
              <li key={condition} className="flex gap-2 text-sm text-muted-foreground">
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                <span>{condition}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {hideHints && (
        <div className="rounded-lg border border-border bg-background/55 p-4 text-sm leading-6 text-muted-foreground">
          No hints, model answer, or rubric will appear before submission. This checkpoint verifies transfer to a fresh situation.
        </div>
      )}
      {saveError && <ErrorBanner message={saveError} />}
      <div>
        <Button className="h-11 px-6" onClick={onStart} disabled={isStarting}>
          {isStarting ? <RotateCcw className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
          Start
        </Button>
      </div>
    </div>
  )
}

function InfoBlock({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-background/55 p-4">
      <div className="mb-2 flex items-center gap-2 text-primary">{icon}<span className="text-xs font-semibold uppercase tracking-[0.08em]">{label}</span></div>
      <p className="text-sm leading-6 text-foreground">{value}</p>
    </div>
  )
}

function DuringAttempt({
  node,
  draft,
  setDraft,
  saveError,
  submitError,
  secondsLeft,
  isSubmitting,
  submittable,
  timeExpired,
  onSubmit,
  onRestart,
}: {
  node: ImproveRoadmapNode
  draft: ActivityDraft
  setDraft: (draft: ActivityDraft) => void
  saveError: string
  submitError: string
  secondsLeft: number | null
  isSubmitting: boolean
  submittable: boolean
  timeExpired: boolean
  onSubmit: () => void
  onRestart: () => void
}) {
  const prompt = getActivityPrompt(node)
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-primary">Attempt in progress</p>
          <h3 className="mt-1 text-2xl font-semibold text-foreground">{prompt.question || prompt.prompt || node.title}</h3>
        </div>
        {secondsLeft !== null && (
          <div className={cn(
            "inline-flex shrink-0 items-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold",
            secondsLeft <= 10 ? "border-destructive/40 bg-destructive/10 text-destructive" : "border-border bg-background/55 text-foreground",
          )}>
            <Timer className="h-4 w-4" />
            {Math.floor(secondsLeft / 60)}:{String(secondsLeft % 60).padStart(2, "0")}
          </div>
        )}
      </div>
      <ActivityBody node={node} draft={draft} setDraft={setDraft} />
      {saveError && <ErrorBanner message={`Draft save issue: ${saveError}`} />}
      {submitError && <ErrorBanner message={submitError} />}
      {timeExpired && (
        <div className="flex flex-col gap-3 rounded-lg border border-amber-500/30 bg-amber-500/10 p-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-amber-800 dark:text-amber-200">Time expired. This attempt cannot be submitted; start a fresh timed attempt.</p>
          <Button type="button" variant="outline" onClick={onRestart}>
            <RotateCcw className="h-4 w-4" />
            Restart
          </Button>
        </div>
      )}
      <div className="flex flex-col gap-2 border-t border-border pt-4 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-xs text-muted-foreground">Drafts are saved to your improvement history while this attempt is active.</p>
        <Button className="h-10 sm:min-w-[160px]" disabled={!submittable || isSubmitting} onClick={onSubmit}>
          {isSubmitting ? <RotateCcw className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
          Submit attempt
        </Button>
      </div>
    </div>
  )
}

function ActivityBody({
  node,
  draft,
  setDraft,
}: {
  node: ImproveRoadmapNode
  draft: ActivityDraft
  setDraft: (draft: ActivityDraft) => void
}) {
  if (node.activity_type === "compare_answers") return <CompareAnswersActivity node={node} draft={draft} setDraft={setDraft} />
  if (node.activity_type === "arrange_blocks") return <ArrangeBlocksActivity node={node} draft={draft} setDraft={setDraft} />
  if (node.activity_type === "rewrite_answer") return <RewriteAnswerActivity node={node} draft={draft} setDraft={setDraft} />
  if (node.activity_type === "guided_spoken_response") return <SpokenResponseActivity node={node} draft={draft} setDraft={setDraft} />
  return <CheckpointActivity node={node} draft={draft} setDraft={setDraft} />
}

function CompareAnswersActivity({
  node,
  draft,
  setDraft,
}: {
  node: ImproveRoadmapNode
  draft: ActivityDraft
  setDraft: (draft: ActivityDraft) => void
}) {
  const prompt = getActivityPrompt(node)
  const answers = Array.isArray(prompt.answers) ? prompt.answers : []
  const learningGuide = Array.isArray(prompt.learning_guide) ? prompt.learning_guide : []
  return (
    <div className="space-y-4">
      {learningGuide.length > 0 && (
        <div className="rounded-lg border border-primary/25 bg-primary/5 p-4">
          <p className="text-sm font-semibold text-foreground">Use this repair path</p>
          <ol className="mt-3 grid gap-3 sm:grid-cols-2">
            {learningGuide.map((step: any, index: number) => (
              <li key={`${String(step.label || "step")}-${index}`} className="flex gap-3 rounded-md border border-border/70 bg-background/70 p-3">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">{index + 1}</span>
                <div>
                  <p className="text-sm font-semibold text-foreground">{String(step.label || `Step ${index + 1}`)}</p>
                  <p className="mt-1 text-sm leading-5 text-muted-foreground">{String(step.text || "")}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      )}
      <div className="grid gap-3 md:grid-cols-2">
        {answers.map((answer: any) => {
          const selected = draft.selectedOption === String(answer.id)
          return (
            <button
              key={String(answer.id)}
              type="button"
              onClick={() => setDraft({ ...draft, selectedOption: String(answer.id) })}
              className={cn(
                "rounded-lg border p-4 text-left transition-all",
                selected ? "border-primary bg-primary/10 shadow-sm shadow-primary/10" : "border-border bg-background/55 hover:border-primary/50",
              )}
              aria-pressed={selected}
            >
              <p className="text-sm font-semibold text-foreground">{answer.label || `Answer ${String(answer.id).toUpperCase()}`}</p>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">{answer.text}</p>
            </button>
          )
        })}
      </div>
      {draft.selectedOption && (
        <div className="rounded-lg border border-border bg-background/55 p-4">
          <label className="text-sm font-semibold text-foreground" htmlFor="compare-reason">Why is this stronger?</label>
          <Textarea
            id="compare-reason"
            className="mt-2 min-h-28"
            value={draft.reason || ""}
            onChange={(event) => setDraft({ ...draft, reason: event.target.value })}
            placeholder="Explain the behaviour being trained, such as problem-first structure or separating purpose from technologies."
          />
        </div>
      )}
    </div>
  )
}

function ArrangeBlocksActivity({
  node,
  draft,
  setDraft,
}: {
  node: ImproveRoadmapNode
  draft: ActivityDraft
  setDraft: (draft: ActivityDraft) => void
}) {
  const prompt = getActivityPrompt(node)
  const blocks = Array.isArray(prompt.blocks) ? prompt.blocks : []
  const order = draft.blockOrder?.length ? draft.blockOrder : blocks.map((block: any) => String(block.id))
  const byId = new Map(blocks.map((block: any) => [String(block.id), block]))

  const move = (index: number, direction: -1 | 1) => {
    const next = [...order]
    const target = index + direction
    if (target < 0 || target >= next.length) return
    const current = next[index]
    next[index] = next[target]
    next[target] = current
    setDraft({ ...draft, blockOrder: next })
  }

  return (
    <div className="space-y-3">
      {order.map((id, index) => {
        const block = byId.get(id)
        return (
          <div key={id} className="flex gap-3 rounded-lg border border-border bg-background/55 p-3">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-secondary text-sm font-semibold text-foreground">{index + 1}</div>
            <p className="min-w-0 flex-1 text-sm leading-6 text-foreground">{block?.text || id}</p>
            <div className="flex shrink-0 gap-1">
              <Button type="button" variant="outline" size="icon-sm" onClick={() => move(index, -1)} disabled={index === 0} aria-label="Move block up">
                <ArrowUp className="h-3.5 w-3.5" />
              </Button>
              <Button type="button" variant="outline" size="icon-sm" onClick={() => move(index, 1)} disabled={index === order.length - 1} aria-label="Move block down">
                <ArrowDown className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function RewriteAnswerActivity({
  node,
  draft,
  setDraft,
}: {
  node: ImproveRoadmapNode
  draft: ActivityDraft
  setDraft: (draft: ActivityDraft) => void
}) {
  const prompt = getActivityPrompt(node)
  return (
    <div className="grid gap-4">
      <div className="rounded-lg border border-border bg-background/55 p-4">
        <p className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">Weak sentence from your answer</p>
        <p className="mt-2 text-lg font-medium text-foreground">{prompt.weak_answer || "We built the project."}</p>
      </div>
      <div>
        <label className="text-sm font-semibold text-foreground" htmlFor="rewrite-answer">Rewrite with exact ownership</label>
        <Textarea
          id="rewrite-answer"
          className="mt-2 min-h-40"
          value={draft.rewrite || ""}
          onChange={(event) => setDraft({ ...draft, rewrite: event.target.value })}
          placeholder="Example shape: I owned..., I chose..., which resulted in..."
        />
      </div>
    </div>
  )
}

function SpokenResponseActivity({
  node,
  draft,
  setDraft,
}: {
  node: ImproveRoadmapNode
  draft: ActivityDraft
  setDraft: (draft: ActivityDraft) => void
}) {
  return (
    <SpokenCapture
      label="Transcript"
      value={draft.transcript || ""}
      onChange={(value) => setDraft({ ...draft, transcript: value })}
      placeholder="Your spoken transcript appears here. If microphone transcription is unavailable, type the answer you spoke."
    />
  )
}

function CheckpointActivity({
  node,
  draft,
  setDraft,
}: {
  node: ImproveRoadmapNode
  draft: ActivityDraft
  setDraft: (draft: ActivityDraft) => void
}) {
  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-border bg-secondary/25 p-4 text-sm leading-6 text-muted-foreground">
        This checkpoint is unseen. Answer directly without opening the structure or rubric.
      </div>
      <SpokenCapture
        label="Checkpoint answer"
        value={draft.answer || draft.transcript || ""}
        onChange={(value) => setDraft({ ...draft, answer: value, transcript: value })}
        placeholder="Answer the checkpoint question here or use the microphone."
      />
    </div>
  )
}

function SpokenCapture({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  placeholder: string
}) {
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null)
  const [isRecording, setIsRecording] = useState(false)
  const [micError, setMicError] = useState("")

  const toggleRecording = () => {
    if (isRecording) {
      recognitionRef.current?.stop()
      setIsRecording(false)
      return
    }
    const Recognition = typeof window !== "undefined" ? (window.SpeechRecognition || window.webkitSpeechRecognition) : undefined
    if (!Recognition) {
      setMicError("Microphone transcription is unavailable in this browser. Type the transcript after speaking.")
      return
    }
    const recognition = new Recognition()
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = "en-US"
    recognition.onresult = (event: any) => {
      let transcript = ""
      for (let index = 0; index < event.results.length; index += 1) {
        transcript += event.results[index][0]?.transcript || ""
      }
      onChange(transcript.trim())
    }
    recognition.onerror = () => {
      setMicError("Microphone transcription stopped. You can continue by typing the transcript.")
      setIsRecording(false)
    }
    recognition.onend = () => setIsRecording(false)
    recognitionRef.current = recognition
    setMicError("")
    setIsRecording(true)
    recognition.start()
  }

  useEffect(() => {
    return () => recognitionRef.current?.abort()
  }, [])

  return (
    <div className="rounded-lg border border-border bg-background/55 p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <label className="text-sm font-semibold text-foreground" htmlFor="spoken-transcript">{label}</label>
        <Button
          type="button"
          variant={isRecording ? "default" : "outline"}
          size="sm"
          onClick={toggleRecording}
          aria-pressed={isRecording}
          aria-label={isRecording ? "Stop recording" : "Start microphone transcript"}
          className={cn(isRecording && "animate-pulse")}
        >
          <Mic className="h-4 w-4" />
          {isRecording ? "Recording" : "Mic"}
        </Button>
      </div>
      <Textarea
        id="spoken-transcript"
        className="min-h-44"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
      />
      {micError && <p className="mt-2 text-xs text-amber-600 dark:text-amber-300">{micError}</p>}
    </div>
  )
}

function FocusedFeedback({
  result,
  node,
  onRetry,
  onContinue,
}: {
  result: ExerciseAttemptResult
  node: ImproveRoadmapNode
  onRetry: () => void
  onContinue: () => void
}) {
  const formatted = formatAttemptResult(result)
  const failed = result.result_status === "failed"
  const partial = result.result_status === "partial_pass"
  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-5">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-primary">After attempt</p>
        <h3 className="mt-1 text-2xl font-semibold text-foreground">{formatted.headline}</h3>
        <p className="mt-2 text-sm text-muted-foreground">Score: {scoreLabel(result.score)} · {String(result.result_status || "").replace(/_/g, " ")}</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-4">
          <p className="text-sm font-semibold text-emerald-700 dark:text-emerald-300">Done correctly</p>
          <ul className="mt-3 space-y-2">
            {(formatted.passed.length ? formatted.passed : ["No pass condition was met yet."]).slice(0, 3).map((item) => (
              <li key={item} className="flex gap-2 text-sm text-foreground">
                <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-4">
          <p className="text-sm font-semibold text-amber-700 dark:text-amber-300">Needs focus</p>
          <ul className="mt-3 space-y-2">
            {(formatted.failed.length ? formatted.failed : ["No targeted miss detected."]).slice(0, 2).map((item) => (
              <li key={item} className="flex gap-2 text-sm text-foreground">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
      <div className="rounded-lg border border-border bg-background/55 p-4">
        <p className="text-sm font-semibold text-foreground">One change for the next attempt</p>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">{formatted.correction}</p>
        {failed && (
          <p className="mt-3 text-sm leading-6 text-muted-foreground">
            You know the material, but this behaviour is not stable yet. A short recovery activity has been added before the next node.
          </p>
        )}
      </div>
      <details className="rounded-lg border border-border bg-background/45 p-4">
        <summary className="cursor-pointer text-sm font-semibold text-foreground">Detailed condition evidence</summary>
        <div className="mt-3 space-y-2">
          {(result.condition_results || []).map((condition, index) => (
            <div key={`${condition.id || index}`} className="flex gap-2 text-sm text-muted-foreground">
              {condition.met ? <Check className="mt-0.5 h-4 w-4 text-emerald-600" /> : <AlertTriangle className="mt-0.5 h-4 w-4 text-amber-600" />}
              <span>{condition.label || condition.id}: {condition.evidence || (condition.met ? "Met" : "Not met")}</span>
            </div>
          ))}
        </div>
      </details>
      <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
        {partial && (
          <Button variant="outline" onClick={onRetry}>
            <RotateCcw className="h-4 w-4" />
            Retry focused attempt
          </Button>
        )}
        {!result.mastery_passed && !partial && (
          <Button variant="outline" onClick={onContinue}>
            <Unlock className="h-4 w-4" />
            Continue to recovery
          </Button>
        )}
        {result.mastery_passed && (
          <Button onClick={onContinue}>
            <ChevronRight className="h-4 w-4" />
            {node.activity_type === "unseen_checkpoint" ? "Return to roadmap" : "Continue to variation"}
          </Button>
        )}
        {node.activity_type === "unseen_checkpoint" && result.mastery_passed && (
          <span className="inline-flex items-center justify-center gap-1.5 rounded-md border border-emerald-500/25 bg-emerald-500/10 px-3 py-2 text-sm font-semibold text-emerald-700 dark:text-emerald-300">
            <BadgeCheck className="h-4 w-4" />
            Held-out passed · awaiting later interview
          </span>
        )}
      </div>
    </div>
  )
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm leading-6 text-destructive">
      {message}
    </div>
  )
}

function ImprovementHistorySection({ history }: { history?: ImprovementHistory | null }) {
  if (!historyHasRealData(history)) {
    return null
  }

  return (
    <section className="rounded-lg border border-border/70 bg-card/70 p-5 shadow-sm backdrop-blur">
      <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-primary">Your Progress</p>
          <h2 className="text-xl font-semibold text-foreground">Improvement history</h2>
        </div>
      </div>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(280px,0.8fr)]">
        <div className="space-y-3">
          {(history?.skills || []).slice(0, 5).map((skill) => (
            <div key={`${skill.skill_key}-${skill.label}`} className="rounded-lg border border-border bg-background/45 p-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <h3 className="text-sm font-semibold text-foreground">{skill.label}</h3>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {skill.attempt_count} previous attempt{skill.attempt_count === 1 ? "" : "s"} · {skill.verification_status.replace(/_/g, " ")}
                  </p>
                </div>
                <div className="flex gap-2 text-center">
                  <MiniMetric label="Baseline" value={skill.baseline_score} />
                  <MiniMetric label="Latest" value={skill.latest_score} />
                  <MiniMetric label="Change" value={skill.improvement} signed />
                </div>
              </div>
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-secondary">
                <div className="h-full rounded-full bg-primary transition-all duration-700" style={{ width: `${Math.max(3, Math.min(100, skill.latest_score))}%` }} />
              </div>
            </div>
          ))}
        </div>
        <div className="space-y-3">
          <div className="rounded-lg border border-border bg-background/45 p-4">
            <h3 className="text-sm font-semibold text-foreground">Checkpoint results</h3>
            <div className="mt-3 space-y-2">
              {(history?.recent_attempts || []).filter((attempt) => attempt.is_checkpoint).slice(0, 4).map((attempt) => (
                <div key={attempt.attempt_id} className="flex items-center justify-between gap-3 rounded-md bg-secondary/30 px-3 py-2 text-sm">
                  <span className="truncate text-muted-foreground">{formatActivityType(attempt.activity_type)}</span>
                  <span className={cn("font-semibold", attempt.passed ? "text-emerald-600 dark:text-emerald-300" : "text-amber-600 dark:text-amber-300")}>
                    {scoreLabel(attempt.score)}
                  </span>
                </div>
              ))}
              {!(history?.recent_attempts || []).some((attempt) => attempt.is_checkpoint) && (
                <p className="text-sm text-muted-foreground">No checkpoint has been submitted yet.</p>
              )}
            </div>
          </div>
          <div className="rounded-lg border border-border bg-background/45 p-4">
            <h3 className="text-sm font-semibold text-foreground">Completed missions</h3>
            <div className="mt-3 space-y-2">
              {(history?.completed_missions || []).slice(0, 3).map((mission) => (
                <div key={mission.mission_id} className="rounded-md bg-secondary/30 px-3 py-2">
                  <p className="truncate text-sm font-medium text-foreground">{mission.title}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {scoreLabel(mission.baseline_readiness)} → {scoreLabel(mission.current_readiness)} · +{scoreLabel(mission.improvement)}
                  </p>
                </div>
              ))}
              {!(history?.completed_missions || []).length && (
                <p className="text-sm text-muted-foreground">No completed mission yet.</p>
              )}
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

function MiniMetric({ label, value, signed }: { label: string; value: number; signed?: boolean }) {
  return (
    <div className="min-w-16 rounded-md border border-border bg-card px-2 py-1.5">
      <p className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">{label}</p>
      <p className="text-sm font-semibold text-foreground">{signed && value > 0 ? "+" : ""}{scoreLabel(value)}</p>
    </div>
  )
}
