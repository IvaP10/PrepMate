import type {
  ActiveImproveMission,
  ExerciseAttemptResult,
  ImproveRoadmapNode,
  ImprovementHistory,
} from "@/lib/api"

export type ActivityDraft = {
  selectedOption?: string
  reason?: string
  blockOrder?: string[]
  rewrite?: string
  transcript?: string
  answer?: string
}

export type ActivityPayload = {
  mission_id: string
  roadmap_node_id: string
  submitted_answer?: string
  submitted_payload: Record<string, unknown>
  idempotency_key: string
  attempt_session_id: string
}

export function getCurrentRoadmapNode(mission: ActiveImproveMission | null | undefined): ImproveRoadmapNode | null {
  const nodes = mission?.roadmap || []
  return (
    nodes.find((node) => node.availability_status === "current" && node.result_status !== "passed" && node.result_status !== "strong_pass") ||
    null
  )
}

export function getActivityPrompt(node: ImproveRoadmapNode | null | undefined): Record<string, any> {
  return (node?.activity && typeof node.activity === "object" ? node.activity : {}) as Record<string, any>
}

export function getPassConditionLabels(node: ImproveRoadmapNode | null | undefined): string[] {
  const conditions = getActivityPrompt(node).pass_conditions
  if (!Array.isArray(conditions)) return []
  return conditions
    .map((condition) => {
      if (typeof condition === "string") return condition
      if (condition && typeof condition === "object") return String(condition.label || condition.text || condition.id || "")
      return ""
    })
    .filter(Boolean)
}

export function shouldHideHints(node: ImproveRoadmapNode | null | undefined): boolean {
  const prompt = getActivityPrompt(node)
  return Boolean(prompt.hide_hints || node?.activity_type === "unseen_checkpoint" || node?.activity_type === "checkpoint")
}

export function estimatedRemainingMinutes(mission: ActiveImproveMission | null | undefined): number {
  return (mission?.roadmap || [])
    .filter((node) => node.result_status !== "passed" && node.result_status !== "strong_pass")
    .reduce((total, node) => total + Number(node.estimated_minutes || 0), 0)
}

export function completedRoadmapSteps(mission: ActiveImproveMission | null | undefined): number {
  return (mission?.roadmap || []).filter(
    (node) => node.result_status === "passed" || node.result_status === "strong_pass" || node.mastery_status === "verified",
  ).length
}

export function buildActivityAttemptPayload(
  node: ImproveRoadmapNode,
  draft: ActivityDraft,
  missionId: string,
  idempotencyKey: string,
  attemptSessionId: string,
): ActivityPayload {
  const submitted_payload: Record<string, unknown> = {
    idempotency_key: idempotencyKey,
    mission_id: missionId,
    roadmap_node_id: node.roadmap_node_id,
  }
  let submitted_answer = ""

  if (node.activity_type === "compare_answers") {
    submitted_payload.selected_option = draft.selectedOption || ""
    submitted_payload.reason = draft.reason || ""
    submitted_answer = draft.reason || ""
  } else if (node.activity_type === "arrange_blocks") {
    submitted_payload.block_order = draft.blockOrder || []
    submitted_answer = (draft.blockOrder || []).join(" -> ")
  } else if (node.activity_type === "rewrite_answer") {
    submitted_payload.rewrite = draft.rewrite || ""
    submitted_answer = draft.rewrite || ""
  } else if (node.activity_type === "guided_spoken_response") {
    submitted_payload.transcript = draft.transcript || ""
    submitted_answer = draft.transcript || ""
  } else {
    submitted_payload.transcript = draft.transcript || draft.answer || ""
    submitted_payload.answer = draft.answer || draft.transcript || ""
    submitted_answer = draft.answer || draft.transcript || ""
  }

  submitted_payload.attempt_session_id = attemptSessionId

  return {
    mission_id: missionId,
    roadmap_node_id: node.roadmap_node_id,
    submitted_answer,
    submitted_payload,
    idempotency_key: idempotencyKey,
    attempt_session_id: attemptSessionId,
  }
}

export function isDraftSubmittable(node: ImproveRoadmapNode | null | undefined, draft: ActivityDraft): boolean {
  if (!node?.exercise_id || node.availability_status !== "current") return false
  if (node.activity_type === "compare_answers") return Boolean(draft.selectedOption && (draft.reason || "").trim().length >= 6)
  if (node.activity_type === "arrange_blocks") {
    const blocks = getActivityPrompt(node).blocks
    return Array.isArray(draft.blockOrder) && Array.isArray(blocks) && draft.blockOrder.length === blocks.length
  }
  if (node.activity_type === "rewrite_answer") return (draft.rewrite || "").trim().split(/\s+/).length >= 8
  if (node.activity_type === "guided_spoken_response") return (draft.transcript || "").trim().split(/\s+/).length >= 10
  return ((draft.answer || draft.transcript || "").trim().split(/\s+/).length >= 10)
}

export function nodeStateLabel(node: ImproveRoadmapNode): string {
  if (node.availability_status === "locked") return "Locked"
  if (node.availability_status === "blocked") return "Recovery required"
  if (node.mastery_status === "verified") return "Verified"
  if (node.mastery_status === "held_out_passed") return "Checkpoint passed · awaiting interview"
  if (node.mastery_status === "needs_reinforcement") return "Needs reinforcement"
  if (node.result_status === "strong_pass") return "Strong pass"
  if (node.result_status === "passed") return "Passed"
  if (node.result_status === "partial_pass") return "Partial pass"
  if (node.attempt_status === "in_progress") return "Practising"
  if (node.availability_status === "current") return "Current"
  return "Learning"
}

export function nextActionLabel(node: ImproveRoadmapNode | null | undefined, hasActiveSession: boolean): string {
  if (!node) return "Start activity"
  if (hasActiveSession) return "Continue activity"
  if (node.activity_type === "unseen_checkpoint") return "Continue to checkpoint"
  if (node.mastery_status === "needs_reinforcement") return "Continue to recovery"
  return "Continue"
}

export function formatAttemptResult(result: ExerciseAttemptResult | null): {
  headline: string
  correction: string
  passed: string[]
  failed: string[]
} {
  if (!result) {
    return { headline: "", correction: "", passed: [], failed: [] }
  }
  const passed = result.passed_conditions || []
  const failed = result.failed_conditions || []
  return {
    headline: `${passed.length} of ${(result.condition_results || []).length || passed.length + failed.length} conditions met`,
    correction: result.specific_feedback || result.feedback?.specific_feedback || failed[0] || "Continue to the next variation.",
    passed,
    failed,
  }
}

export function historyHasRealData(history: ImprovementHistory | null | undefined): boolean {
  return Boolean(history?.has_history && (
    (history.skills || []).length ||
    (history.completed_missions || []).length ||
    (history.recent_attempts || []).length
  ))
}
