import { describe, expect, it } from "vitest"
import {
  chooseInitialPerformanceTab,
  hasPerformanceModeData,
  performanceStateNotice,
} from "./performance-state"

describe("performance state", () => {
  it("distinguishes an empty mode from a mode with saved data", () => {
    expect(hasPerformanceModeData(
      { has_data: false, score_state: "missing" },
    )).toBe(false)
    expect(hasPerformanceModeData(
      { has_data: true, has_evidence: true, score_state: "run_only" },
    )).toBe(true)
  })

  it("opens Technical Round when it is the only mode with an official score", () => {
    expect(chooseInitialPerformanceTab(
      { score_state: "insufficient", has_evidence: true },
      { score_state: "ready", has_official_score: true, has_evidence: true },
    )).toBe("coding")
  })

  it("opens the only mode with saved evidence", () => {
    expect(chooseInitialPerformanceTab(
      { score_state: "missing", has_evidence: false },
      { score_state: "run_only", has_evidence: true },
    )).toBe("coding")
  })

  it("explains why a run is visible without an official score", () => {
    expect(performanceStateNotice(
      { score_state: "run_only", has_evidence: true },
      "coding",
    )).toContain("Final Submit")
  })

  it("distinguishes saved-but-insufficient evidence from missing evidence", () => {
    expect(performanceStateNotice(
      { score_state: "insufficient", has_evidence: true },
      "interview",
    )).toContain("Evidence was saved")
    expect(performanceStateNotice(
      { score_state: "insufficient", has_evidence: false },
      "interview",
    )).toContain("did not capture enough")
  })

  it("keeps historical official scores visible when the latest attempt is insufficient", () => {
    expect(performanceStateNotice(
      {
        score_state: "insufficient",
        has_evidence: false,
        has_official_score: true,
      },
      "interview",
    )).toContain("shown separately")
  })
})
