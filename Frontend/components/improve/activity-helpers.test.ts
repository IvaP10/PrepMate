import { describe, expect, it } from "vitest"

import {
  buildActivityAttemptPayload,
  getCurrentRoadmapNode,
  isDraftSubmittable,
  nodeStateLabel,
} from "./activity-helpers"
import { buildImproveUrl, readImproveTarget } from "../../lib/improve-navigation"

const node = (overrides: Record<string, unknown> = {}) => ({
  roadmap_node_id: "node-1",
  mission_skill_id: "skill-1",
  exercise_id: "exercise-1",
  order_index: 1,
  title: "Rewrite",
  activity_type: "rewrite_answer",
  availability_status: "current",
  attempt_status: "draft",
  result_status: "not_attempted",
  mastery_status: "practising",
  estimated_minutes: 4,
  activity: {},
  ...overrides,
}) as any

describe("Improve activity contracts", () => {
  it("selects only the unfinished server-owned current node", () => {
    const mission = {
      roadmap: [
        node({ roadmap_node_id: "blocked", availability_status: "blocked" }),
        node({ roadmap_node_id: "done", availability_status: "completed", result_status: "passed" }),
        node({ roadmap_node_id: "current" }),
      ],
    } as any

    expect(getCurrentRoadmapNode(mission)?.roadmap_node_id).toBe("current")
  })

  it("will not submit a blocked or completed activity", () => {
    const rewrite = { rewrite: "A complete valid rewrite with enough words here." }
    expect(isDraftSubmittable(node({ availability_status: "blocked" }), rewrite)).toBe(false)
    expect(isDraftSubmittable(node({ availability_status: "completed" }), rewrite)).toBe(false)
    expect(isDraftSubmittable(node(), rewrite)).toBe(true)
  })

  it("builds only answer evidence plus idempotency/session identifiers", () => {
    expect(buildActivityAttemptPayload(
      node(),
      { rewrite: "I owned the API because latency mattered, reducing failures by 20%." },
      "mission-123",
      "attempt-123",
      "session-123",
    )).toEqual({
      mission_id: "mission-123",
      roadmap_node_id: "node-1",
      submitted_answer: "I owned the API because latency mattered, reducing failures by 20%.",
      submitted_payload: {
        rewrite: "I owned the API because latency mattered, reducing failures by 20%.",
        idempotency_key: "attempt-123",
        attempt_session_id: "session-123",
        mission_id: "mission-123",
        roadmap_node_id: "node-1",
      },
      idempotency_key: "attempt-123",
      attempt_session_id: "session-123",
    })
  })

  it("labels held-out proof without claiming later-interview verification", () => {
    expect(nodeStateLabel(node({ mastery_status: "held_out_passed", result_status: "passed", availability_status: "completed" })))
      .toBe("Checkpoint passed · awaiting interview")
  })

  it("round-trips exact mission, node, and exercise URL identifiers", () => {
    const url = buildImproveUrl({
      mode: "technical",
      mission_id: "mission-1",
      roadmap_node_id: "node-1",
      exercise_id: "exercise-1",
    })
    const params = new URL(url, "https://inter.local").searchParams

    expect(readImproveTarget(params)).toEqual({
      mode: "technical",
      mission_id: "mission-1",
      roadmap_node_id: "node-1",
      exercise_id: "exercise-1",
    })
  })
})
