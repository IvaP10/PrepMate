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
  Clock,
  Code,
  ExternalLink,
  Lock,
  MessageSquare,
  Mic,
  Play,
  RotateCcw,
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
  formatAttemptResult,
  getActivityPrompt,
  getCurrentRoadmapNode,
  getPassConditionLabels,
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

  const changeMode = (mode: ImproveMode) => {
    setActiveMode(mode)
    setActivityNode(null)
    setStartFromSession(false)
    setNavigationError("")
  }

  if (!learning && loading) {
    return (
      <main className="w-full px-4 py-6 md:px-8">
        <div className="mx-auto flex max-w-6xl flex-col gap-4">
          <div className="h-28 animate-pulse rounded-lg border border-border/70 bg-card/70" />
          <div className="h-[520px] animate-pulse rounded-lg border border-border/70 bg-card/60" />
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
        <div className="mx-auto flex max-w-6xl flex-col gap-5">
          <ImproveModeSwitch activeMode={activeMode} onChange={changeMode} />
          {navigationError && <ErrorBanner message={navigationError} />}
          <EmptyImproveState
            setActiveNav={setActiveNav}
            history={filterHistoryForMode(learning.improvement_history, activeMode)}
            activeMode={activeMode}
            analysisAvailability={learning.analysis_availability}
          />
        </div>
      </main>
    )
  }

  const completedSteps = completedRoadmapSteps(mission)
  const totalSteps = mission.roadmap.length + 1

  return (
    <main className="w-full px-4 py-6 md:px-8">
      <div className="mx-auto flex max-w-6xl flex-col gap-5">
        <ImproveModeSwitch activeMode={activeMode} onChange={changeMode} />
        {navigationError && <ErrorBanner message={navigationError} />}
        <section className="min-w-0">
          <div className="rounded-2xl bg-primary px-5 py-5 text-primary-foreground shadow-[0_7px_0_rgba(79,70,229,0.28)] md:px-6">
            <div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-xs font-bold uppercase tracking-[0.14em] text-primary-foreground/75">
                {activeMode === "technical" ? "Technical learning path" : "Interview learning path"}
                </p>
                <h2 className="mt-1 text-xl font-bold tracking-tight md:text-2xl">
                  {missionPathTitle(mission.title, activeMode)}
                </h2>
              </div>
              <div className="w-full sm:w-56">
                <div className="mb-2 flex items-center justify-between text-xs font-semibold text-primary-foreground/80">
                  <span>Path progress</span>
                  <span>{completedSteps} / {totalSteps}</span>
                </div>
                <div className="h-2.5 overflow-hidden rounded-full bg-black/15">
                  <div
                    className="h-full rounded-full bg-white transition-all duration-700"
                    style={{ width: `${Math.max(4, Math.min(100, Number(mission.progress_percent || 0)))}%` }}
                  />
                </div>
              </div>
            </div>
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
      </div>
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
      <section className="rounded-2xl border border-border/70 bg-card/75 p-6 shadow-sm backdrop-blur">
        <p className="text-xs font-bold uppercase tracking-[0.12em] text-primary">Mission completed</p>
        <h2 className="mt-1 text-2xl font-bold text-foreground">{latest?.title || "Improvement mission completed"}</h2>
        <div className="mt-6">
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
        <h2 className="text-2xl font-semibold text-foreground">
          {analysisPending
            ? "Preparing your practice plan"
            : hasCompletedEvidence
              ? "No verified weakness yet"
              : isTechnical ? "Build your technical practice plan" : "Build your interview practice plan"}
        </h2>
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

function missionPathTitle(title: string, mode: ImproveMode) {
  const trimmed = String(title || "").trim()
  if (trimmed === "Improve Coding Problem Solving" || trimmed.startsWith("Fix ")) {
    const skill = trimmed.startsWith("Fix ") ? trimmed.slice(4) : "Technical"
    return `Plan and test ${skill.toLowerCase()} solutions before coding`
  }
  if (trimmed === "Explain Projects Clearly") return "Explain projects with decisions, ownership, and results"
  if (trimmed === "Explain InterAI Convincingly") return "Explain InterAI with architecture, decisions, and results"
  if (trimmed === "Defend Resume Claims") return "Support every resume claim with concrete evidence"
  if (trimmed === "Improve Communication and Conciseness") return "Answer directly, then support the answer with evidence"
  if (trimmed.startsWith("Strengthen ")) {
    return `Give a direct answer about ${trimmed.slice("Strengthen ".length).toLowerCase()}, then add evidence`
  }
  return trimmed || (mode === "technical"
    ? "Plan and test the solution before coding"
    : "Answer directly, then support the answer with evidence")
}

function roadmapDisplayTitle(node: ImproveRoadmapNode, mode: ImproveMode) {
  const title = String(node.title || "").toLowerCase()
  if (node.activity_type === "baseline") {
    return mode === "technical"
      ? "The main failure in your previous solution has been identified"
      : "Your weakest answer from the last round has been identified"
  }
  if (node.activity_type === "compare_answers") {
    return "Study the stronger example, then write how you will use its structure"
  }
  if (node.activity_type === "arrange_blocks") {
    return "Place the direct answer first, then context, proof, and result"
  }
  if (node.activity_type === "guided_spoken_response") {
    return mode === "technical"
      ? "State the algorithm, data structure, complexity, and edge cases before coding"
      : "Explain the repaired answer aloud in 60 seconds"
  }
  if (node.activity_type === "unseen_checkpoint") {
    return mode === "technical"
      ? "Solve a related problem without hints and state its complexity"
      : "Answer a related question without hints using the same structure"
  }
  if (node.activity_type === "rewrite_answer") {
    if (title.includes("went wrong")) return "Explain your approach, why it failed, and what you will change"
    if (title.includes("edge-case")) return "List the exact edge cases and expected outputs before submitting"
    if (title.includes("decision before")) return "Write the requirement, your decision, and the expected result before retrying"
    if (title.includes("retry")) return "Rewrite the weak answer with one decision and one measurable result"
    if (mode === "technical") return "Write the failed approach, the cause, and the corrected approach"
    return "Write a 4-part answer: direct point, decision, proof, and result"
  }
  return node.title
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
  const roadmapRef = useRef<HTMLOListElement>(null)
  const roadmapAnimationKey = nodes.map((node) => node.roadmap_node_id).join("|")

  useEffect(() => {
    const roadmap = roadmapRef.current
    if (!roadmap) return
    const steps = Array.from(roadmap.querySelectorAll<HTMLElement>("[data-roadmap-step]"))
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches
    if (reduceMotion || !("IntersectionObserver" in window)) {
      steps.forEach((step) => { step.dataset.revealed = "true" })
      return
    }

    roadmap.dataset.motionReady = "true"
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return
        const step = entry.target as HTMLElement
        step.dataset.revealed = "true"
        observer.unobserve(step)
      })
    }, { threshold: 0.24, rootMargin: "0px 0px -8% 0px" })

    steps.forEach((step) => observer.observe(step))
    return () => observer.disconnect()
  }, [mission.mission_id, roadmapAnimationKey])

  return (
    <ol ref={roadmapRef} className="improve-roadmap relative mx-auto mt-3 max-w-5xl">
      {nodes.map((node, index) => (
        <RoadmapNode
          key={node.roadmap_node_id}
          node={node}
          index={index}
          mode={mission.mode === "technical" ? "technical" : "interview"}
          isCurrent={node.roadmap_node_id === currentNodeId}
          hasActiveSession={Boolean(
            mission.active_attempt_session?.roadmap_node_id === node.roadmap_node_id &&
            mission.active_attempt_session?.exercise_id === node.exercise_id
          )}
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
  const contentOnLeft = index % 2 === 1
  return (
    <li data-roadmap-step data-side={contentOnLeft ? "left" : "right"} className="relative flex min-h-[clamp(300px,46vh,420px)] items-center md:grid md:grid-cols-[minmax(0,1fr)_96px_minmax(0,1fr)] md:gap-7">
      <span aria-hidden="true" className="improve-roadmap-line absolute bottom-0 left-[2.45rem] top-0 w-1 rounded-full bg-border/65 md:left-1/2 md:-translate-x-1/2" />
      <span
        aria-hidden="true"
        className={cn(
          "pointer-events-none absolute hidden text-[7rem] font-black leading-none text-primary/20 dark:text-primary/30 md:block",
          contentOnLeft ? "right-8" : "left-8",
        )}
      >
        {String(index + 1).padStart(2, "0")}
      </span>
      <div className={cn(
        "improve-roadmap-content relative z-10 ml-28 w-full rounded-2xl px-5 py-5 md:ml-0 md:px-6",
        contentOnLeft ? "md:col-start-1 md:row-start-1 md:text-right" : "md:col-start-3 md:row-start-1",
        ready && "border border-primary/25 bg-card shadow-[0_16px_40px_rgba(79,70,229,0.10)]",
      )}>
        <div className={cn("flex flex-wrap items-center gap-2 text-xs font-semibold", contentOnLeft && "md:justify-end")}>
          <span className="rounded-full bg-secondary px-2.5 py-1 text-muted-foreground">Step {index + 1}</span>
          <span className={cn(
            "rounded-full px-2.5 py-1",
            verified ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300" : ready ? "bg-primary/10 text-primary" : "bg-secondary text-muted-foreground",
          )}>
            {verified ? "Verified" : ready ? "Ready now" : "Locked"}
          </span>
        </div>
        <h3 className="mt-4 text-xl font-bold tracking-tight text-foreground md:text-2xl">
            {technical ? "Use this method in your next Technical Round" : "Use this answer structure in your next Interview Round"}
        </h3>
        {ready && (
          <Button className="mt-6 rounded-xl px-5 shadow-[0_4px_0_rgba(55,48,163,0.65)]" onClick={onVerify}>
            <Play className="h-4 w-4" />
            {technical ? "Start Technical Round" : "Start Interview Round"}
          </Button>
        )}
      </div>
      <div className={cn(
        "improve-roadmap-marker absolute left-0 top-1/2 z-20 flex h-20 w-20 -translate-y-1/2 items-center justify-center rounded-full border-4 border-card transition-transform md:relative md:left-auto md:top-auto md:col-start-2 md:row-start-1 md:mx-auto md:translate-y-0",
        verified ? "bg-emerald-500 text-white shadow-[0_7px_0_#047857]" :
          ready ? "bg-primary text-primary-foreground shadow-[0_7px_0_#3730a3] ring-4 ring-primary/15" :
            "bg-secondary text-muted-foreground shadow-[0_7px_0_rgba(100,116,139,0.28)]",
      )}>
        {verified ? <BadgeCheck className="h-7 w-7" /> : ready ? <Play className="ml-1 h-7 w-7" /> : <Lock className="h-6 w-6" />}
      </div>
    </li>
  )
}

function recommendedResource(node: ImproveRoadmapNode): { title: string; url: string } | null {
  const prompt = getActivityPrompt(node)
  const configured = prompt.recommended_resource
  if (
    configured &&
    typeof configured === "object" &&
    typeof configured.title === "string" &&
    typeof configured.url === "string" &&
    /^https:\/\//i.test(configured.url)
  ) {
    return { title: configured.title, url: configured.url }
  }
  return null
}

function RoadmapNode({
  node,
  index,
  mode,
  isCurrent,
  hasActiveSession,
  onInspect,
}: {
  node: ImproveRoadmapNode
  index: number
  mode: ImproveMode
  isCurrent: boolean
  hasActiveSession: boolean
  onInspect: () => void
}) {
  const locked = node.availability_status === "locked" || node.availability_status === "blocked"
  const verified = node.mastery_status === "verified"
  const heldOutPassed = node.mastery_status === "held_out_passed"
  const needsReinforcement = node.mastery_status === "needs_reinforcement"
  const passed = node.result_status === "passed" || node.result_status === "strong_pass"
  const resource = recommendedResource(node)
  const contentOnLeft = index % 2 === 1
  const displayTitle = roadmapDisplayTitle(node, mode)
  const icon = locked ? (
    <Lock className="h-6 w-6" />
  ) : verified || heldOutPassed ? (
    <BadgeCheck className="h-7 w-7" />
  ) : needsReinforcement ? (
    <AlertTriangle className="h-7 w-7" />
  ) : passed ? (
    <Check className="h-7 w-7" />
  ) : isCurrent ? (
    <Play className="ml-1 h-7 w-7" />
  ) : (
    <Circle className="h-6 w-6" />
  )

  return (
    <li data-roadmap-step data-side={contentOnLeft ? "left" : "right"} className="relative flex min-h-[clamp(300px,46vh,420px)] items-center md:grid md:grid-cols-[minmax(0,1fr)_96px_minmax(0,1fr)] md:gap-7">
      <span
        aria-hidden="true"
        className={cn(
          "improve-roadmap-line absolute bottom-0 left-[2.45rem] top-0 w-1 rounded-full md:left-1/2 md:-translate-x-1/2",
          verified || heldOutPassed || passed ? "bg-emerald-500/45" : isCurrent ? "bg-gradient-to-b from-primary/55 to-border/65" : "bg-border/65",
        )}
      />
      <span
        aria-hidden="true"
        className={cn(
          "pointer-events-none absolute hidden text-[7rem] font-black leading-none text-primary/20 dark:text-primary/30 md:block",
          contentOnLeft ? "right-8" : "left-8",
        )}
      >
        {String(index + 1).padStart(2, "0")}
      </span>
      <div className={cn(
        "improve-roadmap-content relative z-10 ml-28 w-full rounded-2xl px-5 py-5 md:ml-0 md:px-6",
        contentOnLeft ? "md:col-start-1 md:row-start-1 md:text-right" : "md:col-start-3 md:row-start-1",
        isCurrent && "border border-primary/25 bg-card shadow-[0_16px_40px_rgba(79,70,229,0.10)]",
        locked && "opacity-65",
      )}>
        <div className={cn("flex flex-wrap items-center gap-2 text-xs font-semibold", contentOnLeft && "md:justify-end")}>
          <span className="rounded-full bg-secondary px-2.5 py-1 text-muted-foreground">Step {index + 1}</span>
          <span className={cn(
            "rounded-full px-2.5 py-1",
            verified || heldOutPassed || passed ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300" :
              needsReinforcement ? "bg-amber-500/10 text-amber-700 dark:text-amber-300" :
                isCurrent ? "bg-primary/10 text-primary" : "bg-secondary text-muted-foreground",
          )}>
            {nodeStateLabel(node)}
          </span>
          {node.estimated_minutes > 0 && (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-secondary px-2.5 py-1 text-muted-foreground">
              <Clock className="h-3.5 w-3.5" />
              {node.estimated_minutes} min
            </span>
          )}
        </div>
        <h3 className="mt-4 text-xl font-bold tracking-tight text-foreground md:text-2xl">{displayTitle}</h3>
        {(resource || (isCurrent && node.exercise_id)) && (
          <div className={cn("mt-6 flex flex-col gap-3 sm:flex-row sm:items-center", contentOnLeft && "md:justify-end")}>
            {isCurrent && node.exercise_id && (
              <Button className="rounded-xl px-5 shadow-[0_4px_0_rgba(55,48,163,0.65)]" onClick={onInspect}>
                <Play className="h-4 w-4" />
                {nextActionLabel(node, hasActiveSession)}
              </Button>
            )}
            {resource && (
              <a
                href={resource.url}
                target="_blank"
                rel="noreferrer"
                aria-label={resource.title}
                title={resource.title}
                className="inline-flex min-h-10 items-center gap-2 rounded-xl border border-border bg-background px-4 text-sm font-semibold text-foreground transition-colors hover:border-primary/40 hover:text-primary"
              >
                <ExternalLink className="h-4 w-4" />
                Open resource
              </a>
            )}
          </div>
        )}
      </div>
      <div className={cn(
        "improve-roadmap-marker absolute left-0 top-1/2 z-20 flex h-20 w-20 -translate-y-1/2 items-center justify-center rounded-full border-4 border-card transition-all md:relative md:left-auto md:top-auto md:col-start-2 md:row-start-1 md:mx-auto md:translate-y-0",
        verified || heldOutPassed || passed ? "bg-emerald-500 text-white shadow-[0_7px_0_#047857]" :
          needsReinforcement ? "bg-amber-500 text-white shadow-[0_7px_0_#b45309]" :
            isCurrent ? "bg-primary text-primary-foreground shadow-[0_7px_0_#3730a3] ring-4 ring-primary/15" :
              "bg-secondary text-muted-foreground shadow-[0_7px_0_rgba(100,116,139,0.28)]",
      )}>
        {icon}
      </div>
    </li>
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
  const lastSavedDraft = useRef(JSON.stringify(draftFromSession(activeSession, node)))
  const resumedSessionRef = useRef("")
  const hideHints = shouldHideHints(node)
  const conditions = getPassConditionLabels(node)
  const submittable = isDraftSubmittable(node, draft)
  const activityMode: ImproveMode = mission.mode === "technical" ? "technical" : "interview"

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
        lastSavedDraft.current = JSON.stringify(draft)
        setSaveError("")
      } catch (error) {
        setSaveError(error instanceof Error ? error.message : "This saved attempt can no longer be resumed.")
      }
    })()
  }, [activeSession, draft, node.exercise_id, phase])

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
    setSubmitError("")
    setSaveError("")
    setPhase("before")
  }

  const submitAttempt = async () => {
    if (!node.exercise_id || !attemptSession || !submittable || isSubmitting) return
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
            <h2 className="truncate text-lg font-semibold text-foreground">{roadmapDisplayTitle(node, activityMode)}</h2>
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
              isSubmitting={isSubmitting}
              submittable={submittable}
              onSubmit={submitAttempt}
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
        <p className="text-base leading-7 text-foreground">{prompt.question || node.description}</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <InfoBlock label="What good looks like" value={node.expected_result || "Complete the instruction above with one concrete example."} />
        <InfoBlock label="Time" value={`${node.estimated_minutes} minutes`} />
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

function InfoBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-background/55 p-4">
      <div className="mb-2 text-xs font-semibold uppercase tracking-[0.08em] text-primary">{label}</div>
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
  isSubmitting,
  submittable,
  onSubmit,
}: {
  node: ImproveRoadmapNode
  draft: ActivityDraft
  setDraft: (draft: ActivityDraft) => void
  saveError: string
  submitError: string
  isSubmitting: boolean
  submittable: boolean
  onSubmit: () => void
}) {
  const prompt = getActivityPrompt(node)
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-5">
      <h3 className="text-2xl font-semibold text-foreground">{prompt.question || prompt.prompt || node.title}</h3>
      <ActivityBody node={node} draft={draft} setDraft={setDraft} />
      {saveError && <ErrorBanner message={`Draft save issue: ${saveError}`} />}
      {submitError && <ErrorBanner message={submitError} />}
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
  if (node.activity_type === "guided_spoken_response") return <SpokenResponseActivity draft={draft} setDraft={setDraft} />
  return <CheckpointActivity draft={draft} setDraft={setDraft} />
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
  const correctOption = String(prompt.correct_option || answers.at(-1)?.id || "")
  const strongerAnswer = answers.find((answer: any) => String(answer.id) === correctOption)

  useEffect(() => {
    if (!correctOption || draft.selectedOption === correctOption) return
    setDraft({ ...draft, selectedOption: correctOption })
  }, [correctOption, draft, setDraft])

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
      {strongerAnswer?.text && (
        <div className="border-y border-border/70 py-4">
          <p className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">Example answer shape</p>
          <p className="mt-2 text-sm leading-6 text-foreground">{String(strongerAnswer.text)}</p>
        </div>
      )}
      <div>
        <label className="text-sm font-semibold text-foreground" htmlFor="compare-reason">Explain how you will apply this structure</label>
        <Textarea
          id="compare-reason"
          className="mt-2 min-h-36"
          value={draft.reason || ""}
          onChange={(event) => setDraft({ ...draft, reason: event.target.value })}
          placeholder="Write what your direct answer, evidence, ownership, and result should contain."
        />
      </div>
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
  draft,
  setDraft,
}: {
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
  draft,
  setDraft,
}: {
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
